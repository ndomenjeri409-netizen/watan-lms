import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '../../lib/cn'
import { Button } from './button'

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden="true" className={cn('animate-pulse rounded-md bg-surface-2 dark:bg-surface-2', className)} {...props} />
}

export interface EmptyStateProps {
  icon?: ReactNode
  title: string
  description?: string
  action?: ReactNode
  className?: string
}

export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center gap-2 px-6 py-10 text-center', className)}>
      {icon && <div className="mb-1 text-subtle" aria-hidden="true">{icon}</div>}
      <h3 className="font-semibold">{title}</h3>
      {description && <p className="max-w-md text-sm text-subtle">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

export interface ErrorStateProps {
  message: string
  onRetry?: () => void
  className?: string
}

export function ErrorState({ message, onRetry, className }: ErrorStateProps) {
  return (
    <div className={cn('flex flex-col items-start gap-3 rounded-md border border-danger/40 bg-surface p-4 text-sm text-fg', className)} role="alert">
      <p>{message}</p>
      {onRetry && <Button variant="secondary" size="sm" onClick={onRetry}>Try again</Button>}
    </div>
  )
}
