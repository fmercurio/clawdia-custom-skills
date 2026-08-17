---
name: creative-production-orchestration
description: "Use when a recurring creative-production request needs safe routing across brand systems, product visuals, thumbnails/covers, campaign assets, or a video brief. Select approved local capabilities, collect a minimal brief, enforce approval and publication gates, and deliver verified assets. Do not use for a simple one-off image prompt, direct provider setup, or automatic publishing."
version: 1.0.0
author: Skills Lab
license: MIT
metadata:
  hermes:
    tags: [creative, design, brand, product-visuals, thumbnails, campaigns, quality-gates]
    related_skills: [design-direction-agent, media-content-workflows, product-marketing-growth, open-design-artifact-operations]
---

# Orquestração de Produção Criativa

## Visão geral

Esta skill coordena pedidos criativos recorrentes que atravessam direção de arte, briefing, geração de ativos, revisão e entrega. Ela é **provider-neutral**: seleciona apenas ferramentas e capacidades já aprovadas e disponíveis no ambiente atual. Não instala CLIs, não cria contas, não autentica fornecedores e não presume créditos, licenças, modelos ou formatos de entrega.

O resultado não é apenas uma imagem. É um fluxo curto e verificável: entender o objetivo, escolher a rota mínima, proteger ativos e identidade, obter aprovação onde importa, checar a qualidade e entregar com limitações explícitas.

## Quando usar

Use quando o pedido envolve uma ou mais destas situações:

- sistema de marca, identidade, aplicações de marca ou conjunto coerente de peças;
- visual de produto para catálogo, campanha, social, página ou marketplace;
- thumbnail, capa, criativo de anúncio, carrossel, banner ou pack de campanha;
- pedido de várias peças com consistência visual e critério de qualidade;
- vídeo, animação ou explainer que precisa descobrir se existe uma capacidade aprovada antes de prometer execução;
- revisão de um briefing criativo antes de mobilizar ferramentas, créditos ou publicação.

Não use para:

- uma imagem simples e isolada sem risco, direção recorrente ou necessidade de QA — use a ferramenta de geração aprovada diretamente;
- implementação de site, app, Figma, apresentação ou outro artefato cujo workflow já seja coberto por uma skill especializada;
- configurar OAuth, instalar provider/CLI, comprar créditos, treinar identidade, publicar mídia ou fazer deploy;
- afirmar desempenho de campanha, conformidade de marketplace ou direitos de uso sem evidência verificável.

## Pré-flight obrigatório

1. **Classifique a entrega.** Identifique objetivo, canal, público, formato e data/decisão que ela precisa suportar.
2. **Descubra, não suponha.** Verifique quais ferramentas locais aprovadas estão realmente disponíveis antes de prometer imagem, vídeo, edição, arquivo editável ou publicação.
3. **Aplique a rota mais estreita.** Não carregue esta skill para substituir uma skill especializada que já cobre a tarefa inteira.
4. **Separe fato de proposta.** Logos, textos, preços, certificações, ingredientes, dados técnicos e claims fornecidos pelo usuário são restrições; nunca invente, complete ou “melhore” esses fatos.
5. **Declare bloqueios cedo.** Se uma capacidade, provider ou permissão não existe, pare na especificação, no storyboard ou no pacote de prompts. Não simule uma execução.

## Roteamento

| Sinal principal | Rota preferencial | Limite |
|---|---|---|
| Direção, consistência, sistema visual ou crítica de design | `design-direction-agent` | Não cria ativos sem uma capacidade disponível e aprovada. |
| Um único visual simples, sem dados sensíveis nem publicação | Ferramenta local de geração de imagem aprovada | Confirmar formato, resolução e uso pretendido quando materialmente relevantes. |
| Artefato/protótipo em projeto Open Design | `open-design-artifact-operations` | Seguir o projeto, o DS e a validação runtime já existentes. |
| Estratégia de campanha, posicionamento ou copy | `product-marketing-growth` | Não transformar hipótese em claim de produto. |
| Produção, download, análise ou reaproveitamento de mídia existente | `media-content-workflows` | Confirmar direitos, origem e ferramenta disponível. |
| Pedido de vídeo/animação/explainer | Descobrir provider aprovado; se ausente, produzir brief/storyboard/prompt pack | Nunca instalar provider, autenticar ou prometer render sem capacidade aprovada. |
| Deploy, publicação em feed, marketplace ou redes sociais | Fluxo especializado e confirmação explícita | Criação/aprovação de asset não autoriza publicação. |

Consulte `references/routing-and-gates.md` quando mais de uma rota competir.

## Brief mínimo

Colete apenas as lacunas que bloqueiam uma boa decisão. Use `templates/creative-brief.md` como contrato reutilizável.

1. **Objetivo e canal:** o que a peça deve ajudar a pessoa a entender, fazer ou decidir, e onde será usada.
2. **Entrega:** tipo de ativo, quantidade, formato, proporção e prazo quando conhecidos.
3. **Restrições de marca e conteúdo:** ativos oficiais, texto exato, paleta/tipografia, referências, proibições e direitos de uso.
4. **Público e direção:** tom, contexto, prioridade visual e exemplos que o usuário aprovou ou rejeitou.
5. **Dados sensíveis e custo:** rosto/identidade, imagens de terceiros, URL externa, upload, geração paga, publicação ou deploy.

