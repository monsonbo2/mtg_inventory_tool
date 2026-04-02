"""HTTP-facing package for the MTG Inventory Tool web backend.

The current API shell supports two runtime modes:

- `local_demo`, the default local-first posture for UI and contract work
- `shared_service`, a safer single-host startup posture for modest shared use

Both modes wrap the existing synchronous inventory service layer and SQLite
runtime. The route boundary now aligns with that sync service surface, shared
service mutating writes use verified-user audit attribution, and broader
authorization/deployment policy still lives outside this package.
"""
