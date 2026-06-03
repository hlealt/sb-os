---
stepId: gatekeeper-loop
runtime: agent-loop
---

# Gatekeeper Loop

The runtime protocol that makes `sb-bookkeeper` an active-agency gatekeeper instead of a passive script runner. This file is the single home for the three gatekeeper rules; `sb-bookkeeper.md` § What This Workflow Does describes WHAT they are, this file defines HOW they run.

**Runtime model.** This is a markdown-step agent-loop, NOT a headless driver script. The agent (you) reads this file and executes the protocol turn by turn, surfacing decisions to the user and waiting for input at each STOP. There is no `_driver.py`; the loop IS the agent following these steps.

**Load at activation.** `sb-bookkeeper.md` (Activation) loads this file before routing to any step. It stays in force across every gastos and investimentos step. Every step's STOP is a Gatekeeper Checkpoint (see § Per-Step Checkpoint).

**Language (binding).** Load `communication` from `{CONFIG_DIR}/standing-rules.yaml` via `lib.standing_rules.load_communication()`. Every user-facing string the loop emits is in `communication.language` (Brazilian Portuguese). Technical terms — function names, paths, column identifiers, tool names — stay in English per `communication.technical_terms`.

**Decision-surface shapes (binding).** Load `batch_ui` from `{CONFIG_DIR}/standing-rules.yaml` via `lib.standing_rules.load_batch_ui()`. When a deviation or issue produces a per-item decision queue (categorias, fornecedores, tags), use `batch_ui`'s field lists and option sets to shape the prompts: one row = one decision (`batch_ui.tags.one_row_one_decision`), never aggregate suppliers (`batch_ui.sub_items.aggregate_suppliers: false`).

## Tools-only data access (architectural invariant)

The loop NEVER reads a ledger CSV, `portfolio.json`, or a raw source file directly to inspect transaction or position data. It reads that data ONLY through a registered tool in `../../scripts/tools-index.md` (e.g. `sample_from_ledger`, `query_corrections`, `query_name_map`, `position_summary`, `position_table`). To find a tool, scan `tools-index.md` for `class: read` and the matching `use`. Manifests (`months.json`, `snapshots.json`) and config files (`suppliers.json`, `tags.json`, `categories.json`, `standing-rules.yaml`) are agent-readable directly — they are not transaction data. If the data the loop needs has no tool, that is itself a deviation: run Rule B (the missing capability routes to `tool-builder`).

---

## Rule A — Refusal-on-out-of-structure

**Fires when:** the user asks for, or the data presents, something the documented structure does not cover. Examples: a request to process a bank/broker source with no parser; a supplier, category, or tag that does not exist; a transaction that fits no category; a rate shape the classifier cannot resolve; a request to write data through a path that is not a registered tool; any instruction that would skip a step, edit a frozen/historical row, or produce output the structure does not define.

**The agent NEVER silently executes an out-of-structure request and NEVER improvises a one-off answer.** It STOPS and surfaces the request to the user with named options.

### Procedure

1. **Name the deviation** in one plain-language sentence (pt-BR): what was asked/found, and which part of the structure it does not fit.
2. **Present exactly these three named options** (pt-BR), each with its one-line consequence:

   ```
   Isto está fora da estrutura atual: {descrição do desvio}.

   Como proceder?
     [A] Tratar pelo protocolo de desvio — construímos a estrutura que falta
         (nova entrada de config / mapeamento / parser / tool) e a partir daí
         isto resolve sozinho. (vai para o protocolo de desvio-para-estrutura)
     [B] Ignorar este item neste fechamento — não processamos, registramos a
         pendência e seguimos. (nada é construído; o item fica de fora)
     [C] Estender a estrutura antes de continuar — você decide a regra/estrutura
         agora; eu a registro e só então retomo o fechamento.
   ```

