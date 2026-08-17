# Proveniência e fronteira da adaptação

## Fonte analisada

- Repositório: https://github.com/higgsfield-ai/skills
- Revisão inspecionada: `fb18134b4aabe99c4bf7ff01c8f4883400efc80d`
- Licença declarada: MIT
- Data da avaliação: 2026-08-17

## O que foi aproveitado

A adaptação preserva apenas ideias gerais de processo:

- roteamento de pedidos criativos por intenção;
- brief mínimo antes de usar ferramentas;
- separação entre proposta, aprovação, produção, QA e entrega;
- variantes identificáveis e revisão localizada;
- distinção entre gerar um ativo e publicá-lo.

Essas ideias foram reescritas para uma skill Hermes-native e provider-neutral. Nenhum script, prompt extenso, endpoint, comando de CLI ou texto operacional do upstream é requisito desta package.

## O que foi rejeitado deliberadamente

- instaladores `curl | sh`, `npx`, plugins e symlinks de outros agentes;
- Higgsfield CLI, OAuth, créditos, modelos e APIs proprietárias;
- treinamento de identidade/Soul, upload automático de imagens ou ingestão de URL;
- deploy de Worker, publicação em feed/marketplace e ações automáticas de distribuição;
- suposições de que vídeo, 3D, arquivos editáveis ou um provider específico estão disponíveis;
- instruções que permitam instalação, autenticação, geração paga ou publicação sem confirmação explícita.

## Revalidação

Reavalie a fonte se houver uma mudança material no commit/versão upstream, se a ClawdIA aprovar um novo provider criativo, se forem adicionadas ferramentas de vídeo/identidade, ou no máximo em 90 dias para decidir se alguma melhoria de processo merece adaptação seletiva.

A revalidação deve repetir: inspeção isolada, licença/proveniência, auditoria de scripts/instaladores, comparação semântica, atualização do registry e validação Hermes. Ela não autoriza importar nem executar o upstream.
