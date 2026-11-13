import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { sendPasswordResetEmail } from 'firebase/auth'
import { useState, type FormEvent } from 'react'
import { api } from '../api/client'
import type { components } from '../api/schema'
import { PageHeader } from '../app/PageHeader'
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  Drawer,
  Tabs,
  TabsList,
  TabsTrigger,
} from '../components/ui'
import { useMe } from '../features/me/useMe'
import { hasRole, roleLabel } from '../features/me/roles'
import { useUnit } from '../features/units/useUnit'
import { apiErrorFields, apiErrorMessage } from '../lib/apiError'
import { auth } from '../lib/firebase'

type User = components['schemas']['User']
type Role = components['schemas']['Role688Enum']
type Assignment = User['assignments'][number]
type UserFilter = 'all' | 'pending' | 'active'

const roles: Role[] = [
  'SUPER_ADMIN',
  'ADMIN',
  'DIRECTOR',
  'AUDITOR',
  'UNIT_MANAGER',
  'HOD',
  'TEACHER',
  'BURSAR',
  'CASHIER',
]
const unitRoles: Role[] = ['UNIT_MANAGER', 'HOD', 'TEACHER', 'CASHIER']
interface RequestError extends Error {
  fields: Record<string, string>
}

function requestError(error: unknown, fallback: string): RequestError {
  return Object.assign(new Error(apiErrorMessage(error, fallback)), {
    fields: apiErrorFields(error),
  })
}

function rolesAssignableBy(isSuperAdmin: boolean) {
  return roles.filter((role) => (
    (isSuperAdmin || role !== 'SUPER_ADMIN')
    && (isSuperAdmin || role !== 'ADMIN')
  ))
}

function assignmentLabel(assignment: Assignment) {
  return `${roleLabel(assignment.role)} · ${assignment.unit?.code ?? 'Group'}`
}

