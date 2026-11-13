import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { components } from '../api/schema'
import { TooltipProvider } from '../components/ui'
import { AppShell } from './AppShell'

vi.mock('../api/client', () => ({
  api: {
    GET: vi.fn(async () => ({
      data: {
        count: 1,
        next: null,
        previous: null,
        results: [
          {
            id: 'unit-a',
            code: 'WTA',
            name: 'Travel',
            kind: 'TRAINING',
            currency: 'KES',
            modules: {},
            is_active: true,
          },
          {
            id: 'unit-b',
            code: 'WTI',
            name: 'Institute',
            kind: 'ACADEMIC',
            currency: 'KES',
            modules: {},
            is_active: true,
          },
        ],
      },
      error: undefined,
    })),
  },
}))

const profile: components['schemas']['Me'] = {
  id: 'shell-user',
  email: 'admin@example.com',
  display_name: 'Admin Example',
  phone_number: '',
  role: 'ADMIN',
  assignments: [{ role: 'ADMIN', unit: null }],
  is_global_read: true,
  awaiting_approval: false,
  is_active: true,
}

function renderShell(path = '/app/students', currentProfile = profile) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route
              path="/app/*"
              element={(
                <AppShell
                  profile={currentProfile}
                  firebaseUser={{ displayName: 'Admin Example', photoURL: null }}
                  logout={vi.fn(async () => undefined)}
                >
                  <h1>Page content</h1>
                </AppShell>
              )}
            />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

describe('AppShell', () => {
  it('renders grouped role navigation and marks the active route', () => {
    renderShell()

    const navigation = screen.getByRole('navigation', { name: 'Main navigation' })
    expect(navigation).toHaveClass('sidebar-scroll')
    expect(document.querySelectorAll('.sidebar-scroll')).toHaveLength(1)
    expect(navigation.parentElement?.firstElementChild).not.toHaveClass('sidebar-scroll')
    expect(navigation.parentElement?.lastElementChild).not.toHaveClass('sidebar-scroll')
    expect(navigation).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'People' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Academics' })).toBeInTheDocument()
    const activeLink = screen.getByRole('link', { name: 'Students' })
    expect(activeLink).toHaveAttribute('aria-current', 'page')
    expect(activeLink).toHaveClass(
      'flex',
      'items-center',
      'gap-3',
      'rounded-md',
      'px-3',
      'border-l-[3px]',
      'aria-[current=page]:bg-sidebar-active',
      'aria-[current=page]:text-white',
      'aria-[current=page]:border-primary',
    )
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveClass('hover:bg-white/6')
    expect(screen.getAllByText('Admin').length).toBeGreaterThan(0)
    expect(screen.queryByRole('link', { name: 'Audit log' })).not.toBeInTheDocument()
    const skipLink = screen.getByRole('link', { name: 'Skip to content' })
    expect(skipLink).toHaveAttribute('href', '#main')
    expect(skipLink).toHaveClass(
      'sr-only',
      'focus-visible:not-sr-only',
      'focus-visible:bg-primary',
      'focus-visible:text-primary-fg',
      'focus-visible:ring-2',
      'focus-visible:ring-ring',
    )
  })

  it('opens the mobile navigation drawer and closes it with Escape', async () => {
    renderShell()

    fireEvent.click(screen.getByRole('button', { name: 'Open navigation menu' }))
    const dialog = await screen.findByRole('dialog', { name: 'Watan LMS navigation' })
    expect(dialog).toBeInTheDocument()
    expect(within(dialog).getByRole('navigation', { name: 'Main navigation' })).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Watan LMS navigation' })).not.toBeInTheDocument())
  })

  it('opens the coming-soon search from the platform shortcut', () => {
    renderShell()

    expect(screen.getByText('Ctrl K')).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })

    expect(screen.getByRole('textbox', { name: 'Search' })).toHaveFocus()
    expect(screen.getByText('Search is coming soon')).toBeInTheDocument()
  })

  it('shows a dismissible profile completion notice when the name is blank', () => {
    renderShell('/app', { ...profile, display_name: '' })
    expect(screen.getByRole('link', { name: 'Add your name and phone number' })).toHaveAttribute('href', '/app/me#complete-profile')

    fireEvent.click(screen.getByRole('button', { name: 'Dismiss complete your profile notice' }))
    expect(screen.queryByText('Complete your profile.')).not.toBeInTheDocument()
  })

  it('lets group readers switch units and persists their selection', async () => {
    localStorage.removeItem('watan-lms-active-unit')
    renderShell()

    const switcher = await screen.findByRole('combobox', { name: 'Business unit' })
    expect(switcher).toHaveClass(
      'absolute',
      'inset-0',
      'opacity-0',
      'sm:h-10',
      'sm:appearance-none',
      'sm:rounded-md',
      'sm:bg-surface-2',
      'sm:border-line',
      'sm:text-fg',
      'sm:px-3',
    )
    expect(switcher.parentElement?.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
    expect(within(switcher).getByRole('option', { name: 'All units' })).toBeInTheDocument()
    expect(within(switcher).getByRole('option', { name: 'Travel' })).toBeInTheDocument()
    expect(within(switcher).getByRole('option', { name: 'Institute' })).toBeInTheDocument()
    fireEvent.change(switcher, { target: { value: 'unit-a' } })

    expect(localStorage.getItem('watan-lms-active-unit')).toBe('unit-a')
  })

  it('shows a badge instead of a switcher to single-unit users', async () => {
    renderShell('/app', {
      ...profile,
      role: 'UNIT_MANAGER',
      assignments: [{ role: 'UNIT_MANAGER', unit: { id: 'unit-a', code: 'WTA', name: 'Travel' } }],
      is_global_read: false,
    })

    expect(await screen.findByText('Travel')).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Business unit' })).not.toBeInTheDocument()
  })

  it('lets multi-unit managers switch only between their assignments', async () => {
    renderShell('/app', {
      ...profile,
      role: 'UNIT_MANAGER',
      assignments: [
        { role: 'UNIT_MANAGER', unit: { id: 'unit-a', code: 'WTA', name: 'Travel' } },
        { role: 'UNIT_MANAGER', unit: { id: 'unit-b', code: 'WTI', name: 'Institute' } },
      ],
      is_global_read: false,
    })

    const switcher = await screen.findByRole('combobox', { name: 'Business unit' })
    expect(within(switcher).getAllByRole('option')).toHaveLength(2)
    expect(within(switcher).queryByRole('option', { name: 'All units' })).not.toBeInTheDocument()
  })

  it.each(['AUDITOR', 'DIRECTOR', 'BURSAR'] as const)(
    '%s can select All units as a group-wide role',
    async (role) => {
      renderShell('/app', {
        ...profile,
        role,
        assignments: [{ role, unit: null }],
        is_global_read: true,
      })

      const switcher = await screen.findByRole('combobox', { name: 'Business unit' })
      expect(within(switcher).getByRole('option', { name: 'All units' })).toBeInTheDocument()
    },
  )
})
