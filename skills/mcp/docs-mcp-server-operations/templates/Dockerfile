FROM node:22-bookworm-slim

ENV NODE_ENV=production \
    DOCS_MCP_TELEMETRY=false \
    PORT=6280

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    jq \
    bash \
    python3 \
    python3-yaml \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN npm install -g @arabold/docs-mcp-server@2.4.2

RUN useradd -m -u 10001 app \
 && mkdir -p /app/scripts /app/templates /data \
 && chown -R app:app /app /data

WORKDIR /app

COPY --chown=app:app scripts/ /app/scripts/
COPY --chown=app:app templates/ /app/templates/

USER app

EXPOSE 6280

CMD [
  "docs-mcp-server", "server",
  "--protocol", "http",
  "--host", "0.0.0.0",
  "--port", "6280",
  "--store-path", "/data",
  "--resume",
  "--telemetry=false"
]
