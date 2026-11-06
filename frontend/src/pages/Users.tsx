import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { sendPasswordResetEmail } from 'firebase/auth'
import { useState } from 'react'
import { api } from '../api/client'
import type { components } from '../api/schema'
import { useMe } from '../features/me/useMe'
import { hasRole } from '../features/me/roles'
import { apiErrorMessage } from '../lib/apiError'
import { PageHeader } from '../app/PageHeader'
import { auth } from '../lib/firebase'

type User = components['schemas']['User']
type Role = components['schemas']['Role688Enum']
type Department = components['schemas']['Department']

const roles: Role[] = [
  'ADMIN',
  'DIRECTOR',
  'AUDITOR',
  'UNIT_MANAGER',
  'HOD',
  'TEACHER',
  'BURSAR',
  'CASHIER',
]

function rolesAssignableBy(isSuperAdmin: boolean) {
  return isSuperAdmin ? ['SUPER_ADMIN', ...roles] as Role[] : roles.filter((role) => role !== 'ADMIN')
}

function UserRow({
  user,
  canManage,
  isSuperAdmin,
  departments,
}: {
  user: User
  canManage: boolean
  isSuperAdmin: boolean
  departments: Department[]
}) {
  const queryClient = useQueryClient()
  const [role, setRole] = useState<Role | ''>(
    () => roles.find((option) => option === user.role) ?? '',
  )
  const [departmentIds, setDepartmentIds] = useState(user.department_ids)
  const [errorMessage, setErrorMessage] = useState('')
  const canEdit = canManage && (
    isSuperAdmin || (user.role !== 'SUPER_ADMIN' && user.role !== 'ADMIN')
  )
  const roleOptions = rolesAssignableBy(isSuperAdmin)
  const changeRole = useMutation({
    mutationFn: async () => {
      setErrorMessage('')
      const { error } = await api.PATCH('/api/v1/users/{id}/role/', {
        params: { path: { id: user.id } },
        body: {
          role: role || null,
          department_ids: role === 'HOD' ? departmentIds : [],
        },
      })
      if (error) throw new Error(apiErrorMessage(error, 'Unable to update this user role.'))
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['users'] })
      void queryClient.invalidateQueries({ queryKey: ['me'] })
    },
    onError: (error) => setErrorMessage(error.message),
  })

  return (
    <tr className="border-t border-line">
      <td className="p-3">{user.display_name || '—'}</td>
      <td className="p-3">{user.email}</td>
      <td className="p-3">
        {canEdit ? (
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label={`Role for ${user.email}`}
              className="rounded border border-line bg-white p-2"
              value={role}
              onChange={(event) => setRole(event.target.value as Role | '')}
            >
              <option value="">Awaiting approval</option>
              {roleOptions.map((option) => <option key={option} value={option}>{option.replace('_', ' ')}</option>)}
            </select>
            <button
              className="rounded border border-line px-2 py-1 disabled:opacity-60"
              type="button"
              disabled={changeRole.isPending}
              onClick={() => changeRole.mutate()}
            >
              {changeRole.isPending ? 'Saving…' : 'Save role'}
            </button>
            {role === 'HOD' && (
              <select
                aria-label={`Departments for ${user.email}`}
                className="min-h-16 rounded border border-line bg-white p-2"
                multiple
                value={departmentIds}
                onChange={(event) => setDepartmentIds(Array.from(event.currentTarget.selectedOptions, (option) => option.value))}
              >
                {departments.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}
              </select>
            )}
          </div>
        ) : user.role?.replace('_', ' ') ?? 'Awaiting approval'}
        {errorMessage && <p className="mt-1 text-xs text-danger-fg" role="alert">{errorMessage}</p>}
      </td>
      <td className="p-3">{user.is_active ? 'Active' : 'Disabled'}</td>
    </tr>
  )
}

