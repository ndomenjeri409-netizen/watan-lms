import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Button } from './button'
import { cn } from '../../lib/cn'
import { ToastContext, type ToastOptions } from './toast-context'

interface ToastItem extends ToastOptions {
  id: number
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const nextId = useRef(0)
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>())

  const dismiss = useCallback((id: number) => {
    const timer = timers.current.get(id)
    if (timer) clearTimeout(timer)
    timers.current.delete(id)
    setItems((current) => current.filter((item) => item.id !== id))
  }, [])

  const toast = useCallback((options: ToastOptions) => {
    const id = ++nextId.current
    setItems((current) => [...current, { ...options, id }])
    const timer = setTimeout(() => dismiss(id), options.duration ?? 5000)
    timers.current.set(id, timer)
    return id
  }, [dismiss])

  useEffect(() => () => {
    for (const timer of timers.current.values()) clearTimeout(timer)
    timers.current.clear()
  }, [])

  const value = useMemo(() => ({ toast, dismiss }), [toast, dismiss])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed right-4 top-4 z-[100] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2" aria-live="polite" aria-relevant="additions">
        {items.map((item) => (
          <div
            key={item.id}
            className={cn(
              'pointer-events-auto rounded-md border bg-surface p-4 text-sm text-fg shadow-lg',
              item.variant === 'success' && 'border-success/40',
              item.variant === 'error' && 'border-danger/40',
              (!item.variant || item.variant === 'default') && 'border-line',
            )}
            role={item.variant === 'error' ? 'alert' : 'status'}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-semibold">{item.title}</p>
                {item.description && <p className="mt-1 text-subtle">{item.description}</p>}
              </div>
              <Button variant="ghost" size="sm" onClick={() => dismiss(item.id)} aria-label="Dismiss notification">×</Button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
