# AGENTS.md

This file is the fast orientation note for coding agents working in this repo.
Read it before making changes.

## Repo Snapshot

This project is a local-first MTG inventory system with:

- a synchronous SQLite-backed service layer
- a FastAPI web API
- a React frontend in `frontend/`
- contract artifacts in `contracts/`
- demo/bootstrap helpers for frontend work

This checkout is currently on the Phase 2 backend rollout branch,
`backend_phase_2`, which layers inventory-scoped access control and
shared-service onboarding on top of the earlier demo/shared-service work.

## Current Direction

The backend is being hardened for a small trusted single-host rollout, not for
horizontal scale or broad multi-tenant use.

The intended first-live shape is:

- one host
- one reverse proxy
- one `mtg-web-api` process
- one SQLite database on local disk
- same-origin frontend and backend
- proxy-published API under `/api`, stripped before upstreaming

See `docs/shared_service_deploy.md` for the detailed deployment runbook.

## Recent Milestones

The recent branch history around the current Phase 2 work includes:

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

Do not assume this repo is still in “local demo only” mode, and do not assume
search/bootstrap behavior is still pre-Phase-2.

## Current Shared-Service Model

Runtime mode is controlled with:

- `MTG_API_RUNTIME_MODE`
- or `mtg-web-api --runtime-mode ...`

Shared-service auth expects verified upstream headers:

- `X-Authenticated-User`
- `X-Authenticated-Roles`

Current authz behavior:

- `/health` is open
- app routes are protected in `shared_service`
- authenticated users with no roles header default to `editor`
- `admin` implies `editor`
- global proxy-backed app roles are `editor` and `admin`
- local inventory membership roles are `viewer`, `editor`, and `owner`
- card-search routes require an authenticated user who can read at least one
  inventory; `POST /me/bootstrap` is the intended first-run escape hatch
- `GET /inventories` is filtered to visible inventories
- inventory reads require inventory membership or global `admin`
- inventory writes require inventory `editor` / `owner` membership or global
  `admin`
- `POST /inventories` still requires global `editor` / `admin`, and the
  creator becomes `owner`
- `POST /inventories/{inventory_slug}/items/bulk` supports grouped tag
  operations:
  - `add_tags`
  - `remove_tags`
  - `set_tags`
  - `clear_tags`
- `POST /me/bootstrap` creates one personal `Collection` inventory per
  authenticated global `editor` / `admin`, grants `owner`, and returns that
  same inventory on repeated calls

Important limitation:

- this is still a small single-host authorization model, not a full multi-user
  organization/team system
- existing inventories with no memberships are effectively admin-only until
  memberships are granted
- membership management is currently CLI-first, not a full app UI workflow
- CLI `create-inventory` does not carry an authenticated actor context by
  default, so if you create inventories via CLI for shared-service rollout,
  plan to grant memberships explicitly afterward

If a task requires real user/inventory isolation, treat that as new
architecture work rather than a small follow-up.

## Data Model Notes

- Inventory access is modeled locally with:
  - `inventory_memberships`
  - `actor_default_inventories`
- Inventory rows are stored by printing-level `scryfall_id`.
- `oracle_id` is a supported input identifier for single-card add flows, but it
  resolves to a specific printing before persistence.
- Add/import flows should not force `language_code="en"` by default.
  If `language_code` is omitted, it should inherit the resolved printing
  language.
- Finish compatibility is enforced against the underlying card printing.
  Do not allow impossible finish values to persist.
- Owned-row responses now include `allowed_finishes`.
- Blank `location` is normalized to `null` in API-facing owned-row, mutation,
  and audit payloads.

## Search Model Notes

There are now two search layers:

- printing-first search:
  - `GET /cards/search`
- grouped card-name search:
  - `GET /cards/search/names`
- printing lookup by card identity:
  - `GET /cards/oracle/{oracle_id}/printings`

Important current search behavior:

- App-facing search defaults to the mainline add-flow catalog scope, not the
  broad full local catalog.
- `scope=all` is the additive opt-in when the frontend intentionally wants the
  broader catalog.
- Name search groups by `oracle_id`, not raw printed name.
- Printing lookup defaults to the same scoped policy and can broaden with
  `scope=all`.
- The default `oracle_id` printing resolver is now policy-backed and should be
  treated as intentional behavior:
  - stay inside the default add-search scope unless the caller opts into
    `scope=all`
  - honor explicit `lang`, `set_code`, `collector_number`, and finish
    compatibility constraints
  - when `lang` is omitted, prefer English
  - within viable candidates, prefer mainstream paper printings before more
    promo-like ones
  - then prefer newer printings with stable tie-breaks

If you change search or bootstrap behavior, keep this policy and the published
contract in sync.

## Demo / Frontend Notes

Local demo bootstrap:

```bash
python3 scripts/bootstrap_frontend_demo.py --db var/db/frontend_demo.db --force
```

Full-catalog demo bootstrap:

```bash
python3 scripts/bootstrap_frontend_demo.py \
  --db var/db/frontend_demo_full.db \
  --force \
  --full-catalog \
  --scryfall-json /path/to/default-cards.json
```

Important demo/bootstrap rules:

- The default small demo mode should stay fast and self-contained.
- The full-catalog mode is now resolver-driven.
- Do not hard-code exact printings in the full-catalog path unless a truly
  specific aesthetic is required.
- Prefer demo intent expressed through the real add flow:
  - `oracle_id`
  - optional `lang`
  - optional `finish`
- Seed demo price snapshots from the resolved printings, not stale hard-coded
  IDs.

