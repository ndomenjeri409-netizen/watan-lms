import { useMemo, useState, type ReactNode } from 'react'
import { MoreHorizontal } from 'lucide-react'
import { Button } from './button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from './dropdown-menu'
import { EmptyState, Skeleton } from './states'
import { Pagination } from './pagination'
import { cn } from '../../lib/cn'

export interface DataTableColumn<T> {
  id: string
  header: ReactNode
  accessor?: keyof T
  cell?: (row: T) => ReactNode
  sortable?: boolean
  className?: string
}

export interface DataTableAction<T> {
  label: string
  onSelect: (row: T) => void
  disabled?: boolean
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[]
  rows: T[]
  getRowId?: (row: T) => string
  loading?: boolean
  emptyState?: ReactNode
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  onSortChange?: (columnId: string, direction: 'asc' | 'desc') => void
  onSelectionChange?: (selectedRows: T[]) => void
  selectedRows?: T[]
  rowActions?: (row: T) => DataTableAction<T>[]
  className?: string
}

export function DataTable<T>({
  columns,
  rows,
  getRowId,
  loading = false,
  emptyState,
  page,
  pageSize,
  total,
  onPageChange,
  onSortChange,
  onSelectionChange,
  selectedRows,
  rowActions,
  className,
}: DataTableProps<T>) {
  const [sort, setSort] = useState<{ columnId: string; direction: 'asc' | 'desc' } | null>(null)
  const selectable = onSelectionChange !== undefined
  const selectedSet = useMemo(() => new Set(selectedRows ?? []), [selectedRows])
  const rowId = (row: T, index: number) => getRowId?.(row) ?? String(index)
  const allSelected = rows.length > 0 && rows.every((row) => selectedSet.has(row))

  const setAllSelected = (checked: boolean) => {
    if (!onSelectionChange) return
    const current = new Set(selectedRows ?? [])
    for (const row of rows) {
      if (checked) current.add(row)
      else current.delete(row)
    }
    onSelectionChange([...current])
  }

  const toggleSelected = (row: T, checked: boolean) => {
    if (!onSelectionChange) return
    const current = new Set(selectedRows ?? [])
    if (checked) current.add(row)
    else current.delete(row)
    onSelectionChange([...current])
  }

  const handleSort = (columnId: string) => {
    const direction = sort?.columnId === columnId && sort.direction === 'asc' ? 'desc' : 'asc'
    setSort({ columnId, direction })
    onSortChange?.(columnId, direction)
  }

  return (
    <div className={cn('space-y-4', className)}>
      <div className="scrollbar-thin overflow-x-auto rounded-md border border-line">
        <table className="w-full border-collapse text-left text-sm">
          <thead className="sticky top-0 z-10 bg-app text-subtle">
            <tr>
              {selectable && (
                <th scope="col" className="w-10 px-3 py-3">
                  <input
                    type="checkbox"
                    aria-label="Select all rows on this page"
                    checked={allSelected}
                    onChange={(event) => setAllSelected(event.currentTarget.checked)}
                  />
                </th>
              )}
              {columns.map((column) => (
                <th
                  key={column.id}
                  scope="col"
                  className={cn('whitespace-nowrap px-4 py-3 font-medium', column.className)}
                  aria-sort={column.sortable && sort?.columnId === column.id ? (sort.direction === 'asc' ? 'ascending' : 'descending') : undefined}
                >
                  {column.sortable ? (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 rounded-sm text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      onClick={() => handleSort(column.id)}
                      aria-label={`Sort by ${typeof column.header === 'string' ? column.header : column.id}`}
                    >
                      {column.header}
                      <span aria-hidden="true">{sort?.columnId === column.id ? (sort.direction === 'asc' ? '↑' : '↓') : '↕'}</span>
                    </button>
                  ) : column.header}
                </th>
              ))}
              {rowActions && <th scope="col" className="w-10 px-3 py-3"><span className="sr-only">Actions</span></th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {loading
              ? Array.from({ length: Math.min(pageSize, 5) }, (_, index) => (
                  <tr key={`loading-${index}`}>
                    {selectable && <td className="px-3 py-3"><Skeleton className="size-4" /></td>}
                    {columns.map((column) => <td key={column.id} className="px-4 py-3"><Skeleton className="h-4 w-24" /></td>)}
                    {rowActions && <td className="px-3 py-3"><Skeleton className="size-6" /></td>}
                  </tr>
                ))
              : rows.map((row, index) => (
                  <tr
                    key={rowId(row, index)}
                    tabIndex={0}
                    className="text-fg outline-none hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  >
                    {selectable && (
                      <td className="px-3 py-3">
                        <input
                          type="checkbox"
                          aria-label={`Select row ${index + 1}`}
                          checked={selectedSet.has(row)}
                          onChange={(event) => toggleSelected(row, event.currentTarget.checked)}
                        />
                      </td>
                    )}
                    {columns.map((column) => (
                      <td key={column.id} className={cn('px-4 py-3', column.className)}>
                        {column.cell ? column.cell(row) : column.accessor ? String(row[column.accessor] ?? '') : null}
                      </td>
                    ))}
                    {rowActions && (
                      <td className="px-3 py-2">
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="sm" aria-label="Row actions"><MoreHorizontal aria-hidden="true" size={16} /></Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {rowActions(row).map((action) => (
                              <DropdownMenuItem key={action.label} disabled={action.disabled} onSelect={() => action.onSelect(row)}>
                                {action.label}
                              </DropdownMenuItem>
                            ))}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </td>
                    )}
                  </tr>
                ))}
          </tbody>
        </table>
        {!loading && rows.length === 0 && (
          emptyState ?? <EmptyState title="No results" description="There are no rows to display." />
        )}
      </div>
      <Pagination page={page} pageSize={pageSize} total={total} onPageChange={onPageChange} />
    </div>
  )
}
