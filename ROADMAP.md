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

## Working Assumption

After the Phase 2 merge point, expect new work to happen on focused feature
branches rather than one long-lived integration branch.

For live branch priority, prefer:

1. `git status --short --branch`
2. recent commits on the current branch
3. GitHub issues / PRs

Do not treat this file as a source of truth once it drifts from active git
state.

## Likely Workstreams

1. Shared-service rollout validation behind the real reverse proxy and verified
   auth headers.
2. Issue and runbook hygiene around recently landed work such as:
   - full-catalog demo bootstrap
   - playable-card default search scope
   - documented `oracle_id` default printing policy
3. Membership/bootstrap follow-through, especially the `POST /me/bootstrap`
   first-run flow and operator runbooks.
4. Next product features such as bulk add or pasted list import, likely
   building on the existing `oracle_id` resolver and bulk tag mutation shape.
5. Later reporting/performance work once rollout behavior is stable.

## Active Questions To Watch

- Does the current shared-service rollout behave cleanly behind the real proxy
  and verified auth headers?
- Are GitHub issue states and local request docs aligned with the actual branch
  state?
- What is the next product feature branch after Phase 2 merge:
  bulk add, pasted list import, or something else?
- Are there any remaining operator runbook gaps around memberships, bootstrap,
  or catalog refresh expectations?
