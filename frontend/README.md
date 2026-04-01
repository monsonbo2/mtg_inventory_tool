# Frontend Sandbox

This directory is reserved for the demo UI implementation.

## Boundary

The frontend should treat the backend as an HTTP service and should not edit or
depend on Python implementation details under `src/mtg_source_stack/`.

Use these as the integration contract:

- `../docs/api_v1_contract.md`
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

## Working Agreement

- Keep all UI code under `frontend/`.
- Request backend contract changes instead of editing backend files directly.
- Do not duplicate backend business rules unless they are purely presentational.
