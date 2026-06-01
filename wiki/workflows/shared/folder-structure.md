# Wiki Folder Structure

Directory layout for `{wiki_root}/`. All paths are relative to `{wiki_root}`. Resolve `{wiki_root}` from `sb-os.json` at runtime — never hardcode.

## Tree

```
{wiki_root}/
├── purpose.md                          OPTIONAL regulatory file — ingest focus lens (not a page; lint skips it)
├── log.md                              actionable queue (candidate-topic + candidate-mention)
├── raw/
│   ├── assets/                         local images / attachments (flat, shared) — user-maintained via Obsidian's "Download attachments for current file"
│   ├── {origin}/                       articles, podcasts, papers — by source origin
│   │   ├── {origin}.md                 raw leaf index (File, Title, Date, Wiki columns)
│   │   └── {date}-{slug}.md            verbatim source file (immutable)
│   └── studies/                        study sessions: /tutor outputs + multi-source notes
│       ├── studies.md                  raw leaf index
│       └── {date}-{slug}.md            raw study session content (immutable)
└── wiki/
    ├── concepts/
    │   ├── concepts.md                 leaf index (or router post-subdivision)
    │   ├── CLAUDE.md                   managed routing rules (only after first subdivision)
    │   ├── {kind-subfolder}/           per-kind subfolder (lazy, lint-proposed at ≥10 pages)
    │   │   ├── {kind-subfolder}.md     subfolder leaf index
    │   │   └── {slug}.md               concept pages of this kind
    │   └── {slug}.md                   flat pages (kinds below subdivision threshold)
    ├── entities/
    │   ├── entities.md                 leaf index (or router post-subdivision)
    │   ├── CLAUDE.md                   managed routing rules (only after first subdivision)
    │   ├── {kind-subfolder}/           per-kind subfolder (e.g., ai-models/, persons/)
    │   │   ├── {kind-subfolder}.md     subfolder leaf index
    │   │   └── {slug}.md               entity pages of this kind
    │   └── {slug}.md                   flat pages (kinds below subdivision threshold)
    ├── topics/
    │   ├── topics.md                   leaf index
    │   └── {slug}.md
    └── sources/
        ├── {origin}/                   mirrors raw/{origin}/
        │   ├── {origin}.md             wiki sources leaf index (File, What it says, My take)
        │   └── {date}-{slug}.md        source page (wiki synthesis of the raw file)
        └── studies/                    mirrors raw/studies/
            ├── studies.md              wiki sources leaf index
            └── {date}-{slug}.md        source page for study sessions
```

## Creation Rules

| Item | Created by | When |
|------|-----------|------|
| `{wiki_root}/log.md` | Ingest (first run) or user | Before first ingest |
| `raw/{origin}/` and `raw/{origin}/{origin}.md` | Lint | On first lint sweep that finds a missing raw index |
| `raw/assets/` | The user (via Obsidian) | First time Obsidian's "Download attachments for current file" runs against the configured `raw/assets` destination. Agents NEVER create or write to this folder. |
| `wiki/concepts/`, `wiki/entities/`, `wiki/topics/`, `wiki/sources/` | Ingest | Lazily on first page creation in each folder |
| Leaf indexes (`concepts.md`, `entities.md`, `topics.md`) | Lint | On first lint sweep; ingest may create defensively for sources only |
| `wiki/sources/{origin}/{origin}.md` | Ingest step 8 | If missing, created with header row before adding the first entry |
| `wiki/{type}/{kind-subfolder}/` (e.g., `wiki/entities/ai-models/`) | Lint step 7.5 | When a kind crosses ≥10 pages and the user accepts the SUBDIVISION PROPOSAL at lint step 9 |
| `wiki/{type}/{kind-subfolder}/{kind-subfolder}.md` (subfolder leaf index) | Lint step 7.5 | Same — created when the subfolder is created |
| `wiki/{type}/CLAUDE.md` (managed marker block) | Lint step 7.5 | Same — created or updated whenever subdivision state changes |
| `wiki/{type}/{type}.md` rewritten as router | Lint step 7.5 | Same — replaces the flat leaf-index format with the router format from `index-formats.md` § "Type-Folder Router Index" |

