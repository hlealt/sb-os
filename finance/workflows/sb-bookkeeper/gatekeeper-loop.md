---
stepId: gatekeeper-loop
runtime: agent-loop
---

# Gatekeeper Loop

The runtime protocol that makes `sb-bookkeeper` an active-agency gatekeeper instead of a passive script runner. This file is the single home for the three gatekeeper rules; `sb-bookkeeper.md` § What This Workflow Does describes WHAT they are, this file defines HOW they run.

**Runtime model.** This is a markdown-step agent-loop, NOT a headless driver script. The agent (you) reads this file and executes the protocol turn by turn, surfacing decisions to the user and waiting for input at each STOP. There is no `_driver.py`; the loop IS the agent following these steps.

**Load at activation.** `sb-bookkeeper.md` (Activation) loads this file before routing to any step. It stays in force across every gastos and investimentos step. Every step's STOP is a Gatekeeper Checkpoint (see § Per-Step Checkpoint).

**Language (binding).** Load `communication` from `{CONFIG_DIR}/standing-rules.yaml` via `lib.standing_rules.load_communication()`. Every user-facing string the loop emits is in `communication.language`. Technical terms — function names, paths, column identifiers, tool names — stay in English per `communication.technical_terms`.

**Decision-surface shapes (binding).** Load `batch_ui` from `{CONFIG_DIR}/standing-rules.yaml` via `lib.standing_rules.load_batch_ui()`. When a deviation or issue produces a per-item decision queue (categories, suppliers, tags), use `batch_ui`'s field lists and option sets to shape the prompts: one row = one decision (`batch_ui.tags.one_row_one_decision`), never aggregate suppliers (`batch_ui.sub_items.aggregate_suppliers: false`).

## Tools-only data access (architectural invariant)

The loop NEVER reads a ledger CSV, `portfolio.json`, or a raw source file directly to inspect transaction or position data. It reads that data ONLY through a registered tool in `../../scripts/tools-index.md` (e.g. `sample_from_ledger`, `query_corrections`, `query_name_map`, `position_summary`, `position_table`). To find a tool, scan `tools-index.md` for `class: read` and the matching `use`. Manifests (`months.json`, `snapshots.json`) and config files (`suppliers.json`, `tags.json`, `categories.json`, `standing-rules.yaml`) are agent-readable directly — they are not transaction data. If the data the loop needs has no tool, that is itself a deviation: run Rule B (the missing capability routes to `tool-builder`).

**The invariant applies equally to WRITES.** The loop NEVER mutates a ledger CSV, a fechamento `transactions.csv`, or a corrections file through an ad-hoc script. All mutations MUST go through a registered `write` tool in `tools-index.md` (e.g. `apply_review_resolution` for row-level review resolutions, `rename_tags` for tag retro-rewrites, `rename_canonical` for supplier renames, `ack_tag_review` for tag-coverage acks). If a needed mutation has no registered `write` tool, that is a Rule B deviation: missing write capability routes to `tool-builder`.

---

## Rule A — Refusal-on-out-of-structure

**Fires when:** the user asks for, or the data presents, something the documented structure does not cover. Examples: a request to process a bank/broker source with no parser; a supplier, category, or tag that does not exist; a transaction that fits no category; a rate shape the classifier cannot resolve; a request to write data through a path that is not a registered tool; any instruction that would skip a step, edit a frozen/historical row, or produce output the structure does not define.

**The agent NEVER silently executes an out-of-structure request and NEVER improvises a one-off answer.** It STOPS and surfaces the request to the user with named options.

### Procedure

