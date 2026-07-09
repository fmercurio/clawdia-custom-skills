# Quality Gate and Canary Searches

A docs index can be fresh and still bad. Temporal freshness only says when it was indexed relative to package registry data. It does not prove the source URL had enough useful documentation.

## Suspicious Signals

Treat these as warnings:

- `status == failed`;
- `documentCount == 0`;
- `documentCount <= 5` for a major framework;
- `uniqueUrlCount == 1` for a large documentation site;
- `sourceUrl` points at `npmjs.com/package/*` for a major framework;
- source URL is a redirect, marketing page, or package landing page;
- canary search returns empty or irrelevant results.

## Canary Search Table

| Library | Query |
|---|---|
| `vite` | `import.meta.env` |
| `next` | `server actions` |
| `react` | `useEffect cleanup` |
| `tailwindcss` | `theme variables` |
| `@tanstack/react-query` | `staleTime queryKey` |
| `@tryghost/admin-api` | `custom integration token` |
| `express` | `error handling middleware` |
| `vue` | `computed refs` |

## Quality Workflow

1. Run `list` and inspect counts/source URLs.
2. Run canary searches for high-impact libraries.
3. If the index is shallow but source URL is official, retry scrape and inspect logs.
4. If the source URL is wrong, remove and scrape from a canonical docs URL.
5. Record the remediation as `refresh`, `remove+scrape`, `defer`, or `manual-review`.

## Example Commands

```bash
BASE="http://127.0.0.1:6280"

npx @arabold/docs-mcp-server@2.4.2 list \
  --server-url "$BASE/api" \
  --output json

npx @arabold/docs-mcp-server@2.4.2 search vite "import.meta.env" \
  --server-url "$BASE/api" \
  --output json
```

## Refresh vs Remove + Scrape

Use `refresh` only when the current source is canonical and already had good coverage.

Use `remove` + `scrape` when:

- the current source is a package registry README;
- the documentation domain moved;
- the scrape captured only a few documents;
- the canary search failed;
- the index is built from the wrong package name or alias.
