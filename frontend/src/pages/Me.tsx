import { useEffect, useState } from 'react'
import { useMe } from '../features/me/useMe'
import { useAuth } from '../lib/auth/AuthProvider'

export function Me() {
  const { logout } = useAuth()
  const { data, error, isPending, isError } = useMe()
  const [waking, setWaking] = useState(false)

  useEffect(() => {
    if (!isPending) {
      setWaking(false)
      return
    }
    const timer = window.setTimeout(() => setWaking(true), 3000)
    return () => window.clearTimeout(timer)
  }, [isPending])

  if (isPending) {
    return <p role="status">{waking ? 'Waking up the server…' : 'Loading your profile…'}</p>
  }
  if (isError) return <p role="alert">{error.message}</p>
  if (!data) return <p role="alert">Profile unavailable.</p>

  return (
    <section className="rounded-xl border border-neutral-200 bg-white p-6">
      <div className="mb-5 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">My profile</h1>
        <button className="text-sm underline" onClick={() => void logout()}>Sign out</button>
      </div>
      <dl className="space-y-4">
        <div><dt className="text-sm text-neutral-500">Name</dt><dd>{data.display_name || '—'}</dd></div>
        <div><dt className="text-sm text-neutral-500">Email</dt><dd>{data.email || '—'}</dd></div>
        <div><dt className="text-sm text-neutral-500">Role</dt><dd>{data.role ?? 'Awaiting approval'}</dd></div>
      </dl>
      {data.role === null && <p className="mt-5 text-sm text-neutral-600">Your account is awaiting approval.</p>}
    </section>
  )
}
