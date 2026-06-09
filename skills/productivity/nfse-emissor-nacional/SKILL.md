---
name: nfse-emissor-nacional
description: >
  Use when automating Brazilian NFS-e draft preparation in the Emissor Nacional
  portal (nfse.gov.br) with Playwright — filling forms, importing taker data from
  portal history, and stopping before final issuance for human review.
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [nfse, brazil, tax, playwright, browser-automation, safe-draft, emissor-nacional]
---

# NFS-e Emissor Nacional Draft Automation

## Overview

This skill packages a safe workflow for preparing Brazilian NFS-e drafts in the **Emissor Nacional** web portal using Playwright. It is designed for agents that must fill forms, reuse data already stored in the portal, and stop at the review screen so a human can inspect and issue manually.

The core rule is: **prepare drafts only; never click the final issue/emit button.**

The skill is intentionally generic. It does not include company names, taxpayer IDs, client data, certificate paths, portal credentials, or service descriptions. Consumers must provide their own configuration and credentials locally.

## Prerequisites

- **Playwright** installed (`pip install playwright && playwright install chromium`)
- A supported browser (Chromium/Chrome) available on the host
- Portal credentials stored in an approved secret manager (env vars, KeePassXC, keychain, etc.)
- A local config file based on `templates/config.example.yaml` filled with organization-specific data

## When to Use

Use this skill when:

- A user wants to automate NFS-e draft creation in `nfse.gov.br/EmissorNacional`.
- The desired output is a portal draft ready for human review, not automatic fiscal issuance.
- Customer/taker data should be imported from the portal history to pull address, phone, and email.
- The portal uses jQuery/Chosen/Select2-style widgets that require real UI interaction and validation.

Do **not** use this skill when:

- The user asks to issue invoices automatically without an explicit, separate safety policy.
- You only need to generate XML via official API/webservice.
- Credentials, certificates, or taxpayer data are missing and cannot be retrieved from an approved local secret store.

## Safety Contract

1. **Never emit automatically.** Stop at the final review/confirmation step.
2. **Never type or expose secrets.** Load portal credentials from the user's approved secret manager or environment.
3. **Never invent fiscal data.** Values, descriptions, tax codes, and taker IDs must come from user-provided config or validated source systems.
4. **Never rely on DOM injection alone.** For portal widgets, use real UI interactions and then read back field values.
5. **Validate before advancing.** Each step must verify that mandatory fields are populated and no visible validation errors remain.
6. **Capture evidence.** Save screenshots or logs proving each draft reached the review step.

## Generic Portal Flow

### Step 0 — Configuration

Create a local config from `templates/config.example.yaml` and fill it with organization-specific data outside the skill package.

Recommended fields:

- `competency`: `YYYY-MM` — the billing period for all drafts in this run
- portal login source: secret manager entry or environment variable names
- customers: key, legal name, CNPJ/CPF, default value, optional per-customer service description and tax overrides
- service municipality and service code
- NBS or service classification when required
- tax selections and rates

### Step 1 — Login

1. Open `https://www.nfse.gov.br/EmissorNacional/Login`.
2. Fill credentials from the approved local secret source.
3. Submit and wait for the Dashboard.
4. Verify the current URL no longer contains `/Login`.

### Step 2 — Open New Complete NFS-e

Direct navigation to some portal routes may produce 403. Prefer clicking through the portal UI:

1. From Dashboard, open the NFS-e menu.
2. Click **Emissão completa** / `/EmissorNacional/DPS/Pessoas`.
3. Wait until the Pessoas step is rendered.

### Step 3 — Pessoas

1. Set competency date first. Many portal handlers use this value to load provider data.
2. Select emitente/prestador as appropriate.
3. Wait for provider/prestador fields to load.
4. Select taker location, usually **Brasil** for domestic takers.
5. Open taker history using the **Últimos Tomadores** button:

```text
#btn_Tomador_Inscricao_historico
```

