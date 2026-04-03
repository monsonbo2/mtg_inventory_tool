"""HTTP-facing package for the MTG Inventory Tool web backend.

The current API shell supports two runtime modes:

- `local_demo`, the default local-first posture for UI and contract work
- `shared_service`, a safer single-host startup posture for modest shared use

Both modes wrap the existing synchronous inventory service layer and SQLite
runtime. The route boundary now aligns with that sync service surface,
`shared_service` now combines verified upstream identity with local
inventory-scoped memberships, and the first-live deployment shape is a
same-origin reverse proxy over the current root-route API surface. Broader
admin-surface policy still lives outside this package.
"""
