import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { components } from '../api/schema'
import { apiErrorMessage } from '../lib/apiError'
import { PageHeader } from '../app/PageHeader'

type Student = components['schemas']['Student']

export function Students() {
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const studentsQuery = useQuery({
    queryKey: ['students', search, page],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/students/', {
        params: { query: { search: search || undefined, page, page_size: 20 } },
      })
      if (error) throw new Error(apiErrorMessage(error, 'Unable to load students.'))
      if (!data) throw new Error('The server returned no student data.')
      return data
    },
  })

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <PageHeader title="Students" />
        <Link className="text-sm underline" to="/app/admissions">Admissions queue</Link>
      </div>
      <label className="block">
        <span className="mb-1 block text-sm font-medium">Search students</span>
        <input
          className="w-full rounded border border-line bg-white p-2"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
            setPage(1)
          }}
          placeholder="Name, registration number, email or phone"
        />
      </label>
      {studentsQuery.isPending && <p role="status">Loading students…</p>}
      {studentsQuery.isError && <p role="alert" className="text-danger-fg">{studentsQuery.error.message}</p>}
      {studentsQuery.data && (
        <div className="scrollbar-thin overflow-x-auto rounded-xl border border-line bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-surface-2">
              <tr>
                <th className="p-3">Registration</th>
                <th className="p-3">Student</th>
                <th className="p-3">Email</th>
                <th className="p-3">Phone</th>
                <th className="p-3">Year</th>
              </tr>
            </thead>
            <tbody>
              {studentsQuery.data.results.map((student: Student) => (
                <tr className="border-t border-line" key={student.id}>
                  <td className="p-3 font-medium">
                    <Link className="underline" to={`/app/students/${student.id}`}>{student.registration_number}</Link>
                  </td>
                  <td className="p-3">{student.first_name} {student.last_name}</td>
                  <td className="p-3">{student.email}</td>
                  <td className="p-3">{student.phone || '—'}</td>
                  <td className="p-3">{student.admission_year}</td>
                </tr>
              ))}
              {studentsQuery.data.results.length === 0 && (
                <tr><td className="p-3 text-subtle" colSpan={5}>No students found.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      <div className="flex items-center justify-between">
        <button className="rounded border border-line px-3 py-2 text-sm disabled:opacity-50" disabled={!studentsQuery.data?.previous || page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>
          Previous
        </button>
        <span className="text-sm text-subtle">Page {page}</span>
        <button className="rounded border border-line px-3 py-2 text-sm disabled:opacity-50" disabled={!studentsQuery.data?.next} onClick={() => setPage((value) => value + 1)}>
          Next
        </button>
      </div>
    </section>
  )
}

export function StudentProfile() {
  const { id = '' } = useParams()
  const studentQuery = useQuery({
    queryKey: ['student', id],
    enabled: Boolean(id),
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/students/{id}/', {
        params: { path: { id } },
      })
      if (error) throw new Error(apiErrorMessage(error, 'Unable to load this student.'))
      if (!data) throw new Error('The server returned no student profile.')
      return data
    },
  })
  const enrollmentQuery = useQuery({
    queryKey: ['enrollments', id],
    enabled: Boolean(id),
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/enrollments/', {
        params: { query: { student: id, page_size: 100 } },
      })
      if (error) throw new Error(apiErrorMessage(error, 'Unable to load enrollments.'))
      if (!data) throw new Error('The server returned no enrollment data.')
      return data.results
    },
  })

  if (studentQuery.isPending) return <p role="status">Loading student profile…</p>
  if (studentQuery.isError || !studentQuery.data) {
    return <p role="alert" className="text-danger-fg">{studentQuery.error?.message ?? 'Student profile unavailable.'}</p>
  }
  const student = studentQuery.data
  return (
    <section className="space-y-5">
      <Link className="text-sm underline" to="/app/students">← Students</Link>
      <div className="rounded-xl border border-line bg-white p-5">
        <p className="text-sm text-subtle">{student.registration_number}</p>
        <PageHeader title={`${student.first_name} ${student.last_name}`} className="mb-0 mt-1" />
        <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
          <div><dt className="text-subtle">Email</dt><dd>{student.email}</dd></div>
          <div><dt className="text-subtle">Phone</dt><dd>{student.phone || '—'}</dd></div>
          <div><dt className="text-subtle">Admission year</dt><dd>{student.admission_year}</dd></div>
          <div><dt className="text-subtle">Status</dt><dd>{student.is_active ? 'Active' : 'Inactive'}</dd></div>
        </dl>
      </div>
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Enrollments</h2>
        {enrollmentQuery.isPending && <p role="status">Loading enrollments…</p>}
        {enrollmentQuery.isError && <p role="alert" className="text-danger-fg">{enrollmentQuery.error.message}</p>}
        {enrollmentQuery.data?.map((enrollment) => (
          <article key={enrollment.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-white p-4">
            <div>
              <h3 className="font-medium">{enrollment.course_title}</h3>
              <p className="text-sm text-subtle">{enrollment.course_code}</p>
            </div>
            <span className="rounded bg-surface-2 px-2 py-1 text-xs font-medium">{enrollment.status}</span>
          </article>
        ))}
        {enrollmentQuery.data?.length === 0 && <p className="text-subtle">No course enrollments yet.</p>}
      </section>
    </section>
  )
}
