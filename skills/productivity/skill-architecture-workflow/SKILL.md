---
name: skill-architecture-workflow
description: "Use when deciding whether a recurring workflow should become a Hermes skill, designing a new skill before authoring it, or adapting an external skill into the governed ClawdIA/Hermes library. Produces scope, triggers, architecture, validation, and promotion criteria. Do not use for a one-off answer, direct runtime installation, or writing an implementation before the workflow is understood."
version: 0.1.0
author: Skills Lab (adapted from Felipe Rodrigues' skill-architect)
license: CC-BY-4.0
metadata:
  hermes:
    tags: [skills, skill-design, discovery, governance, validation, progressive-disclosure]
    related_skills: [hermes-agent-skill-authoring, hermes-agent, software-development-workflows]
---

# Arquitetura de Skills para Hermes / ClawdIA

## Propósito

Use esta skill para transformar uma necessidade recorrente em um desenho de skill reutilizável, seguro e governado. Ela decide **se uma skill é necessária**, como ela deve ser acionada, quais arquivos e ferramentas precisa, como validar o resultado e quando promovê-la para o runtime.

Uma skill ruim é pior do que nenhuma: pode disparar no momento errado, competir com outras skills, induzir ações inseguras ou armazenar procedimentos obsoletos.

## Quando usar

Use quando o usuário quer:

- criar uma nova skill ou tornar um workflow recorrente consistente;
- adaptar uma skill externa para Hermes/ClawdIA;
- definir gatilhos, anti-gatilhos e limites de uma capacidade;
- escolher entre skill, SOUL, prompt, template, script, MCP ou subagente;
- preparar uma skill candidata para o repositório canônico e registry;
- revisar a arquitetura de uma skill antes de implementá-la.

Não use quando:

- a resposta é uma orientação pontual sem repetição provável;
- o problema é apenas uma alteração curta em uma skill já existente;
- o usuário já forneceu um procedimento completo, seguro e aprovado e pediu apenas sua implementação;
- a necessidade é criar um subagente/profile, uma decisão de arquitetura de software ou um PRD de produto.

## Princípios

1. **Entender antes de automatizar.** Use o contexto já disponível — conversa, SOUL, arquivos, Segunda Cérebro e skills existentes — antes de perguntar. Pergunte apenas o que muda escopo, risco, ferramentas, destino ou critério de aceite.
2. **Uma capacidade, uma responsabilidade.** Não criar skills sobrepostas quando uma skill existente pode receber uma extensão pequena.
3. **Fonte canônica antes de runtime.** Para skills reutilizáveis, o repositório `~/.hermes/custom-skills/` é a fonte governada; a instalação em `~/.hermes/skills/` depende de aprovação e validação.
4. **Gatilhos e anti-gatilhos são contrato.** A descrição deve dizer quando carregar e, principalmente, quando não carregar.
5. **Divulgação progressiva.** `SKILL.md` contém o workflow mínimo; referências, templates e scripts entram apenas quando necessários.
6. **Segurança e verificação fazem parte do design.** Se uma capacidade mexe com dados, produção, credenciais ou sistemas externos, ela precisa de gates, limites e provas de execução.
7. **Nenhuma evidência, nenhuma promoção.** A skill só sai de candidata após revisão, validação e uso representativo.

## Fase 0 — Pré-flight: Skill, SOUL, Prompt ou Ferramenta?

Antes de desenhar uma skill, classifique a necessidade:

| Necessidade | Melhor mecanismo inicial |
|---|---|
| Identidade, tom, limites permanentes de um especialista | SOUL/profile |
| Regra curta e específica de um projeto | `AGENTS.md`, instrução de projeto ou prompt |
| Ação determinística repetida | Script testável, chamado por skill |
| Acesso a sistema externo | Tool/MCP + skill que define o workflow seguro |
| Workflow recorrente com decisões, pitfalls e validação | Skill |
| Trabalho isolado e profundo por especialidade | Subagente/profile |

Se o resultado não justificar manutenção, descoberta e testes futuros, não criar uma skill. Registrar a orientação curta no lugar mais simples.

## Fase 1 — Descoberta mínima suficiente

### 1. Recuperar o que já existe

1. Verificar skills que já cubram parte do problema.
2. Consultar contexto canônico quando a capacidade depender de domínio, cliente, produto ou decisão anterior.
3. Para fonte externa, inspecionar em diretório temporário antes de copiar qualquer arquivo ou executar script.
4. Identificar se a proposta é interna, template público, candidate, overlay de profile ou extensão de uma skill existente.

### 2. Definir o problema

Registrar, em linguagem concreta:

```markdown
Resultado desejado:
Workflow atual:
Dor/risco atual:
Quem usa:
Frequência e gatilho:
Ferramentas/dados envolvidos:
O que nunca deve acontecer:
Como saberemos que funcionou:
```

### 3. Casos de uso e limites

Definir pelo menos dois cenários positivos e dois negativos:

| Tipo | Exemplo | Resultado esperado |
|---|---|---|
| Deve carregar | Pedido recorrente diretamente coberto | Skill é usada e entrega o workflow |
| Deve carregar | Variação informal/parafraseada | Skill ainda é encontrada |
| Não deve carregar | Pedido vizinho, mas de outra competência | Outra skill ou resposta normal assume |
| Não deve carregar | Pergunta genérica/one-off | Não cria burocracia nem força workflow |

**Saída da fase:** problema, usuários, riscos, casos positivos/negativos e sucesso definidos.

## Fase 2 — Arquitetura

### 1. Escolher o padrão dominante

| Padrão | Use quando | Cuidado principal |
|---|---|---|
| Workflow sequencial | Passos dependem uns dos outros | Validar cada gate e prever rollback |
| Coordenação multi-serviço | Vários MCPs, APIs ou ferramentas participam | Não assumir que ferramentas estão disponíveis |
| Refinamento iterativo | Qualidade melhora por revisão | Definir critério de parada |
| Seleção contextual | A ferramenta certa depende do input | Decision tree sem sobreposição e com fallback |
| Inteligência de domínio | Valor está nas regras/especialidade | Manter fonte e revisão contra conhecimento obsoleto |

O desenho pode combinar padrões, mas deve declarar o principal.

### 2. Definir formato e disclosure

```text
skill-name/
├── SKILL.md                 # Gatilhos, workflow, pitfalls e validação
├── references/              # Conhecimento longo, políticas, APIs e exemplos densos
├── templates/               # Artefatos reutilizáveis de saída
├── scripts/                 # Checagens determinísticas e seguras
└── tests/                   # Testes para comportamento que não pode regredir
```

Use `references/` quando o material de apoio não precisa entrar em toda execução. Use `scripts/` apenas para lógica determinística, revisável e testável — nunca para esconder decisões, credenciais ou ações irreversíveis.

### 3. Definir limites operacionais

Toda skill que fizer mais do que leitura deve declarar:

- pré-requisitos e discovery read-only;
- ações que exigem confirmação humana;
- dados que não podem ser armazenados nem exibidos;
- ferramentas autorizadas e fallback quando indisponíveis;
- validação posterior à ação;
- critérios de parada/escalonamento.

**Saída da fase:** padrão, estrutura de arquivos, ferramenta/credenciais, limites e mecanismo de validação definidos.

## Fase 3 — Contrato de ativação

Escrever a descrição em três partes:

```text
Use quando [capacidade + sinais concretos do usuário].
Não use para [competências adjacentes ou pedidos incompatíveis].
```

Critérios:

- usar linguagem que o usuário realmente diria;
- incluir termos de domínio, sistemas e tipos de arquivo quando relevantes;
- declarar anti-gatilhos onde houver risco de colisão;
- evitar descrição tão ampla que intercepte conversas normais;
- evitar depender apenas de um comando exato.

Antes de escrever o corpo, simular os quatro cenários da Fase 1. Refinar a descrição se qualquer um deles for ambíguo.

## Fase 4 — Especificação antes da implementação

Produzir uma especificação curta:

```markdown
# <nome da skill>

## Objetivo

## Quando usar

## Quando não usar

## Pré-requisitos

## Workflow

## Gates de segurança e confirmação

## Ferramentas e arquivos de apoio

## Validação

## Casos de teste de gatilho

## Critério de promoção
```

Se a spec revelar que o workflow cabe em uma instrução curta ou numa skill existente, parar e escolher a alternativa mais simples.

## Fase 5 — Implementação Hermes-native

Quando a arquitetura estiver aprovada:

1. Criar ou atualizar a skill no repositório canônico em `~/.hermes/custom-skills/`.
2. Usar frontmatter compatível com Hermes: `name`, `description`, `version`, `author`, `license` e `metadata.hermes`.
3. Usar `SKILL.md` para gatilhos, passos, pitfalls e checklist; mover profundidade para arquivos vinculados.
4. Incluir atribuição e licença quando o material vier de fonte externa.
5. Não instalar no runtime nem copiar para profiles sem aprovação explícita para esse estágio.
6. Atualizar `registry/skills-registry.yaml` com fonte, status, auditoria, paths e critério de promoção.

Para skills externas, nunca executar scripts automaticamente. Inspecionar antes; adaptar comandos, paths e ferramentas para Hermes.

## Fase 6 — Validação e promoção

### Validação mínima

- frontmatter Hermes válido;
- nome e descrição coerentes;
- referências existentes e chamadas sob condição clara;
- scripts examinados, sem secrets/hardcodes/efeitos indevidos;
- testes executados quando houver código;
- cenários de trigger e anti-trigger revisados;
- workflow exercitado até evidência real quando envolver ferramenta externa.

### Status no registry

| Status | Uso |
|---|---|
| `draft` | Ideia ainda sem arquitetura suficiente |
| `candidate` | Arquitetura/artefato pronto para revisão, sem promoção ao runtime |
| `approved` | Revisado, validado e autorizado como capacidade reutilizável |
| `profile-overlay` | Exceção deliberada para um profile/especialista |
| `deprecated` | Mantido para migração, sem novo uso |
| `rejected` | Avaliado e descartado, com motivo registrado |

### Promoção

Promover `candidate` para `approved` somente quando houver:

1. revisão de segurança e compatibilidade;
2. validação estrutural e, se aplicável, testes reais;
3. decisão humana quando a skill cria efeitos externos, acessa dados sensíveis ou vira capacidade compartilhada;
4. instalação/runtime e profile matrix atualizados de forma explícita.

## Pitfalls

1. **Criar skill para todo pedido.** Uma orientação pontual não merece custo permanente de descoberta/manutenção.
2. **Copiar catálogo externo diretamente.** Conteúdo, paths, tools e suposições podem não funcionar no Hermes.
3. **Descrição sem anti-gatilho.** A skill passa a competir com capacidades próximas.
4. **Pular discovery apesar de ambiguidade material.** Pergunte sobre risco, destino e sucesso; não faça entrevista desnecessária.
5. **Misturar regra de negócio e automação não testável.** Lógica determinística deve ser script revisável; julgamento deve ser instrução clara.
6. **Promover sem evidência.** “Parece bom” não substitui execução, validação e revisão.
7. **Guardar segredos na skill.** Credenciais pertencem a `.env`, gerenciador de segredos ou fluxo aprovado, nunca a exemplos ou scripts.

## Checklist de entrega

- [ ] A necessidade realmente requer uma skill.
- [ ] Casos positivos e negativos foram definidos.
- [ ] Existe uma descrição precisa com anti-gatilhos.
- [ ] O padrão de arquitetura e disclosure foram escolhidos.
- [ ] Ferramentas, dados sensíveis e confirmações foram mapeados.
- [ ] O artefato está no repositório canônico com fonte/licença registradas.
- [ ] A validação Hermes e os testes aplicáveis passaram.
- [ ] O registry registra status, risco e critério de promoção.
- [ ] Instalação no runtime/profile ocorreu somente se aprovada.

## Proveniência

Esta skill adapta os princípios de descoberta, arquitetura, disclosure progressivo, gatilhos e validação de `skill-architect`, de Felipe Rodrigues, publicada no catálogo Tech Leads Club sob CC-BY-4.0:

- https://agent-skills.techleads.club/skills/skill-architect/
- https://github.com/tech-leads-club/agent-skills

A adaptação remove o instalador externo e substitui ferramentas/suposições não-Hermes por governança, registry e validação Hermes-native.
