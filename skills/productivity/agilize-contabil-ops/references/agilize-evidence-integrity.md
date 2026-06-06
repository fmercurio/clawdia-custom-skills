# Agilize Evidence Integrity

Use this reference when linking structured evidence (NFS-e, tax, invoice, pro-labore) to finance transactions in Agilize.

## Non-negotiable rule

**A single structured evidence object must not justify more than one finance transaction.**

This applies to all evidence types:
- NFS-e: one `nfse.__identity` → one transaction.
- Tax: one `company_tax_uuid` → one transaction (unless partial payment is explicitly documented).
- Invoice: one `agilizeInvoice.__identity` → one transaction.
- Pro-labore: one `prolabore.__identity` → one transaction.

## NFS-e evidence

### Pre-link checklist

Before applying `evidence[nfse]=<nfse_uuid>`:

1. Re-read the relevant period from `/finance-transactions`.
2. Scan every transaction's `evidences[]` for an existing `nfse.__identity` match.
3. If the NFS-e is already linked elsewhere → stop and resolve the conflict.
4. Match the correct transaction by:
   - tomador/customer name (first priority);
   - amount;
   - receipt date / expected month;
   - user-provided correction.
5. Remove wrong evidence links before linking to the correct transaction.
6. Re-scan and verify duplicate count is zero.

### Duplicate scan pattern

Fetch the full year and group by NFS-e identity:

```python
from collections import defaultdict

by_nf = defaultdict(list)
for tx in transactions:
    for ev in tx.get('evidences') or []:
        nf = ev.get('nfse')
        if nf:
            by_nf[nf['__identity']].append({
                'nf_number': nf.get('numero'),
                'tx_id': tx['__identity'],
                'evidence_id': ev.get('__identity'),
                'date': (tx.get('mainDate') or tx.get('consolidatedAt') or '')[:10],
                'amount': tx.get('amount'),
                'description': tx.get('description'),
            })

duplicates = {k: v for k, v in by_nf.items() if len(v) > 1}
```

Any group with `len(group) > 1` is a conflict.

### Removing wrong evidence

```
DELETE /api/v1/companies/{cid}/finance-transactions/{tid}/evidences/{evidence_id}
```

Use the **evidence id** (`evidences[].__identity`), not the NFS-e id.

### Linking correct evidence

```
POST /api/v1/companies/{cid}/finance-transactions/{tid}
Header: X-HTTP-Method-Override: PUT
Form fields:
  type=<existing>
  amount=<existing>
  description=<existing>
  consolidatedAt=<existing>
  account=<existing account uuid>
  category=<category_uuid>
  evidence[nfse]=<nfse_uuid>
```

### NFS-e competence matching

When matching bank receipts to NFS-e, determine the correct NFS-e competence:

- Some customers pay for services billed in a **prior** month (receipt in month M → NFS-e from M-1).
- Some customers pay in the **same** month (receipt in M → NFS-e from M).
- Customer-specific competence rules should be configured and applied; do not use a generic M→M-1 rule across all customers.

Query `/nfses?competence=YYYY-MM-01T00:00:00` for each candidate month. Match by:
1. Tomador/customer name.
2. Amount (considering retentions: `totalRetido`, `irpjRetido`, `issRetido`, `pisCofinsCsllRetido`).
3. If amount differs, mark for review; do not force-conciliate.

## Tax evidence

### Endpoint

```
GET /api/v1/companies/{cid}/taxes?year=YYYY&closed=true&onlyTaxesNotProvisionedByRh=true&count=3000
```

Match by: competence, deadline, total amount, and tax abbreviation (DAS, DCTFWeb, INSS, IRRF, etc.).

### Linking

The evidence field is **always** `evidence[tax]`, regardless of tax type:

```
POST /finance-transactions/{tid}
Header: X-HTTP-Method-Override: PUT
Form: evidence[tax]=<company_tax_uuid>
```

The category's `allowedEvidenceType` determines the resulting evidence type label (`taxDasEvidence`, `taxInssEvidence`, `DCTFWebFiscal`, etc.).

### Tax duplicate detection

If the same tax obligation appears paid by both direct Pix and credit card:

1. Check the tax guide PDF: competence, due date, total amount.
2. Check payment receipt/comprovante: date, amount, destination.
3. Check card invoice: `card principal + fee = card item total`?
4. If both Pix and card match the same guide, keep evidence only on the actual payment rail.
5. Classify the other as duplicate/abatement/loan-repayment per accountant guidance.
6. **Never** attach the same tax evidence to both transactions.

## Invoice evidence (agilizeInvoiceEvidence)

For categories requiring Agilize's own invoice evidence (e.g. `Contabilidade`):

1. List closed invoices:
   ```
   GET /invoices?competence=YYYY-MM-01T00:00:00-0300&closed=true&count=3000
   ```
2. Match by total and competence.
3. Link:
   ```
   evidence[agilizeInvoice]=<invoice_uuid>
   ```

### Competence vs payment date

Do not assume a payment in month X corresponds to the invoice of competence X. Verify the actual charge date and invoice text. A December charge paid in January's card bill should link to the December competence invoice.

## Pro-labore evidence

Pro-labore categories require both person and pro-labore evidence:

```
GET /prolabores?competence=YYYY-MM-01T00:00:00-0300&count=3000

POST /finance-transactions/{tid}
Header: X-HTTP-Method-Override: PUT
Form:
  person=<partner_person_uuid>
  evidence[prolabore]=<prolabore_uuid>
```

Fetch the pro-labore record from `/prolabores`, **not** the `contraCheque` from `/prolabore-anual`.

## Verification checklist

After any evidence change:

- [ ] Re-read `/finance-transactions` for the target period.
- [ ] Count uncategorized transactions → should not increase.
- [ ] Count transactions with `hasEvidence == false` when category requires evidence → should decrease.
- [ ] Group NFS-e evidence by `nfse.__identity` → duplicate count must be 0.
- [ ] Group tax evidence by `companyTax.__identity` → no unintended duplicates.
- [ ] For any removed evidence, keep an audit note with transaction ID, evidence ID, reason, and rollback target.
