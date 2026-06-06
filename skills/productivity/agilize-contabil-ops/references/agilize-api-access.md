# Agilize API Access — Keycloak/OIDC PKCE Authentication

Use this reference to authenticate against the Agilize platform via the Keycloak SSO/OIDC PKCE flow.

## Overview

Agilize uses Keycloak as its identity provider. The authentication flow is:

1. **Authorization Code with PKCE** — generate a `code_verifier`, compute `code_challenge`, request the auth URL.
2. **Form-based login** — POST username/password to the Keycloak login form.
3. **OTP/TOTP** (if 2FA enabled) — POST the TOTP code to the OTP form.
4. **Extract authorization code** — from the redirect URL fragment.
5. **Token exchange** — trade the code for an `access_token`.
6. **API calls** — use `Authorization: Bearer <token>`.

### Key URLs

| Purpose | URL |
|---|---|
| Auth | `https://sso.agilize.com.br/auth/realms/AgilizeAPPs/protocol/openid-connect/auth` |
| Token | `https://sso.agilize.com.br/auth/realms/AgilizeAPPs/protocol/openid-connect/token` |
| API base | `https://app.agilize.com.br` |
| Client ID | `agilize-legacy-client` |

### Redirect URI

The browser typically redirects to `https://app.agilize.com.br/#/dados-empresa` or `https://app.agilize.com.br/`. The redirect URI must be identical in both the auth request and the token exchange.

## Login script

A generic login script is provided at `scripts/agilize_login.py`.

### Credential sources (priority order)

1. **KeePassXC** — if `--db`, `--key-file`, and `--entry` point to a KeePassXC database containing the Agilize credentials.
2. **Environment variables** — `AGILIZE_USERNAME`, `AGILIZE_PASSWORD`, `AGILIZE_TOTP` (or `AGILIZE_TOTP_SECRET` for seed-based generation).
3. **Config file** — `--config ~/.config/agilize.json` with fields `username`, `password`, `totp_secret`, `company_id`, `company_cnpj`.

### Usage

```bash
# Login and verify (safe GET to finance-accounts):
python scripts/agilize_login.py --verify \
  --company-id "<uuid>" \
  --company-cnpj "<cnpj-only-digits>"

# Authenticated GET, save to file:
python scripts/agilize_login.py \
  --api-get "/api/v1/companies/<uuid>/finance-transactions?from=2025-01-01T00:00:00-0300&to=2025-01-31T23:59:59-0300&count=3000" \
  --output /tmp/agilize-jan-2025.json \
  --company-id "<uuid>" \
  --company-cnpj "<cnpj-only-digits>"

# Using environment variables:
export AGILIZE_USERNAME="user@example.com"
export AGILIZE_PASSWORD="..."
export AGILIZE_TOTP_SECRET="..."  # base32 TOTP seed
python scripts/agilize_login.py --verify --company-id "$AGILIZE_COMPANY_ID"
```

### Security contract

The script:
- Never prints password, TOTP, cookies, bearer token, refresh token, or id_token.
- Reads credentials only into process memory.
- Uses dynamic Keycloak form parsing (no hard-coded `session_code`/`execution`/`tab_id`).
- Writes API responses to `0600` mode files when `--output` is specified.

## Manual PKCE flow (for reference/implementation)

If you need to implement the flow yourself or debug:

### Step 1: Generate PKCE pair

```python
import base64, hashlib, os

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

verifier = b64url(os.urandom(40))
challenge = b64url(hashlib.sha256(verifier.encode("ascii")).digest())
```

### Step 2: Request auth URL

```
GET https://sso.agilize.com.br/auth/realms/AgilizeAPPs/protocol/openid-connect/auth
  ?client_id=agilize-legacy-client
  &redirect_uri=https://app.agilize.com.br/
  &response_mode=fragment
  &response_type=code
  &scope=openid
  &state=<random>
  &nonce=<random>
  &code_challenge=<challenge>
  &code_challenge_method=S256
```

### Step 3: Parse and submit login form

The Keycloak login page returns HTML with a `<form>` containing hidden fields. Extract the form `action` URL and hidden inputs, then POST:

```
POST <form_action>
Body: username=<user>&password=<pass>&<hidden_fields...>
```

### Step 4: Handle OTP (if 2FA enabled)

If the response includes an OTP form, extract its action/hidden fields and POST:

```
POST <otp_form_action>
Body: otp=<6-digit-code>&login=Entrar&<hidden_fields...>
```

### Step 5: Extract code from redirect

The final redirect URL contains `#code=<authorization_code>&state=<state>`. Extract `code` from the URL fragment (not query string, since `response_mode=fragment`).

### Step 6: Exchange code for token

```
POST https://sso.agilize.com.br/auth/realms/AgilizeAPPs/protocol/openid-connect/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&client_id=agilize-legacy-client
&code=<authorization_code>
&redirect_uri=<same as step 2>
&code_verifier=<verifier from step 1>
```

Response:
```json
{
  "access_token": "...",
  "expires_in": 600,
  "refresh_token": "...",
  "token_type": "Bearer"
}
```

### Step 7: Use the access token

```
Authorization: Bearer *** <cnpj-only-digits>
Referer: https://app.agilize.com.br/
Accept: application/json
```

