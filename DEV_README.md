# DEV_README.md

Developer-oriented repo/runtime guide for this project.

This file holds the deeper repo behavior, workflow, and file-map context that is
useful to humans and agents but too detailed for `AGENTS.md`.

## Repo Snapshot

This project is a local-first MTG inventory system with:

- a synchronous SQLite-backed service layer
- a FastAPI web API
- a React frontend in `frontend/`
- contract artifacts in `contracts/`
- demo/bootstrap helpers for frontend work

## Current Runtime Shape

The current intended live posture is still modest and single-host:

- one host
- one reverse proxy
- one `mtg-web-api` process
- one SQLite database on local disk
- same-origin frontend and backend
- proxy-published API under `/api`, stripped before upstreaming

See `docs/shared_service_deploy.md` for the durable deployment runbook.

## Shared-Service Model

Runtime mode is controlled with:

- `MTG_API_RUNTIME_MODE`
- or `mtg-web-api --runtime-mode ...`

Shared-service auth expects verified upstream headers:

- `X-Authenticated-User`
- `X-Authenticated-Roles`

Current authz model:

- `/health` is open
- authenticated users with no roles header have no global roles
- `admin` implies `editor`
- global proxy-backed app roles are `editor` and `admin`
- local inventory membership roles are `viewer`, `editor`, and `owner`
- card-search routes require an authenticated user who can read at least one
  inventory; custom inventory creation or `POST /me/bootstrap` are the
  intended first-run escape hatches
- `GET /inventories` is filtered to visible inventories
- each `GET /inventories` row includes the current actor's effective
  per-inventory capabilities: `role`, `can_read`, `can_write`,
  `can_manage_share`, and `can_transfer_to`
- inventory reads require inventory membership or global `admin`
- inventory writes require inventory `editor` / `owner` membership or global
  `admin`
- `POST /inventories` lets any authenticated user create an inventory and
  become `owner`
- `POST /inventories/{inventory_slug}/items/bulk` now supports grouped:
  - `add_tags`
  - `remove_tags`
  - `set_tags`
  - `clear_tags`
  - `set_quantity`
  - `set_notes`
  - `set_acquisition`
  - `set_finish`
  - `set_location`
  - `set_condition`
- `POST /inventories/{source_inventory_slug}/transfer` now supports atomic
  selected-row and whole-inventory `copy` / `move` operations, `dry_run`
  previews, `on_conflict=fail|merge`, and `keep_acquisition`
- `POST /inventories/{source_inventory_slug}/duplicate` creates a new inventory
  atomically, copies all source rows into it, requires write access to the
  source inventory, and grants the caller `owner`
- `POST /me/bootstrap` creates one personal `Collection` inventory per
  authenticated user, grants `owner`, and returns that same inventory on
  repeated calls

Important limitation:

- this is still a small single-host authorization model, not a full multi-user
  organization/team system
- existing inventories with no memberships are effectively admin-only until
  memberships are granted
- membership management is currently CLI-first, not a full app UI workflow
- CLI `create-inventory` does not carry an authenticated actor context by
  default, so inventories created that way may need membership grants afterward

## Data Model Notes

- Inventory access is modeled locally with:
  - `inventory_memberships`
  - `actor_default_inventories`
- Inventory rows are stored by printing-level `scryfall_id`.
- `oracle_id` is a supported input identifier for single-card add flows, but it
  resolves to a specific printing before persistence.
- Add/import flows should not force `language_code="en"` by default.
- If `language_code` is omitted, it should inherit the resolved printing
  language.
- Finish compatibility is enforced against the underlying card printing.
- Owned-row responses include `allowed_finishes`.
- Blank `location` is normalized to `null` in owned-row, mutation, and audit
  payloads.

## Search Model Notes

There are now four closely related app-facing search surfaces:

- `GET /cards/search`
- `GET /cards/search/names`
- `GET /cards/oracle/{oracle_id}/printings`
- `GET /cards/oracle/{oracle_id}/printings/summary`

Current behavior:

- app-facing search defaults to the mainline add-flow catalog scope
- `scope=all` broadens search and printing lookup back to the full local catalog
- grouped card-name search groups by `oracle_id`
- grouped non-exact name search keeps the FTS/token-prefix path hot and only
  uses broader substring rescue for selective long single-token misses after an
  FTS grouped miss
- quick-add by `oracle_id` stays in the default add-flow scope and does not
  broaden automatically
- when `lang` is omitted for quick-add, the resolver prefers English, then
  mainstream paper printings, then newer printings with stable ties
- the quick-add printing summary route exposes the backend default add choice,
  available languages, scoped printing count, and primary/preferred printings;
  full all-language browsing remains an explicit `lang=all` printings lookup

Migration `0008` note:

- upgraded pre-`0008` databases need a fresh Scryfall bulk import before the
  narrowed default add-search scope is fully trustworthy for auxiliary objects

## Demo / Frontend Notes

Default demo bootstrap:

```bash
cd frontend
npm run demo:bootstrap -- --force
```

Shared-service validation fixtures:

```bash
npm run demo:bootstrap -- --force --shared-service-fixtures
```