1. **Name the deviation** in one plain-language sentence: what was asked/found, and which part of the structure it does not fit.
2. **Present exactly these three named options**, each with its one-line consequence:

   ```
   This is outside the current structure: {deviation description}.

   How do you want to proceed?
     [A] Handle via the deviation protocol — we build the missing structure
         (new config entry / mapping / parser / tool) and from then on
         this resolves on its own. (goes to the deviation-to-structure protocol)
     [B] Ignore this item in this close — we don't process it, we log the
         pending item and continue. (nothing is built; the item is left out)
     [C] Extend the structure before continuing — you decide the rule/structure
         now; I log it and only then resume the close.
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
- **Exit 1 (overlap)** → the gate REFUSES and the CLI prints the three named options: `[R]` reuse the existing store, `[J]` justify a new store (only if genuinely new — requires registering the new store in `lib/source_of_truth_registry.py` / p2-7 in the same change), `[C]` consolidate into the existing one. STOP and surface these to the user exactly as Rule A surfaces its options; do not create the overlapping store on any branch without the user's choice.

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
   | Gate review-state — a gate needs "a human reviewed/acknowledged this" as machine-checkable state | an append-only ack side-ledger keyed by `tx_date \| tx_description \| tx_amount`, consulted by the gate | append to `config/corrections/{gate}-acks.csv` (e.g. `tag-review-acks.csv`); build its `write`/`ack` tool via Seam 1 if the gate consults it programmatically; NEVER a tag/field on the data |
   | Unresolvable rate shape | a `portfolio.json` rate-metadata structure / classifier rule | **dispatch `tool-builder`** if a code path is needed; otherwise record the rule and update the doc |

2. **Prioritize building structure over a one-off fix.** If the deviation needs a new or changed tool, dispatch `tool-builder` (Seam 1) — do not hand-edit a ledger or `portfolio.json` to work around the gap.
3. **Update documentation in the same resolution.** When the durable structure changes (a new tool, a renamed tag, a new config contract, a new parser), dispatch `doc-maintainer` (Seam 2) so `sb-bookkeeper.md`, the step files, and `tools-index.md` do not drift. The deviation is not resolved until docs are current.
4. **Confirm to the user** what durable structure was built/changed and that the same input now resolves on the next run. Then resume the current step.

### Seam 1 — `tool-builder` dispatch

> The `tool-builder` companion is BUILT and live at `../tool-builder/` (landed at `p5-4`). Taking this branch dispatches it via the Agent tool. If the dispatch fails, surface the actual error to the user — never report it as "not available".

When a deviation needs a new or changed tool, dispatch the `tool-builder` sub-agent (`../tool-builder/`). Authority boundary (binding): `tool-builder` output is **tools only** — it NEVER writes ledgers, `portfolio.json`, or the dashboard directly. A generated tool conforms to the destination artifact's existing schema by default; a genuine schema gap is dual-surfaced (a user-facing prompt AND a `schema_gap_finding` audit event), never silently flattened. The new tool MUST be appended to `tools-index.md` as part of its definition-of-done. After the tool exists, route the original data access back through it (tools-only invariant).

### Seam 2 — `doc-maintainer` dispatch

> The `doc-maintainer` companion is BUILT and live at `../doc-maintainer/` (landed at `p5-5`). Taking this branch dispatches it via the Agent tool. If the dispatch fails, surface the actual error to the user — never report it as "not available".

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

> If the blocking issue is a validation-gate failure that is STRUCTURAL (the honest data cannot reach the threshold), run **Rule C.1** before proposing any fix — it governs which fixes are admissible (recalibrate or build real structure; never semantic-free data).

1. **State the issue** in plain language: what is wrong and why it blocks.
2. **Propose a concrete fix**: the specific action that resolves it (re-run a tool, append a correction row, flag an anomaly as acknowledged, route to Rule B for a structural fix).
3. **Offer approve/reject:**

   ```
   Problem (blocking): {description}.
   Proposed fix: {concrete action}.

     [S] Approve the fix — I apply it and continue.
     [N] Reject — you indicate another action or we stop here.
   ```

4. **STOP. Wait.** `[S]` → apply the proposed fix (routing through Rule B if it needs structure), then re-check the gate before proceeding. `[N]` → take the user's alternative or halt the close. The step does NOT advance while a blocking issue is unresolved.

### Deferrable → review-mode

> Review-mode UX lives at `../review-mode.md` (per-month, per-revision-type scoping). The loop ROUTES deferrable issues to review-mode; review-mode owns how they are presented and resolved.

1. **Record the issue** to the close's deferrable list (one line each: what, where, why deferred).
2. **Do not block the current step.** Continue the close.
3. **At close end, surface the deferrable list to the user** and route it to review-mode for scoped handling:

   ```
   {N} items were deferred for review:
   {list of items, one per line, with reason}

   Run review mode now or later?
     [S] Now — enter review-mode for {MONTH}, type: Deferred items
     [D] Later — end the close; review in another session
   ```

   `[S]` → proceed to `../review-mode.md` with `{MONTH}` already set and `REVISION_TYPES = [5]` (deferrable items) and the deferrable list passed as the initial queue.
   `[D]` → close the workflow. The deferrable list is recorded; user runs `bookkeeper [4] Review` in a future session.

### Rule C.1 — Gate integrity: measure meaning, not compliance

**Fires when:** a Rule C **blocking** issue is a validation-gate failure that is STRUCTURAL — the honest data idiom cannot reach the threshold (not a one-row error, not a parse fault, but "the real data simply does not make this number"). Applies to EVERY gate the bookkeeper supervises — coverage, IRR sanity, portfolio delta, parser sanity — in both close and review-mode sessions. This NARROWS Rule C's blocking path and ADDS the checks below BEFORE any fix is proposed.

**Cardinal constraint:** the gate's PURPOSE governs, not its current number. A structurally-failing gate is resolved by recalibrating the gate to its real purpose OR by building real structure that earns the threshold — NEVER by injecting semantic-free data whose only function is to flip the metric.

#### Run in order, before proposing any fix

1. **Threshold provenance.** Verify the failing threshold was deliberately DECIDED for THIS metric — not inherited from another gate through a shared config key. Trace it to a recorded decision for this exact metric. No record (inherited or undecided) → recalibration is on the table from the start; say so and offer it as the first option. (Prevents: a row-coverage gate inheriting an "R$ tagged" resolution through one shared key and blocking every month on a number nobody decided for it.)
2. **Semantic-free-data tripwire.** Test the candidate fix: *would the value it adds be true of every surviving row BY CONSTRUCTION?* If yes, it carries zero bits about the row, exists only to move the metric, and is gaming — STOP, do not propose it. (Instance: a `revisado`/reviewed tag on rows that are all reviewed by the time the gate runs encodes nothing.)
3. **Review-state routing.** When the gate genuinely needs "a human reviewed/acknowledged this" as machine-checkable state, store it in an append-only, identity-keyed acknowledgment side-ledger the gate consults — NEVER as a tag/category/field on the data. Key by `tx_date | tx_description | tx_amount`; acked rows print as visible ACK lines, never silent skips. This is a Rule B durable surface (see Rule B's classification table). Precedents in-system: `gate_portfolio_delta --flagged-ids`, `config/corrections/tag-review-acks.csv` (gate_coverage). Build a new ack ledger and its `write` tool via Rule B / Seam 1.

#### Surface to the user (a specialized Rule C approve/reject)

```
Gate failed structurally: {gate} — {metric} = {actual} vs threshold {threshold}.
The honest data idiom cannot reach {threshold}. Provenance: {decided for this metric / inherited from {gate} / no record}.

