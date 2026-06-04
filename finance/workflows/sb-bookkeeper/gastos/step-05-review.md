---
stepNumber: 5
stepId: review
nextStepFile: step-06-report.md
---

# Step 5: Two-Pass Review Queue

**Goal:** Resolve the unknowns (Pass 1) and, only after Pass 1 is closed, run the month-boundary prompts (Pass 2). Capture cash expenses between the two passes. Persist all decisions to `suppliers.json`, `tags.json`, `categories.json`, and the month's CSV.

## Architectural Invariants (binding)

- **Ordering (data-model §6 invariant 8):** Pass 1 MUST close completely (zero pending items in categories, suppliers AND tags) before any call to Pass 2. Boundary depends on `supplier.movable` resolved in Pass 1.
- **Boundary scope (data-model §6 invariant 9):** Pass 2 only fires for transactions with `is_boundary_day(data_caixa) AND supplier.movable == true AND source_type != 'fatura'`. Outside that scope, no prompt.
- **`data_caixa` immutable:** Pass 2 updates ONLY `data_competencia`. NEVER touches `data_caixa`.
- **Skip-default (Q13a):** The default action in Pass 2 is "keep" → `data_competencia = data_caixa`. No silent flag, no auto-push.
- **Language:** All user-facing strings in `communication.language` (standing-rules.yaml). Lib function names, paths, and column identifiers stay in English.

## Mandatory Sequence

### Section 1 — Pass 1 (Resolve unknowns)

1. Load:
   - `{DASHBOARD_DATA}/{MONTH}/transactions.csv` (the CSV written by step-04).
   - `{CONFIG_DIR}/suppliers.json` via `lib.suppliers.load_suppliers`.
   - `{CONFIG_DIR}/tags.json` via `lib.tags.load_tags`.
   - `{CONFIG_DIR}/categories.json` (raw dict — `lib.queue.build_pass_1_queue` reads `movable_hint` per category).

2. Build the Pass 1 queue by calling `lib.queue.build_pass_1_queue(transactions, suppliers_index, categories_data, tags_index)`. The queue comes already grouped by `item_type` in the order `category` → `supplier` → `tag`, sorted by date within each group.

3. Process the queue by item_type, in batches of 5–7 items. If an item_type is empty, skip silently to the next (do not display an empty section).

   **Batch — categories:**
   - For each item, show: `description · amount · date` and the list of available categories from the `categories` block in `categories.json`.
   - Accept the default suggestion (if any) with a single key — target ≤15s/item per spec §T2.
   - Allow free typing to create a new category; in that case, update `categories.json` (`categories` block) inserting the new entry with the `movable_hint` asked of the user (`movable | non-movable | mixed`).
   - Apply the answer with `lib.queue.apply_pass_1_resolution(transactions, item, {"category": "<value>"})`.
   - If the categorization implies a new supplier (or a new alias on an existing supplier), append the entry to `suppliers.json` with the corresponding `default_category`. (Single layer post-Phase-6 — `vendor_mappings` no longer exists in `categories.json`.)

   **Batch — suppliers:**
   - For each item, show: `description · amount · date · already-resolved category`.
   - Ask for the `canonical` (canonical name) and the `aliases` (list; at least the original description).
   - Ask for the `movable` (`true | false`) — mandatory WHENEVER `categories[<category>].movable_hint == 'mixed'`. For `movable_hint == 'movable'` or `'non-movable'`, pre-fill the default and accept with a single key; the user may override.
   - Ask for the `default_category` (suggest the category already resolved in the item).
   - Persist to `suppliers.json` (new slug in `suppliers`, with `canonical`, `aliases`, `movable`, `default_category`). Reload the `SupplierIndex` after each write.
   - Apply with `lib.queue.apply_pass_1_resolution(transactions, item, {"canonical": "<canonical>", "match_confidence": "exact"})`.

   **Batch — tags:**
   - For each item, show: `proposed_token · description · amount`.
   - Three-option prompt:
     - `[A] Accept` — adds the tag to the dictionary and to the transaction's `tags` column.
     - `[M] Merge with existing tag` — ask for the `existing_token` (from the `tags` block in `tags.json`); replaces the `proposed_token` with the existing one in the transaction's `tags` column.
     - `[R] Reject` — notes the reason; increments `return_count`. Before calling `lib.tags.reject_tag` on subsequent rejections of the same token, call `lib.tags.should_resurface(token, index)`; if `True`, re-present to the user with the message "This tag came back — reconsider?" before incrementing.
   - Validate `proposed_token` with `lib.tags.is_valid_token` before accepting/rejecting.
   - Apply:
     - Accept → `lib.tags.accept_tag(token, label, notes, today, tag_index)`, persist with `lib.tags.save_tags`, and `lib.queue.apply_pass_1_resolution(transactions, item, {"decision": "accept", "token": "<token>"})`.
     - Merge → `lib.tags.merge_tag(proposed, existing, today, tag_index)`, persist, and `apply_pass_1_resolution` with `{"decision": "merge", "token": "<proposed>", "merge_into": "<existing>"}`.
     - Reject → `lib.tags.reject_tag(token, reason, today, tag_index)`, persist, and `apply_pass_1_resolution` with `{"decision": "reject", "token": "<token>"}`.
   - ALWAYS read/write the transaction's `tags` column via `lib.tags.parse_tag_column` and `lib.tags.serialize_tag_column` (semicolon-separated format per data-model §1.3).

