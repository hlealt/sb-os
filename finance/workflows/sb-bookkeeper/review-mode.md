---
stepId: review-mode
runtime: agent-loop
---

# Review Mode

Scoped revision pass — user picks a specific month AND a specific revision type, then works through only those issues for that scope. This is distinct from the full monthly close: no new data is ingested, no new snapshots are generated. The purpose is to resolve issues that were deferred during a close or to apply targeted corrections to a completed month.

**Two entry points:**
1. **Gatekeeper deferral.** At the end of a gastos or investimentos close, the gatekeeper loop (`gatekeeper-loop.md` Rule C) may have accumulated deferrable issues. After presenting the deferrable list, the loop asks: "Rodar o modo de revisão agora ou depois?" — [S] now or [D] defer. Choosing [S] calls this file with the deferrable list pre-loaded as the initial queue.
2. **Direct activation.** User runs `sb-bookkeeper` and selects `[4] Revisão` at the flow prompt. No pre-loaded queue; user picks month and revision type interactively.

**Language and UI (binding).** User-facing strings in PT-BR. Load `communication` and `batch_ui` from `{CONFIG_DIR}/standing-rules.yaml` via `lib.standing_rules.load_communication()` and `load_batch_ui()`. Decision surface shapes follow `batch_ui` — one row = one decision (`batch_ui.tags.one_row_one_decision`); do not aggregate suppliers (`batch_ui.sub_items.aggregate_suppliers: false`).

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
   Modo de revisão — qual mês? (e.g., 2026-03)
   ```

   STOP. Await response. Set `{MONTH}`.

3. Present the revision-type menu:

   ```
   Qual tipo de revisão para {MONTH}?

     [1] Categorias — revisar ou corrigir categorias de transações
     [2] Fornecedores — renomear canônicos, ajustar aliases ou movable
     [3] Tags — aceitar, mesclar ou rejeitar tags pendentes
     [4] Competência — ajustar datas de competência (Pass 3 / cross-month)
     [5] Itens adiados — resolver itens marcados como deferrable no fechamento
     [6] Livre — digitar uma instrução de revisão específica

   Escolha um ou mais tipos (ex: "1,3" ou "5"):
   ```

   STOP. Await response. Set `{REVISION_TYPES}` as the chosen list.

4. Confirm scope in PT-BR:

   ```
   Revisão de {MONTH}: {lista de tipos escolhidos}. Carregando…
   ```

### Section 2 — Load the scoped queue

1. Load `{DASHBOARD_DATA}/{MONTH}/transactions.csv`. If the file does not exist, report: "Mês {MONTH} não encontrado em `ledgers/fechamento/`. Verifique o mês e tente novamente." Halt.

2. Load supporting config files needed by the chosen revision types:
   - Tipos 1, 2, 3: load `{CONFIG_DIR}/suppliers.json`, `{CONFIG_DIR}/tags.json`, `{CONFIG_DIR}/categories.json`.
   - Tipo 4: load `{CONFIG_DIR}/corrections/competencia-overrides.csv` via `lib.queue.load_competencia_overrides`.
   - Tipo 5: use the deferrable list passed in from the gatekeeper loop (already in memory if Entry point 1; otherwise report "Nenhum item adiado encontrado para {MONTH}." and ask whether to continue with another revision type).

3. Build the revision queue for each chosen revision type:
   - **Tipo 1 (Categorias):** filter `transactions.csv` for rows with `category` matching a value the user flags as needing review, OR rows with `manual_override = false` in a contested category. The user may also type a category name to scope further.
   - **Tipo 2 (Fornecedores):** filter for rows where `supplier_canonical` is blank, a known alias has drifted, or the user wants to batch-rename. Present per-canonical groups.
   - **Tipo 3 (Tags):** filter for rows with blank `tags` (untagged) or with `proposed_token` items deferred from Pass 1. Use the same `build_pass_1_queue` tag sub-queue over the scoped month.
   - **Tipo 4 (Competência):** filter for reimbursement-matched rows whose `data_competencia == data_caixa` (potential cross-month candidates), plus any rows in the Pass 3 queue (`lib.queue.build_pass_3_queue`).
   - **Tipo 5 (Itens adiados):** the deferrable list from the gatekeeper. Each item carries a `why_deferred` note; present it alongside the item.
   - **Tipo 6 (Livre):** present a plain-text prompt; the user drives the revision step by step. No structured queue.

4. If all queues for the chosen revision types are empty, report: "Nenhum item para revisão do tipo selecionado em {MONTH}." Ask whether to pick another revision type or exit.

### Section 3 — Process the queue

Present items batch-by-batch (5–7 per batch), one item per row, following `batch_ui` rules. Do NOT aggregate suppliers across items; each row is one decision.

**For each item, display:**
- `data_caixa · supplier_canonical · amount · category · tags` (as applicable to the revision type)
- The specific decision prompt for the revision type (PT-BR):

  - Tipo 1: `Categoria atual: {category}. Manter, ou nova categoria?`
  - Tipo 2: `Canônico atual: {canonical}. Renomear, ou adicionar alias?`
  - Tipo 3: `Tag proposta: {token}. [A] Aceitar / [M] Mesclar com {existing} / [R] Rejeitar`
  - Tipo 4: `Competência atual: {data_competencia}. Manter = {data_caixa}, ou mover para qual mês?`
  - Tipo 5: `Motivo do adiamento: {why_deferred}. {prompt específico do tipo original}`

**Apply resolutions** via the same lib functions used in Step 5 (gastos review):
- Category changes → `lib.queue.apply_pass_1_resolution(..., {"category": ...})` + update `{CONFIG_DIR}/categories.json` if a new category is created.
- Supplier changes → update `{CONFIG_DIR}/suppliers.json` and re-apply to affected rows.
- Tag changes → `lib.tags.accept_tag` / `merge_tag` / `reject_tag` + `lib.tags.save_tags`.
- Competência changes → `lib.queue.apply_pass_3_resolution(...)` — updates `data_competencia`; `data_caixa` NEVER changes.
- Corrections that override historical rows → append to the matching `{CONFIG_DIR}/corrections/*.csv` file (never edit `transactions.csv` rows directly for a past close that has been frozen with `--force`).

After each batch, persist changes to the relevant config files and to a working copy of `transactions.csv`.

### Section 4 — Save and report

1. Write the revised `transactions.csv` back to `{DASHBOARD_DATA}/{MONTH}/transactions.csv` using `atomic_write` (from `shared/lib/safe_write.py`) — same atomic-write pattern as the main close.

2. Confirm to the user (PT-BR):

   ```
   Revisão concluída — {MONTH}, tipo(s): {REVISION_TYPES}.
   {N_resolved} itens resolvidos. {N_skipped} ignorados.
   CSV salvo.
   ```

3. If there are remaining unresolved items in the queue, ask: "Há {N_remaining} itens restantes. Continuar agora ou adiar para uma próxima sessão?"

4. STOP. Await confirmation.

---

## Step Menu

- **Gatekeeper checkpoint** → before saving, run § Per-Step Checkpoint in `../gatekeeper-loop.md`. A revision that creates or modifies a data store, config dict, or dashboard-consumed script triggers Rule A.1 (ME gate).
- **[N] Novo mês / tipo** → return to Section 1 without exiting (pick a different month or revision type).
- **[X] Sair** → exit review mode. Changes already applied and saved are preserved.

---

## Wire Notes

- **Gatekeeper seam.** Rule C of `gatekeeper-loop.md` (deferrable → review-mode) routes to this file. The gatekeeper loop records items in the deferrable list and surfaces them at close end; this file is where those items are resolved. The gatekeeper does not implement the per-revision-type scoping — this file does.
- **`batch_ui` binding.** `batch_ui.tags.one_row_one_decision = true` and `batch_ui.sub_items.aggregate_suppliers: false` are enforced here. Every queue item is one row, one prompt, one decision. The sub-items rule is especially load-bearing for Tipo 2 (fornecedores) — do not batch multiple canonical proposals into one prompt.
- **Corrections convention.** Revisions to a frozen past-close month write to the corrections side-ledger (append-only), not directly to `transactions.csv` rows. The corrected value is re-stamped on next regeneration via the corrections protocol (`categorize.py` loads `manual-overrides.csv` and `competencia-overrides.csv`). This preserves the append-only-ledger constraint for months that have been closed with `--force`.
