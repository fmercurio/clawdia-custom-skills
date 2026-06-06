---
name: agilize-contabil-ops
description: "Agilize contábil platform operations: Keycloak/OIDC PKCE authentication, finance transaction classification, NFS-e evidence linking, transaction splitting, pro-labore reconciliation, monthly close, and audit workflows. Company-agnostic — works for any Agilize tenant."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [agilize, accounting, bookkeeping, reconciliation, nfse, pro-labore, brazilian-accounting]
---

# Agilize Contábil Platform Operations

Use this skill when working with the **Agilize** online accounting platform: authenticating, reading/classifying finance transactions, splitting transactions, linking NFS-e/tax/invoice evidence, reconciling pro-labore, running monthly close checks, and producing audit trails.

This skill is **company-agnostic**. All company-specific values (company ID, CNPJ, category IDs, partner UUIDs) must be supplied via configuration or runtime parameters — never hard-coded.

## Prerequisites

Before using this skill, the following must be available:

1. **Agilize credentials** — username, password, and TOTP (if 2FA is enabled), stored in a secure credential manager (KeePassXC, environment variables, or equivalent).
2. **Company ID** — the Agilize UUID for the target company.
3. **Company CNPJ** — required as the `key` header for most API calls.
4. **Hermes profile** — ideally a dedicated finance/admin profile with its own credential access.

See `references/agilize-api-access.md` for the full authentication pattern.

## Core posture

- Operate as a practical accounting/finance specialist, not as a certified accountant.
- Separate facts, assumptions, estimates, and recommendations.
- Flag tax/legal/accounting uncertainty and recommend accountant validation when material.
- Do not expose sensitive banking, tax, CPF/CNPJ, account, contract, or supplier details in chat unless necessary and minimized.
- **Never** execute payments, transfers, filings, account changes, month-close actions, or any irreversible operation without explicit user approval.

## Security contract

- **Never** print or log passwords, TOTP codes, cookies, bearer tokens, refresh tokens, or full DevTools curls in chat, memory, skills, or audit logs.
- Treat bearer/cookie values as **ephemeral**: use in memory or a short-lived local temp file (mode 0600) only.
- If a credential must be passed to a script, use stdin, environment variables, or a secure credential manager — never shell arguments.
- If API calls return 401, ask the user for a fresh session artifact; do not persist stale tokens.

## Agilize platform overview

Agilize is a Brazilian online accounting/finance platform accessed via `https://app.agilize.com.br/`. Authentication uses **Keycloak/OIDC with PKCE** (Authorization Code flow). The API is REST/JSON under `/api/v1/companies/{company_id}/...`.

### Key endpoints

| Purpose | Endpoint |
|---|---|
| Finance transactions | `GET /api/v1/companies/{cid}/finance-transactions?from=...&to=...&sort=mainDate&direction=DESC&count=3000` |
| Categories (root only) | `GET /api/v1/companies/{cid}/finance-transaction-categories` — returns only top-level (23 roots). Query params `?tree=true`, `?full=true`, `?includeChildren=true` are ignored. |
| Categories (with children) | `GET /api/v1/companies/{cid}/finance-transaction-categories/{rootId}` — returns the root category with full `categoriesChildren` array including sub-category UUIDs, codes, evidence types. Walk recursively to build the complete tree. |
| Finance accounts | `GET /api/v1/companies/{cid}/finance-accounts` |
| Closing periods | `GET /api/v1/companies/{cid}/accounting-closing-periods` |
| NFS-e by competence | `GET /api/v1/companies/{cid}/nfses?competencia=YYYY-MM-01T00:00:00&count=3000` |
| Taxes | `GET /api/v1/companies/{cid}/taxes?year=YYYY&closed=true&count=3000` |
| Pro-labore annual | `GET /api/v1/companies/{cid}/prolabore-anual?anoReferencia=YYYY-01-01T00:00:00P` |
| Pro-labore monthly | `GET /api/v1/companies/{cid}/prolabores?competence=YYYY-MM-01T00:00:00-0300&count=3000` |
| Invoices (Agilize) | `GET /api/v1/companies/{cid}/invoices?competence=...&closed=true&count=3000` |
| Partners/people | `GET /api/v1/companies/{cid}/people?type=partner&count=3000` |
| Transaction split | `POST /api/v1/companies/{cid}/finance-transactions/{tid}/split` |
| Transaction update | `POST /api/v1/companies/{cid}/finance-transactions/{tid}` with `X-HTTP-Method-Override: PUT` |
| Evidence delete | `DELETE /api/v1/companies/{cid}/finance-transactions/{tid}/evidences/{eid}` |
| Pro-labore PDF | `GET /api/v1/companies/{cid}/prolabore-anual/download?competence=...&partner=...` |

