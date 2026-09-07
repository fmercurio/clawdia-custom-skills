# Projeções locais do catálogo v1

## Fonte e cobertura

A única fonte canônica é `registry/skills-registry.yaml`. Seu envelope contém
`skills` (legado) e o bloco fechado abaixo:

```yaml
capability_catalog:
  schema_version: clawdia-capability-source/v1
  capabilities: []
  artifacts: []
  bundles: []
```

Os arrays reais ficam vazios até a migração da issue #46. Não se inferem versões,
capabilities, risco ou aprovação a partir de diretórios. Cada registro futuro
segue seu contrato v1. Um artifact cujo ID coincida com um nome legado precisa
concordar em status, versão e kind (`skill` ou `package` conforme o caminho).
Nome, status, categoria e versão legados não aceitam whitespace nas extremidades;
não se normalizam identificadores para contornar o vínculo de governança.
`installation.repo_path` também precisa ser relativo, sem whitespace nas
extremidades nem barra inicial; a barra final de diretório já usada pelo legado
permanece permitida. Aliases não podem alterar a classificação skill/package
entre o catálogo humano e a projeção v1.
Ferramentas e frameworks sem entrada legada são permitidos. Nenhum outro campo
legado, comentário da fonte ou configuração de runtime é copiado para o JSON.
As seções e links legados de `CATALOG.md` são preservados; as seções v1 mostram
os IDs da mesma projeção e avisam sobre a cobertura parcial.

O bloco é obrigatório para geração, inclusive em fixtures de projeção. Ausência, null, chaves extras,
tipos errados, chaves YAML duplicadas, anchors, aliases, merges, tags inseguras,
valores não finitos e raiz malformada falham antes de qualquer escrita. Há uma
única interpretação YAML dos campos governados, usando SafeLoader estrito.

O leitor legado `parse_registry_entries`, também utilizado pelo inventário do
deploy planner, continua aceitando registries somente com `skills`. Esse modo de
leitura não gera projeções nem supre o bloco ausente: o gerador exige o envelope
completo. Imports como `tools.generate_catalog` e a CLI direta são suportados;
o leitor não carrega as dependências de JSON Schema da pipeline de projeção.

## Canais e relações

- `dist/catalog.v1.json` (`stable`): artifacts e bundles `approved`.
- `dist/catalog.preview.v1.json` (`preview` administrativo): `approved` e `candidate`.
- Os demais status conhecidos são excluídos; valores desconhecidos são erros.
- Capabilities são incluídas somente quando declaradas por registros do canal
  em `provides`, `capabilities`, `requires.capabilities` ou `conflicts.capabilities`.

Antes do filtro, todos os registros, inclusive excluídos, passam pelos schemas
canônicos da issue #42 e pelas mesmas regras semânticas de entidade. IDs são
únicos em toda a fonte, sem múltiplas versões do mesmo ID. Referências desconhecidas,
pins inexatos de bundle e ciclos falham. Uma capability requerida precisa de
um artifact provedor; bundles não contam como provedores implícitos. Para ciclos,
consideram-se conservadoramente todos os provedores possíveis, sem escolher um
plano de resolução.

Cada canal deve fechar suas dependências: artifacts requeridos, bundles requeridos,
provedores de capabilities requeridas e todos os membros de bundles (inclusive
opcionais) precisam estar disponíveis nele. Um requisito de capability precisa
ter ao menos um provedor no canal. Não se promove candidate nem se apaga membro
para corrigir um fechamento inseguro. A geração inteira falha nesse caso.
Conflitos podem conservar IDs de artifacts/bundles conhecidos na fonte e
excluídos do canal. A CLI de projeção isolada permite esses identificadores;
a existência canônica deles é verificada pelo gerador, que dispõe da fonte inteira.

## Elegibilidade, sem permissão

`default_installable_artifacts` é uma lista de IDs aprovados com
`delivery_mode: installable`. Candidate, reference, managed e external nunca
entram; frameworks são reference pelo contrato existente. A lista é calculada
na fonte inteira e coincide nos dois canais.

A filtragem é transitiva: cada artifact requerido deve também ser elegível.
Para capabilities requeridas, todos os provedores canônicos devem ser elegíveis;
um provedor candidate, excluído ou reference impede a elegibilidade do consumidor,
mesmo que haja outra alternativa. Isso é deliberadamente conservador. Não há
escolha de provedor, resolução de conflitos transitivos, avaliação das features
ou versões do runtime, nem decisão por tenant. Esses filtros são condições de
catálogo; aprovação humana, risco, control plane e autorização de runtime
continuam obrigatórios conforme aplicável. Não há instalação, TenantCapabilityPlan
ou resolver completo nesta etapa.

## Bytes, schema e verificação

```bash
python3 tools/generate_catalog.py
python3 tools/generate_catalog.py --check
python3 tools/validate_capability_contract.py --schema projection dist/catalog.v1.json dist/catalog.preview.v1.json
(cd dist && shasum -a 256 -c catalog.v1.json.sha256 catalog.preview.v1.json.sha256)
```

O mesmo pipeline calcula o Markdown, dois JSONs, dois sidecars `.json.sha256`
e `schemas/capability-catalog/v1/catalog-projection.schema.json`. O schema de
projeção é fechado e autocontido, com definições derivadas mecanicamente dos
três schemas de entidade; referências locais são ajustadas e IDs embutidos são
removidos. Os quatro contratos canônicos existentes não são reescritos.
A CLI `--schema projection` acrescenta verificação semântica ao JSON Schema,
incluindo limites SemVer de runtime, referências, pins, ciclos, fechamento stable
mesmo em preview e elegibilidade. Uma projeção isolada pode omitir IDs elegíveis;
a CLI rejeita inclusões inseguras, enquanto o gerador deriva a lista exata da fonte.

A serialização usa UTF-8, LF final, chaves JSON ordenadas e arrays de entidades
ou relações ordenados por identidade/conteúdo. Os arrays v1 representam conjuntos,
sem significado posicional. O checksum SHA-256 cobre os bytes exatos do JSON,
inclusive o LF final. O sidecar usa `hexadecimal  nome-do-arquivo` seguido de LF,
compatível com `sha256sum -c` e `shasum -a 256 -c` executados em `dist`.
Isso prova integridade de bytes, não autenticação do publicador.
Não se emite manifesto CatalogRelease, release ID, timestamp ou SHA de origem:
a montagem e publicação imutável pertencem à issue #47.

`--check` compara bytes brutos de todas as seis saídas, inclusive schema derivado.
Saída ausente, obsoleta ou convertida para CRLF causa retorno não zero sem reparo.
`--root` fixa a raiz; `--output` altera somente o destino Markdown, dentro da raiz.
`dist` permanece nessa raiz. Nenhum caminho de saída vem dos metadados.

Todos os dados e destinos são verificados antes da primeira escrita. Destinos com
symlinks, ancestrais symlink dentro da raiz, hardlinks, escape da raiz ou colisão
com fonte/schema são recusados. Um destino Markdown alternativo existente deve
ser um catálogo previamente gerado. O limite é um checkout local confiável:
não é um publicador privilegiado resistente a troca concorrente de caminhos,
e falhas de I/O durante escrita não têm garantia transacional. Erros de entrada
não alteram saídas existentes. A ferramenta não acessa rede, relógio ou estado Git.
