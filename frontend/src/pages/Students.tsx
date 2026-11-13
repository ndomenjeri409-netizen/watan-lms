import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useForm, useWatch } from 'react-hook-form'
import { z } from 'zod'
import { api } from '../api/client'
import type { components } from '../api/schema'
import { apiErrorMessage } from '../lib/apiError'
import { PageHeader } from '../app/PageHeader'
import { Button, Drawer, FormField, Input, Select, useToast } from '../components/ui'
import { hasRole } from '../features/me/roles'
import { useMe } from '../features/me/useMe'
import { auth } from '../lib/firebase'
import { t } from '../lib/i18n'

type Student = components['schemas']['Student']
type BusinessUnit = components['schemas']['BusinessUnit']
type ClassGroup = components['schemas']['ClassGroup']
type Course = components['schemas']['Course']
type DuplicateLookupMatch = components['schemas']['StudentDuplicateLookupMatch']
const registrationSchema = z.object({
  unit: z.string().uuid(t('Select a business unit.')),
  class_group: z.string().uuid(t('Select an open class.')),
  first_name: z.string().trim().min(1, t('Enter the first name.')),
  last_name: z.string().trim().min(1, t('Enter the last name.')),
  phone: z.string().trim().min(1, t('Enter the phone number.')),
  email: z.union([z.literal(''), z.email(t('Enter a valid email address.'))]).optional(),
})

type RegistrationFormValues = z.infer<typeof registrationSchema>

type DuplicateConflict = {
  message: string
  requires_exact_lookup?: boolean
  requires_confirmation?: boolean
  lookup_token?: string
  visible_matches?: Array<{ id?: string; name: string; home_unit: string; registration_number: string }>
  matches?: Array<{ id?: string; name: string; home_unit: string; registration_number: string }>
}

type StudentImportResult = components['schemas']['StudentImportResult']
type DuplicateSummary = NonNullable<DuplicateConflict['matches']>[number]

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function readDuplicateSummaries(value: unknown): DuplicateSummary[] | undefined {
  if (!Array.isArray(value)) return undefined
  const summaries: DuplicateSummary[] = []
  for (const item of value) {
    if (
      !isRecord(item)
      || typeof item.name !== 'string'
      || typeof item.home_unit !== 'string'
      || typeof item.registration_number !== 'string'
    ) {
      continue
    }
    summaries.push({
      ...(typeof item.id === 'string' ? { id: item.id } : {}),
      name: item.name,
      home_unit: item.home_unit,
      registration_number: item.registration_number,
    })
  }
  return summaries
}

function readDuplicateConflict(value: unknown): DuplicateConflict | null {
  if (!isRecord(value) || typeof value.message !== 'string') return null
  return {
    message: value.message,
    requires_exact_lookup: value.requires_exact_lookup === true,
    requires_confirmation: value.requires_confirmation === true,
    lookup_token: typeof value.lookup_token === 'string' ? value.lookup_token : undefined,
    visible_matches: readDuplicateSummaries(value.visible_matches),
    matches: readDuplicateSummaries(value.matches),
  }
}

function isImportResult(value: unknown): value is StudentImportResult {
  return isRecord(value)
    && typeof value.created === 'number'
    && Array.isArray(value.row_errors)
    && value.row_errors.every((error) =>
      isRecord(error)
      && typeof error.row === 'number'
      && typeof error.message === 'string',
    )
}

