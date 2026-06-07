---
stepId: review-mode
runtime: agent-loop
---

# Review Mode

Scoped revision pass — user picks a specific month AND a specific revision type, then works through only those issues for that scope. This is distinct from the full monthly close: no new data is ingested, no new snapshots are generated. The purpose is to resolve issues that were deferred during a close or to apply targeted corrections to a completed month.

**Two entry points:**
1. **Gatekeeper deferral.** At the end of a gastos or investimentos close, the gatekeeper loop (`gatekeeper-loop.md` Rule C) may have accumulated deferrable issues. After presenting the deferrable list, the loop asks: "Run review mode now or later?" — [S] now or [D] defer. Choosing [S] calls this file with the deferrable list pre-loaded as the initial queue.
2. **Direct activation.** User runs `sb-bookkeeper` and selects `[4] Review` at the flow prompt. No pre-loaded queue; user picks month and revision type interactively.

**Language and UI (binding).** User-facing strings in `communication.language`. Load `communication` and `batch_ui` from `{CONFIG_DIR}/standing-rules.yaml` via `lib.standing_rules.load_communication()` and `load_batch_ui()`. Decision surface shapes follow `batch_ui` — one row = one decision (`batch_ui.tags.one_row_one_decision`); do not aggregate suppliers (`batch_ui.sub_items.aggregate_suppliers: false`).

---

## Path Variables

```
WORKFLOW_DIR = 3-resources/tools/sb-os/finance/workflows/sb-bookkeeper
CONFIG_DIR   = .user/finance/bookkeeper/config
DASHBOARD_DATA = .user/finance/bookkeeper/ledgers/fechamento
```

---

## Mandatory Sequence

### Section 1 — Scope selection

1. If called from the gatekeeper's deferrable list (Entry point 1), the `{MONTH}` is already set (the month just closed). Go directly to step 3 of this section.

2. If called directly (Entry point 2), ask the user:

   ```
   Review mode — which month? (e.g., 2026-03)
   ```

   STOP. Await response. Set `{MONTH}`.

3. Present the revision-type menu:

   ```
   Which revision type for {MONTH}?

     [1] Categories — review or correct transaction categories
     [2] Suppliers — rename canonicals, adjust aliases or movable
     [3] Tags — accept, merge, or reject pending tags
     [4] Competência — adjust competência dates (Pass 3 / cross-month)
     [5] Deferred items — resolve items flagged as deferrable in the close
     [6] Free — type a specific revision instruction

   Choose one or more types (e.g.: "1,3" or "5"):
   ```

   STOP. Await response. Set `{REVISION_TYPES}` as the chosen list.

4. Confirm scope:

   ```
   Reviewing {MONTH}: {list of chosen types}. Loading…
   ```

### Section 2 — Load the scoped queue

1. Load `{DASHBOARD_DATA}/{MONTH}/transactions.csv`. If the file does not exist, report: "Month {MONTH} not found in `ledgers/fechamento/`. Check the month and try again." Halt.

2. Load supporting config files needed by the chosen revision types:
   - Types 1, 2, 3: load `{CONFIG_DIR}/suppliers.json`, `{CONFIG_DIR}/tags.json`, `{CONFIG_DIR}/categories.json`.
   - Type 4: load `{CONFIG_DIR}/corrections/competencia-overrides.csv` via `lib.queue.load_competencia_overrides`.
   - Type 5: use the deferrable list passed in from the gatekeeper loop (already in memory if Entry point 1; otherwise report "No deferred items found for {MONTH}." and ask whether to continue with another revision type).

3. Build the revision queue for each chosen revision type:
   - **Type 1 (Categories):** filter `transactions.csv` for rows with `category` matching a value the user flags as needing review, OR rows with `manual_override = false` in a contested category. The user may also type a category name to scope further.
   - **Type 2 (Suppliers):** filter for rows where `supplier_canonical` is blank, a known alias has drifted, or the user wants to batch-rename. Present per-canonical groups.
   - **Type 3 (Tags):** filter for rows with blank `tags` (untagged) or with `proposed_token` items deferred from Pass 1. Use the same `build_pass_1_queue` tag sub-queue over the scoped month.
   - **Type 4 (Competência):** filter for reimbursement-matched rows whose `data_competencia == data_caixa` (potential cross-month candidates), plus any rows in the Pass 3 queue (`lib.queue.build_pass_3_queue`).
   - **Type 5 (Deferred items):** the deferrable list from the gatekeeper. Each item carries a `why_deferred` note; present it alongside the item.
   - **Type 6 (Free):** present a plain-text prompt; the user drives the revision step by step. No structured queue.

4. If all queues for the chosen revision types are empty, report: "No items to review of the selected type in {MONTH}." Ask whether to pick another revision type or exit.

### Section 3 — Process the queue

