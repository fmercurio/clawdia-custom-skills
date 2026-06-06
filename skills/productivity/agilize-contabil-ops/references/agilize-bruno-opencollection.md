# Agilize Bruno OpenCollection

Use this reference when Agilize API curls from browser DevTools do not replay from the agent (bearer expired, cookies stale) and you need to create Bruno request files for the user to run locally.

## Pattern

Bruno 3+ can read request files as `.yml` (OpenCollection format). A collection root contains:

```yaml
opencollection: 1.0.0

info:
  name: Agilize
bundled: false
extensions:
  bruno:
    ignore:
      - node_modules
      - .git
```

Each request file:

```yaml
info:
  name: Request Display Name
  type: http
  seq: 1

http:
  method: GET
  url: https://app.agilize.com.br/api/v1/companies/{{company_id}}/replace-with-endpoint
  auth:
    type: bearer
    token: "{{access_token}}"
  headers:
    - name: Accept
      value: application/json, text/plain, */*
    - name: Referer
      value: https://app.agilize.com.br/
    - name: key
      value: "{{company_cnpj}}"

settings:
  encodeUrl: true
  timeout: 0
  followRedirects: true
  maxRedirects: 5

docs: |-
  Bruno OpenCollection YAML request for Agilize API.
  Use placeholders for bearer tokens and cookies; do not commit live secrets.
```

## Workflow

1. Ask the user for the DevTools curl or describe the needed request.
2. If the agent gets 401 replaying the curl, create a Bruno request file.
3. Use placeholders (`{{access_token}}`, `{{company_cnpj}}`, etc.) for all secrets.
4. Write the collection under a shared or user-accessible path.
5. Deliver the `.yml` files and tell the user to open them in Bruno.

## Security rules

- **Never** save live bearer tokens, cookies, or passwords in Bruno files committed to the skill.
- If a one-time request needs live credentials, write to a temporary file with `0600` permissions and tell the user to delete after use.
- Prefer Bruno environment variables for secrets (`{{access_token}}`, `{{company_cnpj}}`).

## Templates

- `templates/agilize-opencollection.yml` — collection root file.
- `templates/agilize-bruno-request.yml` — generic request template.
