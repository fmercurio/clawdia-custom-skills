# ClawdIA Custom Skills Repository

Repositório curado de skills customizadas para o ambiente Hermes/ClawdIA.

## Visão geral

Este repo é a **fonte canônica** das skills desenvolvidas, melhoradas ou validadas pela equipe. Skills aqui passaram por auditoria de segurança, conformidade de frontmatter e aprovação humana antes de serem instaladas no runtime Hermes.

## Estrutura

```
custom-skills/
├── README.md                        # Este arquivo
├── skills/                          # Skills aprovadas, organizadas por categoria
│   └── <category>/
│       └── <skill-name>/
│           ├── SKILL.md             # Skill principal
│           ├── references/          # Documentação de referência
│           ├── templates/           # Templates reutilizáveis
│           └── scripts/             # Scripts operacionais
├── packages/                        # Suítes instaláveis com múltiplas skills e lifecycle próprio
│   └── <package-name>/
│       ├── README.md                 # Documentação humana do pacote
│       ├── manifest.yaml             # Versões, capacidades e componentes
│       ├── skills/                   # Skills Hermes-native instaladas pelo pacote
│       ├── scripts/                  # Bootstrap, doctor, install, rollback e export
│       └── tests/                    # Unitários e clean-room E2E
├── registry/
│   └── skills-registry.yaml         # Registro de todas as skills (status, proveniência, decisão)
├── docs/
│   └── governance.md                # Política de governança
└── tools/
    └── validate_skill.py            # Validador de frontmatter e estrutura
```

## Fluxo de trabalho

1. **Proposta** → alguém sugere uma skill (zip, link, ideia)
2. **Inspeção** → Hermes audita segurança, conformidade, diffs
3. **Parecer** → relatório técnico com recomendação de status
4. **Aprovação** → Felippe aprova/rejeita/adapta
5. **Instalação** → skill copiada para `~/.hermes/skills/` (runtime)
6. **Registro** → entrada atualizada no `skills-registry.yaml`

## Status de skills

| Status | Significado |
|---|---|
| `draft` | Criada, ainda não testada |
| `candidate` | Avaliada, aguardando aprovação |
| `approved` | Aprovada para uso no runtime |
| `profile-overlay` | Override deliberado para um SOUL/profile |
| `deprecated` | Substituída, mantida por histórico |
| `rejected` | Avaliada e descartada |

## Regras

- **Nunca instalar automaticamente** — toda instalação requer aprovação
- **Toda skill precisa de**: SKILL.md, gatilhos claros, pitfalls, verificação
- **Proveniência obrigatória**: origem, autor, data, motivo
- **Segurança primeiro**: scripts read-only por padrão, sem hardcoded secrets
- **Company-agnostic**: valores específicos via config, nunca hardcoded
- **Pacotes permanecem candidates** até que clean-room E2E, checksums e revisão humana passem