### Authentication: Keycloak PKCE flow

```
sso.agilize.com.br/auth/realms/AgilizeAPPs/protocol/openid-connect/auth
  → client_id=agilize-legacy-client
  → redirect_uri=https://app.agilize.com.br/...
  → response_mode=fragment, response_type=code, scope=openid
  → PKCE: code_challenge, code_challenge_method=S256

Token exchange:
  POST sso.agilize.com.br/.../protocol/openid-connect/token
  → grant_type=authorization_code
  → client_id=agilize-legacy-client
  → code + code_verifier + redirect_uri
```

Access tokens expire in ~10 minutes. For repeated operations, re-authenticate or replay the PKCE flow with valid Keycloak session cookies.

See `references/agilize-api-access.md` for the full flow, script usage, and fallback patterns.

### Required API headers

```
Authorization: Bearer <access_token>
key: <company_cnpj>
Referer: https://app.agilize.com.br/
Accept: application/json
```

## Default classification workflow

1. **Authenticate** — run the login script or obtain a session artifact.
2. **Fetch categories** — `/finance-transaction-categories` to get the company's category tree (labels + UUIDs).
3. **Fetch transactions** — `/finance-transactions` for the target period.
4. **Classify** — assign categories based on bank/card descriptions, supplier patterns, and user rules.
5. **Reconcile evidence** — link NFS-e, tax, invoice, or pro-labore evidence as required by each category.
6. **Split if needed** — when a single transaction covers multiple expense categories.
7. **Verify** — re-read transactions and confirm categories, evidence, and split children are correct.
8. **Report** — produce audit notes with counts, totals, pending items, and rollback instructions.

## Transaction splitting

When a single bank debit (e.g. a credit-card invoice payment) represents multiple underlying expenses, split the parent transaction into child transactions with independent categories and evidence.

Payload shape:
```json
{
  "splitsDto": [
    {"category": "<cat_uuid>", "description": "...", "amount": 500.85},
    {"category": "<cat_uuid>", "description": "...", "amount": 136.17}
  ]
}
```

**Important:** the UI sends **positive** split amounts even for expense parents. Child transactions are created with negative amounts when the parent is an expense. The sum of split amounts must equal `abs(parent.amount)`.

See `references/agilize-transaction-splitting.md` for the full workflow and verification pattern.

## Evidence integrity rules

### One NFS-e → one transaction

A single NFS-e (`nfse.__identity`) must **never** be linked to more than one finance transaction. Before linking, scan the period for existing references to the same NFS-e.

### Tax evidence

Tax-backed categories use `evidence[tax]=<company_tax_uuid>`. The field is **always** `evidence[tax]` regardless of the tax type (DAS, INSS, IRRF, etc.); the category's `allowedEvidenceType` determines the resulting evidence type label.

### Invoice evidence

Categories like `Contabilidade` require `agilizeInvoiceEvidence`. List closed invoices with `/invoices?competence=...&closed=true` and link the matching one.

### Pro-labore evidence

Pro-labore categories (`personRequired=true`, `requiredPersonType=partner`) require both `person=<partner_uuid>` and `evidence[prolabore]=<prolabore_uuid>`. Fetch from `/prolabores?competence=...` (not `/prolabore-anual`).

See `references/agilize-evidence-integrity.md` for the full pre-link checklist and duplicate-scan pattern.

## Pro-labore vs profit distribution

