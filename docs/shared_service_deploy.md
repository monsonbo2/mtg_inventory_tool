# Shared-Service Deploy

This is the recommended first-live deployment shape for the current backend:

- one host
- one reverse proxy
- one `mtg-web-api` process
- one SQLite database on local disk
- same-origin frontend and backend

## Public Shape

- The browser talks to the app on one origin.
- The reverse proxy serves the frontend and publishes the API under `/api`.
- The proxy strips the `/api` prefix before forwarding to the backend.
- The backend continues to expose root routes internally such as `/health`,
  `/inventories`, and `/cards/search`.
- Public inventory share reads are intentionally unauthenticated at backend
  route `/shared/inventories/{share_token}`. If the frontend calls them through
  the API prefix, the public proxy route is `/api/shared/inventories/{share_token}`
  and must be forwarded without requiring a verified identity header.
- Share-link management responses expose `public_path` as the browser-facing
  page path, currently `/shared/inventories/{share_token}`. That path is not a
  proxy-aware API fetch URL; the frontend page should call the backend JSON
  route through `/api/shared/inventories/{share_token}` in this deployment
  shape.
- CORS is not part of this deployment shape.

## Reverse Proxy Responsibilities

- terminate TLS
- serve the frontend assets
- proxy `/api` requests to the backend
- strip any client-supplied `X-Authenticated-User`
- strip any client-supplied `X-Authenticated-Roles`
- strip any client-supplied `X-Actor-Id`
- inject verified `X-Authenticated-User`
- optionally inject normalized `X-Authenticated-Roles`
- allow unauthenticated public share reads for
  `/api/shared/inventories/{share_token}` while still stripping spoofed identity
  headers on those requests

Recommended normalized roles:

- `editor`
- `admin`

The app currently treats:

- authenticated users with no roles header as authenticated users with no
  global roles
- `admin` as implying `editor`

These are global app roles from the proxy, not per-inventory roles.

## Inventory Access Model

Shared-service access is now inventory-scoped.

Global app roles:

- `editor`
- `admin`

Local inventory membership roles:

- `viewer`
- `editor`
- `owner`

Effective behavior:

- `GET /inventories` returns only the inventories visible to the caller
- inventory card search routes require a caller who can read at least one
  inventory, or a global `admin`
- inventory reads require `viewer`, `editor`, or `owner` membership on that
  inventory, or a global `admin`
- inventory writes require `editor` or `owner` membership on that inventory,
  or a global `admin`
- inventory share-link management requires `owner` membership on that
  inventory, or a global `admin`
- public share-link reads require possession of the signed share URL and do not
  grant membership or access to private inventory fields
- `POST /inventories` lets any authenticated user create an inventory and
  automatically become `owner`
- `POST /me/bootstrap` lets any authenticated user create one owned personal
  `Collection` inventory and returns that same inventory on repeated calls

Important rollout note:

- existing inventories with no memberships are effectively admin-only until
  you grant memberships intentionally

## Backend Startup

Migrate the database intentionally before starting the service:

```bash
mtg-mvp-importer migrate-db --db "var/db/mtg_mvp.db"
```

If this is an upgraded existing catalog rather than a fresh database, run a
fresh Scryfall bulk import after the migration and before relying on the
default app-facing card-search scope:

```bash
mtg-mvp-importer import-scryfall \
  --db "var/db/mtg_mvp.db" \
  --json /path/to/default-cards.json
```

Why this matters:

- migration `0008` can only backfill the new default add-search scope
  heuristically from older `type_line` data
- the full runtime classification now depends on richer Scryfall fields such as
  `layout`, `set_type`, `games`, `digital`, and `oversized`
- without that post-upgrade reimport, some auxiliary catalog rows can remain in
  the default search scope until the next Scryfall refresh

Then run the API in `shared_service` mode behind the reverse proxy:

```bash
MTG_API_SNAPSHOT_SIGNING_SECRET="replace-with-a-long-random-secret" \
mtg-web-api \
  --db "var/db/mtg_mvp.db" \
  --runtime-mode shared_service \
  --host 127.0.0.1 \
  --forwarded-allow-ips 127.0.0.1
```