6. The button sends a POST like:

```text
POST /emissornacional//DPS/Pessoas/ModalHistoricoPessoas/
body: tpPessoa=Tomador&tpHistorico=1
```

7. In the modal `#modalHistoricoPessoas`, locate the table row whose `.cnpj` text matches the configured taker CNPJ/CPF.
8. Click the row's radio label using real Playwright click. Setting `radio.checked = true` via JavaScript is not enough; the **Importar** button may remain disabled.
9. Click `#btnImportar`.
10. Validate that these fields were populated:

```text
Tomador_Inscricao
Tomador_Nome
Tomador_Telefone
Tomador_Email
Tomador_InformarEndereco
Tomador_EnderecoNacional_CEP
Tomador_EnderecoNacional_CodigoMunicipio
Tomador_EnderecoNacional_NomeMunicipio
Tomador_EnderecoNacional_Bairro
Tomador_EnderecoNacional_Logradouro
Tomador_EnderecoNacional_Numero
Tomador_EnderecoNacional_Complemento
```

Only use CNPJ lookup/manual fallback if the taker is not in history, and clearly report that address/contact data may require manual review.

### Step 4 — Serviço

1. Select the service municipality through the real Select2/Chosen UI.
2. Select the service code through the real widget.
3. Set non-incidence/export/immunity flags according to the user's config.
4. Fill the service description from config.
5. Select NBS/classification if required.
6. Read back hidden and visible fields before advancing.

### Step 5 — Valores

1. Fill service value.
2. Set ISSQN retention and municipal benefit flags according to config.
3. Set federal PIS/COFINS situation and retention selections.
4. Set tax value mode and rate when applicable.
5. Read back all key fields and visible validation errors before advancing.

### Step 6 — Review / Draft Ready

1. Advance to the final review screen.
2. Verify body text indicates the review/emission step.
3. Save screenshot evidence.
4. Stop. Do not click **Emitir NFS-e**.
5. Report the draft IDs/clients and screenshot paths to the user.

## Playwright Patterns

### Click-through navigation rather than direct goto

```python
page.evaluate("""() => {
  const menu = document.querySelector('.dropdown-toggle, a[href*="Dashboard#"]');
  if (menu) menu.click();
}""")
page.wait_for_timeout(500)
page.evaluate("""() => {
  const link = document.querySelector('a[href="/EmissorNacional/DPS/Pessoas"]');
  if (link) link.click();
}""")
```

### Import taker from history

```python
def only_digits(value: str) -> str:
    return ''.join(ch for ch in (value or '') if ch.isdigit())


def import_taker_from_history(page, taker_tax_id_digits):
    page.click('#btn_Tomador_Inscricao_historico', timeout=10000)
    page.wait_for_selector('#modalHistoricoPessoas', timeout=10000)

    row_idx = page.evaluate("""taxId => {
      const only = s => (s || '').replace(/\\D/g, '');
      const rows = Array.from(document.querySelectorAll('#modalHistoricoPessoas tbody tr'));
      const idx = rows.findIndex(tr => only(tr.querySelector('.cnpj')?.textContent) === taxId);
      return {idx, rows: rows.map(r => r.innerText.trim()).filter(Boolean)};
    }""", taker_tax_id_digits)

    if row_idx['idx'] < 0:
        page.locator('#modalHistoricoPessoas button:has-text("Fechar")').click(timeout=3000)
        return {"ok": False, "rows": row_idx.get('rows', [])}

    row = page.locator('#modalHistoricoPessoas tbody tr').nth(row_idx['idx'])
    row.locator('label').click(timeout=5000)  # real click enables Importar
    page.wait_for_timeout(500)

    if page.evaluate("() => document.getElementById('btnImportar')?.disabled"):
        return {"ok": False, "error": "Import button stayed disabled"}

    page.click('#btnImportar', timeout=10000)
    page.wait_for_timeout(2500)

    values = page.evaluate("""() => Object.fromEntries([
      'Tomador_Inscricao', 'Tomador_Nome', 'Tomador_Telefone', 'Tomador_Email',
      'Tomador_InformarEndereco', 'Tomador_EnderecoNacional_CEP',
      'Tomador_EnderecoNacional_CodigoMunicipio', 'Tomador_EnderecoNacional_NomeMunicipio',
      'Tomador_EnderecoNacional_Bairro', 'Tomador_EnderecoNacional_Logradouro',
      'Tomador_EnderecoNacional_Numero', 'Tomador_EnderecoNacional_Complemento'
    ].map(id => {
      const el = document.getElementById(id);
      return [id, el ? (el.type === 'checkbox' ? el.checked : el.value) : null];
    }))""")

    ok = only_digits(values.get('Tomador_Inscricao')) == taker_tax_id_digits
    ok = ok and bool(values.get('Tomador_Nome')) and bool(values.get('Tomador_EnderecoNacional_CEP'))
    return {"ok": ok, "values": values}
```

