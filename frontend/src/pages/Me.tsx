import { useState, type FormEvent } from 'react'
import { Avatar, Badge, Button, Card, CardContent, FormField, Input } from '../components/ui'
import { PageHeader } from '../app/PageHeader'
import { roleLabel } from '../features/me/roles'
import { useMe, useUpdateMe } from '../features/me/useMe'
import { useAuth } from '../lib/auth/useAuth'

export function Me() {
  const { data, error, isPending, isError } = useMe()
  const { firebaseUser } = useAuth()
  const updateProfile = useUpdateMe()
  const [saved, setSaved] = useState(false)

  if (isPending) return <p role="status">Loading your profile…</p>
  if (isError) return <p role="alert">{error.message}</p>
  if (!data) return <p role="alert">Profile unavailable.</p>

  const name = data.display_name.trim() || data.email.split('@')[0] || firebaseUser?.displayName?.trim() || 'Account'
  const initials = name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('')
  const handleProfileSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const formData = new FormData(event.currentTarget)
    setSaved(false)
    updateProfile.mutate({
      display_name: String(formData.get('display_name') ?? '').trim(),
      phone_number: String(formData.get('phone_number') ?? '').trim(),
    }, {
      onSuccess: () => setSaved(true),
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader title="My profile" />
      {data.awaiting_approval && (
        <Card className="border-primary/40 bg-primary/15 p-4 text-warning-fg dark:border-primary/40 dark:bg-primary dark:text-warning-fg" role="status">
          Your account is awaiting approval. Your role-specific access will be available after an administrator assigns your role.
        </Card>
      )}
      <Card>
        <CardContent className="pt-6">
          <div className="mb-6 flex items-center gap-4">
            <Avatar
              className="size-16 bg-app text-lg"
              src={firebaseUser?.photoURL}
              alt={name}
              initials={initials}
            />
            <div className="min-w-0">
              <h2 className="truncate text-xl font-semibold">{name}</h2>
              <p className="truncate text-sm text-subtle">{data.email}</p>
              <Badge className="mt-2" variant={data.awaiting_approval ? 'warning' : 'neutral'}>
                {data.assignments.length
                  ? [...new Set(data.assignments.map((assignment) => roleLabel(assignment.role)))].join(', ')
                  : roleLabel(data.role)}
              </Badge>
            </div>
          </div>
          <dl className="grid gap-4 border-t border-line pt-5 sm:grid-cols-2">
            <div>
              <dt className="text-sm text-subtle">Name</dt>
              <dd className="mt-1 font-medium">{name}</dd>
            </div>
            <div>
              <dt className="text-sm text-subtle">Email</dt>
              <dd className="mt-1 font-medium">{data.email}</dd>
            </div>
            <div>
              <dt className="text-sm text-subtle">Role</dt>
              <dd className="mt-1 font-medium">{roleLabel(data.role)}</dd>
            </div>
            <div>
              <dt className="text-sm text-subtle">Phone</dt>
              <dd className="mt-1 font-medium">{data.phone_number || 'Not provided'}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>
      <Card id="complete-profile">
        <CardContent className="pt-6">
          <h2 className="text-lg font-semibold">Profile details</h2>
          <p className="mt-1 text-sm text-subtle">Update the name and phone number shown on your account.</p>
          <form className="mt-5 grid gap-4 sm:max-w-xl" onSubmit={handleProfileSubmit}>
            <FormField label="Name">
              <Input name="display_name" defaultValue={data.display_name} autoComplete="name" maxLength={200} required />
            </FormField>
            <FormField label="Phone number">
              <Input name="phone_number" type="tel" defaultValue={data.phone_number} autoComplete="tel" maxLength={30} />
            </FormField>
            {updateProfile.isError && <p className="text-sm text-danger-fg" role="alert">{updateProfile.error.message}</p>}
            {saved && <p className="text-sm text-success-fg" role="status">Profile updated.</p>}
            <Button className="justify-self-start" type="submit" disabled={updateProfile.isPending}>
              {updateProfile.isPending ? 'Saving…' : 'Save profile'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
