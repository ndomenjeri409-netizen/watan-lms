import { describe, expect, it } from 'vitest'
import { breadcrumbsForPath, navFor } from './navigation'
import type { Profile, Role } from '../features/me/roles'

const profileFor = (role: Role): Profile => {
  const global = ['SUPER_ADMIN', 'ADMIN', 'DIRECTOR', 'AUDITOR'].includes(role)
  return {
    id: 'test-user',
    email: 'test@example.com',
    display_name: 'Test User',
    phone_number: '',
    role,
    assignments: [{ role, unit: global ? null : { id: 'unit-a', code: 'WTA', name: 'Travel' } }],
    is_global_read: global,
    awaiting_approval: false,
    is_active: true,
  }
}

const labelsFor = (role: Role) => navFor(profileFor(role)).flatMap((section) => section.items.map((item) => item.label))

describe('role-based navigation', () => {
  it('builds breadcrumbs from dashboard and navigation sections', () => {
    expect(breadcrumbsForPath('/app/departments', 'Departments')).toEqual([
      { label: 'Dashboard', to: '/app' },
      { label: 'Academics' },
      { label: 'Departments' },
    ])
    expect(breadcrumbsForPath('/app', 'Dashboard')).toEqual([{ label: 'Dashboard' }])
    expect(breadcrumbsForPath('/app/students/student-id', 'Student profile').map(({ label }) => label)).toEqual([
      'Dashboard', 'People', 'Students', 'Student profile',
    ])
  })

  it('shows only profile and awaiting-approval state for unassigned accounts', () => {
    expect(navFor(undefined)).toEqual([])
    expect(navFor({
      ...profileFor('ADMIN'),
      role: null,
      assignments: [],
      is_global_read: false,
      awaiting_approval: true,
    })).toEqual([])
  })

  it('shows the permitted links for every role', () => {
    expect(labelsFor('SUPER_ADMIN')).toEqual([
      'Dashboard', 'My profile', 'Students', 'Admissions', 'Users', 'Departments', 'Course catalog',
      'Manage courses', 'Timetable & attendance', 'Assessments & grades', 'Finance',
    ])
    expect(labelsFor('ADMIN')).toEqual([
      'Dashboard', 'My profile', 'Students', 'Admissions', 'Users', 'Departments', 'Course catalog',
      'Manage courses', 'Timetable & attendance', 'Assessments & grades', 'Finance',
    ])
    expect(labelsFor('DIRECTOR')).toEqual([
      'Dashboard', 'My profile', 'Students', 'Departments', 'Course catalog', 'Timetable & attendance', 'Assessments & grades', 'Finance',
    ])
    expect(labelsFor('HOD')).toEqual([
      'Dashboard', 'My profile', 'Students', 'Admissions', 'Departments', 'Course catalog',
      'Manage courses', 'Timetable & attendance', 'Assessments & grades',
    ])
    expect(labelsFor('TEACHER')).toEqual([
      'Dashboard', 'My profile', 'Students', 'Course catalog', 'Manage courses', 'Timetable & attendance', 'Assessments & grades',
    ])
    expect(labelsFor('BURSAR')).toEqual(['Dashboard', 'My profile', 'Students', 'Course catalog', 'Finance'])
    expect(labelsFor('CASHIER')).toEqual(['Dashboard', 'My profile', 'Students', 'Course catalog', 'Finance'])
    expect(labelsFor('STUDENT')).toEqual([
      'Dashboard', 'My profile', 'Course catalog', 'Timetable & attendance', 'Assessments & grades', 'Finance',
    ])
  })

  it('does not expose administrator links to students and keeps directors out of course management', () => {
    const students = labelsFor('STUDENT')
    expect(students).not.toContain('Users')
    expect(students).not.toContain('Audit log')
    expect(labelsFor('DIRECTOR')).not.toContain('Manage courses')
  })

  it('uses assignments rather than the profile summary role for access', () => {
    const mixedProfile: Profile = {
      ...profileFor('ADMIN'),
      role: 'ADMIN',
      assignments: [{ role: 'HOD', unit: { id: 'unit-a', code: 'WTA', name: 'Travel' } }],
      is_global_read: false,
    }

    const labels = navFor(mixedProfile).flatMap((section) => section.items.map((item) => item.label))
    expect(labels).toContain('Admissions')
    expect(labels).not.toContain('Users')
  })
})
