# Changelog

## 2026-06-10

- Synced repository skill package with the installed Hermes skill version.
- Fixed `agilize_login.py` env-var credential path (`totp_secret` variable).
- Standardized NFS-e XML upload guidance around the reliable legacy 3-step resource flow.
- Fixed `prolabore-anual` endpoint date suffix from invalid `...T00:00:00P` to `...T00:00:00-0300`.
- Hardened spreadsheet reconciliation outputs: generated artefacts now use mode `0600`, CNPJ is masked in Markdown reports, month-end calculation uses `calendar.monthrange`, and 401 responses trigger a one-time re-auth retry.
- Hardened OneDrive XML acquisition: validates NFS-e XML namespace/status before saving and writes downloaded XMLs with mode `0600`.
- Added `.gitignore` for cache/credential/generated local artefacts.
