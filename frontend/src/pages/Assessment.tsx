import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { components } from '../api/schema'
import { apiErrorMessage } from '../lib/apiError'
import { PageHeader } from '../app/PageHeader'
import { auth } from '../lib/firebase'
import { t } from '../lib/i18n'
import { useMe } from '../features/me/useMe'
import { hasRole } from '../features/me/roles'
import { Button } from '../components/ui'

type Assessment = components['schemas']['Assessment']
type AssessmentTemplate = components['schemas']['AssessmentTemplate']
type Submission = components['schemas']['Submission']
type Grade = components['schemas']['Grade']
type GradeRevision = components['schemas']['GradeRevision']
type AssessmentKind = 'ASSIGNMENT' | 'QUIZ' | 'EXAM' | 'PROJECT'

type TranscriptVersionSummary = {
  version: number
  is_revised: boolean
  revision_date: string | null
  created_at: string
}

function assertApiSuccess(error: unknown, fallback: string) {
  if (error) throw new Error(apiErrorMessage(error, fallback))
}

function GradeRevisionHistory({ grade }: { grade: Grade }) {
  const [open, setOpen] = useState(false)
  const revisionsQuery = useQuery({
    queryKey: ['grade-revisions', grade.id],
    enabled: open,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/grades/{id}/revisions/', {
        params: { path: { id: grade.id } },
      })
      assertApiSuccess(error, 'Unable to load grade history.')
      if (!data) throw new Error('The server returned no grade history.')
      return data.results as GradeRevision[]
    },
  })

  return (
    <div className="space-y-2">
      <Button variant="ghost" size="sm" onClick={() => setOpen((value) => !value)}>
        {open ? t('Hide revision history') : t('View revision history')}
      </Button>
      {open && revisionsQuery.isPending && <p role="status">{t('Loading grade history…')}</p>}
      {open && revisionsQuery.isError && <p role="alert" className="text-danger-fg">{revisionsQuery.error.message}</p>}
      {open && revisionsQuery.data?.map((revision) => (
        <p className="text-sm text-subtle" key={revision.id}>
          {t('Revision')} {revision.revision} · {revision.status} · {revision.score ?? '—'}
          {revision.change_note ? ` · ${revision.change_note}` : ''}
          {revision.is_late ? ` · ${t('Late')}` : ''}
        </p>
      ))}
    </div>
  )
}

function AttemptGrantForm({
  assessmentId,
  enrollmentId,
  onCreated,
}: {
  assessmentId: string
  enrollmentId: string
  onCreated: () => void
}) {
  const [open, setOpen] = useState(false)
  const [message, setMessage] = useState('')
  const grant = useMutation({
    mutationFn: async (reason: string) => {
      const { data, error } = await api.POST('/api/v1/assessments/{id}/re-open/', {
        params: { path: { id: assessmentId } },
        body: { enrollment: enrollmentId, reason },
      })
      assertApiSuccess(error, 'The attempt grant could not be created.')
      if (!data) throw new Error('The server returned no attempt grant.')
      return data
    },
    onSuccess: () => {
      setMessage(t('Attempt granted for seven days.'))
      setOpen(false)
      onCreated()
    },
    onError: (error) => setMessage(error.message),
  })

  return (
    <div className="space-y-2">
      <Button variant="ghost" size="sm" onClick={() => setOpen((value) => !value)}>
        {open ? t('Cancel grant') : t('Grant an attempt')}
      </Button>
      {open && (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            const reason = new FormData(event.currentTarget).get('reason')?.toString().trim() ?? ''
            if (reason) grant.mutate(reason)
          }}
        >
          <label className="min-w-40 flex-1 text-xs">
            {t('Reason')}
            <input className="mt-1 block w-full rounded border p-2" name="reason" maxLength={500} required />
          </label>
          <Button size="sm" loading={grant.isPending}>{t('Grant')}</Button>
        </form>
      )}
      {message && <p className="text-xs" role="status">{message}</p>}
    </div>
  )
}

function SubmissionDownload({ submission }: { submission: Submission }) {
  const [message, setMessage] = useState('')
  const download = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.GET('/api/v1/files/{id}/download-url/', {
        params: { path: { id: submission.file } },
      })
      assertApiSuccess(error, 'The submission download could not be prepared.')
      if (!data) throw new Error('The server returned no download link.')
      const link = document.createElement('a')
      link.href = data.download_url
      link.target = '_blank'
      link.rel = 'noopener noreferrer'
      link.click()
    },
    onError: (error) => setMessage(error.message),
  })
  return (
    <span className="inline-flex items-center gap-2">
      <button className="underline" onClick={() => download.mutate()} disabled={download.isPending}>
        {download.isPending ? 'Preparing…' : 'Download submission'}
      </button>
      {message && <span role="alert" className="text-danger-fg">{message}</span>}
    </span>
  )
}

