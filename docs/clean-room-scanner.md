# Scanner neutro de clean-room — contrato v1 (#44)

`tools/scan_catalog.py` é um motor público, offline, stdlib-only. Exige uma
política JSON do operador **fora da árvore examinada e do repositório público**.
Não contém uma lista real de organizações, pessoas, origens ou tenants, nem seus
fingerprints. A política real e as evidências que a fundamentam ficam privadas.
O exemplo abaixo é estritamente sintético e não serve como gate de produção.

```bash
python3 -B tools/scan_catalog.py --root "$SCAN_ROOT" --policy "$PRIVATE_POLICY" --json
python3 -B tools/scan_catalog.py --root "$SCAN_ROOT" --policy "$PRIVATE_POLICY" --archive "$ARTIFACT" --json
```

`SCAN_ROOT` e `PRIVATE_POLICY` são caminhos absolutos; `--archive` é repetível.
Imports `from tools.scan_catalog import scan` e `python3 -B -m tools.scan_catalog`
têm o mesmo contrato. `scan(root, policy, archives=())` retorna `(exit_code, report)`.
Não há escrita, extração, execução do conteúdo, rede, resolução Git, YAML,
referências remotas ou fallback sem política. A CLI desativa a escrita de bytecode.
A árvore e os artefatos devem permanecer imutáveis durante a leitura: esta é uma
ferramenta para checkout local confiável, não um serviço privilegiado resistente
a trocas concorrentes de caminhos. O processo não interpreta pointers LFS nem os
busca; são examinados apenas seus bytes locais, não o objeto remoto.

## Política fechada

Todos os quatro campos de topo são obrigatórios. Sem chaves extras em qualquer
objeto; JSON estrito UTF-8, sem BOM, chaves duplicadas, NaN/Infinity, raiz errada,
strings com controles/surrogates ou dados malformados. Arquivo de política regular,
sem symlink/hardlink, até 1 MiB. Não é carregado de dentro da raiz, mesmo por alias
resolvido. Sua ausência, erro de I/O ou lista de negação vazia retorna 2.

```json
{
  "schema_version": "clean-room-policy/v1",
  "deny_terms": [
    {"id": "term-001", "term": "Synthetic Quartz", "classification": "origin"}
  ],
  "allowlist": [],
  "reviewed_assets": []
}
```

Cada lista tem até 256 registros. Regras têm exatamente `id`, `term` e
`classification`. IDs seguem `term-[0-9]{3}`, são únicos e deliberadamente opacos:
não usar nomes nem hashes privados como IDs. Classificação é `origin`, `private`
ou `tenant`; não existe descoberta automática de todos os identificadores de tenant.
Termos têm 1–128 caracteres, até 16 palavras por whitespace e 4–128 caracteres
após normalização; termos normalizados duplicados são inválidos. Strings de política
não admitem whitespace nas extremidades. Os IDs são validados antes de aparecerem
em relatórios, inclusive quando outra parte da política é inválida.

Normalização `N(s)`: NFKC, casefold, NFKD, retenção apenas de caracteres para os
quais Python `isalnum()` é verdadeiro. Remove acentos combinantes, pontuação,
separadores e controles de formatação. A busca é por substring, conservadora,
inclusive dentro de palavras. Assim variações de caixa, acento, largura, hífen,
underscore e separação entre letras ou por newline não contornam o termo.
O texto inteiro é pesquisado; um termo que atravessa linhas não se perde.
Homoglifos entre alfabetos, conteúdo codificado/cifrado e esteganografia não são
decodificados. Não se aceitam regex fornecidas pela política.

### Exceções contextuais

Cada registro de `allowlist` tem exatamente:

- `rule_id`: um dos IDs de termo configurados; IDs built-in são recusados.
- `path`: caminho relativo exato, com `/`, incluindo a identidade de container
  descrita abaixo quando aplicável. Não pode ser absoluto, conter `\\`, `:`,
  `*`, `?`, `[`, `]`, `!`, segmentos vazios, `.` ou `..`, controles ou whitespace
  nas extremidades de qualquer segmento. Limite de 1.024 caracteres.
- `location`: `content` ou `path`.
- `context_sha256`: 64 dígitos hexadecimais minúsculos.
- `justification`: texto explícito, 8–1.024 caracteres.

