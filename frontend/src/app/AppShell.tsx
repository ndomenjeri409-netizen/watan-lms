import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  Bell,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Menu,
  Moon,
  Search,
  Sun,
} from 'lucide-react'
import { Link, NavLink, Outlet } from 'react-router-dom'
import type { components } from '../api/schema'
import type { User } from 'firebase/auth'
import { Avatar, Badge, Button, Card, Drawer, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger, Input, Tooltip, TooltipContent, TooltipTrigger } from '../components/ui'
import { roleLabel } from '../features/me/roles'
import { UnitProvider } from '../features/units/UnitProvider'
import { useUnit } from '../features/units/useUnit'
import { navFor } from './navigation'
import { cn } from '../lib/cn'
import { getTheme, setTheme, type Theme } from '../lib/theme'

type Profile = components['schemas']['Me']
type UserPresentation = Pick<User, 'displayName' | 'photoURL'>

interface AppShellProps {
  profile?: Profile
  firebaseUser: UserPresentation
  logout: () => Promise<void>
  profileLoading?: boolean
  notificationCount?: number
  children?: ReactNode
}

const sidebarStorageKey = 'watan-lms-sidebar-collapsed'

function displayName(profile: Profile | undefined, firebaseUser: UserPresentation) {
  const name = profile?.display_name.trim() || profile?.email.split('@')[0] || firebaseUser.displayName?.trim()
  if (name) return name
  return 'Account'
}

function roleSummary(profile: Profile | undefined) {
  const labels = [...new Set(profile?.assignments.map((assignment) => roleLabel(assignment.role)) ?? [])]
  return labels.length ? labels.join(', ') : roleLabel(profile?.role)
}

function assignmentUnits(profile: Profile | undefined) {
  return [...new Set(profile?.assignments.map((assignment) => assignment.unit?.code ?? 'All units') ?? [])]
    .join(', ')
}

function WakingNotice({ visible }: { visible: boolean }) {
  const [delayed, setDelayed] = useState(false)

  useEffect(() => {
    if (!visible) return
    const timer = window.setTimeout(() => setDelayed(true), 3000)
    return () => window.clearTimeout(timer)
  }, [visible])

  if (!visible || !delayed) return null
  return (
    <div className="border-b border-primary/40 bg-primary/15 px-4 py-2 text-center text-sm text-warning-fg dark:border-primary/40 dark:bg-primary dark:text-warning-fg" role="status">
      Waking up the server…
    </div>
  )
}

