# Contratos do catálogo de capacidades v1

Este diretório contém os contratos públicos e versionados do catálogo de
capacidades da ClawdIA. Os quatro schemas usam JSON Schema Draft 2020-12 e são
intencionalmente autocontidos: somente referências por fragmento local (`#...`)
são aceitas pelo validador.

## Entidades

### `Capability`

Representa um resultado que a plataforma pode oferecer, não uma instalação nem
uma permissão de tenant.

Campos obrigatórios:

- `schema_version`: constante `clawdia-capability/v1`;
- `id`: identificador estável em kebab-case;
- `label`, `description` e `domain`;
- `risk_level`: `low`, `medium` ou `high`;
- `data_classes`: uma ou mais entre `public`, `internal`, `confidential`,
  `restricted`, `personal`, `financial`, `health` e `credentials`;
- `requires_approval`: obrigatório e igual a `true` para risco médio ou alto.

`credentials` classifica dados com que a capability pode lidar; não autoriza
incluir credenciais no catálogo. Secrets e valores reais de credenciais nunca
pertencem aos documentos públicos.

### `Artifact`

Representa uma implementação ou referência que fornece uma ou mais
capabilities.

- `kind`: `skill`, `package`, `tool`, `framework`, `template` ou `integration`;
- `delivery_mode`: `installable`, `managed`, `external` ou `reference`;
- `status`: estado explícito da governança;
- `version`: SemVer exata;
- `provides`, `requires` e `conflicts`: relações por ID estável;
- `runtime_compatibility`: runtime e limite mínimo obrigatório, com limite
  máximo exclusivo opcional. Quando presente, o máximo deve ser estritamente
  maior que o mínimo segundo a precedência SemVer: prereleases precedem a versão
  final e metadados de build não alteram a ordem. A CLI verifica essa relação;
- `risk_level` e `requires_approval`.

Frameworks são sempre `reference`. O contrato não autoriza instalação: até um
artifact `approved` e `installable` continua sujeito ao control plane e à
aprovação aplicável.

### `Bundle/Recipe`

`Bundle` é o nome do contrato; “recipe” descreve seu papel de composição. Um
bundle fixa versões de artifacts, declara as capabilities resultantes e torna
requisitos, conflitos, risco e aprovação explícitos.

### `CatalogRelease`

Manifesto imutável de uma projeção do catálogo:

- `release_id`: SemVer sem metadados de build (`+...`) nesta versão do contrato;
- `created_at`: perfil UTC de RFC 3339, `YYYY-MM-DDTHH:MM:SS[.fração]Z`, com
  `T`/`Z` maiúsculos e segundos de `00` a `59` (sem leap seconds). O schema
  exige a sintaxe exata; a CLI também valida calendário e horário, mesmo sem
  dependências opcionais de `format` do jsonschema;
- `source_revision`: SHA-1 completo do commit de origem;
- canais `stable` e `preview`;
- checksums SHA-256 de ambas as projeções.

Referências no canal `stable` só aceitam status `approved`. O canal `preview`
aceita `approved` e `candidate` e deve conter tudo o que está no canal `stable`.
Checksums são somente contratados aqui; sua geração e verificação pertencem à
etapa de projeções determinísticas.

## Limite entre catálogo e tenant

Os contratos separam três fatos que não podem ser confundidos:

1. **capability disponível** — existe no catálogo/release;
2. **artifact presente** — aparece como artifact ou composição publicável;
3. **capability autorizada/ativa** — decisão por tenant, fora deste catálogo.

Os estados `installed`, `authorized`, `enabled` e `active` não pertencem a estes
schemas. Eles serão expressos pelo `TenantCapabilityPlan` e pelo inventário do
control plane. Como `additionalProperties` é `false`, a inclusão acidental
desses campos falha fechado.

## Validação local

Instale as dependências de desenvolvimento uma vez:

```bash
python3 -m pip install -r requirements-dev.txt
```

Valide um documento informando o tipo:

```bash
python3 tools/validate_capability_contract.py \
  --schema capability \
  tools/tests/fixtures/capability_catalog/v1/valid/capability.json
```

Tipos aceitos: `capability`, `artifact`, `bundle` e `release`. O comando aceita
vários paths do mesmo tipo, imprime cada resultado e retorna código diferente de
zero se qualquer documento ou schema for inválido. JSON com chaves duplicadas ou
números não finitos também é recusado para evitar interpretações ambíguas.

Execute a suíte:

```bash
python3 -m unittest discover -s tools/tests -p "test_*.py" -v
```

A suíte usa somente fixtures sintéticas, não acessa a rede e não executa scripts
de skills ou packages. Schemas fornecidos ao validador que contenham `$ref` ou
`$dynamicRef` externos são recusados antes da resolução.

## Evolução

Mudanças incompatíveis criam um novo diretório (`v2`, por exemplo), novas
constantes de `schema_version` e novos `$id`. IDs de entidades não devem ser
reaproveitados com outro significado. A publicação de conteúdo real e sua
migração para estes contratos não fazem parte desta fundação.
