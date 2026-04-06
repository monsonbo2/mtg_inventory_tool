# ROADMAP.md

Working roadmap and status note for this repo.

This file is where branch-era planning, recent milestone lists, and “what
probably comes next” notes can live without crowding `AGENTS.md`.

## Recent Baseline Milestones

- `a4452d2` Add inventory membership foundations
- `ab1b1db` Fix health previews and blank location responses
- `cd433ad` Enforce inventory-scoped read access
- `8b760ae` Enforce inventory write access by membership
- `ecc5756` Add bulk inventory tag mutations
- `5bfc988` Add default inventory bootstrap flow
- `b58f089` Add catalog classification import fields
- `c1a5976` Apply default add-search catalog scope
- `49f333e` Add broad catalog search scope opt-in
- `3a1cfca` Define oracle-id default printing ranking
- `3c7aff1` Document oracle-id default printing policy
- `c88f80a` Make full-catalog demo bootstrap resolver-driven
- `4d8e97f` Fix grouped card-name search parameter ordering
- `65fea2d` Add bulk finish mutation support
- `2d002c6` Add bulk location mutation support
- `ec20433` Add bulk condition mutation support
- `c8c042f` Add whole-inventory transfer support
- `537de8e` Add inventory duplication API
- `f1220fa` Canonicalize inventory slug usage
- `485f937` Merge import/export backend tools into this branch
- `869717c` Fix CSV import multipart dependency handling

## Working Assumption

After the Phase 2 merge point, expect new work to happen on focused feature
branches rather than one long-lived integration branch.

Current frontend handoff status on `frontend_phase_2`:

- the shared frontend API client now supports JSON requests, multipart CSV
  upload, and CSV/text downloads
- the frontend type surface and client wrappers now cover shared-service
  bootstrap, import/export, transfer, duplicate, and the broader bulk-mutation
  contract
- the current demo UI still passes frontend tests/build on top of that refactor
- the next frontend product branch should start with shared-service bootstrap
  UX and permission-aware empty states, then move into import/export flows
  before transfer/duplicate polish

For live branch priority, prefer:

1. `git status --short --branch`
2. recent commits on the current branch
3. GitHub issues / PRs

Do not treat this file as a source of truth once it drifts from active git
state.

## Likely Workstreams

1. Shared-service rollout validation behind the real reverse proxy and verified
   auth headers.
2. Frontend integration and handoff follow-through for:
   - generalized bulk mutations
   - transfer / duplicate inventory flows
   - import / export preview and commit paths
3. Issue and runbook hygiene around recently landed work such as:
   - full-catalog demo bootstrap
   - playable-card default search scope
   - documented `oracle_id` default printing policy
   - import / export operational notes
4. Membership/bootstrap follow-through, especially the `POST /me/bootstrap`
   first-run flow and operator runbooks.
5. Later reporting/performance work once rollout behavior is stable.

## Active Questions To Watch

- Does the current shared-service rollout behave cleanly behind the real proxy
  and verified auth headers?
- Are GitHub issue states and local request docs aligned with the actual branch
  state?
- What is the next product feature branch after Phase 2 merge:
  frontend integration of the current bulk / transfer features, pasted list
  import, or something else?
- Are there any remaining operator runbook gaps around memberships, bootstrap,
  catalog refresh expectations, or import/export dependencies?
