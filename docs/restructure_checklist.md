# Repo Restructure Checklist

This document turns the proposed cleanup into a low-risk sequence of PRs.

The goal is to make the repo easier to understand and maintain without changing
behavior until the structure is stable.

## Principles

- Keep public CLI behavior stable during the first two PRs.
- Prefer file moves and import-path cleanup before logic refactors.
- Preserve existing test coverage while splitting large modules.
- Make the repo easier to orient to before making it more abstract.

## Current Pain Points

- The repo presents conflicting descriptions of what the real app is.
- Runtime code, docs, examples, notebooks, and wrappers live together.
- The package lives under a directory with spaces.
- Core Python files are very large and mix unrelated responsibilities.
- Tests exist and pass, but most coverage lives in one large smoke-test file.
- Generated snapshot artifacts are easy to pick up in the working tree.

## Target End State

```text
repo/
  README.md
  pyproject.toml
  src/
    mtg_source_stack/
      __init__.py
      cli/
        importer.py
        inventory.py
      db/
        connection.py
        schema.py
        snapshots.py
      importer/
        service.py
        scryfall.py
        mtgjson.py
      inventory/
        normalize.py
        queries.py
        csv_import.py
        reports.py
        service.py
      data/
        mtg_mvp_schema.sql
  tests/
    __init__.py
    test_cli_smoke.py
    test_importer.py
    test_inventory_service.py
    test_csv_import.py
    fixtures/
  docs/
    architecture.md
    source_map.md
    ingestion_flow.md
    schema_notes.md
  examples/
    sample_inventory_import.csv
    sample_queries.sql
  notebooks/
    mtg_source_stack_walkthrough.ipynb
  scripts/
    mvp_importer.py
    personal_inventory_cli.py
```

## PR 1: Orientation Cleanup

Objective: make the repo understandable without changing packaging, imports, or
CLI behavior.

### Scope

- Move human-facing docs and samples out of `MtG Source Stack/`.
- Keep runtime code where it is for now.
- Clarify the repo story in the READMEs.
- Ignore generated snapshot output.
- Use a more discoverable test command in docs.

### Exact File Moves

- [x] Move `MtG Source Stack/source_map.md` to `docs/source_map.md`
- [x] Move `MtG Source Stack/ingestion_flow.md` to `docs/ingestion_flow.md`
- [x] Move `MtG Source Stack/schema.sql` to `docs/schema_full.sql`
- [x] Move `MtG Source Stack/sample_queries.sql` to `examples/sample_queries.sql`
- [x] Move `MtG Source Stack/sample_inventory_import.csv` to `examples/sample_inventory_import.csv`
- [x] Move `MtG Source Stack/mtg_source_stack_walkthrough.ipynb` to `notebooks/mtg_source_stack_walkthrough.ipynb`

### In-Place Edits

- [x] Update `README.md` to explain the repo at a glance
- [x] Update `README.md` to point to `docs/`, `examples/`, and `notebooks/`
- [x] Update `README.md` to explicitly say runtime code still temporarily lives under `MtG Source Stack/`
- [x] Replace or shorten `MtG Source Stack/README.md` so it no longer contradicts the root README
- [x] Update `.gitignore` to ignore `MtG Source Stack/_snapshots/`
- [x] Update testing docs to recommend `python3 -m unittest discover -s tests -q`

### Non-Goals

- [x] Do not change Python package paths
- [x] Do not change console entry point names
- [x] Do not split Python modules yet
- [x] Do not change database schema behavior

### Acceptance Criteria

- [x] A new contributor can identify runtime code, docs, examples, and notebooks in under a minute
- [x] The root README and folder README tell the same story
- [x] Generated snapshots no longer show up as untracked noise
- [x] Existing tests still pass with no behavior changes

### Validation

- [x] Run `python3 -m unittest discover -s tests -q`
- [x] Open the root README and confirm all moved file references are correct
- [x] Confirm no imports or script entry points changed

## PR 2: Package Normalization

Objective: move to a conventional Python layout while keeping behavior and CLI
entry points stable.

### Scope

- Move the installable package into `src/`.
- Keep wrapper scripts working during the transition.
- Keep the schema file canonical in one runtime location.
- Remove or demote duplicate schema files.

### Exact File Moves

- [x] Move `MtG Source Stack/mtg_source_stack/__init__.py` to `src/mtg_source_stack/__init__.py`
- [x] Move `MtG Source Stack/mtg_source_stack/mvp_importer.py` to `src/mtg_source_stack/mvp_importer.py`
- [x] Move `MtG Source Stack/mtg_source_stack/personal_inventory_cli.py` to `src/mtg_source_stack/personal_inventory_cli.py`
- [x] Move `MtG Source Stack/mtg_source_stack/mtg_mvp_schema.sql` to `src/mtg_source_stack/mtg_mvp_schema.sql`

### In-Place Edits

- [x] Update `pyproject.toml` from the current package-dir layout to a standard `src` layout
- [x] Keep `MtG Source Stack/mvp_importer.py` as a compatibility wrapper
- [x] Keep `MtG Source Stack/personal_inventory_cli.py` as a compatibility wrapper
- [x] Update wrappers to prepend repo `src/` to `sys.path` so direct script execution still works
- [x] Decide whether `MtG Source Stack/mtg_mvp_schema.sql` becomes a docs artifact or is deleted

