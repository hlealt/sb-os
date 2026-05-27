---
stepNumber: 4
stepId: categorize
nextStepFile: step-05-review.md
---

# Step 4: Categorize

**Goal:** Run `categorize.py` to auto-classify transactions, then read its structured stdout to surface unknowns by item type (categorias, fornecedores, tags) — priming Pass 1 of the review queue in step-05.

## Mandatory Sequence

1. Run:
   ```bash
   python "{SCRIPTS_DIR}/categorize.py" "{PROCESSED_DIR}" "{CONFIG_DIR}" "{DASHBOARD_DATA}/{MONTH}"
   ```

2. Parse the script stdout for the three structured sections emitted by `categorize.py`:
   - `UNKNOWN CATEGORIES` — transactions with `category = a_identificar` (description, bank, amount, date).
   - `UNKNOWN SUPPLIERS` — distinct descriptions where alias detection produced no canonical supplier (grouped by description, count per group).
   - `UNKNOWN TAGS` — distinct legacy-subcategory tokens surfaced as candidate tags (count per token + sample description).

   Each section starts with `Count:` (or `Distinct legacy-subcategory suggestions:` for tags). Read the counts and the sample rows.

3. Report the counts to the user in PT-BR, in a single line:

   ```
   Categorias desconhecidas: {N1} · Fornecedores desconhecidos: {N2} · Tags desconhecidas: {N3}
   ```

   If any count is zero, still report it (`0`) — the review queue in step-05 silently skips empty item-type batches per the queue ordering invariant.

4. Confirm to the user that o CSV foi escrito em `{DASHBOARD_DATA}/{MONTH}/transactions.csv` com o novo schema (`data_caixa`, `data_competencia`, `supplier_canonical`, `tags`).

5. Hand off to step-05 carrying the parsed unknowns, batched by item type (categorias → fornecedores → tags) — this ordering is mandatory for the two-pass queue (Pass 1 must close before Pass 2 boundary prompts can fire in step-05).

6. STOP. Wait for confirmation.

## Step Menu

- **Gatekeeper checkpoint** → before advancing, run § Per-Step Checkpoint in `../gatekeeper-loop.md` (out-of-structure → Rule A; detected issue → Rule C blocking/deferrable; direct data read → re-route through a `tools-index.md` tool). The unknowns surfaced here (categorias/fornecedores/tags) are the deviation-to-structure protocol's input — Step 05 resolves them per Rule B.
- **[C] Continuar** → seguir para o Step 05 (Pass 1 — Resolução de desconhecidos)
- **[X] Sair** → encerrar workflow
