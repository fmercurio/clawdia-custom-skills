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
```http
POST /api/v2/user/apps/appDefinitions/update
x-captain-auth: <token>

{
  "appName": "my-app",
  "instanceCount": 1,
  "captainDefinitionRelativeFilePath": "./captain-definition",
  "notExposeAsWebApp": false,
  "forceSsl": false,
  "websocketSupport": false,
  "volumes": [],
  "ports": [],
  "appPushWebhook": {
    "repoInfo": {
      "user": "<github-user>",
      "password": "<github-token>",
      "branch": "main",
      "sshKey": "",
      "repo": "https://github.com/org/repo"
    }
  }
}
```

### Delete app
```http
POST /api/v2/user/apps/appDefinitions/delete/
x-captain-auth: <token>

{"appName": "my-app"}
```

## Build & Deploy

### Get build status + logs
```http
GET /api/v2/user/apps/appData/<app-name>/
x-captain-auth: <token>
```

Response fields:
- `isAppBuilding` (bool) — currently building
- `isBuildFailed` (bool) — last build failed
- `logs.lines` (array) — build log lines

### Get runtime logs
```http
GET /api/v2/user/apps/appData/<app-name>/logs
x-captain-auth: <token>
```

## Known API Limitations

1. **`POST appData/{app}/`** accepts `captainDefinitionContent` or tarball, but `{gitHash: ""}` alone does NOT trigger a Git-based build.
2. **GitHub config** requires `user` + `password` fields in `repoInfo`, even for public repos. Without them: `status=1110`.
3. **Tarball upload** via API may return 500 on CapRover 1.14.x. Use Playwright Force Build instead.
4. **CLI** crashes on Node.js 26 (`ERR_USE_AFTER_CLOSE`).

## Status Codes

| Code | Meaning |
|------|---------|
| 100 | Success |
| 1108 | Missing required field (tarball/captainDefinition) |
| 1110 | Missing required GitHub field |
| HTTP 500 | Internal error (try Playwright fallback) |
