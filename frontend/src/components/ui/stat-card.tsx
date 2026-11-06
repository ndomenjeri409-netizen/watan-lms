import { Card, CardContent } from './card'
import { Skeleton } from './states'
import { cn } from '../../lib/cn'

export interface StatCardProps {
  label: string
  value?: string | number | null
  hint?: string
  progress?: number
  trend?: { value: string; direction: 'up' | 'down' | 'neutral' }
  loading?: boolean
  error?: string
  onRetry?: () => void
  className?: string
}

export function StatCard({
  label,
  value,
  hint,
  progress,
  trend,
  loading = false,
  error,
  onRetry,
  className,
}: StatCardProps) {
  if (loading) {
    return (
      <Card className={cn('min-h-36', className)} aria-label={`Loading ${label}`}>
        <CardContent className="space-y-3 pt-5">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-8 w-20" />
          <Skeleton className="h-3 w-36" />
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card className={cn('min-h-36', className)} role="alert">
        <CardContent className="space-y-2 pt-5">
          <p className="text-sm font-medium">{label}</p>
          <p className="text-sm text-subtle">{error}</p>
          {onRetry && (
            <button type="button" className="text-sm font-medium text-fg underline underline-offset-2" onClick={onRetry}>
              Retry
            </button>
          )}
        </CardContent>
      </Card>
    )
  }

  if (value === undefined || value === null || value === '') return null

  const boundedProgress = progress === undefined ? undefined : Math.max(0, Math.min(100, progress))

  return (
    <Card className={className}>
      <CardContent className="space-y-2 pt-5">
        <p className="text-sm font-medium text-subtle">{label}</p>
        <div className="flex items-baseline gap-2">
          <p className="text-3xl font-semibold">{value}</p>
          {trend && (
            <span
              className={cn(
                'text-xs font-medium',
                trend.direction === 'up' && 'text-success-fg dark:text-success-fg',
                trend.direction === 'down' && 'text-danger-fg dark:text-danger-fg',
                trend.direction === 'neutral' && 'text-subtle',
              )}
            >
              {trend.direction === 'up' ? '↑ ' : trend.direction === 'down' ? '↓ ' : ''}
              {trend.value}
            </span>
          )}
        </div>
        {hint && <p className="text-sm text-subtle">{hint}</p>}
        {boundedProgress !== undefined && (
          <div
            className="h-2 overflow-hidden rounded-full bg-app"
            role="progressbar"
            aria-label={`${label} progress`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={boundedProgress}
          >
            <div className="h-full rounded-full bg-primary" style={{ width: `${boundedProgress}%` }} />
          </div>
        )}
      </CardContent>
    </Card>
  )
}
