import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'

async function loadCourses() {
  const { data, error } = await api.GET('/api/v1/courses/')
  if (error || !data) throw new Error('Unable to load courses.')
  return data.results ?? []
}

async function loadCourse(slug: string) {
  const { data, error } = await api.GET('/api/v1/courses/{slug}/', {
    params: { path: { slug } },
  })
  if (error || !data) throw new Error('Unable to load this course.')
  return data
}

async function loadModules(courseId: string) {
  const { data, error } = await api.GET('/api/v1/course-modules/', {
    params: { query: { course: courseId } },
  })
  if (error || !data) throw new Error('Unable to load the course curriculum.')
  return data.results ?? []
}

export function Courses() {
  const { data: courses, isPending, isError } = useQuery({
    queryKey: ['courses'],
    queryFn: loadCourses,
  })

  return (
    <main className="mx-auto min-h-screen max-w-5xl space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link className="text-sm underline" to="/">Watan LMS</Link>
          <h1 className="mt-2 text-3xl font-semibold">Course catalog</h1>
          <p className="mt-1 text-subtle">Explore published courses.</p>
        </div>
        <Link className="rounded border border-line px-4 py-2 text-sm" to="/login">
          Staff sign in
        </Link>
        <Link className="rounded bg-primary px-4 py-2 text-sm text-primary-fg" to="/apply">
          Apply now
        </Link>
      </header>

      {isPending && <p>Loading courses…</p>}
      {isError && <p role="alert" className="text-danger-fg">Courses could not be loaded.</p>}
      {!isPending && !isError && courses?.length === 0 && (
        <p className="rounded-xl border border-line bg-white p-5">No published courses yet.</p>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        {courses?.map((course) => (
          <Link
            key={course.id}
            className="rounded-xl border border-line bg-white p-5 transition hover:border-line"
            to={`/courses/${course.slug}`}
          >
            <p className="text-xs font-medium uppercase tracking-wide text-subtle">
              {course.code}
            </p>
            <h2 className="mt-2 text-xl font-semibold">{course.title}</h2>
            {course.summary && <p className="mt-2 text-subtle">{course.summary}</p>}
          </Link>
        ))}
      </div>
    </main>
  )
}

export function CourseDetails() {
  const { slug = '' } = useParams()
  const courseQuery = useQuery({
    queryKey: ['course', slug],
    queryFn: () => loadCourse(slug),
    enabled: Boolean(slug),
  })
  const courseId = courseQuery.data?.id
  const modulesQuery = useQuery({
    queryKey: ['course-modules', courseId],
    queryFn: () => loadModules(courseId!),
    enabled: Boolean(courseId),
  })

  if (courseQuery.isPending) return <main className="p-6">Loading course…</main>
  if (courseQuery.isError || !courseQuery.data) {
    return <main className="p-6" role="alert">This course could not be loaded.</main>
  }

  return (
    <main className="mx-auto min-h-screen max-w-4xl space-y-6 p-6">
      <Link className="text-sm underline" to="/courses">← Course catalog</Link>
      <header className="rounded-xl border border-line bg-white p-6">
        <p className="text-sm font-medium uppercase tracking-wide text-subtle">
          {courseQuery.data.code}
        </p>
        <h1 className="mt-2 text-3xl font-semibold">{courseQuery.data.title}</h1>
        {courseQuery.data.summary && (
          <p className="mt-3 text-lg text-subtle">{courseQuery.data.summary}</p>
        )}
        {courseQuery.data.description && (
          <p className="mt-5 whitespace-pre-wrap">{courseQuery.data.description}</p>
        )}
      </header>

      <section aria-labelledby="curriculum-heading" className="space-y-3">
        <h2 id="curriculum-heading" className="text-2xl font-semibold">Course curriculum</h2>
        {modulesQuery.isError && <p role="alert" className="text-danger-fg">The curriculum could not be loaded.</p>}
        {modulesQuery.isPending && <p>Loading curriculum…</p>}
        {modulesQuery.data?.map((module) => (
          <article key={module.id} className="rounded-xl border border-line bg-white p-5">
            <h3 className="text-lg font-semibold">{module.title}</h3>
            {module.description && <p className="mt-1 text-subtle">{module.description}</p>}
          </article>
        ))}
        {modulesQuery.data?.length === 0 && (
          <p className="text-subtle">Course content will be added soon.</p>
        )}
      </section>
    </main>
  )
}
