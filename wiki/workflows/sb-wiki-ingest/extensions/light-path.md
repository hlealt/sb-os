# Ingest extension — Light path (Step 0.7 gate + reduced flow)

JIT extension loaded by `sb-wiki-ingest.md` ONLY at Step 0.7 when ALL three qualifying criteria are satisfied. When the criteria are not met (or when the `silent` keyword is present), the main flow never reads this file and the FULL 11-step flow runs unchanged. When loaded in interactive mode, this file governs the owner-approval gate, the reduced flow contract, the mandatory skip list, and the escalation triggers. Every write guard, the Stage-1 checkpoint, and stub policy stay intact and are reachable from the reduced flow.

---

## Qualifying criteria (mechanical hard lines)

A source qualifies for the light-path PROPOSAL if and only if ALL of the following are true. These are hard lines — no exceptions, no judgment:

| Criterion | Threshold | How to measure |
|-----------|-----------|----------------|
| **Source kind** | Markdown (`.md`) | Extension of the raw file resolved at Step 1 is `.md`. A PDF source NEVER qualifies. |
| **Word count** | ≤ 300 words (body text) | Strip the opening YAML frontmatter block (the leading `---` through its closing `---` at the start of the file only — NOT inline `---` horizontal rules) and all fenced code blocks (triple-backtick delimited). Count whitespace-delimited tokens in the remaining body text. ≤ 300 → passes. |
| **Structural simplicity** | ≤ 1 internal `##` section heading in the raw body | Count lines beginning with `## ` (two hashes and a space) in the raw body (after frontmatter strip). 0 or 1 such headings → passes. A source with ≥ 2 H2 headings has internal structure that exceeds the qualifying bound. |

**Borderline sources** (just over any threshold) run the FULL flow. Thresholds are hard lines, not suggestions. The agent MUST NOT round down or apply judgment about whether a borderline source is "simple enough."

---

## Step 0.7 — Light-path gate (loaded here)

This step runs ONLY in interactive mode. When the `silent` keyword is present (silent mode), this step is SKIPPED entirely and the full flow runs — the light path is NEVER taken silently (see Silent-mode rule below).

After Step 0.6 (questions layer gate), before Step 1:

1. **Measure** the three qualifying criteria against the raw filename resolved from `<slug>` (the file path is known from the slug resolution at Step 1 — read the raw file NOW to measure, then proceed to Step 1 normally; the Step 1 read is not duplicated if this gate fires). If any criterion fails, this extension has no further effect — proceed to Step 1 and run the FULL flow.

2. **All criteria pass → PROPOSE the light path.** Present the qualifying evidence and wait for the owner to approve or decline:

```
LIGHT PATH PROPOSAL — <source slug>

This source qualifies for a reduced ingest flow:
  Word count: <N> words  (threshold ≤ 300)
  Sections:   <M> H2 headings  (threshold ≤ 1)
  Kind:       Markdown

Light path runs: Steps 1, 1.7, 2, 3, 4 (if applicable), 4.5, 5 (if applicable), 6, 7–8, 9, 10, 11.
Skipped (cannot fire for a qualifying source):
  — Step 1.5  (PDF rename / text-twin extraction — not a PDF source)

Escalation: if any escalation trigger fires during the run, the full flow resumes from that point.

Approve light path?  (y / n — default: n, full flow)
```

3. **Owner approves** (`y`, `yes`, or any affirmative) → set the `light_path_active` flag and proceed to Step 1 under the reduced-flow contract below.
4. **Owner declines** (`n`, `no`, or any non-affirmative, including no response) → clear the flag and run the FULL flow unchanged. The owner's decline is never logged — it is a run-time choice.
5. **Silent mode present** → NEVER read this file; NEVER propose; run the FULL flow (see Silent-mode rule below).

---

## Reduced-flow contract

When `light_path_active` is set (owner approved):

### Steps that run normally

