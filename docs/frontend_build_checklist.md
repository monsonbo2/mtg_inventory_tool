# Frontend Build Checklist

This checklist captures the next frontend implementation pass for the local demo
webapp.

It is intentionally scoped to the current published HTTP contract in:

- `api_v1_contract.md`
- `frontend_handoff.md`
- `../contracts/openapi.json`
- `../contracts/demo_payloads/`

The checklist is split into work we can do now and follow-up work that depends
on backend request outcomes.

## Stage 1: Demo-Good Enough

- [ ] Confirm the full happy path is smooth:
  inventory selection, card search, add row, edit row, delete row, and audit
  refresh.
- [ ] Tighten loading, empty, and error states for each panel so the app never
  feels blank or ambiguous.
- [ ] Improve row-level busy states so save and delete actions clearly lock only
  the affected card.
- [ ] Refine the search and add panel so it is easier to scan and faster to use
  repeatedly.
- [ ] Refine the owned-row cards so pricing, metadata, and editable fields are
  easier to parse at a glance.
- [ ] Improve mobile and narrow-screen behavior for the sidebar, search results,
  and owned-row editor.
- [ ] Normalize success and error notices so all mutations report back in a
  consistent way.
- [ ] Add small UX safeguards for invalid quantity, blank fields, and
  destructive delete actions.

## Stage 2: Presentation Polish

- [ ] Break the current single-file UI into a few focused components so the next
  iteration is easier to maintain.
- [ ] Introduce a clearer visual hierarchy for inventory summary, collection
  view, and recent activity.
- [ ] Polish spacing, typography, and interaction feedback so the app feels
  presentation-ready for a demo.
- [ ] Preserve useful local UI state where it helps, especially around search
  and repeated add and edit flows.
- [ ] Add a small amount of client-side helper text around finishes, tags,
  notes, and row metadata.

## Backend-Dependent Followups

- [ ] Replace hardcoded enum assumptions with backend-published values once that
  ticket lands.
- [ ] Revisit the row editor if PATCH behavior expands beyond one-field-per-save.
- [ ] Add richer inventory and demo-state coverage once expanded seed data is
  available.
- [ ] Add card thumbnails or a more visual result layout if image fields are
  added by the backend.

## Definition Of Done

- [ ] A local user can open the app, understand what inventory they are in,
  find a card, add it, edit it, remove it, and verify the change.
- [ ] The app feels stable under normal demo use and does not rely on backend
  internals outside the published HTTP contract.
- [ ] `npm run build` still passes in `frontend/`.
