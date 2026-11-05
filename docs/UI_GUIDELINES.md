# UI Guidelines

Use these conventions for new pages and when extending existing UI. The UI foundation plan is the source of truth for the shared shell, design tokens, and available primitives.

## Page structure

- Render authenticated pages inside `AppShell`.
- Start each page with `PageHeader`, including a clear title and a short description when useful.
- Follow with an optional filter/action bar and content rendered as a `DataTable` or cards from `src/components/ui`.
- Keep page-specific layout in Tailwind utility classes and shared design tokens. Do not add ad-hoc CSS or inline color values.

## Forms and actions

- Use a `Drawer` for create and edit forms. Use React Hook Form with Zod for form state and validation.
- Use a confirm `Dialog` before destructive actions. Make the consequence and action explicit.
- Use shared `Button`, form controls, and `useToast` for consistent feedback.
- Keep authorization enforcement on the backend; hiding a control in the frontend is only a usability measure.

## Data states and pagination

- Every data view must handle loading, empty, and error states. Use `Skeleton`, `EmptyState` with a relevant action, and `ErrorState` with retry behavior where retry is possible.
- Do not show invented or sample business data in shipped UI. Prefer a truthful unavailable/empty state until an API provides real data.
- Lists should use server-side pagination and wire search and ordering to the API. Reuse the typed `DataTable<T>` where it fits.
- Keep API failures visible and actionable; do not silently replace errors with empty results.

## Visual and responsive conventions

- Use icons from `lucide-react`.
- Use the design tokens in `src/index.css` for brand, surface, border, text, and status colors. Avoid hard-coded colors in components.
- Use the Tailwind spacing scale and shared component variants rather than one-off styles.
- Design mobile-first. Tables must scroll horizontally or switch to cards below 640px. Interactive touch targets should be at least 44px where practical.
- Maintain keyboard access, visible focus, semantic labels, and appropriate ARIA attributes.
- Write user-facing text in English and pass it through the `t()` helper in `src/lib/i18n.ts`. The current helper is an identity stub; replace its implementation with a localization provider when translations are introduced.

## Example

```tsx
import { PageHeader } from '../app/PageHeader'
import { t } from '../lib/i18n'

export function ExamplePage() {
  return (
    <section className="space-y-6">
      <PageHeader title={t('Example')} description={t('A short explanation of this page.')} />
      {/* Use shared data and state components for the page content. */}
    </section>
  )
}
```
