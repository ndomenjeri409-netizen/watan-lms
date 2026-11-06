import {
  Award,
  BookOpen,
  Building2,
  CalendarCheck,
  ClipboardList,
  GraduationCap,
  LayoutDashboard,
  ReceiptText,
  PenSquare,
  User,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { hasRole, type Profile, type Role } from '../features/me/roles'

export type NavItem = {
  label: string
  to: string
  icon: LucideIcon
  roles: Role[] | 'all'
  badge?: 'pending'
}

export type NavSection = {
  title: string
  items: NavItem[]
}

export const NAV: NavSection[] = [
  {
    title: 'Overview',
    items: [
      { label: 'Dashboard', to: '/app', icon: LayoutDashboard, roles: 'all' },
      { label: 'My profile', to: '/app/me', icon: User, roles: 'all' },
    ],
  },
  {
    title: 'People',
    items: [
      {
        label: 'Students',
        to: '/app/students',
        icon: GraduationCap,
        roles: ['SUPER_ADMIN', 'ADMIN', 'DIRECTOR', 'AUDITOR', 'UNIT_MANAGER', 'HOD', 'TEACHER', 'BURSAR', 'CASHIER'],
      },
      { label: 'Admissions', to: '/app/admissions', icon: ClipboardList, roles: ['SUPER_ADMIN', 'ADMIN', 'HOD'] },
      { label: 'Users', to: '/app/users', icon: Users, roles: ['SUPER_ADMIN', 'ADMIN'] },
    ],
  },
  {
    title: 'Academics',
    items: [
      { label: 'Departments', to: '/app/departments', icon: Building2, roles: ['SUPER_ADMIN', 'ADMIN', 'DIRECTOR', 'AUDITOR', 'UNIT_MANAGER', 'HOD'] },
      { label: 'Course catalog', to: '/courses', icon: BookOpen, roles: 'all' },
      { label: 'Manage courses', to: '/app/courses', icon: PenSquare, roles: ['SUPER_ADMIN', 'ADMIN', 'HOD', 'TEACHER'] },
      {
        label: 'Timetable & attendance',
        to: '/app/timetable',
        icon: CalendarCheck,
        roles: ['SUPER_ADMIN', 'ADMIN', 'DIRECTOR', 'AUDITOR', 'UNIT_MANAGER', 'HOD', 'TEACHER', 'STUDENT'],
      },
      {
        label: 'Assessments & grades',
        to: '/app/assessments',
        icon: Award,
        roles: ['SUPER_ADMIN', 'ADMIN', 'DIRECTOR', 'AUDITOR', 'UNIT_MANAGER', 'HOD', 'TEACHER', 'STUDENT'],
      },
    ],
  },
  {
    title: 'Finance',
    items: [
      {
        label: 'Finance',
        to: '/app/finance',
        icon: ReceiptText,
        roles: ['SUPER_ADMIN', 'ADMIN', 'DIRECTOR', 'AUDITOR', 'UNIT_MANAGER', 'BURSAR', 'CASHIER', 'STUDENT'],
      },
    ],
  },
]

export function navFor(profile: Profile | undefined): NavSection[] {
  if (!profile || (!profile.assignments.length && profile.role === null)) return []

  return NAV
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => item.roles === 'all' || hasRole(profile, ...item.roles)),
    }))
    .filter((section) => section.items.length > 0)
}

export function breadcrumbsForPath(pathname: string, pageTitle: string) {
  const sections = NAV.flatMap((section) =>
    section.items.map((item) => ({ section: section.title, item })),
  )
  const route = pathname.startsWith('/app/attendance/')
    ? '/app/timetable'
    : pathname
  const match = sections
    .filter(({ item }) => route === item.to || route.startsWith(`${item.to}/`))
    .sort((left, right) => right.item.to.length - left.item.to.length)[0]

  if (!match) return [{ label: 'Dashboard', to: '/app' }, { label: pageTitle }]
  if (match.item.to === '/app' && route === '/app') return [{ label: 'Dashboard' }]

  const breadcrumbs = [
    { label: 'Dashboard', to: '/app' },
    { label: match.section },
    { label: match.item.label, to: match.item.to },
  ]
  if (route !== match.item.to) breadcrumbs.push({ label: pageTitle })
  else breadcrumbs[breadcrumbs.length - 1] = { label: pageTitle }
  return breadcrumbs
}