function SidebarContent({
  profile,
  firebaseUser,
  collapsed,
  onNavigate,
}: {
  profile?: Profile
  firebaseUser: UserPresentation
  collapsed: boolean
  onNavigate?: () => void
}) {
  const sections = navFor(profile)
  const name = displayName(profile, firebaseUser)

  return (
    <div className="flex h-full flex-col bg-sidebar text-sidebar-fg">
      <Link to="/app/me" onClick={onNavigate} className={cn('flex h-16 shrink-0 items-center gap-3 border-b border-white/10 px-4 font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring', collapsed && 'justify-center px-2')} aria-label="Watan LMS home">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-fg"><BookOpen size={19} aria-hidden="true" /></span>
        {!collapsed && <span>Watan LMS</span>}
      </Link>

      <nav className="sidebar-scroll min-h-0 flex-1 space-y-6 px-3 py-5" aria-label="Main navigation">
        {sections.map((section) => (
          <section key={section.title}>
            {!collapsed && <h2 className="mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-sidebar-fg/70">{section.title}</h2>}
            <ul className="space-y-1">
              {section.items.map(({ label, to, icon: Icon, badge }) => (
                <li key={to}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <NavLink
                        to={to}
                        end={to === '/app' || to === '/app/me'}
                        onClick={onNavigate}
                        aria-label={collapsed ? label : undefined}
                        className={({ isActive }) => cn(
                          'flex min-h-10 items-center gap-3 rounded-md px-3 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                          collapsed && 'justify-center px-2',
                          isActive
                            ? 'border-l-[3px] border-primary bg-sidebar-active pl-[9px] font-medium text-white'
                            : 'border-l-[3px] border-transparent pl-[9px] hover:bg-white/5 hover:text-white',
                        )}
                      >
                        <Icon size={18} aria-hidden="true" />
                        {!collapsed && <span className="min-w-0 flex-1 truncate">{label}</span>}
                        {!collapsed && badge === 'pending' && <span className="size-2 rounded-full bg-primary" aria-label="Pending" />}
                      </NavLink>
                    </TooltipTrigger>
                    {collapsed && <TooltipContent side="right">{label}</TooltipContent>}
                  </Tooltip>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </nav>

      <div className={cn('border-t border-white/10 p-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))]', collapsed && 'px-2')}>
        <div className={cn('flex min-w-0 items-center gap-3 rounded-md bg-white/5 p-2', collapsed && 'justify-center')}>
          <Avatar className="size-9 shrink-0 bg-sidebar-active text-white" src={firebaseUser.photoURL} alt={name} />
          {!collapsed && (
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-white">{name}</p>
              <p className="truncate text-xs text-sidebar-fg/75">{roleSummary(profile)}</p>
              {assignmentUnits(profile) && <p className="truncate text-[11px] text-sidebar-fg/60">{assignmentUnits(profile)}</p>}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Topbar({
  profile,
  firebaseUser,
  logout,
  collapsed,
  onToggleSidebar,
  onOpenMobileNav,
  notifications,
}: {
  profile?: Profile
  firebaseUser: UserPresentation
  logout: () => Promise<void>
  collapsed: boolean
  onToggleSidebar: () => void
  onOpenMobileNav: () => void
  notifications: number
}) {
  const unit = useUnit()
  const [searchOpen, setSearchOpen] = useState(false)
  const [theme, setCurrentTheme] = useState<Theme>(getTheme)
  const searchInput = useRef<HTMLInputElement>(null)
  const name = displayName(profile, firebaseUser)
  const searchShortcut = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
    ? '⌘ K'
    : 'Ctrl K'

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== 'k' || (!event.metaKey && !event.ctrlKey)) return
      event.preventDefault()
      searchInput.current?.focus()
    }
    window.addEventListener('keydown', handleShortcut)
    return () => window.removeEventListener('keydown', handleShortcut)
  }, [])

  const toggleTheme = () => {
    const nextTheme = theme === 'dark' ? 'light' : 'dark'
    setTheme(nextTheme)
    setCurrentTheme(nextTheme)
  }

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-line bg-surface/95 px-4 backdrop-blur sm:px-6">
      <Tooltip>
        <TooltipTrigger asChild>
          <Button className="lg:hidden" variant="ghost" size="sm" onClick={onOpenMobileNav} aria-label="Open navigation menu">
            <Menu size={19} aria-hidden="true" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>Open navigation menu</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button className="hidden lg:inline-flex" variant="ghost" size="sm" onClick={onToggleSidebar} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
            {collapsed ? <ChevronRight size={19} aria-hidden="true" /> : <ChevronLeft size={19} aria-hidden="true" />}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{collapsed ? 'Expand sidebar' : 'Collapse sidebar'}</TooltipContent>
      </Tooltip>

      <div className="relative min-w-0 flex-1">
        <div className="relative max-w-md">
          <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-subtle" size={16} aria-hidden="true" />
          <Input
            ref={searchInput}
            className="h-9 min-h-9 pl-9 pr-16"
            aria-label="Search"
            placeholder="Search"
            onFocus={() => setSearchOpen(true)}
            onChange={() => setSearchOpen(true)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') setSearchOpen(false)
            }}
          />
          <kbd className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-subtle">{searchShortcut}</kbd>
        </div>
        {searchOpen && (
          <>
            <button type="button" className="fixed inset-0 z-10 cursor-default" aria-label="Close search message" onClick={() => setSearchOpen(false)} />
            <div className="absolute left-0 top-full z-20 mt-2 w-full max-w-md rounded-md border border-line bg-surface p-4 text-sm text-subtle shadow-lg" role="status">
              Search is coming soon
            </div>
          </>
        )}
      </div>

      {unit.isError ? (
        <span className="hidden text-xs text-danger-fg sm:inline" role="alert">Units unavailable</span>
      ) : unit.isLoading ? (
        <span className="hidden text-xs text-subtle sm:inline" role="status">Loading units…</span>
      ) : unit.canSelectUnit ? (
        <label className="sr-only" htmlFor="active-unit">Active business unit</label>
      ) : null}
      {!unit.isError && !unit.isLoading && unit.canSelectUnit ? (
        <select
          id="active-unit"
          className="h-9 max-w-36 rounded-md border border-line bg-surface px-2 text-sm sm:max-w-48"
          value={unit.selectedValue}
          onChange={(event) => unit.selectUnit(event.target.value)}
          aria-label="Active business unit"
        >
          {profile?.is_global_read && <option value="all">All units</option>}
          {unit.units.map((businessUnit) => (
            <option key={businessUnit.id} value={businessUnit.id}>{businessUnit.name}</option>
          ))}
        </select>
      ) : !unit.isError && !unit.isLoading && unit.units.length === 1 ? (
        <Badge variant="neutral" className="max-w-24 truncate sm:max-w-36">{unit.unitLabel}</Badge>
      ) : null}

      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="sm" onClick={toggleTheme} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>
            {theme === 'dark' ? <Sun size={18} aria-hidden="true" /> : <Moon size={18} aria-hidden="true" />}
          </Button>
        </TooltipTrigger>
        <TooltipContent>Switch to {theme === 'dark' ? 'light' : 'dark'} mode</TooltipContent>
      </Tooltip>
      {notifications > 0 && (
        <Button variant="ghost" size="sm" aria-label={`${notifications} notifications`}>
          <span className="relative">
            <Bell size={18} aria-hidden="true" />
            <span className="absolute -right-2 -top-2 min-w-4 rounded-full bg-primary px-1 text-center text-[10px] leading-4 text-primary-fg">{notifications}</span>
          </span>
        </Button>
      )}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" className="gap-2 px-1.5" aria-label={`Account menu for ${name}`}>
            <Avatar className="size-8" src={firebaseUser.photoURL} alt={name} />
            <span className="hidden max-w-32 truncate text-sm sm:block">{name}</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="min-w-56">
          <DropdownMenuLabel>
            <p className="truncate text-sm font-medium text-fg">{name}</p>
            <p className="truncate font-normal">{profile?.email ?? firebaseUser.displayName ?? ''}</p>
            <Badge className="mt-2">{roleSummary(profile)}</Badge>
            {assignmentUnits(profile) && <p className="mt-1 text-xs">{assignmentUnits(profile)}</p>}
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem asChild><Link to="/app/me">My profile</Link></DropdownMenuItem>
          <DropdownMenuItem onSelect={() => void logout()}>Sign out</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  )
}

export function AppShell({
  profile,
  firebaseUser,
  logout,
  profileLoading = false,
  notificationCount = 0,
  children,
}: AppShellProps) {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(sidebarStorageKey) === 'true')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [dismissedNoticeFor, setDismissedNoticeFor] = useState<string | null>(null)
  useEffect(() => {
    localStorage.setItem(sidebarStorageKey, String(collapsed))
  }, [collapsed])

  return (
    <UnitProvider profile={profile}>
    <div className="min-h-dvh bg-app text-fg">
      <a className="skip-link" href="#main">Skip to content</a>
      <div className="flex min-h-dvh">
        <aside className={cn('sticky top-0 hidden h-dvh shrink-0 transition-[width] duration-200 lg:block', collapsed ? 'w-20' : 'w-64')} aria-label="Sidebar">
          <SidebarContent profile={profile} firebaseUser={firebaseUser} collapsed={collapsed} />
        </aside>
        <div className="min-w-0 flex-1">
          <Topbar
            profile={profile}
            firebaseUser={firebaseUser}
            logout={logout}
            collapsed={collapsed}
            onToggleSidebar={() => setCollapsed((value) => !value)}
            onOpenMobileNav={() => setMobileOpen(true)}
            notifications={notificationCount}
          />
          <WakingNotice visible={profileLoading} />
          {profile
            && !profile.display_name.trim()
            && dismissedNoticeFor !== profile.id
            && localStorage.getItem(`watan-profile-notice-dismissed-${profile.id}`) !== 'true' && (
            <div className="flex items-center justify-between gap-3 border-b border-line bg-surface-2 px-4 py-3 text-sm sm:px-6" role="status">
              <p>
                Complete your profile.{' '}
                <Link className="font-medium text-fg underline underline-offset-2" to="/app/me#complete-profile">Add your name and phone number</Link>
              </p>
              <Button
                variant="ghost"
                size="sm"
                aria-label="Dismiss complete your profile notice"
                onClick={() => {
                  localStorage.setItem(`watan-profile-notice-dismissed-${profile.id}`, 'true')
                  setDismissedNoticeFor(profile.id)
                }}
              >
                ×
              </Button>
            </div>
          )}
          <main id="main" tabIndex={-1} className="mx-auto w-full max-w-7xl p-4 sm:p-6 lg:p-8">
            {profileLoading
              ? <p role="status">Loading your profile…</p>
              : profile?.awaiting_approval
              ? <Card className="p-5" role="status">Your account is awaiting approval.</Card>
              : children ?? <Outlet />}
          </main>
        </div>
      </div>
      <Drawer open={mobileOpen} onOpenChange={setMobileOpen} title="Watan LMS navigation" side="left" className="w-72 max-w-[85vw] border-0 p-0 lg:hidden">
        <SidebarContent profile={profile} firebaseUser={firebaseUser} collapsed={false} onNavigate={() => setMobileOpen(false)} />
      </Drawer>
    </div>
    </UnitProvider>
  )
}
