import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useMe, useUpdateMe } from './useMe'

const { getMe, patchMe, updateFirebaseProfile } = vi.hoisted(() => ({
  getMe: vi.fn(),
  patchMe: vi.fn(),
  updateFirebaseProfile: vi.fn(),
}))

vi.mock('../../api/client', () => ({
  api: { GET: getMe, PATCH: patchMe },
}))
vi.mock('../../lib/auth/useAuth', () => ({
  useAuth: () => ({ firebaseUser: { uid: 'user-1', displayName: 'Old name' } }),
}))
vi.mock('firebase/auth', () => ({
  updateProfile: updateFirebaseProfile,
}))

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useMe', () => {
  beforeEach(() => {
    getMe.mockReset()
    patchMe.mockReset()
    updateFirebaseProfile.mockReset()
  })

  it('loads the profile from the typed API client', async () => {
    getMe.mockResolvedValue({
      data: {
        id: 'a0b1c2d3-e4f5-6789-abcd-ef0123456789',
        email: 'user@example.com',
        display_name: 'Sample User',
        role: null,
        is_active: true,
      },
    })
    const { result } = renderHook(() => useMe(), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.email).toBe('user@example.com')
    expect(getMe).toHaveBeenCalledWith('/api/v1/me')
  })

  it('updates Firebase and the API, then refreshes the profile cache', async () => {
    const updatedProfile = {
      id: 'a0b1c2d3-e4f5-6789-abcd-ef0123456789',
      email: 'user@example.com',
      display_name: 'New name',
      phone_number: '+254700000000',
      role: null,
      is_active: true,
    }
    patchMe.mockResolvedValue({ data: updatedProfile })
    const wrapper = createWrapper()
    const { result } = renderHook(() => useUpdateMe(), { wrapper })

    await act(async () => {
      await result.current.mutateAsync({ display_name: 'New name', phone_number: '+254700000000' })
    })

    expect(updateFirebaseProfile).toHaveBeenCalledWith(
      expect.objectContaining({ uid: 'user-1' }),
      { displayName: 'New name' },
    )
    expect(patchMe).toHaveBeenCalledWith('/api/v1/me', {
      body: { display_name: 'New name', phone_number: '+254700000000' },
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
  })

  it('restores the Firebase display name when the API update fails', async () => {
    patchMe.mockResolvedValue({ error: { code: 'INVALID', message: 'Profile update failed.' } })
    const { result } = renderHook(() => useUpdateMe(), { wrapper: createWrapper() })

    await act(async () => {
      await expect(result.current.mutateAsync({ display_name: 'New name', phone_number: '' }))
        .rejects.toThrow('Profile update failed.')
    })

    expect(updateFirebaseProfile).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ uid: 'user-1' }),
      { displayName: 'Old name' },
    )
  })
})
