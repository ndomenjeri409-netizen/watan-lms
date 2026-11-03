import createClient, { type Middleware } from 'openapi-fetch'
import type { paths } from './schema'
import { auth } from '../lib/firebase'

const authMiddleware: Middleware = {
  async onRequest({ request }) {
    const token = await auth.currentUser?.getIdToken()
    if (token) request.headers.set('Authorization', `Bearer ${token}`)
    return request
  },
}

export const api = createClient<paths>({
  baseUrl: import.meta.env.VITE_API_URL,
})
api.use(authMiddleware)
