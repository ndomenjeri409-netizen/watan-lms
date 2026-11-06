import { updateProfile } from 'firebase/auth'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useAuth } from '../../lib/auth/useAuth'

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
    queryKey: ['me', firebaseUser?.uid],
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

export function useUpdateMe() {
  const { firebaseUser } = useAuth()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (profile: { display_name: string; phone_number: string }) => {
      if (!firebaseUser) throw new ApiError('You must be signed in to update your profile.', 'UNAUTHENTICATED')

      const previousDisplayName = firebaseUser.displayName
      await updateProfile(firebaseUser, { displayName: profile.display_name })
      const { data, error } = await api.PATCH('/api/v1/me', { body: profile })
      if (error || !data) {
        const apiError = error ? toApiError(error) : new ApiError('The API returned no profile.', 'UNKNOWN')
        try {
          await updateProfile(firebaseUser, { displayName: previousDisplayName })
        } catch (rollbackError) {
          throw new AggregateError(
            [apiError, rollbackError],
            'Profile update failed and the Firebase display name could not be restored.',
          )
        }
        throw apiError
      }
      return data
    },
    onSuccess: (profile) => {
      if (firebaseUser) {
        queryClient.setQueryData(['me', firebaseUser.uid], profile)
      }
    },
  })
}