A chave `(rule_id, path, location, context_sha256)` não pode ser duplicada.
Não há globs, autorização de diretório/descendentes, exceções globais ou wildcard.
Exceção de path não autoriza conteúdo, e vice-versa. Uma exceção autoriza todas
as ocorrências daquele termo com aquele contexto normalizado naquela localização
exata; uma mudança que preserve a normalização é intencionalmente equivalente.
Uma mudança do termo, caminho ou contexto normalizado invalida o vínculo.

Para conteúdo, `context` é a sequência das **linhas completas**, da primeira à
última linha ocupada pela ocorrência, unidas por LF. Cada ocorrência é contada;
`line` aponta a primeira linha (base 1). Para nome, `context` é o caminho relativo
completo da fonte ou do membro, preservando os diretórios; `line` é 0.
Metadados textuais usam `content` e linhas relativas ao bloco de metadados.

O digest é SHA-256 dos bytes UTF-8 de:

```text
clean-room-context/v1 + NUL + location + NUL + N(term) + NUL + N(context)
```

`tools.clean_room_policy.context_digest(context, term, location='content')`
implementa esse contrato. O termo é parte do vínculo, além do ID. Calcule o
contexto e registre a justificativa em ambiente privado; não copie linhas reais
para fixtures, documentação ou comandos em logs públicos. Não há geração automática
de exceções. As regras built-in não podem ser isentadas; triagem exige remover o
literal ou usar uma variável inerte explícita, ou revisão do motor com testes.

### Binários revisados

`reviewed_assets` começa vazio. Cada registro tem exatamente `path`, `sha256`
(SHA-256 dos bytes integrais, 64 hex minúsculos), `authorship`, `license`,
`metadata_scrubbed` obrigatoriamente `true`, e `justification`. Caminho segue as
mesmas regras e não pode se repetir. Autoria e justificativa têm 8–1.024 caracteres;
licença, 3–1.024. Autoria/licença são declarações humanas, não verificações legais.

O único asset binário aceito nesta versão é **PPM P6 RGB8 sem compressão**, com
comentários ASCII, largura/altura de 1–5 dígitos positivos, máximo 255, um único
raster de exatamente `largura × altura × 3` bytes e nenhum payload residual.
Exige revisão e hash exatos mesmo quando os bytes incidentalmente são UTF-8.
Cabeçalho, comentários e raster são inspecionados como bytes Latin-1, retirando
NUL para expor sequências ASCII intercaladas. Nomes continuam examinados.
Uma revisão não autoriza termos/credenciais encontrados; a allowlist contextual
é separada e credenciais continuam não isentáveis. Outros binários, PNG/JPEG/GIF,
PDF, formatos cifrados ou metadados que o motor não entende são recusados, **mesmo
com revisão**. Não se declara cobertura de formatos arbitrários nem de conteúdo
visual. Nenhum asset real precisa ser aprovado para o inventário base desta etapa.

## Cobertura, containers e recursos

A fonte inclui arquivos rastreados, não rastreados e ignorados: comentários,
frontmatter, docs, testes, manifests, templates, exemplos, `.env`, demais ocultos,
`CATALOG.md` e `dist`. `.gitignore` não governa cobertura. Apenas diretórios de
controle com nomes exatos `.git`, `__pycache__`, `.venv`, `venv`, `.pytest_cache`,
`.ruff_cache`, `.mypy_cache` são omitidos, em qualquer nível **da fonte**. O operador
deve garantir que não sejam payload publicável. Arquivos com esses nomes não são
omitidos. Archives não têm exclusões. Symlinks, hardlinks e arquivos especiais são
recusados sem seguir/abrir seu alvo. Texto exige UTF-8 estrito, sem NUL/controles
C0 exceto TAB, CR e LF; bytes inválidos entram na verificação binária fechada.
Segmentos reais iniciados por `@` são reservados e recusados, evitando colisão com
identidades internas de containers. Caminhos inválidos também falham sanitizados.

ZIP (stored/deflate), TAR USTAR e TAR.GZ são identificados por assinatura ou
extensão declarada, também dentro da fonte e de outros archives. Um `--archive`
precisa ser um container suportado, não um arquivo texto. JSON/Markdown normais
continuam texto. Assinaturas reconhecidas e extensões de containers não suportados
(BZip2, XZ, Zstandard, 7z, RAR) são recusadas, inclusive disfarçadas de texto.

