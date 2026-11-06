import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Profile } from './roles'
import { useCan } from './useCan'

const mocks = vi.hoisted(() => ({ profile: null as Profile | null }))

vi.mock('./useMe', () => ({
  useMe: () => ({ data: mocks.profile }),
}))

describe('useCan', () => {
  it('checks assigned roles for a requested unit', () => {
    mocks.profile = {
      id: 'manager',
      email: 'manager@example.com',
      display_name: 'Manager',
      phone_number: '',
      role: 'UNIT_MANAGER',
      assignments: [
        { role: 'UNIT_MANAGER', unit: { id: 'unit-a', code: 'WTI', name: 'Institute' } },
      ],
      is_global_read: false,
      awaiting_approval: false,
      is_active: true,
    }

    const { result } = renderHook(() => useCan('UNIT_MANAGER', 'unit-a'))
    expect(result.current).toBe(true)
  })

  it('does not grant a unit-scoped role access to another unit', () => {
    const { result } = renderHook(() => useCan('UNIT_MANAGER', 'unit-b'))
    expect(result.current).toBe(false)
  })
})
