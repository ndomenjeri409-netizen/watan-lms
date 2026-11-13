function firstMessage(value: unknown): string | undefined {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) {
    for (const item of value) {
      const message = firstMessage(item)
      if (message) return message
    }
    return undefined
  }
  if (typeof value === 'object' && value !== null) {
    for (const nested of Object.values(value)) {
      const message = firstMessage(nested)
      if (message) return message
    }
  }
  return undefined
}

export function apiErrorFields(error: unknown): Record<string, string> {
  if (
    typeof error !== 'object'
    || error === null
    || !('fields' in error)
    || typeof error.fields !== 'object'
    || error.fields === null
  ) return {}

  return Object.fromEntries(
    Object.entries(error.fields).flatMap(([field, value]) => {
      const message = firstMessage(value)
      return message ? [[field, message]] : []
    }),
  )
}

export function apiErrorMessage(error: unknown, fallback: string) {
  const fieldMessage = firstMessage(apiErrorFields(error))
  if (
    typeof error === 'object'
    && error !== null
    && 'message' in error
    && typeof error.message === 'string'
    && error.message !== 'Request failed.'
  ) {
    return error.message
  }
  return fieldMessage ?? fallback
}
