import { Button } from './button'
import { cn } from '../../lib/cn'

export interface PaginationProps {
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  className?: string
}

export function Pagination({ page, pageSize, total, onPageChange, className }: PaginationProps) {
  if (!Number.isInteger(page) || page < 1 || !Number.isInteger(pageSize) || pageSize < 1 || total < 0) {
    throw new RangeError('Pagination requires a positive page and pageSize and a non-negative total.')
  }
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const safePage = Math.min(page, pageCount)
  const start = total === 0 ? 0 : (safePage - 1) * pageSize + 1
  const end = Math.min(safePage * pageSize, total)

  return (
    <nav className={cn('flex items-center justify-between gap-4', className)} aria-label="Pagination">
      <p className="text-sm text-subtle">Showing {start}–{end} of {total}</p>
      <div className="flex gap-2">
        <Button variant="secondary" size="sm" onClick={() => onPageChange(safePage - 1)} disabled={safePage <= 1} aria-label="Previous page">
          Previous
        </Button>
        <span className="flex items-center px-2 text-sm" aria-current="page">Page {safePage} of {pageCount}</span>
        <Button variant="secondary" size="sm" onClick={() => onPageChange(safePage + 1)} disabled={safePage >= pageCount} aria-label="Next page">
          Next
        </Button>
      </div>
    </nav>
  )
}