### Non-Goals

- [x] Do not rename CLI commands
- [x] Do not split logic into many modules yet
- [x] Do not change user-facing command syntax

### Acceptance Criteria

- [x] `pip install -e .` works from a clean checkout
- [x] `python3 -c "import mtg_source_stack"` works from repo root after install
- [x] Existing wrapper commands still run
- [x] Existing tests still pass after the package move
- [x] There is one canonical runtime schema file

### Validation

- [x] Run `python3 -m unittest discover -s tests -q`
- [x] Run `pip install -e .`
- [x] Run `mtg-mvp-importer --help`
- [x] Run `mtg-personal-inventory --help`
- [x] Run `python3 "MtG Source Stack/mvp_importer.py" --help`
- [x] Run `python3 "MtG Source Stack/personal_inventory_cli.py" --help`

## PR 3: Internal Module Split

Objective: reduce the two large runtime modules into clear responsibility-based
modules without changing behavior.

### New Modules

- [x] Create `src/mtg_source_stack/db/connection.py`
- [x] Create `src/mtg_source_stack/db/schema.py`
- [x] Create `src/mtg_source_stack/db/snapshots.py`
- [x] Create `src/mtg_source_stack/importer/service.py`
- [x] Create `src/mtg_source_stack/importer/scryfall.py`
- [x] Create `src/mtg_source_stack/importer/mtgjson.py`
- [x] Create `src/mtg_source_stack/inventory/normalize.py`
- [x] Create `src/mtg_source_stack/inventory/queries.py`
- [x] Create `src/mtg_source_stack/inventory/csv_import.py`
- [x] Create `src/mtg_source_stack/inventory/reports.py`
- [x] Create `src/mtg_source_stack/inventory/service.py`
- [x] Create `src/mtg_source_stack/cli/importer.py`
- [x] Create `src/mtg_source_stack/cli/inventory.py`

### Responsibility Moves

- [x] Move DB connection helpers into `db/connection.py`
- [x] Move schema loading and initialization into `db/schema.py`
- [x] Move snapshot creation, listing, and restore logic into `db/snapshots.py`
- [x] Move Scryfall import logic into `importer/scryfall.py`
- [x] Move MTGJSON identifier and price import logic into `importer/mtgjson.py`
- [x] Move importer orchestration into `importer/service.py`
- [x] Move condition, finish, tag, and language normalization into `inventory/normalize.py`
- [x] Move inventory SQL operations into `inventory/service.py`
- [x] Move filter/query construction into `inventory/queries.py`
- [x] Move CSV parsing and mapping into `inventory/csv_import.py`
- [x] Move formatting and report rendering into `inventory/reports.py`
- [x] Reduce `argparse` setup modules to thin CLI entry points

### Test Restructure

- [x] Complete the focused test-file split in a follow-up cleanup PR while keeping smoke coverage green
- [x] Add `tests/__init__.py`
- [x] Split smoke and unit tests into focused files
- [x] Create `tests/test_cli_smoke.py`
- [x] Create `tests/test_importer.py`
- [x] Create `tests/test_inventory_service.py`
- [x] Create `tests/test_csv_import.py`
- [x] Create `tests/fixtures/` for reusable payloads and sample CSV files

### Non-Goals

- [x] Do not redesign the domain model in this PR
- [x] Do not change the database schema unless needed for parity
- [x] Do not rename user-facing commands unless the team explicitly wants that

### Acceptance Criteria

- [x] No single runtime file should remain a giant mixed-responsibility module
- [x] Most functions live near related responsibilities
- [x] Smoke tests still cover end-to-end flows
- [ ] Unit tests cover parsing, normalization, and service logic directly
- [x] Behavior remains backward compatible

### Validation

- [x] Run `python3 -m unittest discover -s tests -q`
- [x] Run a representative import flow against temp files
- [x] Run a representative inventory flow against temp files
- [x] Compare key CLI outputs before and after refactor

## Optional PR 4: Wrapper Retirement

Objective: remove transitional compatibility scaffolding after the repo has
settled.

### Candidate Steps

- [x] Remove `MtG Source Stack/` runtime wrappers if no longer needed
- [x] Move any remaining human-facing assets out of `MtG Source Stack/`
- [x] Rename transitional files or folders that only existed for compatibility

### Acceptance Criteria

- [x] All docs point to the new canonical locations
- [x] No one needs the old wrapper paths for normal use
- [x] The repo reads like a standard Python project

## Suggested Execution Order

1. PR 1 lands first with no behavior changes.
2. PR 2 moves packaging to `src/` while keeping compatibility wrappers.
3. PR 3 splits internals by responsibility.
4. Optional cleanup PR removes transitional scaffolding.

## Review Questions Before Starting

- Should compatibility wrappers remain long-term, or only for one release?
- Should the duplicate top-level MVP schema become a docs file or be removed?
- Is `unittest` the long-term test runner, or should the repo eventually adopt `pytest`?
- Should the final public layout keep `examples/` and `notebooks/`, or should those be folded into `docs/`?
