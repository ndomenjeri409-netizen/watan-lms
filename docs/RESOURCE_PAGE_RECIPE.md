# Resource page recipe

Compose list pages from explicit pieces; keep resource-specific data fetching and actions in the page.

1. Use `PageHeader` for the title, description, and primary action.
2. Keep search and filters in a toolbar. Include them in the query key and send them with the current `page` to the API.
3. Use `DataTable` for columns, row actions, loading, empty states, and server-side pagination. Give each row a stable ID.
4. Open create and edit forms in `Drawer`; use `FormField` for accessible labels, hints, and API validation errors.
5. Confirm destructive or archival actions in `Dialog`. Archive records rather than deleting them, and report mutation results with `useToast`.

`src/pages/Departments.tsx` is the reference implementation. The table and overlays remain ordinary components, not an implicit `ResourcePage` abstraction.
