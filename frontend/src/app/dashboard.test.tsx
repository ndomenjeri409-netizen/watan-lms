import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { components } from '../api/schema'
import { DashboardView } from './Dashboard'
import { dashboardFor } from './dashboard-config'
import type { Role } from '../features/me/roles'

const profile: components['schemas']['Me'] = {
  id: 'preview',
  email: 'admin@example.com',
  display_name: 'Admin Example',
  phone_number: '',
  role: 'ADMIN',
  assignments: [{ role: 'ADMIN', unit: null }],
  is_global_read: true,
  awaiting_approval: false,
  is_active: true,
}

function renderDashboard(props: Partial<Parameters<typeof DashboardView>[0]> = {}) {
  return render(
    <MemoryRouter>
      <DashboardView profile={profile} role="ADMIN" {...props} />
    </MemoryRouter>,
  )
}

describe('role-aware dashboard', () => {
  it('configures only metrics supported by each role and valid quick-action destinations', () => {
    const roles: Role[] = [
      'SUPER_ADMIN', 'ADMIN', 'DIRECTOR', 'AUDITOR', 'UNIT_MANAGER', 'HOD', 'TEACHER',
      'BURSAR', 'CASHIER', 'STUDENT',
    ]

    for (const role of roles) {
      const dashboard = dashboardFor(role)
      expect(new Set(dashboard.stats.map(({ key }) => key)).size).toBe(dashboard.stats.length)
      expect(dashboard.actions.length).toBeGreaterThan(0)
      expect(dashboard.actions.every(({ to }) => to.startsWith('/app/') || to === '/courses')).toBe(true)
    }

    expect(dashboardFor('STUDENT').stats).toEqual([{ key: 'courses', label: 'Your active courses' }])
    expect(dashboardFor('BURSAR').stats).toEqual([])
  })

  it('renders only metrics with numeric values, including zero', () => {
    renderDashboard({ overview: { departments: 0, programs: 3 } })

    expect(screen.getByText('Departments')).toBeInTheDocument()
    expect(screen.getByText('0')).toBeInTheDocument()
    expect(screen.getByText('Programs')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.queryByText('Published courses')).not.toBeInTheDocument()
    expect(screen.queryByText(/Available soon/i)).not.toBeInTheDocument()
  })

  it('skips the metric row when no values are available', () => {
    renderDashboard({ overview: {} })
    expect(screen.queryByRole('region', { name: /key metrics/i })).not.toBeInTheDocument()
  })

  it('computes admin setup progress from available counts', () => {
    renderDashboard({
      overview: { departments: 1, programs: 1, courses: 2, staff: 3, students: 10 },
    })

    expect(screen.getByText('4 of 4 available setup steps complete')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Getting started progress' })).toHaveAttribute('aria-valuenow', '100')
    expect(screen.getByText('Set up fee structures')).toBeInTheDocument()
    expect(screen.getByText('(not available yet)')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Manage users/ })).toHaveAttribute('href', '/app/users')
  })

  it('shows teacher guidance for an empty schedule and grading queue', () => {
    renderDashboard({
      role: 'TEACHER',
      profile: {
        ...profile,
        role: 'TEACHER',
        assignments: [{ role: 'TEACHER', unit: { id: 'unit-a', code: 'WTA', name: 'Travel' } }],
        is_global_read: false,
      },
    })

    expect(screen.getByText('No classes scheduled today')).toBeInTheDocument()
    expect(screen.getByText('No submissions awaiting grading')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open timetable' })).toHaveAttribute('href', '/app/timetable')
    expect(screen.getByRole('link', { name: 'Open assessments' })).toHaveAttribute('href', '/app/assessments')
  })
})
