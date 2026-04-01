# API Contract Artifacts

This directory holds the frontend-facing contract snapshot for the current demo
API shell.

## Contents

- `openapi.json`
  Generated OpenAPI snapshot for the current API surface.
- `demo_payloads/`
  Small example JSON payloads that mirror the expected request/response shapes
  a demo frontend should handle.

## Refreshing The OpenAPI Snapshot

Run this from the repo root after intentional API contract changes:

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

Keep `openapi.json` and `docs/api_v1_contract.md` aligned when the API shape
changes.