3. **STOP. Wait for the user's choice.** Do not proceed on any branch without it.
4. **Route:**
   - `[A]` → run **Rule B (deviation-to-structure protocol)** for this deviation.
   - `[B]` → record the dropped item (one line in the close's pending list) and resume the current step. Nothing is built; the item is not processed.
   - `[C]` → ask the user for the rule/structure, record it into the matching config/structure surface (via Rule B's build path if it needs a tool/doc change), then resume the current step.

**Refusal is not a dead end.** Every refusal offers a path back into structure (A or C). The default outcome of a refusal is durable structure, not a one-off workaround.

### Rule A.1 — Structural non-overlap (ME) gate on store/config/dashboard-script edits

**Fires when:** the deviation in Rule A would create or modify a **data store, a config schema, or a dashboard-consumed script** — a new ledger/CSV, a new config dict or key, a new collection, a new JSON store, a direct backend edit that introduces a place data lives. This is narrower than Rule A's general refusal and ADDS a semantic check before any such edit lands. It fires on ANY such edit, not only `tool-builder` output — direct backend edits, new config dicts, and new collections all pass through it.

**The check is SEMANTIC, not a filesystem existence test.** Before the edit, run the ME gate to ask "does this logical concept already have a canonical store among the 23 p2-7 sources-of-truth domains?":

```
python ../../scripts/shared/me_gate.py --concept "{plain description of the data}" \
    [--target {path}] [--keys {comma,separated,keys}] [--store-name {name}]
```

- **Exit 0 (no overlap)** → the concept is genuinely new; the edit may proceed (then complete it through Rule B's durable-structure path).
- **Exit 1 (overlap)** → the gate REFUSES and the CLI prints the three named options (pt-BR): `[R]` reusar a store existente, `[J]` justificar uma store nova (only if genuinely new — requires registering the new store in `lib/source_of_truth_registry.py` / p2-7 in the same change), `[C]` consolidar na existente. STOP and surface these to the user exactly as Rule A surfaces its options; do not create the overlapping store on any branch without the user's choice.

The reference list is `../../scripts/lib/source_of_truth_registry.py` (the 23 p2-7 domains). A justified-new store (`[J]`) is not resolved until its registry entry exists — this is the same "structure + docs current" quality bar Rule B enforces. The gate composes the optional cross-config duplicate auditor (`audit-data-duplication.py`, deferred — plan p5-12) as a tertiary confirmation when present; until it ships the gate runs on the primary registry check alone and NEVER blocks on the missing net.

---

## Rule B — Deviation-to-structure protocol

**Fires when:** Rule A option `[A]` is chosen, or any approved deviation needs new durable structure. Goal: the same input resolves deterministically on the next run, with no re-deviation.

**Quality bar (binding).** An approved deviation MUST meet the structure's quality bar before it is considered resolved — it is not "done" until the durable structure exists AND its documentation is current. A deviation resolved by improvisation, or by a structure change without a matching doc update, is incomplete.

### Procedure

1. **Classify the deviation** into the durable surface it belongs to:

   | Deviation | Durable surface | Build path |
   |-----------|-----------------|------------|
   | Missing capability — no tool can read/produce the needed data, or a needed mutation has no `write` tool | a registered tool in `../../scripts/tools-index.md` | **dispatch `tool-builder`** (see Seam 1) |
   | Unrecognized source — no parser for a bank/broker/exchange file | a `write`/`parser` tool + a source-manifest entry | **dispatch `tool-builder`** (see Seam 1) |
   | New supplier / category / tag / movable resolution | `suppliers.json` / `categories.json` / `tags.json` entry | the gastos two-pass review queue — follow `gastos/step-05-review.md` (its Pass-1 batches ARE this protocol's expression for these surfaces) |
   | Misclassified row that must not change in place | an append-only correction row keyed by `tx_date \| tx_description \| tx_amount` | append to the matching `config/corrections/*.csv` (the `query_corrections` tool reads them back); NEVER edit the historical ledger row |
   | Unresolvable rate shape | a `portfolio.json` rate-metadata structure / classifier rule | **dispatch `tool-builder`** if a code path is needed; otherwise record the rule and update the doc |

2. **Prioritize building structure over a one-off fix.** If the deviation needs a new or changed tool, dispatch `tool-builder` (Seam 1) — do not hand-edit a ledger or `portfolio.json` to work around the gap.
3. **Update documentation in the same resolution.** When the durable structure changes (a new tool, a renamed tag, a new config contract, a new parser), dispatch `doc-maintainer` (Seam 2) so `sb-bookkeeper.md`, the step files, and `tools-index.md` do not drift. The deviation is not resolved until docs are current.
4. **Confirm to the user (pt-BR)** what durable structure was built/changed and that the same input now resolves on the next run. Then resume the current step.

### Seam 1 — `tool-builder` dispatch

> Wired here as a SEAM. The `tool-builder` companion is built at `p5-4` (`../tool-builder/`). This dispatch point exists now; until `p5-4` lands, taking this branch surfaces to the user that the companion is not yet available (pt-BR: "preciso construir/ajustar uma tool para isto, mas o `tool-builder` ainda não está disponível — registro a pendência").

When a deviation needs a new or changed tool, dispatch the `tool-builder` sub-agent (`../tool-builder/`). Authority boundary (binding): `tool-builder` output is **tools only** — it NEVER writes ledgers, `portfolio.json`, or the dashboard directly. A generated tool conforms to the destination artifact's existing schema by default; a genuine schema gap is dual-surfaced (a user-facing prompt AND a `schema_gap_finding` audit event), never silently flattened. The new tool MUST be appended to `tools-index.md` as part of its definition-of-done. After the tool exists, route the original data access back through it (tools-only invariant).

### Seam 2 — `doc-maintainer` dispatch

> Wired here as a SEAM. The `doc-maintainer` companion is built at `p5-5` (`../doc-maintainer/`). This dispatch point exists now; until `p5-5` lands, taking this branch surfaces to the user that the companion is not yet available (pt-BR: "a estrutura mudou e a documentação precisa ser atualizada, mas o `doc-maintainer` ainda não está disponível — registro a pendência").

When durable structure changes, dispatch the `doc-maintainer` sub-agent (`../doc-maintainer/`) to bring `sb-bookkeeper.md`, the affected step files, and `tools-index.md` current with the change. This is the doc-currency arm of the quality bar in step 3 above.

---

## Rule C — Hybrid issue-surfacing

**Fires when:** the loop detects a problem with the close itself (not an out-of-structure request) — a failing validation gate, a reconciliation mismatch, a suspicious delta, a duplicate, an anomaly surfaced by an audit-diagnostic tool, a parser sanity failure.

Every issue is classified as **blocking** or **deferrable**, and surfaced by the matching path. The loop NEVER silently passes a detected issue.

### Classify the issue

| Class | Definition | Path |
|-------|------------|------|
| **Blocking** | The issue makes the current step's output untrustworthy if it proceeds: a failed `validation-gate` tool (non-zero exit), a reconciliation/count mismatch, an unflagged portfolio anomaly, a fuzzy-match dedup, a row that would be silently wrong. Silent-wrong is the worst outcome — these halt. | **Inline** (below) |
| **Deferrable** | The issue is worth recording but does not make THIS step's output wrong — a cosmetic flag, a low-materiality observation, a revision better handled in a scoped review pass, a non-blocking quality flag (`seed_only`, `short_window`). | **Review-mode** (below) |

When in doubt, classify as **blocking** — surfacing too much beats shipping a silent error.

### Blocking → inline (propose a fix + approve/reject)

1. **State the issue** in plain language (pt-BR): what is wrong and why it blocks.
2. **Propose a concrete fix** (pt-BR): the specific action that resolves it (re-run a tool, append a correction row, flag an anomaly as acknowledged, route to Rule B for a structural fix).
3. **Offer approve/reject:**

   ```
   Problema (bloqueante): {descrição}.
   Correção proposta: {ação concreta}.

     [S] Aprovar a correção — aplico e sigo.
     [N] Rejeitar — você indica outra ação ou paramos aqui.
   ```

4. **STOP. Wait.** `[S]` → apply the proposed fix (routing through Rule B if it needs structure), then re-check the gate before proceeding. `[N]` → take the user's alternative or halt the close. The step does NOT advance while a blocking issue is unresolved.

### Deferrable → review-mode

> Review-mode UX lives at `../review-mode.md` (per-month, per-revision-type scoping). The loop ROUTES deferrable issues to review-mode; review-mode owns how they are presented and resolved.

1. **Record the issue** to the close's deferrable list (one line each: what, where, why deferred).
2. **Do not block the current step.** Continue the close.
3. **At close end, surface the deferrable list to the user (pt-BR)** and route it to review-mode for scoped handling:

   ```
   {N} itens foram adiados para revisão:
   {lista de itens, um por linha, com motivo}

   Rodar o modo de revisão agora ou depois?
     [S] Agora — entrar em review-mode para {MONTH}, tipo: Itens adiados
     [D] Depois — encerrar o fechamento; revisar em outra sessão
   ```

   `[S]` → proceed to `../review-mode.md` with `{MONTH}` already set and `REVISION_TYPES = [5]` (deferrable items) and the deferrable list passed as the initial queue.
   `[D]` → close the workflow. The deferrable list is recorded; user runs `bookkeeper [4] Revisão` in a future session.

---

## Per-Step Checkpoint

Each gastos and investimentos step ends with a STOP. That STOP is a Gatekeeper Checkpoint. Before advancing past any step's STOP, run this checklist:

1. **Out-of-structure?** Did the step encounter an input/request the structure does not cover? → **Rule A**.
2. **New/changed store, config, or dashboard-script?** Did the step create or modify a data store, a config schema/dict/key, or a dashboard-consumed script? → run **Rule A.1** (the ME gate) BEFORE the edit lands. Overlap → refuse with reuse/justify-new/consolidate.
3. **Issue detected?** Did a gate fail, a count mismatch, or an anomaly surface? → **Rule C** (classify blocking vs deferrable).
4. **Data read directly?** Did any inspection of transaction/position data bypass a registered tool? → that is a violation; re-route through a `tools-index.md` tool (and run Rule B if no tool exists).
5. **All clear** → advance to the step's `nextStepFile`.

The checkpoint is the loop's heartbeat: every step boundary re-checks the three rules. A step never advances with an unresolved blocking issue or a silently-executed out-of-structure action.

## Audit-event behavior

Structural changes the loop drives (a correction row appended, a tool registered, a config edit, a competência override) ride the workflow's existing audit-event protocol: one event per `(source_file, destination_file_path)` per run, fail-soft (a failed audit write NEVER raises into the loop and never aborts the close), appended to `.user/finance/bookkeeper/audit/events-{YYYY}.jsonl`. The loop does not invent a second audit mechanism — it reuses the pipeline's. Schema gaps surfaced by `tool-builder` emit `schema_gap_finding`; gate failures emit `gate_fail`. The ME gate (Rule A.1) emits a `gate_pass`/`gate_fail` event (`gate.name: me_non_overlap`) per evaluated store/config/dashboard-script edit.