Nenhum archive é extraído. Bytes são lidos em blocos de até 64 KiB, com buffers
limitados. ZIP valida cabeçalhos locais/centrais, CRC, término do deflate, tamanhos
e cobertura contígua do artefato inteiro. Aceita data descriptors de 32 bits;
recusa ZIP64, criptografia, métodos desconhecidos, payload inicial/final ou entre
membros, extras desconhecidos e links/specials. O único extra suportado é timestamp
estendido `0x5455` (5/9/13 bytes); seus bytes locais/centrais são inspecionados
via Latin-1, assim como o cabeçalho gzip fixo. Comentários são inspecionados
em UTF-8 estrito, sem controles C0 exceto TAB/CR/LF; comentários binários
opacos são recusados. TAR valida checksum,
cabeçalhos e padding, tipos, tamanhos e EOF de pelo menos dois blocos nulos;
inspeciona campos textuais do cabeçalho. Aceita PAX apenas com registros inertes
`comment`, `mtime`, `atime`, `ctime` (incluindo o comentário do `git archive`).
Recusa overrides de path, sparse, GNU longname e extensões não suportadas.
TAR.GZ aceita um único stream gzip sem campos opcionais no cabeçalho, com CRC e
EOF completos, sem concatenação/resíduos. Use gzip sem nome embutido (`gzip -n`)
quando o operador precisar gerar esse formato.

Nomes absolutos, traversal, drives, backslashes, aliases `.`/segmento vazio,
colisões arquivo/diretório e duplicatas (inclusive por NFKC/casefold) falham.
O caminho canônico de um membro **nunca perde um prefixo arbitrário**. Sua
identidade para `path`, allowlist, revisão e `path_id` é:

```text
@artifact/@<sha256-dos-bytes-do-archive>/caminho/completo/do/membro
bundle.zip/@<sha256-dos-bytes-do-archive>/caminho/completo/do/membro
@artifact/@<hash-externo>/inner.zip/@<hash-interno>/caminho/do/membro
```

A segunda forma é para um archive encontrado na fonte. Metadados de membro usam
sua identidade completa; metadados do container usam a identidade do container.
O nome de um `--archive` é examinado separadamente, com identidade
`@artifact/@<hash>`. Não há exceção por basename. Uma alteração de bytes do
container invalida as revisões de seus membros. Archives byte a byte idênticos
representam a mesma identidade de conteúdo. Hashes vinculam bytes: **não provam
autenticidade, aprovação ou autoria**.

Limites fixos, não relaxáveis pela política/CLI: 10.000 entradas totais (incluindo
diretórios, containers e cabeçalhos PAX); 8 MiB por arquivo/membro/buffer descomprimido;
64 MiB acumulados nas leituras e descompressões; profundidade de 3 containers;
razão máxima de expansão de 200 por stream; 100.000 linhas por bloco inspecionado;
10.000 ocorrências no relatório. TAR já em buffer não é contado de novo por cada
slice de membro. Alcance de limite, fluxo truncado/corrompido ou I/O incompleto
retorna 2, jamais verde. Buffers são limitados, não streaming de tamanho ilimitado.

## Regras built-in e relatório

IDs constantes: `builtin-001` prefixos plausíveis de provedores; `builtin-002`
cabeçalho PEM privado; `builtin-003` formato JWT; `builtin-004` atribuições literais
de password/passwd/token/API key/access token/secret; `builtin-005` caminhos
absolutos de home de usuário Unix/macOS/Windows; `builtin-006` IP não global.
Apenas a atribuição inteira `${EXAMPLE_VALUE}` ou `{{ EXAMPLE_VALUE }}` é template
inerte (nome em maiúsculas, dígitos/underscore, início alfabético); aspas externas
são permitidas. Literal vazio, sufixo de placeholder e valores de exemplo comuns
não recebem isenção automática.

A isenção de template reconhece deliberadamente apenas uma atribuição isolada
na linha física (chave sem aspas, separador `=` ou `:`, somente espaços/TAB antes
da chave e depois do valor), ou um valor string ligado à chave real de um objeto
em documento JSON válido. JSON pode ocupar várias linhas e conter objetos/arrays
aninhados, mas essa isenção limita o documento normalizado a 65.536 caracteres e
32 níveis estruturais. Chaves duplicadas, NaN/Infinity e JSON malformado não
recebem contexto JSON. Documentos iniciados por `{` ou `[` não usam o fallback
de atribuição isolada. Strings dentro do JSON nunca emprestam seu contexto a
atribuições contidas nelas. Sufixos, inclusive `}`, `]`, vírgula e ponto e vírgula,
não são terminadores genéricos. Outros formatos, comandos compostos, comentários
na mesma linha e contextos ambíguos conservam o finding; não há parser shell/YAML.

