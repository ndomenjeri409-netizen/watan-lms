> SUPERSEDED by MASTER_GUIDE.md; do not follow.

# UI Foundation Plan — App Shell, Design System, Dashboard

Do this **before building more pages**. Every page built on the plain top-nav layout would need restyling later; pages built on the shell inherit the new look automatically.

**Target look:** a modern admin dashboard like the reference (left sidebar, top bar with search, stat cards, charts, lists/tables), in Watan's own identity. We recreate the *layout and patterns*; we do **not** copy the reference template's HTML, CSS or images (commercial templates are normally licensed per project, and copying would drag in jQuery-era code).

**What to copy vs. avoid from the reference**
| Copy | Avoid |
|---|---|
| Sidebar + top bar structure, search box, theme toggle, notification bell, avatar menu | Floating round buttons that overlap the sidebar menu |
| Stat cards with a label, big number and small trend/progress | Hard-coded demo numbers (never ship fake data; use skeletons until the API returns real values) |
| Card-based dashboard: chart + lists | Three alternate dashboards and a very long menu; group items by task and by role instead |
| Soft cards, generous spacing, clear hierarchy | Small low-contrast grey text; keep WCAG AA (4.5:1) |

## Rules for Copilot
1. Work step by step; stop after each step with the check result.
2. **All pages use the shell and `src/components/ui/*`.** No ad-hoc CSS, no inline colours; only design tokens.
3. Navigation filtering by role is **UX only**; the backend still enforces access.
4. Don't add libraries beyond those named here.
5. No hard-coded demo data in shipped components. Use loading, empty and error states.

---

## Step 1 — Dependencies and tokens

```bash
cd frontend
npm i class-variance-authority clsx tailwind-merge recharts @fontsource-variable/inter
npm i @radix-ui/react-dialog @radix-ui/react-dropdown-menu @radix-ui/react-tabs @radix-ui/react-tooltip @radix-ui/react-slot
```
(You may instead use the `shadcn/ui` CLI for Tailwind v4 + Vite to generate Radix-based components into `src/components/ui`. Follow its current docs. The code is then yours; no runtime dependency on a template.)

- [ ] `src/lib/cn.ts`: `export const cn = (...i: ClassValue[]) => twMerge(clsx(i));`
- [ ] Import the font in `main.tsx`: `import '@fontsource-variable/inter';` (bundled; no external font requests).
- [ ] `src/index.css`: define tokens once, light and dark.

```css
@import "tailwindcss";
@custom-variant dark (&:where([data-theme="dark"], [data-theme="dark"] *));

@theme {
  --font-sans: "Inter Variable", ui-sans-serif, system-ui, sans-serif;
  --radius-card: 0.875rem;
  --color-brand: #c9a227;          /* gold primary */
  --color-brand-fg: #111111;       /* text on gold (AA) */
  --color-sidebar: #0f1115;
  --color-sidebar-fg: #cbd0d8;
  --color-sidebar-active: #1c2027;
  --color-success: #15803d; --color-warning: #b45309; --color-danger: #b91c1c; --color-info: #1d4ed8;
}
:root {
  --bg: #f6f7f9; --surface: #ffffff; --border: #e5e7eb;
  --text: #111827; --muted: #5b6472;
}
:root[data-theme="dark"] {
  --bg: #0b0d10; --surface: #14171c; --border: #262b33;
  --text: #f3f4f6; --muted: #9aa3b2;
}
body { background: var(--bg); color: var(--text); font-family: var(--font-sans); }
@media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
```
Check contrast for brand-on-surface combinations; adjust the gold if any text pair falls below 4.5:1.

- [ ] Theme logic `src/lib/theme.ts`: `getTheme()` (localStorage `theme` or `prefers-color-scheme`), `setTheme()` sets `document.documentElement.dataset.theme`. Run once before render in `main.tsx` to avoid a flash.

**Check:** page background and text change when `data-theme="dark"` is toggled in dev tools.

---

## Step 2 — UI primitives (`src/components/ui/`)

Build each with variants via `cva`, keyboard accessible, with visible focus rings (`focus-visible:ring-2`).

