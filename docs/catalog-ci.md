# CI pública do catálogo

O workflow `catalog-and-validation.yml` executa sete gates públicos independentes
em uma matriz com `fail-fast: false`. Ele roda somente em `pull_request` e em
`push` para `main`, em runners GitHub-hosted `ubuntu-latest`, com permissão global
`contents: read`. O checkout não persiste credenciais. Cada job tem timeout finito.

Antes dos gates, o workflow baixa o archive Linux amd64 oficial do `actionlint`
1.7.12 por URL fixa, confere o SHA-256 fixado antes de extrair ou executar,
confirma a versão, executa a descoberta padrão de workflows com
`-oneline -shellcheck= -pyflakes=` e publica o caminho verificado em
`ACTIONLINT_BIN` para os passos seguintes. O contrato do workflow aceita `env`
somente nesse passo e somente com a versão, URL e checksum revisados.

O bootstrap Python instala somente as versões declaradas em `requirements-dev.txt`:

```bash
python3 -m pip install --disable-pip-version-check -r requirements-dev.txt
```

Esse bootstrap pode acessar a rede e, no workflow, ocorre apenas no runner
GitHub-hosted. Ele não deve ser descrito como offline. Depois de as dependências
estarem disponíveis, os gates de dados não fazem fetch nem instalam dependências.
Para execução local, prepare as dependências em um ambiente descartável. Um wrapper
local `uv --offline` também pode ser usado quando tudo já estiver no cache; isso não
muda os comandos canônicos abaixo nem torna o bootstrap inicial offline.

## Comandos canônicos

O mesmo comando é usado localmente e na célula correspondente da matriz:

```bash
python3 -B tools/run_catalog_ci.py --gate schema-fixtures
python3 -B tools/run_catalog_ci.py --gate deterministic-generation
python3 -B tools/run_catalog_ci.py --gate generated-drift
python3 -B tools/run_catalog_ci.py --gate stable-preview
python3 -B tools/run_catalog_ci.py --gate artifact-checksums
python3 -B tools/run_catalog_ci.py --gate skill-contract
python3 -B tools/run_catalog_ci.py --gate unit-contract
```

A suíte pública é exatamente o conjunto acima:

```bash
python3 -B tools/run_catalog_ci.py --public
```

`--public` não inclui o gate privado. A visão completa inclui o placeholder privado
e, enquanto ele estiver sem provisionamento, deve terminar com código diferente de
zero:

```bash
python3 -B tools/run_catalog_ci.py --all
```

Não use `--root` arbitrário no futuro executor que receber política privada. A raiz
candidata e seus bytes devem ser entregues como dados a um executor confiável e
fixado, sem importar ou executar ferramentas vindas dela.

## Inventário público implementado

- `schema-fixtures`: valida os schemas fechados e o corpus público fixo de fixtures
  válidas e inválidas, sem referências externas. Para uma falha que possa ser
  atribuída sem ambiguidade, informa somente o caminho relativo fixo do schema ou
  fixture presente nas tabelas estáticas do gate.
- `deterministic-generation`: gera em duas cópias temporárias, incluindo uma entrada
  com coleções reordenadas, e exige os mesmos seis outputs.
- `generated-drift`: regenera em cópia temporária e compara byte a byte os seis
  outputs versionados.
- `stable-preview`: valida as duas projeções contra o schema e a fonte, os canais
  `stable`/`preview` e a inclusão dos registros estáveis no preview.
- `artifact-checksums`: confere bytes, sintaxe e basename dos sidecars SHA-256 dos
  dois JSONs em `dist`.
- `skill-contract`: valida os `SKILL.md` encontrados sob `skills` e `packages` em
  uma cópia temporária.
- `unit-contract`: exige `ACTIONLINT_BIN` absoluto, regular e executável, rejeita
  symlinks e confere tamanho e SHA-256 contra identidades binárias fixas para Linux
  amd64 e Darwin arm64. Somente depois copia exatamente os bytes verificados para o
  diretório temporário controlado pelo gate, confere a versão 1.7.12 nessa cópia e
  passa apenas esse caminho staged às suítes públicas em `tools/tests`, ao teste do
  validador `llm-wiki` e a `tools/skill_deploy/tests`, exigindo pelo menos um teste
  por suíte e sucesso de todas elas. Não há busca de fallback em `PATH`, nem checksum
  fornecido pelo chamador, nem herança do ambiente externo.

Esses gates verificam dados, metadados, geração e testes públicos. Um resultado
público verde não é inspeção clean-room da fonte, não examina o archive real a ser
publicado e não prova autoria, licença, aprovação humana ou ausência de conteúdo
privado.

