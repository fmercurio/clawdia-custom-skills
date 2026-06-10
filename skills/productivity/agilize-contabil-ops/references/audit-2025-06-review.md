# Audit Review — June 2025

## Applied fixes (already patched in installed skill)

- **C1**: `agilize_login.py` line 118 — `totp_seed` NameError fixed to `totp_secret`
- **C3**: SKILL.md — contradictory NFS-e upload guidance reconciled: all sections now recommend legacy 3-step resource flow as primary method
- **M1**: `prolabore-anual` URL suffix `P` corrected to `-0300`
- **Pitfall #10**: rewritten to warn about `importacao-lote-nfes` silent failure instead of recommending it

## Pending improvements (not yet applied)

### Medium priority

- `agilize_match_spreadsheet.py` — file permissions hardened to `0o600` via `write_secure()`.
- `agilize_match_spreadsheet.py` — CNPJ printed in report output. Consider masking or marking report as sensitive.
- `agilize_match_spreadsheet.py` — leap year/month-end logic fixed with `calendar.monthrange()`.
- `agilize_match_spreadsheet.py` — `sys.path.insert` for `openpyxl` happens after import attempt. Restructure to insert path before import.
- `agilize_match_spreadsheet.py` — report template has literal `{year}` instead of f-string on line ~361.
- `agilize_login.py` — no token refresh mechanism. Spreadsheet script does 12 sequential monthly fetches and will fail when token expires (~10 min).
- `download_onedrive_shared_xmls.py` — only checks `<?xml` prefix, not NFS-e namespace. Should validate `http://www.sped.fazenda.gov.br/nfse` namespace.
- SKILL.md has significant redundancy with reference docs (PKCE flow, split payload, evidence rules, monthly checklist duplicated). Consider trimming SKILL.md to concise index with "See references/..." pointers.

### Low priority

- Add `.gitignore` to skill root (`__pycache__/`, `*.pyc`, `.DS_Store`).
- `Bearer ***` in header examples lacks explicit redaction note for new readers.

## Repo sync status

- Installed skill and zip are identical (15 files, MD5 matches).
- GitHub repo (`~/.hermes/custom-skills/skills/productivity/agilize-contabil-ops/`) is behind:
  - Missing: `references/agilize-nfse-xml-upload.md`, `scripts/download_onedrive_shared_xmls.py`
  - SKILL.md is older version (16.9 KB vs 21.4 KB + patches above)
- After applying pending fixes, sync installed → repo with `git` push.