Use `/prolabore-anual` to classify owner/partner transfers:

1. Find the competence month and partner.
2. Compare bank transfer to `valorLiquido` (net), not gross `valor`.
3. If transfer exceeds `valorLiquido`: split → pró-labore (net) + adiantamento de lucro (excess).
4. Keep INSS/IRRF as separate tax obligations, not as cash paid to the partner.

See `references/agilize-prolabore-reconciliation.md` for the full rule set.

## Monthly close checklist

Before marking a month as closed:

- [ ] All transactions have a category assigned.
- [ ] No transaction has `hasEvidence == false` when its category requires evidence.
- [ ] No NFS-e is linked to more than one transaction.
- [ ] All pro-labore transfers have partner + pro-labore evidence linked.
- [ ] All tax payments have matching tax evidence.
- [ ] Card invoice payments are split into individual expenses where applicable.
- [ ] Totals reconcile (credits + debits + adjustments = expected balance).
- [ ] No duplicate tax payments (Pix vs card) remain unresolved.

See `references/agilize-monthly-close.md` for the full close runbook.

## Bruno API client fallback

When bearer tokens expire and replays return 401, create Bruno request files so the user can run them in an authenticated browser context.

See `references/agilize-bruno-opencollection.md` and `templates/agilize-opencollection.yml` + `templates/agilize-bruno-request.yml`.

## Common Pitfalls

1. **`company_id` left as literal `"uuid"` or placeholder.** The verify endpoint returns HTTP 500 (HTML error page, not JSON 404) when the UUID is missing/malformed because Agilize resolves the route pattern but fails on the missing entity. Always confirm the config file has the real UUID before running `--verify`. See `references/agilize-api-access.md` → "Finding the company_id".

2. **No company discovery endpoint, but JWT has it.** Agilize does not expose `/companies`, `/users/me/companies`, or any list endpoint — all 404. However, after a successful PKCE login, the JWT `access_token` contains a `tenant` claim (array of UUIDs) with the company ID. Decode the JWT payload (base64url middle segment) and extract `tenant[0]`. Only fall back to DevTools (Network tab) if the JWT claim is absent or the user has multiple companies and the wrong one is first. See `references/agilize-api-access.md` → "Finding the company_id".

3. **Exhaust autonomous discovery before asking user for manual steps.** Before requesting DevTools inspection, cookie exports, or any browser-side action, try: (1) decode JWT claims from the token you already have, (2) probe likely API endpoints, (3) use browser tools to navigate and inspect. Users expect the agent to be self-sufficient — asking for manual browser work when the data is already in the JWT or accessible via script is a friction signal.

4. **Analytics cookies ≠ auth cookies.** Browser cookie exports from `app.agilize.com.br` capture only `_ga_*`, `_hjSession*`, `_dd_s`, `_gid` — none authenticate. Auth cookies (`KEYCLOAK_IDENTITY`, `KEYCLOAK_SESSION`) live on `sso.agilize.com.br`. See `references/agilize-api-access.md` → "Cookie pitfall".

5. **TOTP seed in JSON `null` vs missing.** If a config file has `"totp_secret": null`, the key is "present" in the JSON mapping but `generate_totp(None)` will crash. The installed script checks `cfg.get("totp_secret")` (truthy, not key-existence) — if you vendor or fork the script, preserve this check.

6. **Sensitive credentials must not be requested in chat.** When setting up the config file or any credential source, prefer asking the user to write the file themselves (or use 1Password / KeePassXC), then signal "pronto" or "atualizei". Never paste passwords, TOTP seeds, or tokens into a multi-user chat channel.

7. **"Investimento anjo" (BR.2.2) is frequently misused for grants and donations.** Angel investment strictly requires equity/ownership counterpart. Grants from international foundations (LUMINATE, Pulitzer, ICFJ, etc.), donations from readers/subscribers (Stripe, PIX), and project funding from tech companies (Microsoft, Google) are **not** angel investment — they are taxable revenue without equity. Correct classifications: BR.1.11 Projetos culturais (institutional grants, `genericEvidence`, no NFS-e), BR.1.10 Direito Autoral (reader/subscriber donations, `genericEvidence`, no NFS-e), BR.1.2 Prestação de serviço pro exterior (only when there IS a service invoice/contract). Always ask the user about the **nature** of the transaction (service vs donation vs grant) before proposing a category — do not assume international payments are service payments. See `references/agilize-category-classification.md`.

