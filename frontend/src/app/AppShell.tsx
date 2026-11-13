import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  Bell,
  BookOpen,
  ChevronDown,
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
import { Avatar, Badge, Button, Card, Dialog, DialogContent, DialogDescription, DialogTitle, Drawer, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger, Input, Tooltip, TooltipContent, TooltipTrigger } from '../components/ui'
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
                        className={cn(
                          'flex min-h-10 items-center gap-3 rounded-md px-3 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                          collapsed && 'justify-center px-2',
                          'border-l-[3px] border-transparent pl-[9px] hover:bg-white/6 hover:text-white aria-[current=page]:border-primary aria-[current=page]:bg-sidebar-active aria-[current=page]:font-medium aria-[current=page]:text-white aria-[current=page]:hover:bg-sidebar-active aria-[current=page]:hover:text-white',
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
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false)
  const [theme, setCurrentTheme] = useState<Theme>(getTheme)
  const searchInput = useRef<HTMLInputElement>(null)
  const mobileSearchInput = useRef<HTMLInputElement>(null)
  const name = displayName(profile, firebaseUser)
  const searchShortcut = typeof navigator !== 'undefined' && /Mac/i.test(navigator.platform)
    ? '⌘ K'
    : 'Ctrl K'

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== 'k' || (!event.metaKey && !event.ctrlKey)) return
      event.preventDefault()
      if (window.innerWidth >= 640) searchInput.current?.focus()
      else setMobileSearchOpen(true)
    }
    window.addEventListener('keydown', handleShortcut)
    return () => window.removeEventListener('keydown', handleShortcut)
  }, [])

  const toggleTheme = () => {
    const nextTheme = theme === 'dark' ? 'light' : 'dark'
    setTheme(nextTheme)
    setCurrentTheme(nextTheme)
  }
  const mobileUnitLabel = unit.selectedValue === 'all'
    ? 'All'
    : unit.units.find((businessUnit) => businessUnit.id === unit.selectedValue)?.code ?? unit.unitLabel

  return (
    <header className="sticky top-0 z-30 flex h-[calc(3.5rem+env(safe-area-inset-top))] min-h-14 flex-nowrap items-center gap-1 border-b border-line bg-surface/95 px-2 pt-[env(safe-area-inset-top)] backdrop-blur sm:h-16 sm:min-h-16 sm:gap-3 sm:px-6 sm:py-0">
      <Tooltip>
        <TooltipTrigger asChild>
          <Button className="order-0 size-11 shrink-0 p-0 sm:hidden" variant="ghost" size="sm" onClick={onOpenMobileNav} aria-label="Open navigation menu">
            <Menu size={19} aria-hidden="true" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>Open navigation menu</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button className="order-0 hidden lg:inline-flex" variant="ghost" size="sm" onClick={onToggleSidebar} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
            {collapsed ? <ChevronRight size={19} aria-hidden="true" /> : <ChevronLeft size={19} aria-hidden="true" />}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{collapsed ? 'Expand sidebar' : 'Collapse sidebar'}</TooltipContent>
      </Tooltip>

      <div className="order-2 min-w-0 flex-1 sm:hidden" aria-hidden="true" />

      <div className="relative order-1 hidden min-w-0 max-w-md flex-1 sm:block">
        <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-subtle" size={16} aria-hidden="true" />
        <Input
          ref={searchInput}
          className="h-10 min-h-10 w-full pl-9 pr-20"
          aria-label="Search"
          placeholder="Search"
          onFocus={() => setSearchOpen(true)}
          onChange={() => setSearchOpen(true)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') setSearchOpen(false)
          }}
        />
        {searchOpen && (
          <div className="absolute left-0 top-full z-20 mt-2 w-full rounded-md border border-line bg-surface p-4 text-sm text-subtle shadow-lg" role="status">
            Search is coming soon
          </div>
        )}
        <kbd className="pointer-events-none absolute right-3 top-1/2 hidden -translate-y-1/2 whitespace-nowrap text-xs text-subtle lg:[@media(hover:hover)_and_(pointer:fine)]:inline-flex">
          {searchShortcut}
        </kbd>
      </div>

      {unit.isError ? (
        <span className="order-2 hidden shrink-0 text-xs text-danger-fg sm:inline" role="alert">Units unavailable</span>
      ) : unit.isLoading ? (
        <span className="order-2 hidden shrink-0 text-xs text-subtle sm:inline" role="status">Loading units…</span>
      ) : unit.canSelectUnit ? (
        <>
          <label className="sr-only" htmlFor="active-unit">Business unit</label>
          <div className="relative order-1 h-11 min-w-11 shrink-0 sm:order-2 sm:h-10 sm:w-40 sm:min-w-0">
            <span className="flex h-11 min-w-11 items-center justify-center rounded-full border border-line bg-surface-2 px-2 text-xs font-medium text-fg sm:hidden">
              {mobileUnitLabel}
            </span>
            <select
              id="active-unit"
              className="absolute inset-0 z-10 h-full w-full cursor-pointer opacity-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:static sm:z-0 sm:block sm:h-10 sm:w-full sm:appearance-none sm:rounded-md sm:border sm:border-line sm:bg-surface-2 sm:px-3 sm:pr-9 sm:text-sm sm:text-fg sm:opacity-100"
              value={unit.selectedValue}
              onChange={(event) => unit.selectUnit(event.target.value)}
              aria-label="Business unit"
            >
              {profile?.is_global_read && <option value="all">All units</option>}
              {unit.units.map((businessUnit) => (
                <option key={businessUnit.id} value={businessUnit.id}>{businessUnit.name}</option>
              ))}
            </select>
            <ChevronDown
              className="pointer-events-none absolute right-3 top-1/2 z-10 hidden -translate-y-1/2 text-subtle sm:block"
              size={16}
              aria-hidden="true"
            />
          </div>
        </>
      ) : !unit.isError && !unit.isLoading && unit.units.length === 1 ? (
        <Badge variant="neutral" className="order-1 shrink-0 truncate sm:order-2 sm:max-w-36">{unit.unitLabel}</Badge>
      ) : null}

      <Button
        className="order-3 size-11 shrink-0 p-0 sm:hidden"
        variant="ghost"
        size="sm"
        onClick={() => setMobileSearchOpen(true)}
        aria-label="Open search"
      >
        <Search size={19} aria-hidden="true" />
      </Button>
      <Dialog open={mobileSearchOpen} onOpenChange={setMobileSearchOpen}>
        <DialogContent
          className="left-1/2 top-[calc(env(safe-area-inset-top)+3.5rem)] w-[calc(100vw-1rem)] max-w-none -translate-x-1/2 translate-y-0 rounded-lg p-4 sm:hidden"
          onOpenAutoFocus={(event) => {
            event.preventDefault()
            mobileSearchInput.current?.focus()
          }}
        >
          <DialogTitle>Search</DialogTitle>
          <DialogDescription>Search is coming soon</DialogDescription>
          <Input ref={mobileSearchInput} className="mt-4 h-11 min-h-11" aria-label="Search" placeholder="Search" />
        </DialogContent>
      </Dialog>

      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            className="order-4 size-11 shrink-0 p-0 [@media(max-width:359px)]:hidden sm:size-10 lg:size-9"
            variant="ghost"
            size="sm"
            onClick={toggleTheme}
            aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          >
            {theme === 'dark' ? <Sun size={18} aria-hidden="true" /> : <Moon size={18} aria-hidden="true" />}
          </Button>
        </TooltipTrigger>
        <TooltipContent>Switch to {theme === 'dark' ? 'light' : 'dark'} mode</TooltipContent>
      </Tooltip>
      {notifications > 0 && (
        <Button className="order-5 hidden lg:inline-flex" variant="ghost" size="sm" aria-label={`${notifications} notifications`}>
          <span className="relative">
            <Bell size={18} aria-hidden="true" />
            <span className="absolute -right-2 -top-2 min-w-4 rounded-full bg-primary px-1 text-center text-[10px] leading-4 text-primary-fg">{notifications}</span>
          </span>
        </Button>
      )}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            className="order-6 size-11 shrink-0 p-0 sm:size-10 lg:h-9 lg:w-auto lg:gap-2 lg:px-1.5"
            aria-label={`Account menu for ${name}`}
          >
            <Avatar className="size-8" src={firebaseUser.photoURL} alt={name} />
            <span className="hidden max-w-32 truncate text-sm lg:block">{name}</span>
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
          <DropdownMenuItem className="min-h-11 [@media(min-width:360px)]:hidden" onSelect={toggleTheme}>
            Switch to {theme === 'dark' ? 'light' : 'dark'} mode
          </DropdownMenuItem>
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
      <a
        className="sr-only focus-visible:fixed focus-visible:left-4 focus-visible:top-4 focus-visible:z-50 focus-visible:not-sr-only focus-visible:rounded-md focus-visible:bg-primary focus-visible:px-4 focus-visible:py-2 focus-visible:font-medium focus-visible:text-primary-fg focus-visible:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        href="#main"
      >
        Skip to content
      </a>
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
