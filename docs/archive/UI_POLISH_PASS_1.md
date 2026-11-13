> SUPERSEDED by MASTER_GUIDE.md; do not follow.

# UI Polish Pass 1 (revised) — exact brand palette + fixes from the screenshots

Revision: the UI now uses **exactly six brand colours**. Everything else is derived from them by opacity or mixing, never by adding new hex values.

| Token | Hex | Role |
|---|---|---|
| `ink` | `#0D0E12` | App background (dark), sidebar, top bar, text on light surfaces, text on amber |
| `panel` | `#181A22` | Cards, drawers, dialogs, tables (dark); active nav item background |
| `amber` | `#FFAE1B` | **Primary**: main buttons, active-nav indicator, focus ring, progress, key chart series |
| `violet` | `#8F41FF` | **Secondary accent**: selected states, info badges, second chart series, secondary highlights |
| `white` | `#FFFFFF` | Text on dark, card surface in light theme |
| `mist` | `#A0A5B5` | Muted text on dark, sidebar text, dividers, third chart series |

Work in order: **Section 0 first** (palette), then A to F. Stop after each section, run its check, commit.

## Rules for Copilot
1. Change only what each task says. Don't redesign the shell.
2. **No hex, `rgb()` or Tailwind default palette classes (`bg-gray-500`, `text-red-600`, …) anywhere except the `@theme` block in `src/index.css`.** Components use semantic names only (`bg-surface`, `text-fg`, `bg-primary`).
3. No fake numbers anywhere. A card with no real data is hidden or replaced.
4. Follow `docs/UI_GUIDELINES.md`.

---

## 0. Palette, theming and enforcement

### 0.1 Contrast findings (these drive the usage rules)
Approximate WCAG ratios computed from the hex values; re-check with a contrast tool before sign-off.

| Pair | Ratio | Verdict |
|---|---|---|
| White on `ink` / on `panel` | ≈ 19 / 17 : 1 | Excellent |
| `mist` on `ink` / on `panel` | ≈ 7.8 / 7.1 : 1 | Good (muted text on dark) |
| `amber` on `ink` / on `panel` | ≈ 10.4 / 9.4 : 1 | Excellent (amber text and icons on dark) |
| `ink` on `amber` | ≈ 10.4 : 1 | Excellent → **button text on amber is always `ink`** |
| White on `amber` | ≈ 1.9 : 1 | **Fails** → never white on amber |
| White on `violet` | ≈ 4.8 : 1 | Passes AA for normal text (barely) |
| `violet` on `ink` / on `panel` | ≈ 4.0 / 3.6 : 1 | **Fails for small text**; OK for large text, icons, borders, fills |
| `mist` on white | ≈ 2.5 : 1 | **Fails** → never use `mist` as text in the light theme |
| `amber` on white | ≈ 1.9 : 1 | **Fails** → never amber text or thin amber lines on white |

Resulting usage rules:
- **Violet is a fill/accent colour, not a text colour on dark.** Use it for badges (with white text), selected rows, chart series, icon accents, borders. Links on dark are **amber** or white-underlined.
- **Light theme:** text is `ink`; muted text is a mix of `ink` and white (not `mist`); amber is used as a fill with `ink` text, or as an indicator bar; the focus ring is `ink`, not amber.
- **The palette has no success or danger colour.** Recommended exception: add exactly two functional status colours, `success` and `danger`, used only for paid/approved and overdue/rejected, always paired with an icon and a label. If you want a strictly six-colour UI, drop them and encode status with icon + text + amber/violet/mist instead (less glanceable for money and overdue states). Decide before Section 0 is implemented; the file assumes the recommended exception.

### 0.2 Default theme
The palette is dark-first. **Default theme = dark.** Keep the theme toggle; remember the user's choice; first visit uses dark regardless of OS setting. The sidebar is `ink` in both themes.

### 0.3 Tokens (`src/index.css`)
Only the `@theme` block may contain hex values.