8. **Closed periods block all transaction modifications.** When `isClosedPeriod: true` (visible on every transaction object as `canBeUpdated: false`), the Agilize UI shows "Período encerrado" and no creates/updates/deletes are possible via API or UI. Reclassifying historical data requires reopening the period first — a decision that belongs to the accountant, not the agent. Always check `canBeUpdated` before attempting batch operations on a date range.

9. **Category creation is not exposed via API.** POST to `/finance-transaction-categories` returns `PARENT_IS_REQUIRED` regardless of payload structure (`parent`, `parentCategory`, `parentId`, object wrappers, etc.). If a new category is needed (e.g., "Doações recebidas"), it must be created through the Agilize web UI manually. Do not waste time trying API variants — use existing categories or ask the user to create one in the UI.

## Spreadsheet reconciliation

For auditing Agilize categorization against an external cash-flow spreadsheet (Excel/CSV), use the dedicated match + crosstab workflow. The script `scripts/agilize_match_spreadsheet.py` runs the full pipeline (download → parse → greedy match → crosstab → report). Full algorithm and pitfalls documented in `references/agilize-spreadsheet-reconciliation.md`.

```bash
python scripts/agilize_match_spreadsheet.py --xlsx ~/path/to/fluxo.xlsx --year 2025
```

Match strategy is greedy on `(month, abs_amount)` with description as tie-breaker; adjacent-month fallback handles consolidation lag. Output: matched/unmatched JSON + crosstab + (optionally) Markdown report. **Diagnostic only** — never apply fixes during the diagnostic pass.

## Output style

For this domain, respond with concise operational blocks:

- **Diagnóstico** — what is true now.
- **Arquivos/artefatos** — paths created/updated.
- **Conciliação** — totals and mismatches.
- **Pendências** — only the decisions needed to proceed.
- **Próximo passo** — 1–3 concrete actions.

## References

- `references/agilize-api-access.md` — Keycloak/OIDC PKCE authentication flow, login script usage, credential manager integration, and fallback patterns.
- `references/agilize-transaction-splitting.md` — Transaction split API, category mapping, evidence linking after split, and verification.
- `references/agilize-evidence-integrity.md` — NFS-e/tax/invoice/pro-labore evidence rules, duplicate-scan pattern, and pre-link checklist.
- `references/agilize-prolabore-reconciliation.md` — Pro-labore annual reference, partner transfer classification, and split rules.
- `references/agilize-monthly-close.md` — Monthly close workflow, verification checklist, and audit trail.
- `references/agilize-bruno-opencollection.md` — Bruno request format and conversion guide for non-replayable curls.
- `references/agilize-spreadsheet-reconciliation.md` — Read-only diagnostic workflow for matching cash-flow spreadsheets against Agilize transactions, with greedy match algorithm, crosstab analysis, and report structure.
- `references/agilize-category-classification.md` — Full Agilize category tree (root + sub-categories), revenue classification guide for grants/donations/services, evidence requirements per category, and the "Investimento anjo" misuse pattern.

## Scripts

- `scripts/agilize_login.py` — Generic Agilize Keycloak/OIDC PKCE login script. Reads credentials from KeePassXC, environment variables, or a config file. Prints only redacted status metadata. Supports `--verify` and `--api-get` for authenticated reads.
- `scripts/agilize_match_spreadsheet.py` — Match a cash-flow spreadsheet (Excel/CSV) against Agilize transactions for diagnostic reconciliation. Greedy `(month, abs_amount)` match with description-scored tie-breaker; outputs matched/unmatched JSON + crosstab.

## Templates

- `templates/agilize-opencollection.yml` — Bruno OpenCollection root file.
- `templates/agilize-bruno-request.yml` — Bruno request template with bearer auth and placeholder variables.
