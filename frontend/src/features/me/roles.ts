import type { components } from '../../api/schema'

export type Role = components['schemas']['UserAssignment']['role']
export type Profile = components['schemas']['Me']

const roleOrder: Role[] = [
  'SUPER_ADMIN',
  'ADMIN',
  'DIRECTOR',
  'AUDITOR',
  'UNIT_MANAGER',
  'HOD',
  'BURSAR',
  'TEACHER',
  'CASHIER',
  'STUDENT',
]

const roleLabels: Record<Role, string> = {
  SUPER_ADMIN: 'Super admin',
  ADMIN: 'Admin',
  DIRECTOR: 'Director',
  AUDITOR: 'Auditor',
  UNIT_MANAGER: 'Unit manager',
  HOD: 'HOD',
  TEACHER: 'Teacher',
  BURSAR: 'Bursar',
  CASHIER: 'Cashier',
  STUDENT: 'Student',
}

export function roleLabel(role: Role | string | null | undefined): string {
  if (!role) return 'Awaiting approval'
  return role in roleLabels ? roleLabels[role as Role] : role
}

export function hasRole(profile: Profile | undefined, ...roles: Role[]): boolean {
  if (!profile) return false
  if (roles.includes('STUDENT') && profile.role === 'STUDENT') return true
  return profile.assignments.some((assignment) => roles.includes(assignment.role))
}

export function primaryRole(profile: Profile): Role | null {
  const assignedRoles = new Set(profile.assignments.map((assignment) => assignment.role))
  return roleOrder.find((role) => assignedRoles.has(role))
    ?? (profile.role === 'STUDENT' ? 'STUDENT' : null)
}
