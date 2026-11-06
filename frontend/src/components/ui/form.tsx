import { forwardRef, isValidElement, cloneElement, type InputHTMLAttributes, type ReactElement, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

const controlStyles =
  'flex min-h-10 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-fg placeholder:text-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-app disabled:cursor-not-allowed disabled:opacity-50'

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {}

export const Input = forwardRef<HTMLInputElement, InputProps>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn(controlStyles, className)}
    {...props}
  />
))
Input.displayName = 'Input'

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(({ className, ...props }, ref) => (
  <select ref={ref} className={cn(controlStyles, className)} {...props} />
))
Select.displayName = 'Select'

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(({ className, ...props }, ref) => (
  <textarea ref={ref} className={cn(controlStyles, 'min-h-24 resize-y', className)} {...props} />
))
Textarea.displayName = 'Textarea'

type DescribedControl = {
  id?: string
  'aria-describedby'?: string
  'aria-invalid'?: boolean | 'true' | 'false'
}

export interface FormFieldProps {
  label: string
  hint?: string
  error?: string
  id?: string
  children: ReactElement<DescribedControl>
  className?: string
}

export function FormField({ label, hint, error, id, children, className }: FormFieldProps) {
  if (!isValidElement<DescribedControl>(children)) {
    throw new Error('FormField requires a single form control as its child.')
  }

  const controlId = id ?? children.props.id ?? `field-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
  const hintId = hint ? `${controlId}-hint` : undefined
  const errorId = error ? `${controlId}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined

  const control = cloneElement(children, {
    id: controlId,
    'aria-describedby': describedBy,
    'aria-invalid': error ? true : children.props['aria-invalid'],
  })

  return (
    <div className={cn('space-y-1.5', className)}>
      <label htmlFor={controlId} className="block text-sm font-medium">{label}</label>
      {control}
      {hint && <p id={hintId} className="text-sm text-subtle">{hint}</p>}
      {error && <p id={errorId} className="text-sm text-danger-fg dark:text-danger-fg" role="alert">{error}</p>}
    </div>
  )
}
