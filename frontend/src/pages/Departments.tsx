import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Pencil, Plus, Search } from 'lucide-react'
import { api } from '../api/client'
import type { components } from '../api/schema'
import { useMe } from '../features/me/useMe'
import { hasRole } from '../features/me/roles'
import { useUnit } from '../features/units/useUnit'
import { apiErrorMessage } from '../lib/apiError'
import { PageHeader } from '../app/PageHeader'
import {
  Badge,
  Button,
  DataTable,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  Drawer,
  EmptyState,
  FormField,
  Input,
  useToast,
  type DataTableAction,
  type DataTableColumn,
} from '../components/ui'

type Department = components['schemas']['Department']

interface DepartmentFieldErrors {
  name?: string
  code?: string
  unit?: string
}

interface DepartmentRequestError extends Error {
  fields?: Record<string, unknown>
}

function departmentRequestError(error: unknown, fallback: string): DepartmentRequestError {
  const fields = typeof error === 'object' && error !== null && 'fields' in error
    && typeof error.fields === 'object' && error.fields !== null
    ? error.fields as Record<string, unknown>
    : undefined
  return Object.assign(new Error(apiErrorMessage(error, fallback)), { fields })
}

function fieldMessage(fields: Record<string, unknown> | undefined, field: keyof DepartmentFieldErrors) {
  const value = fields?.[field]
  if (typeof value === 'string') return value
  if (Array.isArray(value) && typeof value[0] === 'string') return value[0]
  return undefined
}

function statusFor(department: Department) {
  if (department.archived_at) return { label: 'Archived', variant: 'neutral' as const }
  if (!department.is_active) return { label: 'Inactive', variant: 'warning' as const }
  return { label: 'Active', variant: 'success' as const }
}

