import { useQuery } from '@tanstack/react-query'
import { ArrowRight, BookOpen, CalendarDays, ClipboardCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { components } from '../api/schema'
import { useMe } from '../features/me/useMe'
import { hasRole, primaryRole, type Role } from '../features/me/roles'
import { useUnit } from '../features/units/useUnit'
import { PageHeader } from './PageHeader'
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  Skeleton,
  StatCard,
} from '../components/ui'
import { dashboardFor } from './dashboard-config'

type Profile = components['schemas']['Me']
type TimetableSlot = components['schemas']['TimetableSlot']
type ClassGroup = components['schemas']['ClassGroup']
type Room = components['schemas']['Room']
type Assessment = components['schemas']['Assessment']
type Overview = Record<string, number>

interface ScheduleItem {
  slot: TimetableSlot
  group: ClassGroup
  room?: Room
}

interface GradingItem {
  assessment: Assessment
  count: number
}

function assertApiSuccess(error: unknown, fallback: string) {
  if (error) {
    const message = typeof error === 'object' && error !== null && 'message' in error
      ? String(error.message)
      : fallback
    throw new Error(message || fallback)
  }
}

function localDate(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

async function loadTodaySchedule(): Promise<ScheduleItem[]> {
  const [slotsResponse, groupsResponse, roomsResponse] = await Promise.all([
    api.GET('/api/v1/timetable/', { params: { query: { page_size: 100 } } }),
    api.GET('/api/v1/class-groups/', { params: { query: { page_size: 100 } } }),
    api.GET('/api/v1/rooms/', { params: { query: { page_size: 100 } } }),
  ])
  assertApiSuccess(slotsResponse.error, "Today's timetable could not be loaded.")
  assertApiSuccess(groupsResponse.error, "Today's class groups could not be loaded.")
  assertApiSuccess(roomsResponse.error, "Today's room list could not be loaded.")
  if (!slotsResponse.data || !groupsResponse.data || !roomsResponse.data) {
    throw new Error("Today's schedule data was incomplete.")
  }

  const now = new Date()
  const today = localDate(now)
  const weekday = (now.getDay() + 6) % 7
  const groups = new Map(groupsResponse.data.results.map((group) => [group.id, group]))
  const rooms = new Map(roomsResponse.data.results.map((room) => [room.id, room]))

  return slotsResponse.data.results
    .filter((slot) =>
      slot.is_active !== false
      && slot.weekday === weekday
      && slot.effective_from <= today
      && (!slot.effective_until || slot.effective_until >= today),
    )
    .flatMap((slot) => {
      const group = groups.get(slot.class_group)
      if (!group || group.is_active === false) return []
      return [{
        slot,
        group,
        room: slot.room ? rooms.get(slot.room) : undefined,
      }]
    })
    .sort((left, right) => left.slot.starts_at.localeCompare(right.slot.starts_at))
}

async function loadGradingQueue(): Promise<GradingItem[]> {
  const [assessmentsResponse, submissionsResponse, gradesResponse] = await Promise.all([
    api.GET('/api/v1/assessments/', { params: { query: { page_size: 100 } } }),
    api.GET('/api/v1/submissions/', { params: { query: { page_size: 100 } } }),
    api.GET('/api/v1/grades/', { params: { query: { page_size: 100 } } }),
  ])
  assertApiSuccess(assessmentsResponse.error, 'Assessments could not be loaded.')
  assertApiSuccess(submissionsResponse.error, 'Submissions could not be loaded.')
  assertApiSuccess(gradesResponse.error, 'Grades could not be loaded.')
  if (!assessmentsResponse.data || !submissionsResponse.data || !gradesResponse.data) {
    throw new Error('Grading queue data was incomplete.')
  }

  const gradedSubmissionIds = new Set(gradesResponse.data.results.map((grade) => grade.submission))
  const assessmentById = new Map(assessmentsResponse.data.results.map((assessment) => [assessment.id, assessment]))
  const counts = new Map<string, number>()

  for (const submission of submissionsResponse.data.results) {
    if (!gradedSubmissionIds.has(submission.id) && assessmentById.has(submission.assessment)) {
      counts.set(submission.assessment, (counts.get(submission.assessment) ?? 0) + 1)
    }
  }

  return [...counts].flatMap(([assessmentId, count]) => {
    const assessment = assessmentById.get(assessmentId)
    return assessment ? [{ assessment, count }] : []
  })
}

function GettingStarted({ overview }: { overview: Overview }) {
  const steps = [
    { label: 'Create departments', done: (overview.departments ?? 0) > 0, to: '/app/departments' },
    { label: 'Add programs and courses', done: (overview.programs ?? 0) > 0 && (overview.courses ?? 0) > 0, to: '/app/courses' },
    { label: 'Invite teachers and staff', done: (overview.staff ?? 0) > 0, to: '/app/users' },
    { label: 'Admit and enrol students', done: (overview.students ?? 0) > 0, to: '/app/admissions' },
    { label: 'Set up fee structures', done: false, unavailable: true as const },
  ]
  const availableSteps = steps.filter((step) => !step.unavailable)
  const completed = availableSteps.filter((step) => step.done).length
  const progress = (completed / availableSteps.length) * 100

  return (
    <Card>
      <CardHeader>
        <CardTitle>Getting started</CardTitle>
        <p className="text-sm text-subtle">{completed} of {availableSteps.length} available setup steps complete</p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div
          className="h-2 overflow-hidden rounded-full bg-app"
          role="progressbar"
          aria-label="Getting started progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress}
        >
          <div className="h-full rounded-full bg-primary" style={{ width: `${progress}%` }} />
        </div>
        <ol className="space-y-3">
          {steps.map((step, index) => (
            <li key={step.label} className="flex items-start gap-3 text-sm">
              <span className={step.done ? 'font-semibold text-success-fg' : 'font-semibold text-subtle'}>{index + 1}.</span>
              {step.unavailable
                ? <span className="text-subtle">{step.label} <span className="text-xs">(not available yet)</span></span>
                : step.done
                  ? <span>{step.label}</span>
                  : <Link className="underline underline-offset-2 hover:text-fg" to={step.to}>{step.label}</Link>}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  )
}

function TeacherActions({
  schedule,
  scheduleLoading,
  scheduleError,
  refetchSchedule,
  grading,
  gradingLoading,
  gradingError,
  refetchGrading,
}: {
  schedule: ScheduleItem[]
  scheduleLoading: boolean
  scheduleError?: string
  refetchSchedule: () => void
  grading: GradingItem[]
  gradingLoading: boolean
  gradingError?: string
  refetchGrading: () => void
}) {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><CalendarDays size={18} aria-hidden="true" />Today's schedule</CardTitle></CardHeader>
        <CardContent>
          {scheduleLoading ? <Skeleton className="h-28 w-full" /> : scheduleError ? (
            <div role="alert" className="space-y-2 text-sm">
              <p>{scheduleError}</p>
              <button type="button" className="underline" onClick={refetchSchedule}>Retry</button>
            </div>
          ) : schedule.length === 0 ? (
            <EmptyState
              icon={<CalendarDays size={24} />}
              title="No classes scheduled today"
              description="Your current timetable will appear here."
              action={<Button variant="secondary" size="sm" asChild><Link to="/app/timetable">Open timetable</Link></Button>}
              className="py-6"
            />
          ) : (
            <ul className="divide-y divide-line">
              {schedule.map(({ slot, group, room }) => (
                <li key={slot.id} className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
                  <div className="min-w-0">
                    <p className="font-medium">{group.course_title} · {group.name}</p>
                    <p className="text-sm text-subtle">{slot.starts_at.slice(0, 5)}–{slot.ends_at.slice(0, 5)}{room ? ` · ${room.name}` : ''}</p>
                  </div>
                  <Button variant="secondary" size="sm" asChild><Link to="/app/timetable">Take attendance</Link></Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><ClipboardCheck size={18} aria-hidden="true" />Needs grading</CardTitle></CardHeader>
        <CardContent>
          {gradingLoading ? <Skeleton className="h-28 w-full" /> : gradingError ? (
            <div role="alert" className="space-y-2 text-sm">
              <p>{gradingError}</p>
              <button type="button" className="underline" onClick={refetchGrading}>Retry</button>
            </div>
          ) : grading.length === 0 ? (
            <EmptyState
              icon={<BookOpen size={24} />}
              title="No submissions awaiting grading"
              description="Create an assessment or review submissions in the assessment workspace."
              action={<Button variant="secondary" size="sm" asChild><Link to="/app/assessments">Open assessments</Link></Button>}
              className="py-6"
            />
          ) : (
            <ul className="divide-y divide-line">
              {grading.map(({ assessment, count }) => (
                <li key={assessment.id} className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{assessment.title}</p>
                    <p className="text-sm text-subtle">{assessment.class_group_name ?? assessment.course_title}</p>
                  </div>
                  <Button variant="secondary" size="sm" asChild>
                    <Link to="/app/assessments">{count} to grade</Link>
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function DashboardQueryView({ profile, role }: { profile: Profile; role: Role }) {
  const unit = useUnit()
  const overviewQuery = useQuery({
    queryKey: ['dashboard-overview', profile.id, unit.unitId],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/reports/overview', {
        params: { query: { unit: unit.unitId } },
      })
      assertApiSuccess(error, 'Dashboard metrics could not be loaded.')
      if (!data) throw new Error('The server returned no dashboard metrics.')
      const overview: Overview = {}
      for (const [key, value] of Object.entries(data)) {
        if (typeof value === 'number') overview[key] = value
      }
      return overview
    },
  })
  const scheduleQuery = useQuery({
    queryKey: ['dashboard-today-schedule', profile.id],
    enabled: hasRole(profile, 'TEACHER'),
    queryFn: loadTodaySchedule,
  })
  const gradingQuery = useQuery({
    queryKey: ['dashboard-grading-queue', profile.id],
    enabled: hasRole(profile, 'TEACHER'),
    queryFn: loadGradingQueue,
  })

  return (
    <DashboardView
      profile={profile}
      role={role}
      unitLabel={unit.unitLabel}
      overview={overviewQuery.data}
      overviewLoading={overviewQuery.isPending}
      overviewError={overviewQuery.error?.message}
      refetchOverview={() => void overviewQuery.refetch()}
      schedule={scheduleQuery.data ?? []}
      scheduleLoading={scheduleQuery.isPending}
      scheduleError={scheduleQuery.error?.message}
      refetchSchedule={() => void scheduleQuery.refetch()}
      grading={gradingQuery.data ?? []}
      gradingLoading={gradingQuery.isPending}
      gradingError={gradingQuery.error?.message}
      refetchGrading={() => void gradingQuery.refetch()}
    />
  )
}

export function Dashboard() {
  const { data: profile } = useMe()
  const role = profile ? primaryRole(profile) : null
  if (!profile || !role) return null

  return <DashboardQueryView profile={profile} role={role} />
}

export function DashboardView({
  profile,
  role,
  unitLabel,
  overview,
  overviewLoading = false,
  overviewError,
  refetchOverview,
  schedule = [],
  scheduleLoading = false,
  scheduleError,
  refetchSchedule = () => undefined,
  grading = [],
  gradingLoading = false,
  gradingError,
  refetchGrading = () => undefined,
}: {
  profile: Profile
  role: Role
  unitLabel?: string
  overview?: Overview
  overviewLoading?: boolean
  overviewError?: string
  refetchOverview?: () => void
  schedule?: ScheduleItem[]
  scheduleLoading?: boolean
  scheduleError?: string
  refetchSchedule?: () => void
  grading?: GradingItem[]
  gradingLoading?: boolean
  gradingError?: string
  refetchGrading?: () => void
}) {
  const activeUnitLabel = unitLabel ?? (profile.is_global_read ? 'All units' : 'Your unit')
  const config = dashboardFor(role)
  const metrics = config.stats.filter(({ key }) => overview && key in overview)
  const showMetrics = overviewLoading || Boolean(overviewError) || metrics.length > 0

  return (
    <div className="space-y-8">
      <PageHeader
        title={`Welcome, ${profile.display_name.trim() || profile.email.split('@')[0]}`}
        description={`${activeUnitLabel} overview of your learning management workspace.`}
      />

      {showMetrics && (
        <section aria-label={`${activeUnitLabel} key metrics`} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {overviewLoading && config.stats.map((stat) => (
            <StatCard key={stat.key} label={stat.label} loading />
          ))}
          {!overviewLoading && overviewError && (
            <StatCard label="Dashboard metrics" error={overviewError} onRetry={refetchOverview} />
          )}
          {!overviewLoading && !overviewError && metrics.map((stat) => (
            <StatCard key={stat.key} label={stat.label} value={overview?.[stat.key]} />
          ))}
        </section>
      )}

      {hasRole(profile, 'ADMIN', 'SUPER_ADMIN') ? (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(18rem,1fr)]">
          {overviewError ? (
            <Card role="alert"><CardContent className="space-y-2 pt-5">
              <p>Getting started progress requires dashboard metrics.</p>
              <button type="button" className="text-sm underline" onClick={refetchOverview}>Retry</button>
            </CardContent></Card>
          ) : overviewLoading ? <Skeleton className="h-72 w-full" /> : <GettingStarted overview={overview ?? {}} />}
          <Card>
            <CardHeader><CardTitle>Quick actions</CardTitle></CardHeader>
            <CardContent className="grid gap-2">
              {config.actions.map((action) => (
                <Button key={action.to} variant="secondary" asChild className="justify-between">
                  <Link to={action.to}>{action.label}<ArrowRight size={16} aria-hidden="true" /></Link>
                </Button>
              ))}
            </CardContent>
          </Card>
        </div>
      ) : hasRole(profile, 'TEACHER') ? (
        <TeacherActions
          schedule={schedule}
          scheduleLoading={scheduleLoading}
          scheduleError={scheduleError}
          refetchSchedule={refetchSchedule}
          grading={grading}
          gradingLoading={gradingLoading}
          gradingError={gradingError}
          refetchGrading={refetchGrading}
        />
      ) : (
        <Card>
          <CardHeader><CardTitle>Quick actions</CardTitle></CardHeader>
          <CardContent className="grid gap-2 sm:grid-cols-2">
            {config.actions.map((action) => (
              <Button key={action.to} variant="secondary" asChild className="justify-between">
                <Link to={action.to}>{action.label}<ArrowRight size={16} aria-hidden="true" /></Link>
              </Button>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