Present items batch-by-batch (5–7 per batch), one item per row, following `batch_ui` rules. Do NOT aggregate suppliers across items; each row is one decision.

**For each item, display:**
- `data_caixa · supplier_canonical · amount · category · tags` (as applicable to the revision type)
- The specific decision prompt for the revision type:

  - Type 1: `Current category: {category}. Keep, or new category?`
  - Type 2: `Current canonical: {canonical}. Rename, or add alias?`
  - Type 3: `Proposed tag: {token}. [A] Accept / [M] Merge with {existing} / [R] Reject`
  - Type 4: `Current competência: {data_competencia}. Keep = {data_caixa}, or move to which month?`
  - Type 5: `Reason for deferral: {why_deferred}. {original type's specific prompt}`

**Apply resolutions** through the registered write tools:

- **Category, supplier_canonical, tags, recurrence, data_competencia, manual_override changes on a closed month** → MUST use the registered `apply_review_resolution` tool (`migrations/apply_review_resolution.py`, class `write`/`retro-rewrite`). Protocol:
  1. Run dry-run preview (default — no `--apply`): confirms the identity triple matches exactly one row and enumerates every affected location.
  2. Present the preview to the user and await confirmation.
  3. Run with `--apply` to re-stamp the matched row and optionally append a canonical correction row to `manual-overrides.csv` or `competencia-overrides.csv`.
  4. Applying a resolution via an unregistered ad-hoc script is a tools-only-invariant violation — if no write tool exists for the needed mutation, that is a Rule B deviation (missing write capability → `tool-builder`).
  - The underlying lib functions (`lib.queue.apply_pass_1_resolution`, `lib.queue.apply_pass_3_resolution`) are the mechanism the tool uses internally; they are NOT a direct agent-facing apply path.

- **Supplier config changes (canonical rename, alias edits)** → use `rename_canonical` tool (`migrations/rename_canonical.py`).
- **Tag changes on the namespace** → use `rename_tags` tool (`migrations/rename_tags.py`) or `lib.tags.accept_tag` / `merge_tag` / `reject_tag` + `lib.tags.save_tags` for within-session tag-state edits that do not require a durable retro-rewrite.
- **New category creation** → update `{CONFIG_DIR}/categories.json` directly (config file, not a ledger row — direct edit is permitted).
- `data_caixa` is NEVER mutable — the `apply_review_resolution` tool hard-rejects any attempt to set it.

After each batch, persist changes to the relevant config files and to `transactions.csv` (via the tool's atomic write — never a direct row edit on a frozen close).

### Section 4 — Save and report

1. Write the revised `transactions.csv` back to `{DASHBOARD_DATA}/{MONTH}/transactions.csv` using `atomic_write` (from `shared/lib/safe_write.py`) — same atomic-write pattern as the main close.

2. Confirm to the user:

   ```
   Review complete — {MONTH}, type(s): {REVISION_TYPES}.
   {N_resolved} items resolved. {N_skipped} skipped.
   CSV saved.
   ```

3. If there are remaining unresolved items in the queue, ask: "{N_remaining} items remaining. Continue now or defer to a next session?"

4. STOP. Await confirmation.

---

## Step Menu

- **Gatekeeper checkpoint** → before saving, run § Per-Step Checkpoint in `../gatekeeper-loop.md`. A revision that creates or modifies a data store, config dict, or dashboard-consumed script triggers Rule A.1 (ME gate).
- **[N] New month / type** → return to Section 1 without exiting (pick a different month or revision type).
- **[X] Exit** → exit review mode. Changes already applied and saved are preserved.

---

## Wire Notes

- **Gatekeeper seam.** Rule C of `gatekeeper-loop.md` (deferrable → review-mode) routes to this file. The gatekeeper loop records items in the deferrable list and surfaces them at close end; this file is where those items are resolved. The gatekeeper does not implement the per-revision-type scoping — this file does.
- **`batch_ui` binding.** `batch_ui.tags.one_row_one_decision = true` and `batch_ui.sub_items.aggregate_suppliers: false` are enforced here. Every queue item is one row, one prompt, one decision. The sub-items rule is especially load-bearing for Type 2 (suppliers) — do not batch multiple canonical proposals into one prompt.
- **Corrections convention.** Revisions to a frozen past-close month MUST route through the registered `apply_review_resolution` tool (`migrations/apply_review_resolution.py`) — it re-stamps the matched row in `transactions.csv` (atomic write) and optionally appends a durable correction row to the corrections side-ledger (`manual-overrides.csv` or `competencia-overrides.csv`). The corrected value propagates on next regeneration via the corrections protocol (`categorize.py` loads those files). Applying a resolution through an unregistered ad-hoc script is a tools-only-invariant violation. This preserves the append-only-ledger constraint for months closed with `--force`.
