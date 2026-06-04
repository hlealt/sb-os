---
stepId: investor-portfolio
runtime: agent-loop
---

# Portfolio Mode (B4 — Coherence)

The `/sb-investor` reasoning mode that maps the user's real exposure against his theses — surfacing positions held without a thesis, theses with no matching exposure, and concentration — so belief and portfolio stay coherent. **This mode is read-only and builds NO coherence tool.** It composes the existing registered position read tools, reads theses' `related_positions` frontmatter, and performs the position↔thesis join itself in reasoning (D3 Option A). No `portfolio-view` tool exists, and no thin `thesis-map` / `unmapped` tool is built in v1 (build-on-demand only — see § Build-on-demand trigger).

**Loaded by:** `./investor.md` reads-and-follows this file when `./capability-manifest.md` routes the `portfolio` (B4) intent. The invariants (read-only, tools-only, own-workspace-writes, watchlist), policy read-rules wiring, present-and-confirm pattern, issue-surfacing, Rule A, and the per-step Investor Checkpoint in `./investor-loop.md` are already in force when this file runs — this file does NOT restate them. Read `./investor-loop.md` before acting on any step below.

**Division of labour (read once, then act):**

| Layer | Owns |
|-------|------|
| This mode (the cartographer) | reasoning: read exposure via the registered tools, read theses' `related_positions`, perform the join, derive the three coherence findings, present them |
| Registered read tools (`../../scripts/tools-index.md`, `class: read`) | the ONLY path to position data — they read `portfolio.json` themselves; this mode calls them and NEVER reads the JSON or any ledger directly |
| The user | owns every follow-up action a finding implies (author a thesis, review one, set `watchlist`, record a decision); this mode surfaces, the user decides |

This mode persists NOTHING and writes NO wiki page, ledger, or position store. It is pure read-and-reason.

---

## Step 1 — Policy gate (MANDATORY, FIRST)

Before ANY reasoning, load the policy file(s) `../../CLAUDE.md` § Policy Read-Rules requires — per `./investor-loop.md` § Policy read-rules wiring. Mapping exposure and proposing any watchlist change are such actions: `research-policy.md` is required (scope / priorities / exclusions / watchlist-approval / horizon). NEVER restate the read-rules table — read it.

If `research-policy.md` marks an entity or position in scope's reasoning out-of-scope or excluded, say so for that item and STOP on it, or offer to widen scope via the `policy` thin mode — do NOT reason past an exclusion (`./investor-loop.md` § Policy read-rules wiring; Rule A). This gate runs before Step 2 every time; no coherence reasoning begins before it clears.

## Step 2 — Read exposure (tools-only)

Read position data ONLY through the registered `class: read` tools in `../../scripts/tools-index.md` — NEVER read `portfolio.json`, a ledger CSV, or a snapshot directly (`./investor-loop.md` § Tools-only data access). Scan that index for `class: read` and select by the question each tool answers:

| Need | Tool (invoke per its `tools-index.md` entry) |
|------|----------------------------------------------|
| The full set of active positions (id, bucket, currency, type, value, P&L, IRR) — the left side of the join | `position_table` (optionally narrow with `--bucket` / `--currency` / `--type`) |
| An all-in-one diagnostic for a single position the join flags (metadata, balcão, snapshots, anomalies) | `position_summary PRODUCT_ID` |
| For USD (`rv_eua`) positions, how much BRL P&L is native gain vs FX — informs concentration reasoning | `fx_impact_report` |

Treat each tool's stdout as the authoritative position record for this turn. If the position data the join needs has no read tool, that is out-of-structure → Rule A `[A]` (`./investor-loop.md`): record the missing-read-tool gap and route it to the build; NEVER hand-read the store to compensate and NEVER build a tool at runtime. A tool reporting an anomaly (e.g. `position_summary` exit 1) or data the join cannot reconcile is surfaced per `./investor-loop.md` § Issue-surfacing; a suspected data problem routes to `sb-bookkeeper` (never fixed here).

## Step 3 — Read theses' position mappings

Read the theses' `related_positions` frontmatter — the right side of the join. Theses are markdown the agent reads directly at `{wiki_root}/wiki/theses/{slug}.md` (resolve `{wiki_root}` from `sb-os.json`; NEVER hardcode); they are NOT position data, so no read tool is involved. For each thesis collect:

| Field | Used for |
|-------|----------|
| `related_positions` | the position ids / tickers the thesis claims to map to — the join key against Step 2 |
| `status` / `conviction` | whether a mapped thesis is live (`active` / `developing`) or retired (`rejected` / `archived`) — a position mapped only by a retired thesis counts as effectively unmapped |
| `watchlist` | whether the thesis is already an approved watchlist item (the invariant; never set here without approval) |

`related_positions` links positions by ledger id / ticker (the same identity `position_table` emits), so the two sides join on that key. A thesis with an empty `related_positions` is a thesis-without-exposure candidate (Step 4).

## Step 4 — Perform the join + derive coherence (agent-performed)

