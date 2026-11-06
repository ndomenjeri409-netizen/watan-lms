import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { useMe } from '../features/me/useMe'
import { hasRole } from '../features/me/roles'
import { PageHeader } from '../app/PageHeader'

async function loadCourses() {
  const { data, error } = await api.GET('/api/v1/courses/')
  if (error || !data) throw new Error('Unable to load courses.')
  return data.results ?? []
}

async function loadDepartments() {
  const { data, error } = await api.GET('/api/v1/departments/')
  if (error || !data) throw new Error('Unable to load departments.')
  return data.results ?? []
}

async function loadModules(courseId: string) {
  const { data, error } = await api.GET('/api/v1/course-modules/', {
    params: { query: { course: courseId } },
  })
  if (error || !data) throw new Error('Unable to load course modules.')
  return data.results ?? []
}

async function loadUnits(moduleId: string) {
  const { data, error } = await api.GET('/api/v1/course-units/', {
    params: { query: { module: moduleId } },
  })
  if (error || !data) throw new Error('Unable to load course units.')
  return data.results ?? []
}

async function loadLessons(unitId: string) {
  const { data, error } = await api.GET('/api/v1/lessons/', {
    params: { query: { unit: unitId } },
  })
  if (error || !data) throw new Error('Unable to load lessons.')
  return data.results ?? []
}

function assertSuccess(error: unknown) {
  if (error) throw new Error('The change could not be saved.')
}

