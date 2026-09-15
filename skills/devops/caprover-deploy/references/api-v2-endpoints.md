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

### Trigger and source-correlation semantics

Dashboard Force Build posts once to
`/api/v2/user/apps/webhooks/triggerbuild?token=<approved-app-token>&namespace=captain`.
The query token is read from the selected app definition and is never logged; the
server decodes the app binding from that token. Status `100` is sent before
`scheduleDeployNewVersion` completes, so it proves only that the exact webhook
request was acknowledged, not that it was queued or deployed.

The pinned CLI constructs a detached multipart upload, which would return status
`101` without awaiting scheduling. The layout-pinned request guard validates that
exact logical request, removes `?detached=1` from the actual outgoing URL, and
requires status `100` from the resulting synchronous upload. It does not send
`detached=0`: the reviewed server treats query presence as truthy. In server
v1.15.4 the non-detached handler awaits `scheduleDeployNewVersion`, so this exact
request completion plus an expected-source readback supports the CLI positive
path. Status `101`, rejection, timeout, or an ambiguous response is inconclusive.

For local Git, the controller resolves the selected branch once and directs the
CLI to archive that immutable full commit SHA. For tarballs, it uploads a protected
private byte-for-byte snapshot and injects `sha256:<artifact-digest>` into the
existing `gitHash` field. That digest is a client-supplied source fingerprint
persisted by CapRover, not server-native artifact attestation, an operation ID, or
exclusive ownership of the observed generation.

### Optional SSH replica observation

For the reviewed server v1.15.4, `isLegacyAppName: true` maps an app to Docker
service `srv-captain--<app-name>`; `false` maps it to `<app-name>`. The controller
requires that flag to be present and boolean before an SSH replica observation.
It serializes the complete `docker service ls` command as one shell-quoted SSH
command argument. Docker's [`service ls` filtering](https://docs.docker.com/reference/cli/docker/service/ls/)
can return names that contain the filter value, so prefix siblings may appear in
the output. The controller ignores those siblings and requires exactly one row
whose name equals the mapped target and whose running and desired replica counts
both equal the validated positive app `instanceCount`. Zero or duplicate exact
target rows, or an unhealthy exact target alongside a healthy sibling, remain
inconclusive. This remains deployment evidence, not application health.

## Known API Limitations

1. `POST appData/{app}/` is not used by this skill's Python API path. The guarded CLI transport uses it only through the synchronous adaptation above. An empty `gitHash` is not treated as a Git-build trigger.
2. API mode supports remote Git configuration only with explicit `--configure-only`; it reports `configured_not_deployed`.
3. API tarball upload is unsupported and rejected before authentication or writes.
4. Git config requires nonempty `user` and `password` fields in `repoInfo`, while preserving and reading back the existing writable app definition.
5. Redirects are rejected for every credential-bearing API request, including same-origin redirects.

CLI upload is a separate selected method using the external, layout-pinned official CLI 2.4.4 and its deployment guard. The reviewed layout was tested with Node 26.7.0; there is no blanket Node 26 compatibility claim.

## Status Codes

| Code | Meaning |
|------|---------|
| 100 | Success |
| 101 | Detached upload acknowledged; scheduling/deployment/health not verified |
| 1102 | Not authorized |
| 1105 / 1106 | Wrong password / invalid authentication token |
| 1108 | Illegal operation |
| 1109 | Build error |
| 1110 | Illegal parameter, including invalid Git configuration |
| HTTP 500 | Inconclusive server failure; stop without changing methods |
