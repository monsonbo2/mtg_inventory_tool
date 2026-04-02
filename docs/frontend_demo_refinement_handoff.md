# Frontend Demo Refinement Handoff

Use this note to continue frontend-only demo work in a clean local checkout.

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

## Implementation Plan

1. Add App-level UI state for:
   - `collectionView: "compact" | "detailed"`
   - `expandedItemId: number | null`
   - `activityOpen: boolean`
2. Upgrade the collection header in `frontend/src/components/OwnedCollectionPanel.tsx`
   to show:
   - inventory name
   - total rows
   - total cards
   - estimated value
   - `Compact` / `Detailed` toggle
   - `View Activity` button
3. Add a new compact row/list presentation as the default collection view
4. Keep `OwnedItemCard` as the `Detailed` mode
5. Reuse `AuditFeed` inside a new drawer component opened from `View Activity`
6. Remove the on-page audit panel from the main layout in `frontend/src/App.tsx`
7. Add tests for:
   - compact default view
   - view toggle behavior
   - one-row-at-a-time expansion
   - activity drawer open/close behavior
   - audit no longer appearing on the front page by default

## Validation

Run:

- `npm test -- --run`
- `npm run build`

## Helpful Files

- `frontend/src/App.tsx`
- `frontend/src/components/OwnedCollectionPanel.tsx`
- `frontend/src/components/OwnedItemCard.tsx`
- `frontend/src/components/AuditFeed.tsx`
- `docs/frontend_search_autocomplete_checklist.md`