export function Students() {
  const { data: profile } = useMe()
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [registrationOpen, setRegistrationOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [duplicateConflict, setDuplicateConflict] = useState<DuplicateConflict | null>(null)
  const [lookupMatches, setLookupMatches] = useState<DuplicateLookupMatch[]>([])
  const [lookupQuery, setLookupQuery] = useState('')
  const [lookupIsRegistrationNumber, setLookupIsRegistrationNumber] = useState(false)
  const [importResult, setImportResult] = useState<StudentImportResult | null>(null)
  const canRegisterStudents = hasRole(profile, 'SUPER_ADMIN', 'ADMIN', 'HOD', 'UNIT_MANAGER')
  const registrationForm = useForm<RegistrationFormValues>({
    resolver: zodResolver(registrationSchema),
    defaultValues: { unit: '', class_group: '', first_name: '', last_name: '', phone: '', email: '' },
  })
  const selectedUnit = useWatch({ control: registrationForm.control, name: 'unit' })

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
  const unitsQuery = useQuery({
    queryKey: ['units', 'student-registration'],
    enabled: registrationOpen,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/units', {
        params: { query: { page_size: 100 } },
      })
      if (error) throw new Error(apiErrorMessage(error, t('Unable to load business units.')))
      if (!data) throw new Error(t('The server returned no business units.'))
      return data.results as BusinessUnit[]
    },
  })
  const coursesQuery = useQuery({
    queryKey: ['courses', 'student-registration'],
    enabled: registrationOpen,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/courses/', {
        params: { query: { page_size: 100 } },
      })
      if (error) throw new Error(apiErrorMessage(error, t('Unable to load courses.')))
      if (!data) throw new Error(t('The server returned no course data.'))
      return data.results as Course[]
    },
  })
  const classesQuery = useQuery({
    queryKey: ['class-groups', 'student-registration'],
    enabled: registrationOpen,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/class-groups/', {
        params: { query: { page_size: 100 } },
      })
      if (error) throw new Error(apiErrorMessage(error, t('Unable to load classes.')))
      if (!data) throw new Error(t('The server returned no class data.'))
      return data.results as ClassGroup[]
    },
  })
  const coursesById = new Map((coursesQuery.data ?? []).map((course) => [course.id, course]))
  const availableClasses = (classesQuery.data ?? []).filter((group) => {
    const course = coursesById.get(group.course)
    return group.is_active
      && (group.status === 'OPEN' || group.status === 'RUNNING')
      && course?.unit === selectedUnit
      && course.is_active
      && course.status === 'PUBLISHED'
  })

  const registerStudent = useMutation({
    mutationFn: async (values: RegistrationFormValues & { confirm_duplicate?: boolean }) => {
      const { data, error, response } = await api.POST('/api/v1/students/', {
        body: { ...values, confirm_duplicate: values.confirm_duplicate ?? false },
      })
      if (response.status === 409) {
        const conflict = readDuplicateConflict(error)
        if (conflict) return { kind: 'duplicate' as const, conflict }
      }
      if (error) throw new Error(apiErrorMessage(error, t('Unable to register this student.')))
      if (!data) throw new Error(t('The server returned no student record.'))
      return { kind: 'created' as const, student: data }
    },
    onSuccess: (result) => {
      if (result.kind === 'duplicate') {
        setDuplicateConflict(result.conflict)
        setLookupMatches([])
        return
      }
      setDuplicateConflict(null)
      setRegistrationOpen(false)
      registrationForm.reset()
      void queryClient.invalidateQueries({ queryKey: ['students'] })
      toast({ title: t('Student registered'), description: result.student.registration_number, variant: 'success' })
    },
  })
  const exactLookup = useMutation({
    mutationFn: async () => {
      if (!duplicateConflict?.lookup_token || !lookupQuery.trim()) {
        throw new Error(t('Enter a phone number or registration number for the exact lookup.'))
      }
      const { data, error } = await api.POST('/api/v1/students/duplicate-lookup/', {
        body: {
          token: duplicateConflict.lookup_token,
          ...(lookupIsRegistrationNumber
            ? { registration_number: lookupQuery.trim() }
            : { phone: lookupQuery.trim() }),
        },
      })
      if (error) throw new Error(apiErrorMessage(error, t('The exact lookup failed.')))
      return data?.matches ?? []
    },
    onSuccess: (matches) => {
      setLookupMatches(matches)
      if (matches.length === 0) {
        toast({ title: t('No exact match found'), description: t('You can continue only after resolving the possible duplicate.'), variant: 'error' })
      }
    },
  })
  const enrollExisting = useMutation({
    mutationFn: async ({ classGroup, token }: { classGroup: string; token: string }) => {
      const { data, error } = await api.POST('/api/v1/students/enroll-in-unit/', {
        body: { class_group: classGroup, enrollment_token: token },
      })
      if (error) throw new Error(apiErrorMessage(error, t('Unable to enroll this student.')))
      if (!data) throw new Error(t('The server returned no enrollment.'))
      return data
    },
    onSuccess: () => {
      setRegistrationOpen(false)
      setDuplicateConflict(null)
      setLookupMatches([])
      registrationForm.reset()
      void queryClient.invalidateQueries({ queryKey: ['students'] })
      toast({ title: t('Student enrolled in this unit'), variant: 'success' })
    },
  })
  const importStudents = useMutation({
    mutationFn: async (file: File) => {
      const user = auth.currentUser
      if (!user) throw new Error(t('Sign in again before importing students.'))
      const token = await user.getIdToken()
      const formData = new FormData()
      formData.append('file', file)
      const url = new URL('/api/v1/students/import/', import.meta.env.VITE_API_URL || window.location.origin)
      const response = await fetch(url, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      })
      const payload: unknown = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, t('Unable to import students.')))
      if (!isImportResult(payload)) throw new Error(t('The server returned an invalid import report.'))
      return payload
    },
    onSuccess: (result) => {
      setImportResult(result)
      void queryClient.invalidateQueries({ queryKey: ['students'] })
    },
  })

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <PageHeader title={t('Students')} />
        <Link className="text-sm underline" to="/app/admissions">Admissions queue</Link>
      </div>
      {canRegisterStudents && (
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => setRegistrationOpen(true)}>{t('Register student')}</Button>
          <Button variant="secondary" onClick={() => { setImportResult(null); setImportOpen(true) }}>{t('Import CSV')}</Button>
        </div>
      )}
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
                <th className="p-3">{t('Home unit')}</th>
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
                  <td className="p-3">{student.home_unit_code ?? '—'}</td>
                  <td className="p-3">{student.email}</td>
                  <td className="p-3">{student.phone || '—'}</td>
                  <td className="p-3">{student.admission_year}</td>
                </tr>
              ))}
              {studentsQuery.data.results.length === 0 && (
                <tr><td className="p-3 text-subtle" colSpan={6}>No students found.</td></tr>
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
      <Drawer
        open={registrationOpen}
        onOpenChange={(open) => {
          setRegistrationOpen(open)
          if (!open) {
            setDuplicateConflict(null)
            setLookupMatches([])
            exactLookup.reset()
            registerStudent.reset()
          }
        }}
        title={t('Register student')}
        description={t('Register a student and enroll them in an open class. A student account is not required.')}
      >
        {(unitsQuery.isError || coursesQuery.isError || classesQuery.isError) && (
          <p role="alert" className="mb-3 text-danger-fg">
            {unitsQuery.error?.message ?? coursesQuery.error?.message ?? classesQuery.error?.message}
          </p>
        )}
        {registerStudent.isError && <p role="alert" className="mb-3 text-danger-fg">{registerStudent.error.message}</p>}
        {exactLookup.isError && <p role="alert" className="mb-3 text-danger-fg">{exactLookup.error.message}</p>}
        {enrollExisting.isError && <p role="alert" className="mb-3 text-danger-fg">{enrollExisting.error.message}</p>}
        {(unitsQuery.isPending || coursesQuery.isPending || classesQuery.isPending) && (
          <p role="status" className="mb-3">{t('Loading registration options…')}</p>
        )}
        <form
          className="grid gap-4"
          onSubmit={registrationForm.handleSubmit((values) => {
            setDuplicateConflict(null)
            registerStudent.mutate(values)
          })}
        >
          <FormField label={t('Business unit')} error={registrationForm.formState.errors.unit?.message}>
            <Select
              {...registrationForm.register('unit')}
              onChange={(event) => {
                registrationForm.setValue('unit', event.target.value, { shouldValidate: true })
                registrationForm.setValue('class_group', '', { shouldValidate: true })
                setDuplicateConflict(null)
                setLookupMatches([])
              }}
            >
              <option value="">{t('Select a unit')}</option>
              {(unitsQuery.data ?? []).filter((unit) => unit.is_active).map((unit) => (
                <option key={unit.id} value={unit.id}>{unit.code} — {unit.name}</option>
              ))}
            </Select>
          </FormField>
          <FormField label={t('Open class')} error={registrationForm.formState.errors.class_group?.message}>
            <Select {...registrationForm.register('class_group')}>
              <option value="">{t('Select a class')}</option>
              {availableClasses.map((group) => (
                <option key={group.id} value={group.id}>{group.code} — {group.course_title}</option>
              ))}
            </Select>
          </FormField>
          {!classesQuery.isPending && selectedUnit && availableClasses.length === 0 && (
            <p className="text-sm text-subtle">{t('No open classes are available for this unit.')}</p>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField label={t('First name')} error={registrationForm.formState.errors.first_name?.message}>
              <Input autoComplete="given-name" {...registrationForm.register('first_name')} />
            </FormField>
            <FormField label={t('Last name')} error={registrationForm.formState.errors.last_name?.message}>
              <Input autoComplete="family-name" {...registrationForm.register('last_name')} />
            </FormField>
          </div>
          <FormField label={t('Phone')} error={registrationForm.formState.errors.phone?.message}>
            <Input type="tel" autoComplete="tel" {...registrationForm.register('phone')} />
          </FormField>
          <FormField label={t('Email (optional)')} error={registrationForm.formState.errors.email?.message}>
            <Input type="email" autoComplete="email" {...registrationForm.register('email')} />
          </FormField>
          {duplicateConflict && (
            <div className="space-y-3 rounded-lg border border-line bg-surface-2 p-3" role="status">
              <p>{duplicateConflict.message}</p>
              {(duplicateConflict.matches ?? duplicateConflict.visible_matches ?? []).map((match) => (
                <p key={`${match.home_unit}-${match.registration_number}`} className="text-sm">
                  {match.name} · {match.home_unit} · {match.registration_number}
                </p>
              ))}
              {duplicateConflict.requires_confirmation && (
                <Button
                  type="button"
                  variant="secondary"
                  disabled={registerStudent.isPending}
                  onClick={() => registerStudent.mutate({
                    ...registrationForm.getValues(),
                    confirm_duplicate: true,
                  })}
                >
                  {t('Confirm new registration')}
                </Button>
              )}
              {duplicateConflict.requires_exact_lookup && (
                <div className="grid gap-3">
                  <p className="text-sm">{t('Verify a possible cross-unit match using one exact phone number or registration number. Only a minimal match summary will be shown.')}</p>
                  <FormField label={t('Exact lookup value')}>
                    <Input value={lookupQuery} onChange={(event) => setLookupQuery(event.target.value)} />
                  </FormField>
                  <FormField label={t('Lookup by')}>
                    <Select value={lookupIsRegistrationNumber ? 'registration_number' : 'phone'} onChange={(event) => setLookupIsRegistrationNumber(event.target.value === 'registration_number')}>
                      <option value="phone">{t('Phone')}</option>
                      <option value="registration_number">{t('Registration number')}</option>
                    </Select>
                  </FormField>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={exactLookup.isPending || !lookupQuery.trim()}
                    onClick={() => exactLookup.mutate()}
                  >
                    {exactLookup.isPending ? t('Checking…') : t('Run exact lookup')}
                  </Button>
                  {lookupMatches.map((match) => (
                    <article key={match.enrollment_token} className="grid gap-2 rounded border border-line bg-white p-3">
                      <p className="text-sm">{match.name} · {match.home_unit} · {match.registration_number}</p>
                      <Button
                        type="button"
                        disabled={!registrationForm.getValues('class_group') || enrollExisting.isPending}
                        onClick={() => enrollExisting.mutate({
                          classGroup: registrationForm.getValues('class_group'),
                          token: match.enrollment_token,
                        })}
                      >
                        {t('Enroll in my unit')}
                      </Button>
                    </article>
                  ))}
                </div>
              )}
            </div>
          )}
          <div className="flex justify-end gap-2 border-t border-line pt-3">
            <Button type="button" variant="secondary" onClick={() => setRegistrationOpen(false)}>{t('Cancel')}</Button>
            <Button type="submit" disabled={registerStudent.isPending || unitsQuery.isPending || classesQuery.isPending}>
              {registerStudent.isPending ? t('Registering…') : t('Register')}
            </Button>
          </div>
        </form>
      </Drawer>
      <Drawer
        open={importOpen}
        onOpenChange={(open) => {
          setImportOpen(open)
          if (!open) importStudents.reset()
        }}
        title={t('Import students from CSV')}
        description={t('Each valid row registers a student and enrolls them in the specified open class.')}
      >
        <div className="space-y-4">
          <p className="text-sm text-subtle">
            {t('Required headers: unit_code, class_code, first_name, last_name, phone. Optional: email, date_of_birth, national_id. Files must be UTF-8 and no larger than 5 MB.')}
          </p>
          {importStudents.isError && <p role="alert" className="text-danger-fg">{importStudents.error.message}</p>}
          <FormField label={t('CSV file')}>
            <Input
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) importStudents.mutate(file)
              }}
            />
          </FormField>
          {importStudents.isPending && <p role="status">{t('Importing students…')}</p>}
          {importResult && (
            <div className="space-y-2" role="status">
              <p>{t('Created')}: {importResult.created}</p>
              {importResult.row_errors.map((error) => (
                <p key={error.row} className="text-sm text-danger-fg">{t('Row')} {error.row}: {error.message}</p>
              ))}
              {importResult.row_errors.length === 0 && <p className="text-sm text-subtle">{t('No row errors.')}</p>}
            </div>
          )}
        </div>
      </Drawer>
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
          <div><dt className="text-subtle">Status</dt><dd>{student.status ?? (student.is_active ? 'ACTIVE' : 'INACTIVE')}</dd></div>
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
