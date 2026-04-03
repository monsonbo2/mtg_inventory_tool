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

The repo is currently in the transition from `demo-ready` to
`shared-service-ready`.

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

The branch history around the current shared-service work includes:

- `6ecc4e3` Add shared-service runtime hardening mode
- `fab4420` Require verified user identity for shared-service writes
- `cabef10` Harden SQLite shared-service runtime posture
- `19c38f0` Add shared-service editor and admin roles
- `6ad8298` Document and validate shared-service deploy posture
- `9b3a3e2` Add deterministic backend test command and CI
- `b409f56` Add card-name search and oracle printings lookup
- `9a9b355` Accept oracle IDs across single-card add flows

Do not assume this repo is still in “local demo only” mode.

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
- `GET /inventories` is filtered to visible inventories
- inventory reads require inventory membership or global `admin`
- inventory writes require inventory `editor` / `owner` membership or global
  `admin`
- `POST /inventories` still requires global `editor` / `admin`, and the
  creator becomes `owner`
- `POST /me/bootstrap` creates one personal `Collection` inventory per
  authenticated global `editor` / `admin`, grants `owner`, and returns that
  same inventory on repeated calls

Important limitation:

- this is still a small single-host authorization model, not a full multi-user
  organization/team system
- existing inventories with no memberships are effectively admin-only until
  memberships are granted
- membership management is currently CLI-first, not a full app UI workflow

If a task requires real user/inventory isolation, treat that as new
architecture work rather than a small follow-up.

## Data Model Notes

- Inventory rows are stored by printing-level `scryfall_id`.
- `oracle_id` is a supported input identifier for single-card add flows, but it
  resolves to a specific printing before persistence.
- Add/import flows should not force `language_code="en"` by default.
  If `language_code` is omitted, it should inherit the resolved printing
  language.
- Finish compatibility is enforced against the underlying card printing.
  Do not allow impossible finish values to persist.
- Owned-row responses now include `allowed_finishes`.

## Search Model Notes

There are now two search layers:

- printing-first search:
  - `GET /cards/search`
- grouped card-name search:
  - `GET /cards/search/names`
- printing lookup by card identity:
  - `GET /cards/oracle/{oracle_id}/printings`

Name search groups by `oracle_id`, not raw printed name.
Printing lookup defaults to English-preferred behavior, with explicit language
selection available.

## Demo / Frontend Notes

Local demo bootstrap:

```bash
python3 scripts/bootstrap_frontend_demo.py --db var/db/frontend_demo.db --force
```

That bootstrap is backend-owned and now includes richer seeded data, including
multilingual behavior that should stay compatible with the current add-flow
rules.

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

Frontend:

```bash
cd frontend && npm test
cd frontend && npm run build
```

Useful full-suite backend command if you are already in the repo root:

```bash
python3 -m unittest discover -s tests -q
```

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

## Important Current Hotspots

These files are still understandable, but they are the places where extra care
is needed because they are becoming coordination bottlenecks:

- `src/mtg_source_stack/inventory/mutations.py`
- `src/mtg_source_stack/inventory/analysis.py`
- `src/mtg_source_stack/cli/inventory.py`

Prefer small extractions and targeted tests over broad rewrites.

## Known Near-Term Priorities

At the time this file was written, the next likely backend priorities are:

1. Harden unique-key mutation races into deterministic `409` behavior instead of
   leaking raw SQLite failures.
2. Add automated parity enforcement for generated OpenAPI vs
   `contracts/openapi.json`.
3. Fix `inventory_health(..., preview_limit=...)` so it actually limits preview
   payloads.
4. Normalize optional blank fields consistently, especially `location`.
5. Finish rollout/runbook validation for the new inventory membership model.

If your task touches one of these areas, assume it is active design territory.

## Things Not To Assume

- Do not assume the backend is ready for horizontal scale.
- Do not assume `shared_service` means a full org/team permission system.
- Do not assume blank optional fields are normalized consistently everywhere.
- Do not assume docs/examples are allowed to drift from code.
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
