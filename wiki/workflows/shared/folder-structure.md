# Wiki Folder Structure

Directory layout for `{wiki_root}/`. All paths are relative to `{wiki_root}`. Resolve `{wiki_root}` from `sb-os.json` at runtime — never hardcode.

## Tree

```
{wiki_root}/
├── log.md                              single append-only event log
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
    │   ├── concepts.md                 leaf index
    │   └── {slug}.md
    ├── entities/
    │   ├── entities.md                 leaf index
    │   └── {slug}.md
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

All folder and index creation is lazy — folders and indexes are created only when content requires them.

## Stability Rules

- Type folders (`concepts/`, `entities/`, `topics/`, `sources/`) are STABLE — never reorganize or rename.
- Topic-folder sub-organization (e.g., `wiki/concepts/ai/`) is DEFERRED until ≥20 wiki pages. Do NOT pre-organize.
- Raw files are IMMUTABLE — never edit a saved source file.

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

Pattern source: Karpathy-style workflow. Full schema: `3-resources/tools/sb-os/docs/wiki-schema.md` § "Asset folder".
