# Finance Data Access

Tools-only access protocol for finance data. Binds EVERY agent session that touches data under `.user/finance/bookkeeper/` — ledgers, fechamento months, corrections side-ledgers, `portfolio.json` and its snapshots — whether or not a finance workflow is loaded. The canonical runtime protocol is `{sb_os_path}/finance/workflows/sb-bookkeeper/gatekeeper-loop.md` § Tools-only data access; this rule carries its binding statements into sessions that never load that workflow.

## Trigger and Scope

**Activates when:** any task reads or mutates a file under `.user/finance/bookkeeper/`.

**Does NOT govern:** manifests (`months.json`, `snapshots.json`) and config files (`suppliers.json`, `categories.json`, `tags.json`, `standing-rules.yaml`) — agent-readable directly; files outside `.user/finance/bookkeeper/`; the finance module's own scripts and docs.

**Sub-agent dispatches:** rules do not inherit into Agent-tool sub-agents. A dispatch whose task may touch `.user/finance/bookkeeper/` data MUST name this rule in the sub-agent prompt and instruct: "read/mutate finance data ONLY through registered tools in `{sb_os_path}/finance/scripts/tools-index.md`".

## Reads — sequencing gate

Transaction/position data is read ONLY through a registered `class: read` tool in `{sb_os_path}/finance/scripts/tools-index.md` (e.g. `sample_from_ledger`, `query_corrections`, `query_name_map`, `position_summary`, `position_table`). Scan the registry for the matching `use`. NEVER open a ledger CSV, `portfolio.json`, or a raw source file directly to inspect transaction or position data.

## Writes — sequencing gate

Ledgers, fechamento CSVs, corrections side-ledgers, and `portfolio.json` are mutated ONLY through a registered `class: write` tool — dry-run preview first, `--apply` only after the user confirms the preview. Writing a one-off script for a finance mutation is a violation — including "I'll delete it after".

| Invariant | Rule |
|-----------|------|
| Corrections | Append-only. NEVER edit a historical ledger row in place. |
| `data_caixa` | Never changes. |
| Frozen/closed months | Revisions go through the corrections protocol (`apply_review_resolution`) — never in-place edits. |

## Missing Capability = Deviation

| Gap | Route |
|-----|-------|
| No registered tool covers the needed read or mutation | Invoke the `sb-tool-builder` skill to build + register the tool, then route the operation through it. Inside a workflow that defines its own dispatch seam (sb-bookkeeper gatekeeper-loop Seam 1), follow the seam instead. |
| Durable structure changed and finance docs are stale | Invoke the `sb-doc-maintainer` skill (Seam 2 inside sb-bookkeeper). |
| A new data store, collection, or config key is about to be created | Run the ME gate FIRST: `python {sb_os_path}/finance/scripts/shared/me_gate.py --concept "..."`. Overlap (exit 1) → STOP and surface the gate's reuse / justify-new / consolidate options to the user. |

## Required Output

Before each finance data operation, name in chat the registered tool you are routing through — e.g. `routing through sample_from_ledger`. An operation with no named registered tool is a violation; the naming is what makes compliance visible.

## Anti-Patterns

| Type | Thought | Action |
|------|---------|--------|
| Skip | "It's a small edit — a quick script is faster" | Small edits are how this protocol died on 2026-06-06 (4 ad-hoc mutation scripts in one session). Route through a `write` tool; no tool → `sb-tool-builder`. |
| Skip | "review-mode says apply via the lib functions" | Lib functions are tool internals, not entry points. The entry point is a registered tool, dry-run first. |
| Skip | "Building a tool is overkill for 3 rows" | 3 rows through `apply_review_resolution` cost less than one improvised script — and the capability persists. |
| Skip | "I just need to peek at one CSV value" | Peeks are reads. `sample_from_ledger` exists for exactly this. |
| Game | "I'll delete the script after" | Deleting the script destroys the evidence of a capability gap. The gap routes to `sb-tool-builder`. |
| Game | "I wrote a script and I'm calling it a tool" | A tool is registered in `tools-index.md` with all ten fields and a test. Unregistered = ad-hoc script = violation. |
| Game | "Dry-run is a formality — straight to `--apply`" | `--apply` without a user-confirmed dry-run preview is a violation, even through a registered tool. |
| Game | "My sub-agent will just explore, it won't touch data" | Exploration reads ARE reads, and sub-agents never see this rule. Name it in the dispatch prompt (observed leak: 2026-06-06, Explore sub-agents read 5 ledgers directly). |
