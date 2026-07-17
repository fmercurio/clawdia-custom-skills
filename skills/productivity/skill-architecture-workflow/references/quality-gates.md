# Quality Gates — Skill Architecture Workflow

Use esta referência durante a Fase 6, depois de escrever ou adaptar uma skill.

## 1. Scorecard de descrição

Pontue cada item de 1 a 5. Skills candidatas devem atingir ao menos 4 em todos os itens ou registrar a lacuna no registry.

| Critério | Pergunta |
|---|---|
| Capacidade | Está claro o resultado que a skill entrega? |
| Trigger | O agente identifica pedidos reais e variações? |
| Anti-trigger | Está claro o que não deve carregar a skill? |
| Linguagem do usuário | A descrição usa termos que o usuário realmente empregaria? |
| Convivência | A skill evita colisão com SOULs, tools e skills próximas? |

## 2. Testes de ativação

Preparar pelo menos seis frases antes da promoção:

```markdown
## Deve carregar
1. <pedido direto>
2. <pedido parafraseado>
3. <pedido informal ou incompleto>

## Não deve carregar
1. <capacidade adjacente>
2. <pergunta one-off>
3. <pedido que pertence a outra skill>
```

Para cada frase, registrar: esperado, mecanismo selecionado, resultado real e ajuste necessário.

## 3. Matriz de segurança

| Pergunta | Se sim |
|---|---|
| Escreve, envia, apaga ou publica algo? | Declarar confirmação, escopo e verificação pós-ação. |
| Toca produção, dinheiro, documentos legais ou dados pessoais? | Exigir gate humano e evidência de escopo. |
| Precisa de credencial? | Usar env/secret manager; proibir exemplos e argumentos com secret. |
| Executa script externo? | Inspecionar antes, testar em ambiente controlado e documentar efeitos. |
| Opera múltiplos profiles/tenants? | Declarar fronteira de profile/tenant e evitar descoberta global implícita. |

## 4. Comandos de validação

No repositório canônico:

```bash
cd ~/.hermes/custom-skills
python3 tools/validate_skill.py skills/<categoria>/<skill>/SKILL.md --json
```

Quando houver scripts ou testes:

```bash
python3 -m py_compile skills/<categoria>/<skill>/scripts/*.py
python3 -m pytest skills/<categoria>/<skill>/tests -q -o 'addopts='
```

Não executar glob vazio como se fosse sucesso. Se a skill não tiver scripts ou testes, declarar explicitamente que não se aplicam.

## 5. Critério de promoção

Uma skill não vira `approved` apenas porque passa no validador estrutural. Exigir:

- execução representativa ou simulação verificável;
- revisão de segurança correspondente ao risco;
- provenance/licença registradas;
- decisão de instalação e profiles-alvo;
- decisão humana se produzir efeitos externos ou tratar dados sensíveis.
