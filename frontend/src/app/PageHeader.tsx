import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { cn } from '../lib/cn'
import { breadcrumbsForPath } from './navigation'

export interface PageBreadcrumb {
  label: string
  to?: string
}

export interface PageHeaderProps {
  title: string
  description?: string
  actions?: ReactNode
  breadcrumbs?: PageBreadcrumb[]
  className?: string
}

export function PageHeader({ title, description, actions, breadcrumbs, className }: PageHeaderProps) {
  const { pathname } = useLocation()
  const resolvedBreadcrumbs = pathname.startsWith('/app')
    ? breadcrumbsForPath(pathname, title)
    : breadcrumbs

  return (
    <header className={cn('flex flex-wrap items-end justify-between gap-4', className)}>
      <div>
        {resolvedBreadcrumbs && resolvedBreadcrumbs.length > 0 && (
          <nav aria-label="Breadcrumb" className="mb-2 flex items-center gap-2 text-sm text-subtle">
            {resolvedBreadcrumbs.map((breadcrumb, index) => (
              <span key={`${breadcrumb.label}-${index}`} className="inline-flex items-center gap-2">
                {index > 0 && <span aria-hidden="true">/</span>}
                {breadcrumb.to
                  ? <Link className="rounded-sm hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" to={breadcrumb.to}>{breadcrumb.label}</Link>
                  : <span aria-current={index === resolvedBreadcrumbs.length - 1 ? 'page' : undefined}>{breadcrumb.label}</span>}
              </span>
            ))}
          </nav>
        )}
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h1>
        {description && <p className="mt-1 text-sm text-subtle sm:text-base">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  )
}
