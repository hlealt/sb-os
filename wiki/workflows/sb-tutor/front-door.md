# Tutor — Front-Door Calibration Pipeline

Replaces the old self-report knowledge probe (former R3). Runs ONCE when a topic arrives — brought directly (Activation) or picked from the no-topic menu — BEFORE the R4 learning plan and any teaching. Four stages run in order; stage 4 emits a compact calibration result the rest of the tutor consumes. NEVER teach before this completes.

Calibration is NOT self-report: the student is NEVER asked to rate their own knowledge term-by-term ("know it / heard of it / no idea"). Depth is INFERRED from the query, CONFIRMED with the student, and tested with ONE real question at the inferred frontier.

## When it fires

| Situation | Run |
|-----------|-----|
| A brought topic, or a picked no-topic-menu candidate | The full pipeline (stages 1–4) |
| A closely related topic within the SAME session, level already clear | Lightweight path — skip stages 1–3; reuse the prior `level` + `technicality-level`; run stage 4 after a one-line goal/scope confirmation only |
| A mid-lesson question or tangent | NOT a new front door — ground it with the Mandatory Wiki Check only (step-01-boot C6); do NOT re-run calibration |

## Stage 1 — TERRAIN (map what exists; never read as depth)

Deterministic and cheap. Maps the knowledge terrain so teaching is grounded and the plan is well-shaped. Terrain is NOT a depth signal — wiki presence ≠ student mastery (the corpus is auto-ingested and possibly only skimmed).

1. **Decompose the query** into 2–5 sub-asks (the implicit questions inside it). Example: "how do knowledge graphs work" → {what a graph stores, nodes vs edges, query/traversal, vs relational, GraphRAG}.
2. **Search the topic AND each sub-ask.** Invoke the wiki-search capability — follow `./capabilities/wiki-search.md` for the exact invocation + I/O contract. Collect every page whose top hit clears the C7 grounding bar (step-01-boot) as a GROUNDING PAGE.
3. **Build the syllabus skeleton from the linked-concept neighborhood.** READ the top grounding pages and harvest their `##` section headings + outgoing wikilinks — the search envelope returns ranked chunks, NOT the link graph, so you must read the pages to get neighbors. Cluster the headings/links + the sub-asks into 4–7 candidate modules ordered foundational → advanced. This is a DRAFT skeleton that seeds the R4 plan, not the final plan.
4. **No wiki / all misses** (Mandatory Wiki Check outcomes A/C): build the skeleton from the topic's training-data structure instead. Never block on an empty wiki.

Carry forward: the grounding pages + the syllabus skeleton. Do NOT infer `level` from terrain.

## Stage 2 — READ (draft a structured read of the query)

From the query ALONE (terrain may inform module shape, but NEVER depth), draft — internally, to surface in stage 3:

- **intent** — the explicit learning goal + success criteria ("by the end you can ___"). What would make this lesson a win.
- **scope** — explicitly in / out: what this topic does and does not cover for this student now.
- **depth hypothesis** — a GUESS at the student's current `level` (beginner | intermediate | advanced) AND the target `technicality-level` (stage 4), each with its supporting evidence from the query. Label every part a hypothesis, not a verdict. Evidence = vocabulary used, specificity of the ask, named tools/constraints, stated role or goal.

## Stage 3 — CONFIRM + PROBE (one discriminating question)

ONE pill (R1/R2 apply: ≤20 lines, one pause). Two moves in the same pill:

1. **Confirm the read.** State intent + scope + the depth hypothesis back in plain language, and invite a correction ("here's what I think you're after — fix me where I'm off").
2. **Probe the frontier.** Ask ONE real, discriminating question pitched at the inferred edge — a question only someone at or above that level answers cleanly. NEVER a self-rating ("do you know X?"). Prefer "what happens if / why / which would you pick" over definition recall.

Branch on the answer (plus any correction to the read):

| Answer | Action |
|--------|--------|
| Clean / correct | `level` confirmed at the hypothesis → stage 4 |
| Wrong / partial | The true edge is LOWER. Lower altitude one notch, locate the real edge (optionally ONE more probe a notch down), then stage 4 |
| Reveals MORE advanced | Raise altitude. Auto-COMPRESS the syllabus skeleton (drop/merge now-trivial modules), then show the trimmed plan for ONE approval before teaching (the student may re-expand), then stage 4 |

Keep it warm — one question, framed as calibration, never a quiz-grilling.

## Stage 4 — CALIBRATE (emit the result the rest of the tutor consumes)

Emit a compact calibration result and hand it to the standard flow:

```
{ level, intent, scope, syllabus, technicality-level }
```

| Field | Meaning | Consumed by |
|-------|---------|-------------|
| `level` | confirmed current depth (beginner / intermediate / advanced) — where teaching STARTS | start point (skip mastered, focus gaps); R12 `started_level` |
| `intent` | explicit goal + success criteria | focus; R9 summary framing |
| `scope` | in / out | what to teach vs defer |
| `syllabus` | the stage-1 skeleton, adjusted by stage 3 | seeds the R4 plan (max 5–7 modules) |
| `technicality-level` | TARGET output depth — scale below | chat register (R13), R12 library HTML, R9 summary, optional wiki-topic depth |

**technicality-level scale** — how DEEP/technical the OUTPUT is pitched. DISTINCT from `level` (where the student STARTS) and from `pref.learning.profile` (which sets HOW to teach, e.g. visual-first/brisk):

| Value | Output is pitched as |
|-------|----------------------|
| `lay` | plain-language, analogy-first, minimal jargon, no formalism |
| `applied` | practitioner depth: how-to, concrete examples, named tools, light mechanism |
| `technical` | mechanism + precise terms, tradeoffs, some formalism / code |
| `expert` | full formalism, edge cases, primary-source depth, assumes fluency |

Derive `technicality-level` from intent + scope + the confirmed level — NOT from level alone (a beginner may want an `expert` deep-dive; an expert may want a `lay` refresher). E.g. "implement X in production" → `technical`/`expert`; "what even is X" → `lay`/`applied`.

Then continue the Standard Flow at the R4 plan (seeded by `syllabus`).

## Edge cases

- No goal volunteered → `intent` defaults to "broad working understanding"; say so and invite the student to narrow.
- Ambiguous frontier (can't pick a probe level) → default the probe to the intermediate edge; the answer relocates it.
- Student declines the probe → proceed on the hypothesis, flagged as unconfirmed; recalibrate at the first module checkpoint (R6).
