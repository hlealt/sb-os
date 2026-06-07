# Wiki Frontmatter Schemas

Frontmatter definitions for all wiki page types. Every wiki page MUST include the common block plus its type-specific additions.

## Common (all types)

```yaml
---
type: concept | entity | topic | source
created: YYYY-MM-DD
last-touched: YYYY-MM-DD
related:
  - "[[other-page.md]]"
tags: [<type>]
---
```

`tags` MUST include the page's `type:` value as one entry (a concept page carries `concept`, a thesis page `thesis`, …) — Obsidian graph groups color by `tag:`, not by frontmatter fields. Write it at page creation; `/sb-wiki-lint`'s type-tag sync enforces it (append-only — user tags are free-form and always preserved). `related` uses quoted wikilinks.

## Index files — `type: index`

Every agent-maintained index file (wiki leaf indexes, per-kind subfolder indexes, type-folder routers, `wiki/sources/{origin}/{origin}.md`) carries `type: index` + `tags: [index]`. Not a synthesis page type — excluded from stub/orphan/page-type checks. `created`/`related` are not required on index files.

## Concept — adds `kind`

```yaml
kind: <free-form string>
```

`kind` is free-form (no predefined enum). Examples: `methodology`, `pattern`, `principle`, `protocol`, `theory`, `algorithm`. Kinds do not drive schema behavior — no kind-conditional sections, no validation.

## Entity — adds `kind`

```yaml
kind: tool | person | company | product | model | benchmark | data-format
```

`kind` is a predefined enum (small and stable). This enum is the SINGLE SOURCE OF TRUTH for entity kinds — the ingest and lint workflows and any registered extension reference it here rather than restating its values. Enables Dataview filtering ("all tools", "all people I follow"). Each enum value MUST pass the blind-reader test — meaning is clear without reading the page. New values added only when multiple ill-fitting entities accumulate AND the proposed name passes the blind-reader test. Generic terms (`pattern`, `spec`, `dynamic`) FAIL the test. `data-format` covers data interchange formats and notations (JSON, TOON, YAML, Markdown). `protocol` is reserved for future use (MCP, HTTP, gRPC).

## Source — adds `raw`, `url`, `author`

```yaml
raw: "[[YYYY-MM-DD-slug.md]]"
url: https://...
author: "..."
```

`raw` is a quoted wikilink to the raw counterpart. `read-date` is NOT used — `created` covers the same intent.

## Topic

No additional frontmatter. The trigger that produced the topic is recorded in `log.md`.

## `type: purpose` — non-page regulatory value

`type: purpose` is a valid frontmatter value reserved for the single regulatory file `{wiki_root}/purpose.md` (the ingest focus lens). It is **NOT a page type** — do NOT add it to the page-type enum (`concept | entity | topic | source`). A file carrying `type: purpose` is excluded from page-type checks, leaf indexes, and orphan detection; it is regulatory configuration, not synthesis. Base behavior — not a `wiki-ext`. Full spec: `3-resources/tools/sb-os/wiki/docs/wiki-schema.md` § "Regulatory layer — purpose.md".

## `type: questions` / `type: questions-index` — non-page values

`type: questions` is reserved for the single file `{wiki_root}/questions.md` (the user open-questions queue) and `type: questions-index` for the single lint-generated file `{wiki_root}/open-gaps.md`. Neither is a page type — do NOT add either to the page-type enum (`concept | entity | topic | source`). A file carrying either value is excluded from page-type checks, leaf indexes, and orphan detection; it is queue/aggregate data, not synthesis. Base behavior — not a `wiki-ext`. Full spec: `3-resources/tools/sb-os/wiki/docs/wiki-schema.md` § "Questions layer — questions.md".

## Status field — DEFERRED

Stub-state is detected structurally (see `stub-policy.md`). No `status:` frontmatter field at v1.

## `sources:` field — NOT USED

Provenance lives in the Sources section body (footnote definitions). Do NOT add a `sources:` frontmatter field.
