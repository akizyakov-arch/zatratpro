# Document Extraction Prompt Tuning Backlog (`v0.5.8.27`)

## Working Baseline

Current extraction architecture is considered a valid working point:

- `05db9bd` `Add document extraction routing skeleton`
- `da7d783` `Document extraction strategy in env example`
- `6bb001a` `Add family-aware extraction prompt registry`
- `fa8d1f3` `Tighten item math for table documents`

What is already working:

- `DocumentExtractionService` is the single strategy boundary
- `DOCUMENT_EXTRACTION_STRATEGY` switch is in place
- family routing works for:
  - `fiscal_documents`
  - `primary_table_documents`
  - `vat_documents`
  - `cash_order_documents`
  - `generic_fallback`
- extraction still goes through the same pipeline:
  - extraction
  - `DocumentSchema` normalization
  - schema validation
  - business validation
- no new FSM or UI flow was introduced

This means the next step is not architecture work, but prompt-quality tuning.

---

## Phase C Goal

Improve extraction quality inside already working families without changing:

- routing architecture
- extraction strategy switch
- JSON contract
- preview/save/duplicate flow

Scope of the next block:

1. `primary_table_documents`
2. `vat_documents`

---

## Problem 1 — `primary_table_documents`

### Observed issue

On some goods invoice / table-document samples:

- document family is detected correctly
- final `total` is correct
- but item-level math is still wrong:
  - wrong `quantity`
  - wrong `price`
  - wrong row-level arithmetic interpretation

### Target behavior

For table documents:

- do not infer `quantity`, `price`, or `line_total` by reverse math unless the row is explicit
- if only row amount is reliable, keep `line_total` and allow `quantity = null`, `price = null`
- do not bind neighboring numeric columns incorrectly
- prefer partial but reliable row extraction over confident false math

### Prompt tuning goals

Add stronger family-specific rules for `primary_table_documents`:

- column mapping must be conservative
- quantity/price/line_total must come only from explicit row values
- if OCR suggests conflicting numeric interpretations, prefer `line_total`
- do not fabricate row arithmetic from visually noisy table fragments
- if the row is real but some numeric columns are unreliable, return partial item data

---

## Problem 2 — `vat_documents`

### Observed issue

On some VAT invoice samples:

- family is detected correctly
- document type is correct
- but `sum without VAT` is treated incorrectly

Typical risk:

- `сумма без НДС` is confused with `vat_total_amount`
- base amount, VAT amount, and grand total are mixed

### Target behavior

For VAT documents:

- `vat_total_amount` must contain only the VAT amount
- `сумма без НДС` is not VAT amount
- `итого с НДС` is not VAT amount
- `vat_scope` must reflect what is explicitly shown, not inferred from nearby totals

### Prompt tuning goals

Add stronger family-specific rules for `vat_documents`:

- separate:
  - taxable base / amount without VAT
  - VAT amount
  - total including VAT
- map `vat_total_amount` only from explicit VAT fields
- do not populate `vat_total_amount` from base amount or total amount
- keep `vat_total_amount = null` when VAT amount is not clearly visible

---

## Out of Scope

This block must not include:

- routing refactor
- new document families
- handler changes
- new FSM logic
- duplicate/save flow changes
- business validation rewrite

If a future correction is needed in schema/business rules, it should be added only after prompt tuning shows a stable repeated pattern.

---

## Recommended Execution Order

### Step 1

Tune `primary_table_documents` prompt rules.

### Step 2

Tune `vat_documents` prompt rules.

### Step 3

Re-run the same representative samples and compare:

- `document_type`
- `items`
- `quantity`
- `price`
- `line_total`
- `vat_total_amount`
- `vat_scope`
- `total`

### Step 4

Only if prompt tuning is still insufficient, consider narrow post-validation fixes.

---

## Acceptance Criteria

### For `primary_table_documents`

- fewer false `quantity/price` combinations
- fewer wrong row-level arithmetic interpretations
- no regression in correct `total`
- no growth in fake item rows

### For `vat_documents`

- `vat_total_amount` is no longer populated from `сумма без НДС`
- clearer separation of VAT base vs VAT amount vs total
- no regression in correct `document_type`

---

## Practical Conclusion

Current routing/extraction code can be treated as a stable architectural baseline.

The next block is a focused prompt-quality pass, not a new refactor.