All steps run normally EXCEPT those explicitly listed as skipped below. "Normally" means the full step logic, including every write guard, the Stage-1 checkpoint (Step 10), stub policy, append-only protection, and escalation checks.

| Step | Light-path behavior |
|------|---------------------|
| Step 1 — Read raw file | Runs normally (already read for the gate measurement — no re-read needed). |
| Step 1.7 — Content-duplicate check | Runs UNCONDITIONALLY. This is a write guard — NEVER skipped on the light path. |
| Step 2 — Write source page | Runs normally. |
| Step 3 — Identify entities and concepts | Runs normally — clustering, stub-rule application, and all firm/speculative/semantic tier construction. |
| Step 3·7c — Answer-scan | Runs normally IF the questions layer is ON (Step 0.6). |
| Step 4 — Update existing entity/concept pages | Runs normally IF `existing-pages` is non-empty after Step 3. If empty, list as skipped in the Stage-1 output. |
| Step 4.5 — Stage topic-update proposals | Runs normally — all three tiers surfaced per their normal posture at Step 10. |
| Step 5 — Create stubs | Runs normally IF `stub-candidates` is non-empty after Step 3. If empty, list as skipped in the Stage-1 output. |
| Step 6 — Candidate-topic triggers | Runs UNCONDITIONALLY. Trigger detection is never skipped on the light path. |
| Steps 7–8 — Index transaction | Runs UNCONDITIONALLY. Mandatory bookkeeping — never skipped. |
| Step 9 — Append log entries | Runs UNCONDITIONALLY for any fires. |
| Step 10 — Stage 1 checkpoint | Runs UNCONDITIONALLY. **The Stage-1 checkpoint is never skipped on the light path.** The preview table includes a `(light path — skipped steps listed below)` annotation on the header line and a mandatory skip-list block at the bottom (see format below). |
| Step 11 — Stage 2 reflection | Runs normally (offered to the owner post-commit as usual). |

### Steps that cannot fire for a qualifying source and are SKIPPED

| Step | Why it cannot fire | Skip condition |
|------|-------------------|----------------|
| Step 1.5 — PDF rename / text-twin extraction | The qualifying criterion `Kind: Markdown` proves this source is not a PDF. Step 1.5 fires ONLY for PDF sources. | Always skipped when `light_path_active`. |
| Step 3·7b — Speculative tier | CONDITIONALLY skipped: fire only when `stub-candidates` is non-empty after Step 3. If `stub-candidates = 0` (no new names require stubs), the speculative tier provably cannot produce candidates and is skipped. If `stub-candidates ≥ 1`, this step runs normally. | Skipped ONLY when `stub-candidates = 0` after Step 3. |

**Skip-list rule (fail-loud).** Every skipped step MUST appear in the mandatory skip-list block of the Stage-1 preview (Step 10). An unlisted skip is a defect. If a step is conditionally skipped (e.g., Step 4 because `existing-pages = 0`), it MUST also appear with its reason.

### Stage-1 skip-list block (mandatory)

Append the following block at the bottom of the INGEST PREVIEW (Step 10), ALWAYS when `light_path_active`:

```
LIGHT PATH — skipped steps:
  Step 1.5   PDF rename / text-twin extraction — not a PDF source
  [Step 3·7b  Speculative tier — 0 stub candidates]  (include only if stub-candidates = 0)
  [Step 4     Existing page updates — 0 existing pages]  (include only if existing-pages = 0)
  [Step 5     Stub creation — 0 stub candidates]  (include only if stub-candidates = 0)
```

Brackets indicate conditional inclusion. Step 1.5 ALWAYS appears. All other skips are reported dynamically based on the actual working sets produced at Step 3.

---

## Escalation triggers (spec row 6)

**Rule:** If ANY escalation trigger fires during a light-path run, the run escalates to the FULL flow from that point — it NEVER silently ignores the trigger. The owner is notified at the point of escalation.

Escalation message format (surface inline when the trigger fires):

