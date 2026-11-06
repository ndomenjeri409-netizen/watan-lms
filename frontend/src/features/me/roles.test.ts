import { describe, expect, it } from 'vitest'
import { hasRole, primaryRole, roleLabel, type Profile } from './roles'

describe('roleLabel', () => {
  it.each([
    ['SUPER_ADMIN', 'Super admin'],
    ['ADMIN', 'Admin'],
    ['DIRECTOR', 'Director'],
    ['AUDITOR', 'Auditor'],
    ['UNIT_MANAGER', 'Unit manager'],
    ['HOD', 'HOD'],
    ['TEACHER', 'Teacher'],
    ['BURSAR', 'Bursar'],
    ['CASHIER', 'Cashier'],
    ['STUDENT', 'Student'],
  ] as const)('labels %s as %s', (role, label) => {
    expect(roleLabel(role)).toBe(label)
  })

  describe('assignment-aware role helpers', () => {
    const profile: Profile = {
      id: 'user',
      email: 'user@example.com',
      display_name: 'User',
      phone_number: '',
      role: 'HOD',
      assignments: [
        { role: 'HOD', unit: { id: 'unit-a', code: 'WTI', name: 'Institute' } },
        { role: 'CASHIER', unit: { id: 'unit-b', code: 'WTA', name: 'Travel' } },
      ],
      is_global_read: false,
      awaiting_approval: false,
      is_active: true,
    }

    it('checks roles from assignments and selects the primary assigned role', () => {
      expect(hasRole(profile, 'HOD')).toBe(true)
      expect(hasRole(profile, 'CASHIER')).toBe(true)
      expect(hasRole(profile, 'CASHIER', 'TEACHER')).toBe(true)
      expect(hasRole(profile, 'ADMIN')).toBe(false)
      expect(primaryRole(profile)).toBe('HOD')
    })

    it('derives student access from the profile role without a role assignment', () => {
      expect(hasRole({ ...profile, role: 'STUDENT', assignments: [] }, 'STUDENT')).toBe(true)
    })
  })

  it('labels accounts awaiting approval', () => {
    expect(roleLabel(null)).toBe('Awaiting approval')
    expect(roleLabel(undefined)).toBe('Awaiting approval')
  })
})