export function Users() {
  const queryClient = useQueryClient()
  const { data: me } = useMe()
  const units = useUnit()
  const [filter, setFilter] = useState<UserFilter>('all')
  const [drawerUser, setDrawerUser] = useState<User | null>(null)
  const [assignmentRole, setAssignmentRole] = useState<Role | ''>('')
  const [assignmentUnit, setAssignmentUnit] = useState('')
  const [assignmentDepartments, setAssignmentDepartments] = useState<string[]>([])
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState('')
  const [removeTarget, setRemoveTarget] = useState<{ user: User; assignment: Assignment } | null>(null)
  const [removeError, setRemoveError] = useState('')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [inviteRole, setInviteRole] = useState<Role | ''>('')
  const [inviteUnit, setInviteUnit] = useState('')
  const [inviteDepartments, setInviteDepartments] = useState<string[]>([])
  const [inviteMessage, setInviteMessage] = useState('')
  const [inviteError, setInviteError] = useState('')
  const canManage = hasRole(me, 'SUPER_ADMIN', 'ADMIN')
  const isSuperAdmin = hasRole(me, 'SUPER_ADMIN')
  const availableRoles = rolesAssignableBy(isSuperAdmin)

  const departmentsQuery = useQuery({
    queryKey: ['departments'],
    enabled: canManage,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/departments/')
      if (error) throw new Error(apiErrorMessage(error, 'Unable to load departments.'))
      return data?.results ?? []
    },
  })

  const usersQuery = useQuery({
    queryKey: ['users'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/users/')
      if (error) throw new Error(apiErrorMessage(error, 'Unable to load users.'))
      if (!data) throw new Error('The server returned no user list.')
      return data
    },
  })

  const assignRole = useMutation({
    mutationFn: async () => {
      if (!drawerUser || !assignmentRole) throw new Error('Select a role.')
      setFormError('')
      setFieldErrors({})
      const { error } = await api.POST('/api/v1/users/{id}/assignments/', {
        params: { path: { id: drawerUser.id } },
        body: {
          role: assignmentRole,
          ...(assignmentUnit ? { unit: assignmentUnit } : {}),
          ...(assignmentRole === 'HOD' ? { department_ids: assignmentDepartments } : {}),
        },
      })
      if (error) throw requestError(error, 'Unable to assign this role.')
    },
    onSuccess: () => {
      setDrawerUser(null)
      setFieldErrors({})
      setFormError('')
      void queryClient.invalidateQueries({ queryKey: ['users'] })
      void queryClient.invalidateQueries({ queryKey: ['me'] })
    },
    onError: (error: RequestError) => {
      setFormError(error.message)
      setFieldErrors(error.fields)
    },
  })

  const removeAssignment = useMutation({
    mutationFn: async () => {
      if (!removeTarget) return
      setRemoveError('')
      const { error } = await api.DELETE(
        '/api/v1/users/{id}/assignments/{assignment_id}/',
        {
          params: {
            path: {
              id: removeTarget.user.id,
              assignment_id: removeTarget.assignment.id,
            },
          },
        },
      )
      if (error) throw new Error(apiErrorMessage(error, 'Unable to remove this assignment.'))
    },
    onSuccess: () => {
      setRemoveTarget(null)
      void queryClient.invalidateQueries({ queryKey: ['users'] })
      void queryClient.invalidateQueries({ queryKey: ['me'] })
    },
    onError: (error: Error) => setRemoveError(error.message),
  })

  const invite = useMutation({
    mutationFn: async () => {
      setInviteMessage('')
      setInviteError('')
      const { error } = await api.POST('/api/v1/users/invite/', {
        body: {
          email,
          display_name: displayName,
          role: inviteRole || null,
          ...(inviteUnit ? { unit_id: inviteUnit } : {}),
          department_ids: inviteRole === 'HOD' ? inviteDepartments : [],
        },
      })
      if (error) throw new Error(apiErrorMessage(error, 'Unable to create the account.'))
      try {
        await sendPasswordResetEmail(auth, email)
      } catch {
        throw new Error('The account was created, but the password setup email could not be sent.')
      }
    },
    onSuccess: () => {
      setInviteMessage(`Invite sent to ${email}.`)
      setEmail('')
      setDisplayName('')
      setInviteRole('')
      setInviteUnit('')
      setInviteDepartments([])
      void queryClient.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (error: Error) => setInviteError(error.message),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['users'] }),
  })

  function openAssignDrawer(user: User) {
    setDrawerUser(user)
    setAssignmentRole('')
    setAssignmentUnit(units.unitId ?? (units.units.length === 1 ? units.units[0].id : ''))
    setAssignmentDepartments([])
    setFieldErrors({})
    setFormError('')
  }

  function submitInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    invite.mutate()
  }

  const visibleUsers = (usersQuery.data?.results ?? []).filter((user) => (
    filter === 'all' || user.status.toLowerCase() === filter
  ))
  const selectedDepartments = (departmentsQuery.data ?? []).filter(
    (department) => department.unit?.id === assignmentUnit,
  )
  const inviteSelectedDepartments = (departmentsQuery.data ?? []).filter(
    (department) => department.unit?.id === inviteUnit,
  )
  const unitRequired = Boolean(assignmentRole && unitRoles.includes(assignmentRole))
  const inviteUnitRequired = Boolean(inviteRole && unitRoles.includes(inviteRole))
  const showAssignmentUnit = unitRequired || assignmentRole === 'BURSAR'
  const showInviteUnit = inviteUnitRequired || inviteRole === 'BURSAR'

  return (
    <section className="space-y-6">
      <PageHeader title="Users" />

      {canManage && (
        <form
          className="grid gap-3 rounded-card border border-line bg-surface p-5 sm:grid-cols-2"
          onSubmit={submitInvite}
        >
          <h2 className="text-lg font-medium sm:col-span-2">Invite a user</h2>
          <label className="grid gap-1 text-sm">
            Name
            <input
              className="h-10 rounded border border-line bg-surface px-3 text-fg"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              required
            />
          </label>
          <label className="grid gap-1 text-sm">
            Email
            <input
              className="h-10 rounded border border-line bg-surface px-3 text-fg"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>
          <label className="grid gap-1 text-sm">
            Role
            <select
              className="h-10 rounded border border-line bg-surface px-3 text-fg"
              value={inviteRole}
              onChange={(event) => setInviteRole(event.target.value as Role | '')}
              required
            >
              <option value="" disabled>Select a role</option>
              {availableRoles.map((option) => (
                <option key={option} value={option}>{roleLabel(option)}</option>
              ))}
            </select>
          </label>
          {showInviteUnit && (
            <label className="grid gap-1 text-sm">
              Business unit{inviteUnitRequired ? '' : ' (optional for Bursar)'}
              <select
                aria-label="Invite business unit"
                className="h-10 rounded border border-line bg-surface px-3 text-fg"
                value={inviteUnit}
                onChange={(event) => setInviteUnit(event.target.value)}
                required={inviteUnitRequired}
              >
                <option value="">{inviteUnitRequired ? 'Select a unit' : 'Group-level Bursar'}</option>
                {units.units.map((unit) => (
                  <option key={unit.id} value={unit.id}>{unit.name} ({unit.code})</option>
                ))}
              </select>
            </label>
          )}
          {inviteRole === 'HOD' && (
            <label className="grid gap-1 text-sm sm:col-span-2">
              Departments for this HOD
              <select
                aria-label="Departments for invite"
                className="min-h-24 rounded border border-line bg-surface px-3 text-fg"
                multiple
                value={inviteDepartments}
                onChange={(event) => setInviteDepartments(
                  Array.from(event.currentTarget.selectedOptions, (option) => option.value),
                )}
                required
              >
                {inviteSelectedDepartments.map((department) => (
                  <option key={department.id} value={department.id}>{department.name}</option>
                ))}
              </select>
              {departmentsQuery.isError && <span role="alert">{departmentsQuery.error.message}</span>}
            </label>
          )}
          <Button className="self-end" type="submit" disabled={invite.isPending}>
            {invite.isPending ? 'Sending invite…' : 'Create account and invite'}
          </Button>
          {inviteMessage && <p className="text-sm text-success-fg sm:col-span-2" role="status">{inviteMessage}</p>}
          {inviteError && <p className="text-sm text-danger-fg sm:col-span-2" role="alert">{inviteError}</p>}
        </form>
      )}

      <Tabs value={filter} onValueChange={(value) => setFilter(value as UserFilter)}>
        <TabsList aria-label="Filter users">
          <TabsTrigger value="all">All</TabsTrigger>
          <TabsTrigger value="pending">Pending</TabsTrigger>
          <TabsTrigger value="active">Active</TabsTrigger>
        </TabsList>
      </Tabs>

      {usersQuery.isPending && <p role="status">Loading users…</p>}
      {usersQuery.isError && <p role="alert">{usersQuery.error.message}</p>}
      {usersQuery.data && (
        <div className="scrollbar-thin overflow-x-auto rounded-card border border-line bg-surface">
          <table className="w-full text-left text-sm">
            <thead className="bg-surface-2">
              <tr>
                <th className="p-3">Name</th>
                <th className="p-3">Email</th>
                <th className="p-3">Assignments</th>
                <th className="p-3">Status</th>
                <th className="p-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {visibleUsers.map((user) => {
                const isPending = user.status === 'PENDING'
                const canEdit = canManage && !(isSuperAdmin && me?.id === user.id)
                return (
                  <tr className="border-t border-line align-top" key={user.id}>
                    <td className="p-3">{user.display_name || '—'}</td>
                    <td className="p-3">{user.email}</td>
                    <td className="space-y-2 p-3">
                      {user.assignments.filter((assignment) => assignment.is_active).length === 0
                        ? <span className="text-subtle">No active assignments</span>
                        : user.assignments.filter((assignment) => assignment.is_active).map((assignment) => (
                            <div className="flex items-center gap-2" key={assignment.id}>
                              <Badge variant="neutral">{assignmentLabel(assignment)}</Badge>
                              {canEdit && (
                                <Button
                                  aria-label={`Remove ${assignmentLabel(assignment)} from ${user.email}`}
                                  className="h-8 px-2"
                                  variant="ghost"
                                  type="button"
                                  onClick={() => {
                                    setRemoveTarget({ user, assignment })
                                    setRemoveError('')
                                  }}
                                >
                                  Remove
                                </Button>
                              )}
                            </div>
                          ))}
                    </td>
                    <td className="p-3">
                      <Badge variant={isPending ? 'warning' : 'success'}>
                        {isPending ? 'Pending approval' : user.is_active ? 'Active' : 'Disabled'}
                      </Badge>
                    </td>
                    <td className="p-3">
                      {canEdit && (
                        <Button
                          size="sm"
                          type="button"
                          variant={isPending ? 'primary' : 'secondary'}
                          onClick={() => openAssignDrawer(user)}
                        >
                          {isPending ? 'Approve' : 'Assign role'}
                        </Button>
                      )}
                    </td>
                  </tr>
                )
              })}
              {visibleUsers.length === 0 && (
                <tr>
                  <td className="p-3 text-subtle" colSpan={5}>No users found.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <Drawer
        open={Boolean(drawerUser)}
        onOpenChange={(open) => {
          if (!open) setDrawerUser(null)
        }}
        title={drawerUser?.status === 'PENDING' ? 'Approve user' : 'Assign role'}
        description={drawerUser ? `${drawerUser.display_name || drawerUser.email} · ${drawerUser.email}` : undefined}
      >
        <form
          className="grid gap-4"
          onSubmit={(event) => {
            event.preventDefault()
            assignRole.mutate()
          }}
        >
          <label className="grid gap-1 text-sm">
            Role
            <select
              aria-label="Role"
              className="h-10 rounded border border-line bg-surface px-3 text-fg"
              value={assignmentRole}
              onChange={(event) => {
                setAssignmentRole(event.target.value as Role | '')
                setAssignmentDepartments([])
                setFieldErrors({})
              }}
              required
            >
              <option value="" disabled>Select a role</option>
              {availableRoles.map((option) => (
                <option key={option} value={option}>{roleLabel(option)}</option>
              ))}
            </select>
            {fieldErrors.role && <span className="text-danger-fg" role="alert">{fieldErrors.role}</span>}
          </label>
          {showAssignmentUnit && (
            <label className="grid gap-1 text-sm">
              Business unit{unitRequired ? '' : ' (optional for Bursar)'}
              <select
                aria-label="Business unit"
                className="h-10 rounded border border-line bg-surface px-3 text-fg"
                value={assignmentUnit}
                onChange={(event) => setAssignmentUnit(event.target.value)}
                required={unitRequired}
              >
                <option value="">{unitRequired ? 'Select a unit' : 'Group-level Bursar'}</option>
                {units.units.map((unit) => (
                  <option key={unit.id} value={unit.id}>{unit.name} ({unit.code})</option>
                ))}
              </select>
              {fieldErrors.unit && <span className="text-danger-fg" role="alert">{fieldErrors.unit}</span>}
            </label>
          )}
          {assignmentRole === 'HOD' && (
            <label className="grid gap-1 text-sm">
              Departments
              <select
                aria-label="Departments"
                className="min-h-24 rounded border border-line bg-surface px-3 text-fg"
                multiple
                value={assignmentDepartments}
                onChange={(event) => setAssignmentDepartments(
                  Array.from(event.currentTarget.selectedOptions, (option) => option.value),
                )}
                required
              >
                {selectedDepartments.map((department) => (
                  <option key={department.id} value={department.id}>{department.name}</option>
                ))}
              </select>
              {fieldErrors.department_ids && (
                <span className="text-danger-fg" role="alert">{fieldErrors.department_ids}</span>
              )}
            </label>
          )}
          {formError && !Object.values(fieldErrors).includes(formError) && (
            <p className="text-sm text-danger-fg" role="alert">{formError}</p>
          )}
          <Button type="submit" disabled={assignRole.isPending}>
            {assignRole.isPending ? 'Saving…' : drawerUser?.status === 'PENDING' ? 'Approve user' : 'Assign role'}
          </Button>
        </form>
      </Drawer>

      <Dialog
        open={Boolean(removeTarget)}
        onOpenChange={(open) => {
          if (!open) setRemoveTarget(null)
        }}
      >
        <DialogContent>
          <DialogTitle>Remove assignment?</DialogTitle>
          <DialogDescription>
            {removeTarget
              ? `Deactivate ${assignmentLabel(removeTarget.assignment)} for ${removeTarget.user.email}?`
              : ''}
          </DialogDescription>
          {removeError && <p className="mt-4 text-sm text-danger-fg" role="alert">{removeError}</p>}
          <div className="mt-6 flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setRemoveTarget(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="danger"
              disabled={removeAssignment.isPending}
              onClick={() => removeAssignment.mutate()}
            >
              {removeAssignment.isPending ? 'Removing…' : 'Remove assignment'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  )
}