**Note:** Access tokens expire in ~10 minutes. For longer sessions, re-authenticate or use refresh tokens (if the flow provides them).

## Fallback: Keycloak session cookies

If the login script fails because the Keycloak flow changed, the user can provide **Keycloak session cookies** (`KEYCLOAK_IDENTITY`, `KEYCLOAK_SESSION`) saved to a local file. The agent can then replay the PKCE auth-code flow using those cookies to obtain a fresh bearer.

```
GET https://sso.agilize.com.br/auth/realms/AgilizeAPPs/protocol/openid-connect/auth?...
Cookie: KEYCLOAK_IDENTITY=...; KEYCLOAK_SESSION=...
```

This produces a redirect with a fresh `code`, which can be exchanged normally.

## Fallback: Bruno API client

If bearer tokens consistently expire or the PKCE flow cannot be automated, create Bruno request files so the user can run them in an authenticated browser context.

See `references/agilize-bruno-opencollection.md`.

## Finding the company_id

Agilize exposes **no discovery endpoint** to list companies accessible by the authenticated user. Probing `/api/v1/companies`, `/users/me`, `/users/me/companies`, `/my-companies`, `/empresas`, `/companies/all`, `/companies?cnpj=...`, `/companies?search=...` all return 404 or `null`. Do not waste turns probing these.

### Primary method: JWT `tenant` claim (autonomous, no browser needed)

After a successful PKCE login via `agilize_login.py`, the JWT `access_token` contains a `tenant` claim — an array of company UUIDs accessible by the authenticated user. For single-company accounts, `tenant[0]` is the company_id.

```python
import base64, json, sys, os
sys.path.insert(0, os.path.expanduser("~/.hermes/skills/productivity/agilize-contabil-ops/scripts"))
import agilize_login as A

cfg = json.load(open(os.path.expanduser("~/.config/agilize.json")))
token = A.login(cfg, A.DEFAULT_CLIENT_ID, A.DEFAULT_REDIRECT_URI, 30,
                "Mozilla/5.0 Chrome/124.0 Safari/537.36")

# Decode JWT payload (middle segment, base64url)
payload_b64 = token.access_token.split('.')[1]
payload_b64 += '=' * (-len(payload_b64) % 4)  # pad
claims = json.loads(base64.urlsafe_b64decode(payload_b64))

company_id = claims["tenant"][0]
print(f"company_id={company_id}")
```

Other useful claims: `preferred_username`, `email`, `name` (company/person name), `locale`.

### Fallback: DevTools Network tab

Only use this if the JWT `tenant` claim is absent, or the account has multiple companies and `tenant[0]` is not the desired one:

1. Open https://app.agilize.com.br/ and select the target company.
2. F12 → Network tab.
3. Navigate to any screen (Financeiro, Dashboard, etc.) — any action that triggers an API call.
4. Click any request to `app.agilize.com.br/api/v1/companies/...`.
5. Copy the UUID from the path: `/api/v1/companies/{UUID}/finance-transactions`.

Format: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` (36 chars, 5 hyphen-separated blocks). Stable per company — once recorded, it does not change.

### Diagnosing a bad company_id

When `company_id` is missing, malformed, or a placeholder (e.g. literal `"uuid"`), the API returns **HTTP 500** (not 404). The server resolves the route pattern but fails on the missing entity, producing an HTML error page. Always inspect the `--verify` HTTP status first; a 500 with HTML body usually means bad UUID, not a server outage.

## Cookie pitfall: analytics vs auth

When a user exports browser cookies as a session fallback, **only Keycloak cookies carry authentication**:

- **Useful**: `KEYCLOAK_IDENTITY`, `KEYCLOAK_SESSION` (domain `sso.agilize.com.br`).
- **Useless**: `_ga_*`, `_gid`, `_hjSession*`, `_dd_s`, `_ga` (domain `.agilize.com.br` or `app.agilize.com.br`). These are analytics/tracking cookies (Google Analytics, Hotjar, DataDog) and cannot authenticate any API call.

Browser cookie exporters default to the current tab's domain. If a user is on `app.agilize.com.br` when they export, they get only analytics cookies. To obtain auth cookies, the user must either:
- Export from `sso.agilize.com.br` (visit it directly, then export), or
- Skip cookie fallback and use PKCE credential login (`agilize_login.py`).

If a cookie dump contains only `_ga_*` / `_hjSession*` / `_dd_s` / `_gid`, do not attempt to use them — ask for credentials or for a fresh export from the SSO domain.

## Common error patterns

| Error | Cause | Fix |
|---|---|---|
| `401 Authorization required` | Bearer token expired | Re-authenticate or ask for fresh session |
| `403 Forbidden` | Missing `key` header (CNPJ) | Add `key: <cnpj>` to request headers |
| `400 A transação já possui uma evidência` | Trying to add evidence to a transaction that already has one | Delete existing evidence first, then re-add |
| `500 Internal Server Error` (HTML page) | `company_id` missing, malformed, or placeholder `"uuid"` | Extract from JWT `tenant` claim (see above), or verify via DevTools |
| Keycloak form not found | Keycloak flow/UI changed | Update form parsing or use cookie fallback |
