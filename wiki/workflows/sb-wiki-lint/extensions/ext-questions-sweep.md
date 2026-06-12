# Lint extension — Step 7.7 (Questions answer-sweep + graduation detection)

> **Loaded by** `sb-wiki-lint.md` Step 7.7 ONLY when the questions layer is ON (`{wiki_root}/questions.md` present and parseable). Skip-if-absent: when the layer is OFF the main file never reads this file. Paths below are relative to THIS file's location (`wiki/workflows/sb-wiki-lint/extensions/`).

### Step 7.7 — Questions answer-sweep + graduation detection (skip-if-absent)

Resolve `{wiki_root}/questions.md`. **Absent → questions layer OFF**: hold EMPTY `questions-answer-proposals` and `graduation-proposals` sets; skip this ENTIRE step; the Step 9 `PROPOSED ANSWERS` and `GRADUATION PROPOSAL` blocks are omitted and the run is identical to today (optionality guarantee #1). **Present but malformed** (unreadable, invalid frontmatter, or no parseable H2 entries): WARN and treat as absent — hold EMPTY sets, skip the step; NEVER abort the lint (guarantee #5). **Present and parseable**: parse every H2 entry per `../../shared/question-entry-shapes.md` and proceed. State is INFERRED — an entry is `open` iff it has no `answer:` block or zero `answer:` bullets, else `answered`. Per `../../../docs/wiki-schema.md` § "Questions layer — questions.md" → "The answer-scan" (Lint row).

Detection ONLY — this step NEVER writes. It builds two proposal sets that the user gates at Step 9; apply/invoke happens at Step 9 on explicit accept.

#### 7.7a — Answer-sweep (both homes → `questions-answer-proposals`)

**Dirty-set scoping (spec rule 5):** read `dirty_set` from the helper report. Apply per home:

| Home | Dirty-set gate |
|------|----------------|
| **Topic-home** | Sweep open questions ONLY from topic pages whose wiki-root-relative path is in `dirty_set`. Topic pages absent from `dirty_set` are unchanged — skip their `Open questions` lines. |
| **`questions.md`** | Sweep open entries ONLY when `questions.md` itself is in `dirty_set` (whole-file signal — the helper tracks `questions.md` as a single entry; when it is NOT dirty, no entry was added or edited, and the entire `questions.md`-home sweep is skipped). When `questions.md` IS dirty, sweep all its open entries. |

On `--full` runs and first-run / state-fallback, `dirty_set` contains every tracked page, so both homes are swept in full.

Gather the scoped open-question set by invoking the deterministic helper:

```bash
python {sb_os_path}/wiki/scripts/sb-wiki-lint-deterministic.py sweep-gather
```

The helper emits a JSON object with a `questions` array. Each element carries `home` (`topic` or `questions.md`), `question` (verbatim text), and `source` (wiki-root-relative path). Filter this array with the dirty-set gate above: keep only `topic` items whose `source` is in `dirty_set`, and keep `questions.md` items only when `questions.md` itself is in `dirty_set`. Then sweep each remaining open question against the EXISTING wiki — concept/entity/topic page bodies plus source-page `Substance` sections — for content that answers it. This sweep is OFF the ingest hot-path, so it MAY be MORE THOROUGH than ingest's mechanical match (Step 3·7b/3·7c of `sb-wiki-ingest.md`). **Semantic-primary (D11):** when the semantic tier is available the firing signal is the semantic read — membership (below) plus a lightly-semantic read of a page that materially addresses the question without sharing 2 surface tokens; the shared `token_overlap ≥2` signal is the no-Voyage degrade floor only — it never fires on its own while the tier is up. It remains a PROPOSAL surface — it NEVER auto-applies.

When the semantic tier is available (schema § "Retrieval tiers — hybrid search"), the helper is the PRIMARY firing signal — per open question, from the vault root: `python {sb_os_path}/wiki/scripts/sb-wiki-search.py search "<question text>" --k 5 --json` — and treat each hit page as a candidate answering page (the agent's lightly-semantic read may additionally fire a page that materially addresses the question). Tier unavailable → run the sweep with grep/LLM reads plus the `token_overlap ≥2` degrade floor exactly as before; a helper failure NEVER aborts the lint.

> **Thresholds frozen (§13; owner rulings D11/D12).** The lint-sweep firing signal is semantic-primary: the semantic read (`--k 5` membership + a lightly-semantic read of a page that materially addresses the question without 2 shared surface tokens) is the PRIMARY signal when the tier is available; the shared `token_overlap ≥2` signal (mirrored from `sb-wiki-ingest.md` Step 3·7b/3·7c) is the no-Voyage degrade floor only. The D12 probation that held this window open is RESOLVED: the mechanized token-floor junk-fire defect (p2-8 ESL-2) is fixed by the semantic-primary policy, validated 2026-06-10 (junk answer-scan 33→0, speculative 6→0, degrade still fires, genuine pair ranked #1 — evidence at `1-projects/rbtv-evolution/coding/done-gate-evidence/sb-os/2026-06-10-answer-scan-semantic-primary{.md,/}`). Frozen at these values. The ≥10-run sweep-thoroughness validation window is CLOSED — owner-ratified (run-count close condition met). Per `../../../docs/wiki-schema.md` § "Questions layer — questions.md" → "The answer-scan" validation-window note (heuristic 3, lint sweep thoroughness).

For each fire, capture into `questions-answer-proposals`: the home (`topic` or `questions.md`); the question identity (topic page path + the verbatim `Open questions` line for a topic-home fire; the `questions.md` entry's H2 heading for a `questions.md` fire); the answering page filename; and the proposed `answer:` claim — a 1-sentence claim derived from the answering page that addresses the question, carrying the citation `[^N]: [[<answering-page>.md]]`.

These are surfaced as a USER-GATED `PROPOSED ANSWERS` block at Step 9. Apply happens ONLY on accept, reusing the SAME append-only / inline-`answer:` handling as `sb-wiki-ingest.md` Step 10 (the ingest p3-2 path) — NEVER a parallel write path:

- **`questions.md` row** — accrete the 1-sentence claim onto the entry's `answer:` field per the answer-write procedure in `../../shared/question-entry-shapes.md` (`answer:` field rule + State rule), citing `[[<answering-page>.md]]`.
- **topic-home row** — STRIKE the matched `Open questions` line in place (`~~…~~`, never delete it) and FOLD the answer into the topic body under the topic-shape-appropriate section, with an inline `[^N]` marker and a matching `[^N]: [[<answering-page>.md]]` def in the topic's `Sources`; bump `last-touched: <today>`. Append-only protection applies — NEVER overwrite existing prose.

Rejecting a row leaves the entry/topic untouched; the match is not preserved — it re-detects on a future sweep if overlap recurs.

#### 7.7b — Graduation detection (`questions.md` only → `graduation-proposals`)

Scan every **answered** `questions.md` entry (≥1 `answer:` bullet) for maturity. Topic-home questions never graduate (they resolve in place on the topic page) — graduation is `questions.md`-only. Mark a maturity heuristic for each answered entry; entries that look MATURE feed `graduation-proposals` (the entry H2 + a 1-line answer preview + its `relates:` targets) for the Step 9 GRADUATION PROPOSAL block.

> **Validation window — ON (§13 fuzzy thresholds).** The EXACT graduation maturity heuristic — when an accreted `answer:` is "ripe" for a page (starting point: an entry with ≥2 accreted `answer:` bullets from distinct sources, OR a single bullet the user has marked, surfaces as mature) — is deliberately unfrozen while tuning. **Close condition: freeze the wording here once the `runs_completed` counter in `{wiki_root}/lint-deterministic-report.json` (added by task `p2-gaps`; absent-as-0) reaches ≥10 AND at least one GRADUATION PROPOSAL has been surfaced (i.e., the heuristic has been exercised at real scale).** Graduation proposals are surfaced per-run only and not persisted separately; the run counter is the durable close signal. Per `../../../docs/wiki-schema.md` § "Questions layer — questions.md" → "The answer-scan" validation-window note (heuristic 1, graduation maturity).

Detection ONLY. Build `graduation-proposals` for the Step 9 GRADUATION PROPOSAL block. The graduated entry is NOT pruned here — pruning of a promoted entry (page now exists) is owned by Step 8; this step only PROPOSES.