```css
@import "tailwindcss";
@custom-variant dark (&:where([data-theme="dark"], [data-theme="dark"] *));

@theme {
  --color-*: initial;                       /* removes Tailwind's default palette */
  --color-transparent: transparent;
  --color-current: currentColor;

  --color-ink: #0D0E12;
  --color-panel: #181A22;
  --color-amber: #FFAE1B;
  --color-violet: #8F41FF;
  --color-white: #FFFFFF;
  --color-mist: #A0A5B5;

  /* functional status colours (the only non-brand hexes; see 0.1) */
  --color-success: #22C55E;
  --color-danger: #EF4444;

  --font-sans: "Inter Variable", ui-sans-serif, system-ui, sans-serif;
  --radius-card: 0.875rem;
}

/* Semantic theme variables */
:root, :root[data-theme="dark"] {
  color-scheme: dark;
  --bg: var(--color-ink);
  --surface: var(--color-panel);
  --surface-2: color-mix(in srgb, var(--color-white) 6%, var(--color-panel));
  --border: color-mix(in srgb, var(--color-white) 10%, var(--color-ink));
  --text: var(--color-white);
  --muted: var(--color-mist);
  --ring: var(--color-amber);
  --scroll-thumb: color-mix(in srgb, var(--color-mist) 35%, var(--color-ink));
  --scroll-thumb-hover: color-mix(in srgb, var(--color-mist) 55%, var(--color-ink));
}
:root[data-theme="light"] {
  color-scheme: light;
  --bg: color-mix(in srgb, var(--color-mist) 10%, var(--color-white));
  --surface: var(--color-white);
  --surface-2: color-mix(in srgb, var(--color-mist) 12%, var(--color-white));
  --border: color-mix(in srgb, var(--color-mist) 40%, var(--color-white));
  --text: var(--color-ink);
  --muted: color-mix(in srgb, var(--color-ink) 62%, var(--color-white));   /* verify >= 4.5:1 */
  --ring: var(--color-ink);
  --scroll-thumb: color-mix(in srgb, var(--color-mist) 70%, var(--color-white));
  --scroll-thumb-hover: var(--color-mist);
}
:root {
  --primary: var(--color-amber);
  --primary-fg: var(--color-ink);
  --primary-hover: color-mix(in srgb, var(--color-white) 14%, var(--color-amber));
  --primary-active: color-mix(in srgb, var(--color-ink) 14%, var(--color-amber));
  --accent: var(--color-violet);
  --accent-fg: var(--color-white);

  --sidebar-bg: var(--color-ink);
  --sidebar-fg: var(--color-mist);
  --sidebar-fg-active: var(--color-white);
  --sidebar-active-bg: var(--color-panel);
  --sidebar-border: color-mix(in srgb, var(--color-white) 8%, var(--color-ink));
}

/* Semantic utilities: bg-app, bg-surface, text-fg, text-subtle, border-line, bg-primary ... */
@theme inline {
  --color-app: var(--bg);
  --color-surface: var(--surface);
  --color-surface-2: var(--surface-2);
  --color-line: var(--border);
  --color-fg: var(--text);
  --color-subtle: var(--muted);
  --color-primary: var(--primary);
  --color-primary-fg: var(--primary-fg);
  --color-accent: var(--accent);
  --color-accent-fg: var(--accent-fg);
  --color-sidebar: var(--sidebar-bg);
}

body { background: var(--bg); color: var(--text); font-family: var(--font-sans); }
:focus-visible { outline: 2px solid var(--ring); outline-offset: 2px; }
```
If your installed Tailwind v4 version resolves `@theme inline` differently, adapt the mechanics but keep the rule: **components only use semantic names; hex lives in one block.**

### 0.4 Component mapping (apply everywhere)
| Element | Style |
|---|---|
| Page / top bar | `bg-app`, bottom border `border-line` |
| Sidebar | `ink` always; text `mist`; hover = white at 6%; **active item = `panel` background, white text, 3 px amber indicator on the left** |
| Card, table, drawer, dialog | `bg-surface`, 1 px `border-line`, radius token |
| Primary button | `bg-primary text-primary-fg`, hover/active use the derived tokens |
| Secondary button | transparent, 1 px `border-line`, `text-fg`; hover `bg-surface-2` |
| Accent button (rare, e.g. "Upgrade", highlights) | `bg-accent text-accent-fg` |
| Destructive button | `bg-danger` with white text; confirmation dialog required |
| Badges | neutral = `mist` on `surface-2`; info/selected = violet fill + white text; warning = amber fill + `ink` text; success/danger = functional colours with icon + label |
| Inputs | `bg-surface-2` (dark) or `bg-surface` (light), `border-line`, focus ring per theme |
| Links | dark theme: amber (underline on hover); light theme: `ink` underlined |
| Charts | series order: amber, violet, mist, white (dark) / ink (light); always add labels or patterns, never rely on colour alone |
| Selected table row / tab underline | violet at 18% fill / amber underline (dark) or ink underline (light) |

