# Tutor — Visual Library Protocol

Builds and enriches the owner's visual learning library: one Lumen HTML page per taught topic + a knowledge-map `index.html`. The tutor AUTHORS a per-topic markdown page-source; a deterministic builder renders it. NEVER hand-write HTML/CSS/JS — author only the page-source.

## Resolve paths (always first)

1. Read `sb-os.json` at the vault root → `{sb_os_path}` (field `sb_os_path`).
2. Resolve `{library_root}` from the **Learning library destination** context entry (injected like the Session-summary path). If that entry is absent (first library run): ask the owner once — "Where should your visual learning library live? (a folder in your vault, e.g. `2-areas/{area}/learning-library/`)" — then APPEND a `Learning library destination` (write) entry to the profile YAML the bootstrap uses (`{user_context_root}/sb-tutor/step-01-boot.yaml`), per `para/docs/context-injection-schema.md`. If the owner declines, present the page path in chat only and skip the build.
3. Schema (author to this EXACTLY): `{sb_os_path}/wiki/scripts/learning-library/page-source-schema.md`.
4. Builder: `python {sb_os_path}/wiki/scripts/sb-tutor-build-library.py --library-root "{library_root}" [--topic {slug}]`.

## Authoring quality bar — every page (learned from owner feedback)

The builder owns layout/sizing/table-styling/diagram-fit. YOU own content quality. A page that misses these is a defect, not a draft:

1. **Deep, wiki-grounded — never a stub.** Search + read the wiki for the topic BEFORE authoring (Mandatory Wiki Check + targeted reads). Build each `##` section from real substance — definitions, distinctions, decision criteria, tradeoffs, quantified facts — so the page reconstructs the idea, not a table of contents. Supplement with general knowledge only where the wiki is thin, and say so in `sources`. A thin 1–2-section page is a fail.
2. **Visual-heavy — every concept earns a visual.** Lead each section with a diagram/chart/table/callout, not walls of prose. Per topic: ≥1 interactive `graph` (concept map / state machine / pipeline), a `chart` for anything quantitative, a markdown **table** for any comparison or structured set, `> [!note]`/`> [!warn]` callouts for mental models/cautions, ≥1 `deeper` for a dense aside, and one `quiz`.
3. **Interactive-light — `desc`s are mandatory.** EVERY node AND edge in a `graph` block carries a `desc` (its click-to-explain text). A graph without descs is half-built.
4. **YAML-safe blocks.** Inside `graph`/`chart`/`quiz` YAML, QUOTE any value containing `:`, `#`, or quote marks (single-quote it; double any inner apostrophe). One unquoted colon breaks the block.
5. **Author markdown only; scale to the topic.** Never write HTML/CSS/JS (the builder renders everything). Use as many sections as the topic needs — the page adapts to density.
6. **Macro visible, micro collapsed.** A section's MAIN substance — its key points, the list/table/limits that ARE the section — stays VISIBLE (sections render expanded). NEVER hide a section's core content inside a single `deeper`. Use `deeper` ONLY for optional micro-detail behind a point (a derivation, an edge case, a tangent). Test: if expanding one collapsed block reveals the section's actual content, you mis-used `deeper` — promote it to visible body.

## CREATE / UPDATE mode

Fires from the tutor's module checkpoint (R6) and session close (R9) — the visual page grows as the lesson proceeds; it does NOT replace the R9 study-note markdown (that still feeds the wiki).

1. Pick a STABLE `{slug}` for the topic (slugified title); reuse it across the whole topic's life.
2. Author/extend `{library_root}/topics/{slug}.md` per the schema:
   - Frontmatter: `title`, `slug`, `date`, `started_level` + `terms` (from the R3 diagnosis — the "where you started" probe), `goal` (R3 goal), `mastery` (0–100 from checkpoint performance), `sources` (wiki pages by subject from the Mandatory Wiki Check + any researched links + the training-data substrate), `related` (sibling topics, with `slug` when they already exist in `topics/`), optional `glossary`.
   - Body: `##` sections that MEET THE AUTHORING QUALITY BAR above — wiki-grounded depth, visual-heavy, every `graph` node/edge with a `desc`, YAML-safe blocks.
   - At each later checkpoint, ADD or EXTEND that module's section in the SAME file — append/deepen; never delete earlier sections.
3. Run the builder (`--topic {slug}` for a single topic; no `--topic` to rebuild all). It also regenerates the index map.
4. Tell the owner, by subject: the page is at `{library_root}/pages/{slug}.html` (open it / refresh).

## ENRICH mode

Fires when the tutor is invoked to expand part of a page — e.g. the copy-button prompt `/sb-tutor expand the item [<item>] of the topic [<topic>].`, or "enrich the topic <topic>".

1. Resolve the source: match `<topic>` to a `title`/`slug` in `{library_root}/topics/`. Not found → tell the owner the topic isn't in the library yet; offer to teach it (CREATE mode). Never guess.
2. Locate `<item>` in that page-source — the section heading or block whose text matches.
3. DEEPEN it in place to the Authoring quality bar — add real wiki-grounded substance, and a visual where it clarifies (graph `desc`s + YAML-safe blocks). **Append/deepen ONLY: never delete, summarize away, or shrink existing content** (rbtv "never lose information"). Keep `slug` unchanged.
4. If the enrich hits a wiki gap, run the tutor's normal Wiki Gap Handling (R-c) — log + offer research.
5. Rebuild: builder with `--topic {slug}`.
6. Tell the owner what was deepened and the page path to re-open.

## Rules

- Author page-source markdown ONLY; the builder owns all look/layout/interactivity.
- `{slug}` is identity — never change it after creation (links + index depend on it).
- Refer to sources BY SUBJECT in chat, never by filename (tutor C5).
- The build is deterministic; after it returns, the page + index reflect the current sources.