This optional fixture mode adds stable actors for frontend rollout checks:
`new-user@example.com`, `bootstrapped@example.com`, `viewer@example.com`,
`writer@example.com`, `no-access@example.com`, and `admin@example.com`. Omit
`X-Authenticated-Roles` for all except `admin@example.com`, where the normalized
roles header should be `admin`.

Proxy-backed shared-service preflight:

```bash
npm run demo:bootstrap -- --force --shared-service-fixtures
npm run build
npm run smoke:shared-service-proxy -- --start-backend
```

Manual browser validation through the local harness:

```bash
MTG_API_SNAPSHOT_SIGNING_SECRET="local-shared-service-dev-secret" \
npm run backend:demo -- --runtime-mode shared_service --no-auto-migrate

npm run proxy:shared-service -- --fixture-preset viewer
```

The harness validates the `/api` prefix strip and fixture header injection. It
is intentionally local-only; production reverse-proxy work is tracked
separately in issue #57.

Full-catalog demo bootstrap:

```bash
npm run demo:bootstrap -- \
  --force \
  --full-catalog \
  --scryfall-json /path/to/default-cards.json \
  --db ../var/db/frontend_demo_full.db
```

Optional full-catalog pricing import:

```bash
npm run demo:bootstrap -- \
  --force \
  --full-catalog \
  --scryfall-json /path/to/default-cards.json \
  --identifiers-json /path/to/AllIdentifiers.json \
  --prices-json /path/to/AllPricesToday.json \
  --db ../var/db/frontend_demo_full.db
```

Rules of thumb:

- keep the default small demo mode fast and self-contained
- full-catalog mode should stay resolver-driven
- avoid hard-coding exact printings in full-catalog bootstrap unless a very
  specific aesthetic is required
- prefer demo intent expressed through the real add flow:
  - `oracle_id`
  - optional `lang`
  - optional `finish`

## Import / Export Route Notes

Current import surfaces:

- `POST /imports/csv`
- `POST /imports/decklist`
- `POST /imports/deck-url`

Current shared-service auth shape:

- `_require_import_inventory_write_access(...)` in
  `src/mtg_source_stack/api/routes.py` is the real shared write-access rule for
  import routes.
- `_require_csv_import_inventory_write_access(...)` is currently a naming seam
  on top of that shared helper, not separate policy.
- Each import route currently builds its own `inventory_validator` closure
  before calling the service-layer import function.

Why this matters:

- The layering is reasonable if CSV import later needs stricter or different
  auth behavior than decklist or deck-URL imports.
- Today, though, the CSV-specific wrapper and the repeated inline validator
  closures are mostly structure rather than behavior.
- If future cleanup touches this area, keep one shared source of truth for the
  actual write-access rule and only keep route-specific wrappers if they are
  buying real policy separation or clearer intent.

Current schema-policy shape:

- API import routes pass `schema_policy="require_current"` into the service
  layer, so request handling never auto-migrates the database.
- CLI import entrypoints keep the local-first default
  `schema_policy="initialize_if_needed"`.
- The public import entrypoints prepare the schema once, then resolution/write
  helpers operate on the prepared DB path.

Multipart caveat:

- `POST /imports/csv` uses FastAPI `UploadFile` + `File(...)` + `Form(...)`.
- FastAPI checks for `python-multipart` when that route is registered, not only
  when a request reaches the route.
- That means app import, route registration, and OpenAPI generation can all
  fail if `python-multipart` is unavailable, even for unrelated tests or routes.
- Treat that as an app-startup coupling, not just a CSV-upload runtime detail,
  when changing import-route wiring.

## File Map

- access control:
  - `src/mtg_source_stack/inventory/access.py`
  - `src/mtg_source_stack/api/dependencies.py`
  - `src/mtg_source_stack/api/routes.py`
- catalog search and printing resolution:
  - `src/mtg_source_stack/inventory/catalog.py`
  - `src/mtg_source_stack/inventory/query_catalog.py`
  - `tests/test_inventory_service.py`
  - `tests/test_web_api.py`
- mutations and response shaping:
  - `src/mtg_source_stack/inventory/mutations.py`
  - `src/mtg_source_stack/inventory/response_models.py`
  - `src/mtg_source_stack/api/response_models.py`
- importer and migrations:
  - `src/mtg_source_stack/importer/scryfall.py`
  - `src/mtg_source_stack/db/migrations/`
  - `tests/test_importer.py`
  - `tests/test_schema_migrations.py`

## Useful Commands

Python command note:

- `./scripts/test_backend.sh` is intentionally safe for a base `pip install -e .`
  environment and does not require the optional web stack.
- API/web tests require the `web` extra. Activate a web-capable environment or
  install it with `pip install -e '.[web]'` before running
  `./scripts/test_backend_web.sh`.
- Both backend wrappers force this checkout's `src/` tree onto `PYTHONPATH` so
  multi-checkout editable installs do not leak into test runs.

Backend base:

```bash
./scripts/test_backend.sh
```

Backend API/web:

```bash
./scripts/test_backend_web.sh
```

