import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import '@fontsource-variable/inter'
import '../src/index.css'
import type { components } from '../src/api/schema'
import { TooltipProvider } from '../src/components/ui'
import { AppShell } from '../src/app/AppShell'
import { getTheme, setTheme } from '../src/lib/theme'

const profile: components['schemas']['Me'] = {
  id: 'topbar-e2e-user',
  email: 'admin@example.com',
  display_name: 'Admin Example',
  phone_number: '',
  role: 'ADMIN',
  assignments: [{ role: 'ADMIN', unit: null }],
  is_global_read: true,
  awaiting_approval: false,
  is_active: true,
}

setTheme(getTheme())

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TooltipProvider>
        <MemoryRouter initialEntries={['/app']}>
          <Routes>
            <Route
              path="/app"
              element={(
                <AppShell
                  profile={profile}
                  firebaseUser={{ displayName: 'Admin Example', photoURL: null }}
                  logout={async () => undefined}
                >
                  <h1>Responsive topbar fixture</h1>
                </AppShell>
              )}
            />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
)
