# Agilize Transaction Splitting

Use this reference when classifying transactions that need to be split into multiple categories (e.g. a credit-card invoice payment covering telecom, accounting, and SaaS).

## Execution guard

Treat local prep CSV `classified_split_*` rows as **planning notes**, not authorization to call `/split`. Before splitting:

1. Re-read the Agilize transaction list and check for existing children (`parent`, `isSplit`, `canBeDivisionRemoved`).
2. Confirm the split is operationally desired for this accounting month.
3. If the user says only specific transactions should be split, do **not** split others. Apply 1:1 category instead and update the local batch/audit log.

## Source-of-truth workflow

1. **Prepare classification** from source documents (bank CSV, card CSV/PDF, NFS-e, category tree).
2. **Confirm category IDs** from `/finance-transaction-categories` — never rely on labels alone.
3. **Locate the parent transaction** via:
   ```
   GET /api/v1/companies/{cid}/finance-transactions?from=YYYY-MM-DDT00:00:00-0300&to=YYYY-MM-DDT23:59:59-0300&sort=mainDate&direction=DESC&count=3000
   ```
4. **Split** the exact parent transaction (store its `__identity`).
5. **Create splits** via:
   ```
   POST /api/v1/companies/{cid}/finance-transactions/{tid}/split
   ```

### Payload

```json
{
  "splitsDto": [
    {"category": "<category_uuid>", "description": "Description A", "amount": 500.85},
    {"category": "<category_uuid>", "description": "Description B", "amount": 136.17}
  ]
}
```

**Critical:** the API expects **positive** split amounts even for expense parents. Children are created with negative amounts internally. The sum of split amounts must equal `abs(parent.amount)`.

## Required headers for mutations

```
Authorization: Bearer <token>
key: <company_cnpj>
Referer: https://app.agilize.com.br/
Content-Type: application/json
```

## Evidence linking after split

Some categories require structured evidence. After splitting, check each child:

### Invoice evidence (`agilizeInvoiceEvidence`)

For categories like `Contabilidade` (accounting fees):

1. List paid/closed invoices: `GET /invoices?competence=YYYY-MM-01T00:00:00-0300&closed=true&count=3000`
2. Match by total, competence, and deadline.
3. Update the child transaction:
   ```
   POST /finance-transactions/{tid}
   Header: X-HTTP-Method-Override: PUT
   Body (multipart/form):
     type=<existing>
     amount=<existing>
     description=<existing>
     consolidatedAt=<existing>
     account=<account_uuid>
     category=<category_uuid>
     evidence[agilizeInvoice]=<invoice_uuid>
   ```

### Tax evidence

For tax categories, the evidence field is **always** `evidence[tax]`:
```
evidence[tax]=<company_tax_uuid>
```

### Person-required categories

If category has `personRequired=true` (e.g. pro-labore), the update must include:
```
person=<partner_person_uuid>
```

Fetch partners: `GET /people?type=partner&count=3000`.

### Pro-labore evidence

For pro-labore categories, link the actual pro-labore record (not the `contraCheque` from `/prolabore-anual`):
```
GET /prolabores?competence=YYYY-MM-01T00:00:00-0300&count=3000
→ evidence[prolabore]=<prolabore_uuid>
→ person=<partner_uuid>
```

## Replacing existing evidence

Agilize rejects `A transação já possui uma evidência cadastrada.` if you try to PUT new evidence over existing evidence. The correct sequence:

1. Read the transaction; capture existing `evidences[].__identity` for rollback.
2. `DELETE /finance-transactions/{tid}/evidences/{evidence_id}` — remove old evidence.
3. Re-read the transaction.
4. `POST /finance-transactions/{tid}` with `X-HTTP-Method-Override: PUT` and new evidence.
5. If the new evidence update fails after deletion, immediately re-add the old evidence as rollback.

## Verification after split

After `POST .../split` returns 200, immediately re-list the same month and verify:

- Parent: `isSplit: true`, has `splitAt` timestamp.
- Children: `parent.__identity == <parent_id>`.
- Child descriptions, values, and category codes match the prepared classification.
- Evidence-required child categories have correct structured evidence linked.
- `__meta.canBeDivisionRemoved` is `true` on child rows (rollback path).

## Card invoice split pattern (generic)

When a bank transaction is a card-bill payment, do not classify the full payment as one expense. Split into the real card expenses:

1. Obtain the card statement CSV and PDF for the billing cycle.
2. Reconcile the bank payment amount against the PDF total.
3. Split the bank transaction into individual card purchases with their own categories.
4. Treat negative card rows (`Pagamento recebido`, credits, abatements) as card credits pending review, not expenses.
5. Classify card IOF/juros/multa as financial expenses unless the contador requests otherwise.

## Competence pitfall

Do not assume a payment in month X should be linked to the invoice/tax of competence X. Always verify the actual charge date and document competence before linking evidence. A card charge on 2024-12-31 paid in the January invoice should be linked to the December competence invoice, not January.
