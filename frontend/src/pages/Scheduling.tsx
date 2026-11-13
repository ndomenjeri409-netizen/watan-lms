import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'
import { Plus } from 'lucide-react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { api } from '../api/client'
import type { components } from '../api/schema'
import { apiErrorMessage } from '../lib/apiError'
import { useMe } from '../features/me/useMe'
import { hasRole } from '../features/me/roles'
import { PageHeader } from '../app/PageHeader'
import { Button, Drawer, FormField, Input, Select, useToast } from '../components/ui'
import { t } from '../lib/i18n'

type ClassGroup = components['schemas']['ClassGroup']
type ClassTeacher = components['schemas']['ClassTeacher']
type CourseAssignment = components['schemas']['CourseAssignment']
type AcademicPeriod = components['schemas']['AcademicPeriod']
type TimetableSlot = components['schemas']['TimetableSlot']
type AttendanceSession = components['schemas']['AttendanceSession']
type AttendanceRecord = components['schemas']['AttendanceRecord']
type AttendanceRosterEntry = components['schemas']['AttendanceRosterEntry']
type QrIssue = components['schemas']['QrIssue']
type PendingCheckIn = { token: string; client_checkin_id: string }

const academicPeriodFormSchema = z.object({
  name: z.string().trim().min(1, t('Enter a period name.')).max(100),
  kind: z.enum(['TERM', 'INTAKE']),
  unit: z.string(),
  starts_on: z.string().min(1, t('Select a start date.')),
  ends_on: z.string().min(1, t('Select an end date.')),
}).refine((period) => period.ends_on >= period.starts_on, {
  path: ['ends_on'],
  message: t('The end date must be on or after the start date.'),
})
type AcademicPeriodForm = z.infer<typeof academicPeriodFormSchema>

