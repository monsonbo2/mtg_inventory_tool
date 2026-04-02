"""HTTP-facing package for the MTG Inventory Tool web backend.

The current API shell supports two runtime modes:

- `local_demo`, the default local-first posture for UI and contract work
- `shared_service`, a safer single-host startup posture for modest shared use

Both modes wrap the existing synchronous inventory service layer and SQLite
runtime. The route boundary now aligns with that sync service surface,
`shared_service` now requires authenticated `editor` access for the current
app routes, and broader deployment plus finer-grained admin policy still lives
outside this package.
"""
