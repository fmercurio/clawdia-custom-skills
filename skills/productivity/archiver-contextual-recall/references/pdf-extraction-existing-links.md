# Archiver PDF extraction and existing-link enrichment

# This note captures the durable workflow for improving Archiver recall when existing links are already indexed with weak `body_only` context.

## Problem

The first contextual backfill populated `link_contexts` from existing Markdown/body context only. That was safe but weak for PDFs: PDF links stayed `context_status='body_only'`, so contextual recall did not know the actual document contents.

## Durable pattern

1. Keep archival lossless: never fail item/link creation just because extraction fails.
2. Add extractor support in `scripts/archiver_extract_context.py`, not in the backfill script.
3. Make extractor dependencies optional:
   - HTML/plain text: stdlib `urllib.request` path.
   - PDFs: optional `PyMuPDF` / `fitz` path.
4. Make missing optional dependency body-only compatible:
   - `context_status='unsupported_content_type'`
   - `extractor='pymupdf'`
   - `error='pymupdf_not_installed'`
5. Re-run existing links through:
   ```bash
   python3 scripts/backfill_link_contexts.py --dry-run --extract-existing --json
   python3 scripts/backfill_link_contexts.py --extract-existing --json
   ```
6. Do not use `--force` unless intentionally re-fetching rows already marked `extracted`.

## PDF extractor implementation shape

In `archiver_extract_context.py`:

- Detect PDFs by `Content-Type: application/pdf` or URL path ending in `.pdf`.
- Read bounded bytes; a larger cap than HTML is useful for PDFs, e.g. `pdf_max_bytes=8_000_000`, while keeping HTML/text at the smaller existing cap.
- Dynamically import `fitz` with `import_module('fitz')` so the module still loads without PyMuPDF.
- Extract metadata title if available; otherwise derive a title from the first extracted text.
- Extract only a bounded page count / text amount, e.g. first 12 pages or ~20k chars.
- Truncate stored `summary` and `extracted_text` to keep SQLite/context compact.
- Suppress noisy recoverable MuPDF warnings/errors if available:
  ```python
  tools = getattr(fitz, 'TOOLS', None)
  if tools is not None:
      if hasattr(tools, 'mupdf_display_errors'):
          tools.mupdf_display_errors(False)
      if hasattr(tools, 'mupdf_display_warnings'):
          tools.mupdf_display_warnings(False)
  ```

## Tests to add

Use fake network and fake `fitz`; do not hit real PDFs in tests.

- `extract_url_context()` returns `context_status='extracted'` and `extractor='pymupdf'` for a fake PDF response with fake PyMuPDF pages.
- Missing PyMuPDF returns `context_status='unsupported_content_type'`, `extractor='pymupdf'`, `error='pymupdf_not_installed'`, and no extracted text.
- Existing HTML/plain tests must continue passing.

Validation command:

```bash
python3 -m py_compile scripts/archiver_extract_context.py scripts/backfill_link_contexts.py scripts/tests/test_archiver_scripts.py
PYTHONPATH=. python3 -m pytest scripts/tests/test_archiver_scripts.py -q
```

## Real-run interpretation

After installing PyMuPDF and rerunning extraction backfill, PDFs should move from `body_only` to `extracted` with `extractor='pymupdf'`.

Non-PDF unsupported endpoints (e.g. JSON API URLs) can legitimately remain `body_only`; 403/404 pages remain `failed` until a future resolver/alternate URL strategy handles them.