- [ ] `Button` (primary, secondary, ghost, danger; sm/md/lg; `loading` prop; `asChild`)
- [ ] `Card`, `CardHeader`, `CardTitle`, `CardContent`
- [ ] `StatCard` (`label`, `value`, optional `hint`, optional `progress` 0–100, optional `trend`; **`loading` and `error` states**)
- [ ] `Badge` (neutral, success, warning, danger, info)
- [ ] `Input`, `Select`, `Textarea`, `FormField` (label, hint, error message, `aria-describedby`)
- [ ] `Avatar` (image or initials fallback)
- [ ] `DropdownMenu` (Radix), `Tooltip`, `Tabs`
- [ ] `Dialog` and `Drawer` (side sheet for create/edit forms)
- [ ] `Skeleton`, `EmptyState` (icon, title, description, action), `ErrorState` (message + retry)
- [ ] `Toast` (simple provider + `useToast`)
- [ ] `DataTable<T>`: typed `columns`, `rows`, `loading`, `emptyState`, sortable headers, optional row selection, row actions menu, sticky header, horizontal scroll on small screens; **server-side** `page`, `pageSize`, `total`, `onPageChange` (matches the DRF pagination).
- [ ] `Pagination`

**Check:** a temporary `/app/_ui` route renders every component in light and dark mode (remove or guard behind `import.meta.env.DEV` afterwards).

---

## Step 3 — Navigation config

`src/app/navigation.ts` (single source of truth):

```ts
import type { Role } from '../features/me/roles';   // 'SUPER_ADMIN' | 'ADMIN' | 'DIRECTOR' | 'HOD' | 'TEACHER' | 'BURSAR' | 'STUDENT'

export type NavItem = { label: string; to: string; icon: LucideIcon; roles: Role[] | 'all'; badge?: 'pending' };
export type NavSection = { title: string; items: NavItem[] };

export const NAV: NavSection[] = [
  { title: 'Overview', items: [
    { label: 'Dashboard', to: '/app', icon: LayoutDashboard, roles: 'all' },
    { label: 'My profile', to: '/app/me', icon: User, roles: 'all' },
  ]},
  { title: 'People', items: [
    { label: 'Students', to: '/app/students', icon: GraduationCap, roles: ['SUPER_ADMIN','ADMIN','DIRECTOR','HOD','TEACHER','BURSAR'] },
    { label: 'Admissions', to: '/app/admissions', icon: ClipboardList, roles: ['SUPER_ADMIN','ADMIN','HOD'] },
    { label: 'Users', to: '/app/users', icon: Users, roles: ['SUPER_ADMIN','ADMIN'] },
  ]},
  { title: 'Academics', items: [
    { label: 'Departments', to: '/app/departments', icon: Building2, roles: ['SUPER_ADMIN','ADMIN','DIRECTOR','HOD'] },
    { label: 'Course catalog', to: '/app/courses', icon: BookOpen, roles: 'all' },
    { label: 'Manage courses', to: '/app/courses/manage', icon: PenSquare, roles: ['SUPER_ADMIN','ADMIN','HOD','TEACHER'] },
    { label: 'Timetable & attendance', to: '/app/timetable', icon: CalendarCheck, roles: 'all' },
    { label: 'Assessments & grades', to: '/app/assessments', icon: Award, roles: 'all' },
  ]},
  { title: 'Finance', items: [
    { label: 'Fees & invoices', to: '/app/finance', icon: Wallet, roles: ['SUPER_ADMIN','ADMIN','DIRECTOR','BURSAR','STUDENT'] },
  ]},
  { title: 'Administration', items: [
    { label: 'Settings', to: '/app/settings', icon: Settings, roles: ['SUPER_ADMIN','ADMIN'] },
    { label: 'Audit log', to: '/app/audit', icon: ScrollText, roles: ['SUPER_ADMIN','ADMIN'] },
  ]},
];

export const navFor = (role: Role | null) =>
  NAV.map(s => ({ ...s, items: s.items.filter(i => i.roles === 'all' || (role && i.roles.includes(role))) }))
     .filter(s => s.items.length > 0);
```
Adjust the routes to match the routes you already built; keep the labels from your current top menu. Users with `role === null` see no nav, only the "awaiting approval" screen.

**Check:** a unit test per role asserts which items appear (STUDENT does not see Users or Audit log; BURSAR sees Finance; DIRECTOR sees no "Manage courses").

---

## Step 4 — App shell (`src/app/AppShell.tsx`)

Structure: `<a class="skip-link">Skip to content</a>`, `<Sidebar/>`, `<div><Topbar/><main id="main"><Outlet/></main></div>`.

