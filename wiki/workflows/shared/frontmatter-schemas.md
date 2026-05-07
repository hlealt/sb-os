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
tags: []
---
```

`tags` is optional and free-form. `related` uses quoted wikilinks.

## Concept — adds `kind`

```yaml
kind: <free-form string>
```

`kind` is free-form (no predefined enum). Examples: `methodology`, `pattern`, `principle`, `protocol`, `theory`, `algorithm`. Kinds do not drive schema behavior — no kind-conditional sections, no validation.

## Entity — adds `kind`

```yaml
kind: tool | person | company | product | model | benchmark | data-format
```

`kind` is a predefined enum (small and stable). Enables Dataview filtering ("all tools", "all people I follow"). Each enum value MUST pass the blind-reader test — meaning is clear without reading the page. New values added only when multiple ill-fitting entities accumulate AND the proposed name passes the blind-reader test. Generic terms (`pattern`, `spec`, `dynamic`) FAIL the test. `data-format` covers data interchange formats and notations (JSON, TOON, YAML, Markdown). `protocol` is reserved for future use (MCP, HTTP, gRPC).

## Source — adds `raw`, `url`, `author`

```yaml
raw: "[[YYYY-MM-DD-slug.md]]"
url: https://...
author: "..."
```

`raw` is a quoted wikilink to the raw counterpart. `read-date` is NOT used — `created` covers the same intent.

## Topic

No additional frontmatter. The trigger that produced the topic is recorded in `log.md`.

## Status field — DEFERRED

Stub-state is detected structurally (see `stub-policy.md`). No `status:` frontmatter field at v1.

## `sources:` field — NOT USED

Provenance lives in the Sources section body (footnote definitions). Do NOT add a `sources:` frontmatter field.
