import { lazy, Suspense } from 'react'
import { Navigate, Outlet, Route, Routes, Link } from 'react-router-dom'
import type { User } from 'firebase/auth'
import type { components } from './api/schema'
import { Login } from './pages/Login'
import { Me } from './pages/Me'
import { Users } from './pages/Users'
import { Departments } from './pages/Departments'
import { CourseEditor } from './pages/CourseEditor'
import { CourseDetails, Courses } from './pages/Courses'
import { AdmissionsQueue, Apply } from './pages/Admissions'
import { StudentProfile, Students } from './pages/Students'
import { AttendanceCheckIn, Scheduling } from './pages/Scheduling'
import { AssessmentWorkspace } from './pages/Assessment'
import { useAuth } from './lib/auth/useAuth'
import { useMe } from './features/me/useMe'
import { UiPreview } from './pages/UiPreview'
import { AppShell } from './app/AppShell'
import { Finance } from './pages/Finance'

const Dashboard = lazy(() => import('./app/Dashboard').then(({ Dashboard: component }) => ({ default: component })))

function ProtectedLayout() {
  const { firebaseUser, loading, logout } = useAuth()
  const { data: profile, isPending: profileLoading, isError } = useMe()

  if (loading) return <main className="p-6">Loading your account…</main>
  if (!firebaseUser) return <Navigate to="/login" replace />
  if (isError || !profile) {
    if (profileLoading) {
      return <AppShell profile={undefined} firebaseUser={firebaseUser} logout={logout} profileLoading><Outlet /></AppShell>
    }
    return (
      <main className="space-y-4 p-6" role="alert">
        <p>Your profile could not be loaded. Please sign out and try again.</p>
        <button className="underline" onClick={() => void logout()}>Sign out</button>
      </main>
    )
  }

  return <AppShell profile={profile} firebaseUser={firebaseUser} logout={logout} profileLoading={profileLoading}><Outlet /></AppShell>
}

function App() {
  return (
    <Routes>
      {import.meta.env.DEV && (
        <Route
          path="/app/_ui"
          element={(
            <AppShell
              profile={{ id: 'preview', email: 'preview@example.com', display_name: 'UI Preview', phone_number: '', role: 'ADMIN', assignments: [{ role: 'ADMIN', unit: null }], is_global_read: true, awaiting_approval: false, is_active: true } satisfies components['schemas']['Me']}
              firebaseUser={{ displayName: 'UI Preview', photoURL: null } satisfies Pick<User, 'displayName' | 'photoURL'>}
              logout={async () => undefined}
            >
              <UiPreview />
            </AppShell>
          )}
        />
      )}
      <Route path="/" element={<main className="space-y-3 p-6"><h1 className="text-2xl font-semibold">Watan LMS</h1><p>Learning management, made simple.</p><Link className="underline" to="/courses">Browse the course catalog</Link><p><Link className="underline" to="/apply">Apply for a course</Link></p></main>} />
      <Route path="/login" element={<Login />} />
      <Route path="/courses" element={<Courses />} />
      <Route path="/courses/:slug" element={<CourseDetails />} />
      <Route path="/apply" element={<Apply />} />
      <Route path="/app" element={<ProtectedLayout />}>
        <Route index element={<Suspense fallback={<main className="p-6">Loading dashboard…</main>}><Dashboard /></Suspense>} />
        <Route path="me" element={<Me />} />
        <Route path="users" element={<Users />} />
        <Route path="departments" element={<Departments />} />
        <Route path="courses" element={<CourseEditor />} />
        <Route path="students" element={<Students />} />
        <Route path="students/:id" element={<StudentProfile />} />
        <Route path="admissions" element={<AdmissionsQueue />} />
        <Route path="timetable" element={<Scheduling />} />
        <Route path="attendance/scan" element={<AttendanceCheckIn />} />
        <Route path="assessments" element={<AssessmentWorkspace />} />
        <Route path="finance" element={<Finance />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