IPs loopback e redes de documentação `192.0.2.0/24`, `198.51.100.0/24`,
`203.0.113.0/24`, `2001:db8::/32` são excluídos. Endereços IPv4-mapped IPv6 são
avaliados como IPv4. A classificação não global usa `ipaddress` da stdlib; fixe a
versão do interpretador no gate. Heurísticas podem ter falsos positivos/negativos;
nomes privados de tenant/origem dependem da política explícita. Não existe isenção
geral por arquivo de teste ou por documentação.

A CLI sempre escreve um único JSON compacto, ordenado, com LF final, mesmo sem
`--json`. Argumentos inválidos (inclusive `--help`, abreviações e campos ausentes)
produzem erro JSON, sem usage/traceback. Retornos:

- `0`: scan completo e nenhuma ocorrência não autorizada; `status: pass`.
- `1`: scan completo com ocorrências não autorizadas; `status: fail`.
- `2`: entrada/política/I/O/formato/limite inválido; `status: error`.

Relatório fechado: `schema_version: clean-room-report/v1`, `status`, `error`
(`null` ou `invalid_input`), `scanned_entries`, `authorized_findings`,
`unauthorized_findings`, `findings`. Cada finding contém apenas `rule_id`,
`path_id`, `location`, `line`, `authorized`. Não há caminhos/valores/termos brutos,
justificativas, exceções Python, timestamps ou caminhos absolutos.

`path_id = SHA256(UTF8("clean-room-path/v1" + NUL + identidade-relativa))`.
Não normaliza a identidade antes do hash. Findings são ordenados por
`(path_id, location, line, rule_id, authorized)`. Contadores refletem as entradas
entregues para inspeção e ocorrências registradas; no erro podem ser parciais,
e `status: error` nunca atesta conclusão. Não deduplicam ocorrências em contexto
igual. O relatório não emite hashes da política nem prova revisão humana.

## Procedimento do operador e handoff

1. Construir/revisar a política real em diretório privado fora do repo, com termos
   reais apenas nesse arquivo e IDs opacos. Fixar os bytes revisados da política,
   do scanner e do interpretador. Verificar a origem/aprovação por canal protegido;
   um checksum sozinho não autentica essa aprovação.
2. Executar `generate_catalog.py --check` e o scan da raiz pública candidata,
   incluindo não rastreados/ignorados. Examinar os findings em ambiente privado.
   Resolver cada ocorrência; não criar allowlists amplas para obter verde.
3. Montar o archive exato a publicar e examiná-lo **antes** da publicação, no mesmo
   processo ou em nova execução com a mesma política fixada. Exemplo para um commit
   imutável escolhido pelo operador (variáveis definidas por ele):

   ```bash
   git archive --format=tar --output="$ARTIFACT" "$IMMUTABLE_COMMIT"
   python3 -B tools/scan_catalog.py --root "$SCAN_ROOT" --policy "$PRIVATE_POLICY" --archive "$ARTIFACT" --json
   ```

   `git archive` não inclui mudanças não commitadas: uma árvore de trabalho verde
   não demonstra que esse archive as contém. Para revisão antes de commit, o
   operador deve montar e examinar o candidato exato separadamente. O motor não
   executa Git. Guardar artefato e relatório fora da árvore pública; publicar somente
   os mesmos bytes examinados, depois dos demais gates e aprovações.
4. **#45** implementará entrega protegida da política e wiring do gate de produção.
   Não disponibilizar política/secrets a código de PR. Usar scanner revisado/pinado
   de origem confiável em job protegido, com candidato somente como dados, rede
   restrita e política fora do checkout. Nem testes de PR nem hash equivalem à
   autorização de receber política privada. Os testes públicos sintéticos já são
   descobertos pela CI existente; não são verificação privada de produção.
5. **#46** continua responsável pela migração real; **#47**, montagem/publicação.
   Esta implementação preserva pipeline #43, inventário/statuses legados e conteúdos
   de SKILL/package. Um scanner textual não comprova reautoria humana clean-room,
   aprovação de licença, completude da política ou segurança do conteúdo executável.
