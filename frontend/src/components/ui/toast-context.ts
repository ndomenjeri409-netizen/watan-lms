import { createContext } from 'react'

export interface ToastOptions {
  title: string
  description?: string
  variant?: 'default' | 'success' | 'error'
  duration?: number
}

export interface ToastContextValue {
  toast: (options: ToastOptions) => number
  dismiss: (id: number) => void
}

export const ToastContext = createContext<ToastContextValue | null>(null)
