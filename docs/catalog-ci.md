# CI pública do catálogo

O workflow `catalog-and-validation.yml` executa sete gates públicos independentes
em uma matriz com `fail-fast: false`. Ele roda somente em `pull_request` e em
`push` para `main`, em runners GitHub-hosted `ubuntu-latest`, com permissão global
`contents: read`. O checkout não persiste credenciais. Cada job tem timeout finito.

O bootstrap instala somente as versões declaradas em `requirements-dev.txt`:

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
  válidas e inválidas, sem referências externas.
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
- `unit-contract`: descobre as suítes públicas em `tools/tests`, no teste do
  validador `llm-wiki` e em `tools/skill_deploy/tests`, exigindo pelo menos um teste
  por suíte e sucesso de todas elas.

Esses gates verificam dados, metadados, geração e testes públicos. Um resultado
público verde não é inspeção clean-room da fonte, não examina o archive real a ser
publicado e não prova autoria, licença, aprovação humana ou ausência de conteúdo
privado.

Os limites do runner são fechados: arquivos contratuais têm no máximo 1.000.000
bytes; snapshots têm no máximo 4.096 arquivos, 64.000.000 bytes no total e caminhos
relativos de até 512 bytes. Cada uma das três suítes de `unit-contract` tem timeout
de 120 segundos. Seu log combinado de stdout/stderr é aceito até 1.000.000 bytes e
o processo recebe limite de tamanho de arquivo de 8.388.609 bytes. O relatório usa
nomes lógicos como `generated-outputs` e `public-unit-suites`; eles identificam
grupos e não necessariamente o arquivo exato que causou a falha.

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

Os testes públicos existentes do scanner usam políticas e achados sintéticos. Eles
não são um scan privado desta nova árvore. Testes contra PR hostil precisam de um
runner de sistema operacional realmente descartável e sem secrets. Limpar variáveis
de ambiente ou apontar proxies para um endpoint inválido não constitui sandbox de
filesystem nem de rede.

Nada nesta fatia publica releases ou archives, faz deploy/instalação, promove
artefatos de `candidate` para `approved` ou autoriza merge. Esses passos continuam
fora do workflow público.