### Validation helper

```python
def visible_validation_errors(page):
    return page.evaluate("""() => Array.from(document.querySelectorAll(
      '.field-validation-error, .validation-summary-errors, .alert-danger, .text-danger'
    )).map(e => e.innerText.trim()).filter(Boolean)""")
```

## Draft Deletion / Rebuild Pattern

When the user explicitly asks to rebuild drafts:

1. Open the Dashboard or Rascunhos list through portal navigation.
2. Enumerate rows and capture current IDs, taker CNPJ/CPF, competency, and text.
3. Delete only rows matching the configured targets and competency.
4. Use the portal's own endpoint only after confirming the IDs are from the visible table:

```text
POST /emissornacional/Rascunhos/Excluir/
body: id=<visible-row-data-id>
```

5. Verify in a fresh Dashboard session that old drafts disappeared.
6. Recreate drafts one by one and verify each reaches review.
7. Verify the final Dashboard shows exactly the expected drafts.

**Recovery on failure:** If the rebuild process is interrupted mid-way, the agent must report which drafts were deleted and which were recreated, so the user can decide whether to retry or complete manually.

## Common Pitfalls

1. **Typing only CNPJ instead of importing history.** The portal may not fill phone, email, and address. Always prefer `btn_Tomador_Inscricao_historico` for recurring takers.
2. **Setting radio checked via JavaScript.** The Import button may remain disabled. Use a real Playwright click on the label.
3. **Direct URL navigation.** Some routes return 403 unless reached through UI click handlers. Prefer click-through navigation.
4. **Select2/Chosen DOM injection.** Creating options manually can leave hidden values inconsistent. Interact with the widget and read back hidden IDs.
5. **Assuming the draft list URL is reliable.** The Dashboard may be a more stable verification surface than direct `/Notas/Rascunhos` navigation.
6. **Forgetting the safety stop.** The automation must halt before final issuance and require human action.
7. **Leaking taxpayer data into reusable skills.** Keep real taxpayer IDs, names, emails, certificate paths, and credentials in local config only.
8. **Interrupted rebuild without reporting.** If a batch rebuild fails mid-way, the user must know exactly which drafts were deleted vs. recreated.

## Verification Checklist

- [ ] Playwright and Chromium are installed on the host.
- [ ] Credentials were loaded from a local secret source, not embedded in code.
- [ ] Competency (`YYYY-MM`) is set from config before creating drafts.
- [ ] New draft opened through portal UI and not by brittle direct URL when blocked.
- [ ] Competency date set before loading provider data.
- [ ] Taker imported from history and address/contact fields validated.
- [ ] Service municipality/code selected via real UI interaction and read back.
- [ ] Values/taxes filled and read back.
- [ ] No visible validation errors before each advance.
- [ ] Draft reached review/emission step.
- [ ] Screenshot evidence saved.
- [ ] Automation stopped before final issuance.
- [ ] Final dashboard/list shows the expected draft set.