4. When all three queues are empty, **declare Pass 1 closed**. Save the intermediate CSV (`transactions.csv`) with the resolutions applied. Confirm to the user: `Pass 1 closed. {N_cat} categories, {N_sup} suppliers, {N_tag} tags resolved.`

5. **Completion gate — Pass-1-queue closure (`gate_pass_1_queue.py`, gate #11 — auto-halt).** Before any call to Pass 2, write the queue-state file and run the gate. This mechanizes the ordering invariant (data-model §6 invariant 8) as an exit-code gate, instead of relying only on the runtime `QueueOrderingError`.

   a. Write the queue-state JSON to `{DASHBOARD_DATA}/{MONTH}/.pass-queue-state.json` with EXACTLY these two keys (gate #11 reads only these — do not invent other fields):

      ```json
      {
        "pass_1_items": [],
        "pass_2_items": ["<one marker per Pass-2-candidate boundary item>"]
      }
      ```

      - `pass_1_items`: the list of Pass 1 items STILL unresolved (pending categories/suppliers/tags). After step 4, this list MUST be empty (`[]`).
      - `pass_2_items`: the list of Pass 2 candidates — the transactions that satisfy `is_boundary_day(data_caixa) AND supplier.movable == true AND source_type != 'fatura'` (the same filtering as Section 3). One item per candidate (a stable row identifier, e.g. `tx_date|tx_description|tx_amount`, suffices as a marker). If there are no candidates, use `[]`.

   b. Run the gate:

      ```bash
      python "{SCRIPTS_DIR}/gate_pass_1_queue.py" --queue-state "{DASHBOARD_DATA}/{MONTH}/.pass-queue-state.json"
      ```

      The gate fires (exit 1) only when `pass_2_items` is non-empty AND `pass_1_items` is non-empty (the `QueueOrderingError` condition). Exit 0 = Pass 1 closed (or no pending Pass 2 work); exit 2 = file missing/malformed.

   - **Exit 0** → record the pass and proceed to Section 2.
   - **Exit 1 (FAIL)** → Rule C **blocking** (`../gatekeeper-loop.md`). Do NOT proceed to Pass 2. Return to step 3 and clear the remaining Pass 1 items; rewrite the queue-state JSON and run the gate again. The step does not advance until the gate returns exit 0.

> ⛔ **Gate:** Do not proceed to Section 3 (Pass 2) until `gate_pass_1_queue.py` returns exit 0. The call to `lib.queue.build_pass_2_queue` also raises `QueueOrderingError` if any transaction has an unresolved category/supplier — gate #11 is the exit-code form of the same invariant.

### Section 2 — Cash expenses

Ask the user:

> "Were there any cash expenses this month that do not appear in the bank statements?"

If yes, for each cash expense, append a row to the CSV with:

| Field | Value |
|-------|-------|
| `bank` | `manual` |
| `source_type` | `dinheiro` |
| `match_confidence` | `manual` |
| `data_caixa` | date provided by the user |
| `data_competencia` | same as `data_caixa` (default; user may override) |
| `supplier_canonical` | `Cash` |
| `tags` | `""` (empty string — no tags) |
| `category` | category provided by the user |
| `amount`, `description` | provided by the user |

Save the CSV.

### Section 3 — Pass 2 (Month boundaries)

1. Reload `transactions.csv` (with Pass 1 resolutions + cash expenses), `suppliers.json` (updated in Pass 1), and `categories.json`.

2. Build the Pass 2 queue by calling `lib.queue.build_pass_2_queue(transactions, suppliers_index, categories_data)`. Internally the function:
   - Verifies that every transaction has a resolved category and supplier (otherwise raises `QueueOrderingError` — a sign of a Pass 1 bug).
   - Resolves the effective `movable` via `lib.suppliers.get_supplier_movable(canonical, index, category_hint)`. If it raises `UnresolvedMovableError`, return to Pass 1 and handle the supplier with `movable_hint == 'mixed'` before proceeding.
   - Filters by `lib.boundary.needs_boundary_prompt(transaction, supplier_movable, data_caixa)` — only items where `is_boundary_day(data_caixa) AND supplier_movable AND source_type != 'fatura'`.
   - Each returned item has `prompt_default = 'keep'` (Q13a).

3. If the queue comes back empty, report `No candidates for Pass 2.` and proceed to Section 4.

4. For each item, in chronological order:
   - Show: `description · amount · data_caixa · supplier_canonical · current data_competencia`.
   - Prompt:

     ```
     [M] Keep competência = caixa (default)
     [V] Move competência to another month — provide new ISO date (YYYY-MM-DD)
     ```

   - Single ENTER key or `[M]` → action `keep`. Modifies nothing. (Skip-default Q13a.)
   - `[V]` + date → action `move`. Apply with `lib.queue.apply_pass_2_resolution(transactions, item, {"action": "move", "new_date": <date>})`. ONLY `data_competencia` is updated — `data_caixa` stays immutable.

### Section 4 — Save and continue

1. Write the final CSV to `{DASHBOARD_DATA}/{MONTH}/transactions.csv` (overwrites the intermediate).

2. **Completion gate — tag coverage before commit (`gate_coverage.py`, gates #1/#2/#3 ANDed — auto-LOOP).** Run over the final CSV:

   ```bash
   python "{SCRIPTS_DIR}/gate_coverage.py" --transactions "{DASHBOARD_DATA}/{MONTH}/transactions.csv" --loop-count {LOOP_COUNT}
   ```

   The three gates are ANDed in a single call (exit 0 only if ALL pass): #1 R$ coverage ≥ 90%, #2 row coverage ≥ 90%, #3 no untagged expense with `abs(amount) > R$100`. Excludes `receitas`/`intercontas`/`ignorar`/`venda`. `{LOOP_COUNT}` starts at `0`.

   - **Exit 0** → all three gates passed. Record the pass and proceed to step 3.
   - **Exit 1 (FAIL) with `{LOOP_COUNT} < 3`** → this gate **auto-loops** (it is not an inline halt). Return to the tag batch (Section 1 § Batch — tags) and tag the expenses lacking coverage, increment `{LOOP_COUNT}` by 1, rewrite the CSV, and run the gate again. This repeats until exit 0 or until `{LOOP_COUNT}` reaches 3.
   - **Exit 1 (FAIL) with `{LOOP_COUNT} == 3`** → the gate's max-loop guard prints the prompt "Prosseguir mesmo assim? [S/N]". Treat as Rule C **blocking**: surface the prompt to the user; `[S]` → record the exception and proceed; `[N]` → keep correcting or stop the close.
   - **Exit 2** → CSV missing/malformed; report and ask how to proceed.

3. Confirm to the user: `Review complete. {N_pass1} resolutions (Pass 1) + {N_cash} cash expenses + {N_pass2_moved} competências moved (Pass 2). Tag coverage approved. CSV saved.`
4. STOP. Wait for confirmation to continue.

## Step Menu

- **Gatekeeper checkpoint** → before advancing, run § Per-Step Checkpoint in `../gatekeeper-loop.md`. This step's two-pass review queue IS the deviation-to-structure protocol (Rule B) for new categories/suppliers/tags; a deviation needing a new tool or parser routes to Rule B Seam 1 (`tool-builder`), and a structure change routes to Seam 2 (`doc-maintainer`). Two completion gates fire in this step: `gate_pass_1_queue.py` (#11, auto-halt, before Pass 2) and `gate_coverage.py` (#1/#2/#3, auto-loop to the tag batch, before commit).
- **[C] Continue** → proceed to Step 06 (Generate Report)
- **[X] Exit** → halt workflow
