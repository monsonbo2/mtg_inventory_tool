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
`frontend_handoff.md` and `../contracts/README.md`.

## Current Runtime Docs

- `architecture.md`
  High-level map of the active package structure and intended public surfaces.
- `backend_v1_contract.md`
  Canonical product rules and schema scope for the current web-v1 backend.
- `ingestion_flow.md`
  How the importer turns Scryfall and MTGJSON bulk files into local runtime
  tables.
- `api_v1_contract.md`
  JSON serialization, error mapping, and operational contract notes for the
  current demo API shell.
- `frontend_handoff.md`
  Frontend/backend ownership boundary and the expected demo-UI integration
  rules.
- `../src/mtg_source_stack/api/`
  Demo FastAPI shell that applies the API contract to the current service
  facade.
- `../contracts/`
  OpenAPI snapshot and example payloads for frontend integration.
- `../scripts/bootstrap_frontend_demo.py`
  One-command demo-data bootstrap for frontend work against the local API.
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
