# API Contract Artifacts

This directory holds the frontend-facing contract snapshot for the current demo
API shell.

## Contents

- `openapi.json`
  Canonical OpenAPI snapshot for the current API surface. Backend contract
  tests compare a freshly generated schema from the live app against this file,
  so intentional API changes must refresh it in the same change.
- `demo_payloads/`
  Small example JSON payloads that mirror the expected request/response shapes
  a demo frontend should handle.
- `../scripts/bootstrap_frontend_demo.py`
  One-command local dataset bootstrap for frontend demos.

## Refreshing The OpenAPI Snapshot

`openapi.json` is test-enforced by `python3 -m unittest tests.test_api_contract -q`
and by the normal backend CI path through `./scripts/test_backend.sh`.

Run this from the repo root after intentional API contract changes:

```bash
PYTHONPATH=src python3 - <<'PY'
import json
from pathlib import Path
from mtg_source_stack.api.app import create_app
from mtg_source_stack.api.dependencies import ApiSettings

app = create_app(
    ApiSettings(
        db_path=Path("var/db/mtg_mvp.db"),
        runtime_mode="local_demo",
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

If the live app schema changes and this snapshot is not refreshed, the backend
test suite will fail.

After refreshing the snapshot, rerun `python3 -m unittest tests.test_api_contract -q`
and keep `openapi.json` and `docs/api_v1_contract.md` aligned when the API
shape changes.
