# Ingest extension — Questions layer (Steps 0.6 + 3·7c)

JIT extension loaded by `sb-wiki-ingest.md` ONLY when the questions layer is ON (`{wiki_root}/questions.md` present and parseable — probed at the Step 0.6 gate). When OFF, the main flow never reads this file; hold an EMPTY `candidate-answers` set, omit the Step 10 `PROPOSED ANSWERS` block, and behave EXACTLY as today. Execute Step 0.6 here at the Step 0.6 gate; execute Step 3·7c here at the Step 3·7c gate (same points in the main flow as the inline steps were).

### Step 0.6 — Load questions (answer-scan)

Read + parse the OPTIONAL questions-layer registry `{wiki_root}/questions.md`. This loads the open questions that the answer-scan matches the new source against at the Stage-1 `PROPOSED ANSWERS` block (Step 10). The canonical spec is `../../../docs/wiki-schema.md` § "Questions layer — questions.md" — follow it; the entry schema and two-homes contract there are authoritative. The runtime entry shape is `../../shared/question-entry-shapes.md`. This step ONLY loads — it NEVER writes (writes happen at Step 10 commit on user accept).

1. Resolve `{wiki_root}/questions.md`.
2. **Absent** → **questions layer OFF**: hold an EMPTY question set; skip ALL questions behavior for this run; the Step 10 `PROPOSED ANSWERS` block is omitted and every other step behaves EXACTLY as it does today (optionality guarantee #1). Proceed to Step 1.
3. **Malformed** (unreadable, invalid frontmatter, or no parseable H2 entries) → WARN and proceed as if absent (empty question set, layer OFF). NEVER abort the ingest (guarantee #5). Proceed to Step 1.
4. **Present and parseable** → parse every H2 entry per the entry schema and hold the **open** ones for the Step 10 scan. State is INFERRED — an entry is `open` iff it has no `answer:` block or zero `answer:` bullets; `answered` entries (≥1 `answer:` bullet) are skipped by the scan. For each open entry hold: the question text, its `relates:` wikilinks, and its `seeded-by:` wikilink (if any). Holding open questions does not gate any Step 1–9 logic — it feeds ONLY the Step 10 block.

### Step 3·7c — Answer-scan (match new source against open questions, BOTH homes)

SKIP this step entirely if the questions layer is OFF (Step 0.6: `questions.md` absent or malformed). When OFF, hold an EMPTY `candidate-answers` set — the Step 10 `PROPOSED ANSWERS` block is omitted and the run is identical to today.

Match THIS source against every **open** question in **BOTH** homes, using the SAME signals as the speculative-topic-update tier (Step 3·7b) — do NOT invent a new one:

| Home | Open-question source |
|------|----------------------|
| **Topic-home** | Each un-struck `Open questions` bullet line on topic pages. Source them WITHOUT walking every topic page: grep `{wiki_root}/wiki/topics/` for the `## Open questions` heading with trailing context lines; extract the bullet lines under each matched heading (stop at the next heading; skip `~~struck~~` lines). Read a topic page itself only when one of its lines fires. |
| **`questions.md`** | Each open entry held from Step 0.6 (no `answer:` block or zero `answer:` bullets). |

For EACH open question (either home) fire a candidate answer per the semantic-primary rule (D11) — semantic membership decides when the tier is available; token overlap is the degrade path only:

| Condition | Detection |
|-----------|-----------|
| Semantic membership (PRIMARY — the decider when the tier is available) | When the semantic tier is available: query the helper with the open question text — `search "<question text>" --k 5` (`--no-sync` after the run's first call) — and fire when THIS ingest's source page (written at step 2, synced into the index by the run's first helper call) appears among the results. While the tier is up this is the SOLE firing signal — token overlap is suppressed entirely. |
| Token overlap (DEGRADE path — fires ONLY when the semantic tier is down) | When the semantic tier is unavailable: the question text shares ≥2 substantive tokens with this source's `Substance` section text (use the topic-home question's `Open questions` line text, or the `questions.md` entry's H2 question text). **Tokenize via `token_overlap(question_text, substance_text)` in `sb-wiki-lint-deterministic.py`** — Step 3·7b is the EXACT-rule authority. Threshold: ≥2 distinct substantive tokens shared. When the tier is UP this never fires on its own. |

For each fire, capture into `candidate-answers`: the home (`topic` or `questions.md`); the question identity (topic page path + the verbatim `Open questions` line for a topic-home fire; the `questions.md` entry's H2 heading for a `questions.md` fire); the firing signal (`semantic (top-5)`, or matched tokens on the degrade path); and the proposed `answer:` claim — a 1-sentence claim derived from this source's `Substance` that addresses the question, carrying the source citation `[^N]: [[<raw-filename>]]`.

**Topic-home routing — reuse the existing append-only path (NO parallel path).** For each topic-home fire, stage the corresponding topic update through `candidate-topic-updates` (the firm tier consumed at Step 4.5): the proposed change is the answer claim folded into the topic body under the topic-shape-appropriate section per the Step 4.5 Update-behavior routing, PLUS a strike of the matched `Open questions` line. The topic-home fire is surfaced to the user ONLY in the `PROPOSED ANSWERS` block (Step 10) — SUPPRESS its row from the firm `TOPIC UPDATES` block so the same resolution is never presented twice. Accepting the `PROPOSED ANSWERS` row applies the staged topic-update through the Step 4.5 machinery (append-only protection applies); rejecting it discards the staged update. Do NOT create a second write path for topic pages.

This step prepares but does NOT write. Apply happens at Step 10 commit, only for accepted rows.

> **Thresholds frozen (§13; owner rulings D11/D12).** The firing signal is semantic-primary: a candidate fires on semantic membership (`search "<question text>" --k 5` returns this ingest's source page) when Voyage is available; `token_overlap ≥2` (mirrored from Step 3·7b) is the no-Voyage degrade only — it never fires on its own while the tier is up. Validated on post-D11 evidence (2026-06-10): re-running the ESL-2 inputs with live Voyage produced 0 junk answer-fires (was 33 token-fires) while the source ranked #1 on the genuine question it answers, and the degrade path still fired (39). The earlier 10-fires/13-runs freeze was an LLM-as-tokenizer-era result and is superseded. The `--k 5` cutoff and the semantic-primary policy are frozen at these values.