```
⚠ LIGHT PATH ESCALATING — <trigger description>
Resuming full flow from Step <N>.
```

| Trigger | Fires when | Resume at |
|---------|-----------|-----------|
| Near-duplicate found | Step 3·5c: the near-dup probe identifies a same-referent existing page for any new candidate | Step 3 (continue processing, full flow) |
| Candidate-topic trigger | Step 6: any trigger fires (contradiction, evolution, or cross-application) | Step 6 (complete trigger capture, then full flow for remaining steps) |
| Stub count exceeds bound | Step 3: `stub-candidates ≥ 3` after clustering | Step 3 (continue Step 3–5 in full-flow mode, then continue) |
| Firm topic-update density | Step 3: `candidate-topic-updates ≥ 3` firm entries after clause 7 | Step 4.5 (all tiers staged normally, full-flow posture) |

When escalation fires, the `light_path_active` flag is cleared. All remaining steps run exactly as the full flow specifies. The Stage-1 preview header reflects the escalation:

```
INGEST PREVIEW — <source slug>   [light path — ESCALATED to full flow: <trigger>]
```

---

## Silent-mode rule

**The light path is NEVER taken in silent mode.** When the `silent` keyword is present at invocation, this extension MUST NOT be read. The full 11-step flow runs. The gate in the main workflow body (`Step 0.7`) checks for the `silent` keyword before reading this file — if `silent` is present, the gate does NOT load this extension and runs the full flow as if the gate were absent. In `ingest-all` dispatches, each subagent runs the full flow — the light path's owner-approval gate requires an interactive session.

Exception (RESERVED — not active today): a dispatch that explicitly carries the `light_path` keyword AND provides the `light_path_approval: yes` flag (a pre-granted approval from an operator-level invocation) may run the light path non-interactively — the proposal is skipped and the gate auto-approves, but every other light-path rule (skip list, escalation, KEEP audit) applies. **No current workflow, YAML file, user-context file, or dispatch sets this flag.** An agent MUST NOT self-issue this flag — it is only valid when set by an explicit operator-level dispatch that names it. This exception is reserved for future tooling; absent the explicit flag, silent mode ALWAYS runs the full flow. The reserved flag's inclusion here (keep vs. remove) is an owner YAGNI call; it is never inferred from source content or criteria alone.

---

## KEEP audit (preserved protections)

The following protections are UNCHANGED by the light path — they apply identically in the full flow and in the light-path reduced flow:

| Protection | Source | Light-path status |
|------------|--------|------------------|
| Write-surface contract A7 (no thesis writes) | `sb-wiki-ingest.md` § Write-Surface Contract | UNCHANGED — never writes thesis pages |
| Write-surface contract D24 (two-tier T4 write rule) | `sb-wiki-ingest.md` § Write-Surface Contract | UNCHANGED |
| Write-surface contract A10 (file and image routing) | `sb-wiki-ingest.md` § Write-Surface Contract | UNCHANGED |
| Content-duplicate check (Step 1.7) | Runs unconditionally | UNCHANGED |
| Stage-1 checkpoint (Step 10) | Runs unconditionally | UNCHANGED |
| Stub policy (append-only protection) | `../../shared/stub-policy.md` | UNCHANGED — Step 4 and Step 5 follow the full stub policy when they run |
| `../../shared/stub-policy.md` § Near-duplicate probe (Step 3·5c) | Runs per Step 3 (escalation trigger fires if a same-referent is found) | UNCHANGED — escalation ensures the light path never silently creates a duplicate stub |
| Candidate-topic trigger detection (Step 6) | Runs unconditionally | UNCHANGED |
| Mandatory bookkeeping — raw index + wiki sources index (Steps 7–8) | Runs unconditionally via the transaction script | UNCHANGED |
| Idempotency — a light-run source is re-ingestable later by the full flow without conflict | The transaction script's idempotency guarantee applies | UNCHANGED |
