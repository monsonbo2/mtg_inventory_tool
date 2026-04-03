# Docs Guide

This directory mixes current runtime documentation, future design notes, and a
small amount of historical context.

If you're new to the repo, the best reading order is:

1. `architecture.md`
2. `backend_v1_contract.md`
3. `ingestion_flow.md`
4. `../notebooks/00_repo_architecture_walkthrough.ipynb`

If you're building against the current demo web API shell, read
`api_v1_contract.md` after those.

If you're preparing a separate frontend sandbox, also read
`frontend_handoff.md`, `../frontend/README.md`, `frontend_build_checklist.md`,
`frontend_search_autocomplete_checklist.md`,
`frontend_demo_refinement_handoff.md`, `frontend_backend_requests/`, and
`../contracts/README.md`.

## Current Runtime Docs

- `architecture.md`
  High-level map of the active package structure and intended public surfaces.
- `backend_v1_contract.md`
  Canonical product rules and schema scope for the current web-v1 backend.
- `ingestion_flow.md`
  How the importer turns Scryfall and MTGJSON bulk files into local runtime
  tables.
- `api_v1_contract.md`
  JSON serialization, error mapping, runtime modes, and operational contract
  notes for the current web API shell.
- `frontend_handoff.md`
  Frontend/backend ownership boundary and the expected demo-UI integration
  rules.
- `frontend_build_checklist.md`
  Working implementation checklist for the next frontend demo-build pass.
- `frontend_search_autocomplete_checklist.md`
  Working implementation checklist for the polished search-autocomplete pass.
- `frontend_demo_refinement_handoff.md`
  Current branch/worktree handoff note for the next frontend demo-refinement
  pass.
- `frontend_backend_requests/`
  Folder of frontend-requested backend/API changes, with
  `frontend_backend_requests/README.md` as the process guide and template.
- `shared_service_deploy.md`
  First-live deployment runbook for the current single-host shared-service API
  posture.
- `../src/mtg_source_stack/api/`
  FastAPI shell that applies the API contract to the current sync service
  facade, with `local_demo` and `shared_service` runtime modes plus the current
  shared-service split between global app roles and local inventory
  memberships.
- `../contracts/`
  OpenAPI snapshot and example payloads for frontend integration.
- `../scripts/bootstrap_frontend_demo.py`
  Demo-data bootstrap for frontend work against the local API, with both the
  default tiny demo catalog and an optional full-catalog Scryfall import mode.
- `schema_mvp.sql`
  Docs-side copy of the base MVP schema for convenient browsing.
- `../src/mtg_source_stack/mtg_mvp_schema.sql`
  Base runtime schema file loaded before later migrations add newer runtime
  structures such as audit and search support.
- `../examples/sample_queries.sql`
  Example SQL queries that target the current MVP runtime schema.

If prose and SQL ever disagree, treat the runtime schema plus the recorded
migrations as the source of truth.

## Future Design Notes

- `source_map.md`
  Upstream source strategy, field ownership, and integration notes that go
  beyond the current local-only read path.
- `schema_full.sql`
  Future normalized schema design, not the live runtime model.

## Historical Context

- `restructure_checklist.md`
  Historical refactor plan kept for background, not for current implementation
  guidance.

## Notebook Walkthroughs

- `../notebooks/00_repo_architecture_walkthrough.ipynb`
- `../notebooks/01_db_and_migrations_walkthrough.ipynb`
- `../notebooks/02_importer_walkthrough.ipynb`
- `../notebooks/03_inventory_domain_walkthrough.ipynb`
- `../notebooks/04_reporting_and_api_contract_walkthrough.ipynb`
