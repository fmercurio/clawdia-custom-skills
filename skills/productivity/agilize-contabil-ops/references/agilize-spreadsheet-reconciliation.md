# Spreadsheet ↔ Agilize Reconciliation (Diagnostic)

Use this reference when auditing Agilize categorization against an external cash-flow spreadsheet (Excel/CSV/Google Sheets). The workflow is **read-only / diagnostic** — it produces a divergence report, never applies fixes.

## When to use

- User asks "compare/reconcile/audit my Agilize categorization against this spreadsheet"
- User wants to verify that planilha classifications match what's actually in Agilize
- Period-end review before sending to accountant
- Catching systematic miscategorization (e.g. bulk-misclassified revenue streams)

## Match algorithm

Sheet descriptions are typically **short and clean** ("STRIPE", "C6", "MICROSOFT"). Agilize descriptions are **long and noisy** ("STRIPE BRASIL SOLUCOES DE PAGAMENTO LTDA_1", "<numeric-id>-BANCO TOPAZIO SA"). Pure description matching fails (~12% match rate). The working algorithm:

1. **Index Agilize by `(month, abs_amount)` → list[tx]**. Group by month to limit candidate pool.
2. **For each sheet row**, look up candidates by `(month, abs_amount)`.
3. **Score each candidate by description compatibility**:
   - `1.0` — exact normalized match
   - `0.8` — sheet_desc is substring/prefix/suffix of ag_desc (most common case)
   - `0.5 * token_overlap_ratio` — token-set overlap, capped
   - `0` — no signal
4. **Greedy assignment**: pick highest-scoring unused candidate.
5. **Adjacent-month fallback** (±1 month): handles cases where `mainDate` vs `statementTransaction.date` differ across month boundaries.
6. **Track used Agilize IDs** to prevent double-assignment.

Expected match rate: **90-95%** with this approach. Below 85% suggests data quality issues (wrong year, wrong company, or significant missing/misclassified transactions).

## Output structure

The match produces three artifacts:

1. **`matched.json`** — `{sheet_row, ag_tx, score, candidates}` per match
2. **`unmatched_sheet.json`** — sheet rows with no Agilize counterpart
3. **`crosstab.json`** — `sheet_classificacao → agilize_category → count` mapping

## Crosstab interpretation

For each sheet classification, look at the distribution of Agilize categories:

- **Single Agilize category (100%)** → consistent mapping, no issue.
- **Dominant Agilize category (>90%)** → mostly consistent, investigate the minority.
- **Spread across categories** → either (a) Agilize is **more granular** than the sheet (e.g. FIXA desdobra em INSS, DAS, ISS — this is correct, sheet is the one oversimplified), or (b) **real misclassification**.

Distinguishing (a) from (b) requires inspecting 2-3 sample transactions per pair. The fix for (a) is to update the sheet; the fix for (b) is to update Agilize (with accountant approval).

## Common mismatch patterns

These patterns recur across companies and are worth scanning for explicitly:

### Bulk misclassification of payment-rail receipts

Payment processors (Stripe, PayPal, Remessa Online, kamiPay) and bank-transfer descriptions ("501928788", "TRANSFERENCIA DE C6 CONTA GLOBAL") often get bucketed into a single generic category like "Investimento anjo" or "Outros receitas" because their descriptions don't match any supplier pattern. The actual underlying transaction is usually:

- **International subscriptions/donations** (Stripe) → Receita operacional / Prestação de serviço
- **Foreign-currency receipts** (Remessa Online) → Receita operacional
- **Grants from international foundations** (numbered descriptions, often just a CNPJ/EIN) → Receita or grant category, NOT equity investment

**Scan heuristic**: if any single category holds >50% of transaction count or >50% of total R$ value, decompose it by description pattern ( Stripe / Remessa / Pix / Banco Topázio / CNPJ-only / etc.) and check whether the dominant pattern is actually that category's purpose.

### Investment-account movements categorized as revenue

Spreadsheets often have a separate "bank" column for an investment account (CDB, aplicação). In Agilize these may appear under the checking account with a category like `BR.11.1 Resgate de aplicação financeira` or `BR.12.1 Aplicação Financeira`. These are **not revenue** — they're internal movements. Check the sheet's "bank" column to detect this.

### Pro-labore: gross vs net mismatch

Planilha values for pro-labore often record the **gross** amount per partner. Agilize typically records the **net** (after INSS/IRRF). Always validate against `/prolabore-anual?anoReferencia=YYYY-01-01T00:00:00-0300` which returns both `valor` (gross) and `valorLiquido` (net). The Agilize transactions should match `valorLiquido`. If the sheet shows `valor` it's the sheet that's out of sync, not Agilize.

### Saldo inicial / transferências internas

Sheet rows tagged "SALDO 2024", "TRANSF. ENTRE CONTAS" with bank pairs (e.g. C6 → Cora, same date, opposite amounts) often have **no counterpart in Agilize** — Agilize doesn't import opening balances or treats inter-account transfers as a single movement, not two. Don't try to force-match these.

## NFS-e cross-check

For revenue-side audits, always cross-check Agilize receita categories against `/nfses?competence=YYYY-MM-01T00:00:00`. Compare:

- Sum of NFS-e `valorServicos` vs sum of `BR.1.1 Prestação de serviço` transactions
- Count of NFS-e issued vs count of revenue transactions with `nfseEvidence`

Material gap (e.g. R$ 200k in NFS-e vs R$ 1.3M in revenue categories) indicates either unreported revenue or miscategorized revenue that should have had NFS-e issued. **This is accountant territory** — flag it, don't try to fix it.

## Common pitfalls

1. **Asking the user to do manual work the agent can do.** Before asking for DevTools curls, cookie exports, or "find this in your browser", check whether the data is in the JWT, can be discovered via API probing, or can be obtained via headless browser automation. Friction signal.

2. **Treating sheet classifications as ground truth.** Sheets are often less granular than Agilize. Don't flag "Agilize has 8 categories for what the sheet calls FIXA" as a divergence — that's Agilize being correct.

3. **Forgetting that all 12 months may be closed.** Check `isClosedPeriod` on transactions. If everything is closed, no fixes are possible without accountant reopening the period. Adjust the report's recommendations accordingly.

4. **Forgetting to read the `bank` column.** Sheets with a "bank" or "account" column may distinguish checking vs investment accounts. Agilize may not — these movements can show up under the main checking account with an investment-style category.

5. **Diagnostic-only discipline.** Don't drift into applying fixes mid-diagnosis. Run the full match + crosstab + report first, then discuss fixes as a separate user-approved batch.

## Verification checklist

After producing a diagnostic report:

- [ ] Match rate stated and >85% (or unmatched rows explained by category like SALDO 2024 / TRANSF)
- [ ] Crosstab covers all sheet classifications present in the period
- [ ] Each "⚠ mixed" mapping has 2-3 sample transactions shown
- [ ] High-value unmatched rows (|amount| > R$ 10k) explicitly called out
- [ ] NFS-e sum vs BR.1.1 sum compared if revenue-side audit
- [ ] Period-closed status reported (affects whether fixes are even possible)
- [ ] No credentials, tokens, or sensitive banking details in the report

## Output style

Use the operational blocks from the parent SKILL.md (Diagnóstico / Arquivos / Conciliação / Pendências / Próximo passo). Group divergences by **natureza** (grant, receita operacional, doação, transferência interna, other) rather than by sheet classification — that's how the accountant will discuss them.