Faça no máximo uma pergunta compacta por vez quando a resposta muda a rota, o risco ou o resultado. Para entregas parciais, não force um questionário completo.

## Gates de segurança e aprovação

### Gate A — capacidade e dados

Antes de qualquer ação externa, confirme:

- a ferramenta local existe e é apropriada;
- o usuário autorizou qualquer **upload para terceiro**, ingestão de URL de produto, uso de provider externo ou geração paga;
- há autorização explícita para semelhança facial, voz, identidade, pessoa reconhecível ou marca de terceiro;
- o usuário possui ou pode usar os ativos enviados;
- a entrega não depende de claim regulatório, preço, certificação ou dado não fornecido.

Sem confirmação, produza somente briefing, direção, storyboard, checklist ou prompts não executados.

### Gate B — proposta e aprovação

Para identidade visual, logo, campanha multi-peça, produto de marca, ou qualquer ativo que será reutilizado:

1. mostre opções/proposta com variantes identificáveis;
2. registre qual elemento está em revisão;
3. espere feedback explícito antes de consolidar uma direção;
4. nunca interprete silêncio, geração concluída ou preferência do agente como aprovação.

Para pedidos simples, a autorização explícita da geração pode cobrir uma única primeira proposta; não cobre uso posterior, variações caras ou publicação.

### Gate C — produção e qualidade

Depois de aprovação, execute apenas o lote aprovado e verifique os critérios de `templates/creative-qc.md`:

- formato, dimensões e contagem solicitados;
- texto, marca e ativos oficiais preservados quando aplicável;
- legibilidade, corte seguro, contraste e consistência com o canal;
- ausência de claims, preços, selos ou detalhes inventados;
- limitações de IA, editabilidade, fonte e direitos descritas honestamente.

Uma falha deve levar à correção localizada, não a uma reinvenção da direção aprovada.

### Gate D — distribuição

Salvar, entregar ou mostrar um arquivo não autoriza:

- publicar em rede social, marketplace ou feed;
- enviar para terceiros;
- subir para CDN/drive externo;
- fazer deploy de site/app;
- aplicar uma peça em uma campanha ativa.

Cada ato de distribuição ou produção exige confirmação explícita e uma rota especializada que faça read-back do resultado.

## Fluxo operacional

1. **Entender.** Classifique pedido, risco e rota; recupere projeto/brand lock quando ele já existe.
2. **Descobrir.** Confira capacidades locais e pré-requisitos de maneira somente leitura.
3. **Especificar.** Produza o brief mínimo e confirme Gates A/B necessários.
4. **Dirigir.** Proponha uma direção ou um pacote de prompts com critérios objetivos de revisão.
5. **Executar.** Use somente a ferramenta aprovada para a rota, em escopo e volume autorizados.
6. **Revisar.** Aplique QA visual/operacional e corrija somente o que falhou.
7. **Entregar.** Forneça arquivos/links realmente produzidos, versões, formatos, limitações e próximo passo; se não houve execução, diga claramente que é uma especificação pronta para execução.
8. **Encerrar.** Registre, quando apropriado, direção aprovada e ativos canônicos no projeto correto; não armazene rostos, credenciais ou material sensível em skill, memória global ou exemplo.

## Entrega esperada

A resposta final deve conter, conforme aplicável:

- ativo, caminho ou URL realmente produzido;
- resumo de finalidade, variante e formato;
- o que foi aprovado e o que continua como proposta;
- limitações verificadas (por exemplo: imagem achatada versus editável, fonte ausente, ausência de provider de vídeo);
- um único próximo passo que requer decisão humana, quando houver.

Nunca apresente prompt, mockup ou plano como mídia, publicação ou deploy concluído.

## Armadilhas comuns

1. **Trocar direção por ferramenta.** Ter uma ferramenta não substitui objetivo, público e restrições.
2. **Fazer upload por conveniência.** Material fornecido não é consentimento para enviar a um fornecedor externo.
3. **Prometer vídeo sem capacidade.** Se não há provider aprovado, entregue pré-produção, não um falso render.
4. **Tratar IA como fonte de fatos.** Texto em imagem, embalagem e social pode alucinar; preserve a cópia oficial.
5. **Aprovar em nome do usuário.** Sucesso técnico não é aprovação criativa nem autorização comercial.
6. **Publicar como etapa implícita.** Distribuição exige confirmação independente e read-back.
7. **Duplicar skills especialistas.** Encaminhe para a capacidade mais específica sempre que ela já resolver o problema.

## Checklist de verificação

- [ ] Objetivo, canal e entrega foram identificados.
- [ ] Capacidade local foi descoberta antes de promessa de execução.
- [ ] Rota especializada foi escolhida quando disponível.
- [ ] Upload, identidade, custo, ingestão externa e publicação passaram pelos gates aplicáveis.
- [ ] Direção e versão aprovada estão explícitas.
- [ ] QA cobre formato, marca/copy, legibilidade, consistência e fatos.
- [ ] Resultado declarado corresponde a artefato realmente produzido.
- [ ] Distribuição/deploy não ocorreu sem confirmação e verificação própria.

## Referências

- `references/routing-and-gates.md` — árvore de decisão e tabela de gates.
- `references/provenance.md` — fonte externa, limites da adaptação e política de revalidação.
- `templates/creative-brief.md` — brief mínimo reutilizável.
- `templates/creative-qc.md` — checklist de QA para entrega.
