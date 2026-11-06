import type { Role } from '../features/me/roles'

export interface DashboardStat {
  key: string
  label: string
}

export interface DashboardAction {
  label: string
  to: string
}

const managementStats = [
  { key: 'departments', label: 'Departments' },
  { key: 'programs', label: 'Programs' },
  { key: 'courses', label: 'Published courses' },
  { key: 'students', label: 'Active students' },
  { key: 'pending_applications', label: 'Pending applications' },
  { key: 'pending_enrollments', label: 'Pending enrollments' },
]

const dashboardByRole: Record<Role, { stats: DashboardStat[]; actions: DashboardAction[] }> = {
  SUPER_ADMIN: {
    stats: [...managementStats, { key: 'users', label: 'Active users' }, { key: 'staff', label: 'Staff members' }],
    actions: [
      { label: 'Manage users', to: '/app/users' },
      { label: 'View students', to: '/app/students' },
      { label: 'Manage courses', to: '/app/courses' },
      { label: 'Review admissions', to: '/app/admissions' },
    ],
  },
  ADMIN: {
    stats: [...managementStats, { key: 'users', label: 'Active users' }, { key: 'staff', label: 'Staff members' }],
    actions: [
      { label: 'Manage users', to: '/app/users' },
      { label: 'View students', to: '/app/students' },
      { label: 'Manage courses', to: '/app/courses' },
      { label: 'Review admissions', to: '/app/admissions' },
    ],
  },
  DIRECTOR: {
    stats: managementStats,
    actions: [
      { label: 'View students', to: '/app/students' },
      { label: 'Departments', to: '/app/departments' },
      { label: 'Open timetable', to: '/app/timetable' },
      { label: 'Assessments & grades', to: '/app/assessments' },
    ],
  },
  AUDITOR: {
    stats: managementStats,
    actions: [
      { label: 'View students', to: '/app/students' },
      { label: 'Departments', to: '/app/departments' },
      { label: 'Open timetable', to: '/app/timetable' },
      { label: 'Assessments & grades', to: '/app/assessments' },
    ],
  },
  UNIT_MANAGER: {
    stats: managementStats,
    actions: [
      { label: 'View students', to: '/app/students' },
      { label: 'Departments', to: '/app/departments' },
      { label: 'Manage courses', to: '/app/courses' },
      { label: 'Open timetable', to: '/app/timetable' },
    ],
  },
  HOD: {
    stats: managementStats,
    actions: [
      { label: 'Review admissions', to: '/app/admissions' },
      { label: 'Departments', to: '/app/departments' },
      { label: 'Manage courses', to: '/app/courses' },
      { label: 'Assessments & grades', to: '/app/assessments' },
    ],
  },
  TEACHER: {
    stats: [
      { key: 'courses', label: 'Published courses' },
      { key: 'assessments', label: 'Published assessments' },
      { key: 'submissions_to_grade', label: 'Submissions to grade' },
    ],
    actions: [
      { label: 'Open timetable', to: '/app/timetable' },
      { label: 'Manage courses', to: '/app/courses' },
      { label: 'Assessments & grades', to: '/app/assessments' },
      { label: 'View students', to: '/app/students' },
    ],
  },
  BURSAR: {
    stats: [],
    actions: [
      { label: 'View students', to: '/app/students' },
      { label: 'Course catalog', to: '/courses' },
    ],
  },
  CASHIER: {
    stats: [],
    actions: [
      { label: 'View students', to: '/app/students' },
      { label: 'Course catalog', to: '/courses' },
    ],
  },
  STUDENT: {
    stats: [{ key: 'courses', label: 'Your active courses' }],
    actions: [
      { label: 'Course catalog', to: '/courses' },
      { label: 'Open timetable', to: '/app/timetable' },
      { label: 'Assessments & grades', to: '/app/assessments' },
    ],
  },
}

export function dashboardFor(role: Role) {
  return dashboardByRole[role]
}
