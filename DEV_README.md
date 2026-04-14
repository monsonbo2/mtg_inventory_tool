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
- `POST /inventories` still requires global `editor` / `admin`, and the creator
  becomes `owner`
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
  atomically, copies all source rows into it, and grants the caller `owner`
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

There are now three closely related app-facing search surfaces:

- `GET /cards/search`
- `GET /cards/search/names`
- `GET /cards/oracle/{oracle_id}/printings`

Current behavior:

- app-facing search defaults to the mainline add-flow catalog scope
- `scope=all` broadens search and printing lookup back to the full local catalog
- grouped card-name search groups by `oracle_id`
- quick-add by `oracle_id` stays in the default add-flow scope and does not
  broaden automatically
- when `lang` is omitted for quick-add, the resolver prefers English, then
  mainstream paper printings, then newer printings with stable ties

Migration `0008` note:

- upgraded pre-`0008` databases need a fresh Scryfall bulk import before the
  narrowed default add-search scope is fully trustworthy for auxiliary objects

## Demo / Frontend Notes

Default demo bootstrap:

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

Backend:

```bash
./scripts/test_backend.sh
python3 -m unittest discover -s tests -q
```

Frontend:

```bash
cd frontend && npm test
cd frontend && npm run build
```

Localhost API test layer:

```bash
python3 -m unittest tests.test_web_api tests.test_api_app -q
```

Importer benchmark:

```bash
python3 scripts/benchmark_import_pipeline.py \
  --db /tmp/mtg_benchmark.db \
  --scryfall-json /path/to/default-cards.json \
  --identifiers-json /path/to/AllIdentifiers.json.gz \
  --prices-json /path/to/AllPricesToday.json.gz
```

Search index maintenance:

```bash
python3 -m mtg_source_stack.mvp_importer check-search-index --db var/db/mtg_mvp.db
python3 -m mtg_source_stack.mvp_importer rebuild-search-index --db var/db/mtg_mvp.db
```

Sync run history:

```bash
python3 -m mtg_source_stack.mvp_importer list-sync-runs --db var/db/mtg_mvp.db
python3 -m mtg_source_stack.mvp_importer show-sync-run --db var/db/mtg_mvp.db --run-id 1
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

Useful targeted commands:

```bash
python3 -m unittest discover -s tests -q
python3 -m unittest tests.test_web_api tests.test_api_app -q
cd frontend && npm test
cd frontend && npm run build
```

OpenAPI parity lives in `tests/test_api_contract.py`. If API behavior changes,
expect that suite to fail until `contracts/openapi.json` is refreshed.

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
  - `python3 -m unittest tests.test_web_api tests.test_api_app -q`
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
  an inventory; `POST /me/bootstrap` exists for that reason.
- Do not assume CLI-created inventories automatically have memberships.
- Do not assume docs/examples are allowed to drift from code.
- Do not assume the full-catalog demo should pin exact printings.
- Do not assume localhost integration tests will run inside every sandbox.
- Do not assume `oracle_id` changes storage semantics; storage remains
  printing-based.