Notes:

- `shared_service` enables proxy-header handling by default.
- `shared_service` disables auto-migrate by default.
- API import routes obey that startup schema posture and return
  `schema_not_ready` instead of migrating during request handling.
- `shared_service` rejects `MTG_API_TRUST_ACTOR_HEADERS=true`.
- `shared_service` now also requires `MTG_API_SNAPSHOT_SIGNING_SECRET` so
  deck URL preview tokens and public inventory share URLs stay tamper-evident.
- public inventory share links store only a nonce in the database; the reusable
  signed browser share URL is rebuilt from the nonce plus
  `MTG_API_SNAPSHOT_SIGNING_SECRET` for owner copy-link UX.
- rotating `MTG_API_SNAPSHOT_SIGNING_SECRET` invalidates in-flight deck URL
  preview tokens and active public inventory share URLs that were signed with
  the previous secret. Owners can copy the current URL again after the service
  is using the new secret.
- wildcard public bind addresses should be treated as an explicit operator
  choice, not the default posture.

Useful environment settings:

- `MTG_API_SNAPSHOT_SIGNING_SECRET`
- `MTG_API_AUTHENTICATED_ACTOR_HEADER`
- `MTG_API_AUTHENTICATED_ROLES_HEADER`
- `MTG_API_PROXY_HEADERS`
- `MTG_API_FORWARDED_ALLOW_IPS`
- `MTG_API_AUTO_MIGRATE`

## Membership Rollout Commands

Use the inventory CLI to seed or repair memberships:

```bash
mtg-personal-inventory grant-inventory-membership \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --actor-id alice@example.com \
  --role owner

mtg-personal-inventory list-inventory-memberships \
  --db "var/db/mtg_mvp.db" \
  --inventory personal

mtg-personal-inventory revoke-inventory-membership \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --actor-id alice@example.com
```

Recommended first-live rollout:

1. If the system is blank, let first users create inventories through the app
   so custom names are preserved and the creator becomes `owner`. Use
   `POST /me/bootstrap` only when the default `Collection` name is acceptable,
   or grant `owner` memberships to existing inventories with the CLI.
2. Grant `viewer` / `editor` memberships for the first cohort.
3. Verify visible inventories, allowed writes, and denied writes with at least
   two real user identities before launch.

For local rehearsal before involving real users, seed the frontend demo DB with
shared-service fixtures:

```bash
cd frontend
npm run demo:bootstrap -- --force --shared-service-fixtures
```

Fixture checks:

| User | Roles header | Expected route behavior |
| --- | --- | --- |
| `new-user@example.com` | omit | `GET /me/access-summary` has no readable inventory and `can_bootstrap=true`; custom inventory creation should succeed. |
| `bootstrapped@example.com` | omit | Can read `bootstrapped-collection`. |
| `viewer@example.com` | omit | Can read `personal`; writes to `personal` should return `403`. |
| `writer@example.com` | omit | Can read and write `trade-binder`. |
| `no-access@example.com` | omit | No readable inventories; search should return `403`. |
| `admin@example.com` | `admin` | Can see all demo inventories through global bypass. |

## Operational Expectations

- keep the SQLite database on local storage, not a network filesystem
- validate snapshot backup and restore before live use
- run bulk import/sync jobs as admin operations, not during active edit windows
- keep the backend behind the proxy rather than exposing it directly

## Non-Goals For This Deployment

- direct public exposure of `mtg-web-api`
- separate-origin frontend and backend with browser CORS
- multi-process SQLite scale-out
- proxy passthrough of raw IdP group names into the app

## Next Validation Step

Before first live use, run a rollout smoke pass against this exact shape:

- restore a backup into a fresh DB
- start the API in `shared_service`
- verify the proxy injects the expected headers
- verify at least two authenticated browser sessions
- verify visible inventories and denied inventory access match the granted
  memberships
- verify audit attribution and request IDs
