# CapRover REST API v2 — Quick Reference

## Authentication

```http
POST /api/v2/login/
Content-Type: application/json

{"password": "<caprover-password>"}
```

Response:
```json
{
  "status": 100,
  "description": "Login succeeded",
  "data": { "token": "<JWT>" }
}
```

Token goes in `x-captain-auth` header for all subsequent requests.

## App Management

### List all apps
```http
GET /api/v2/user/apps/appDefinitions/
x-captain-auth: <token>
```

### Create app
```http
POST /api/v2/user/apps/appDefinitions/register/
x-captain-auth: <token>

{"appName": "my-app", "hasPersistentData": false}
```

### Update app definition (GitHub config)

The supported `POST /api/v2/user/apps/appDefinitions/update` is a **full update**,
not a partial patch. Omitted fields can receive defaults. Do not send a hand-written
example payload with empty volumes/ports/env or default flags to an existing app.

The controller reads and validates the current definition, writes a protected
recovery snapshot, copies the supported writable fields, changes only the intended
Git fields, posts that complete projection, and verifies the readback. Unknown
schemas or preservation drift fail closed. `redirectDomain`, when present, is a
string, not a boolean. Sensitive environment/Git values stay in memory or the
owner-only recovery snapshot, never in ordinary output.

See [safe full updates](../../caprover-operations/references/safe-app-definition-updates.md)
and the checked-in controller for the version-specific field allowlist. Serialize
configuration changes: these requests are not an atomic compare-and-swap against
concurrent operators. A failed readback is not permission to restore automatically.

## Build & Deploy

### Get build status + logs
```http
GET /api/v2/user/apps/appData/<app-name>/
x-captain-auth: <token>
```

The controller retains only these response fields:
- `isAppBuilding` (bool) — currently building
- `isBuildFailed` (bool) — last build failed

## Known API Limitations

1. `POST appData/{app}/` is not used by this skill's Python API path. An empty `gitHash` is not treated as a Git-build trigger.
2. API mode supports remote Git configuration only with explicit `--configure-only`; it reports `configured_not_deployed`.
3. API tarball upload is unsupported and rejected before authentication or writes.
4. Git config requires nonempty `user` and `password` fields in `repoInfo`, while preserving and reading back the existing writable app definition.
5. Redirects are rejected for every credential-bearing API request, including same-origin redirects.

CLI upload is a separate selected method using the external, layout-pinned official CLI 2.4.4 and its deployment guard. The reviewed layout was tested with Node 26.7.0; there is no blanket Node 26 compatibility claim.

## Status Codes

| Code | Meaning |
|------|---------|
| 100 | Success |
| 101 | Detached deployment accepted; not build/health verification |
| 1102 | Not authorized |
| 1105 / 1106 | Wrong password / invalid authentication token |
| 1108 | Illegal operation |
| 1109 | Build error |
| 1110 | Illegal parameter, including invalid Git configuration |
| HTTP 500 | Inconclusive server failure; stop without changing methods |
