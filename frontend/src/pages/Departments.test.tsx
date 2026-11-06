import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../components/ui'
import { UnitProvider } from '../features/units/UnitProvider'
import type { Profile } from '../features/me/roles'
import { Departments } from './Departments'

const apiMocks = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn(),
  PATCH: vi.fn(),
  DELETE: vi.fn(),
}))

vi.mock('../api/client', () => ({ api: apiMocks }))
const profile: Profile = {
  id: 'admin',
  email: 'admin@example.com',
  display_name: 'Admin',
  phone_number: '',
  role: 'ADMIN',
  assignments: [{ role: 'ADMIN', unit: null }],
  is_global_read: true,
  awaiting_approval: false,
  is_active: true,
}

vi.mock('../features/me/useMe', () => ({ useMe: () => ({ data: profile }) }))

const emptyList = { count: 0, next: null, previous: null, results: [] }

function renderDepartments() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter>
          <UnitProvider profile={profile}>
            <Departments />
          </UnitProvider>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('Departments page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.GET.mockImplementation(async (path: string) => ({
      data: path === '/api/v1/units'
        ? { ...emptyList, results: [{ id: 'unit-a', code: 'WTA', name: 'Travel', kind: 'TRAINING', currency: 'KES', modules: {}, is_active: true }] }
        : emptyList,
      error: undefined,
    }))
    apiMocks.POST.mockResolvedValue({ data: { id: 'new', name: 'Travel', code: 'TRV' }, error: undefined })
  })

  it('opens the create drawer and validates codes before submission', async () => {
    renderDepartments()
    await screen.findByText('No departments yet')

    fireEvent.click(screen.getByRole('button', { name: /Add department/ }))
    fireEvent.change(screen.getByLabelText('Department name'), { target: { value: 'Travel' } })
    fireEvent.change(screen.getByLabelText('Code'), { target: { value: 'T&T' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add department' }))

    expect(await screen.findByText('Use 2–8 uppercase letters or digits.')).toBeInTheDocument()
    expect(apiMocks.POST).not.toHaveBeenCalled()
  })

  it('shows backend field errors inline in the drawer', async () => {
    apiMocks.POST.mockResolvedValue({
      error: {
        code: 'VALIDATION',
        message: 'Request failed.',
        fields: { code: ['A department with this code already exists.'] },
      },
    })
    renderDepartments()
    await screen.findByText('No departments yet')

    fireEvent.click(screen.getByRole('button', { name: /Add department/ }))
    fireEvent.change(screen.getByLabelText('Department name'), { target: { value: 'Travel' } })
    fireEvent.change(screen.getByLabelText('Code'), { target: { value: 'TRV' } })
    fireEvent.change(screen.getByLabelText('Business unit'), { target: { value: 'unit-a' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add department' }))

    expect(await screen.findByText('A department with this code already exists.')).toBeInTheDocument()
    expect(screen.getByLabelText('Code')).toHaveAttribute('aria-invalid', 'true')
  })

  it('submits server-side search and archive visibility filters', async () => {
    renderDepartments()
    await screen.findByText('No departments yet')

    fireEvent.change(screen.getByRole('searchbox', { name: 'Search departments' }), {
      target: { value: 'travel' },
    })
    await waitFor(() => {
      expect(apiMocks.GET).toHaveBeenLastCalledWith('/api/v1/departments/', expect.objectContaining({
        params: expect.objectContaining({
          query: expect.objectContaining({ page: 1, search: 'travel' }),
        }),
      }))
    })

    fireEvent.click(screen.getByRole('checkbox', { name: 'Show archived' }))
    await waitFor(() => {
      expect(apiMocks.GET).toHaveBeenLastCalledWith('/api/v1/departments/', expect.objectContaining({
        params: expect.objectContaining({
          query: expect.objectContaining({ show_archived: true }),
        }),
      }))
    })
  })
})
