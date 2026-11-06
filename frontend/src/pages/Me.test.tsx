import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '../api/schema'
import { Me } from './Me'

const mocks = vi.hoisted(() => ({
  useMe: vi.fn(),
  useUpdateMe: vi.fn(),
  useAuth: vi.fn(),
}))

vi.mock('../features/me/useMe', () => ({ useMe: mocks.useMe, useUpdateMe: mocks.useUpdateMe }))
vi.mock('../lib/auth/useAuth', () => ({ useAuth: mocks.useAuth }))

const baseProfile: components['schemas']['Me'] = {
  id: 'profile-id',
  email: 'learner@example.com',
  display_name: '',
  phone_number: '',
  role: 'STUDENT',
  assignments: [],
  is_global_read: false,
  awaiting_approval: false,
  is_active: true,
}

describe('Me profile page', () => {
  beforeEach(() => {
    mocks.useMe.mockReset()
    mocks.useUpdateMe.mockReset()
    mocks.useAuth.mockReset()
    mocks.useMe.mockReturnValue({
      data: baseProfile,
      error: null,
      isPending: false,
      isError: false,
    })
    mocks.useAuth.mockReturnValue({
      firebaseUser: { displayName: null, photoURL: null },
    })
    mocks.useUpdateMe.mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false, error: null })
  })

  it('uses the display name before the Firebase name and email fallback', () => {
    mocks.useMe.mockReturnValue({
      data: { ...baseProfile, display_name: '  LMS Profile  ' },
      error: null,
      isPending: false,
      isError: false,
    })
    mocks.useAuth.mockReturnValue({
      firebaseUser: { displayName: 'Firebase Profile', photoURL: null },
    })

    render(<MemoryRouter><Me /></MemoryRouter>)

    expect(screen.getByRole('heading', { name: 'My profile' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'LMS Profile' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'LMS Profile' })).toBeInTheDocument()
    expect(screen.getByText('Student', { selector: 'span' })).toBeInTheDocument()
  })

  it('uses the email local-part when the account name is empty', () => {
    mocks.useAuth.mockReturnValue({
      firebaseUser: { displayName: '  Firebase Name ', photoURL: null },
    })
    const { rerender } = render(<MemoryRouter><Me /></MemoryRouter>)
    expect(screen.getByRole('heading', { name: 'learner' })).toBeInTheDocument()

    mocks.useAuth.mockReturnValue({ firebaseUser: null })
    rerender(<MemoryRouter><Me /></MemoryRouter>)
    expect(screen.getByRole('heading', { name: 'learner' })).toBeInTheDocument()
  })

  it('shows the awaiting-approval notice and role badge when no role is assigned', () => {
    mocks.useMe.mockReturnValue({
      data: { ...baseProfile, role: null, awaiting_approval: true },
      error: null,
      isPending: false,
      isError: false,
    })

    render(<MemoryRouter><Me /></MemoryRouter>)

    expect(screen.getByRole('status')).toHaveTextContent(/Your account is awaiting approval/)
    expect(screen.getAllByText('Awaiting approval').length).toBeGreaterThan(0)
  })

  it('submits name and phone changes to the profile mutation', () => {
    const mutate = vi.fn()
    mocks.useUpdateMe.mockReturnValue({ mutate, isPending: false, isError: false, error: null })
    render(<MemoryRouter><Me /></MemoryRouter>)

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: '  Learner Name  ' } })
    fireEvent.change(screen.getByLabelText('Phone number'), { target: { value: '+254700000000' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))

    expect(mutate).toHaveBeenCalledWith(
      { display_name: 'Learner Name', phone_number: '+254700000000' },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    )
  })
})