Os limites do runner são fechados: arquivos contratuais têm no máximo 1.000.000
bytes; snapshots têm no máximo 4.096 arquivos, 64.000.000 bytes no total e caminhos
relativos de até 512 bytes. Cada uma das três suítes de `unit-contract` tem timeout
de 120 segundos. Seu log combinado de stdout/stderr é aceito até 1.000.000 bytes e
o processo recebe limite de tamanho de arquivo de 8.388.609 bytes. O relatório usa
diagnósticos de caminho específico quando a causa já corresponde a uma entrada
fixa conhecida. Em `generated-drift`, output ausente, ilegível ou divergente informa
o primeiro caminho de `GENERATED_FILES` que falhou. Em `artifact-checksums`, falhas
estruturais ou de leitura informam o artefato ou sidecar fixo, e sintaxe ou basename
inválido informa somente o sidecar. Quando a sintaxe e o basename são válidos mas o
digest diverge, não é possível atribuir a causa a um dos dois bytes de entrada; o
diagnóstico informa o par `[artefato, sidecar]`, nessa ordem. Conteúdo do sidecar,
targets de symlink, exceções e hashes observados nunca fornecem nomes ao relatório.

Em `schema-fixtures`, invalidez estrutural, ausência, leitura impossível ou falha
da propriedade de fechamento de um schema fixo informa somente o schema. Ausência,
symlink/não-regular, corrupção JSON estrutural ou falha de leitura de uma fixture
fixa informa somente a fixture. Já uma comparação semântica schema↔fixture — fixture
válida que falha ou fixture negativa que passa — ou uma exceção durante essa
validação informa o par fixo `[schema, fixture]`, nessa ordem. Assim, uma alteração
semanticamente válida do schema, por exemplo remover um `required` que faz uma
fixture negativa passar, não é atribuída falsamente só à fixture. A enumeração do
corpus só atribui uma ausência quando exatamente uma entrada permitida está faltando
e não há entradas extras. Arquivo extra, múltiplas ausências, diretório
estruturalmente inválido, import/ambiente e outros erros sem atribuição determinável
preservam o alias `["schemas", "contract-fixtures"]`; nomes, caminhos e conteúdo
recebidos do input nunca passam para o relatório.

Outros gates e falhas anteriores à identificação causal, como snapshot ou geração,
continuam usando nomes lógicos como `generated-outputs` e `public-unit-suites`; eles
identificam grupos e não necessariamente o arquivo exato que causou a falha. Em
sucesso, as listas de arquivos permanecem as listas lógicas originais do contrato.

## Limite privado e bloqueio intencional

O job `private-clean-room/UNPROVISIONED` é separado, não faz checkout, não recebe
secrets e falha com uma mensagem sanitizada fixa. O agregador preserva o nome
obrigatório `Skills Catalog Validation`, usa `always()`, depende da matriz pública e
do job privado e só fica verde quando ambos terminam com `success`. Não há
`continue-on-error`, fallback verde ou autorização de merge.

Este rascunho deve permanecer vermelho até existir provisionamento privado real.
Como um PR candidato pode alterar o próprio workflow, esse job não é o emissor
confiável do check privado exigido. A proteção de branch que espera o nome agregado
e o emissor GitHub Actions é configuração externa e não foi enfraquecida aqui.

Ainda faltam, em infraestrutura protegida e separada:

1. receber o candidato como dados e inspecionar a árvore/fonte exata;
2. montar e inspecionar o archive realmente candidato, vinculado ao SHA exato;
3. executar o scanner real com política privada fora do checkout e sem expor
   fingerprints, identificadores de origem ou caminhos de máquina, usuário ou
   tenant;
4. emitir o resultado requerido por um workflow não modificável pelo candidato.

A integração geral A5 e a integração privada continuam abertas; esta fatia E1b de
`schema-fixtures` não as implementa nem altera seu estado.

Os testes públicos existentes do scanner usam políticas e achados sintéticos. Eles
não são um scan privado desta nova árvore. Testes contra PR hostil precisam de um
runner de sistema operacional realmente descartável e sem secrets. Limpar variáveis
de ambiente ou apontar proxies para um endpoint inválido não constitui sandbox de
filesystem nem de rede.

Em particular, `unit-contract` executa tooling e testes públicos do candidato. Seus
limites de ambiente, tempo, output e artefatos reduzem exposição acidental, mas não
formam um sandbox para código hostil e não conferem autoridade privada. A cópia
verificada de `actionlint` autentica somente esse executável; ela não transforma o
restante do candidato em código confiável nem substitui a inspeção clean-room.

Nada nesta fatia publica releases ou archives, faz deploy/instalação, promove
artefatos de `candidate` para `approved` ou autoriza merge. Esses passos continuam
fora do workflow público.
