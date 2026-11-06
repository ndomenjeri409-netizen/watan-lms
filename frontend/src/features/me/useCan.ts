import { hasRole, type Role } from './roles'
import { useMe } from './useMe'

export function useCan(roles: Role | Role[], unitId?: string) {
  const { data: profile } = useMe()
  const requestedRoles = Array.isArray(roles) ? roles : [roles]
  if (!profile) return false
  if (unitId) {
    return profile.assignments.some(
      (assignment) => requestedRoles.includes(assignment.role)
        && (assignment.unit?.id === unitId || (assignment.unit === null && profile.is_global_read)),
    )
  }
  return hasRole(profile, ...requestedRoles)
}
