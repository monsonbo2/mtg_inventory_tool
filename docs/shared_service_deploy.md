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

Recommended normalized roles:

- `editor`
- `admin`

The app currently treats:

- authenticated users with no roles header as `editor`
- `admin` as implying `editor`

## Backend Startup

Migrate the database intentionally before starting the service:

```bash
mtg-mvp-importer migrate-db --db "var/db/mtg_mvp.db"
```

Then run the API in `shared_service` mode behind the reverse proxy:

```bash
mtg-web-api \
  --db "var/db/mtg_mvp.db" \
  --runtime-mode shared_service \
  --host 127.0.0.1 \
  --forwarded-allow-ips 127.0.0.1
```

Notes:

- `shared_service` enables proxy-header handling by default.
- `shared_service` disables auto-migrate by default.
- `shared_service` rejects `MTG_API_TRUST_ACTOR_HEADERS=true`.
- wildcard public bind addresses should be treated as an explicit operator
  choice, not the default posture.

Useful environment settings:

- `MTG_API_AUTHENTICATED_ACTOR_HEADER`
- `MTG_API_AUTHENTICATED_ROLES_HEADER`
- `MTG_API_PROXY_HEADERS`
- `MTG_API_FORWARDED_ALLOW_IPS`
- `MTG_API_AUTO_MIGRATE`

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
- verify audit attribution and request IDs
