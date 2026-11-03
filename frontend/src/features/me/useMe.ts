import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useAuth } from '../../lib/auth/AuthProvider'

export class ApiError extends Error {
  readonly code: string
  readonly fields: Record<string, unknown>

  constructor(
    message: string,
    code: string,
    fields: Record<string, unknown> = {},
  ) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.fields = fields
  }
}

function toApiError(error: unknown) {
  if (
    typeof error === 'object'
    && error !== null
    && 'message' in error
    && typeof error.message === 'string'
  ) {
    const code = 'code' in error && typeof error.code === 'string' ? error.code : 'UNKNOWN'
    const fields = 'fields' in error && typeof error.fields === 'object' && error.fields !== null
      ? error.fields as Record<string, unknown>
      : {}
    return new ApiError(error.message, code, fields)
  }
  return new ApiError('The API request failed.', 'UNKNOWN')
}

export function useMe() {
  const { firebaseUser } = useAuth()
  return useQuery({
    queryKey: ['me'],
    enabled: Boolean(firebaseUser),
    staleTime: 60_000,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/me')
      if (error) throw toApiError(error)
      if (!data) throw new ApiError('The API returned no profile.', 'UNKNOWN')
      return data
    },
  })
}
