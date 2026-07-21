# Como contribuir

Obrigado pelo interesse em melhorar o repositório de skills da ClawdIA.
Contribuições externas são bem-vindas por meio de pull requests. Toda proposta
passa por revisão humana, de segurança e de governança antes de ser aceita.

> Pull requests may be submitted in Portuguese or English.

## Antes de começar

- Procure uma issue ou pull request existente sobre o mesmo assunto.
- Para mudanças grandes, abra uma issue descrevendo o problema e a abordagem.
- Nunca inclua credenciais, tokens, cookies, dados pessoais, dados de clientes ou
  identificadores reais de empresas.
- Confirme que você pode redistribuir todo conteúdo, código e referência enviados.
- Registre a proveniência de conteúdo adaptado: fonte, autor original, licença e
  mudanças realizadas.

## Fluxo recomendado

1. Faça um fork do repositório.
2. Crie uma branch curta e descritiva a partir de `main`.
3. Faça uma mudança focada; evite misturar assuntos independentes.
4. Rode as validações e testes relevantes.
5. Abra um pull request preenchendo o template por completo.

Exemplo:

```bash
git clone https://github.com/SEU-USUARIO/clawdia-custom-skills.git
cd clawdia-custom-skills
git switch -c feat/minha-skill
```

## Requisitos para skills

Uma skill deve ficar em `skills/<categoria>/<nome>/` e incluir, no mínimo:

- `SKILL.md` com frontmatter válido;
- `name` estável, em minúsculas, com no máximo 64 caracteres;
- `description` objetiva, com no máximo 1.024 caracteres e iniciada por
  `Use when...`;
- gatilhos de uso claros;
- passos operacionais completos;
- seção de pitfalls ou riscos;
- passos de verificação;
- referências, templates, scripts e testes necessários para uso seguro.

Scripts devem ser seguros por padrão. Operações de escrita ou destrutivas precisam
ser explícitas, limitadas ao escopo informado e exigir confirmação quando houver
risco relevante. Skills devem ser company-agnostic: valores específicos pertencem
à configuração, não ao código ou à documentação versionada.

Novas skills entram como `candidate`. Aceitar um pull request **não** instala nem
habilita automaticamente a skill em nenhum runtime Hermes.

Para packages, preserve também o lifecycle documentado no próprio pacote,
incluindo manifest, testes, checksums e clean-room E2E quando aplicável.

## Validação

Valide cada `SKILL.md` alterado:

```bash
python3 tools/validate_skill.py skills/<categoria>/<nome>/SKILL.md
```

Rode também os testes relevantes à área modificada. Quando houver testes Pytest:

```bash
python3 -m pytest caminho/para/tests
```

Antes de enviar:

```bash
git diff --check
git status --short
```

Inclua no pull request os comandos executados e seus resultados. Se algum teste
não puder ser executado, explique o motivo e o risco correspondente.

## Critérios de revisão

Os mantenedores avaliam:

- utilidade e escopo;
- compatibilidade com Hermes/ClawdIA;
- segurança e privacidade;
- proveniência e licenciamento;
- clareza, manutenção e custo operacional;
- testes e evidências apresentados;
- aderência a [`docs/governance.md`](docs/governance.md).

Uma revisão pode pedir alterações, adaptar a proposta ou rejeitá-la mesmo que os
testes estejam verdes. A decisão de promover uma skill para `approved` permanece
com os mantenedores.

## Relatos de segurança

Não publique vulnerabilidades exploráveis, segredos ou dados sensíveis em issues
ou pull requests. Use o canal privado de contato dos mantenedores antes de divulgar
detalhes técnicos sensíveis.
