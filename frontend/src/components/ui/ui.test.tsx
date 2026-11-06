import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Button } from './button'
import { DataTable, type DataTableColumn } from './data-table'
import { FormField, Input } from './form'
import { Pagination } from './pagination'
import { StatCard } from './stat-card'

interface Row {
  id: string
  name: string
}

const columns: DataTableColumn<Row>[] = [
  { id: 'name', header: 'Name', accessor: 'name', sortable: true },
]

describe('UI primitives', () => {
  it('exposes loading and form validation accessibly', () => {
    const { rerender } = render(<Button loading>Save</Button>)
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('aria-busy', 'true')

    rerender(
      <FormField label="Email" hint="Use your school email." error="Email is required.">
        <Input />
      </FormField>,
    )
    const input = screen.getByLabelText('Email')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input.getAttribute('aria-describedby')).toContain('field-email-hint')
    expect(input.getAttribute('aria-describedby')).toContain('field-email-error')
  })

  it('reports sortable table selection and uses server-side pagination', () => {
    const onSelectionChange = vi.fn()
    const onPageChange = vi.fn()
    const onSortChange = vi.fn()
    const rows = [{ id: '1', name: 'Amina' }]

    render(
      <DataTable
        columns={columns}
        rows={rows}
        getRowId={(row) => row.id}
        page={1}
        pageSize={1}
        total={2}
        onPageChange={onPageChange}
        onSortChange={onSortChange}
        onSelectionChange={onSelectionChange}
        selectedRows={[]}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Sort by Name' }))
    expect(onSortChange).toHaveBeenCalledWith('name', 'asc')
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select row 1' }))
    expect(onSelectionChange).toHaveBeenCalledWith(rows)
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }))
    expect(onPageChange).toHaveBeenCalledWith(2)
  })

  it('renders clamped progress and loading skeletons for stat cards', () => {
    const { rerender } = render(<StatCard label="Completion" value="100%" progress={120} />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
    expect(screen.getByText('100%')).toBeInTheDocument()
    rerender(<StatCard label="Completion" value="" loading />)
    expect(screen.getByLabelText('Loading Completion')).toBeInTheDocument()
    rerender(<StatCard label="Completion" value="" error="Metrics unavailable." />)
    expect(screen.getByRole('alert')).toHaveTextContent('Metrics unavailable.')
  })

  it('does not render a stat card when its value is missing', () => {
    const { container, rerender } = render(<StatCard label="Courses" />)
    expect(container.firstChild).toBeNull()
    rerender(<StatCard label="Courses" value={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows the empty state and keeps pagination usable for an empty table', () => {
    const onPageChange = vi.fn()
    render(
      <DataTable
        columns={columns}
        rows={[]}
        page={1}
        pageSize={10}
        total={12}
        onPageChange={onPageChange}
        emptyState={<p>No students match this filter.</p>}
      />,
    )

    expect(screen.getByText('No students match this filter.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }))
    expect(onPageChange).toHaveBeenCalledWith(2)
  })

  it('disables pagination at the start and end of the result set', () => {
    render(<Pagination page={2} pageSize={10} total={20} onPageChange={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled()
  })
})