function AssessmentUpload({
  assessment,
  attemptsUsed,
  submissionGrantsUsed,
  activeGrantUntil,
  canSubmit,
}: {
  assessment: Assessment
  attemptsUsed: number
  submissionGrantsUsed: number
  activeGrantUntil: string | null
  canSubmit: boolean
}) {
  const queryClient = useQueryClient()
  const [message, setMessage] = useState('')
  const submission = useMutation({
    mutationFn: async (file: File) => {
      const { data: started, error: startError } = await api.POST('/api/v1/files/uploads/', {
        body: {
          purpose: 'submission',
          filename: file.name,
          content_type: file.type || 'application/octet-stream',
          size: file.size,
        },
      })
      assertApiSuccess(startError, 'The upload could not be prepared.')
      if (!started) throw new Error('The server returned no upload details.')

      const uploadResponse = await fetch(started.upload_url, {
        method: 'PUT',
        headers: started.headers,
        body: file,
      })
      if (!uploadResponse.ok) {
        throw new Error(`The file upload failed (${uploadResponse.status}).`)
      }

      const { data: completed, error: completeError } = await api.POST('/api/v1/files/{id}/complete/', {
        params: { path: { id: started.file.id } },
      })
      assertApiSuccess(completeError, 'The uploaded file could not be verified.')
      if (!completed) throw new Error('The server returned no verified file.')

      const { error: submissionError } = await api.POST('/api/v1/submissions/', {
        body: { assessment: assessment.id, file: completed.id },
      })
      assertApiSuccess(submissionError, 'The submission could not be recorded.')
    },
    onSuccess: async () => {
      setMessage('Submission received.')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['submissions'] }),
        queryClient.invalidateQueries({ queryKey: ['assessments'] }),
      ])
    },
    onError: (error) => setMessage(error.message),
  })

  return (
    <div className="space-y-2">
      <p className="text-sm text-subtle">
        {t('Attempts used')}: {attemptsUsed} / {(assessment.max_attempts ?? 1) + submissionGrantsUsed}
        {assessment.late_until && ` · ${t('Late submissions accepted until')} ${new Date(assessment.late_until).toLocaleString()}`}
        {activeGrantUntil && ` · ${t('Extra attempt until')} ${new Date(activeGrantUntil).toLocaleString()}`}
      </p>
      <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(event) => {
        event.preventDefault()
        const form = event.currentTarget
        const file = (new FormData(form).get('file')) as File | null
        if (file && file.size > 20 * 1024 * 1024) {
          setMessage('The file exceeds the 20 MB limit.')
          return
        }
        if (file && file.size > 0) submission.mutate(file)
      }}
    >
      <label className="min-w-52 flex-1 text-sm">
        Submission file (PDF, Word, text or image; max 20 MB)
        <input className="mt-1 block w-full rounded border p-2" name="file" type="file" accept=".pdf,.doc,.docx,.txt,.jpg,.jpeg,.png" required />
      </label>
      <button className="rounded bg-primary px-4 py-2 text-sm text-primary-fg disabled:opacity-50" disabled={submission.isPending || !canSubmit}>
        {submission.isPending ? 'Uploading…' : 'Submit'}
      </button>
      {!canSubmit && <p className="w-full text-sm text-subtle">{t('The submission window or attempt limit has been reached. Request an attempt grant from staff.')}</p>}
      {message && <p className="w-full text-sm" role="status">{message}</p>}
      </form>
    </div>
  )
}

