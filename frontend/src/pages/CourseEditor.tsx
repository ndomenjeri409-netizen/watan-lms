import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { useMe } from '../features/me/useMe'
import { hasRole } from '../features/me/roles'
import { PageHeader } from '../app/PageHeader'
import { Button } from '../components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle, Drawer } from '../components/ui/dialog'
import { apiErrorMessage } from '../lib/apiError'
import { t } from '../lib/i18n'

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

async function loadPages<T>(
  loadPage: (page: number) => Promise<{ results?: T[]; next?: string | null }>,
) {
  const results: T[] = []
  for (let page = 1; ; page += 1) {
    const data = await loadPage(page)
    results.push(...(data.results ?? []))
    if (!data.next) return results
  }
}

async function loadModules(courseId: string) {
  return loadPages(async (page) => {
    const { data, error } = await api.GET('/api/v1/course-modules/', {
      params: { query: { course: courseId, page, page_size: 100 } },
    })
    if (error || !data) throw new Error('Unable to load course modules.')
    return data
  })
}

async function loadUnits(moduleId: string) {
  return loadPages(async (page) => {
    const { data, error } = await api.GET('/api/v1/course-units/', {
      params: { query: { module: moduleId, page, page_size: 100 } },
    })
    if (error || !data) throw new Error('Unable to load course topics.')
    return data
  })
}

async function loadLessons(unitId: string) {
  return loadPages(async (page) => {
    const { data, error } = await api.GET('/api/v1/lessons/', {
      params: { query: { unit: unitId, page, page_size: 100 } },
    })
    if (error || !data) throw new Error('Unable to load lessons.')
    return data
  })
}

async function loadMaterials(lessonId: string) {
  return loadPages(async (page) => {
    const { data, error } = await api.GET('/api/v1/materials/', {
      params: { query: { lesson: lessonId, page, page_size: 100 } },
    })
    if (error || !data) throw new Error('Unable to load lesson materials.')
    return data
  })
}

async function loadCourseAssignments(courseId: string) {
  const { data, error } = await api.GET('/api/v1/course-assignments/', {
    params: { query: { course: courseId, is_active: true, page_size: 100 } },
  })
  if (error || !data) throw new Error('Unable to load course teachers.')
  return data.results ?? []
}

async function loadTeacherCourses(teacherId: string) {
  const { data, error } = await api.GET('/api/v1/course-assignments/', {
    params: { query: { teacher: teacherId, is_active: true, page_size: 100 } },
  })
  if (error || !data) throw new Error('Unable to load your course assignments.')
  return data.results ?? []
}

function assertSuccess(error: unknown) {
  if (error) throw new Error(apiErrorMessage(error, 'The change could not be saved.'))
}

function MaterialDownload({ fileId }: { fileId: string }) {
  const download = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.GET('/api/v1/files/{id}/download-url/', {
        params: { path: { id: fileId } },
      })
      assertSuccess(error)
      if (!data) throw new Error('The download link could not be prepared.')
      return data.download_url
    },
    onSuccess: (url) => {
      window.open(url, '_blank', 'noopener,noreferrer')
    },
  })

  return (
    <span className="inline-flex items-center gap-2">
      <Button
        variant="secondary"
        size="sm"
        loading={download.isPending}
        onClick={() => download.mutate()}
        type="button"
      >
        {t(download.isPending ? 'Preparing download…' : 'Download file')}
      </Button>
      {download.error && <span role="alert" className="text-danger-fg">{download.error.message}</span>}
    </span>
  )
}