const pendingCheckInsKey = 'watan-lms-pending-attendance'
const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const nextClassStatuses: Record<ClassGroup['status'], ClassGroup['status'][]> = {
  PLANNED: ['OPEN', 'CANCELLED'],
  OPEN: ['RUNNING', 'CANCELLED'],
  RUNNING: ['COMPLETED', 'CANCELLED'],
  COMPLETED: [],
  CANCELLED: [],
}

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
  const { toast } = useToast()
  const periodForm = useForm<AcademicPeriodForm>({
    resolver: zodResolver(academicPeriodFormSchema),
    defaultValues: { name: '', kind: 'TERM', unit: '', starts_on: '', ends_on: '' },
  })
  const [formError, setFormError] = useState('')
  const [issuedQr, setIssuedQr] = useState<Record<string, QrIssue>>({})
  const [selectedSession, setSelectedSession] = useState('')
  const [attendanceMarkDrafts, setAttendanceMarkDrafts] = useState<
    Record<string, Record<string, AttendanceRecord['status']>>
  >({})
  const [newGroupCourseId, setNewGroupCourseId] = useState('')
  const [newGroupPeriodId, setNewGroupPeriodId] = useState('')
  const [periodDrawerOpen, setPeriodDrawerOpen] = useState(false)
  const [assistantSelections, setAssistantSelections] = useState<Record<string, string>>({})
  const canManageGroups = hasRole(profile, 'SUPER_ADMIN', 'ADMIN', 'HOD', 'UNIT_MANAGER')
  const canManagePeriods = hasRole(profile, 'SUPER_ADMIN', 'ADMIN')
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
  const periodsQuery = useQuery({
    queryKey: ['academic-periods', 'scheduling'],
    enabled: canManageGroups,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/academic-periods/')
      assertApiSuccess(error, 'Unable to load academic periods.')
      if (!data) throw new Error('The server returned no academic periods.')
      return data.results
    },
  })
  const activePeriods = (periodsQuery.data ?? []).filter(
    (period) => period.is_active && period.kind !== null,
  )
  const selectedCourse = coursesQuery.data?.find((course) => course.id === newGroupCourseId)
  const eligiblePeriods = activePeriods.filter(
    (period) => !period.unit || period.unit === selectedCourse?.unit,
  )
  const unitsQuery = useQuery({
    queryKey: ['units', 'academic-period-form'],
    enabled: canManagePeriods,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/units')
      assertApiSuccess(error, 'Unable to load business units.')
      if (!data) throw new Error('The server returned no business units.')
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
  const classTeachersQuery = useQuery({
    queryKey: ['class-teachers'],
    enabled: canManageGroups,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/class-teachers/', {
        params: { query: { is_active: true, page_size: 100 } },
      })
      assertApiSuccess(error, 'Unable to load class teachers.')
      if (!data) throw new Error('The server returned no class teachers.')
      return data.results
    },
  })
  const courseTeachersQuery = useQuery({
    queryKey: ['course-assignments', 'workload'],
    enabled: canManageGroups,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/course-assignments/', {
        params: { query: { is_active: true, page_size: 100 } },
      })
      assertApiSuccess(error, 'Unable to load course-teacher assignments.')
      if (!data) throw new Error('The server returned no course-teacher assignments.')
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
  const rosterQuery = useQuery({
    queryKey: ['attendance-roster', selectedSession],
    enabled: Boolean(selectedSession) && canManageOwnSchedule,
    queryFn: async () => {
      const roster: AttendanceRosterEntry[] = []
      let page = 1
      let hasNextPage = true
      while (hasNextPage) {
        const { data, error } = await api.GET('/api/v1/attendance/sessions/{id}/roster/', {
          params: {
            path: { id: selectedSession },
            query: { page, page_size: 100 },
          },
        })
        assertApiSuccess(error, 'Unable to load the class attendance roster.')
        if (!data) throw new Error('The server returned no attendance roster.')
        roster.push(...data.results)
        hasNextPage = Boolean(data.next)
        page += 1
      }
      return roster
    },
  })

  const invalidateScheduling = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['class-groups'] }),
      queryClient.invalidateQueries({ queryKey: ['class-teachers'] }),
      queryClient.invalidateQueries({ queryKey: ['course-assignments', 'workload'] }),
      queryClient.invalidateQueries({ queryKey: ['timetable'] }),
      queryClient.invalidateQueries({ queryKey: ['attendance-sessions'] }),
    ])
  }

  const createGroup = useMutation({
    mutationFn: async (form: FormData) => {
      const { data, error } = await api.POST('/api/v1/class-groups/', {
        body: {
          course: form.get('course')?.toString() ?? '',
          lead_teacher: form.get('lead_teacher')?.toString() ?? '',
          academic_period: form.get('academic_period')?.toString() ?? '',
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

  const createAcademicPeriod = useMutation({
    mutationFn: async (form: AcademicPeriodForm) => {
      const { data, error } = await api.POST('/api/v1/academic-periods/', {
        body: {
          name: form.name,
          starts_on: form.starts_on,
          ends_on: form.ends_on,
          kind: form.kind,
          unit: form.unit || null,
          is_current: false,
          is_active: true,
        },
      })
      assertApiSuccess(error, 'The academic period could not be created.')
      if (!data) throw new Error('The server returned no academic period.')
      return data
    },
    onSuccess: async () => {
      setFormError('')
      setPeriodDrawerOpen(false)
      periodForm.reset()
      toast({ title: t('Academic period created'), variant: 'success' })
      await queryClient.invalidateQueries({ queryKey: ['academic-periods', 'scheduling'] })
    },
    onError: (error) => {
      setFormError(error.message)
      toast({ title: t('Academic period could not be created'), description: error.message, variant: 'error' })
    },
  })

  const assignClassTeacher = useMutation({
    mutationFn: async ({
      groupId,
      teacherId,
      role,
    }: {
      groupId: string
      teacherId: string
      role: 'LEAD' | 'ASSISTANT'
    }) => {
      const { error } = await api.POST('/api/v1/class-teachers/', {
        body: { class_group: groupId, teacher: teacherId, role },
      })
      assertApiSuccess(error, 'The teacher could not be assigned to this class.')
    },
    onSuccess: async () => {
      setFormError('')
      setAssistantSelections({})
      await invalidateScheduling()
    },
    onError: (error) => setFormError(error.message),
  })

  const unassignClassTeacher = useMutation({
    mutationFn: async (assignmentId: string) => {
      const { error } = await api.DELETE('/api/v1/class-teachers/{id}/', {
        params: { path: { id: assignmentId } },
      })
      assertApiSuccess(error, 'The teacher could not be unassigned.')
    },
    onSuccess: async () => {
      setFormError('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['class-teachers'] }),
        queryClient.invalidateQueries({ queryKey: ['course-assignments', 'workload'] }),
      ])
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

  const transitionClassGroup = useMutation({
    mutationFn: async ({
      groupId,
      status,
    }: {
      groupId: string
      status: ClassGroup['status']
    }) => {
      const { error } = await api.POST('/api/v1/class-groups/{id}/transition/', {
        params: { path: { id: groupId } },
        body: { status },
      })
      assertApiSuccess(error, 'The class status could not be changed.')
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

  const markAttendance = useMutation({
    mutationFn: async ({ sessionId, records }: {
      sessionId: string
      records: { student: string; status: AttendanceRecord['status'] }[]
    }) => {
      const { data, error } = await api.POST('/api/v1/attendance/sessions/{id}/mark/', {
        params: { path: { id: sessionId } },
        body: { records },
      })
      assertApiSuccess(error, 'Attendance marks could not be saved.')
      if (!data) throw new Error('The server returned no attendance records.')
      return data
    },
    onSuccess: async () => {
      setFormError('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['attendance-records', selectedSession] }),
        queryClient.invalidateQueries({ queryKey: ['attendance-roster', selectedSession] }),
        queryClient.invalidateQueries({ queryKey: ['attendance-sessions'] }),
      ])
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
  const attendanceRoster = rosterQuery.data ?? []

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <PageHeader title="Timetable & attendance" />
        <div className="flex flex-wrap items-center gap-2">
          {canManagePeriods && (
            <Button type="button" variant="secondary" onClick={() => setPeriodDrawerOpen(true)}>
              <Plus size={16} aria-hidden="true" />
              {t('Add academic period')}
            </Button>
          )}
          {hasRole(profile, 'STUDENT') && <Link className="rounded border px-3 py-2 text-sm underline" to="/app/attendance/scan">Check in to class</Link>}
        </div>
      </div>

      {formError && <p role="alert" className="rounded border border-danger/40 bg-danger/10 p-3 text-danger-fg">{formError}</p>}
      {(groupsQuery.isError || slotsQuery.isError || sessionsQuery.isError || classTeachersQuery.isError || courseTeachersQuery.isError || teachersQuery.isError || periodsQuery.isError || unitsQuery.isError) && (
        <p role="alert" className="text-danger-fg">
          {groupsQuery.error?.message ?? slotsQuery.error?.message ?? sessionsQuery.error?.message ?? classTeachersQuery.error?.message ?? courseTeachersQuery.error?.message ?? teachersQuery.error?.message ?? periodsQuery.error?.message ?? unitsQuery.error?.message}
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
            setNewGroupCourseId('')
            setNewGroupPeriodId('')
          }}
        >
          <h2 className="text-xl font-semibold sm:col-span-2">Create a class group</h2>
          <label className="text-sm">Course
            <select
              className="mt-1 w-full rounded border p-2"
              name="course"
              value={newGroupCourseId}
              onChange={(event) => {
                setNewGroupCourseId(event.target.value)
                setNewGroupPeriodId('')
              }}
              required
            >
              <option value="">Select a course</option>
              {(coursesQuery.data ?? []).filter((course) => course.is_active && course.status === 'PUBLISHED').map((course) => <option key={course.id} value={course.id}>{course.title} ({course.code})</option>)}
            </select>
          </label>
          <label className="text-sm">{t('Lead teacher')}
            <select className="mt-1 w-full rounded border p-2" name="lead_teacher" required>
              <option value="">{t('Select a lead teacher')}</option>
              {(teachersQuery.data ?? []).filter((teacher) => {
                const course = coursesQuery.data?.find((item) => item.id === newGroupCourseId)
                return course && teacher.assignments.some(
                  (assignment) => assignment.role === 'TEACHER' && assignment.unit?.id === course.unit,
                )
              }).map((teacher) => <option key={teacher.id} value={teacher.id}>{teacher.display_name || teacher.email}</option>)}
            </select>
          </label>
          <label className="text-sm">Academic period
            <select
              className="mt-1 w-full rounded border p-2"
              name="academic_period"
              value={newGroupPeriodId}
              onChange={(event) => setNewGroupPeriodId(event.target.value)}
              required
              disabled={periodsQuery.isPending || eligiblePeriods.length === 0}
            >
              <option value="">{periodsQuery.isPending ? 'Loading periods…' : 'Select a period'}</option>
              {eligiblePeriods.map((period: AcademicPeriod) => <option key={period.id} value={period.id}>{period.name} ({period.kind?.toLowerCase()})</option>)}
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
          {eligiblePeriods.length === 0 && !periodsQuery.isPending && (
            <p className="text-sm text-subtle sm:col-span-2">
              {activePeriods.length === 0
                ? 'Create a classified, active academic period before scheduling a class.'
                : 'No active period matches this course’s business unit.'}
            </p>
          )}
        </form>
      )}

      {canManageGroups && (
        <section className="space-y-3 rounded-xl border border-line bg-white p-4">
          <h2 className="text-xl font-semibold">Teacher workload</h2>
          <ul className="divide-y divide-line">
            {(teachersQuery.data ?? []).map((teacher) => {
              const classCount = (classTeachersQuery.data ?? []).filter(
                (assignment) => assignment.teacher === teacher.id,
              ).length
              const courseCount = (courseTeachersQuery.data ?? []).filter(
                (assignment: CourseAssignment) =>
                  assignment.teacher === teacher.id && assignment.can_edit_content,
              ).length
              return (
                <li className="flex flex-wrap justify-between gap-2 py-2 text-sm" key={teacher.id}>
                  <span>{teacher.display_name || teacher.email}</span>
                  <span>{classCount} classes · {courseCount} courses with content access</span>
                </li>
              )
            })}
            {teachersQuery.data?.length === 0 && <li className="py-2 text-sm text-subtle">No teachers are assigned to your units.</li>}
          </ul>
        </section>
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
          const course = coursesQuery.data?.find((item) => item.id === group.course)
          const classTeachers = (classTeachersQuery.data ?? []).filter((assignment) => assignment.class_group === group.id)
          const assignedTeacherIds = new Set(classTeachers.map((assignment) => assignment.teacher))
          const unitTeachers = (teachersQuery.data ?? []).filter((teacher) =>
            course && teacher.assignments.some(
              (assignment) => assignment.role === 'TEACHER' && assignment.unit?.id === course.unit,
            ),
          )
          return (
            <article className="space-y-3 rounded-xl border border-line bg-white p-4" key={group.id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="font-semibold">{group.course_title} — {group.name}</h3>
                  <p className="text-sm text-subtle">
                    {group.code} · {group.lead_teacher_name ?? t('Lead teacher not assigned')} · {group.status.toLowerCase()}
                  </p>
                </div>
                {canManageOwnSchedule && (
                  <button
                    className="rounded bg-primary px-3 py-2 text-sm text-primary-fg disabled:opacity-50"
                    disabled={group.status !== 'RUNNING' || openSession.isPending || sessions.some((session) => session.is_open)}
                    onClick={() => openSession.mutate(group)}
                  >
                    {sessions.some((session) => session.is_open) ? 'Attendance open' : group.status === 'RUNNING' ? 'Start attendance' : 'Class must be running'}
                  </button>
                )}
              </div>
              {canManageGroups && nextClassStatuses[group.status].length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {nextClassStatuses[group.status].map((status) => (
                    <button
                      className="rounded border border-line px-3 py-2 text-sm disabled:opacity-50"
                      disabled={transitionClassGroup.isPending}
                      key={status}
                      onClick={() => transitionClassGroup.mutate({ groupId: group.id, status })}
                    >
                      {status === 'RUNNING' ? 'Start class' : status === 'COMPLETED' ? 'Complete class' : status === 'CANCELLED' ? 'Cancel class' : 'Open class'}
                    </button>
                  ))}
                </div>
              )}
              {canManageGroups && (
                <section className="space-y-2 border-t border-line pt-3">
                  <h4 className="font-medium">Class teachers</h4>
                  <ul className="space-y-1 text-sm">
                    {classTeachers.map((assignment: ClassTeacher) => (
                      <li className="flex items-center justify-between gap-2" key={assignment.id}>
                        <span>{assignment.teacher_name || assignment.teacher_email} · {assignment.role === 'LEAD' ? 'Lead' : 'Assistant'}</span>
                        {assignment.role === 'ASSISTANT' && (
                          <div className="flex items-center gap-3">
                            <Button
                              type="button"
                              variant="secondary"
                              size="sm"
                              disabled={assignClassTeacher.isPending}
                              onClick={() => assignClassTeacher.mutate({
                                groupId: group.id,
                                teacherId: assignment.teacher,
                                role: 'LEAD',
                              })}
                            >
                              {t('Make lead')}
                            </Button>
                          <button
                            className="underline disabled:opacity-50"
                            disabled={unassignClassTeacher.isPending}
                            onClick={() => unassignClassTeacher.mutate(assignment.id)}
                          >
                            Unassign
                          </button>
                          </div>
                        )}
                      </li>
                    ))}
                    {classTeachers.length === 0 && <li className="text-subtle">No assignment records yet.</li>}
                  </ul>
                  <form
                    className="flex flex-wrap gap-2"
                    onSubmit={(event) => {
                      event.preventDefault()
                      const teacherId = assistantSelections[group.id]
                      if (teacherId) assignClassTeacher.mutate({ groupId: group.id, teacherId, role: 'ASSISTANT' })
                    }}
                  >
                    <select
                      aria-label={`Add a teacher to ${group.name}`}
                      className="min-w-48 flex-1 rounded border p-2"
                      value={assistantSelections[group.id] ?? ''}
                      onChange={(event) => setAssistantSelections((current) => ({
                        ...current,
                        [group.id]: event.target.value,
                      }))}
                    >
                      <option value="">Select a unit teacher</option>
                      {unitTeachers.filter((teacher) => !assignedTeacherIds.has(teacher.id)).map((teacher) => (
                        <option key={teacher.id} value={teacher.id}>{teacher.display_name || teacher.email}</option>
                      ))}
                    </select>
                    <button
                      className="rounded border border-line px-3 py-2 text-sm disabled:opacity-50"
                      disabled={!assistantSelections[group.id] || assignClassTeacher.isPending}
                    >
                      {assignClassTeacher.isPending ? 'Assigning…' : 'Assign assistant'}
                    </button>
                  </form>
                </section>
              )}
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
          {canManageOwnSchedule && (
            <section className="space-y-3 border-b border-line pb-4">
              <h3 className="font-semibold">{t('Class roster')}</h3>
              {rosterQuery.isPending && <p role="status">{t('Loading class roster…')}</p>}
              {rosterQuery.isError && <p role="alert" className="text-danger-fg">{rosterQuery.error.message}</p>}
              {attendanceRoster.length > 0 && (
                <form
                  className="space-y-3"
                  onSubmit={(event) => {
                    event.preventDefault()
                    const records = attendanceRoster.map((entry) => ({
                      student: entry.student,
                      status: attendanceMarkDrafts[selectedSession]?.[entry.student]
                        ?? entry.status
                        ?? 'ABSENT',
                    }))
                    markAttendance.mutate({ sessionId: selectedSession, records })
                  }}
                >
                  <div className="space-y-2">
                    {attendanceRoster.map((entry) => (
                      <label className="flex flex-wrap items-center justify-between gap-3 rounded border border-line p-3 text-sm" key={entry.student}>
                        <span>
                          {entry.student_name} · {entry.registration_number}
                          {entry.status === null && <span className="ml-2 text-subtle">{t('Not marked')}</span>}
                        </span>
                        <Select
                          className="w-36"
                          value={attendanceMarkDrafts[selectedSession]?.[entry.student] ?? entry.status ?? 'ABSENT'}
                          onChange={(event) => setAttendanceMarkDrafts((current) => ({
                            ...current,
                            [selectedSession]: {
                              ...current[selectedSession],
                              [entry.student]: event.target.value as AttendanceRecord['status'],
                            },
                          }))}
                        >
                          <option value="PRESENT">{t('Present')}</option>
                          <option value="ABSENT">{t('Absent')}</option>
                          <option value="LATE">{t('Late')}</option>
                          <option value="EXCUSED">{t('Excused')}</option>
                        </Select>
                      </label>
                    ))}
                  </div>
                  <Button loading={markAttendance.isPending}>{t('Save attendance')}</Button>
                </form>
              )}
              {rosterQuery.data && attendanceRoster.length === 0 && <p className="text-sm text-subtle">{t('No active enrollments in this class roster.')}</p>}
            </section>
          )}
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

      <Drawer
        open={periodDrawerOpen}
        onOpenChange={(open) => {
          setPeriodDrawerOpen(open)
          if (!open) periodForm.reset()
        }}
        title={t('Add academic period')}
        description={t('Choose a fixed term or rolling intake. Leave the unit blank for a group-wide period.')}
      >
        <form
          className="space-y-5"
          onSubmit={periodForm.handleSubmit((values) => createAcademicPeriod.mutate(values))}
        >
          <FormField label={t('Period name')} error={periodForm.formState.errors.name?.message}>
            <Input {...periodForm.register('name')} maxLength={100} required />
          </FormField>
          <FormField label={t('Period type')} error={periodForm.formState.errors.kind?.message}>
            <Select {...periodForm.register('kind')} required>
              <option value="TERM">{t('Term')}</option>
              <option value="INTAKE">{t('Intake')}</option>
            </Select>
          </FormField>
          <FormField
            label={t('Business unit')}
            hint={t("Optional; a unit-specific period is only available to that unit's classes.")}
            error={unitsQuery.error?.message}
          >
            <Select {...periodForm.register('unit')} disabled={unitsQuery.isPending || unitsQuery.isError}>
              <option value="">{t('All units')}</option>
              {(unitsQuery.data ?? []).map((unit) => <option key={unit.id} value={unit.id}>{unit.name}</option>)}
            </Select>
          </FormField>
          <FormField label={t('Starts on')} error={periodForm.formState.errors.starts_on?.message}>
            <Input {...periodForm.register('starts_on')} type="date" required />
          </FormField>
          <FormField label={t('Ends on')} error={periodForm.formState.errors.ends_on?.message}>
            <Input {...periodForm.register('ends_on')} type="date" required />
          </FormField>
          <div className="flex justify-end gap-2 border-t border-line pt-4">
            <Button type="button" variant="secondary" onClick={() => setPeriodDrawerOpen(false)}>{t('Cancel')}</Button>
            <Button type="submit" loading={createAcademicPeriod.isPending}>
              <Plus size={16} aria-hidden="true" />
              {t('Add period')}
            </Button>
          </div>
        </form>
      </Drawer>
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
