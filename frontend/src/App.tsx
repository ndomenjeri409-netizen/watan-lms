import { Navigate, Outlet, Route, Routes, Link } from 'react-router-dom'
import { Login } from './pages/Login'
import { Me } from './pages/Me'
import { useAuth } from './lib/auth/AuthProvider'

function ProtectedLayout() {
  const { firebaseUser, loading } = useAuth()

  if (loading) return <main className="p-6">Loading your account…</main>
  if (!firebaseUser) return <Navigate to="/login" replace />

  return (
    <main className="mx-auto min-h-screen max-w-4xl p-6">
      <nav className="mb-8 flex items-center justify-between border-b border-neutral-200 pb-4">
        <Link className="font-semibold" to="/app/me">Watan LMS</Link>
        <Link className="text-sm underline" to="/app/me">My profile</Link>
      </nav>
      <Outlet />
    </main>
  )
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<main className="p-6"><h1 className="text-2xl font-semibold">Watan LMS</h1><p>Learning management, made simple.</p></main>} />
      <Route path="/login" element={<Login />} />
      <Route path="/app" element={<ProtectedLayout />}>
        <Route index element={<Navigate to="me" replace />} />
        <Route path="me" element={<Me />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
