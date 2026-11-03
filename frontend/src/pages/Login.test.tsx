import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { Login } from './Login'

const { loginMock } = vi.hoisted(() => ({ loginMock: vi.fn() }))

vi.mock('../lib/auth/AuthProvider', () => ({
  useAuth: () => ({ login: loginMock }),
}))

describe('Login', () => {
  beforeEach(() => loginMock.mockReset())

  it('renders email validation errors and does not submit', async () => {
    render(<MemoryRouter><Login /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Enter a valid email address.')).toBeInTheDocument()
    expect(screen.getByText('Password is required.')).toBeInTheDocument()
    expect(loginMock).not.toHaveBeenCalled()
  })

  it('submits the valid credentials through the login function', async () => {
    loginMock.mockResolvedValue(undefined)
    render(<MemoryRouter><Login /></MemoryRouter>)
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'user@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'secret' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(loginMock).toHaveBeenCalledWith('user@example.com', 'secret'))
  })
})
