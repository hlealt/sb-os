# Tutor — Visual Library Protocol

Builds and enriches the owner's visual learning library: one Lumen HTML page per taught topic + a knowledge-map `index.html`. The tutor AUTHORS a per-topic markdown page-source; a deterministic builder renders it. NEVER hand-write HTML/CSS/JS — author only the page-source.

## Resolve paths (always first)

1. Read `sb-os.json` at the vault root → `{sb_os_path}` (field `sb_os_path`).
2. Resolve `{library_root}` from the **Learning library destination** context entry (injected like the Session-summary path). If that entry is absent (first library run): ask the owner once — "Where should your visual learning library live? (a folder in your vault, e.g. `2-areas/{area}/learning-library/`)" — then APPEND a `Learning library destination` (write) entry to the profile YAML the bootstrap uses (`{user_context_root}/sb-tutor/step-01-boot.yaml`), per `para/docs/context-injection-schema.md`. If the owner declines, present the page path in chat only and skip the build.
3. Schema (author to this EXACTLY): `{sb_os_path}/wiki/scripts/learning-library/page-source-schema.md`.
4. Builder: `python {sb_os_path}/wiki/scripts/sb-tutor-build-library.py --library-root "{library_root}" [--topic {slug}]`.

## Authoring quality bar — every page (learned from owner feedback)

The builder owns layout/sizing/table-styling/diagram-fit. YOU own content quality. A page that misses these is a defect, not a draft:

**Pitch the page DEPTH to the session's `technicality-level`** (from the front-door calibration — scale in `front-door.md`): `lay` → analogy-led, minimal jargon, shallower `deeper` asides; `applied` → practitioner how-to + concrete examples; `technical` → mechanism, precise terms, tradeoffs, code where it clarifies; `expert` → full formalism, edge cases, primary-source depth. Technicality sets DEPTH; the clarity + glossary rules below (every term defined in plain words) hold at EVERY level, and the injected `pref.learning.profile` still governs visual-first/brisk delivery — independent axes.

