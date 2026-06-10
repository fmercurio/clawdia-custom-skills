# Agilize NFS-e XML/ZIP upload

Use this reference when a user has already emitted NFS-e outside Agilize and asks to upload XML files or a ZIP package into the Agilize platform.

## Endpoint / UI flow that actually imports NFS-e

The visible Agilize import UI (`nfseImportDirectiveCtrl`) does **not** stop at `importacao-lote-nfes`. The working flow is the legacy resource flow:

```http
POST /api/v1/companies/{company_id}/nfses/preimportfromresource
Authorization: Bearer <access_token>
key: <company_cnpj_digits>
Referer: https://app.agilize.com.br/
Accept: application/json, text/plain, */*
Content-Type: multipart/form-data
```

Multipart body uses indexed field names:

```text
resources[0] = <file1.xml>
resources[1] = <file2.xml>
resources[2] = <package.zip>
```

Then create the import resource with the same files:

```http
POST /api/v1/companies/{company_id}/nfseimportresources
```

Finally import from that resource:

```http
POST /api/v1/companies/{company_id}/nfses/importfromresource
Content-Type: application/json

{"nfseImportResource": "<resource.__identity>"}
```

Pitfall: `POST /api/v1/companies/{company_id}/importacao-lote-nfes` with `resources[]` can return HTTP 201 and create a batch, but then process with `quantidadeNotasProcessadas: 0` and no visible NFS-e. Treat that route as a batch/import-log route, not sufficient proof of successful NFS-e import.

## Discovery notes

The legacy Angular service also exposes imported-resource routes:

```text
companies/{company}/nfseimportresources/:resource/:action
GET /nfseimportresources/{id}/download
```

The React uploader response usually includes a batch/import object such as `loteNfe` with an `__identity`. Treat that as the upload handle for later verification.

## Recommended workflow

1. Authenticate via the standard Keycloak/PKCE flow. If the company UUID is not already configured, decode the JWT payload and read the `tenant[0]` claim.
2. Collect only user-specified `.xml` and `.zip` files. Do not upload every XML under a broad home-directory search.
3. Before uploading, create a small manifest: filename, byte size, and SHA-256. Report this manifest without printing XML contents.
4. Validate XML inputs before upload: parse each `.xml`, confirm the root is NFS-e (`http://www.sped.fazenda.gov.br/nfse`), and confirm emitted status (`cStat=100`) when available. Remove failed download artifacts such as HTML error pages saved with `.xml` names.
5. POST all files through the legacy 3-step resource flow: `preimportfromresource` → `nfseimportresources` → `importfromresource`; use indexed multipart fields `resources[0]`, `resources[1]`, ... exactly as the UI does.
6. Verify HTTP 2xx and record the resource/import handle (`resource.__identity` or equivalent response identity).
7. Re-read `/nfses?competencia=YYYY-MM-01T00:00:00&count=3000` for the target competence and confirm note number, amount, and competence. Only treat `importacao-lote-nfes` as auxiliary batch-log evidence, not proof of successful import.

## OneDrive/shared-folder acquisition pattern

When the user supplies a public OneDrive folder link containing XMLs, prefer a deterministic local-browser scrape over manual UI downloading:

1. Use Playwright/headless browser locally, not the remote browser, when you need files written into the agent filesystem.
2. Navigate to the shared link, enter the target dated subfolder (usually the most recent competence month), and click each `.xml` file link to open the preview.
3. Watch network responses for `my.microsoftpersonalcontent.com/.../_layouts/15/download.aspx?UniqueId=...` with `Content-Type: text/xml`; save the response body directly.
4. Map saved files by the visible filename and/or `<nNFSe>` value, not by OneDrive-generated item IDs.
5. Validate root namespace, `<nNFSe>`, and `<cStat>` after saving; only upload validated XMLs.

Avoid relying on `onedrive.live.com/download?resid=...` for shared folders: it often returns 403 or an HTML login/error page without the preview-generated `tempauth` URL. If a test download produced an `.xml` file whose root is XHTML/HTML, delete it before collecting upload files.

## Minimal Python shape

```python
files = []
opened = []
try:
    for path in paths:
        f = open(path, "rb")
        opened.append(f)
        files.append(("resources[]", (os.path.basename(path), f, "application/xml")))
    resp = requests.post(url, headers=headers, files=files, timeout=120)
finally:
    for f in opened:
        f.close()
```

## Pitfalls

- **Use indexed resource fields (`resources[0]`, `resources[1]`, ...), not `file`, `files`, or bare `resources[]`, for the legacy UI import flow.** A different field name may silently fail or be rejected by backend validation.
- **Do not use `/nfses` for upload.** `/nfses` is the listing/detail API; the working upload/import route is the legacy 3-step resource flow.
- **Do not trust batch creation alone.** `importacao-lote-nfes` can show a batch with `__identity`, `createdAt`, `status`, `processado`, and `quantidadeNotasProcessadas`, but `quantidadeNotasProcessadas: 0` means no useful NFS-e import happened.
- **Shared OneDrive direct-download links are brittle.** For public folders, open file previews and capture the `my.microsoftpersonalcontent.com/.../download.aspx?...tempauth=...` XML response, or automate that with Playwright. Direct `onedrive.live.com/download?resid=...` calls may save HTML/403 pages as `.xml`.
- **File Provider / OneDrive visibility is environment-specific.** If OneDrive files are not visible to the agent filesystem due to macOS TCC/File Provider permissions or unsynced account state, ask for an accessible local path, copied ZIP, or share link. Do not conclude OneDrive is generally unavailable.
- **Protect secrets and XML contents.** Upload XMLs as files, compute hashes, but do not dump sensitive invoice XML contents in chat/logs.
