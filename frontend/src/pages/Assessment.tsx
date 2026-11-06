import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api } from '../api/client'
import type { components } from '../api/schema'
import { apiErrorMessage } from '../lib/apiError'
import { PageHeader } from '../app/PageHeader'
import { auth } from '../lib/firebase'
import { useMe } from '../features/me/useMe'
import { hasRole } from '../features/me/roles'

type Assessment = components['schemas']['Assessment']
type Submission = components['schemas']['Submission']
type Grade = components['schemas']['Grade']
type AssessmentKind = 'ASSIGNMENT' | 'QUIZ' | 'EXAM' | 'PROJECT'


function assertApiSuccess(error: unknown, fallback: string) {
  if (error) throw new Error(apiErrorMessage(error, fallback))
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

function AssessmentUpload({ assessment }: { assessment: Assessment }) {
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
      <button className="rounded bg-primary px-4 py-2 text-sm text-primary-fg disabled:opacity-50" disabled={submission.isPending}>
        {submission.isPending ? 'Uploading…' : 'Submit'}
      </button>
      {message && <p className="w-full text-sm" role="status">{message}</p>}
    </form>
  )
}

export function AssessmentWorkspace() {
  const { data: profile } = useMe()
  const queryClient = useQueryClient()
  const [formError, setFormError] = useState('')
  const [selectedCourse, setSelectedCourse] = useState('')
  const [rejectNotes, setRejectNotes] = useState<Record<string, string>>({})
  const canManage = hasRole(profile, 'SUPER_ADMIN', 'ADMIN', 'HOD', 'TEACHER')
  const canGrade = hasRole(profile, 'SUPER_ADMIN', 'ADMIN', 'TEACHER')
  const isStudent = hasRole(profile, 'STUDENT')
  const isTeacher = hasRole(profile, 'TEACHER')
  const canReview = hasRole(profile, 'SUPER_ADMIN', 'ADMIN', 'HOD')

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
      const { data, error } = await api.GET('/api/v1/submissions/')
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

  const createAssessment = useMutation({
    mutationFn: async (form: FormData) => {
      const { data, error } = await api.POST('/api/v1/assessments/', {
        body: {
          course: form.get('course')?.toString() ?? '',
          class_group: form.get('class_group')?.toString() || null,
          title: form.get('title')?.toString() ?? '',
          instructions: form.get('instructions')?.toString() ?? '',
          kind: (form.get('kind')?.toString() || 'ASSIGNMENT') as AssessmentKind,
          maximum_score: form.get('maximum_score')?.toString() ?? '100',
          due_at: form.get('due_at')?.toString() || null,
        },
      })
      assertApiSuccess(error, 'The assessment could not be created.')
      if (!data) throw new Error('The server returned no assessment.')
      return data
    },
    onSuccess: async () => {
      setFormError('')
      await queryClient.invalidateQueries({ queryKey: ['assessments'] })
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
    mutationFn: async ({ submission, score, feedback }: { submission: Submission; score: string; feedback: string }) => {
      const { data, error } = await api.POST('/api/v1/grades/', {
        body: { submission: submission.id, score, feedback },
      })
      assertApiSuccess(error, 'The grade could not be saved.')
      if (!data) throw new Error('The server returned no grade.')
      return data
    },
    onSuccess: async () => {
      setFormError('')
      await queryClient.invalidateQueries({ queryKey: ['grades'] })
    },
    onError: (error) => setFormError(error.message),
  })

  const updateGrade = useMutation({
    mutationFn: async ({ grade, score, feedback }: { grade: Grade; score: string; feedback: string }) => {
      const { error } = await api.PATCH('/api/v1/grades/{id}/', {
        params: { path: { id: grade.id } },
        body: { score, feedback },
      })
      assertApiSuccess(error, 'The returned grade could not be updated.')
    },
    onSuccess: async () => {
      setFormError('')
      await queryClient.invalidateQueries({ queryKey: ['grades'] })
    },
    onError: (error) => setFormError(error.message),
  })

  const gradeAction = useMutation({
    mutationFn: async ({ grade, action, note }: { grade: Grade; action: 'submit-for-approval' | 'approve' | 'reject'; note?: string }) => {
      const { error } = action === 'reject'
        ? await api.POST('/api/v1/grades/{id}/reject/', {
            params: { path: { id: grade.id } },
            body: { note: note ?? '' },
          })
        : action === 'approve'
          ? await api.POST('/api/v1/grades/{id}/approve/', {
              params: { path: { id: grade.id } },
            })
          : await api.POST('/api/v1/grades/{id}/submit-for-approval/', {
              params: { path: { id: grade.id } },
            })
      assertApiSuccess(error, 'The grade workflow action failed.')
    },
    onSuccess: async () => {
      setFormError('')
      await queryClient.invalidateQueries({ queryKey: ['grades'] })
    },
    onError: (error) => setFormError(error.message),
  })

  const gradeBySubmission = useMemo(
    () => new Map((gradesQuery.data ?? []).map((grade) => [grade.submission, grade])),
    [gradesQuery.data],
  )
  const assessments = assessmentsQuery.data ?? []
  const courseIds = Array.from(new Set(assessments.map((assessment) => assessment.course)))
  const availableCourses = (coursesQuery.data ?? []).filter((course) =>
    !isTeacher
    || course.created_by === profile?.id
    || (groupsQuery.data ?? []).some(
      (group) => group.course === course.id && group.teacher === profile?.id,
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

  async function downloadTranscript() {
    const token = await auth.currentUser?.getIdToken()
    if (!token) throw new Error('Sign in again before downloading the transcript.')
    const response = await fetch(`${import.meta.env.VITE_API_URL}/api/v1/transcripts/me/`, {
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

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <PageHeader title="Assessments & grades" />
        {isStudent && (
          <button className="rounded border border-line px-3 py-2 text-sm underline" onClick={() => void downloadTranscript().catch((error: unknown) => setFormError(apiErrorMessage(error, 'The transcript could not be downloaded.')))}>
            Download transcript PDF
          </button>
        )}
      </div>
      {formError && <p role="alert" className="rounded border border-danger/40 bg-danger/10 p-3 text-danger-fg">{formError}</p>}
      {(assessmentsQuery.isError || gradesQuery.isError || submissionsQuery.isError) && (
        <p role="alert" className="text-danger-fg">
          {assessmentsQuery.error?.message ?? gradesQuery.error?.message ?? submissionsQuery.error?.message}
        </p>
      )}

      {canManage && (
        <form
          className="grid gap-3 rounded-xl border border-line bg-white p-4 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault()
            createAssessment.mutate(new FormData(event.currentTarget))
            event.currentTarget.reset()
          }}
        >
          <h2 className="text-xl font-semibold sm:col-span-2">Create assessment</h2>
          <label className="text-sm">Course
            <select className="mt-1 w-full rounded border p-2" name="course" required>
              <option value="">Select a course</option>
              {availableCourses.map((course) => <option key={course.id} value={course.id}>{course.title} ({course.code})</option>)}
            </select>
          </label>
          <label className="text-sm">Class group (optional)
            <select className="mt-1 w-full rounded border p-2" name="class_group" defaultValue="">
              <option value="">All course students</option>
              {(groupsQuery.data ?? []).map((group) => <option key={group.id} value={group.id}>{group.course_title} — {group.name}</option>)}
            </select>
          </label>
          <label className="text-sm">Title
            <input className="mt-1 w-full rounded border p-2" name="title" required maxLength={200} />
          </label>
          <label className="text-sm">Type
            <select className="mt-1 w-full rounded border p-2" name="kind">
              <option value="ASSIGNMENT">Assignment</option><option value="QUIZ">Quiz</option><option value="EXAM">Exam</option><option value="PROJECT">Project</option>
            </select>
          </label>
          <label className="text-sm">Maximum score
            <input className="mt-1 w-full rounded border p-2" name="maximum_score" type="number" min="0.01" step="0.01" defaultValue="100" required />
          </label>
          <label className="text-sm">Due date
            <input className="mt-1 w-full rounded border p-2" name="due_at" type="datetime-local" />
          </label>
          <label className="text-sm sm:col-span-2">Instructions
            <textarea className="mt-1 w-full rounded border p-2" name="instructions" rows={3} />
          </label>
          <button className="rounded bg-primary px-4 py-2 text-primary-fg disabled:opacity-50 sm:col-span-2" disabled={createAssessment.isPending}>
            {createAssessment.isPending ? 'Saving…' : 'Save draft'}
          </button>
        </form>
      )}

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Assessments</h2>
        {assessmentsQuery.isPending && <p role="status">Loading assessments…</p>}
        {assessments.map((assessment) => (
          <article className="space-y-3 rounded-xl border border-line bg-white p-4" key={assessment.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="font-semibold">{assessment.title}</h3>
                <p className="text-sm text-subtle">{assessment.course_title} · {assessment.kind} · {assessment.maximum_score} points</p>
                <p className="text-sm text-subtle">
                  {assessment.class_group_name ? `Group: ${assessment.class_group_name} · ` : ''}
                  {assessment.due_at ? `Due ${new Date(assessment.due_at).toLocaleString()}` : 'No due date'}
                  {' · '}{assessment.status}
                </p>
              </div>
              {isStudent && (
                <section className="space-y-3">
                  <h2 className="text-xl font-semibold">My submissions</h2>
                  {(submissionsQuery.data ?? []).map((submission) => {
                    const grade = gradeBySubmission.get(submission.id)
                    return (
                      <article className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-white p-4" key={submission.id}>
                        <div>
                          <h3 className="font-semibold">{submission.assessment_title} · attempt {submission.attempt_number}</h3>
                          <p className="text-sm text-subtle">{submission.file_name} · submitted {new Date(submission.submitted_at).toLocaleString()}</p>
                          {grade && <p className="text-sm">{grade.status === 'PUBLISHED' ? `${grade.score}/${grade.maximum_score} · ${grade.feedback || 'No feedback'}` : 'Grade pending publication'}</p>}
                        </div>
                      </article>
                    )
                  })}
                  {submissionsQuery.data?.length === 0 && <p className="text-subtle">You have not submitted any work yet.</p>}
                </section>
              )}

              {canManage && (
                <div className="flex gap-3 text-sm">
                  {assessment.status === 'DRAFT' && <button className="underline" onClick={() => changeAssessment.mutate({ assessment, action: 'publish' })}>Publish</button>}
                  {assessment.status === 'PUBLISHED' && <button className="underline" onClick={() => changeAssessment.mutate({ assessment, action: 'close' })}>Close submissions</button>}
                </div>
              )}
            </div>
            {assessment.instructions && <p className="whitespace-pre-wrap text-sm">{assessment.instructions}</p>}
            {isStudent && assessment.status === 'PUBLISHED' && <AssessmentUpload assessment={assessment} />}
          </article>
        ))}
        {assessments.length === 0 && !assessmentsQuery.isPending && <p className="text-subtle">No assessments are available yet.</p>}
      </section>

      {canManage && (
        <section className="space-y-3">
          <h2 className="text-xl font-semibold">Submission queue</h2>
          {(submissionsQuery.data ?? []).map((submission) => {
            const grade = gradeBySubmission.get(submission.id)
            const assessment = assessments.find((item) => item.id === submission.assessment)
            return (
              <article className="space-y-3 rounded-xl border border-line bg-white p-4" key={submission.id}>
                <div>
                  <h3 className="font-semibold">{submission.student_name} · {submission.registration_number}</h3>
                  <p className="text-sm text-subtle">{submission.assessment_title} · attempt {submission.attempt_number} · submitted {new Date(submission.submitted_at).toLocaleString()}</p>
                  <p className="text-sm">{submission.file_name} · <SubmissionDownload submission={submission} /></p>
                </div>
                {grade ? (
                  <div className="space-y-2 border-t pt-3">
                    <p className="text-sm">{grade.score}/{grade.maximum_score} · {grade.status} · revision {grade.revision}</p>
                    {grade.feedback && <p className="text-sm">{grade.feedback}</p>}
                    {grade.review_note && <p className="text-sm text-danger-fg">Returned: {grade.review_note}</p>}
                    {canGrade && (grade.status === 'DRAFT' || grade.status === 'REJECTED') && (
                      <form
                        className="flex flex-wrap items-end gap-3"
                        onSubmit={(event) => {
                          event.preventDefault()
                          const values = new FormData(event.currentTarget)
                          updateGrade.mutate({
                            grade,
                            score: values.get('score')?.toString() ?? '',
                            feedback: values.get('feedback')?.toString() ?? '',
                          })
                        }}
                      >
                        <label className="text-sm">Score
                          <input className="mt-1 block w-28 rounded border p-2" name="score" type="number" min="0" max={grade.maximum_score} step="0.01" defaultValue={grade.score} required />
                        </label>
                        <label className="min-w-48 flex-1 text-sm">Feedback
                          <input className="mt-1 block w-full rounded border p-2" name="feedback" defaultValue={grade.feedback} />
                        </label>
                        <button className="rounded border px-3 py-2 text-sm disabled:opacity-50" disabled={updateGrade.isPending}>Save correction</button>
                      </form>
                    )}
                    <div className="flex flex-wrap gap-3 text-sm">
                      {(grade.status === 'DRAFT' || grade.status === 'REJECTED') && (
                        <button className="underline" onClick={() => gradeAction.mutate({ grade, action: 'submit-for-approval' })}>Submit for approval</button>
                      )}
                      {canReview && grade.status === 'PENDING_APPROVAL' && (
                        <>
                          <button className="underline" onClick={() => gradeAction.mutate({ grade, action: 'approve' })}>Approve & publish</button>
                          <label className="flex gap-2">
                            <input className="rounded border px-2" placeholder="Reason to return" value={rejectNotes[grade.id] ?? ''} onChange={(event) => setRejectNotes((current) => ({ ...current, [grade.id]: event.target.value }))} />
                            <button className="underline" onClick={() => gradeAction.mutate({ grade, action: 'reject', note: rejectNotes[grade.id] ?? '' })}>Return</button>
                          </label>
                        </>
                      )}
                    </div>
                  </div>
                ) : canGrade ? (
                  <form
                    className="flex flex-wrap items-end gap-3 border-t pt-3"
                    onSubmit={(event) => {
                      event.preventDefault()
                      const values = new FormData(event.currentTarget)
                      createGrade.mutate({
                        submission,
                        score: values.get('score')?.toString() ?? '',
                        feedback: values.get('feedback')?.toString() ?? '',
                      })
                    }}
                  >
                    <label className="text-sm">Score
                      <input className="mt-1 block w-28 rounded border p-2" name="score" type="number" min="0" max={assessment?.maximum_score ?? undefined} step="0.01" required />
                    </label>
                    <label className="min-w-48 flex-1 text-sm">Feedback
                      <input className="mt-1 block w-full rounded border p-2" name="feedback" />
                    </label>
                    <button className="rounded bg-primary px-4 py-2 text-sm text-primary-fg disabled:opacity-50" disabled={createGrade.isPending}>Save draft grade</button>
                  </form>
                ) : <p className="text-sm text-subtle">No grade has been entered.</p>}
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
                      const grade = student.grades[assessment.id]
                      return <td className="p-3" key={assessment.id}>{grade ? `${grade.score} · ${grade.status}` : '—'}</td>
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