Broad unittest discovery is still safe in a base environment because web/API
modules skip cleanly when optional dependencies are absent. Prefer the explicit
wrappers for routine validation because they make the intended dependency layer
obvious.

Frontend:

```bash
cd frontend && npm test
cd frontend && npm run build
```

Importer benchmark:

```bash
PYTHONPATH=src .venv/bin/python scripts/benchmark_import_pipeline.py \
  --db /tmp/mtg_benchmark.db \
  --scryfall-json /path/to/default-cards.json \
  --identifiers-json /path/to/AllIdentifiers.json.gz \
  --prices-json /path/to/AllPricesToday.json.gz
```

Search index maintenance:

```bash
PYTHONPATH=src .venv/bin/python -m mtg_source_stack.mvp_importer check-search-index --db var/db/mtg_mvp.db
PYTHONPATH=src .venv/bin/python -m mtg_source_stack.mvp_importer rebuild-search-index --db var/db/mtg_mvp.db
```

Sync run history:

```bash
PYTHONPATH=src .venv/bin/python -m mtg_source_stack.mvp_importer list-sync-runs --db var/db/mtg_mvp.db
PYTHONPATH=src .venv/bin/python -m mtg_source_stack.mvp_importer show-sync-run --db var/db/mtg_mvp.db --run-id 1
```

Suggested local/shared-service cadence:

- `sync-prices`: daily
- `sync-scryfall`: weekly
- `sync-identifiers`: weekly or less often
- `check-search-index`: after unusual repairs/import interruptions, or on a periodic ops check
- `rebuild-search-index`: repair-only command when `check-search-index` reports drift

## Contract Surfaces

If backend behavior changes, inspect these together:

- `contracts/openapi.json`
- `docs/api_v1_contract.md`
- relevant files in `contracts/demo_payloads/`
- `docs/frontend_handoff.md`
- `frontend/src/types.ts`

OpenAPI parity is test-enforced, not advisory.

## Validation Commands

Backend default:

```bash
./scripts/test_backend.sh
```

Backend API/web:

```bash
./scripts/test_backend_web.sh
```

Useful targeted commands:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -q
PYTHONPATH=src .venv/bin/python -m unittest tests.test_api_contract tests.test_api_app tests.test_web_api -q
cd frontend && npm test
cd frontend && npm run build
```

OpenAPI parity lives in `tests/test_api_contract.py` and is part of the API/web
test surface. If API behavior changes, expect `./scripts/test_backend_web.sh` to
fail until `contracts/openapi.json` is refreshed.

## Refreshing OpenAPI

After intentional API contract changes, refresh `contracts/openapi.json` from
the repo root with:

```bash
PYTHONPATH=src .venv/bin/python - <<'PY'
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

## Agent Workflow Notes

- GitHub issues and pull requests are the only ticket tracking source of truth.
- Local planning docs under `docs/frontend_backend_requests/` and `ROADMAP.md`
  are useful context, but they are not authoritative ticket state and should
  not be used as live status boards.
- GitHub issues and pull requests share one number sequence. A missing issue
  number may actually be a PR.
- If work for a ticket lands in a commit, update the GitHub issue as part of
  that workflow. Editing only a local doc is not sufficient.
- Keep behavior changes and regression tests together when possible.
- Prefer additive API changes over overloading existing routes.
- Be careful around demo/bootstrap scripts: they are part of the effective
  frontend contract, not throwaway tooling.

## Sandbox / Elevation Notes

- Some agent sessions cannot bind localhost or use outbound network access.
- If localhost integration tests skip unexpectedly, or GitHub/network commands
  fail for sandbox reasons, rerun them with elevated permissions instead of
  assuming the repo is broken.
- This most often applies to:
  - `PYTHONPATH=src .venv/bin/python -m unittest tests.test_web_api tests.test_api_app -q`
  - `gh auth status`
  - `gh issue ...`
  - `gh pr ...`
  - `git push`

## Hotspots

These files are still understandable, but they are coordination bottlenecks:

- `src/mtg_source_stack/inventory/access.py`
- `src/mtg_source_stack/inventory/catalog.py`
- `src/mtg_source_stack/inventory/mutations.py`
- `src/mtg_source_stack/inventory/analysis.py`
- `src/mtg_source_stack/cli/inventory.py`
- `scripts/bootstrap_frontend_demo.py`
- `tests/test_web_api.py`

Prefer small extractions and targeted tests over broad rewrites.

## Things Not To Assume

- Do not assume the backend is ready for horizontal scale.
- Do not assume `shared_service` means a full org/team permission system.
- Do not assume `scope=all` is the default search behavior.
- Do not assume every authenticated user can search before they own or can read
  an inventory; custom inventory creation and `POST /me/bootstrap` exist for
  that reason.
- Do not assume CLI-created inventories automatically have memberships.
- Do not assume docs/examples are allowed to drift from code.
- Do not assume the full-catalog demo should pin exact printings.
- Do not assume localhost integration tests will run inside every sandbox.
- Do not assume `oracle_id` changes storage semantics; storage remains
  printing-based.
