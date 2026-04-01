# Frontend Sandbox

This directory is reserved for the demo UI implementation.

## Boundary

The frontend should treat the backend as an HTTP service and should not edit or
depend on Python implementation details under `src/mtg_source_stack/`.

Use these as the integration contract:

- `../docs/api_v1_contract.md`
- `../docs/frontend_handoff.md`
- `../docs/frontend_backend_requests.md`
- `../contracts/openapi.json`
- `../contracts/demo_payloads/`

## Expected Scope

The first demo UI is expected to cover:

- inventory selection
- card search and add flow
- owned item list
- quick edit flows
- recent audit activity

## Environment

Copy or adapt `.env.example` into whatever env-file convention your chosen
frontend toolchain expects.

The backend default for local work is:

- API base URL: `http://127.0.0.1:8000`

## Quick Start

1. Bootstrap a demo database:

   ```bash
   python3 ../scripts/bootstrap_frontend_demo.py --db ../var/db/frontend_demo.db --force
   ```

2. Install the backend web dependencies if you have not already:

   ```bash
   pip install -e ..[web]
   ```

3. Start the API:

   ```bash
   mtg-web-api --db ../var/db/frontend_demo.db
   ```

4. Prefer a frontend dev proxy instead of direct browser cross-origin calls.

   The current demo API does not enable CORS by default. If your dev server
   runs on another origin such as `localhost:3000` or `localhost:5173`, proxy
   API requests back to `http://127.0.0.1:8000`.

   Example Vite proxy:

   ```ts
   export default {
     server: {
       proxy: {
         "/api": "http://127.0.0.1:8000",
       },
     },
   }
   ```

## Working Agreement

- Keep all UI code under `frontend/`.
- Request backend contract changes instead of editing backend files directly.
- Do not duplicate backend business rules unless they are purely presentational.
