import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { useAuth } from '../lib/auth/AuthProvider'

const loginSchema = z.object({
  email: z.string().email('Enter a valid email address.'),
  password: z.string().min(1, 'Password is required.'),
})

type LoginValues = z.infer<typeof loginSchema>

export function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [serverError, setServerError] = useState('')
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({ resolver: zodResolver(loginSchema) })

  const submit = handleSubmit(async ({ email, password }) => {
    setServerError('')
    try {
      await login(email, password)
      navigate('/app/me', { replace: true })
    } catch {
      setServerError('Unable to sign in. Check your email and password.')
    }
  })

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center p-6">
      <Link to="/" className="mb-6 text-sm underline">Watan LMS</Link>
      <h1 className="mb-2 text-3xl font-semibold">Sign in</h1>
      <p className="mb-6 text-neutral-600">Use your school account to continue.</p>
      <form className="space-y-4" onSubmit={submit} noValidate>
        <label className="block">
          <span className="mb-1 block">Email</span>
          <input className="w-full rounded border border-neutral-300 bg-white p-3" type="email" autoComplete="email" {...register('email')} />
          {errors.email && <span role="alert" className="text-sm text-red-700">{errors.email.message}</span>}
        </label>
        <label className="block">
          <span className="mb-1 block">Password</span>
          <input className="w-full rounded border border-neutral-300 bg-white p-3" type="password" autoComplete="current-password" {...register('password')} />
          {errors.password && <span role="alert" className="text-sm text-red-700">{errors.password.message}</span>}
        </label>
        {serverError && <p role="alert" className="text-sm text-red-700">{serverError}</p>}
        <button className="w-full rounded bg-neutral-900 p-3 font-medium text-white disabled:opacity-60" type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}
