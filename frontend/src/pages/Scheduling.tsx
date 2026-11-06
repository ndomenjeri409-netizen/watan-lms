import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'
import { api } from '../api/client'
import type { components } from '../api/schema'
import { apiErrorMessage } from '../lib/apiError'
import { useMe } from '../features/me/useMe'
import { hasRole } from '../features/me/roles'
import { PageHeader } from '../app/PageHeader'

type ClassGroup = components['schemas']['ClassGroup']
type TimetableSlot = components['schemas']['TimetableSlot']
type AttendanceSession = components['schemas']['AttendanceSession']
type QrIssue = components['schemas']['QrIssue']
type PendingCheckIn = { token: string; client_checkin_id: string }

const pendingCheckInsKey = 'watan-lms-pending-attendance'
const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

function assertApiSuccess(error: unknown, fallback: string) {
  if (error) throw new Error(apiErrorMessage(error, fallback))
}

function hasHttpStatus(error: unknown): error is { status: number } {
  return typeof error === 'object' && error !== null && 'status' in error && typeof error.status === 'number'
}

function readPendingCheckIns(): PendingCheckIn[] {
  const saved = localStorage.getItem(pendingCheckInsKey)
  if (!saved) return []
  try {
    const parsed: unknown = JSON.parse(saved)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((item): item is PendingCheckIn =>
      typeof item === 'object'
      && item !== null
      && 'token' in item
      && typeof item.token === 'string'
      && 'client_checkin_id' in item
      && typeof item.client_checkin_id === 'string',
    )
  } catch {
    return []
  }
}

function getErrorMessage(error: unknown, fallback: string) {
  return apiErrorMessage(error, fallback)
}

