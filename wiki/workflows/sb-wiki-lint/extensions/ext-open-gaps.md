# Lint extension — Step 8.5 (Regenerate `open-gaps.md`)

> **Loaded by** `sb-wiki-lint.md` Step 8.5 on EVERY lint run (always-emit — `open-gaps.md` is regenerated wholesale every run, including an empty-state file when nothing is open, and including the topic-home aggregate when the questions layer is OFF). Paths below are relative to THIS file's location (`wiki/workflows/sb-wiki-lint/extensions/`).

### Step 8.5 — Regenerate `open-gaps.md` (cross-wiki open-questions aggregate)

REGENERATE `{wiki_root}/open-gaps.md` wholesale on every lint run — a READ-ONLY aggregate that recovers the single-pane visibility the two-homes model gives up (per `../../../docs/wiki-schema.md` § "Questions layer — questions.md" → "`open-gaps.md` — lint-generated aggregate"). This is a VIEW, not a store: lint OVERWRITES the entire file each run; the user never hand-edits it (edits are overwritten). NEVER append; NEVER preserve prior content. Run AFTER Step 8 so the just-pruned `questions.md` state is reflected (promoted/retired entries are already gone and never surface as open gaps).

Collect the open-question set by invoking the deterministic helper:

```bash
python {sb_os_path}/wiki/scripts/sb-wiki-lint-deterministic.py open-gaps
```

The helper emits the complete `open-gaps` aggregate (topic-home open-questions + `questions.md` open entries) with the defined empty-state semantics. Capture its stdout and write it to `{wiki_root}/open-gaps.md`.

**Empty-state — ALWAYS emit the file (never skip).** When `questions.md` is absent AND no topic page has an unresolved `Open questions` line, the helper still emits both sections with the per-section empty-state line `_No open questions._` — do NOT skip generation and do NOT leave a stale prior file in place. Rationale: a stale `open-gaps.md` left from a previous run (when questions existed) would misreport the current state; an always-present empty file is self-documenting and keeps the view honest. (Documented as a shape.md Decision.)

The emitted file carries this exact shape (frontmatter `type: questions-index` per `../../shared/frontmatter-schemas.md`):

```markdown
---
type: questions-index
last-touched: <today YYYY-MM-DD>
---

# Open gaps

> Lint-generated, READ-ONLY — regenerated in full on every `/sb-wiki-lint` run. Do NOT hand-edit; edits are overwritten. Aggregates every OPEN question across both homes (topic pages + `questions.md`). Resolve a question in its home; it drops off this view on the next lint.

## Topic-home open questions (N)

| Question | Topic |
|----------|-------|
| <verbatim Open questions line text> | [[<topic-slug>.md]] |

## `questions.md` open questions (N)

| Question | Home | Relates |
|----------|------|---------|
| [YYYY-MM-DD] <question text> | [[questions.md]] | [[<page>.md]], … |
```

Row rules:

1. **Topic-home rows** — one row per non-struck `Open questions` line. `Question` = the verbatim line text (strip the leading list marker). `Topic` = a `[[<topic-slug>.md]]` backlink to the home topic page.
2. **`questions.md` rows** — one row per open entry. `Question` = the entry's `[YYYY-MM-DD] <question text>` H2 text verbatim, written as PLAIN table text (not inside a wikilink — the `[YYYY-MM-DD]` brackets and `?` in a question break Obsidian's `#`-heading-anchor syntax, so a heading-anchor link is NOT used). `Home` = a plain `[[questions.md]]` file backlink to the queue. `Relates` = the entry's `relates:` targets as `[[<page>.md]]` links joined by `, ` (write `—` when `relates:` is empty/absent).
3. Section header counts `(N)` reflect the rows in that section. Omit NEITHER section — when a section has zero rows, keep the heading and write the empty-state line `_No open questions._` beneath it.
4. Capture `open-gaps-regenerated` (total open-question rows written, or `empty` when both sections are empty) for the LINT REPORT.

`open-gaps.md` is EXCLUDED from every validation walk (Steps 1–5, 7): it carries `type: questions-index` (a non-page value) and is a root-level sibling outside `wiki/` and `raw/`, so it is never walked for stub/orphan/index checks (per `../../shared/folder-structure.md` "Questions Layer Files" → "`open-gaps.md`" and `../../shared/frontmatter-schemas.md` § "`type: questions` / `type: questions-index`"). Lint GENERATES it here; it never participates as a lint target.