### 0.5 Enforcement (so the palette stays precise)
- [ ] `scripts/check-colors.mjs` (run in `npm run lint` and CI): fail if any `.ts/.tsx/.css` file other than the `@theme` block in `src/index.css` contains a hex colour, `rgb(`/`hsl(`, or a Tailwind default-palette class matching `\b(bg|text|border|ring|fill|stroke|from|to|via)-(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}\b`.
  (With `--color-*: initial` those classes produce no colour anyway, but the check catches mistakes early.)
- [ ] A Vitest contrast test that reads the token values and asserts the **allowed** pairs from 0.1 meet their thresholds (4.5:1 normal text, 3:1 large text/UI), so a future token change can't silently break accessibility.
- [ ] Replace every existing hard-coded or old-token colour in the shell and pages (old gold `#c9a227` and any greys) with semantic classes.

**Check:** toggle dark/light on Dashboard, Departments, Profile: surfaces, text, buttons, focus rings and badges follow the table above; `npm run lint` passes the colour check; no `#`-colour appears outside `@theme`.

---

## A. Scrollbars (the mismatch you reported)

**Cause (most likely):** browsers draw native scrollbars from the page's `color-scheme`. The page was "light", so the dark sidebar showed a white scrollbar track. The tokens in 0.3 set `color-scheme` per theme; now style the scrollbars.

- [ ] Add (using tokens, no hex):
```css
html { scrollbar-gutter: stable; scrollbar-width: thin; scrollbar-color: var(--scroll-thumb) transparent; }

.sidebar-scroll {
  color-scheme: dark;                       /* sidebar is dark in both themes */
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: color-mix(in srgb, var(--color-mist) 35%, var(--color-ink)) transparent;
}
/* Fallback for older Safari (ignored where the standard properties are supported) */
.sidebar-scroll::-webkit-scrollbar { width: 8px; }
.sidebar-scroll::-webkit-scrollbar-track { background: transparent; }
.sidebar-scroll::-webkit-scrollbar-thumb { background: color-mix(in srgb, var(--color-mist) 35%, var(--color-ink)); border-radius: 8px; }
.sidebar-scroll::-webkit-scrollbar-thumb:hover { background: color-mix(in srgb, var(--color-mist) 55%, var(--color-ink)); }
```
- [ ] Apply `.sidebar-scroll` to **only the sidebar navigation list** (`min-h-0 flex-1`), keeping the brand block and user footer pinned.
- [ ] Apply the same thin-scrollbar style to tables, drawers and dialogs that scroll.
- [ ] Optional: soft top/bottom shadow on the sidebar list when it can scroll, so items cut off at the edge (like "Dashboard" in the admin screenshot) look intentional.

**Check:** no white strip beside the sidebar in either theme; page scrollbar matches the theme; no layout jump when the scrollbar appears.

---

## B. Shell corrections

- [ ] **Breadcrumb bug:** `/app/departments` shows "My profile / Departments". Root = **Dashboard**; middle crumb = nav section when useful (`Dashboard / Academics / Departments`). Derive breadcrumbs from `NAV`, not from the previous page.
- [ ] **Display name:** welcome heading, top bar and sidebar footer show `ndomenjeri409` (email prefix). Use `display_name`; when empty show a dismissible "Complete your profile" banner linking to a form (name, phone). Add `PATCH /api/v1/me` (syncs to Firebase `updateProfile`).
- [ ] **Shortcut hint:** show `Ctrl K` on Windows/Linux, `⌘ K` on macOS. The shortcut opens a "Search is coming soon" popover until the command palette exists.
- [ ] **Role labels:** one `roleLabel()` helper → "Super admin", "Teacher", "HOD" (not raw enum text); small `Badge` in the profile and user menu.
- [ ] **Sidebar on short screens:** role text in the user card is clipped in the teacher screenshot. Make the shell `h-dvh`; sidebar is a flex column (`brand` / `nav: flex-1 min-h-0` / `footer`); footer padding includes `env(safe-area-inset-bottom)`.
- [ ] **Icon-only buttons:** `aria-label` and tooltips on the collapse chevron (rotates when collapsed), theme toggle, etc. Collapsed sidebar shows item labels as tooltips.
- [ ] **Active nav item:** per 0.4 (panel background + 3 px amber indicator).

