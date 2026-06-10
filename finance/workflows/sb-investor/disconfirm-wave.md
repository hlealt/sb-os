---
stepId: investor-disconfirm-wave
runtime: agent-loop
---

# Disconfirm Wave (Step 7a + B10 skeleton)

The canonical home of the `sb-investor` disconfirm (adversarial discovery) wave and its prompt skeleton.

**Loaded by:** `./research.md` Step 7 flow (runs the wave as part of the Step 3 discovery pass); `./thesis.md` Step 2b (dispatches by reference); `./review.md` Step 3b (dispatches by reference). All three load by dispatch — this file is JIT-loaded into the dispatched sub-agent, not into the calling mode.

**Read `./investor-loop.md` before acting.**

---

## Step 7a — Disconfirm (adversarial discovery wave)

The highest-value discovery primitive: instead of asking "what supports the anchor?", it asks **"what source would OVERTURN the anchor?"** and hunts for it — making the rigor spine (evidence → counter-evidence → invalidation) an ACTIVE search, not a reasoned-from-context afterthought. Step 7a is the **stable, dispatchable home** of this wave: `thesis` (B1) and `review` (B3) reach it by DISPATCHING `research` (the existing `review`→`research` sub-agent precedent), never by re-implementing discovery. Keep its interface below stable — consumers depend on it.

**Where it runs (sequencing).** Although numbered 7a, the Disconfirm wave is a DISCOVERY operation: it fires in the discovery pass **alongside the Step 3 width sweep** in `./research.md`, and its candidates merge into the **`./research.md` § Step 4 Propose** table tagged `disconfirming (evidence-against)` — they are NOT a post-ingest step. Capture/ingest (Steps 5–7) act only on the subset the user approves at `./research.md` § Step 4; a disconfirming candidate the user approves flows through capture-and-ingest exactly like any other approved source. The 7a label marks the wave's identity and dispatch interface, not a runtime position after ingest.

**Interface (DOCUMENTED — keep stable; `thesis`/`review` dispatch against this):**

| Side | Contract |
|------|----------|
| **Input** | The anchor claim / assumption (the Step 2 thesis claim, or — when dispatched by a consumer — the specific assumption or near/untested invalidation criterion the consumer hands in) + the entity(ies) + the `research-policy` scope/exclusions |
| **Output** | **Ranked disconfirming candidates + metadata ONLY**, each carrying a **why-it-would-overturn** note (what about the source, if true, falsifies the anchor) in addition to the standard `| title | url | source | trust class | why it matters | relation to the thesis |` fields. Full source text NEVER returns to the parent. |

**Dispatch.** Prompt ONE sub-agent (native dispatch — NOT the `deep-research` skill) to find the strongest source that would FALSIFY the anchor. The prompt MUST:

1. **Invoke the `rbtv-web-searching` skill before any web work and follow it exactly** (the sub-agent does not inherit this requirement; state it explicitly and imperatively), keeping the wave plugin-agnostic (no hard-wired search plugin).
2. Frame the hunt adversarially: search for the data, analysis, or primary source that, if it exists and holds, breaks the anchor — not for confirmation of it.
3. Obey the **same cost cap as the width sweep** (the cost-cap table in `./research.md` § Step 3): **Haiku model · ≤ 5 fetches · single-pass, never loops**.
4. Carry the **same URL-liveness verification and trust-class rubric requirements as the Step 3 wave prompts** (`./research.md` § Step 3 prompt items 3–4).
5. **Return ONLY ranked disconfirming candidates + metadata + the why-it-would-overturn note.** The **full source text MUST stay inside the sub-agent** (anti-context-rot — the parent context stays clean).

Rank the returned disconfirming candidates by `source-policy` trust class (loaded by the calling mode's Step 1) exactly as `./research.md` § Step 3 does; a candidate that fails the trust bar is surfaced per `./investor-loop.md` § Issue-surfacing — never silently dropped or kept. The wave writes NOTHING and fetches nothing into this mode; it adds no new data-access path. Its candidates feed the `./research.md` § Step 4 Propose checkpoint, where the user approves or rejects them through the unchanged present-and-confirm subset flow — nothing disconfirming is captured before approval, per-run or standing (the Step 4 auto-capture partition applies to disconfirming candidates identically).

### B10 — Canonical Disconfirm-Wave Prompt Skeleton (SINGLE SOURCE — `thesis.md` Step 2b dispatches this)

This is the CANONICAL skeleton. `thesis.md` (Step 2b) DISPATCHES `research` pointing at this skeleton — do NOT duplicate it there.

```
You are a disconfirm-wave sub-agent. Your SOLE job is to find the strongest source(s) that would FALSIFY the anchor claim below. Do NOT search for confirmation.

MANDATORY — invoke the `rbtv-web-searching` skill before any web work and follow it exactly.

--- INPUT CONTRACT ---
Anchor claim: {anchor_claim}
Entity/entities: {entities}
Specific assumption or invalidation criterion (if dispatched by thesis/review): {specific_assumption_or_criterion}
Research-policy scope: {scope}
Research-policy exclusions: {exclusions}
Source-policy trust tiers: {trust_tiers}
--- END INPUT CONTRACT ---

SCOPE: adversarial only — hunt for data, analysis, or primary sources that, if true, break the anchor claim. Respect the research-policy exclusions above; drop any candidate touching an excluded topic.

HARD BOUNDARIES:
- Model: Haiku
- Max fetches: ≤ 5
- Wave shape: single-pass, NEVER loop
- Return ONLY ranked candidates + metadata (full source text MUST stay inside this sub-agent — anti-context-rot)
- Verify every candidate URL is live before returning it (HEAD or page fetch); drop dead / 404 / unresolvable URLs
- Trust-class assignment: when uncertain between two tiers, assign the LOWER trust (higher number) — NEVER inflate

TRUST-TIER SEED RUBRIC (use tiers from INPUT CONTRACT if filled; fall back to this):
1 = primary (filings, regulator / company official)
2 = trusted analysis (named research firm / analyst with a track record)
3 = established press
4 = unverified (blog / UGC / aggregator)
Uncertain → assign LOWER trust (higher tier number).

ORCHESTRATION LESSONS (BINDING):
(a) Worklist / input notes are LEADS, not citation mandates — a lead points to a domain, not a pre-approved source; verify and qualify independently.
(b) Input notes are point-in-time — RE-VERIFY every claim against the live wiki before acting on it; a stale note is not ground truth.

RETURN SHAPE — return ONLY this table, no other text:
| title | url | source | trust class | why it matters | relation to the thesis | why-it-would-overturn |
(Tag each row: disconfirming (evidence-against))

WAVE-FIGURE STATUS (BINDING): any figure cited in the metadata above is UNVERIFIED by default — NEVER citable until a Step 7 ingest confirms it in the captured source. Watch for the correction classes in `./data/correction-classes.md` when assigning trust and why-it-would-overturn.
```