export function Scheduling() {
  const { data: profile } = useMe()
  const queryClient = useQueryClient()
  const [formError, setFormError] = useState('')
  const [issuedQr, setIssuedQr] = useState<Record<string, QrIssue>>({})
  const [selectedSession, setSelectedSession] = useState('')
  const canManageGroups = hasRole(profile, 'SUPER_ADMIN', 'ADMIN', 'HOD')
  const canManageOwnSchedule = canManageGroups || hasRole(profile, 'TEACHER')

  const groupsQuery = useQuery({
    queryKey: ['class-groups'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/class-groups/')
      assertApiSuccess(error, 'Unable to load class groups.')
      if (!data) throw new Error('The server returned no class groups.')
      return data.results
    },
  })
  const slotsQuery = useQuery({
    queryKey: ['timetable'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/timetable/')
      assertApiSuccess(error, 'Unable to load the timetable.')
      if (!data) throw new Error('The server returned no timetable.')
      return data.results
    },
  })
  const sessionsQuery = useQuery({
    queryKey: ['attendance-sessions'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/attendance/sessions/')
      assertApiSuccess(error, 'Unable to load attendance sessions.')
      if (!data) throw new Error('The server returned no attendance sessions.')
      return data.results
    },
  })
  const coursesQuery = useQuery({
    queryKey: ['courses', 'scheduling'],
    enabled: canManageGroups || hasRole(profile, 'TEACHER'),
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/courses/')
      assertApiSuccess(error, 'Unable to load courses.')
      if (!data) throw new Error('The server returned no courses.')
      return data.results
    },
  })
  const teachersQuery = useQuery({
    queryKey: ['teachers'],
    enabled: canManageGroups,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/users/', {
        params: { query: { role: 'TEACHER', is_active: true } },
      })
      assertApiSuccess(error, 'Unable to load teachers.')
      if (!data) throw new Error('The server returned no teachers.')
      return data.results
    },
  })
  const roomsQuery = useQuery({
    queryKey: ['rooms'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/rooms/', {
        params: { query: { is_active: true } },
      })
      assertApiSuccess(error, 'Unable to load rooms.')
      if (!data) throw new Error('The server returned no rooms.')
      return data.results
    },
  })
  const departmentsQuery = useQuery({
    queryKey: ['departments', 'scheduling'],
    enabled: canManageGroups,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/departments/')
      assertApiSuccess(error, 'Unable to load departments.')
      if (!data) throw new Error('The server returned no departments.')
      return data.results
    },
  })
  const recordsQuery = useQuery({
    queryKey: ['attendance-records', selectedSession],
    enabled: Boolean(selectedSession),
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/attendance/records/', {
        params: { query: { session: selectedSession } },
      })
      assertApiSuccess(error, 'Unable to load attendance records.')
      if (!data) throw new Error('The server returned no attendance records.')
      return data.results
    },
  })

  const invalidateScheduling = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['class-groups'] }),
      queryClient.invalidateQueries({ queryKey: ['timetable'] }),
      queryClient.invalidateQueries({ queryKey: ['attendance-sessions'] }),
    ])
  }

  const createGroup = useMutation({
    mutationFn: async (form: FormData) => {
      const teacher = canManageGroups
        ? form.get('teacher')?.toString() ?? ''
        : profile?.id ?? ''
      const { data, error } = await api.POST('/api/v1/class-groups/', {
        body: {
          course: form.get('course')?.toString() ?? '',
          teacher,
          name: form.get('name')?.toString() ?? '',
          code: form.get('code')?.toString() ?? '',
          capacity: Number(form.get('capacity')) || 40,
        },
      })
      assertApiSuccess(error, 'The class group could not be created.')
      if (!data) throw new Error('The server returned no class group.')
      return data
    },
    onSuccess: async () => {
      setFormError('')
      await invalidateScheduling()
    },
    onError: (error) => setFormError(error.message),
  })

  const createRoom = useMutation({
    mutationFn: async (form: FormData) => {
      const { data, error } = await api.POST('/api/v1/rooms/', {
        body: {
          department: form.get('department')?.toString() || null,
          name: form.get('name')?.toString() ?? '',
          code: form.get('code')?.toString() ?? '',
          capacity: Number(form.get('capacity')) || 1,
          is_active: true,
        },
      })
      assertApiSuccess(error, 'The room could not be created.')
      if (!data) throw new Error('The server returned no room.')
      return data
    },
    onSuccess: async () => {
      setFormError('')
      await queryClient.invalidateQueries({ queryKey: ['rooms'] })
    },
    onError: (error) => setFormError(error.message),
  })

  const createSlot = useMutation({
    mutationFn: async (form: FormData) => {
      const { data, error } = await api.POST('/api/v1/timetable/', {
        body: {
          class_group: form.get('class_group')?.toString() ?? '',
          room: form.get('room')?.toString() || null,
          weekday: Number(form.get('weekday')) as components['schemas']['WeekdayEnum'],
          starts_at: form.get('starts_at')?.toString() ?? '',
          ends_at: form.get('ends_at')?.toString() ?? '',
          effective_from: form.get('effective_from')?.toString() ?? '',
          effective_until: form.get('effective_until')?.toString() || null,
        },
      })
      assertApiSuccess(error, 'The timetable slot could not be created.')
      if (!data) throw new Error('The server returned no timetable slot.')
      return data
    },
    onSuccess: async () => {
      setFormError('')
      await invalidateScheduling()
    },
    onError: (error) => setFormError(error.message),
  })

  const openSession = useMutation({
    mutationFn: async (group: ClassGroup) => {
      const { data, error } = await api.POST('/api/v1/attendance/sessions/open/', {
        body: { class_group: group.id, title: `${group.course_title} attendance` },
      })
      assertApiSuccess(error, 'Attendance could not be opened.')
      if (!data) throw new Error('The server returned no attendance session.')
      return data
    },
    onSuccess: async () => {
      setFormError('')
      await invalidateScheduling()
    },
    onError: (error) => setFormError(error.message),
  })

  const issueQr = useMutation({
    mutationFn: async (session: AttendanceSession) => {
      const { data, error } = await api.POST('/api/v1/attendance/sessions/{id}/qr/', {
        params: { path: { id: session.id } },
      })
      assertApiSuccess(error, 'A check-in code could not be issued.')
      if (!data) throw new Error('The server returned no check-in code.')
      return { sessionId: session.id, data }
    },
    onSuccess: ({ sessionId, data }) => {
      setIssuedQr((current) => ({ ...current, [sessionId]: data }))
      setFormError('')
    },
    onError: (error) => setFormError(error.message),
  })

  const closeSession = useMutation({
    mutationFn: async (session: AttendanceSession) => {
      const { error } = await api.POST('/api/v1/attendance/sessions/{id}/close/', {
        params: { path: { id: session.id } },
      })
      assertApiSuccess(error, 'Attendance could not be closed.')
    },
    onSuccess: async () => {
      setFormError('')
      await invalidateScheduling()
    },
    onError: (error) => setFormError(error.message),
  })

  const slotsByGroup = useMemo(() => {
    const grouped = new Map<string, TimetableSlot[]>()
    for (const slot of slotsQuery.data ?? []) {
      const slots = grouped.get(slot.class_group) ?? []
      slots.push(slot)
      grouped.set(slot.class_group, slots)
    }
    return grouped
  }, [slotsQuery.data])

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <PageHeader title="Timetable & attendance" />
        {hasRole(profile, 'STUDENT') && <Link className="rounded border px-3 py-2 text-sm underline" to="/app/attendance/scan">Check in to class</Link>}
      </div>

      {formError && <p role="alert" className="rounded border border-danger/40 bg-danger/10 p-3 text-danger-fg">{formError}</p>}
      {(groupsQuery.isError || slotsQuery.isError || sessionsQuery.isError) && (
        <p role="alert" className="text-danger-fg">
          {groupsQuery.error?.message ?? slotsQuery.error?.message ?? sessionsQuery.error?.message}
        </p>
      )}

      {canManageGroups && (
        <form
          className="grid gap-3 rounded-xl border border-line bg-white p-4 sm:grid-cols-2 lg:grid-cols-4"
          onSubmit={(event) => {
            event.preventDefault()
            createRoom.mutate(new FormData(event.currentTarget))
            event.currentTarget.reset()
          }}
        >
          <h2 className="text-xl font-semibold sm:col-span-2 lg:col-span-4">Add a room</h2>
          <label className="text-sm">Department
            <select className="mt-1 w-full rounded border p-2" name="department" defaultValue="" required={hasRole(profile, 'HOD')}>
              <option value="">Shared room</option>
              {(departmentsQuery.data ?? []).map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}
            </select>
          </label>
          <label className="text-sm">Room name
            <input className="mt-1 w-full rounded border p-2" name="name" required maxLength={120} />
          </label>
          <label className="text-sm">Room code
            <input className="mt-1 w-full rounded border p-2" name="code" required maxLength={32} />
          </label>
          <label className="text-sm">Capacity
            <input className="mt-1 w-full rounded border p-2" name="capacity" type="number" min={1} defaultValue={30} />
          </label>
          <button className="rounded bg-primary px-4 py-2 text-primary-fg disabled:opacity-50" disabled={createRoom.isPending}>
            {createRoom.isPending ? 'Saving…' : 'Add room'}
          </button>
        </form>
      )}

      {canManageGroups && (
        <form
          className="grid gap-3 rounded-xl border border-line bg-white p-4 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault()
            createGroup.mutate(new FormData(event.currentTarget))
            event.currentTarget.reset()
          }}
        >
          <h2 className="text-xl font-semibold sm:col-span-2">Create a class group</h2>
          <label className="text-sm">Course
            <select className="mt-1 w-full rounded border p-2" name="course" required>
              <option value="">Select a course</option>
              {(coursesQuery.data ?? []).map((course) => <option key={course.id} value={course.id}>{course.title} ({course.code})</option>)}
            </select>
          </label>
          <label className="text-sm">Teacher
            <select className="mt-1 w-full rounded border p-2" name="teacher" required>
              <option value="">Select a teacher</option>
              {(teachersQuery.data ?? []).map((teacher) => <option key={teacher.id} value={teacher.id}>{teacher.display_name || teacher.email}</option>)}
            </select>
          </label>
          <label className="text-sm">Group name
            <input className="mt-1 w-full rounded border p-2" name="name" required maxLength={160} />
          </label>
          <label className="text-sm">Group code
            <input className="mt-1 w-full rounded border p-2" name="code" required maxLength={40} />
          </label>
          <label className="text-sm">Capacity
            <input className="mt-1 w-full rounded border p-2" name="capacity" type="number" min={1} defaultValue={40} />
          </label>
          <button className="self-end rounded bg-primary px-4 py-2 text-primary-fg disabled:opacity-50" disabled={createGroup.isPending}>
            {createGroup.isPending ? 'Creating…' : 'Create group'}
          </button>
        </form>
      )}

      {canManageOwnSchedule && (
        <form
          className="grid gap-3 rounded-xl border border-line bg-white p-4 sm:grid-cols-2 lg:grid-cols-4"
          onSubmit={(event) => {
            event.preventDefault()
            createSlot.mutate(new FormData(event.currentTarget))
            event.currentTarget.reset()
          }}
        >
          <h2 className="text-xl font-semibold sm:col-span-2 lg:col-span-4">Add a timetable slot</h2>
          <label className="text-sm">Class group
            <select className="mt-1 w-full rounded border p-2" name="class_group" required>
              <option value="">Select a group</option>
              {(groupsQuery.data ?? []).map((group) => <option key={group.id} value={group.id}>{group.course_title} — {group.name}</option>)}
            </select>
          </label>
          <label className="text-sm">Room
            <select className="mt-1 w-full rounded border p-2" name="room" defaultValue="">
              <option value="">No room assigned</option>
              {(roomsQuery.data ?? []).map((room) => <option key={room.id} value={room.id}>{room.name} ({room.code})</option>)}
            </select>
          </label>
          <label className="text-sm">Weekday
            <select className="mt-1 w-full rounded border p-2" name="weekday" required>
              {weekdays.map((day, index) => <option key={day} value={index}>{day}</option>)}
            </select>
          </label>
          <label className="text-sm">Effective from
            <input className="mt-1 w-full rounded border p-2" name="effective_from" type="date" required />
          </label>
          <label className="text-sm">Start time
            <input className="mt-1 w-full rounded border p-2" name="starts_at" type="time" required />
          </label>
          <label className="text-sm">End time
            <input className="mt-1 w-full rounded border p-2" name="ends_at" type="time" required />
          </label>
          <label className="text-sm">Effective until (optional)
            <input className="mt-1 w-full rounded border p-2" name="effective_until" type="date" />
          </label>
          <button className="self-end rounded bg-primary px-4 py-2 text-primary-fg disabled:opacity-50" disabled={createSlot.isPending}>
            {createSlot.isPending ? 'Saving…' : 'Add slot'}
          </button>
        </form>
      )}

      <div className="space-y-3">
        <h2 className="text-xl font-semibold">Class groups</h2>
        {groupsQuery.isPending && <p role="status">Loading class groups…</p>}
        {(groupsQuery.data ?? []).map((group) => {
          const sessions = (sessionsQuery.data ?? []).filter((session) => session.class_group === group.id)
          return (
            <article className="space-y-3 rounded-xl border border-line bg-white p-4" key={group.id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="font-semibold">{group.course_title} — {group.name}</h3>
                  <p className="text-sm text-subtle">{group.code} · {group.teacher_name}</p>
                </div>
                {canManageOwnSchedule && (
                  <button
                    className="rounded bg-primary px-3 py-2 text-sm text-primary-fg disabled:opacity-50"
                    disabled={openSession.isPending || sessions.some((session) => session.is_open)}
                    onClick={() => openSession.mutate(group)}
                  >
                    {sessions.some((session) => session.is_open) ? 'Attendance open' : 'Start attendance'}
                  </button>
                )}
              </div>
              <div className="space-y-1 text-sm">
                {(slotsByGroup.get(group.id) ?? []).map((slot) => (
                  <p key={slot.id}>
                    {weekdays[slot.weekday]} · {slot.starts_at.slice(0, 5)}–{slot.ends_at.slice(0, 5)}
                    {slot.room ? ` · ${roomsQuery.data?.find((room) => room.id === slot.room)?.name ?? 'Assigned room'}` : ''}
                    {' · '}from {slot.effective_from}
                  </p>
                ))}
                {(slotsByGroup.get(group.id) ?? []).length === 0 && <p className="text-subtle">No timetable slots yet.</p>}
              </div>
              {sessions.map((session) => {
                const qr = issuedQr[session.id]
                const scanUrl = qr
                  ? `${window.location.origin}/app/attendance/scan?token=${encodeURIComponent(qr.token)}`
                  : ''
                return (
                  <div className="space-y-2 border-t border-line pt-3" key={session.id}>
                    <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                      <span>{session.title || 'Attendance'} · {session.record_count} check-ins · {session.is_open ? 'Open' : 'Closed'}</span>
                      <div className="flex gap-3">
                        <button className="underline" onClick={() => setSelectedSession(session.id)}>View records</button>
                        {session.is_open && canManageOwnSchedule && (
                          <>
                            <button className="underline" onClick={() => issueQr.mutate(session)} disabled={issueQr.isPending}>Refresh QR</button>
                            <button className="underline" onClick={() => closeSession.mutate(session)} disabled={closeSession.isPending}>Close</button>
                          </>
                        )}
                      </div>
                    </div>
                    {qr && session.is_open && (
                      <div className="flex flex-wrap items-center gap-4 rounded border border-line p-3">
                        <QRCodeSVG value={scanUrl} size={160} level="M" />
                        <div className="space-y-1 text-sm">
                          <p>Scan this code to check in. It expires at {new Date(qr.expires_at).toLocaleTimeString()}.</p>
                          <p className="break-all font-mono">{qr.token}</p>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </article>
          )
        })}
        {groupsQuery.data?.length === 0 && <p className="text-subtle">No class groups are available for your account.</p>}
      </div>

      {selectedSession && (
        <section className="space-y-3 rounded-xl border border-line bg-white p-4">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-xl font-semibold">Attendance records</h2>
            <button className="text-sm underline" onClick={() => setSelectedSession('')}>Close</button>
          </div>
          {recordsQuery.isPending && <p role="status">Loading records…</p>}
          {recordsQuery.isError && <p role="alert" className="text-danger-fg">{recordsQuery.error.message}</p>}
          <ul className="divide-y divide-neutral-100">
            {(recordsQuery.data ?? []).map((record) => (
              <li className="flex flex-wrap justify-between gap-2 py-2 text-sm" key={record.id}>
                <span>{record.student_name} · {record.registration_number}</span>
                <span>{record.status} · {new Date(record.checked_in_at).toLocaleTimeString()}</span>
              </li>
            ))}
            {recordsQuery.data?.length === 0 && <li className="py-2 text-sm text-subtle">No students have checked in yet.</li>}
          </ul>
        </section>
      )}
    </section>
  )
}

export function AttendanceCheckIn() {
  const [searchParams] = useSearchParams()
  const [token, setToken] = useState(searchParams.get('token') ?? '')
  const [statusMessage, setStatusMessage] = useState('')
  const [pending, setPending] = useState(readPendingCheckIns)
  const queryClient = useQueryClient()

  useEffect(() => {
    localStorage.setItem(pendingCheckInsKey, JSON.stringify(pending))
  }, [pending])

  const sendPending = async (item: PendingCheckIn) => {
    const { error, response } = await api.POST('/api/v1/attendance/check-in/', {
      body: { token: item.token, client_checkin_id: item.client_checkin_id },
    })
    if (error) {
      if (response.status === 409) return
      if (response.status < 500) {
        const requestError = new Error(apiErrorMessage(error, 'This check-in can no longer be submitted.')) as Error & { status: number }
        requestError.status = response.status
        throw requestError
      }
      throw new TypeError('The attendance service is temporarily unavailable.')
    }
  }

  const retryPending = useCallback(async () => {
    if (!navigator.onLine || pending.length === 0) return
    const remaining: PendingCheckIn[] = []
    for (const item of pending) {
      try {
        await sendPending(item)
      } catch (error) {
        if (hasHttpStatus(error) && error.status < 500) {
          setStatusMessage(getErrorMessage(error, 'A saved check-in expired and was removed from the retry queue.'))
        } else {
          remaining.push(item)
        }
      }
    }
    setPending(remaining)
    if (remaining.length < pending.length) {
      setStatusMessage(`Synced ${pending.length - remaining.length} queued check-in${pending.length - remaining.length === 1 ? '' : 's'}.`)
      await queryClient.invalidateQueries({ queryKey: ['attendance-records'] })
    }
  }, [pending, queryClient])

  useEffect(() => {
    const handleOnline = () => { void retryPending() }
    window.addEventListener('online', handleOnline)
    return () => window.removeEventListener('online', handleOnline)
  }, [retryPending])

  const checkIn = useMutation({
    mutationFn: async (rawToken: string) => {
      const item = { token: rawToken.trim(), client_checkin_id: crypto.randomUUID() }
      if (!item.token) throw new Error('Enter a check-in code first.')
      if (!navigator.onLine) {
        setPending((current) => [...current, item])
        return 'queued'
      }
      try {
        await sendPending(item)
        return 'submitted'
      } catch (error) {
        if (!hasHttpStatus(error)) {
          setPending((current) => [...current, item])
          return 'queued'
        }
        throw error
      }
    },
    onSuccess: async (result) => {
      setStatusMessage(result === 'queued'
        ? 'You are offline. Your check-in is saved and will retry when you reconnect.'
        : 'Your attendance has been recorded.')
      setToken('')
      if (result === 'submitted') {
        await queryClient.invalidateQueries({ queryKey: ['attendance-records'] })
        await queryClient.invalidateQueries({ queryKey: ['attendance-sessions'] })
      }
    },
    onError: (error) => setStatusMessage(getErrorMessage(error, 'Attendance could not be recorded.')),
  })

  return (
    <section className="mx-auto max-w-xl space-y-5">
      <div>
        <PageHeader
          title="Class check-in"
          description="Scan the class QR code with your phone camera or enter its code below. Offline attempts are saved on this device for retry."
        />
      </div>
      <form
        className="space-y-3 rounded-xl border border-line bg-white p-4"
        onSubmit={(event) => {
          event.preventDefault()
          checkIn.mutate(token)
        }}
      >
        <label className="block text-sm font-medium" htmlFor="attendance-token">Attendance code</label>
        <input
          id="attendance-token"
          className="w-full rounded border border-line p-3 font-mono"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          autoComplete="off"
          required
        />
        <button className="w-full rounded bg-primary px-4 py-3 text-primary-fg disabled:opacity-50" disabled={checkIn.isPending}>
          {checkIn.isPending ? 'Submitting…' : 'Check in'}
        </button>
      </form>
      {statusMessage && <p role="status" className="rounded border border-line bg-white p-3">{statusMessage}</p>}
      {pending.length > 0 && (
        <div className="flex items-center justify-between gap-3 rounded border border-primary/40 bg-primary/15 p-3 text-sm">
          <span>{pending.length} check-in{pending.length === 1 ? '' : 's'} waiting to sync.</span>
          <button className="underline" onClick={() => void retryPending()} disabled={!navigator.onLine}>Retry now</button>
        </div>
      )}
    </section>
  )
}