export function Users() {
  const queryClient = useQueryClient()
  const { data: me } = useMe()
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [role, setRole] = useState<Role | ''>('')
  const [departmentIds, setDepartmentIds] = useState<string[]>([])
  const [message, setMessage] = useState('')
  const [errorMessage, setErrorMessage] = useState('')
  const departmentsQuery = useQuery({
    queryKey: ['departments'],
    enabled: hasRole(me, 'SUPER_ADMIN', 'ADMIN'),
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/departments/')
      if (error) throw new Error(apiErrorMessage(error, 'Unable to load departments.'))
      return data
    },
  })
  const usersQuery = useQuery({
    queryKey: ['users'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/users/')
      if (error) throw new Error(apiErrorMessage(error, 'Unable to load users.'))
      return data
    },
  })

  const invite = useMutation({
    mutationFn: async () => {
      setMessage('')
      setErrorMessage('')
      const { data, error } = await api.POST('/api/v1/users/invite/', {
        body: { email, display_name: displayName, role: role || null, department_ids: role === 'HOD' ? departmentIds : [] },
      })
      if (error) throw new Error(apiErrorMessage(error, 'Unable to create the account.'))
      if (!data) throw new Error('The server did not return the new account.')
      try {
        await sendPasswordResetEmail(auth, email)
      } catch {
        throw new Error('The account was created, but the password setup email could not be sent.')
      }
      return data
    },
    onSuccess: (user) => {
      setMessage(`Invite sent to ${user.email}.`)
      setEmail('')
      setDisplayName('')
      setRole('')
      setDepartmentIds([])
      void queryClient.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (error) => setErrorMessage(error.message),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['users'] }),
  })

  const canManage = hasRole(me, 'SUPER_ADMIN', 'ADMIN')
  const availableRoles = rolesAssignableBy(hasRole(me, 'SUPER_ADMIN'))

  return (
    <section className="space-y-6">
      <PageHeader title="Users" />

      {canManage && (
        <form
          className="grid gap-3 rounded-xl border border-line bg-white p-5 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault()
            invite.mutate()
          }}
        >
          <h2 className="text-lg font-medium sm:col-span-2">Invite a user</h2>
          <label className="grid gap-1 text-sm">
            Name
            <input className="rounded border border-line p-2" value={displayName} onChange={(event) => setDisplayName(event.target.value)} required />
          </label>
          <label className="grid gap-1 text-sm">
            Email
            <input className="rounded border border-line p-2" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>
          <label className="grid gap-1 text-sm">
            Role
            <select className="rounded border border-line bg-white p-2" value={role} onChange={(event) => setRole(event.target.value as Role | '')} required>
              <option value="" disabled>Select a role</option>
              {availableRoles.map((option) => <option key={option} value={option}>{option.replace('_', ' ')}</option>)}
            </select>
          </label>
          {role === 'HOD' && (
            <label className="grid gap-1 text-sm sm:col-span-2">
              Departments for this HOD
              <select
                className="min-h-24 rounded border border-line bg-white p-2"
                multiple
                value={departmentIds}
                onChange={(event) => setDepartmentIds(Array.from(event.currentTarget.selectedOptions, (option) => option.value))}
                required
              >
                {(departmentsQuery.data?.results ?? []).map((department: Department) => (
                  <option key={department.id} value={department.id}>{department.name}</option>
                ))}
              </select>
              {departmentsQuery.isError && <span role="alert">{departmentsQuery.error.message}</span>}
            </label>
          )}
          <button className="self-end rounded bg-primary p-2 font-medium text-primary-fg disabled:opacity-60" type="submit" disabled={invite.isPending}>
            {invite.isPending ? 'Sending invite…' : 'Create account and invite'}
          </button>
          {message && <p className="text-sm text-success-fg sm:col-span-2" role="status">{message}</p>}
          {errorMessage && <p className="text-sm text-danger-fg sm:col-span-2" role="alert">{errorMessage}</p>}
        </form>
      )}

      {usersQuery.isPending && <p role="status">Loading users…</p>}
      {usersQuery.isError && <p role="alert">{usersQuery.error.message}</p>}
      {usersQuery.data && (
        <div className="scrollbar-thin overflow-x-auto rounded-xl border border-line bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-surface-2">
              <tr><th className="p-3">Name</th><th className="p-3">Email</th><th className="p-3">Role</th><th className="p-3">Status</th></tr>
            </thead>
            <tbody>
              {usersQuery.data.results.map((user: User) => (
                <UserRow
                  key={user.id}
                  user={user}
                  canManage={canManage}
                  isSuperAdmin={hasRole(me, 'SUPER_ADMIN')}
                  departments={departmentsQuery.data?.results ?? []}
                />
              ))}
              {usersQuery.data.results.length === 0 && <tr><td className="p-3 text-subtle" colSpan={4}>No users found.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