export function AssessmentWorkspace() {
  const { data: profile } = useMe()
  const queryClient = useQueryClient()
  const [formError, setFormError] = useState('')
  const [selectedCourse, setSelectedCourse] = useState('')
  const [assessmentCourse, setAssessmentCourse] = useState('')
  const [selectedTemplate, setSelectedTemplate] = useState('')
  const [rejectNotes, setRejectNotes] = useState<Record<string, string>>({})
  const [editingGradeCell, setEditingGradeCell] = useState('')
  const [currentTime, setCurrentTime] = useState(() => Date.now())
  const canManage = hasRole(profile, 'SUPER_ADMIN', 'ADMIN', 'HOD', 'UNIT_MANAGER', 'TEACHER')
  const canGrade = hasRole(profile, 'SUPER_ADMIN', 'ADMIN', 'HOD', 'UNIT_MANAGER', 'TEACHER')
  const isStudent = hasRole(profile, 'STUDENT')
  const isTeacher = hasRole(profile, 'TEACHER')
  const canReview = hasRole(profile, 'SUPER_ADMIN', 'ADMIN', 'HOD', 'UNIT_MANAGER')

  useEffect(() => {
    const timer = window.setInterval(() => setCurrentTime(Date.now()), 30_000)
    return () => window.clearInterval(timer)
  }, [])

  const coursesQuery = useQuery({
    queryKey: ['courses', 'assessment-workspace'],
    enabled: canManage,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/courses/')
      assertApiSuccess(error, 'Unable to load courses.')
      if (!data) throw new Error('The server returned no courses.')
      return data.results
    },
  })
  const groupsQuery = useQuery({
    queryKey: ['class-groups', 'assessment-workspace'],
    enabled: canManage,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/class-groups/')
      assertApiSuccess(error, 'Unable to load class groups.')
      if (!data) throw new Error('The server returned no class groups.')
      return data.results
    },
  })
  const templatesQuery = useQuery({
    queryKey: ['assessment-templates'],
    enabled: canManage,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/assessment-templates/')
      assertApiSuccess(error, 'Unable to load assessment templates.')
      if (!data) throw new Error('The server returned no assessment templates.')
      return data.results
    },
  })
  const assessmentsQuery = useQuery({
    queryKey: ['assessments'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/assessments/')
      assertApiSuccess(error, 'Unable to load assessments.')
      if (!data) throw new Error('The server returned no assessments.')
      return data.results
    },
  })
  const submissionsQuery = useQuery({
    queryKey: ['submissions'],
    enabled: canManage || isStudent,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/submissions/', {
        params: { query: { page_size: 100 } },
      })
      assertApiSuccess(error, 'Unable to load submissions.')
      if (!data) throw new Error('The server returned no submissions.')
      return data.results
    },
  })
  const gradesQuery = useQuery({
    queryKey: ['grades'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/grades/')
      assertApiSuccess(error, 'Unable to load grades.')
      if (!data) throw new Error('The server returned no grades.')
      return data.results
    },
  })
  const attemptGrantsQuery = useQuery({
    queryKey: ['assessment-attempt-grants'],
    enabled: canManage || isStudent,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/assessment-attempt-grants/', {
        params: { query: { page_size: 100 } },
      })
      assertApiSuccess(error, 'Unable to load attempt grants.')
      if (!data) throw new Error('The server returned no attempt grants.')
      return data.results
    },
  })
  const transcriptVersionsQuery = useQuery({
    queryKey: ['transcript-versions'],
    enabled: isStudent,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/transcripts/me/versions/')
      assertApiSuccess(error, 'Unable to load transcript versions.')
      if (!data) throw new Error('The server returned no transcript versions.')
      return (data as { versions: TranscriptVersionSummary[] }).versions
    },
  })

  const createAssessment = useMutation({
    mutationFn: async (form: FormData) => {
      let templateId = form.get('template')?.toString() ?? ''
      if (!templateId) {
        const { data: template, error: templateError } = await api.POST('/api/v1/assessment-templates/', {
          body: {
            course: form.get('course')?.toString() ?? '',
            title: form.get('title')?.toString() ?? '',
            instructions: form.get('instructions')?.toString() ?? '',
            kind: (form.get('kind')?.toString() || 'ASSIGNMENT') as AssessmentKind,
            maximum_score: form.get('maximum_score')?.toString() ?? '100',
          },
        })
        assertApiSuccess(templateError, 'The assessment template could not be created.')
        if (!template) throw new Error('The server returned no assessment template.')
        templateId = template.id
      }

      const { data, error } = await api.POST('/api/v1/assessments/', {
        body: {
          template: templateId,
          class_group: form.get('class_group')?.toString() ?? '',
          weight: form.get('weight')?.toString() ?? '1',
          due_at: form.get('due_at')?.toString() || null,
          late_until: form.get('late_until')?.toString() || null,
          max_attempts: Number(form.get('max_attempts')?.toString() || 1),
        },
      })
      assertApiSuccess(error, 'The assessment could not be created.')
      if (!data) throw new Error('The server returned no assessment.')
      return data
    },
    onSuccess: async () => {
      setFormError('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['assessments'] }),
        queryClient.invalidateQueries({ queryKey: ['assessment-templates'] }),
      ])
    },
    onError: (error) => setFormError(error.message),
  })

  const changeAssessment = useMutation({
    mutationFn: async ({ assessment, action }: { assessment: Assessment; action: 'publish' | 'close' }) => {
      const { error } = await api.POST(`/api/v1/assessments/{id}/${action}/` as '/api/v1/assessments/{id}/publish/', {
        params: { path: { id: assessment.id } },
      })
      assertApiSuccess(error, `The assessment could not be ${action === 'publish' ? 'published' : 'closed'}.`)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['assessments'] })
    },
    onError: (error) => setFormError(error.message),
  })

  const createGrade = useMutation({
    mutationFn: async ({ assessmentId, enrollmentId, score, feedback, change_note }: {
      assessmentId: string
      enrollmentId: string
      score: string
      feedback: string
      change_note: string
    }) => {
      const { data, error } = await api.POST('/api/v1/grades/', {
        body: {
          assessment: assessmentId,
          enrollment: enrollmentId,
          score,
          feedback,
          change_note,
        },
      })
      assertApiSuccess(error, 'The grade could not be saved.')
      if (!data) throw new Error('The server returned no grade.')
      return data
    },
    onSuccess: async () => {
      setFormError('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['grades'] }),
        queryClient.invalidateQueries({ queryKey: ['gradebook'] }),
        queryClient.invalidateQueries({ queryKey: ['assessment-attempt-grants'] }),
      ])
    },
    onError: (error) => setFormError(error.message),
  })

  const updateGrade = useMutation({
    mutationFn: async ({ grade, score, feedback, changeNote }: {
      grade: Grade
      score: string
      feedback: string
      changeNote: string
    }) => {
      const { error } = await api.PATCH('/api/v1/grades/{id}/', {
        params: { path: { id: grade.id } },
        body: { score, feedback, change_note: changeNote || undefined },
      })
      assertApiSuccess(error, 'The returned grade could not be updated.')
    },
    onSuccess: async () => {
      setFormError('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['grades'] }),
        queryClient.invalidateQueries({ queryKey: ['gradebook'] }),
      ])
    },
    onError: (error) => setFormError(error.message),
  })

  const gradeAction = useMutation({
    mutationFn: async ({ grade, action, note }: { grade: Grade; action: 'submit-for-approval' | 'approve' | 'publish' | 'approve-and-publish' | 'reject'; note?: string }) => {
      const { error } = action === 'reject'
        ? await api.POST('/api/v1/grades/{id}/reject/', {
            params: { path: { id: grade.id } },
            body: { note: note ?? '' },
          })
        : action === 'approve'
          ? await api.POST('/api/v1/grades/{id}/approve/', {
              params: { path: { id: grade.id } },
            })
          : action === 'publish'
            ? await api.POST('/api/v1/grades/{id}/publish/', {
                params: { path: { id: grade.id } },
              })
            : action === 'approve-and-publish'
              ? await api.POST('/api/v1/grades/{id}/approve-and-publish/', {
                  params: { path: { id: grade.id } },
                })
              : await api.POST('/api/v1/grades/{id}/submit-for-approval/', {
              params: { path: { id: grade.id } },
            })
      assertApiSuccess(error, 'The grade workflow action failed.')
    },
    onSuccess: async () => {
      setFormError('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['grades'] }),
        queryClient.invalidateQueries({ queryKey: ['gradebook'] }),
      ])
    },
    onError: (error) => setFormError(error.message),
  })

  const gradeBySubmission = useMemo(
    () => new Map(
      (gradesQuery.data ?? [])
        .filter((grade): grade is Grade & { submission: string } => Boolean(grade.submission))
        .map((grade) => [grade.submission, grade]),
    ),
    [gradesQuery.data],
  )
  const gradeByEnrollmentAssessment = useMemo(
    () => new Map((gradesQuery.data ?? []).map((grade) => [`${grade.assessment}:${grade.enrollment}`, grade])),
    [gradesQuery.data],
  )
  const assessments = assessmentsQuery.data ?? []
  const courseIds = Array.from(new Set(assessments.map((assessment) => assessment.course)))
  const availableCourses = (coursesQuery.data ?? []).filter((course) =>
    !isTeacher
    || course.created_by === profile?.id
    || (groupsQuery.data ?? []).some(
      (group) => group.course === course.id && group.lead_teacher_id === profile?.id,
    ),
  )
  const gradebookCourses = isTeacher
    ? availableCourses.filter((course) => course.created_by === profile?.id)
    : coursesQuery.data?.filter((course) => courseIds.includes(course.id))
      ?? assessments.map((assessment) => ({
      id: assessment.course,
      title: assessment.course_title,
      code: '',
      })).filter((course, index, list) => list.findIndex((item) => item.id === course.id) === index)
  const activeCourse = selectedCourse || gradebookCourses[0]?.id || ''

  const gradebookQuery = useQuery({
    queryKey: ['gradebook', activeCourse],
    enabled: Boolean(activeCourse),
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/gradebook/', {
        params: { query: { course: activeCourse } },
      })
      assertApiSuccess(error, 'Unable to load the gradebook.')
      if (!data) throw new Error('The server returned no gradebook.')
      return data
    },
  })

  async function downloadTranscript(version?: number) {
    const token = await auth.currentUser?.getIdToken()
    if (!token) throw new Error('Sign in again before downloading the transcript.')
    const versionQuery = version ? `?version=${version}` : ''
    const response = await fetch(`${import.meta.env.VITE_API_URL}/api/v1/transcripts/me/${versionQuery}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!response.ok) throw new Error(apiErrorMessage(await response.json(), 'The transcript could not be downloaded.'))
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = 'my-transcript.pdf'
    link.click()
    URL.revokeObjectURL(url)
  }
  const [transcriptVersion, setTranscriptVersion] = useState('')

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <PageHeader title="Assessments & grades" />
        {isStudent && (
          <div className="flex items-center gap-2">
            <label className="text-sm">
              {t('Transcript version')}
              <select
                className="ml-2 rounded border border-line p-2"
                value={transcriptVersion}
                onChange={(event) => setTranscriptVersion(event.target.value)}
              >
                <option value="">{t('Latest')}</option>
                {(transcriptVersionsQuery.data ?? []).map((version) => (
                  <option key={version.version} value={version.version}>
                    {t('Version')} {version.version}{version.is_revised ? ` · ${t('Revised')}` : ''}
                  </option>
                ))}
              </select>
            </label>
            <Button
              variant="secondary"
              onClick={() => void downloadTranscript(
                transcriptVersion ? Number(transcriptVersion) : undefined,
              ).catch((error: unknown) => setFormError(apiErrorMessage(error, 'The transcript could not be downloaded.')))}
            >
              {t('Download transcript PDF')}
            </Button>
          </div>
        )}
      </div>
      {formError && <p role="alert" className="rounded border border-danger/40 bg-danger/10 p-3 text-danger-fg">{formError}</p>}
      {(assessmentsQuery.isError || gradesQuery.isError || submissionsQuery.isError) && (
        <p role="alert" className="text-danger-fg">
          {assessmentsQuery.error?.message ?? gradesQuery.error?.message ?? submissionsQuery.error?.message}
        </p>
      )}
      {attemptGrantsQuery.isError && <p role="alert" className="text-danger-fg">{attemptGrantsQuery.error.message}</p>}
      {transcriptVersionsQuery.isError && <p role="alert" className="text-danger-fg">{transcriptVersionsQuery.error.message}</p>}
      {templatesQuery.isError && <p role="alert" className="text-danger-fg">{templatesQuery.error.message}</p>}

      {canManage && (
        <form
          className="grid gap-3 rounded-xl border border-line bg-white p-4 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault()
            createAssessment.mutate(new FormData(event.currentTarget))
          }}
        >
          <h2 className="text-xl font-semibold sm:col-span-2">Create assessment</h2>
          <label className="text-sm">Course
            <select className="mt-1 w-full rounded border p-2" name="course" required value={assessmentCourse} onChange={(event) => {
              setAssessmentCourse(event.target.value)
              setSelectedTemplate('')
            }}>
              <option value="">Select a course</option>
              {availableCourses.map((course) => <option key={course.id} value={course.id}>{course.title} ({course.code})</option>)}
            </select>
          </label>
          <label className="text-sm">Template
            <select className="mt-1 w-full rounded border p-2" name="template" value={selectedTemplate} onChange={(event) => setSelectedTemplate(event.target.value)}>
              <option value="">Create a new template</option>
              {(templatesQuery.data ?? []).filter((template: AssessmentTemplate) => template.course === assessmentCourse).map((template) => <option key={template.id} value={template.id}>{template.title}</option>)}
            </select>
          </label>
          <label className="text-sm">Class group
            <select className="mt-1 w-full rounded border p-2" name="class_group" required defaultValue="">
              <option value="">Select a class group</option>
              {(groupsQuery.data ?? []).filter((group) => group.course === assessmentCourse).map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
            </select>
          </label>
          {!selectedTemplate && <label className="text-sm">Title
            <input className="mt-1 w-full rounded border p-2" name="title" required maxLength={200} />
          </label>}
          {!selectedTemplate && <label className="text-sm">Type
            <select className="mt-1 w-full rounded border p-2" name="kind">
              <option value="ASSIGNMENT">Assignment</option><option value="QUIZ">Quiz</option><option value="EXAM">Exam</option><option value="PROJECT">Project</option>
            </select>
          </label>}
          {!selectedTemplate && <label className="text-sm">Maximum score
            <input className="mt-1 w-full rounded border p-2" name="maximum_score" type="number" min="0.01" step="0.01" defaultValue="100" required />
          </label>}
          <label className="text-sm">Weight
            <input className="mt-1 w-full rounded border p-2" name="weight" type="number" min="0.01" step="0.01" defaultValue="1" required />
          </label>
          <label className="text-sm">Due date
            <input className="mt-1 w-full rounded border p-2" name="due_at" type="datetime-local" />
          </label>
          <label className="text-sm">{t('Late submission cutoff')}
            <input className="mt-1 w-full rounded border p-2" name="late_until" type="datetime-local" />
          </label>
          <label className="text-sm">{t('Maximum attempts')}
            <input className="mt-1 w-full rounded border p-2" name="max_attempts" type="number" min="1" step="1" defaultValue="1" required />
          </label>
          {!selectedTemplate && <label className="text-sm sm:col-span-2">Instructions
            <textarea className="mt-1 w-full rounded border p-2" name="instructions" rows={3} />
          </label>}
          <button className="rounded bg-primary px-4 py-2 text-primary-fg disabled:opacity-50 sm:col-span-2" disabled={createAssessment.isPending || !assessmentCourse}>
            {createAssessment.isPending ? 'Saving…' : 'Save draft'}
          </button>
        </form>
      )}

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Assessments</h2>
        {assessmentsQuery.isPending && <p role="status">Loading assessments…</p>}
        {assessments.map((assessment) => {
          const attempts = (submissionsQuery.data ?? []).filter((item) => item.assessment === assessment.id)
          const grants = (attemptGrantsQuery.data ?? []).filter((grant) => grant.assessment === assessment.id)
          const submissionGrantsUsed = grants.filter((grant) => grant.used_for === 'SUBMISSION').length
          const activeGrantUntil = grants.find(
            (grant) => !grant.used_at && new Date(grant.valid_until).getTime() > currentTime,
          )?.valid_until ?? null
          const activeGrant = Boolean(activeGrantUntil)
          const maxAttempts = assessment.max_attempts ?? 1
          const lateWindowOpen = !assessment.due_at
            || currentTime <= new Date(assessment.late_until ?? assessment.due_at).getTime()
          const attemptsAvailable = attempts.length < maxAttempts + submissionGrantsUsed
          const canSubmit = (assessment.status === 'PUBLISHED' && (activeGrant || (lateWindowOpen && attemptsAvailable)))
            || (assessment.status === 'CLOSED' && activeGrant)
          return (
            <article className="space-y-3 rounded-xl border border-line bg-white p-4" key={assessment.id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="font-semibold">{assessment.title}</h3>
                  <p className="text-sm text-subtle">{assessment.course_title} · {assessment.kind} · {assessment.maximum_score} points</p>
                  <p className="text-sm text-subtle">
                    {assessment.class_group_name ? `Group: ${assessment.class_group_name} · ` : ''}
                    {assessment.due_at ? `Due ${new Date(assessment.due_at).toLocaleString()}` : 'No due date'}
                    {assessment.late_until && ` · ${t('Late cutoff')} ${new Date(assessment.late_until).toLocaleString()}`}
                    {' · '}{assessment.status}
                    {` · ${t('Maximum attempts')}: ${maxAttempts}`}
                  </p>
                </div>
                {canManage && (
                  <div className="flex gap-3 text-sm">
                    {assessment.status === 'DRAFT' && <button className="underline" onClick={() => changeAssessment.mutate({ assessment, action: 'publish' })}>Publish</button>}
                    {assessment.status === 'PUBLISHED' && <button className="underline" onClick={() => changeAssessment.mutate({ assessment, action: 'close' })}>Close submissions</button>}
                  </div>
                )}
              </div>
              {assessment.instructions && <p className="whitespace-pre-wrap text-sm">{assessment.instructions}</p>}
              {isStudent && ['PUBLISHED', 'CLOSED'].includes(assessment.status) && (
                <AssessmentUpload
                  assessment={assessment}
                  attemptsUsed={attempts.length}
                  submissionGrantsUsed={submissionGrantsUsed}
                  activeGrantUntil={activeGrantUntil}
                  canSubmit={canSubmit}
                />
              )}
            </article>
          )
        })}
        {assessments.length === 0 && !assessmentsQuery.isPending && <p className="text-subtle">No assessments are available yet.</p>}
      </section>

      {isStudent && (
        <section className="space-y-3">
          <h2 className="text-xl font-semibold">{t('My submissions')}</h2>
          {(submissionsQuery.data ?? []).map((submission) => (
            <article className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-white p-4" key={submission.id}>
              <div>
                <h3 className="font-semibold">{submission.assessment_title} · {t('Attempt')} {submission.attempt_number}</h3>
                <p className="text-sm text-subtle">
                  {submission.file_name} · {t('Submitted')} {new Date(submission.submitted_at).toLocaleString()}
                  {submission.is_late && ` · ${t('Late')}`}
                </p>
              </div>
            </article>
          ))}
          {submissionsQuery.data?.length === 0 && <p className="text-subtle">{t('You have not submitted any work yet.')}</p>}
        </section>
      )}

      {canManage && (
        <section className="space-y-3">
          <h2 className="text-xl font-semibold">Submission queue</h2>
          {(submissionsQuery.data ?? []).map((submission) => {
            const grade = gradeBySubmission.get(submission.id)
            return (
              <article className="space-y-3 rounded-xl border border-line bg-white p-4" key={submission.id}>
                <div>
                  <h3 className="font-semibold">{submission.student_name} · {submission.registration_number}</h3>
                  <p className="text-sm text-subtle">
                    {submission.assessment_title} · {t('Attempt')} {submission.attempt_number} · {t('Submitted')} {new Date(submission.submitted_at).toLocaleString()}
                    {submission.is_late && ` · ${t('Late')}`}
                  </p>
                  <p className="text-sm">{submission.file_name} · <SubmissionDownload submission={submission} /></p>
                </div>
                {grade ? (
                  <div className="space-y-2 border-t pt-3">
                    <p className="text-sm">
                      {grade.score ?? '—'}/{grade.maximum_score} · {grade.status} · {t('revision')} {grade.revision}
                      {grade.official_score !== null && ` · ${t('Official')}: ${grade.official_score}`}
                      {grade.regrade_pending && ` · ${t('New grade pending publication')}`}
                    </p>
                    {grade.feedback && <p className="text-sm">{grade.feedback}</p>}
                    {grade.review_note && <p className="text-sm text-danger-fg">Returned: {grade.review_note}</p>}
                    {canGrade && ['DRAFT', 'REJECTED', 'PUBLISHED'].includes(grade.status) && (
                      <form
                        className="flex flex-wrap items-end gap-3"
                        onSubmit={(event) => {
                          event.preventDefault()
                          const values = new FormData(event.currentTarget)
                          updateGrade.mutate({
                            grade,
                            score: values.get('score')?.toString() ?? '',
                            feedback: values.get('feedback')?.toString() ?? '',
                            changeNote: values.get('change_note')?.toString() ?? '',
                          })
                        }}
                      >
                        <label className="text-sm">Score
                          <input className="mt-1 block w-28 rounded border p-2" name="score" type="number" min="0" max={grade.maximum_score} step="0.01" defaultValue={grade.score} required />
                        </label>
                        <label className="min-w-48 flex-1 text-sm">Feedback
                          <input className="mt-1 block w-full rounded border p-2" name="feedback" defaultValue={grade.feedback} />
                        </label>
                        <label className="min-w-48 flex-1 text-sm">{t('Change note')}
                          <input className="mt-1 block w-full rounded border p-2" name="change_note" required />
                        </label>
                        <Button variant="secondary" loading={updateGrade.isPending}>{t('Save new revision')}</Button>
                      </form>
                    )}
                    <div className="flex flex-wrap gap-3 text-sm">
                      {(grade.status === 'DRAFT' || grade.status === 'REJECTED') && (
                        <button className="underline" onClick={() => gradeAction.mutate({ grade, action: 'submit-for-approval' })}>Submit for approval</button>
                      )}
                      {canReview && grade.status === 'PENDING_APPROVAL' && (
                        <>
                          <button className="underline" onClick={() => gradeAction.mutate({ grade, action: 'approve' })}>{t('Approve only')}</button>
                          <button className="underline" onClick={() => gradeAction.mutate({ grade, action: 'approve-and-publish' })}>{t('Approve & publish')}</button>
                          <label className="flex gap-2">
                            <input className="rounded border px-2" placeholder="Reason to return" value={rejectNotes[grade.id] ?? ''} onChange={(event) => setRejectNotes((current) => ({ ...current, [grade.id]: event.target.value }))} />
                            <button className="underline" onClick={() => gradeAction.mutate({ grade, action: 'reject', note: rejectNotes[grade.id] ?? '' })}>Return</button>
                          </label>
                        </>
                      )}
                      {canReview && grade.status === 'APPROVED' && (
                        <button className="underline" onClick={() => gradeAction.mutate({ grade, action: 'publish' })}>{t('Publish approved grade')}</button>
                      )}
                    </div>
                    <GradeRevisionHistory grade={grade} />
                  </div>
                ) : <p className="text-sm text-subtle">{t('No grade record is available for this submission.')}</p>}
              </article>
            )
          })}
          {submissionsQuery.data?.length === 0 && <p className="text-subtle">No submissions have been received.</p>}
        </section>
      )}

      <section className="space-y-3">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-xl font-semibold">{isStudent ? 'My grades' : 'Gradebook'}</h2>
          {gradebookCourses.length > 0 && (
            <label className="text-sm">Course
              <select className="ml-2 rounded border p-2" value={activeCourse} onChange={(event) => setSelectedCourse(event.target.value)}>
                {gradebookCourses.map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}
              </select>
            </label>
          )}
        </header>
        {gradebookQuery.isPending && activeCourse && <p role="status">Loading gradebook…</p>}
        {gradebookQuery.isError && <p role="alert" className="text-danger-fg">{gradebookQuery.error.message}</p>}
        {gradebookQuery.data && (
          <div className="scrollbar-thin overflow-x-auto rounded-xl border border-line bg-white">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-2">
                <tr>
                  <th className="p-3">{isStudent ? 'Course' : 'Student'}</th>
                  {gradebookQuery.data.assessments.map((assessment) => (
                    <th className="min-w-36 p-3" key={assessment.id}>{assessment.title}<span className="block font-normal text-subtle">/{assessment.maximum_score}</span></th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {gradebookQuery.data.students.map((student) => (
                  <tr className="border-t border-line" key={student.id}>
                    <td className="p-3 font-medium">{isStudent ? gradebookQuery.data.course.title : `${student.name} (${student.registration_number})`}</td>
                    {gradebookQuery.data.assessments.map((assessment) => {
                      const cellKey = `${assessment.id}:${student.enrollment_id}`
                      const grade = gradeByEnrollmentAssessment.get(cellKey)
                      const entry = student.grades[assessment.id]
                      const canEditStaffMark = Boolean(
                        canGrade
                        && grade?.source === 'STAFF_RECORDED'
                        && ['DRAFT', 'REJECTED', 'PUBLISHED'].includes(grade.status),
                      )
                      const showMarkForm = canGrade
                        && editingGradeCell === cellKey
                        && (!grade || canEditStaffMark)
                      return (
                        <td className="min-w-52 space-y-2 p-3 align-top" key={assessment.id}>
                          {entry ? (
                            <p>
                              {entry.official_score ?? entry.score ?? '—'} · {entry.status}
                              {entry.regrade_pending && <span className="block text-xs text-subtle">{t('New grade pending publication')}</span>}
                            </p>
                          ) : <p className="text-subtle">—</p>}
                          {grade && <GradeRevisionHistory grade={grade} />}
                          {grade && (
                            <div className="flex flex-wrap gap-2 text-xs">
                              {canGrade && ['DRAFT', 'REJECTED'].includes(grade.status) && (
                                <button className="underline" onClick={() => gradeAction.mutate({ grade, action: 'submit-for-approval' })}>
                                  {t('Submit for approval')}
                                </button>
                              )}
                              {canReview && grade.status === 'PENDING_APPROVAL' && (
                                <>
                                  <button className="underline" onClick={() => gradeAction.mutate({ grade, action: 'approve' })}>
                                    {t('Approve only')}
                                  </button>
                                  <button className="underline" onClick={() => gradeAction.mutate({ grade, action: 'approve-and-publish' })}>
                                    {t('Approve & publish')}
                                  </button>
                                  <button className="underline" onClick={() => gradeAction.mutate({ grade, action: 'reject', note: rejectNotes[grade.id] ?? '' })}>
                                    {t('Return')}
                                  </button>
                                </>
                              )}
                              {canReview && grade.status === 'APPROVED' && (
                                <button className="underline" onClick={() => gradeAction.mutate({ grade, action: 'publish' })}>
                                  {t('Publish')}
                                </button>
                              )}
                            </div>
                          )}
                          {canGrade && !isStudent && !grade && (
                            <Button variant="ghost" size="sm" onClick={() => setEditingGradeCell(cellKey)}>
                              {t('Record offline mark')}
                            </Button>
                          )}
                          {canEditStaffMark && (
                            <Button variant="ghost" size="sm" onClick={() => setEditingGradeCell(cellKey)}>
                              {t('Edit staff mark')}
                            </Button>
                          )}
                          {showMarkForm && (
                            <form
                              className="space-y-2"
                              onSubmit={(event) => {
                                event.preventDefault()
                                const values = new FormData(event.currentTarget)
                                const score = values.get('score')?.toString() ?? ''
                                const feedback = values.get('feedback')?.toString() ?? ''
                                const changeNote = values.get('change_note')?.toString() ?? ''
                                if (grade) {
                                  updateGrade.mutate({
                                    grade,
                                    score,
                                    feedback,
                                    changeNote,
                                  })
                                } else {
                                  createGrade.mutate({
                                    assessmentId: assessment.id,
                                    enrollmentId: student.enrollment_id,
                                    score,
                                    feedback,
                                    change_note: changeNote,
                                  })
                                }
                                setEditingGradeCell('')
                              }}
                            >
                              <label className="block text-xs">{t('Score')}
                                <input className="mt-1 block w-full rounded border p-2" name="score" type="number" min="0" max={assessment.maximum_score} step="0.01" defaultValue={grade?.score ?? ''} required />
                              </label>
                              <label className="block text-xs">{t('Feedback')}
                                <input className="mt-1 block w-full rounded border p-2" name="feedback" defaultValue={grade?.feedback ?? ''} />
                              </label>
                              <label className="block text-xs">{t('Change note')}
                                <input className="mt-1 block w-full rounded border p-2" name="change_note" required />
                              </label>
                              <div className="flex gap-2">
                                <Button size="sm" loading={createGrade.isPending || updateGrade.isPending}>{t('Save draft')}</Button>
                                <Button type="button" variant="ghost" size="sm" onClick={() => setEditingGradeCell('')}>{t('Cancel')}</Button>
                              </div>
                            </form>
                          )}
                          {canManage && !isStudent && (
                            <AttemptGrantForm
                              assessmentId={assessment.id}
                              enrollmentId={student.enrollment_id}
                              onCreated={() => {
                                void queryClient.invalidateQueries({ queryKey: ['assessment-attempt-grants'] })
                              }}
                            />
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
                {gradebookQuery.data.students.length === 0 && <tr><td className="p-3 text-subtle" colSpan={Math.max(1, gradebookQuery.data.assessments.length + 1)}>No students or published grades.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  )
}