Resolve it (the gate's purpose governs, not the number):
  [R] Recalibrate the gate — set threshold/scope to what the metric's purpose
      requires; I record the decision as this metric's provenance.
  [B] Build real structure — {the concrete structure that earns the threshold}.
  [K] Keep the gate; this month does not pass — record it, you decide acceptance.
```

NEVER offer a semantic-free-data option. STOP and wait. Route `[B]` through Rule B; record `[R]`'s decision as the threshold's provenance.

#### Anti-patterns

| Thought | Action |
|---------|--------|
| "A `revisado` tag on the reviewed rows reaches 90% — quick fix." | Tripwire 2: every surviving row is reviewed by construction; the tag carries zero bits. Reject; recalibrate or build real structure. |
| "The threshold is 90%, the gate fails, so apply a fix to pass." | Run check 1 first. If 90% was inherited from another gate and never decided for THIS metric, recalibrating the threshold IS the fix — not data. |
| "The gate needs 'human reviewed' — I'll add a `reviewed: true` field to the rows." | Check 3: review-state goes to an append-only ack side-ledger keyed by row identity, consulted by the gate — never a field on the data. |
| "I'll redefine the metric or relabel the gate so today's number passes." | Retargeting the metric to dodge the failure is gaming. Recalibrate the threshold to the purpose or build structure; never redefine the metric to pass today's number. |

---

## Per-Step Checkpoint

Each gastos and investimentos step ends with a STOP. That STOP is a Gatekeeper Checkpoint. Before advancing past any step's STOP, run this checklist:

1. **Out-of-structure?** Did the step encounter an input/request the structure does not cover? → **Rule A**.
2. **New/changed store, config, or dashboard-script?** Did the step create or modify a data store, a config schema/dict/key, or a dashboard-consumed script? → run **Rule A.1** (the ME gate) BEFORE the edit lands. Overlap → refuse with reuse/justify-new/consolidate.
3. **Issue detected?** Did a gate fail, a count mismatch, or an anomaly surface? → **Rule C** (classify blocking vs deferrable; a structurally-failing gate → **Rule C.1** before any fix).
4. **Data read directly?** Did any inspection of transaction/position data bypass a registered tool? → that is a violation; re-route through a `tools-index.md` tool (and run Rule B if no tool exists).
5. **All clear** → advance to the step's `nextStepFile`.

The checkpoint is the loop's heartbeat: every step boundary re-checks the three rules. A step never advances with an unresolved blocking issue or a silently-executed out-of-structure action.

## Audit-event behavior

Structural changes the loop drives (a correction row appended, a tool registered, a config edit, a competência override) ride the workflow's existing audit-event protocol: one event per `(source_file, destination_file_path)` per run, fail-soft (a failed audit write NEVER raises into the loop and never aborts the close), appended to `.user/finance/bookkeeper/audit/events-{YYYY}.jsonl`. The loop does not invent a second audit mechanism — it reuses the pipeline's. Schema gaps surfaced by `tool-builder` emit `schema_gap_finding`; gate failures emit `gate_fail`. The ME gate (Rule A.1) emits a `gate_pass`/`gate_fail` event (`gate.name: me_non_overlap`) per evaluated store/config/dashboard-script edit.