Join Step 2 (positions) against Step 3 (theses' `related_positions`) in reasoning — this is the agent-performed join (Option A); NO tool does it. Derive the three coherence findings:

| Finding | Definition | How derived |
|---------|------------|-------------|
| **Positions without theses** | An active position with no live thesis mapping it (no `related_positions` match, or matched only by a `rejected` / `archived` thesis) | positions from Step 2 minus the join hits to live theses; advisor-managed positions are noted as such (advisor-managed ≠ a deliberate user thesis) |
| **Theses without exposure** | A live thesis whose `related_positions` is empty or maps only to positions absent from Step 2 | live theses from Step 3 with no join hit into the active position set |
| **Concentration** | A bucket / currency / single position whose share of portfolio value is large enough to flag — and (for `rv_eua`) how much of that is FX vs native | the value/P&L totals `position_table` emits, plus the FX split from `fx_impact_report` for USD positions |

Match on the ledger id / ticker identity; when a `related_positions` entry does not resolve to any Step-2 position (or the reverse), classify it (stale mapping vs genuinely unmapped) and surface ambiguity per `./investor-loop.md` § Issue-surfacing rather than guessing. A persistent pattern of missing or duplicated matches is the § Build-on-demand trigger.

## Step 5 — Present the coherence map (present-and-confirm)

Run `./investor-loop.md` § Present-and-confirm. State the coherence map and STOP for the user's choice. The map MUST carry:

| Element | Content |
|---------|---------|
| Positions without theses | each flagged position (id, bucket, value share), noting advisor-managed ones; the implied next step is authoring a thesis (`thesis`, B1) — surfaced, never auto-run |
| Theses without exposure | each live thesis with no matching position; the implied next step is a review (`review`, B3) or recording the gap as intentional — surfaced, never auto-run |
| Concentration | the flagged bucket / currency / position shares, with the FX-vs-native split for `rv_eua` |

This map is read-only output: presenting it persists nothing. Any follow-up — authoring, reviewing, recording a decision, or a watchlist change — is the user's to choose. A request to **set `watchlist: true`** on any page that arises here is the watchlist invariant applied: surface it through `./investor-loop.md` § Present-and-confirm and the `policy` thin mode; the agent NEVER auto-sets `watchlist` to clear a coherence gap or satisfy its own reasoning (`./investor-loop.md` § Watchlist invariant).

| User choice | Action |
|-------------|--------|
| `[S]` Aprovar | Acknowledge the map; route any follow-up the user names per § Step 6 |
| `[E]` Editar | Refine the framing / scope the user adjusts (e.g. a different bucket or concentration threshold); re-derive from Steps 2–4 and re-present |
| `[N]` Rejeitar | Drop the map; take the user's alternative path or halt |

## Step 6 — Handoff

After the map is presented, route any implied next step — surface it, never auto-chain without the routing the user confirms (`./capability-manifest.md` § Multi-mode chaining):

| Coherence finding implies | Handoff |
|---------------------------|---------|
| A position without a thesis the user wants reasoned | Suggest `thesis` (B1, read-and-follow `./thesis.md`) to author one and map `related_positions` |
| A thesis whose exposure or staleness needs re-checking | Suggest `review` (B3, read-and-follow `./review.md`) |
| A buy / sell / rebalance the map points to | Suggest `decision` (B5, read-and-follow `./decision.md`) to record the action + rationale |
| An approved watchlist change | Route through the `policy` thin mode (`./investor-loop.md` § B6 Policy thin mode) — applied ONLY on the user's explicit approval |

---

## Build-on-demand trigger

The agent-performed join is v1's coherence engine; no `thesis-map` / `unmapped` read tool ships now. Build that thin tool LATER, and only when one of these holds (D3 · ratified): the in-reasoning join starts **missing or duplicating matches** (the join has outgrown reliable in-context reasoning), OR portfolio checks **run often enough** that re-deriving the join each turn is wasteful. Until then, this mode composes the existing read tools + reasons the join. Building the tool is a build-time decision surfaced to the user — never started at runtime by this loop (`./investor-loop.md` Rule A note: the investor never builds durable structure at runtime).

---

## Boundaries (this mode)

- Read-only on ALL data; position data ONLY through the registered `class: read` tools (`./investor-loop.md` § Tools-only data access). The mode NEVER reads `portfolio.json`, a ledger, or a snapshot directly, and NEVER writes one.
- The position↔thesis join is agent-performed in reasoning (Option A); no tool performs it and none is built at runtime (§ Build-on-demand trigger).
- Theses / entity / source pages are markdown the agent reads directly — they are not position data.
- Persists NOTHING: the coherence map is read-only output. No wiki page, no policy file, no ledger, no `portfolio.json` is written by this mode.
- `watchlist: true` is set ONLY after explicit user approval, routed through the `policy` thin mode — NEVER auto-set to clear a coherence gap (`./investor-loop.md` § Watchlist invariant).
- Never mutates ledgers, `portfolio.json`, or the dashboard. A request to do so, to read position data off a non-tool path, or to set `watchlist` without approval is out-of-structure → Rule A in `./investor-loop.md`. A suspected data problem is recorded and routed to `sb-bookkeeper`, never fixed here.
- Every user-facing turn ends at an Investor Checkpoint (`./investor-loop.md` § Per-Step Checkpoint).
