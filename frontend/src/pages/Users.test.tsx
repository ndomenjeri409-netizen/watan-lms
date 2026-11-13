import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Profile } from '../features/me/roles'
import { UnitProvider } from '../features/units/UnitProvider'
import { ToastProvider } from '../components/ui'
import { Users } from './Users'

const apiMocks = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn(),
  DELETE: vi.fn(),
}))

vi.mock('../api/client', () => ({ api: apiMocks }))
vi.mock('../lib/firebase', () => ({ auth: { currentUser: null } }))

const profile: Profile = {
  id: 'admin',
  email: 'admin@example.test',
  display_name: 'Admin',
  phone_number: '',
  role: 'SUPER_ADMIN',
  assignments: [{ role: 'SUPER_ADMIN', unit: null }],
  is_global_read: true,
  awaiting_approval: false,
  is_active: true,
}

vi.mock('../features/me/useMe', () => ({ useMe: () => ({ data: profile }) }))

const unit = {
  id: 'unit-a',
  code: 'WTI',
  name: 'Watan Training Institute',
  kind: 'ACADEMIC',
  currency: 'KES',
  modules: {},
  is_active: true,
}
const department = {
  id: 'department-a',
  unit: { id: unit.id, code: unit.code, name: unit.name },
  name: 'Travel',
  code: 'TRV',
  program_count: 0,
  course_count: 0,
}
const pendingUser = {
  id: 'pending-user',
  email: 'pending@example.test',
  display_name: 'Pending user',
  role: null,
  is_active: true,
  department_ids: [],
  assignments: [],
  status: 'PENDING',
  created_at: '2026-01-01T00:00:00Z',
}
const adminUser = {
  id: 'admin',
  email: profile.email,
  display_name: profile.display_name,
  role: 'SUPER_ADMIN',
  is_active: true,
  department_ids: [],
  assignments: [{
    id: 'assignment-admin',
    role: 'SUPER_ADMIN',
    unit: null,
    is_active: true,
  }],
  status: 'ACTIVE',
  created_at: '2026-01-01T00:00:00Z',
}

function renderUsers() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter>
          <UnitProvider profile={profile}>
            <Users />
          </UnitProvider>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('Users page role assignment drawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.setItem('watan-lms-active-unit', unit.id)
    apiMocks.GET.mockImplementation(async (path: string) => ({
      data: {
        count: path === '/api/v1/users/' ? 2 : 1,
        next: null,
        previous: null,
        results: path === '/api/v1/units'
          ? [unit]
          : path === '/api/v1/departments/'
            ? [department]
            : [pendingUser, adminUser],
      },
      error: undefined,
    }))
    apiMocks.POST.mockResolvedValue({ data: pendingUser, error: undefined })
    apiMocks.DELETE.mockResolvedValue({ data: adminUser, error: undefined })
  })

  it('shows unit only for unit roles and submits the active unit selection', async () => {
    renderUsers()
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }))

    const drawer = await screen.findByRole('dialog', { name: 'Approve user' })
    const roleSelect = within(drawer).getByLabelText('Role')
    expect(within(drawer).queryByLabelText('Business unit')).not.toBeInTheDocument()

    fireEvent.change(roleSelect, { target: { value: 'TEACHER' } })
    const unitSelect = within(drawer).getByLabelText('Business unit')
    expect(unitSelect).toHaveValue(unit.id)

    fireEvent.change(roleSelect, { target: { value: 'HOD' } })
    expect(within(drawer).getByLabelText('Departments')).toBeInTheDocument()

    fireEvent.change(roleSelect, { target: { value: 'SUPER_ADMIN' } })
    expect(within(drawer).queryByLabelText('Business unit')).not.toBeInTheDocument()
    expect(within(drawer).queryByLabelText('Departments')).not.toBeInTheDocument()

    fireEvent.change(roleSelect, { target: { value: 'TEACHER' } })
    fireEvent.click(within(drawer).getByRole('button', { name: 'Approve user' }))

    await waitFor(() => {
      expect(apiMocks.POST).toHaveBeenCalledWith(
        '/api/v1/users/{id}/assignments/',
        expect.objectContaining({
          params: { path: { id: pendingUser.id } },
          body: { role: 'TEACHER', unit: unit.id },
        }),
      )
    })
  })

  it('renders server field errors instead of a generic request failure', async () => {
    apiMocks.POST.mockResolvedValue({
      error: {
        code: 'VALIDATION',
        message: 'Request failed.',
        fields: { unit: ['Select an active unit valid for this role.'] },
      },
    })
    renderUsers()
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }))

    const drawer = await screen.findByRole('dialog', { name: 'Approve user' })
    fireEvent.change(within(drawer).getByLabelText('Role'), { target: { value: 'TEACHER' } })
    fireEvent.click(within(drawer).getByRole('button', { name: 'Approve user' }))

    expect(await within(drawer).findByText('Select an active unit valid for this role.')).toBeInTheDocument()
    expect(within(drawer).queryByText('Request failed.')).not.toBeInTheDocument()
  })
})
