# Frontend Source

The frontend is a Vite + React + TypeScript app. It treats the backend as an
HTTP service through `api.ts`; do not import Python runtime code from here.

## File Map

- `App.tsx`: application shell and top-level state wiring.
- `api.ts`: browser-facing HTTP client helpers.
- `downloadHelpers.ts`: browser download helpers for API text responses such
  as CSV exports.
- `inventoryCapabilities.ts`: policy-named helpers for readable, writable,
  transfer, export, and share-management affordances.
- `types.ts`: TypeScript mirrors of the app-facing API contract.
- `components/`: presentational and workflow components.
- `hooks/`: reusable state and API orchestration hooks.
- `styles.css`: the global CSS manifest.
- `styles/`: ordered global CSS buckets.

## Style Structure

`styles.css` is the explicit cascade entrypoint. Keep `base.css` and
`layout.css` first, keep `responsive.css` last, and add new feature styles near
the owning surface instead of recreating a broad catch-all file.

Current buckets:

- `base.css`: root tokens, document reset, focus and screen-reader utilities.
- `layout.css`: app shell, hero, and workspace grid layout.
- `panels.css`: shared panel headings, hints, and grid shells.
- `status-feedback.css`: status pills, row status labels, and feedback colors.
- `search.css`: search panel, autocomplete, search workspace, quick-add, and
  printing/language controls.
- `import-dialog.css`: import triggers, menus, preview, target, and resolution
  dialog states.
- `inventory-sidebar.css`: collection selector, create controls, and inventory
  switcher.
- `sticky-workspace-controls.css`: sticky top controls and their dropdowns.
- `forms-buttons.css`: shared fields, inputs, form sections, and buttons.
- `cards.css`: card shells, thumbnails, tags, owned cards, and compact rows.
- `collection-panel.css`: collection summary, view toggles, pagination, and
  collection search.
- `inventory-table.css`: table toolbar, filters, bulk tray, transfer tray, and
  table rows.
- `overlays.css`: modal shell, activity drawer, and audit feed cards.
- `empty-states.css`: panel empty/loading/error state visuals.

Feature-local media queries can stay in the owning file when that preserves the
current cascade. Use `responsive.css` for broad breakpoint overrides that span
multiple surfaces.
