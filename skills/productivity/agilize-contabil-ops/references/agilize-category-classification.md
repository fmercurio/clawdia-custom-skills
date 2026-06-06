# Agilize Category Classification Guide

## Fetching the full category tree

The root endpoint `GET /finance-transaction-categories` returns only ~23 top-level categories. Query params `?tree=true`, `?full=true`, `?includeChildren=true`, `?depth=10` are **ignored** — they return the same root list.

To get sub-categories, fetch each root by ID:

```
GET /api/v1/companies/{cid}/finance-transaction-categories/{rootId}
```

The response includes a `categoriesChildren` array with full sub-category objects (UUID, code, name, allowedEvidenceType, personRequired, etc.). Walk recursively to build the complete tree.

**Category creation via API does not work.** POST returns `PARENT_IS_REQUIRED` regardless of field name or payload structure. New categories must be created in the Agilize web UI.

## Revenue categories (BR.1 Receitas)

| Code | Name | Evidence | NFS-e? | Use for |
|---|---|---|---|---|
| BR.1.1 | Prestação de serviço | nfseEvidence | **Yes** | Domestic service revenue. Requires NFS-e issuance. |
| BR.1.2 | Prestação de serviço pro exterior com invoice | invoiceEvidence | No | Service to foreign clients where you have an invoice/contract. ISS exempt (LC 116/2003 art. 2º §2º I). |
| BR.1.3 | Receitas com juros e multas | genericEvidence | No | Financial revenue from interest/penalties. |
| BR.1.4 | Adiantamento de dividendo | genericEvidence | No | Advance dividend distribution to partners. |
| BR.1.6 | Prestação de serviço pro exterior com NFS-e | nfseEvidence | **Yes** | Service to foreign clients that still requires NFS-e issuance. |
| BR.1.9 | Cashback | genericEvidence | No | Cashback/rebate received. |
| BR.1.10 | Direito Autoral | genericEvidence | No | Royalties/author rights, reader donations, subscriber contributions for content creation. |
| BR.1.11 | Projetos culturais | genericEvidence | No | Institutional grants, cultural projects, journalism funding without service counterparty. |

## "Investimento anjo" (BR.2.2) misuse pattern

**Common error:** classifying grants, donations, and international funding as "Investimento anjo".

**Correct rule:** BR.2.2 Investimento anjo applies **only** when there is an equity/ownership counterpart — i.e., the investor receives shares in the company. If there is no equity exchange, it is not angel investment.

### Correct classification for non-equity incoming funds

| Source | Correct category | Rationale |
|---|---|---|
| Institutional grants (LUMINATE, Pulitzer, ICFJ, Serrapilheira, etc.) | BR.1.11 Projetos culturais | Donation for project, no service contract, no equity. genericEvidence (attach grant agreement). |
| Tech company grants (Microsoft, Google for Startups, etc.) | BR.1.11 or BR.1.2 | If pure grant → BR.1.11. If there's a service contract/invoice → BR.1.2. **Ask the user** which. |
| Reader/subscriber donations (Stripe, PIX, Núcleo, Patreon-like) | BR.1.10 Direito Autoral | Remuneration for intellectual creation. genericEvidence (attach receipt). |
| International wire transfers via Remessa Online | Split: principal → BR.1.10 or BR.1.11, FX difference → BR.17.6 | The FX gain/loss on the exchange rate is separate from the underlying revenue. |
| Transfer between own accounts (e.g., C6 ↔ Topázio) | **Not revenue** — use BR.11.1 (resgate) / BR.12.1 (aplicação) | Internal movement, not income. |

### Key question to ask the user

Before proposing a revenue category, always ask: **"Esta entrada é doação, prestação de serviço, ou aporte de capital?"** The tax treatment differs:

- **Doação/Grant** → BR.1.10 or BR.1.11 (no NFS-e, no ISS, but taxable for IRPJ/CSLL/PIS/COFINS)
- **Prestação de serviço** → BR.1.1 (domestic, NFS-e required) or BR.1.2 (foreign, invoice required)
- **Aporte de capital** → BR.10.1 Aporte de sócio (equity) or BR.9.1 Integralização de capital

### Tax implications summary

All three are taxable income for IRPJ/CSLL/PIS/COFINS. The difference is:
- **NFS-e categories** (BR.1.1, BR.1.6): ISS may apply depending on service type and municipality
- **Invoice categories** (BR.1.2): ISS exempt for service exports (LC 116/2003)
- **Generic evidence categories** (BR.1.10, BR.1.11): No ISS (no service counterparty), but still subject to income taxes

## Expense categories reference (BR.7 Despesas operacionais)

Common sub-categories for operational expenses:

- BR.7.1 Água, BR.7.2 Aluguel, BR.7.3 Condomínio, BR.7.4 Luz
- BR.7.5 Material de escritório, BR.7.6 Contabilidade (agilizeInvoiceEvidence)
- BR.7.7 Serviços contratados, BR.7.8 Tarifa bancária, BR.7.9 Telefone e internet
- BR.7.14 Material de uso e consumo
- BR.7.17-25 Transporte/Hospedagem/Alimentação (adiantamento/pagamento/reembolso variants)

## Payroll categories (BR.6 Folha de pagamento)

- BR.6.1 Salários, BR.6.2 Pró-labore (personRequired=partner, prolaboreEvidence)
- BR.6.3 INSS (taxInssEvidence) — appears multiple times in tree for different retention types
- BR.6.4 FGTS, BR.6.5 Férias, BR.6.6 Décimo terceiro, BR.6.9 Bolsa estágio
- BR.6.10 IRRF (taxIrpjFolhaEvidence)

## Tax categories (BR.4 and BR.5)

- BR.4.1 IRPJ, BR.4.2 CSLL, BR.4.3 PIS, BR.4.4 COFINS
- BR.4.5 ISS, BR.4.7 IPTU, BR.4.8 DAS (taxDasEvidence), BR.4.10 ISS DAS
- BR.5.x Impostos retidos (IRRF, ISS retenção, PIS/COFINS/CSLL retenção)

## Financial categories

- BR.11.1 Resgate de aplicação, BR.11.2 Rendimento de aplicação
- BR.12.1 Aplicação financeira
- BR.16.3 Juros (multas/juros)
- BR.17.6 Variação cambial monetária — for FX gains/losses

## Evidence types cheat sheet

| Evidence type | What to attach | Required by |
|---|---|---|
| nfseEvidence | NFS-e XML/PDF | BR.1.1, BR.1.6 |
| invoiceEvidence | International invoice/contract | BR.1.2 |
| genericEvidence | Any receipt/document | BR.1.10, BR.1.11, BR.7.x, BR.17.x |
| prolaboreEvidence | Pro-labore record from /prolabores | BR.6.2 |
| taxDasEvidence | DAS guide | BR.4.8 |
| taxInssEvidence | INSS guide | BR.6.3 |
| feeEvidence | Municipal fee guide | BR.4.6 |
| agilizeInvoiceEvidence | Agilize-issued invoice | BR.7.6 |
