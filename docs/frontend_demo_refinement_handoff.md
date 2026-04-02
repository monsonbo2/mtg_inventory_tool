# Frontend Demo Refinement Handoff

Use this note to continue frontend-only demo work in a clean local checkout.
This file is intended to be decision-complete for the next implementation pass.

## Worktree And Branch

- Work from `/home/boydm9/inventory_tool2_frontend`
- Branch: `frontend-demo-refinement`
- Do not use `/home/boydm9/inventory_tool2` for frontend work in the next
  session; that original checkout is the shared backend-facing worktree

## Current State

- Frontend autocomplete is implemented and committed in `de6cafb`:
  `Add frontend search autocomplete`
- The autocomplete checklist is committed in `e7f128a`:
  `Add frontend autocomplete checklist`
- Backend support for owned-row allowed finishes is present in `b44e227`
- Demo seed data was updated to use real card art in `f4fb2e5`
- The frontend worktree is currently clean and ready for the next pass

## Next Objective

Refine the demo layout so the main page feels like an inventory workspace:

1. Make the inventory display default to a compact row view
2. Keep the current richer card layout as an alternate `Detailed` mode
3. Move the audit feed off the front page into a right-side drawer

## Locked Product Decisions

- Compact view is the default every time the app loads
- Detailed view reuses the current rich card layout as much as possible
- Activity lives in a right-side drawer, not on the front page
- Compact editing uses one expanded row at a time
- Keep the existing one-field-save mutation model
- Do not add backend/API changes for this pass

## Implementation Summary

The page should emphasize three things:

1. choose an inventory
2. search/add cards
3. scan and edit what is already in the inventory

The left sidebar remains inventory-only. The main content column should contain
the search/add panel and a collection panel. Audit activity should no longer be
rendered on the page by default.

## Detailed Implementation Plan

### 1. App-level state and layout wiring

Add the following UI state in `frontend/src/App.tsx`:

- `collectionView: "compact" | "detailed"` with default `"compact"`
- `expandedItemId: number | null`
- `activityOpen: boolean`

Keep all three as local UI state only. Do not persist them to local storage or
the URL in this pass.

App responsibilities after the refactor:

- Continue owning inventory, owned-row, audit, and search data fetching
- Continue owning mutation handlers
- Stop rendering `AuditFeed` in the default sidebar stack
- Pass audit data into a new drawer surface instead
- Pass collection-view state and handlers into `OwnedCollectionPanel`

### 2. Main page structure

Keep:

- `InventorySidebar` in the left column
- `SearchPanel` at the top of the main content column

Change:

- Remove the on-page `AuditFeed` from the left column
- Make `OwnedCollectionPanel` the primary lower-half workspace surface
- Add a right-side drawer component for activity instead of the current in-page
  audit panel

The page should read as:

- left: inventory scope and selected-inventory context
- main: search/add and collection workspace
- overlay/drawer: activity when explicitly opened

### 3. Collection header behavior

Upgrade `frontend/src/components/OwnedCollectionPanel.tsx` so the collection
header includes:

- inventory name
- total rows
- total cards
- estimated value
- `Compact` / `Detailed` toggle
- `View Activity` button
- existing view-status pill

Behavior:

- `Compact` is active by default
- switching views does not refetch data
- switching views does not clear notices or reset the selected inventory
- `View Activity` is disabled when no inventory is selected

### 4. Compact default collection view

Add a new compact row/list presentation as the default collection mode.

Recommended split:

- `CompactInventoryList`
- `CompactInventoryRow`

Each collapsed row should show:

- thumbnail
- card name
- set name or set code + collector number
- quantity
- finish
- location
- estimated value
- a clear `Edit` or expand affordance

Visual structure:

- left: thumbnail + identity
- middle: compact metadata chips / labels
- right: quantity, value, and expand affordance

Compact rows should be scan-friendly, not spreadsheet-like. This should feel
denser than the current detailed card layout, but still visually readable.

### 5. Compact row editing

Editing in compact mode should happen inline.

Rules:

- only one row may be expanded at a time
- opening a row closes any previously open row
- clicking the open row’s expand control closes it

Expanded content should include:

- quantity editor
- finish editor
- location editor
- tags editor
- notes editor
- delete action
- saved / unsaved / saving status text

Mutation behavior:

- keep the current one-field-save model
- reuse the existing patch/delete handlers from `App.tsx`
- keep finish compatibility handling exactly as it works today
- do not invent a multi-field draft submit flow

The compact expanded editor should reuse as much logic as practical from the
current row-editing behavior, but the presentation can be new.

### 6. Detailed alternate view

Keep the current rich card-based presentation as the `Detailed` mode.

Rules:

- reuse `OwnedItemCard` as much as possible
- do not redesign detailed mode in this pass
- detailed mode is now the optional inspection layout, not the default

The goal is to preserve current functionality while changing the default
presentation, not to rework the detailed card UI.

### 7. Activity drawer

Create a right-side drawer component and render `AuditFeed` inside it.

Recommended split:

- `ActivityDrawer`
- existing `AuditFeed` reused inside the drawer body

Drawer behavior:

- opens from `View Activity`
- closes via close button
- closes via outside click
- closes via `Escape`
- overlays the page on desktop
- becomes full-width on narrow screens

Data behavior:

- reuse the already-loaded `auditEvents`, `viewStatus`, `viewError`, and
  selected inventory data
- do not add a second audit fetch path
- do not change audit API usage in this pass

### 8. Empty, loading, and error states

Preserve the current collection-state logic in both view modes:

- no inventory selected
- loading with no rows
- error with no rows
- empty selected inventory
- loaded populated inventory

Also preserve the current audit empty/loading/error behavior inside the drawer.

### 9. Styling and responsive behavior

Add CSS for:

- compact collection header controls
- view toggle
- compact row list
- compact expanded editor section
- right-side activity drawer
- mobile drawer behavior

Responsive expectations:

- compact rows remain readable on smaller widths
- row metadata may wrap or collapse, but should not become a raw table
- activity drawer should become nearly full-width on mobile
- the main page should not depend on the audit panel being visible

## Internal Interface Changes

No backend/API changes are needed.

Internal frontend changes expected:

- `OwnedCollectionPanel` will need additional props for:
  - `collectionView`
  - `onCollectionViewChange`
  - `expandedItemId`
  - `onExpandedItemChange`
  - `onOpenActivity`
- `App.tsx` will need to own and pass those props
- `AuditFeed` should remain a reusable, data-driven component
- New UI components will likely be added for:
  - compact collection list/row
  - activity drawer
  - collection header controls if needed

## Test Plan

Add or update UI tests to cover:

- compact mode is the default on initial render
- `Compact` / `Detailed` toggle switches the presentation without refetching
- one compact row expands at a time
- compact-row inline edits still use the existing mutation/notice flow
- `View Activity` opens the activity drawer
- activity drawer closes on close button
- activity drawer closes on outside click
- activity drawer closes on `Escape`
- audit is no longer rendered on the page by default

Run:

- `npm test -- --run`
- `npm run build`

## Helpful Files

- `frontend/src/App.tsx`
- `frontend/src/components/OwnedCollectionPanel.tsx`
- `frontend/src/components/OwnedItemCard.tsx`
- `frontend/src/components/AuditFeed.tsx`
- `frontend/src/components/InventorySidebar.tsx`
- `docs/frontend_search_autocomplete_checklist.md`

## Defaults Chosen

- Compact is the default view every load
- Detailed reuses the current richer card UI
- Activity uses a right-side drawer
- Only one compact row expands at a time
- No backend changes, URL state, or persistence in this pass