**Check:** breadcrumbs correct everywhere; names/roles read well; every icon button has an accessible name.

---

## C. Dashboards: stop showing a wall of "Available soon"

Problem: the admin home is four "Available soon" cards plus an empty chart.

- [ ] **Hide, don't announce.** A `StatCard` without data isn't rendered; if none have data, skip the row.
- [ ] **Real numbers that already exist:** backend `GET /api/v1/reports/overview` returns role-scoped counts for models that exist now (for example `{"users": 12, "departments": 5}`; keys for unbuilt modules are omitted). The UI renders one `StatCard` per key present.
- [ ] **Admin / Super admin home = "Getting started" checklist + quick actions** (computed from the counts): 1 Create departments · 2 Add programs and courses · 3 Invite teachers and staff · 4 Admit and enrol students · 5 Set up fee structures. Remove the empty "Activity overview" card until reporting exists. Progress bar in amber.
- [ ] **Teacher home = action lists:** **Today's schedule** (class, time, room, "Take attendance") and **Needs grading** (assessment, class, count). Each shows an `EmptyState` linking to where the data is created until the modules exist.
- [ ] Specify (build later): Student = next class, next deadline, fee balance, announcements; HOD = approval queues; Bursar = collected today, overdue invoices; Director = KPI row + trend chart.
- [ ] `StatCard` value: large number, skeleton bar while loading, retry link on error; never text like "Available soon" in the value slot.

**Check:** a fresh admin sees a useful checklist and real counts; no placeholder text; a teacher with no schedule sees guidance, not an empty chart.

---

## D. Departments page → the reference "list page" recipe

- [ ] **`ResourcePage` recipe** (components + docs, not magic): `PageHeader` (title, description, primary action top right) → toolbar (search, filters, result count) → `DataTable` → create/edit in a right-side `Drawer` → confirm `Dialog` for archive.
- [ ] Refactor Departments:
  - Primary **Add department** button in the header opens a Drawer (name, code).
  - Columns: Name, Code (monospace badge), Programs, Courses, Status, row actions (Edit, Archive).
  - Server-side `?search=` and `?page=`; focusable rows with hover (`surface-2`).
  - Toasts on success/error; field errors from the API shown inline.
- [ ] **Validation (backend + frontend):** `code` = 2–8 uppercase letters/digits, unique ignoring case; `name` unique ignoring case. DB `UniqueConstraint(Lower("code"))`; errors in the standard `{code, message, fields}` shape. The existing `T&T` is invalid; migrate it to a valid code such as `TT` (confirm with the institute). Check the spelling of "Languages Studies".
- [ ] **Archive, don't delete** (`archived_at`), hidden by default with "Show archived".
- [ ] All controls in a row share one height token (`h-10`); the current "Add department" button is taller than the inputs.

**Check:** add/edit/archive/search work through the drawer; invalid or duplicate codes show field-level errors.

---

## E. Quality gates

- [ ] Frontend tests: breadcrumb builder from `NAV`; `roleLabel`; `StatCard` hidden without data; checklist completion from counts; Departments drawer validation; sidebar nav list is the only scroll container; **palette contrast test** (0.5); colour-check script passes.
- [ ] Backend tests: `reports/overview` returns only existing keys and is role-scoped; department code validation and case-insensitive uniqueness; `PATCH /me` updates `display_name`.
- [ ] `npm run lint && npm run typecheck && npm test && npm run build`, `ruff`, `pytest` pass; regenerate `openapi.yaml` and `schema.d.ts`.
- [ ] Screenshot review at 1280 px and 390 px, dark and light, for Admin and Teacher.

## Prompt for Copilot (agent mode)
```
Read docs/UI_POLISH_PASS_1.md. Implement section 0 only (palette, tokens, theming, enforcement).
Do not change anything outside that section. Use only the six brand hex values plus the two
functional status colours in the @theme block. Run the Check, show the result, and stop.
```
Then repeat for A, B, C, D, E, committing after each section.