function StudentPreview({ courseId }: { courseId: string }) {
  const modulesQuery = useQuery({
    queryKey: ['student-course-preview', courseId, 'modules'],
    queryFn: () => loadModules(courseId),
  })
  const modules = (modulesQuery.data ?? []).filter((item) => item.is_active && item.is_visible)
  const unitQueries = useQueries({
    queries: modules.map((module) => ({
      queryKey: ['student-course-preview', courseId, 'units', module.id],
      queryFn: () => loadUnits(module.id),
    })),
  })
  const units = modules.flatMap((module, index) =>
    (unitQueries[index]?.data ?? [])
      .filter((item) => item.is_active && item.is_visible)
      .map((unit) => ({ module, unit })),
  )
  const lessonQueries = useQueries({
    queries: units.map(({ unit }) => ({
      queryKey: ['student-course-preview', courseId, 'lessons', unit.id],
      queryFn: () => loadLessons(unit.id),
    })),
  })
  const lessons = units.flatMap(({ module, unit }, index) =>
    (lessonQueries[index]?.data ?? [])
      .filter((item) => item.is_active && item.is_visible)
      .map((lesson) => ({ module, unit, lesson })),
  )
  const materialQueries = useQueries({
    queries: lessons.map(({ lesson }) => ({
      queryKey: ['student-course-preview', courseId, 'materials', lesson.id],
      queryFn: () => loadMaterials(lesson.id),
    })),
  })
  const materials = lessons.flatMap(({ lesson, ...parents }, index) =>
    (materialQueries[index]?.data ?? [])
      .filter((item) => item.is_active && item.is_visible)
      .map((material) => ({ ...parents, lesson, material })),
  )
  const loading =
    modulesQuery.isLoading ||
    unitQueries.some((query) => query.isLoading) ||
    lessonQueries.some((query) => query.isLoading) ||
    materialQueries.some((query) => query.isLoading)
  const failed =
    modulesQuery.isError ||
    unitQueries.some((query) => query.isError) ||
    lessonQueries.some((query) => query.isError) ||
    materialQueries.some((query) => query.isError)

  return (
    <section className="space-y-3 rounded-xl border border-line bg-white p-5" aria-label={t('Student preview')}>
      <h2 className="text-xl font-semibold">{t('Student preview')}</h2>
      <p className="text-sm text-subtle">{t('Only active, visible course content appears here.')}</p>
      {loading && <p role="status">{t('Loading course preview…')}</p>}
      {failed && <p role="alert" className="text-danger-fg">{t('The course preview could not be loaded.')}</p>}
      {!loading && !failed && modules.length === 0 && (
        <p className="text-sm text-subtle">{t('No visible modules are available.')}</p>
      )}
      {!loading && !failed && modules.map((module) => (
        <article className="space-y-2 border-t border-line pt-3" key={module.id}>
          <h3 className="font-semibold">{module.position}. {module.title}</h3>
          {module.description && <p className="text-sm text-subtle">{module.description}</p>}
          <ul className="space-y-3 pl-4">
            {units.filter(({ unit }) => unit.module === module.id).map(({ unit }) => (
              <li key={unit.id}>
                <h4 className="font-medium">{unit.position}. {unit.title}</h4>
                {unit.description && <p className="text-sm text-subtle">{unit.description}</p>}
                <ul className="space-y-2 pl-4">
                  {lessons.filter((entry) => entry.unit.id === unit.id).map(({ lesson }) => (
                    <li key={lesson.id}>
                      <p className="font-medium">{lesson.position}. {lesson.title}</p>
                      {lesson.description && <p className="text-sm text-subtle">{lesson.description}</p>}
                      {lesson.video_url && (
                        <a className="text-sm underline" href={lesson.video_url} target="_blank" rel="noreferrer">
                          {t('Watch lesson video')}
                        </a>
                      )}
                      <ul className="mt-1 space-y-1">
                        {materials.filter((entry) => entry.lesson.id === lesson.id).map(({ material }) => (
                          <li key={material.id}>
                            {material.kind === 'LINK' && material.url ? (
                              <a className="text-sm underline" href={material.url} target="_blank" rel="noreferrer">
                                {material.title}
                              </a>
                            ) : material.file ? (
                              <span className="inline-flex items-center gap-2">
                                <span className="text-sm">{material.title}</span>
                                <MaterialDownload fileId={material.file} />
                              </span>
                            ) : (
                              <span className="text-sm">{material.title}</span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </article>
      ))}
    </section>
  )
}

type ModuleRecord = Awaited<ReturnType<typeof loadModules>>[number]
type TopicRecord = Awaited<ReturnType<typeof loadUnits>>[number]
type LessonRecord = Awaited<ReturnType<typeof loadLessons>>[number]
type MaterialRecord = Awaited<ReturnType<typeof loadMaterials>>[number]

type CurriculumEditTarget =
  | { type: 'module'; item: ModuleRecord }
  | { type: 'topic'; item: TopicRecord }
  | { type: 'lesson'; item: LessonRecord }
  | { type: 'material'; item: MaterialRecord }

type CurriculumItemTarget = {
  type: 'module' | 'topic' | 'lesson' | 'material'
  id: string
}

export function CourseEditor() {
  const { data: profile } = useMe()
  const queryClient = useQueryClient()
  const [courseId, setCourseId] = useState('')
  const [moduleId, setModuleId] = useState('')
  const [unitId, setUnitId] = useState('')
  const [lessonId, setLessonId] = useState('')
  const [formError, setFormError] = useState('')
  const [courseDetailsOpen, setCourseDetailsOpen] = useState(false)
  const [archiveDialogOpen, setArchiveDialogOpen] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [materialKind, setMaterialKind] = useState<'LINK' | 'FILE'>('LINK')
  const [editingCurriculumItem, setEditingCurriculumItem] = useState<CurriculumEditTarget | null>(null)
  const [curriculumArchiveTarget, setCurriculumArchiveTarget] = useState<CurriculumItemTarget | null>(null)
  const canManageCourses = hasRole(profile, 'SUPER_ADMIN', 'ADMIN', 'HOD', 'UNIT_MANAGER')
  const canEditCourses = canManageCourses || hasRole(profile, 'TEACHER')
  const isTeacherOnly = hasRole(profile, 'TEACHER') && !canManageCourses
  const canPublishCourse = canManageCourses

  const coursesQuery = useQuery({ queryKey: ['courses'], queryFn: loadCourses })
  const selectedCourse = coursesQuery.data?.find((course) => course.id === courseId)
  const teacherAssignmentsQuery = useQuery({
    queryKey: ['course-assignments', 'teacher', profile?.id],
    queryFn: () => loadTeacherCourses(profile!.id),
    enabled: Boolean(profile?.id && isTeacherOnly),
  })
  const courseAssignmentsQuery = useQuery({
    queryKey: ['course-assignments', courseId],
    queryFn: () => loadCourseAssignments(courseId),
    enabled: Boolean(courseId),
  })
  const teachersQuery = useQuery({
    queryKey: ['teachers', 'course-assignments'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/users/', {
        params: { query: { role: 'TEACHER', is_active: true, page_size: 100 } },
      })
      if (error || !data) throw new Error('Unable to load teachers.')
      return data.results ?? []
    },
    enabled: canManageCourses,
  })
  const departmentsQuery = useQuery({
    queryKey: ['departments'],
    queryFn: loadDepartments,
    enabled: canManageCourses,
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
  const materialsQuery = useQuery({
    queryKey: ['materials', lessonId],
    queryFn: () => loadMaterials(lessonId),
    enabled: Boolean(lessonId),
  })
  const selectedModule = modulesQuery.data?.find((item) => item.id === moduleId)
  const selectedTopic = unitsQuery.data?.find((item) => item.id === unitId)
  const selectedLesson = lessonsQuery.data?.find((item) => item.id === lessonId)

  const updateCurriculumItem = useMutation({
    mutationFn: async ({ target, form }: { target: CurriculumEditTarget; form: FormData }) => {
      const title = form.get('title')?.toString() ?? ''
      const description = form.get('description')?.toString() ?? ''
      if (target.type === 'module') {
        const { error } = await api.PATCH('/api/v1/course-modules/{id}/', {
          params: { path: { id: target.item.id } },
          body: { title, description },
        })
        assertSuccess(error)
      } else if (target.type === 'topic') {
        const { error } = await api.PATCH('/api/v1/course-units/{id}/', {
          params: { path: { id: target.item.id } },
          body: { title, description },
        })
        assertSuccess(error)
      } else if (target.type === 'lesson') {
        const { error } = await api.PATCH('/api/v1/lessons/{id}/', {
          params: { path: { id: target.item.id } },
          body: {
            title,
            description,
            video_url: form.get('video_url')?.toString() ?? '',
            duration_minutes: Number(form.get('duration_minutes')) || 0,
          },
        })
        assertSuccess(error)
      } else if (target.item.kind === 'LINK') {
        const { error } = await api.PATCH('/api/v1/materials/{id}/', {
          params: { path: { id: target.item.id } },
          body: { title, url: form.get('url')?.toString() ?? '' },
        })
        assertSuccess(error)
      } else {
        const { error } = await api.PATCH('/api/v1/materials/{id}/', {
          params: { path: { id: target.item.id } },
          body: { title },
        })
        assertSuccess(error)
      }
    },
    onSuccess: async () => {
      setEditingCurriculumItem(null)
      setFormError('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['course-modules', courseId] }),
        queryClient.invalidateQueries({ queryKey: ['course-units', moduleId] }),
        queryClient.invalidateQueries({ queryKey: ['lessons', unitId] }),
        queryClient.invalidateQueries({ queryKey: ['materials', lessonId] }),
      ])
    },
    onError: (error) => setFormError(error.message),
  })

  const setCurriculumVisibility = useMutation({
    mutationFn: async (target: CurriculumItemTarget & { is_visible: boolean }) => {
      if (target.type === 'module') {
        const { error } = await api.PATCH('/api/v1/course-modules/{id}/', {
          params: { path: { id: target.id } },
          body: { is_visible: target.is_visible },
        })
        assertSuccess(error)
      } else if (target.type === 'topic') {
        const { error } = await api.PATCH('/api/v1/course-units/{id}/', {
          params: { path: { id: target.id } },
          body: { is_visible: target.is_visible },
        })
        assertSuccess(error)
      } else if (target.type === 'lesson') {
        const { error } = await api.PATCH('/api/v1/lessons/{id}/', {
          params: { path: { id: target.id } },
          body: { is_visible: target.is_visible },
        })
        assertSuccess(error)
      } else {
        const { error } = await api.PATCH('/api/v1/materials/{id}/', {
          params: { path: { id: target.id } },
          body: { is_visible: target.is_visible },
        })
        assertSuccess(error)
      }
    },
    onSuccess: async () => {
      setFormError('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['course-modules', courseId] }),
        queryClient.invalidateQueries({ queryKey: ['course-units', moduleId] }),
        queryClient.invalidateQueries({ queryKey: ['lessons', unitId] }),
        queryClient.invalidateQueries({ queryKey: ['materials', lessonId] }),
      ])
    },
    onError: (error) => setFormError(error.message),
  })

  const archiveCurriculumItem = useMutation({
    mutationFn: async (target: CurriculumItemTarget) => {
      if (target.type === 'module') {
        const { error } = await api.DELETE('/api/v1/course-modules/{id}/', {
          params: { path: { id: target.id } },
        })
        assertSuccess(error)
      } else if (target.type === 'topic') {
        const { error } = await api.DELETE('/api/v1/course-units/{id}/', {
          params: { path: { id: target.id } },
        })
        assertSuccess(error)
      } else if (target.type === 'lesson') {
        const { error } = await api.DELETE('/api/v1/lessons/{id}/', {
          params: { path: { id: target.id } },
        })
        assertSuccess(error)
      } else {
        const { error } = await api.DELETE('/api/v1/materials/{id}/', {
          params: { path: { id: target.id } },
        })
        assertSuccess(error)
      }
    },
    onSuccess: async () => {
      setCurriculumArchiveTarget(null)
      setFormError('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['course-modules', courseId] }),
        queryClient.invalidateQueries({ queryKey: ['course-units', moduleId] }),
        queryClient.invalidateQueries({ queryKey: ['lessons', unitId] }),
        queryClient.invalidateQueries({ queryKey: ['materials', lessonId] }),
      ])
    },
    onError: (error) => setFormError(error.message),
  })

  const reorderCurriculumItems = useMutation({
    mutationFn: async (target: { type: 'module' | 'topic' | 'lesson'; parentId: string; ids: string[] }) => {
      const body = { parent_id: target.parentId, ids: target.ids }
      if (target.type === 'module') {
        const { error } = await api.POST('/api/v1/course-modules/reorder/', { body })
        assertSuccess(error)
      } else if (target.type === 'topic') {
        const { error } = await api.POST('/api/v1/course-units/reorder/', { body })
        assertSuccess(error)
      } else {
        const { error } = await api.POST('/api/v1/lessons/reorder/', { body })
        assertSuccess(error)
      }
    },
    onSuccess: async (_data, target) => {
      await queryClient.invalidateQueries({
        queryKey: target.type === 'module'
          ? ['course-modules', courseId]
          : target.type === 'topic'
            ? ['course-units', moduleId]
            : ['lessons', unitId],
      })
    },
    onError: (error) => setFormError(error.message),
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
      setModuleId('')
      setUnitId('')
      setLessonId('')
      await queryClient.invalidateQueries({ queryKey: ['courses'] })
    },
    onError: (error) => setFormError(error.message),
  })

  const updateCourse = useMutation({
    mutationFn: async (form: FormData) => {
      if (!selectedCourse) throw new Error('Select a course to edit.')
      const { data, error } = await api.PATCH('/api/v1/courses/{slug}/', {
        params: { path: { slug: selectedCourse.slug } },
        body: {
          version: selectedCourse.version,
          department: form.get('department')?.toString() || selectedCourse.department,
          title: form.get('title')?.toString() ?? selectedCourse.title,
          code: form.get('code')?.toString() || selectedCourse.code,
          summary: form.get('summary')?.toString() ?? selectedCourse.summary,
          description: form.get('description')?.toString() ?? selectedCourse.description,
        },
      })
      assertSuccess(error)
      if (!data) throw new Error('The course could not be updated.')
      return data
    },
    onSuccess: async () => {
      setFormError('')
      setCourseDetailsOpen(false)
      await queryClient.invalidateQueries({ queryKey: ['courses'] })
    },
    onError: (error) => setFormError(error.message),
  })

  const assignCourseTeacher = useMutation({
    mutationFn: async (form: FormData) => {
      const { error } = await api.POST('/api/v1/course-assignments/', {
        body: {
          course: courseId,
          teacher: form.get('teacher')?.toString() ?? '',
          can_edit_content: form.get('can_edit_content') === 'on',
        },
      })
      assertSuccess(error)
    },
    onSuccess: async () => {
      setFormError('')
      await queryClient.invalidateQueries({ queryKey: ['course-assignments', courseId] })
      await queryClient.invalidateQueries({ queryKey: ['course-assignments', 'teacher'] })
    },
    onError: (error) => setFormError(error.message),
  })

  const unassignCourseTeacher = useMutation({
    mutationFn: async (assignmentId: string) => {
      const { error } = await api.DELETE('/api/v1/course-assignments/{id}/', {
        params: { path: { id: assignmentId } },
      })
      assertSuccess(error)
    },
    onSuccess: async () => {
      setFormError('')
      await queryClient.invalidateQueries({ queryKey: ['course-assignments', courseId] })
      await queryClient.invalidateQueries({ queryKey: ['course-assignments', 'teacher'] })
    },
    onError: (error) => setFormError(error.message),
  })

  const publishCourse = useMutation({
    mutationFn: async () => {
      if (!selectedCourse) throw new Error('Select a course to publish.')
      const { error } = await api.POST('/api/v1/courses/{slug}/publish/', {
        params: { path: { slug: selectedCourse.slug } },
        body: { version: selectedCourse.version },
      })
      assertSuccess(error)
    },
    onSuccess: async () => {
      setFormError('')
      await queryClient.invalidateQueries({ queryKey: ['courses'] })
    },
    onError: (error) => setFormError(error.message),
  })

  const unpublishCourse = useMutation({
    mutationFn: async () => {
      if (!selectedCourse) throw new Error('Select a course to unpublish.')
      const { error } = await api.POST('/api/v1/courses/{slug}/unpublish/', {
        params: { path: { slug: selectedCourse.slug } },
        body: { version: selectedCourse.version },
      })
      assertSuccess(error)
    },
    onSuccess: async () => {
      setFormError('')
      await queryClient.invalidateQueries({ queryKey: ['courses'] })
    },
    onError: (error) => setFormError(error.message),
  })

  const duplicateCourse = useMutation({
    mutationFn: async () => {
      if (!selectedCourse) throw new Error('Select a course to duplicate.')
      const { data, error } = await api.POST('/api/v1/courses/{slug}/duplicate/', {
        params: { path: { slug: selectedCourse.slug } },
        body: { version: selectedCourse.version },
      })
      assertSuccess(error)
      if (!data) throw new Error('The course could not be duplicated.')
      return data
    },
    onSuccess: async (course) => {
      setFormError('')
      setCourseId(course.id)
      setModuleId('')
      setUnitId('')
      setLessonId('')
      await queryClient.invalidateQueries({ queryKey: ['courses'] })
    },
    onError: (error) => setFormError(error.message),
  })

  const archiveCourse = useMutation({
    mutationFn: async () => {
      if (!selectedCourse) throw new Error('Select a course to archive.')
      const { error } = await api.POST('/api/v1/courses/{slug}/archive/', {
        params: { path: { slug: selectedCourse.slug } },
        body: { version: selectedCourse.version },
      })
      assertSuccess(error)
    },
    onSuccess: async () => {
      setFormError('')
      setArchiveDialogOpen(false)
      setCourseId('')
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
          position: Math.max(0, ...(modulesQuery.data ?? []).map((item) => item.position)) + 1,
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
          position: Math.max(0, ...(unitsQuery.data ?? []).map((item) => item.position)) + 1,
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
          position: Math.max(0, ...(lessonsQuery.data ?? []).map((item) => item.position)) + 1,
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
      const title = form.get('title')?.toString() ?? ''
      let fileId: string | undefined
      const selectedFile = form.get('file')
      const kind = form.get('kind') === 'FILE' ? 'FILE' : 'LINK'
      if (kind === 'FILE') {
        if (!(selectedFile instanceof File) || selectedFile.size === 0) {
          throw new Error('Choose a file to upload.')
        }
        const { data: started, error: startError } = await api.POST('/api/v1/files/uploads/', {
          body: {
            purpose: 'material',
            filename: selectedFile.name,
            content_type: selectedFile.type || 'application/octet-stream',
            size: selectedFile.size,
          },
        })
        assertSuccess(startError)
        if (!started) throw new Error('The server returned no upload details.')

        const uploadResponse = await fetch(started.upload_url, {
          method: 'PUT',
          headers: started.headers,
          body: selectedFile,
        })
        if (!uploadResponse.ok) {
          throw new Error(`The file upload failed (${uploadResponse.status}).`)
        }

        const { data: completed, error: completeError } = await api.POST('/api/v1/files/{id}/complete/', {
          params: { path: { id: started.file.id } },
        })
        assertSuccess(completeError)
        if (!completed) throw new Error('The uploaded file could not be verified.')
        fileId = completed.id
      }

      const { error } = await api.POST('/api/v1/materials/', {
        body: kind === 'FILE'
          ? { lesson: lessonId, title, kind, file: fileId }
          : { lesson: lessonId, title, kind, url: form.get('url')?.toString() ?? '' },
      })
      assertSuccess(error)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['materials', lessonId] })
    },
    onError: (error) => setFormError(error.message),
  })

  const reorderSelected = (
    type: 'module' | 'topic' | 'lesson',
    parentId: string,
    items: { id: string }[] | undefined,
    selectedId: string,
    offset: -1 | 1,
  ) => {
    if (!items) return
    const ids = items.map((item) => item.id)
    const index = ids.indexOf(selectedId)
    const destination = index + offset
    if (index < 0 || destination < 0 || destination >= ids.length) return
    ;[ids[index], ids[destination]] = [ids[destination], ids[index]]
    reorderCurriculumItems.mutate({ type, parentId, ids })
  }

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
      {courseAssignmentsQuery.isError && <p role="alert" className="text-danger-fg">Course teachers could not be loaded.</p>}
      {teacherAssignmentsQuery.isError && <p role="alert" className="text-danger-fg">Your course assignments could not be loaded.</p>}
      {teachersQuery.isError && <p role="alert" className="text-danger-fg">Teachers could not be loaded.</p>}

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
          {coursesQuery.data?.filter((course) => course.is_active && (!isTeacherOnly || teacherAssignmentsQuery.data?.some((assignment) => assignment.course === course.id && assignment.can_edit_content))).map((course) => (
            <option key={course.id} value={course.id}>{course.code} — {course.title}</option>
          ))}
        </select>
      </label>

      {selectedCourse && (
        <div className="space-y-3">
          <Button
            variant="secondary"
            onClick={() => setPreviewOpen((open) => !open)}
            type="button"
          >
            {t(previewOpen ? 'Close student preview' : 'Preview as student')}
          </Button>
          {previewOpen && <StudentPreview courseId={courseId} />}
        </div>
      )}

      {selectedCourse && canPublishCourse && (
        <div className="flex flex-wrap gap-2">
          {selectedCourse.status === 'DRAFT' ? (
            <Button
              variant="secondary"
              size="sm"
              loading={publishCourse.isPending}
              onClick={() => {
                setFormError('')
                publishCourse.mutate()
              }}
              type="button"
            >
              {t(publishCourse.isPending ? 'Publishing…' : 'Publish selected course')}
            </Button>
          ) : (
            <Button
              variant="secondary"
              size="sm"
              loading={unpublishCourse.isPending}
              onClick={() => {
                setFormError('')
                unpublishCourse.mutate()
              }}
              type="button"
            >
              {t(unpublishCourse.isPending ? 'Unpublishing…' : 'Unpublish selected course')}
            </Button>
          )}
          <Button
            variant="secondary"
            size="sm"
            loading={duplicateCourse.isPending}
            onClick={() => {
              setFormError('')
              duplicateCourse.mutate()
            }}
            type="button"
          >
          {t(duplicateCourse.isPending ? 'Duplicating…' : 'Duplicate selected course')}
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={() => setArchiveDialogOpen(true)}
            type="button"
          >
            {t('Archive selected course')}
          </Button>
        </div>
      )}

      {selectedCourse && canPublishCourse && (
        <Dialog open={archiveDialogOpen} onOpenChange={setArchiveDialogOpen}>
          <DialogContent>
            <DialogTitle>{t('Archive this course?')}</DialogTitle>
            <DialogDescription>
              {t('The course will be removed from active course management. Existing class and enrollment records are retained. This action cannot be undone from this screen.')}
            </DialogDescription>
            {archiveCourse.error && <p className="mt-4 text-danger-fg" role="alert">{archiveCourse.error.message}</p>}
            <div className="mt-6 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setArchiveDialogOpen(false)} type="button">
                {t('Cancel')}
              </Button>
              <Button
                variant="danger"
                loading={archiveCourse.isPending}
                onClick={() => {
                  setFormError('')
                  archiveCourse.mutate()
                }}
                type="button"
              >
                {t('Archive course')}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      )}

      {selectedCourse && canManageCourses && (
        <>
          <Button variant="secondary" onClick={() => setCourseDetailsOpen(true)} type="button">
            {t('Edit course details')}
          </Button>
          <Drawer
            open={courseDetailsOpen}
            onOpenChange={setCourseDetailsOpen}
            title={t('Edit course details')}
            description={t('Update course information. Identity and scope fields lock after classes are created.')}
          >
            <form
              key={selectedCourse.id}
              className={formClass}
              onSubmit={(event) => {
                event.preventDefault()
                setFormError('')
                updateCourse.mutate(new FormData(event.currentTarget))
              }}
            >
              {updateCourse.error && <p className="text-danger-fg" role="alert">{updateCourse.error.message}</p>}
              <select
                className={fieldClass}
                name="department"
                required
                defaultValue={selectedCourse.department}
                disabled={selectedCourse.has_classes || Boolean(selectedCourse.program)}
              >
                {departmentsQuery.data?.filter((department) => department.unit.id === selectedCourse.unit).map((department) => (
                  <option key={department.id} value={department.id}>{department.name}</option>
                ))}
              </select>
              <input className={fieldClass} name="title" placeholder="Course title" required defaultValue={selectedCourse.title} />
              <input
                className={fieldClass}
                name="code"
                placeholder="Course code"
                required
                defaultValue={selectedCourse.code}
                readOnly={selectedCourse.has_classes}
              />
              <input className={fieldClass} name="summary" placeholder="Short summary" defaultValue={selectedCourse.summary} />
              <textarea className={fieldClass} name="description" placeholder="Course description" rows={4} defaultValue={selectedCourse.description} />
              {selectedCourse.has_classes && (
                <p className="text-sm text-subtle">{t('Department and course code are locked because classes already exist.')}</p>
              )}
              {!selectedCourse.has_classes && selectedCourse.program && (
                <p className="text-sm text-subtle">{t('Department cannot change while this course is assigned to a program.')}</p>
              )}
              <Button loading={updateCourse.isPending} type="submit">
                {t(updateCourse.isPending ? 'Saving…' : 'Save course details')}
              </Button>
            </form>
          </Drawer>
        </>
      )}

      {canManageCourses && (
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
          {canManageCourses && (
            <section className={formClass}>
              <h2 className="text-xl font-semibold">Course teachers</h2>
              <ul className="space-y-2">
                {(courseAssignmentsQuery.data ?? []).map((assignment) => (
                  <li className="flex flex-wrap items-center justify-between gap-2 rounded border border-line p-3" key={assignment.id}>
                    <span>{assignment.teacher_name || assignment.teacher_email} · {assignment.can_edit_content ? 'Can edit course content' : 'Teaching assignment only'}</span>
                    <button
                      className="text-sm underline disabled:opacity-50"
                      disabled={unassignCourseTeacher.isPending}
                      onClick={() => unassignCourseTeacher.mutate(assignment.id)}
                      type="button"
                    >
                      Unassign
                    </button>
                  </li>
                ))}
                {courseAssignmentsQuery.data?.length === 0 && <li className="text-sm text-subtle">No teachers assigned yet.</li>}
              </ul>
              <form
                className="grid gap-3 sm:grid-cols-[1fr_auto_auto]"
                onSubmit={(event) => {
                  event.preventDefault()
                  setFormError('')
                  assignCourseTeacher.mutate(new FormData(event.currentTarget))
                  event.currentTarget.reset()
                }}
              >
                <select className={fieldClass} name="teacher" required defaultValue="">
                  <option value="" disabled>Select a unit teacher</option>
                  {teachersQuery.data?.filter((teacher) => {
                    const course = coursesQuery.data?.find((item) => item.id === courseId)
                    return course && teacher.assignments.some(
                      (assignment) => assignment.role === 'TEACHER' && assignment.unit?.id === course.unit,
                    )
                  }).map((teacher) => (
                    <option key={teacher.id} value={teacher.id}>{teacher.display_name || teacher.email}</option>
                  ))}
                </select>
                <label className="flex items-center gap-2 text-sm">
                  <input name="can_edit_content" type="checkbox" />
                  Can edit course content
                </label>
                <button className="rounded bg-primary px-4 py-2 font-medium text-primary-fg disabled:opacity-60" disabled={assignCourseTeacher.isPending}>
                  {assignCourseTeacher.isPending ? 'Assigning…' : 'Assign teacher'}
                </button>
              </form>
            </section>
          )}

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
              {modulesQuery.data?.map((module) => (
                <option key={module.id} value={module.id}>
                  {module.title}{!module.is_active ? ' (archived)' : !module.is_visible ? ' (hidden)' : ''}
                </option>
              ))}
            </select>
          </label>
          {selectedModule && (
            <div className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                onClick={() => setEditingCurriculumItem({ type: 'module', item: selectedModule })}
                type="button"
              >
                {t('Edit module')}
              </Button>
              <Button
                variant="secondary"
                loading={setCurriculumVisibility.isPending}
                onClick={() => setCurriculumVisibility.mutate({
                  type: 'module',
                  id: selectedModule.id,
                  is_visible: !selectedModule.is_visible,
                })}
                type="button"
              >
                {t(selectedModule.is_visible ? 'Hide module' : 'Show module')}
              </Button>
              <Button
                variant="danger"
                disabled={!selectedModule.is_active}
                onClick={() => setCurriculumArchiveTarget({ type: 'module', id: selectedModule.id })}
                type="button"
              >
                {t('Archive module')}
              </Button>
              <Button
                variant="secondary"
                disabled={modulesQuery.data?.[0]?.id === selectedModule.id || reorderCurriculumItems.isPending}
                onClick={() => reorderSelected('module', courseId, modulesQuery.data, selectedModule.id, -1)}
                type="button"
              >
                {t('Move earlier')}
              </Button>
              <Button
                variant="secondary"
                disabled={modulesQuery.data?.at(-1)?.id === selectedModule.id || reorderCurriculumItems.isPending}
                onClick={() => reorderSelected('module', courseId, modulesQuery.data, selectedModule.id, 1)}
                type="button"
              >
                {t('Move later')}
              </Button>
            </div>
          )}
        </div>
      )}

      {moduleId && (
        <div className="space-y-5">
          <form className={formClass} onSubmit={(event) => {
            event.preventDefault()
            setFormError('')
            createUnit.mutate(new FormData(event.currentTarget))
          }}>
            <h2 className="text-xl font-semibold">Add a topic</h2>
            <input className={fieldClass} name="title" placeholder="Topic title" required />
            <textarea className={fieldClass} name="description" placeholder="Description (optional)" rows={2} />
            <button className="rounded bg-primary px-4 py-2 font-medium text-primary-fg disabled:opacity-60" disabled={createUnit.isPending}>
              Add topic
            </button>
          </form>

          <label className="block">
            <span className="mb-1 block font-medium">Topic</span>
            <select className={fieldClass} value={unitId} onChange={(event) => {
              setUnitId(event.target.value)
              setLessonId('')
            }}>
              <option value="">Select a topic</option>
              {unitsQuery.data?.map((unit) => (
                <option key={unit.id} value={unit.id}>
                  {unit.title}{!unit.is_active ? ' (archived)' : !unit.is_visible ? ' (hidden)' : ''}
                </option>
              ))}
            </select>
          </label>
          {selectedTopic && (
            <div className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                onClick={() => setEditingCurriculumItem({ type: 'topic', item: selectedTopic })}
                type="button"
              >
                {t('Edit topic')}
              </Button>
              <Button
                variant="secondary"
                loading={setCurriculumVisibility.isPending}
                onClick={() => setCurriculumVisibility.mutate({
                  type: 'topic',
                  id: selectedTopic.id,
                  is_visible: !selectedTopic.is_visible,
                })}
                type="button"
              >
                {t(selectedTopic.is_visible ? 'Hide topic' : 'Show topic')}
              </Button>
              <Button
                variant="danger"
                disabled={!selectedTopic.is_active}
                onClick={() => setCurriculumArchiveTarget({ type: 'topic', id: selectedTopic.id })}
                type="button"
              >
                {t('Archive topic')}
              </Button>
              <Button
                variant="secondary"
                disabled={unitsQuery.data?.[0]?.id === selectedTopic.id || reorderCurriculumItems.isPending}
                onClick={() => reorderSelected('topic', moduleId, unitsQuery.data, selectedTopic.id, -1)}
                type="button"
              >
                {t('Move earlier')}
              </Button>
              <Button
                variant="secondary"
                disabled={unitsQuery.data?.[unitsQuery.data.length - 1]?.id === selectedTopic.id || reorderCurriculumItems.isPending}
                onClick={() => reorderSelected('topic', moduleId, unitsQuery.data, selectedTopic.id, 1)}
                type="button"
              >
                {t('Move later')}
              </Button>
            </div>
          )}
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
            <p className="text-sm text-subtle">
              {t('Use an HTTPS YouTube or Vimeo link.')}
            </p>
            <input className={fieldClass} name="duration_minutes" type="number" min="0" placeholder="Duration in minutes" />
            <button className="rounded bg-primary px-4 py-2 font-medium text-primary-fg disabled:opacity-60" disabled={createLesson.isPending}>
              Add lesson
            </button>
          </form>

          <label className="block">
            <span className="mb-1 block font-medium">Lesson</span>
            <select className={fieldClass} value={lessonId} onChange={(event) => setLessonId(event.target.value)}>
              <option value="">Select a lesson</option>
              {lessonsQuery.data?.map((lesson) => (
                <option key={lesson.id} value={lesson.id}>
                  {lesson.title}{!lesson.is_active ? ' (archived)' : !lesson.is_visible ? ' (hidden)' : ''}
                </option>
              ))}
            </select>
          </label>
          {selectedLesson && (
            <div className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                onClick={() => setEditingCurriculumItem({ type: 'lesson', item: selectedLesson })}
                type="button"
              >
                {t('Edit lesson')}
              </Button>
              <Button
                variant="secondary"
                loading={setCurriculumVisibility.isPending}
                onClick={() => setCurriculumVisibility.mutate({
                  type: 'lesson',
                  id: selectedLesson.id,
                  is_visible: !selectedLesson.is_visible,
                })}
                type="button"
              >
                {t(selectedLesson.is_visible ? 'Hide lesson' : 'Show lesson')}
              </Button>
              <Button
                variant="danger"
                disabled={!selectedLesson.is_active}
                onClick={() => setCurriculumArchiveTarget({ type: 'lesson', id: selectedLesson.id })}
                type="button"
              >
                {t('Archive lesson')}
              </Button>
              <Button
                variant="secondary"
                disabled={lessonsQuery.data?.[0]?.id === selectedLesson.id || reorderCurriculumItems.isPending}
                onClick={() => reorderSelected('lesson', unitId, lessonsQuery.data, selectedLesson.id, -1)}
                type="button"
              >
                {t('Move earlier')}
              </Button>
              <Button
                variant="secondary"
                disabled={lessonsQuery.data?.[lessonsQuery.data.length - 1]?.id === selectedLesson.id || reorderCurriculumItems.isPending}
                onClick={() => reorderSelected('lesson', unitId, lessonsQuery.data, selectedLesson.id, 1)}
                type="button"
              >
                {t('Move later')}
              </Button>
            </div>
          )}
        </div>
      )}

      {lessonId && (
        <>
          {materialsQuery.isError && <p role="alert" className="text-danger-fg">{t('Lesson materials could not be loaded.')}</p>}
          <ul className="space-y-2">
            {(materialsQuery.data ?? []).map((material) => (
              <li className="flex flex-wrap items-center justify-between gap-2 rounded border border-line p-3" key={material.id}>
                <span>
                  {material.title}
                  {!material.is_active ? ` · ${t('Archived')}` : !material.is_visible ? ` · ${t('Hidden')}` : ''}
                </span>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setEditingCurriculumItem({ type: 'material', item: material })}
                    type="button"
                  >
                    {t('Edit')}
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={setCurriculumVisibility.isPending}
                    onClick={() => setCurriculumVisibility.mutate({
                      type: 'material',
                      id: material.id,
                      is_visible: !material.is_visible,
                    })}
                    type="button"
                  >
                    {t(material.is_visible ? 'Hide' : 'Show')}
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    disabled={!material.is_active}
                    onClick={() => setCurriculumArchiveTarget({ type: 'material', id: material.id })}
                    type="button"
                  >
                    {t('Archive')}
                  </Button>
                </div>
              </li>
            ))}
            {materialsQuery.data?.length === 0 && (
              <li className="text-sm text-subtle">{t('No materials have been added to this lesson.')}</li>
            )}
          </ul>

          <form className={formClass} onSubmit={(event) => {
            event.preventDefault()
            setFormError('')
            createMaterial.mutate(new FormData(event.currentTarget))
          }}>
            <h2 className="text-xl font-semibold">{t('Add lesson material')}</h2>
            <input className={fieldClass} name="title" placeholder={t('Material title')} required />
            <label>
              <span className="mb-1 block font-medium">{t('Material type')}</span>
              <select
                className={fieldClass}
                name="kind"
                value={materialKind}
                onChange={(event) => setMaterialKind(event.target.value as 'LINK' | 'FILE')}
              >
                <option value="LINK">{t('External link')}</option>
                <option value="FILE">{t('Uploaded file')}</option>
              </select>
            </label>
            {materialKind === 'LINK' ? (
              <input className={fieldClass} name="url" type="url" placeholder="https://…" required />
            ) : (
              <input
                className={fieldClass}
                name="file"
                type="file"
                accept=".pdf,.docx,.pptx,.xlsx,.jpg,.jpeg,.png,.webp,.zip"
                required
              />
            )}
            <Button loading={createMaterial.isPending} type="submit">
              {t(createMaterial.isPending ? 'Adding material…' : 'Add material')}
            </Button>
          </form>
        </>
      )}

      {editingCurriculumItem && (
        <Drawer
          open
          onOpenChange={(open) => {
            if (!open) setEditingCurriculumItem(null)
          }}
          title={t(`Edit ${editingCurriculumItem.type}`)}
          description={t('Changes affect the course curriculum, not existing class records.')}
        >
          <form
            key={`${editingCurriculumItem.type}-${editingCurriculumItem.item.id}`}
            className={formClass}
            onSubmit={(event) => {
              event.preventDefault()
              setFormError('')
              updateCurriculumItem.mutate({
                target: editingCurriculumItem,
                form: new FormData(event.currentTarget),
              })
            }}
          >
            {updateCurriculumItem.error && (
              <p role="alert" className="text-danger-fg">{updateCurriculumItem.error.message}</p>
            )}
            <label>
              <span className="mb-1 block font-medium">{t('Title')}</span>
              <input
                className={fieldClass}
                name="title"
                required
                defaultValue={editingCurriculumItem.item.title}
              />
            </label>
            {editingCurriculumItem.type !== 'material' && (
              <label>
                <span className="mb-1 block font-medium">{t('Description')}</span>
                <textarea
                  className={fieldClass}
                  name="description"
                  rows={3}
                  defaultValue={editingCurriculumItem.item.description}
                />
              </label>
            )}
            {editingCurriculumItem.type === 'lesson' && (
              <>
                <label>
                  <span className="mb-1 block font-medium">{t('Video URL')}</span>
                  <p className="mb-1 text-sm text-subtle">
                    {t('Use an HTTPS YouTube or Vimeo link.')}
                  </p>
                  <input
                    className={fieldClass}
                    name="video_url"
                    type="url"
                    defaultValue={editingCurriculumItem.item.video_url}
                  />
                </label>
                <label>
                  <span className="mb-1 block font-medium">{t('Duration in minutes')}</span>
                  <input
                    className={fieldClass}
                    name="duration_minutes"
                    type="number"
                    min="0"
                    defaultValue={editingCurriculumItem.item.duration_minutes}
                  />
                </label>
              </>
            )}
            {editingCurriculumItem.type === 'material' && editingCurriculumItem.item.kind === 'LINK' && (
              <label>
                <span className="mb-1 block font-medium">{t('External URL')}</span>
                <input
                  className={fieldClass}
                  name="url"
                  type="url"
                  required
                  defaultValue={editingCurriculumItem.item.url}
                />
              </label>
            )}
            {editingCurriculumItem.type === 'material' && editingCurriculumItem.item.kind === 'FILE' && (
              <p className="text-sm text-subtle">{t('Uploaded files cannot be replaced from this editor.')}</p>
            )}
            <Button loading={updateCurriculumItem.isPending} type="submit">
              {t(updateCurriculumItem.isPending ? 'Saving…' : 'Save changes')}
            </Button>
          </form>
        </Drawer>
      )}

      {curriculumArchiveTarget && (
        <Dialog
          open
          onOpenChange={(open) => {
            if (!open) setCurriculumArchiveTarget(null)
          }}
        >
          <DialogContent>
            <DialogTitle>{t(`Archive this ${curriculumArchiveTarget.type}?`)}</DialogTitle>
            <DialogDescription>
              {t('The item and its history will be retained, but it will no longer appear in the student course view.')}
            </DialogDescription>
            {archiveCurriculumItem.error && (
              <p className="mt-4 text-danger-fg" role="alert">{archiveCurriculumItem.error.message}</p>
            )}
            <div className="mt-6 flex justify-end gap-2">
              <Button
                variant="secondary"
                onClick={() => setCurriculumArchiveTarget(null)}
                type="button"
              >
                {t('Cancel')}
              </Button>
              <Button
                variant="danger"
                loading={archiveCurriculumItem.isPending}
                onClick={() => archiveCurriculumItem.mutate(curriculumArchiveTarget)}
                type="button"
              >
                {t('Archive item')}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </section>
  )
}