export function Departments() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { data: me } = useMe()
  const unit = useUnit()
  const [search, setSearch] = useState('')
  const [pageState, setPageState] = useState({ page: 1, unitId: unit.unitId })
  const page = pageState.unitId === unit.unitId ? pageState.page : 1
  const setPage = (nextPage: number) => setPageState({ page: nextPage, unitId: unit.unitId })
  const [showArchived, setShowArchived] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editing, setEditing] = useState<Department | null>(null)
  const [archiveTarget, setArchiveTarget] = useState<Department | null>(null)
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [unitId, setUnitId] = useState('')
  const [codeChanged, setCodeChanged] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<DepartmentFieldErrors>({})
  const [formError, setFormError] = useState('')
  const canManage = hasRole(me, 'SUPER_ADMIN', 'ADMIN')

  const departmentsQuery = useQuery({
    queryKey: ['departments', search, page, showArchived, unit.unitId],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/departments/', {
        params: {
          query: {
            page,
            page_size: 25,
            search: search || undefined,
            show_archived: showArchived || undefined,
            unit: unit.unitId,
          },
        },
      })
      if (error) throw new Error(apiErrorMessage(error, 'Unable to load departments.'))
      if (!data) throw new Error('The server returned no department list.')
      return data
    },
  })

  const saveDepartment = useMutation({
    mutationFn: async (values: { id?: string; name: string; code: string; codeChanged: boolean; unitId: string }) => {
      if (values.id) {
        const body: components['schemas']['PatchedDepartmentWriteRequest'] = {
          name: values.name,
          unit: values.unitId,
          ...(values.codeChanged ? { code: values.code } : {}),
        }
        const { data, error } = await api.PATCH('/api/v1/departments/{id}/', {
          params: { path: { id: values.id } },
          body,
        })
        if (error) throw departmentRequestError(error, 'Unable to update department.')
        if (!data) throw new Error('The server returned no updated department.')
        return data
      }

      const { data, error } = await api.POST('/api/v1/departments/', {
        body: { campus: null, unit: values.unitId, name: values.name, code: values.code, is_active: true },
      })
      if (error) throw departmentRequestError(error, 'Unable to create department.')
      if (!data) throw new Error('The server returned no new department.')
      return data
    },
    onSuccess: (_department, values) => {
      setDrawerOpen(false)
      setEditing(null)
      setFieldErrors({})
      setFormError('')
      setPage(1)
      toast({
        title: values.id ? 'Department updated' : 'Department created',
        variant: 'success',
      })
      void queryClient.invalidateQueries({ queryKey: ['departments'] })
    },
    onError: (error: DepartmentRequestError) => {
      const fields = error.fields
      setFieldErrors({
        name: fieldMessage(fields, 'name'),
        code: fieldMessage(fields, 'code'),
        unit: fieldMessage(fields, 'unit'),
      })
      setFormError(error.message)
      toast({ title: 'Department could not be saved', description: error.message, variant: 'error' })
    },
  })

  const archiveDepartment = useMutation({
    mutationFn: async (department: Department) => {
      const { error } = await api.DELETE('/api/v1/departments/{id}/', {
        params: { path: { id: department.id } },
      })
      if (error) throw new Error(apiErrorMessage(error, 'Unable to archive department.'))
      return department
    },
    onSuccess: (department) => {
      setArchiveTarget(null)
      toast({ title: 'Department archived', description: department.name, variant: 'success' })
      void queryClient.invalidateQueries({ queryKey: ['departments'] })
    },
    onError: (error: Error) => {
      toast({ title: 'Department could not be archived', description: error.message, variant: 'error' })
    },
  })

  function openCreateDrawer() {
    setEditing(null)
    setName('')
    setCode('')
    setUnitId(unit.unitId ?? unit.units[0]?.id ?? '')
    setCodeChanged(false)
    setFieldErrors({})
    setFormError('')
    setDrawerOpen(true)
  }

  function openEditDrawer(department: Department) {
    setEditing(department)
    setName(department.name)
    setCode(department.code)
    setUnitId(department.unit?.id ?? '')
    setCodeChanged(false)
    setFieldErrors({})
    setFormError('')
    setDrawerOpen(true)
  }

  function submitDepartment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const errors: DepartmentFieldErrors = {}
    const normalizedName = name.trim()
    const normalizedCode = code.trim().toUpperCase()
    if (!normalizedName) errors.name = 'Enter a department name.'
    if (!unitId) errors.unit = 'Select a business unit.'
    if (normalizedName.length > 160) errors.name = 'Use 160 characters or fewer.'
    if ((!editing || codeChanged) && !/^[A-Z0-9]{2,8}$/.test(normalizedCode)) {
      errors.code = 'Use 2–8 uppercase letters or digits.'
    }
    setFieldErrors(errors)
    setFormError('')
    if (Object.keys(errors).length > 0) return
    saveDepartment.mutate({
      id: editing?.id,
      name: normalizedName,
      code: normalizedCode,
      codeChanged,
      unitId,
    })
  }

  const columns: DataTableColumn<Department>[] = [
    { id: 'name', header: 'Name', accessor: 'name' },
    {
      id: 'code',
      header: 'Code',
      cell: (department) => <Badge variant="neutral" className="font-mono">{department.code}</Badge>,
    },
    {
      id: 'unit',
      header: 'Business unit',
      cell: (department) => department.unit?.name ?? 'Unassigned',
    },
    { id: 'programs', header: 'Programs', cell: (department) => department.program_count },
    { id: 'courses', header: 'Courses', cell: (department) => department.course_count },
    {
      id: 'status',
      header: 'Status',
      cell: (department) => {
        const status = statusFor(department)
        return <Badge variant={status.variant}>{status.label}</Badge>
      },
    },
  ]

  const rowActions = (department: Department): DataTableAction<Department>[] => [
    { label: 'Edit', onSelect: openEditDrawer, disabled: !canManage },
    ...(!department.archived_at
      ? [{ label: 'Archive', onSelect: setArchiveTarget, disabled: !canManage }]
      : []),
  ]

  return (
    <section className="space-y-6">
      <PageHeader
        title="Departments"
        description="Manage departments, their programs, and course counts."
        actions={canManage && (
          <Button size="md" className="h-10" onClick={openCreateDrawer}>
            <Plus size={16} aria-hidden="true" />
            Add department
          </Button>
        )}
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <label className="relative min-w-0 flex-1">
          <span className="sr-only">Search departments</span>
          <Search size={16} aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-subtle" />
          <Input
            className="h-10 pl-9"
            type="search"
            placeholder="Search departments"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value)
              setPage(1)
            }}
          />
        </label>
        <label className="inline-flex h-10 items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(event) => {
              setShowArchived(event.target.checked)
              setPage(1)
            }}
          />
          Show archived
        </label>
      </div>

      {departmentsQuery.isError ? (
        <div className="space-y-2" role="alert">
          <p>{departmentsQuery.error.message}</p>
          <Button variant="secondary" size="sm" onClick={() => void departmentsQuery.refetch()}>Retry</Button>
        </div>
      ) : (
        <DataTable
          columns={columns}
          rows={departmentsQuery.data?.results ?? []}
          getRowId={(department) => department.id}
          loading={departmentsQuery.isPending}
          page={page}
          pageSize={25}
          total={departmentsQuery.data?.count ?? 0}
          onPageChange={setPage}
          rowActions={canManage ? rowActions : undefined}
          emptyState={(
            <EmptyState
              title={search ? 'No departments match this search' : 'No departments yet'}
              description={search ? 'Try another name or code.' : 'Add a department to organize programs and courses.'}
            />
          )}
        />
      )}

      <Drawer
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={editing ? 'Edit department' : 'Add department'}
        description="Department names and codes must be unique."
      >
        <form className="space-y-5" onSubmit={submitDepartment} noValidate>
          <FormField label="Department name" error={fieldErrors.name}>
            <Input
              autoFocus
              maxLength={160}
              value={name}
              onChange={(event) => {
                setName(event.target.value)
                setFieldErrors((current) => ({ ...current, name: undefined }))
              }}
              required
            />
          </FormField>
          <FormField label="Business unit" error={fieldErrors.unit}>
            <select
              className="h-10 w-full rounded-md border border-line bg-surface px-3 text-sm"
              value={unitId}
              onChange={(event) => {
                setUnitId(event.target.value)
                setFieldErrors((current) => ({ ...current, unit: undefined }))
              }}
              required
            >
              <option value="">Select a business unit</option>
              {unit.units.map((businessUnit) => (
                <option key={businessUnit.id} value={businessUnit.id}>{businessUnit.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Code" hint="2–8 uppercase letters or digits." error={fieldErrors.code}>
            <Input
              className="font-mono uppercase"
              maxLength={8}
              value={code}
              onChange={(event) => {
                setCode(event.target.value.toUpperCase())
                setCodeChanged(true)
                setFieldErrors((current) => ({ ...current, code: undefined }))
              }}
              required
            />
          </FormField>
          {formError && <p className="text-sm text-danger-fg" role="alert">{formError}</p>}
          <div className="flex justify-end gap-2 border-t border-line pt-4">
            <Button type="button" variant="secondary" size="md" onClick={() => setDrawerOpen(false)}>Cancel</Button>
            <Button type="submit" size="md" loading={saveDepartment.isPending}>
              {editing ? <Pencil size={16} aria-hidden="true" /> : <Plus size={16} aria-hidden="true" />}
              {editing ? 'Save changes' : 'Add department'}
            </Button>
          </div>
        </form>
      </Drawer>

      <Dialog open={Boolean(archiveTarget)} onOpenChange={(open) => !open && setArchiveTarget(null)}>
        <DialogContent>
          <DialogTitle>Archive department?</DialogTitle>
          <DialogDescription>
            {archiveTarget
              ? `${archiveTarget.name} will be hidden from the default list. You can show archived departments later.`
              : 'This department will be hidden from the default list.'}
          </DialogDescription>
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setArchiveTarget(null)}>Cancel</Button>
            <Button
              variant="danger"
              loading={archiveDepartment.isPending}
              disabled={!archiveTarget}
              onClick={() => archiveTarget && archiveDepartment.mutate(archiveTarget)}
            >
              Archive department
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  )
}
