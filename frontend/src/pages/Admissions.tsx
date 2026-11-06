import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { sendPasswordResetEmail } from 'firebase/auth'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { components } from '../api/schema'
import { auth } from '../lib/firebase'
import { apiErrorMessage } from '../lib/apiError'
import { PageHeader } from '../app/PageHeader'
import { useMe } from '../features/me/useMe'
import { hasRole } from '../features/me/roles'

type Application = components['schemas']['Application']

export function Apply() {
  const [submitted, setSubmitted] = useState(false)
  const [formError, setFormError] = useState('')
  const coursesQuery = useQuery({
    queryKey: ['courses'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/courses/')
      if (error) throw new Error(apiErrorMessage(error, 'Unable to load courses.'))
      if (!data) throw new Error('The server returned no course data.')
      return data.results
    },
  })
  const submitApplication = useMutation({
    mutationFn: async (form: FormData) => {
      const { data, error } = await api.POST('/api/v1/applications/', {
        body: {
          course: form.get('course')?.toString() ?? '',
          program: form.get('program')?.toString() || null,
          first_name: form.get('first_name')?.toString() ?? '',
          last_name: form.get('last_name')?.toString() ?? '',
          email: form.get('email')?.toString() ?? '',
          phone: form.get('phone')?.toString() ?? '',
          statement: form.get('statement')?.toString() ?? '',
        },
      })
      if (error) throw new Error(apiErrorMessage(error, 'Unable to submit your application.'))
      if (!data) throw new Error('The server returned no application confirmation.')
      return data
    },
    onSuccess: () => {
      setSubmitted(true)
      setFormError('')
    },
    onError: (error) => setFormError(error.message),
  })

  if (submitted) {
    return (
      <main className="mx-auto max-w-xl space-y-4 p-6">
        <Link className="text-sm underline" to="/courses">← Course catalog</Link>
        <div className="rounded-xl border border-success/40 bg-white p-6">
          <h1 className="text-2xl font-semibold">Application received</h1>
          <p className="mt-2 text-subtle">
            Your application is pending review. If accepted, we’ll email you instructions to access your student account.
          </p>
        </div>
      </main>
    )
  }

  return (
    <main className="mx-auto max-w-xl space-y-5 p-6">
      <Link className="text-sm underline" to="/courses">← Course catalog</Link>
      <header>
        <h1 className="text-3xl font-semibold">Apply for a course</h1>
        <p className="mt-2 text-subtle">Submit your details for staff review.</p>
      </header>
      {coursesQuery.isError && <p role="alert" className="text-danger-fg">{coursesQuery.error.message}</p>}
      {formError && <p role="alert" className="text-danger-fg">{formError}</p>}
      <form className="grid gap-4 rounded-xl border border-line bg-white p-5" onSubmit={(event) => {
        event.preventDefault()
        setFormError('')
        submitApplication.mutate(new FormData(event.currentTarget))
      }}>
        <label className="grid gap-1">
          Course
          <select className="rounded border border-line bg-white p-2" name="course" required defaultValue="">
            <option value="" disabled>Select a published course</option>
            {coursesQuery.data?.map((course) => (
              <option key={course.id} value={course.id}>{course.code} — {course.title}</option>
            ))}
          </select>
        </label>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="grid gap-1">
            First name
            <input className="rounded border border-line p-2" name="first_name" autoComplete="given-name" required />
          </label>
          <label className="grid gap-1">
            Last name
            <input className="rounded border border-line p-2" name="last_name" autoComplete="family-name" required />
          </label>
        </div>
        <label className="grid gap-1">
          Email
          <input className="rounded border border-line p-2" name="email" type="email" autoComplete="email" required />
        </label>
        <label className="grid gap-1">
          Phone (optional)
          <input className="rounded border border-line p-2" name="phone" type="tel" autoComplete="tel" />
        </label>
        <label className="grid gap-1">
          Tell us briefly about your interest (optional)
          <textarea className="rounded border border-line p-2" name="statement" rows={4} />
        </label>
        <button className="rounded bg-primary p-3 font-medium text-primary-fg disabled:opacity-60" disabled={submitApplication.isPending || coursesQuery.isPending || !coursesQuery.data?.length}>
          {submitApplication.isPending ? 'Submitting…' : 'Submit application'}
        </button>
      </form>
    </main>
  )
}