All folder and index creation is lazy — folders and indexes are created only when content requires them.

## Stability Rules

- Type folders (`concepts/`, `entities/`, `topics/`, `sources/`) are STABLE — never reorganize or rename.
- Per-kind subfolders WITHIN a type folder are an opt-in subdivision pattern proposed by lint (`/sb-wiki-lint`) when one kind crosses ≥5 pages. Pre-subdivision, every type folder is flat. Schema § "Folder subdivision" defines threshold, naming policy (e.g., `kind: model` → `ai-models/` because "models" is generic), parent-index router format, and the managed `{type}/CLAUDE.md` marker block. Subdivision is opt-in per-kind; mixed structure (some kinds in subfolders, others flat) is permitted.
- Topics-folder subdivision is deferred until ≥20 topic pages. `sources/` is already subdivided by origin and not subject to the per-kind rule.
- Raw files are IMMUTABLE — never edit a saved source file.

## Wikilink Resolution

Subdivision relies on Obsidian filename-based wikilink resolution. Required setting (per README "Obsidian setup"): Settings → Files & Links → "New link format" = `Shortest path when possible`. New wikilinks then carry no path segments and survive page moves between flat root and per-kind subfolders.

## Regulatory File

`{wiki_root}/purpose.md` is the **optional** ingest focus lens — a root-level sibling of `raw/`, `wiki/`, and `log.md`. It is **NOT a wiki page and NOT raw**; it carries `type: purpose` (non-page regulatory value, see `frontmatter-schemas.md`).

| Aspect | Rule |
|--------|------|
| Path | `{wiki_root}/purpose.md` (root-level sibling; outside `wiki/` and `raw/`) |
| Maintained by | The user (vault content). Only the ingest mechanism that READS it ships in sb-os. |
| Agent writes | Lint NEVER writes or edits it. `/sb-wiki-ingest` reads it only (Step 0.5). |
| Optionality | Absent → lens OFF → ingest identical to today. |
| Lint behavior | SKIP entirely — NEVER flag as orphan/stray/stub, NEVER index, NEVER count in orphan detection (in or out). Holds structurally: lint walks only `wiki/` and `raw/` subtrees, so a root-level sibling is never walked. Mirrors the `raw/assets/` skip contract. |

Full spec: `3-resources/tools/sb-os/wiki/docs/wiki-schema.md` § "Regulatory layer — purpose.md".

## Asset Folder

`raw/assets/` is the standard, flat, shared destination for local images and binary attachments referenced by source pages and wiki pages. It is **NOT a raw origin** — it has no `{origin}.md` leaf index, no source pages, and is excluded from every raw-origin walk.

| Aspect | Rule |
|--------|------|
| Path | `{wiki_root}/raw/assets/` (flat, single shared folder) |
| Maintained by | The user via Obsidian's core "Download attachments for current file" command. Obsidian Settings → Files and links → "Default location for new attachments" → `raw/assets`. |
| Agent writes | NEVER. No sb-os workflow creates, moves, renames, or deletes files inside `raw/assets/`. |
| Filename convention | None enforced. Obsidian writes whatever names it writes. |
| Referenced from pages | `![[filename.png]]` — Obsidian resolves via global attachment search. |
| Iteration in workflows that walk `raw/` | EXCLUDE `raw/assets/` from every iteration set. It is not an origin. |
| Lint behavior | SKIP entirely — no index creation, no orphan-detection participation (in or out), no filename validation. |
| Pre-existing exceptions | A vault may carry legacy asset folders nested inside specific origins (e.g., `raw/mails/assets/{message-folder}/` from `gmail-bridge`). User-owned; untouched by every sb-os component. New assets land in `{wiki_root}/raw/assets/`. |

Pattern source: Karpathy-style workflow. Full schema: `3-resources/tools/sb-os/wiki/docs/wiki-schema.md` § "Asset folder".