export function CourseEditor() {
  const { data: profile } = useMe()
  const queryClient = useQueryClient()
  const [courseId, setCourseId] = useState('')
  const [moduleId, setModuleId] = useState('')
  const [unitId, setUnitId] = useState('')
  const [lessonId, setLessonId] = useState('')
  const [formError, setFormError] = useState('')
  const canCreateCourse = hasRole(profile, 'SUPER_ADMIN', 'ADMIN', 'HOD')
  const canEditCourses = canCreateCourse || hasRole(profile, 'TEACHER')
  const canPublishCourse = canEditCourses

  const coursesQuery = useQuery({ queryKey: ['courses'], queryFn: loadCourses })
  const departmentsQuery = useQuery({
    queryKey: ['departments'],
    queryFn: loadDepartments,
    enabled: canCreateCourse,
  })
  const modulesQuery = useQuery({
    queryKey: ['course-modules', courseId],
    queryFn: () => loadModules(courseId),
    enabled: Boolean(courseId),
  })
  const unitsQuery = useQuery({
    queryKey: ['course-units', moduleId],
    queryFn: () => loadUnits(moduleId),
    enabled: Boolean(moduleId),
  })
  const lessonsQuery = useQuery({
    queryKey: ['lessons', unitId],
    queryFn: () => loadLessons(unitId),
    enabled: Boolean(unitId),
  })

  const createCourse = useMutation({
    mutationFn: async (form: FormData) => {
      const { data, error } = await api.POST('/api/v1/courses/', {
        body: {
          department: form.get('department')?.toString() ?? '',
          title: form.get('title')?.toString() ?? '',
          code: form.get('code')?.toString() ?? '',
          summary: form.get('summary')?.toString() ?? '',
          description: form.get('description')?.toString() ?? '',
          status: 'DRAFT',
        },
      })
      assertSuccess(error)
      if (!data) throw new Error('The course could not be created.')
      return data
    },
    onSuccess: async (course) => {
      setCourseId(course.id)
      await queryClient.invalidateQueries({ queryKey: ['courses'] })
    },
    onError: (error) => setFormError(error.message),
  })

  const publishCourse = useMutation({
    mutationFn: async () => {
      const course = coursesQuery.data?.find((item) => item.id === courseId)
      if (!course) throw new Error('Select a course to publish.')
      const { error } = await api.PATCH('/api/v1/courses/{slug}/', {
        params: { path: { slug: course.slug } },
        body: { status: 'PUBLISHED' },
      })
      assertSuccess(error)
    },
    onSuccess: async () => {
      setFormError('')
      await queryClient.invalidateQueries({ queryKey: ['courses'] })
    },
    onError: (error) => setFormError(error.message),
  })

  const createModule = useMutation({
    mutationFn: async (form: FormData) => {
      const { data, error } = await api.POST('/api/v1/course-modules/', {
        body: {
          course: courseId,
          title: form.get('title')?.toString() ?? '',
          description: form.get('description')?.toString() ?? '',
          position: Number(form.get('position')),
        },
      })
      assertSuccess(error)
      if (!data) throw new Error('The module could not be created.')
      return data
    },
    onSuccess: async (module) => {
      setModuleId(module.id)
      await queryClient.invalidateQueries({ queryKey: ['course-modules', courseId] })
    },
    onError: (error) => setFormError(error.message),
  })

  const createUnit = useMutation({
    mutationFn: async (form: FormData) => {
      const { data, error } = await api.POST('/api/v1/course-units/', {
        body: {
          module: moduleId,
          title: form.get('title')?.toString() ?? '',
          description: form.get('description')?.toString() ?? '',
          position: Number(form.get('position')),
        },
      })
      assertSuccess(error)
      if (!data) throw new Error('The unit could not be created.')
      return data
    },
    onSuccess: async (unit) => {
      setUnitId(unit.id)
      await queryClient.invalidateQueries({ queryKey: ['course-units', moduleId] })
    },
    onError: (error) => setFormError(error.message),
  })

  const createLesson = useMutation({
    mutationFn: async (form: FormData) => {
      const { data, error } = await api.POST('/api/v1/lessons/', {
        body: {
          unit: unitId,
          title: form.get('title')?.toString() ?? '',
          description: form.get('description')?.toString() ?? '',
          video_url: form.get('video_url')?.toString() ?? '',
          position: Number(form.get('position')),
          duration_minutes: Number(form.get('duration_minutes')) || 0,
        },
      })
      assertSuccess(error)
      if (!data) throw new Error('The lesson could not be created.')
      return data
    },
    onSuccess: async (lesson) => {
      setLessonId(lesson.id)
      await queryClient.invalidateQueries({ queryKey: ['lessons', unitId] })
    },
    onError: (error) => setFormError(error.message),
  })

  const createMaterial = useMutation({
    mutationFn: async (form: FormData) => {
      const { error } = await api.POST('/api/v1/materials/', {
        body: {
          lesson: lessonId,
          title: form.get('title')?.toString() ?? '',
          kind: 'LINK',
          url: form.get('url')?.toString() ?? '',
        },
      })
      assertSuccess(error)
    },
    onError: (error) => setFormError(error.message),
  })

  if (!profile || !canEditCourses) {
    return <main className="p-6" role="alert">You do not have access to course management.</main>
  }

  const fieldClass = 'w-full rounded border border-line bg-white p-2'
  const formClass = 'grid gap-3 rounded-xl border border-line bg-white p-5'

  return (
    <section className="space-y-6">
      <PageHeader
        title="Course management"
        description="Create courses and build their curriculum."
      />

      {formError && <p role="alert" className="text-danger-fg">{formError}</p>}
      {coursesQuery.isError && <p role="alert" className="text-danger-fg">Courses could not be loaded.</p>}
      {departmentsQuery.isError && <p role="alert" className="text-danger-fg">Departments could not be loaded.</p>}

      <label className="block">
        <span className="mb-1 block font-medium">Choose a course</span>
        <select
          className={fieldClass}
          value={courseId}
          onChange={(event) => {
            setCourseId(event.target.value)
            setModuleId('')
            setUnitId('')
            setLessonId('')
          }}
        >
          <option value="">Select a course</option>
          {coursesQuery.data?.filter((course) => !hasRole(profile, 'TEACHER') || course.created_by === profile.id).map((course) => (
            <option key={course.id} value={course.id}>{course.code} — {course.title}</option>
          ))}
        </select>
      </label>

      {courseId && canPublishCourse && coursesQuery.data?.find((course) => course.id === courseId)?.status !== 'PUBLISHED' && (
        <button
          className="rounded border border-line px-4 py-2 text-sm disabled:opacity-60"
          disabled={publishCourse.isPending}
          onClick={() => {
            setFormError('')
            publishCourse.mutate()
          }}
          type="button"
        >
          {publishCourse.isPending ? 'Publishing…' : 'Publish selected course'}
        </button>
      )}

      {canCreateCourse && (
        <form
          className={formClass}
          onSubmit={(event) => {
            event.preventDefault()
            setFormError('')
            createCourse.mutate(new FormData(event.currentTarget))
          }}
        >
          <h2 className="text-xl font-semibold">Create a course</h2>
          <select className={fieldClass} name="department" required defaultValue="">
            <option value="" disabled>Select a department</option>
            {departmentsQuery.data?.map((department) => (
              <option key={department.id} value={department.id}>{department.name}</option>
            ))}
          </select>
          <input className={fieldClass} name="title" placeholder="Course title" required />
          <input className={fieldClass} name="code" placeholder="Course code" required />
          <input className={fieldClass} name="summary" placeholder="Short summary" />
          <textarea className={fieldClass} name="description" placeholder="Course description" rows={4} />
          <button className="rounded bg-primary px-4 py-2 font-medium text-primary-fg disabled:opacity-60" disabled={createCourse.isPending}>
            {createCourse.isPending ? 'Creating…' : 'Create draft course'}
          </button>
        </form>
      )}

      {courseId && (
        <div className="space-y-5">
          <form
            className={formClass}
            onSubmit={(event) => {
              event.preventDefault()
              setFormError('')
              createModule.mutate(new FormData(event.currentTarget))
            }}
          >
            <h2 className="text-xl font-semibold">Add a module</h2>
            <input className={fieldClass} name="title" placeholder="Module title" required />
            <textarea className={fieldClass} name="description" placeholder="Description (optional)" rows={2} />
            <input className={fieldClass} name="position" type="number" min="1" defaultValue="1" required />
            <button className="rounded bg-primary px-4 py-2 font-medium text-primary-fg disabled:opacity-60" disabled={createModule.isPending}>
              Add module
            </button>
          </form>

          <label className="block">
            <span className="mb-1 block font-medium">Module</span>
            <select className={fieldClass} value={moduleId} onChange={(event) => {
              setModuleId(event.target.value)
              setUnitId('')
              setLessonId('')
            }}>
              <option value="">Select a module</option>
              {modulesQuery.data?.map((module) => <option key={module.id} value={module.id}>{module.title}</option>)}
            </select>
          </label>
        </div>
      )}

      {moduleId && (
        <div className="space-y-5">
          <form className={formClass} onSubmit={(event) => {
            event.preventDefault()
            setFormError('')
            createUnit.mutate(new FormData(event.currentTarget))
          }}>
            <h2 className="text-xl font-semibold">Add a unit</h2>
            <input className={fieldClass} name="title" placeholder="Unit title" required />
            <textarea className={fieldClass} name="description" placeholder="Description (optional)" rows={2} />
            <input className={fieldClass} name="position" type="number" min="1" defaultValue="1" required />
            <button className="rounded bg-primary px-4 py-2 font-medium text-primary-fg disabled:opacity-60" disabled={createUnit.isPending}>
              Add unit
            </button>
          </form>

          <label className="block">
            <span className="mb-1 block font-medium">Unit</span>
            <select className={fieldClass} value={unitId} onChange={(event) => {
              setUnitId(event.target.value)
              setLessonId('')
            }}>
              <option value="">Select a unit</option>
              {unitsQuery.data?.map((unit) => <option key={unit.id} value={unit.id}>{unit.title}</option>)}
            </select>
          </label>
        </div>
      )}

      {unitId && (
        <div className="space-y-5">
          <form className={formClass} onSubmit={(event) => {
            event.preventDefault()
            setFormError('')
            createLesson.mutate(new FormData(event.currentTarget))
          }}>
            <h2 className="text-xl font-semibold">Add a lesson</h2>
            <input className={fieldClass} name="title" placeholder="Lesson title" required />
            <textarea className={fieldClass} name="description" placeholder="Description (optional)" rows={2} />
            <input className={fieldClass} name="video_url" type="url" placeholder="Video URL (optional)" />
            <input className={fieldClass} name="position" type="number" min="1" defaultValue="1" required />
            <input className={fieldClass} name="duration_minutes" type="number" min="0" placeholder="Duration in minutes" />
            <button className="rounded bg-primary px-4 py-2 font-medium text-primary-fg disabled:opacity-60" disabled={createLesson.isPending}>
              Add lesson
            </button>
          </form>

          <label className="block">
            <span className="mb-1 block font-medium">Lesson</span>
            <select className={fieldClass} value={lessonId} onChange={(event) => setLessonId(event.target.value)}>
              <option value="">Select a lesson</option>
              {lessonsQuery.data?.map((lesson) => <option key={lesson.id} value={lesson.id}>{lesson.title}</option>)}
            </select>
          </label>
        </div>
      )}

      {lessonId && (
        <form className={formClass} onSubmit={(event) => {
          event.preventDefault()
          setFormError('')
          createMaterial.mutate(new FormData(event.currentTarget))
        }}>
          <h2 className="text-xl font-semibold">Add an external material link</h2>
          <input className={fieldClass} name="title" placeholder="Material title" required />
          <input className={fieldClass} name="url" type="url" placeholder="https://…" required />
          <button className="rounded bg-primary px-4 py-2 font-medium text-primary-fg disabled:opacity-60" disabled={createMaterial.isPending}>
            Add material
          </button>
        </form>
      )}
    </section>
  )
}