Frontend contract surfaces to keep in sync when backend behavior changes:

- `contracts/openapi.json`
- `docs/api_v1_contract.md`
- relevant files in `contracts/demo_payloads/`
- `docs/frontend_handoff.md`
- `frontend/src/types.ts` when frontend-facing shapes change

## Canonical Validation Commands

Backend:

```bash
./scripts/test_backend.sh
```

This script forces this checkout’s `src/` onto `PYTHONPATH` and should be the
default backend test command for both humans and agents.

OpenAPI parity is enforced in the backend test suite. If API behavior changes,
expect `tests/test_api_contract.py` to fail until `contracts/openapi.json` is
refreshed.

Frontend:

```bash
cd frontend && npm test
cd frontend && npm run build
```

Useful full-suite backend command if you are already in the repo root:

```bash
python3 -m unittest discover -s tests -q
```

Live localhost integration layer:

```bash
python3 -m unittest tests.test_web_api tests.test_api_app -q
```

Important note for agents:

- In some sandboxed environments, those localhost tests will skip because the
  test harness cannot bind `127.0.0.1`.
- On a normal local dev machine they should run.
- If the suite unexpectedly skips there, verify
  `LOCALHOST_SERVER_TESTING_AVAILABLE` in:
  - `tests/test_web_api.py`
  - `tests/test_api_app.py`

## Sandbox / Elevation Notes

- Some agent sessions run in a sandbox that blocks localhost socket binding
  and/or outbound network access.
- If live API tests skip unexpectedly, or remote/GitHub commands fail for
  sandbox reasons, rerun them with elevated permissions instead of assuming the
  repo is broken.
- This most often applies to:
  - `python3 -m unittest tests.test_web_api tests.test_api_app -q`
  - `gh auth status`
  - `gh issue ...`
  - `gh pr ...`
  - `git push`

## Refreshing OpenAPI

After intentional API contract changes, refresh `contracts/openapi.json` from
the repo root with:

```bash
python3 - <<'PY'
import json
from pathlib import Path
from mtg_source_stack.api.app import create_app
from mtg_source_stack.api.dependencies import ApiSettings

app = create_app(
    ApiSettings(
        db_path=Path("var/db/mtg_mvp.db"),
        auto_migrate=True,
        host="127.0.0.1",
        port=8000,
    )
)

Path("contracts/openapi.json").write_text(
    json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
)
PY
```

Do not update only the runtime code and leave the published artifacts stale.
The snapshot is test-enforced, not advisory.

## Important Current Hotspots

These files are still understandable, but they are the places where extra care
is needed because they are becoming coordination bottlenecks:

- `src/mtg_source_stack/inventory/access.py`
- `src/mtg_source_stack/inventory/catalog.py`
- `src/mtg_source_stack/inventory/mutations.py`
- `src/mtg_source_stack/inventory/analysis.py`
- `src/mtg_source_stack/cli/inventory.py`
- `scripts/bootstrap_frontend_demo.py`
- `tests/test_web_api.py`

Prefer small extractions and targeted tests over broad rewrites.

## Ticket Workflow

- GitHub issues are the primary ticket source of truth for this repo.
- Local planning/request docs under `docs/frontend_backend_requests/` are useful
  context, but they are not the authoritative ticket state.
- GitHub issues and pull requests share one number sequence. A missing issue
  number may actually be a PR.
- Internal agent names such as "Dani" or "Carol" are coordination labels, not
  GitHub usernames.
- If work for a ticket lands in a commit, update the GitHub issue as part of
  that workflow. Do not treat editing only the local request doc as sufficient.
- When ticket status changes materially, keep both surfaces in sync:
  - GitHub issue state/comments
  - relevant local request docs, if they exist
- Do not close a GitHub ticket just because local docs were updated; close it
  when the implementing work is actually committed/pushed or otherwise clearly
  delivered.

## Known Near-Term Priorities

At the time this file was updated, the next likely priorities are:

1. Merge/review `backend_phase_2` and do the real shared-service dress
   rehearsal behind the actual reverse proxy and auth headers.
2. Close out issue hygiene for the current branch state, especially around:
   - full-catalog demo bootstrap
   - playable-card default search scope
   - documented `oracle_id` default printing policy
3. Finish rollout/runbook validation for the inventory membership model and the
   `POST /me/bootstrap` first-run flow.
4. If a next product feature starts, bulk add / pasted list import is the most
   likely candidate and should build on the existing `oracle_id` resolver.
5. Larger reporting/performance work is still later, not the immediate next
   step.

If your task touches one of these areas, assume it is active design territory.

## Things Not To Assume

- Do not assume the backend is ready for horizontal scale.
- Do not assume `shared_service` means a full org/team permission system.
- Do not assume `scope=all` is the default search behavior.
- Do not assume every authenticated user can search before they own or can read
  an inventory; `POST /me/bootstrap` exists for that reason.
- Do not assume CLI-created inventories automatically have memberships.
- Do not assume docs/examples are allowed to drift from code.
- Do not assume the full-catalog demo should pin exact printings.
- Do not assume localhost integration tests will run inside every sandbox.
- Do not assume `oracle_id` changes storage semantics; storage remains
  printing-based.

## Working Style For This Repo

- Keep changes tightly scoped.
- Prefer regression tests in the same pass as behavior changes.
- Preserve published contract artifacts when runtime behavior changes.
- Prefer additive API changes over overloaded route behavior when introducing
  new frontend-facing features.
- Be careful around demo/bootstrap scripts: they are part of the effective
  frontend contract, not just throwaway tooling.
