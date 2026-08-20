# Creative Production Orchestration

Skill Hermes-native e provider-neutral para coordenar pedidos recorrentes de produção criativa sem transformar o agente em um instalador de fornecedores ou publicador automático.

## O que cobre

- direção e QA de sistemas de marca;
- visuais de produto, capas, thumbnails e peças de campanha;
- roteamento para ferramentas e skills locais já aprovadas;
- gates explícitos para uploads, identidade, custo e distribuição;
- pré-produção de vídeo quando não houver capacidade de vídeo aprovada.

## O que não faz

Não instala CLIs, não autentica contas, não compra créditos, não envia ativos a terceiros por padrão, não treina identidade e não publica/deploya conteúdo sem confirmação específica.

## Conteúdo

- `SKILL.md` — contrato de ativação, fluxo, gates, QA e limites.
- `references/` — roteamento e proveniência da adaptação.
- `templates/` — brief mínimo e checklist de QA reutilizáveis.

Valide com:

```bash
python3 tools/validate_skill.py skills/creative/creative-production-orchestration/SKILL.md
git diff --check
```
