# Agilize Monthly Close Workflow

Use this reference when running the monthly accounting close on Agilize.

## Prerequisites

- All bank/card statements for the month are imported or available.
- NFS-e data for the competence period(s) is available.
- Tax obligations for the month are known.
- Pro-labore values are confirmed.

## Close workflow

### Step 1: Verify completeness

Fetch all transactions for the month and verify:

```
GET /api/v1/companies/{cid}/finance-transactions?from=YYYY-MM-01T00:00:00-0300&to=YYYY-MM-DDT23:59:59-0300&sort=mainDate&direction=DESC&count=3000
```

Where `DD` is the last day of the month.

Check:
- [ ] Transaction count matches expectations (compare with bank/card statement counts).
- [ ] No duplicate transactions from repeated imports.
- [ ] Totals reconcile: sum of credits + debits + adjustments = expected net change.

### Step 2: Verify classification

For each transaction, verify it has a category assigned:

```python
uncategorized = [t for t in transactions if not t.get('category')]
```

Report any uncategorized items with transaction ID, amount, and description.

### Step 3: Verify required evidence

Some categories require structured evidence. Identify these by checking `allowedEvidenceType` in the category tree:

```python
categories = api_get(f"/finance-transaction-categories")
requires_evidence = {
    c['__identity']: c.get('allowedEvidenceType')
    for c in categories
    if c.get('allowedEvidenceType')
}

missing_evidence = []
for t in transactions:
    cat = t.get('category')
    if cat in requires_evidence and not t.get('evidences'):
        missing_evidence.append(t)
```

### Step 4: NFS-e integrity scan

Run the duplicate NFS-e scan (see `references/agilize-evidence-integrity.md`):

```python
duplicates = scan_nfse_duplicates(transactions)
assert len(duplicates) == 0, f"NFS-e evidence conflicts: {duplicates}"
```

### Step 5: Tax payment verification

For each tax payment in the month:

1. Verify the tax obligation exists in `/taxes?year=YYYY`.
2. Verify `evidence[tax]` is linked.
3. Check for duplicate payments (same tax paid via Pix and card — see evidence integrity reference).

### Step 6: Pro-labore verification

For each partner transfer:

1. Verify classification (pró-labore vs adiantamento de lucro).
2. Verify `person` and `evidence[prolabore]` are linked.
3. Verify amount reconciliation against `/prolabore-anual`.

### Step 7: Card invoice reconciliation

For card invoice payments:

1. Verify the payment is split into individual expenses (if applicable).
2. Verify each child has correct category and evidence.
3. Verify credits/abatements are handled correctly (not classified as expenses).

### Step 8: Customer receipt reconciliation

For service revenue receipts:

1. Match each receipt to an NFS-e by tomador and amount.
2. Apply customer-specific competence rules (same month vs prior month).
3. Verify NFS-e evidence is linked to the correct transaction.
4. Flag unmatched receipts or amount mismatches for review.

### Step 9: Generate close report

Produce a monthly summary with:

```markdown
## Monthly Close: YYYY-MM

### Summary
- Transactions: N
- Credits: R$ X
- Debits: R$ Y
- Net: R$ Z

### Classification
- Categorized: N (100%)
- Uncategorized: 0
- Low confidence reviewed: M

### Evidence
- NFS-e linked: K / K expected
- Tax evidence linked: J / J expected
- Invoice evidence linked: I / I expected
- Pro-labore evidence linked: H / H expected
- NFS-e duplicates: 0

### Pending items
- [list any items needing accountant/user review]

### Audit trail
- [list changes made with transaction IDs, old/new values, and timestamps]
```

### Step 10: Final approval gate

**Do not** mark the month as closed, submit to the accountant, or take any irreversible action without explicit user approval.

## Audit workspace

Maintain a local workspace for each company/month:

```text
~/.hermes/finance-admin/<company>/
  audit_log.md
  monthly_batches/
    YYYY-MM.csv
    YYYY-MM-summary.md
    YYYY-MM-review-needed.csv
    YYYY-MM-close-checklist.md
```

## Closing periods API

Check whether a period is already closed:

```
GET /api/v1/companies/{cid}/accounting-closing-periods
```

Do not attempt to modify transactions in a closed period without first confirming with the user/accountant.