1. **Deep, wiki-grounded — never a stub.** Search + read the wiki for the topic BEFORE authoring (Mandatory Wiki Check + targeted reads). Build each `##` section from real substance — definitions, distinctions, decision criteria, tradeoffs, quantified facts — so the page reconstructs the idea, not a table of contents. Supplement with general knowledge only where the wiki is thin, and say so in `sources`. A thin 1–2-section page is a fail.
2. **Visual-heavy — every concept earns a visual.** Lead each section with a diagram/chart/table/callout, not walls of prose. Per topic: ≥1 interactive `graph` (concept map / state machine / pipeline), a `chart` for anything quantitative, a markdown **table** for any comparison or structured set, `> [!note]`/`> [!warn]` callouts for mental models/cautions, ≥1 `deeper` for a dense aside, a `trace` block when comparing several methods/options across the SAME sequence of steps (steps × method-columns, with each cell's bulky code/payload behind its click-to-open modal); a `flow` block for a process/pipeline (connected stages, optional detail-on-click); `tabs` for variants of one thing in a single space (e.g. the same example in 3 languages); `anncode` for teaching code line-by-line (clickable per-line annotations open in the modal); and one `quiz`.
3. **Interactive-light — `desc`s are mandatory.** EVERY node AND edge in a `graph` block carries a `desc` (its click-to-explain text). A graph without descs is half-built.
4. **YAML-safe blocks.** Inside `graph`/`chart`/`quiz` YAML, QUOTE any value containing `:`, `#`, or quote marks (single-quote it; double any inner apostrophe). One unquoted colon breaks the block.
5. **Author markdown only; scale to the topic.** Never write HTML/CSS/JS (the builder renders everything). Use as many sections as the topic needs — the page adapts to density.
6. **Macro visible, micro collapsed.** A section's MAIN substance — its key points, the list/table/limits that ARE the section — stays VISIBLE (sections render expanded). NEVER hide a section's core content inside a single `deeper`. Use `deeper` ONLY for optional micro-detail behind a point (a derivation, an edge case, a tangent). Test: if expanding one collapsed block reveals the section's actual content, you mis-used `deeper` — promote it to visible body.
7. **Plain-language glossary — define every technical term.** Add a `glossary:` entry (a plain, no-jargon, one-sentence definition) for EVERY technical term, acronym, or piece of jargon a non-expert would not know — including terms that appear only inside a `graph`/`deeper` explanation. The builder highlights each and shows its definition as a hover/focus tooltip, in prose AND in the click-to-explain panels. A definition that itself uses jargon is a defect — define it in plain words. Leaving a page's jargon undefined is a fail.
8. **Scannable prose — bullets over walls.** Prefer bulleted/numbered lists and tables over dense paragraphs. When a passage enumerates items, options, a sequence, or tradeoffs (HTTP methods, status codes, build steps, decision criteria), render it as a list or table — never a multi-sentence prose block the reader must parse linearly. Reserve paragraphs for genuine connective reasoning that does not decompose into items. A wall of prose that hides a list is a defect — this applies inside `deeper` blocks too. (Owner feedback, 2026-06-29.)

## CREATE / UPDATE mode

Fires from the tutor's module checkpoint (R6) and session close (R9) — the visual page grows as the lesson proceeds; it does NOT replace the R9 study-note markdown (that still feeds the wiki).

1. Pick a STABLE `{slug}` for the topic (slugified title); reuse it across the whole topic's life.
2. Author/extend `{library_root}/topics/{slug}.md` per the schema:
   - Frontmatter: `title`, `slug`, `date`, `started_level` (= the calibration `level`), optional `terms` (any known/new terms the calibration surfaced — no longer a self-report list), `goal` (the calibration `intent`), `mastery` (0–100 from checkpoint performance), `sources` (wiki pages from the Mandatory Wiki Check — record each as `{subject, page}` with the wiki note's name in `page` so the builder hyperlinks the subject to that note in Obsidian; + any researched links + the training-data substrate), `related` (sibling topics, with `slug` when they already exist in `topics/`), optional `glossary`.
   - Body: `##` sections that MEET THE AUTHORING QUALITY BAR above — wiki-grounded depth, visual-heavy, every `graph` node/edge with a `desc`, YAML-safe blocks.
   - At each later checkpoint, ADD or EXTEND that module's section in the SAME file — append/deepen; never delete earlier sections.
3. Run the builder (`--topic {slug}` for a single topic; no `--topic` to rebuild all). It also regenerates the index map.
4. Tell the owner, by subject: the page is at `{library_root}/pages/{slug}.html` (open it / refresh).

## ENRICH mode — orchestrated pipeline

Fires when the tutor is invoked to deepen part of a library page — the hover-copy prompt `/sb-tutor expand the item [<title>] of the topic [<topic>] (source: <filepath>, section: #<anchor-id>).`, or a plain "enrich the topic <topic>". ENRICH is an ORCHESTRATED run: the tutor is the conductor; a locator script frames the exact block, a research agent gathers grounding, an update agent rewrites the block, then the builder rebuilds. Invoke `rbtv-orchestrating` and follow `rbtv-sub-agents` for each dispatch — name the skill + its workspace-root-absolute path, and give every write path workspace-root-absolute.

1. **Read the demand.** From the copy-prompt take `<title>`, `<topic>`, `<filepath>` (the page-source, relative to `{library_root}`, e.g. `topics/{slug}.md`), and the section `#<anchor-id>` (`s-…`). A plain "enrich the topic <topic>" carries no anchor — resolve `<topic>` to its `topics/{slug}.md` (match a `title`/`slug` under `{library_root}/topics/`; not found → tell the owner it isn't in the library yet, offer CREATE mode, never guess) and choose the section from the owner's words (ask if unclear).
2. **Locate (deterministic).** Frame the exact current block + line range + slug:
   `python {sb_os_path}/wiki/scripts/sb-tutor-locate-item.py --library-root "{library_root}" --source "<filepath>" --item "<anchor-id-or-title>" --json`.
   Non-zero exit → it lists the page's sections; pick the right one or tell the owner the item isn't on the page. Use `matched.block` (current content), `matched.start`/`end` (line range), and `slug`.
3. **Dispatch the RESEARCH agent (gather, do not edit).** One worker; task = gather grounding to deepen `<title>` within `<topic>`. Ground in the wiki — `python {sb_os_path}/wiki/scripts/sb-wiki-search.py search "<query>" --k 8 --json` AND invoke `sb-wiki-query` (`.claude/skills/sb-wiki-query/SKILL.md`) — READ the top pages; supplement with the internet via web search where the wiki is thin. Return STRUCTURED findings ONLY — key facts, distinctions, quantified figures, a candidate visual/table, a plain-language definition of every new jargon term, and the exact sources by subject. It edits NO file. Per `rbtv-sub-agents`, name `sb-wiki-query` + its absolute path imperatively in the dispatch.
4. **Dispatch the UPDATE agent (append-only edit).** One worker; give it the located block, the research findings, the schema (`{sb_os_path}/wiki/scripts/learning-library/page-source-schema.md`), and this file's Authoring quality bar. Task = DEEPEN that ONE section in `{library_root}/<filepath>` (workspace-root-absolute) in place: add the researched substance and a visual where it clarifies (graph `desc`s + YAML-safe blocks), add a plain-language `glossary:` entry for every new technical term, and add the new wiki sources to frontmatter `sources` as `{subject, page}` (`page` = the wiki note's name, so they hyperlink to the wiki note in Obsidian). **Append/deepen ONLY — never delete, summarize away, or shrink existing content; never touch another section; keep `slug` and the section `## heading` text unchanged** (changing the heading changes its anchor-id, breaking saved copy-prompts). It runs NO builder.
5. **Rebuild (deterministic, conductor):**
   `python {sb_os_path}/wiki/scripts/sb-tutor-build-library.py --library-root "{library_root}" --topic {slug}`.
6. **Verify + report.** Confirm the rebuilt `{library_root}/pages/{slug}.html` shows the deepened section with all prior content intact. Tell the owner, by subject, what was deepened and the page path to re-open.

## Rules

- Author page-source markdown ONLY; the builder owns all look/layout/interactivity.
- `{slug}` is identity — never change it after creation (links + index depend on it).
- Refer to sources BY SUBJECT in chat, never by filename (tutor C5).
- The build is deterministic; after it returns, the page + index reflect the current sources.
