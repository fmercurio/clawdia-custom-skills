# Roteamento e gates de produção criativa

| Pedido | Rota | Gate antes de agir | Resultado se bloqueado |
|---|---|---|---|
| Uma imagem simples | Ferramenta de imagem aprovada | Confirmar formato e uso quando relevantes | Prompt/brief pronto para execução |
| Identidade, marca ou pack coerente | Direção de design + workflow de marca | Ativos oficiais, escopo e aprovação de direção | Brand lock e opções para revisão |
| Visual de produto | Direção + geração aprovada | Direitos sobre o produto/fotos, claims e uso comercial | Shot list e prompts não executados |
| Thumbnail/capa | Workflow de imagem ou mídia aprovado | Tema verdadeiro, texto oficial e canal | Composição e copy proposta |
| Campanha multi-peça | Marketing + direção de design | Objetivo, público, claim e approval gate | Plano de assets e matriz de mensagens |
| Vídeo/animação | Provider de vídeo aprovado, se existir | Provider, custo, upload e direitos confirmados | Storyboard, roteiro e prompt pack |
| Publicar/deployar | Skill especializada de destino | Confirmação final e mecanismo de read-back | Pacote pronto, sem distribuição |

## Matriz de risco

| Condição | Pode seguir sem confirmação extra? | Ação correta |
|---|---:|---|
| Brief e ferramenta local já aprovados, uma proposta simples | Às vezes | Limitar ao escopo explicitamente autorizado. |
| Rosto, voz, identidade ou pessoa reconhecível | Não | Pedir confirmação específica de uso e provider. |
| Upload para serviço externo ou ingestão de URL | Não | Identificar destino e pedir autorização explícita. |
| Crédito pago, compra, conta/OAuth ou CLI nova | Não | Não instalar/autenticar; solicitar decisão. |
| Publicação, envio a terceiro, CDN ou deploy | Não | Usar rota especializada após confirmação final. |
| Informação comercial/regulatória ausente | Não | Solicitar cópia oficial ou remover o claim. |

## Critério de parada

Pare e devolva uma especificação, não uma execução, quando qualquer um destes itens for verdadeiro:

1. não há ferramenta aprovada capaz de produzir o formato pedido;
2. o passo exigiria upload, identidade, cobrança ou publicação sem autorização;
3. o usuário não forneceu o dado factual necessário;
4. a direção aprovada não existe para um sistema de marca ou lote multi-peça;
5. o resultado não pode ser validado pelo contrato de entrega.
