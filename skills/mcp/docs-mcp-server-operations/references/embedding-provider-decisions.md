# Embedding Provider Decisions

`docs-mcp-server` can search without embeddings, but semantic search quality improves when embeddings are enabled. Decide before indexing production data.

## Options

| Option | Environment | Pros | Trade-offs |
|---|---|---|---|
| OpenAI embeddings | `OPENAI_API_KEY` | simple, hosted | usage cost, external dependency |
| OpenAI-compatible endpoint | `OPENAI_API_BASE`, `OPENAI_API_KEY` | can be private/internal | you operate the endpoint |
| No embeddings | none | simplest, no embedding cost | weaker semantic search |

## Model Configuration

Example:

```bash
--embedding-model openai:text-embedding-3-small
```

For OpenAI-compatible services, the model string still commonly uses the `openai:` prefix, but the actual model name must match the provider.

## Vector Dimension Rule

Do not reuse the same store when changing embedding models with incompatible vector dimensions. If changing from one embedding model family to another:

1. stop the server;
2. backup or archive the old store if needed;
3. start with an empty `/data`; or
4. remove/reindex all libraries under the new model.

## Container Network Rule

Inside a container, `localhost` means the container itself. A local workstation embedding server is not reachable through a container-local loopback URL unless explicitly networked. Use a reachable service URL or disable embeddings.

## Secrets Rule

Embedding API keys belong in the platform secret store or environment variables. They must not be committed to:

- Dockerfiles;
- `captain-definition`;
- docs registry YAML;
- skill files;
- issue comments;
- deployment reports.
