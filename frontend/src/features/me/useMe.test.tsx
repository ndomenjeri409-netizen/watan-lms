import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useMe } from './useMe'

const { getMe } = vi.hoisted(() => ({ getMe: vi.fn() }))

vi.mock('../../api/client', () => ({
  api: { GET: getMe },
}))
vi.mock('../../lib/auth/AuthProvider', () => ({
  useAuth: () => ({ firebaseUser: { uid: 'user-1' } }),
}))

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useMe', () => {
  beforeEach(() => getMe.mockReset())

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
})