- [ ] **Sidebar** (dark surface from tokens): brand/logo block, grouped sections with small uppercase titles, items with icon + label, active state from the router (`aria-current="page"`), collapsible to icon-only on desktop (persist in `localStorage`), and a **slide-over drawer under 1024 px** with a backdrop and focus trap (Radix Dialog). Footer area: user mini-card.
- [ ] **Topbar:** menu button (mobile and collapse toggle), search input (stub: opens a "Search coming soon" popover for now; becomes the command palette `Ctrl/Cmd+K` later), theme toggle, notifications bell (stub with count badge from a prop, hidden when 0), user menu (avatar, name, role badge, "My profile", "Sign out").
- [ ] **PageHeader** (`title`, `description`, `actions`, optional breadcrumbs) used at the top of every page.
- [ ] Content container: `max-w-7xl`, consistent padding, spacing between cards.
- [ ] Replace the current top-nav layout; keep the existing auth guard and routes.
- [ ] "Waking up" banner (from Sprint 0) moves into the shell as a slim top notice.

**Check:** at 1280 px: sidebar visible; at 390 px: sidebar hidden and opens as a drawer; keyboard Tab order is logical; Esc closes the drawer.

---

## Step 5 — Dashboard home (`/app`)

A role-aware home that matches the reference's *pattern* without fake data:

- [ ] Top row of **4 `StatCard`s**, chosen per role (config map). Until the reporting endpoint exists they show **loading skeletons, then an "Available soon" empty hint**, never made-up numbers. Planned sources: STUDENT (attendance %, fee balance, next assessment, unread announcements); TEACHER (today's classes, submissions to grade); HOD (pending enrollments, grade approvals); BURSAR (collected today, overdue invoices); DIRECTOR/ADMIN (students, courses, fees collected, attendance rate).
- [ ] Main area: a `Card` with a **Recharts** chart wrapper (`ChartCard`) with loading/empty states (used later for income vs expense and enrollment trends).
- [ ] Side/lower area: two list cards ("Recent activity", "Needs your attention") using the same `EmptyState` until data exists.
- [ ] **Quick actions** per role (buttons linking to existing pages).
- [ ] SUPER_ADMIN only: a **setup checklist** card (Firebase auth OK, DB reachable via `/readyz`, storage configured), useful during rollout.

**Check:** each role sees a sensible dashboard; no hard-coded numbers anywhere (`grep` for large literals in the dashboard folder).

---

## Step 6 — Fix the profile page

- [ ] Name fallback: `display_name` → Firebase `displayName` → email local-part (never show "—" for the name).
- [ ] Layout: avatar with initials, name, email, role `Badge`, and an "Awaiting approval" notice when `role` is null.
- [ ] Use `Card` and `PageHeader` from the new components.

---

## Step 7 — Page conventions for all future pages (`docs/UI_GUIDELINES.md`)

Document and enforce:
1. Page = `PageHeader` + optional filter bar + `DataTable` or cards.
2. Create/edit in a **Drawer** form (React Hook Form + Zod); destructive actions in a confirm `Dialog`.
3. Every data view has **loading (skeleton), empty (with action) and error (with retry)** states.
4. Lists are server-paginated with `search` and `ordering` wired to the API.
5. Icons from `lucide-react` only; colours from tokens only; spacing on the Tailwind scale.
6. Mobile first: tables scroll horizontally or collapse to cards below 640 px; touch targets ≥ 44 px.
7. Text in English, wrapped for later i18n (use a `t()` helper stub now).

Add to `.github/copilot-instructions.md`: *"All new pages must use AppShell, PageHeader and components from src/components/ui. No ad-hoc CSS or inline colours. Follow docs/UI_GUIDELINES.md."*

---

## Step 8 — Tests and checks

- [ ] Vitest + Testing Library: `navFor` per role; Sidebar renders grouped items and marks the active route; mobile drawer opens/closes; `StatCard` shows skeleton, value and error states; `DataTable` shows empty state and calls `onPageChange`.
- [ ] Optional: `vitest-axe` smoke test on the shell and dashboard.
- [ ] `npm run lint && npm run typecheck && npm test && npm run build` pass; fix the two existing lint warnings in this step.

---

## Definition of Done
- [ ] Sidebar + top bar shell replaces the top-nav layout on all existing pages.
- [ ] Light and dark themes work, with no flash on load.
- [ ] Role-filtered navigation verified by tests.
- [ ] Dashboard and profile pages use the new components; no fake data.
- [ ] `/app/_ui` showcase (dev only) shows all primitives.
- [ ] Mobile (390 px) and desktop (1280 px) screenshots compared with the reference for layout feel.
- [ ] `docs/UI_GUIDELINES.md` and the Copilot instruction line committed.

## Prompt to give Copilot (agent mode)
```
Read docs/UI_FOUNDATION_PLAN.md. Implement Step 1 only (dependencies and design tokens).
Do not restyle existing pages yet. When done, run the Step 1 check, show the result, and stop.
```
Then repeat with Step 2, Step 3, and so on, committing after each step.
