# Agilize Pro-labore Reconciliation

Use this reference when classifying owner/partner bank transfers as pró-labore vs profit distribution/advance.

## Annual pro-labore reference

Fetch the annual pro-labore data to understand each partner's monthly gross/net values:

```
GET /api/v1/companies/{cid}/prolabore-anual?anoReferencia=YYYY-01-01T00:00:00-0300
```

### Response shape

```json
{
  "contracheques": {
    "2025-01-01": [
      {
        "partnerName": "Partner Name",
        "partner": { "__identity": "<partner_uuid>" },
        "competence": "2025-01-01",
        "valor": 3061.09,        // gross pro-labore
        "iNSS": 336.72,
        "iRPJFolha": 17.78,
        "totalDeImpostos": 354.50,
        "valorLiquido": 2706.59   // net amount payable to partner
      }
    ],
    "2025-02-01": [...]
  },
  "competenciaEmProcessamento": "2025-06-01"
}
```

## Classification rules for partner transfers

1. Find the competence month in `prolabore-anual`.
2. Match the partner by name and/or `partner.__identity`.
3. Compare bank transfer(s) to **`valorLiquido`** (net), not gross `valor`.
4. If a single transfer equals `valorLiquido`:
   → Classify as `Folha de pagamento > Retirada de Pró-labore`.
5. If a single transfer exceeds `valorLiquido`:
   → Split: `valorLiquido` → pró-labore; excess → `Dividendos - Patrimonial > Adiantamento de lucro`.
6. If one transfer covers pró-labore and another transfer remains in the same month:
   → First transfer → pró-labore; second → adiantamento de lucro (subject to accountant validation).
7. Keep INSS/IRRF as separate tax/payroll obligations, not as cash paid to the partner.

## Required fields for pro-labore transactions

Pro-labore categories have `personRequired=true` / `requiredPersonType=partner`. The transaction update must include:

```
person=<partner_person_uuid>
evidence[prolabore]=<prolabore_uuid>
```

Fetch partners:
```
GET /api/v1/companies/{cid}/people?type=partner&count=3000
```

Fetch the monthly pro-labore record (not the annual reference):
```
GET /api/v1/companies/{cid}/prolabores?competence=YYYY-MM-01T00:00:00-0300&count=3000
```

## Profit distribution / adiantamento de lucro

For transfers classified as profit advance/distribution:

- Category: `Dividendos - Patrimonial > Adiantamento de lucro` (or `Receitas > Adiantamento de dividendo` if it's a return).
- If the category has `personRequired=true` for partners, include `person=<partner_uuid>`.
- No pro-labore evidence is needed for profit distribution.

## Pro-labore PDF evidence

For supporting documentation, download the pro-labore PDF:

```
GET /api/v1/companies/{cid}/prolabore-anual/download?competence=YYYY-MM-01T00:00:00-0300&partner={partner_id}
```

This can be used as evidence attachment or for audit trails.

## Multi-partner scenarios

If the company has multiple partners:

1. Fetch `/prolabore-anual` for all partners.
2. For each partner transfer, identify the beneficiary by name/account.
3. Match each to the correct `contracheque` entry.
4. Do not assume all partner transfers in a month are the same type (one may be pró-labore, another may be profit distribution).

## Verification

After classifying partner transfers:

- [ ] Each pró-labore transaction has `person` set to the correct partner.
- [ ] Each pró-labore transaction has `evidence[prolabore]` linked.
- [ ] No pro-labore evidence is duplicated across transactions.
- [ ] Excess transfers are classified as adiantamento de lucro.
- [ ] INSS/IRRF obligations are separate from cash paid to partners.
- [ ] Totals reconcile: sum of pró-labore + adiantamento = total transferred to partner.