export function AdmissionsQueue() {
  const { data: profile } = useMe()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [feedback, setFeedback] = useState('')
  const applicationsQuery = useQuery({
    queryKey: ['applications', page],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/applications/', {
        params: { query: { page, page_size: 20, status: 'PENDING', ordering: 'created_at' } },
      })
      if (error) throw new Error(apiErrorMessage(error, 'Unable to load applications.'))
      if (!data) throw new Error('The server returned no application data.')
      return data
    },
  })
  const approve = useMutation({
    mutationFn: async (application: Application) => {
      const { data, error } = await api.POST('/api/v1/applications/{id}/approve/', {
        params: { path: { id: application.id } },
      })
      if (error) throw new Error(apiErrorMessage(error, 'Unable to approve this application.'))
      if (!data) throw new Error('The server returned no approval details.')
      let invitationSent = true
      try {
        await sendPasswordResetEmail(auth, data.student.email)
      } catch {
        invitationSent = false
      }
      return { data, invitationSent }
    },
    onSuccess: async ({ data, invitationSent }) => {
      setFeedback(invitationSent
        ? `Approved ${data.student.registration_number}; account setup email sent.`
        : `Approved ${data.student.registration_number}; send a password setup email to ${data.student.email} from Firebase.`)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['applications'] }),
        queryClient.invalidateQueries({ queryKey: ['students'] }),
        queryClient.invalidateQueries({ queryKey: ['enrollments'] }),
      ])
    },
    onError: (error) => setFeedback(error.message),
  })
  const reject = useMutation({
    mutationFn: async (application: Application) => {
      const { error } = await api.POST('/api/v1/applications/{id}/reject/', {
        params: { path: { id: application.id } },
        body: { note: '' },
      })
      if (error) throw new Error(apiErrorMessage(error, 'Unable to reject this application.'))
    },
    onSuccess: async () => {
      setFeedback('Application rejected.')
      await queryClient.invalidateQueries({ queryKey: ['applications'] })
    },
    onError: (error) => setFeedback(error.message),
  })
  const canReview = hasRole(profile, 'SUPER_ADMIN', 'ADMIN', 'HOD')

  return (
    <section className="space-y-5">
      <PageHeader title="Admissions queue" description="Review applications for your authorized departments." />
      {feedback && <p className="rounded border border-line bg-white p-3" role="status">{feedback}</p>}
      {applicationsQuery.isPending && <p role="status">Loading applications…</p>}
      {applicationsQuery.isError && <p role="alert" className="text-danger-fg">{applicationsQuery.error.message}</p>}
      <div className="space-y-3">
        {applicationsQuery.data?.results.map((application) => (
          <article key={application.id} className="space-y-3 rounded-xl border border-line bg-white p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">{application.first_name} {application.last_name}</h2>
                <p className="text-sm text-subtle">{application.email} · {application.phone || 'No phone'}</p>
                <p className="mt-1 text-sm">{application.course_title} · submitted {new Date(application.created_at).toLocaleDateString()}</p>
              </div>
              <span className="rounded bg-primary px-2 py-1 text-xs font-medium text-warning-fg">Pending</span>
            </div>
            {application.statement && <p className="whitespace-pre-wrap text-sm">{application.statement}</p>}
            <div className="flex gap-2">
              {canReview && <button
                className="rounded bg-primary px-3 py-2 text-sm font-medium text-primary-fg disabled:opacity-60"
                disabled={approve.isPending || reject.isPending}
                onClick={() => approve.mutate(application)}
                type="button"
              >
                Approve and provision student
              </button>}
              {canReview && <button
                className="rounded border border-line px-3 py-2 text-sm disabled:opacity-60"
                disabled={approve.isPending || reject.isPending}
                onClick={() => reject.mutate(application)}
                type="button"
              >
                Reject
              </button>}
            </div>
          </article>
        ))}
        {applicationsQuery.data?.results.length === 0 && (
          <p className="rounded-xl border border-line bg-white p-5">No pending applications.</p>
        )}
      </div>
      <div className="flex items-center justify-between">
        <button className="rounded border border-line px-3 py-2 text-sm disabled:opacity-50" disabled={!applicationsQuery.data?.previous || page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>
          Previous
        </button>
        <span className="text-sm text-subtle">Page {page}</span>
        <button className="rounded border border-line px-3 py-2 text-sm disabled:opacity-50" disabled={!applicationsQuery.data?.next} onClick={() => setPage((value) => value + 1)}>
          Next
        </button>
      </div>
    </section>
  )
}
