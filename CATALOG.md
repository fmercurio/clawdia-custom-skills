# Catálogo de Skills e Packages

> **Arquivo gerado — não edite manualmente.**

`registry/skills-registry.yaml` é a fonte canônica dos metadados; `tools/generate_catalog.py` valida o repositório e renderiza este catálogo.

## Resumo

### Por tipo de artefato
| Tipo de artefato | Quantidade |
| --- | ---: |
| skill | 15 |
| package | 1 |

### Por status
| Status | Quantidade |
| --- | ---: |
| approved | 5 |
| candidate | 11 |
| draft | 0 |
| profile-overlay | 0 |
| deprecated | 0 |
| rejected | 0 |

## Skills aprovadas

| Categoria | Nome | Status | Descrição pública | Link |
| --- | --- | --- | --- | --- |
| note-taking | second-brain-operations | approved | Step-by-step playbook for setting up and operating a PARA-first Second Brain with Hermes — vault creation, semantic search engine, pull/push skills, health-check cron, weekly review, and operational rhythm. | [second-brain-operations](skills/note-taking/second-brain-operations/SKILL.md) |
| productivity | agilize-contabil-ops | approved | Agilize contábil platform operations: Keycloak/OIDC PKCE authentication, finance transaction classification, NFS-e evidence linking, transaction splitting, pro-labore reconciliation, monthly close, and audit workflows. Company-agnostic — works for any Agilize tenant. | [agilize-contabil-ops](skills/productivity/agilize-contabil-ops/SKILL.md) |
| productivity | archiver-contextual-recall | approved | Contextual link recall with deterministic weekly Archiver operational reviews for integrity and curation health. | [archiver-contextual-recall](skills/productivity/archiver-contextual-recall/SKILL.md) |
| social-media | discord-voice-meetings | approved | Build a Discord voice meeting transcription system — capture audio, identify speakers, transcribe via Groq Whisper, generate LLM-powered meeting minutes/atas. Framework-agnostic reference implementation included. | [discord-voice-meetings](skills/social-media/discord-voice-meetings/SKILL.md) |
| software-development | explain-code-change | approved | Generate a source-grounded explanation artifact for code changes with a fact/interpretation split, structured content sections, quiz quality validations, deterministic option shuffling, and a single offline HTML artifact output. | [explain-code-change](skills/software-development/explain-code-change/SKILL.md) |

## Skills candidatas

| Categoria | Nome | Status | Descrição pública | Link |
| --- | --- | --- | --- | --- |
| devops | caprover-deploy | candidate | Automated CapRover deployment via CLI → API → Playwright fallback. Handles app creation, GitHub repo config, build triggering, HTTPS/WebSocket enablement, and post-deploy verification. Generic — no instance-specific data. | [caprover-deploy](skills/devops/caprover-deploy/SKILL.md) |
| mcp | docs-mcp-server-operations | candidate | Generic public skill for deploying and maintaining a shared Docs MCP Server for Hermes, Codex, or other MCP clients. Covers persistent Docker/CapRover deployment, safe public/read-only exposure, embedding provider decisions, dependency scanning, staleness reports, and quality gates against shallow documentation indexes. | [docs-mcp-server-operations](skills/mcp/docs-mcp-server-operations/SKILL.md) |
| note-taking | brain-search | candidate | Generic template — FTS5 + semantic search engine for a PARA-first Second Brain vault. Concept-level queries, keyword search, vault exploration, and index management. Customize vault path and embedding model per deployment. | [brain-search](skills/note-taking/brain-search/SKILL.md) |
| note-taking | markdown-knowledge-vaults | candidate | Class-level workflow for inspecting, validating, and operating Markdown knowledge vaults in Hermes through durable source handling, inspect-first gates, schema and retrieval validation, explicit apply controls, and rollback-safe lifecycle management. | [markdown-knowledge-vaults](skills/note-taking/markdown-knowledge-vaults/SKILL.md) |
| note-taking | pull-brain | candidate | Generic template — recover and load consolidated context from a PARA-first Second Brain vault. Retrieves knowledge in PARA order, uses brain-search for concept-level queries, and separates vault facts from session memory. | [pull-brain](skills/note-taking/pull-brain/SKILL.md) |
| note-taking | push-brain | candidate | Generic template — save, consolidate, and sync a PARA-first Second Brain vault after a meaningful session. Classifies into PARA, writes durable knowledge, runs health-check, commits, pushes, and rebuilds search index. | [push-brain](skills/note-taking/push-brain/SKILL.md) |
| productivity | autonomous-context-to-spec | candidate | Convert ambiguous context into a traceable concept and specification workflow: structured refinement, assumption handling, risk-aware decision gates, vertical slicing, and evidence-backed traceability before any authorized execution. | [autonomous-context-to-spec](skills/productivity/autonomous-context-to-spec/SKILL.md) |
| productivity | nfse-emissor-nacional | candidate | Safe NFS-e draft preparation in the Brazilian Emissor Nacional portal (nfse.gov.br) using Playwright — taker history import, Select2/Chosen widget handling, draft-only workflow with human review stop. | [nfse-emissor-nacional](skills/productivity/nfse-emissor-nacional/SKILL.md) |
| productivity | skill-architecture-workflow | candidate | Hermes-native workflow for deciding whether a recurring need deserves a skill, then designing its scope, trigger contract, progressive disclosure, safety gates, validation, provenance, and promotion path through the governed custom-skills library. | [skill-architecture-workflow](skills/productivity/skill-architecture-workflow/SKILL.md) |
| productivity | topic-channel-soul-routing | candidate | Generic runbook for configuring Telegram topics, Discord channels/threads, or equivalent messaging surfaces as specialist agent souls/profiles while preserving conversation-first behavior and explicit-only Kanban/task intake. | [topic-channel-soul-routing](skills/productivity/topic-channel-soul-routing/SKILL.md) |

## Outras skills governadas

Nenhuma skill com outro status encontrada.

## Packages

| Categoria | Nome | Status | Descrição pública | Link |
| --- | --- | --- | --- | --- |
| note-taking | second-brain-kit | candidate | Hermes-native installable suite for bootstrapping a new Second Brain or connecting an existing Markdown vault, with profile-aware skills, FTS5, health checks, deterministic lifecycle scripts, rollback and optional OKF. | [second-brain-kit](packages/second-brain-kit/README.md) |
