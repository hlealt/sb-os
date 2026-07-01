# Learning-library page-source schema

A **page-source** is one markdown file per topic at `{library_root}/topics/{slug}.md`. The builder `sb-tutor-build-library.py` turns it into `{library_root}/pages/{slug}.html` (Lumen theme) and rebuilds `{library_root}/index.html` (knowledge map). The tutor AUTHORS these files; the builder renders them. Design (look/layout/interactions) is fixed by the builder — author only content.

## Frontmatter (YAML)

```yaml
---
title: Graph Databases & Knowledge Graphs   # required — display title
slug: graph-databases                        # optional — defaults to slugified title; KEEP STABLE across re-builds/enrich
date: 2026-04-18                              # session date (YYYY-MM-DD)
started_level: intermediate                  # the R3 diagnosis verdict (beginner | intermediate | advanced)
mastery: 78                                  # 0–100, mastery at session close (drives map node size/brightness)
goal: When a graph DB beats relational, ...  # the R3 goal question answer
terms:                                       # the R3 knowledge probe — "where you started"
  - node:known                               # "term:status"; status = known | heard | new
  - property graph:heard
  - graphRAG:new
sources:                                     # "light sources" — where teaching was grounded
  wiki:                                       # wiki pages used; DISPLAY by subject. Add `page:` (the wiki note's name or path) and the builder hyperlinks the subject to that note in Obsidian — resolved by note NAME, so the link survives the wiki moving folders. A plain string still works (subject, no link).
    - {subject: Graph Databases, page: graph-databases}
    - {subject: Knowledge Graphs, page: knowledge-graphs}
  internet:
    - {title: "Neo4j — What is a graph database?", url: "https://..."}
  training: "graph theory, query languages"  # one line on the training-data substrate
related:                                      # "related topics — learn next" + map edges
  - {title: Markov Chains, slug: markov-chains, why: "the math of traversal"}
glossary:                                     # define EVERY technical term in PLAIN language (no jargon) — builder highlights each + shows a hover/focus tooltip, in prose AND graph click-to-explain panels
  node: "an entity the graph stores — a 'thing' with a label and properties."
---
```

## Body — sections + visual blocks

- Each `## Heading` starts a collapsible section that also becomes an in-topic-nav entry. Use as many as the topic needs (the page adapts to density).
- Plain markdown works: paragraphs, `**bold**`, `*italic*`, lists, `| tables |`, fenced ` ```code ```.
- Callouts: a blockquote whose first text is `[!note]` or `[!warn]` renders as a highlighted callout.
- Special fenced blocks (YAML inside, except `deeper`):

**Interactive concept diagram** (interactive-light: 1–2 KEY diagrams per topic — click any node/edge for its explanation):
````
```graph
caption: a property graph — click to inspect
nodes:
  - {id: ada, label: Ada, kind: "Node · Person", desc: "what this element IS — shown when clicked", hi: false}
edges:
  - {from: ada, to: note, label: WROTE, desc: "what this relationship IS — shown when clicked"}
```
````
Auto circular layout; `desc` is the click-to-explain text. Mark a focal node `hi: true` (amber).

**Chart** (hover a point for its value):
````
```chart
type: line          # line | bar
xlabel: hops
ylabel: query time
x: [1, 2, 3, 4, 5]
series:
  - {name: relational, color: "#E29A12", values: [1, 2, 4, 8, 16]}
  - {name: graph, color: "#5B4FE0", values: [1.2, 1.2, 1.3, 1.3, 1.4]}
caption: relational cost explodes; graph stays flat
```
````

**Go-deeper expander** (first line = summary; rest = markdown body). This is where enrich-mode adds depth:
````
```deeper
Property graph vs. triple store
A **property graph** hangs properties on nodes/edges; a **triple store** records (subject → predicate → object) facts...
```
````

**Quick-check** (one self-test per topic; `learn by doing`):
````
```quiz
q: Which job is the graph database clearly better at?
options:
  - {text: "Summing 50M rows", correct: false, fb: "that's a tabular aggregate."}
  - {text: "Connecting two people through 4 intermediaries", correct: true, fb: "many-hop is the graph's home turf."}
```
````

**Comparison trace** (per-step rows × N method-columns; each cell's bulky code opens in a wide modal so the columns stay narrow + legible):
````
```trace
caption: one capability, three ways            # optional
columns: ['MCP server', 'Agent Skill', 'CLI']  # column headers (N columns)
steps:
  - goal: '1 · Discover'                        # visible row goal
    note: 'how each door announces itself'      # optional visible sub-line
    cells:                                      # one per column, in order
      - summary: 'sends `tools/list`'           # always-visible narrow-column text
        note: 'optional prose shown in the modal'   # optional
        code: |                                 # optional — shown VERBATIM in the modal
          {"method": "tools/list"}
      - {summary: 'reads SKILL.md'}             # a cell may be summary-only (no button)
      - {summary: 'runs `--help`'}
```
````
A cell carrying `code` or `note` gets a **View I/O** button opening the page's shared modal at full width — keep the literal payload/script there, not in the narrow column. Author `code` as a `code: |` block scalar (literal — no quoting, no escaping). Like `deeper`, the block is fence-extracted, so NEVER put a nested ``` fence anywhere inside a `trace` block (the modal already renders `code` as a styled code block). Glossary tooltips apply to `caption`/`goal`/`note`/`summary`, never to `code`.

**Process flow** (a pipeline as connected stage boxes — input → step → output; a stage's long detail opens in the shared wide modal so the boxes stay scannable):
````
```flow
caption: how a raw source becomes a wiki page    # optional
stages:                                          # rendered in order, joined by arrow connectors
  - id: capture                                  # a stage with `detail` MUST be block-style (see note)
    label: 'Capture'
    kind: 'input'
    desc: 'fetch + clean the raw source'
    detail: |
      Optional LONGER detail shown in the modal when the stage's `details` button is clicked.
      Authored as a `detail: |` block scalar (literal — no quoting). May span many lines of markdown.
  - {id: ingest, label: 'Ingest', kind: 'step', desc: 'two-stage Karpathy ingest'}   # inline OK (no block scalar)
  - {id: page, label: 'Wiki page', kind: 'output', desc: 'the published note'}
```
````
Each stage box shows `label` (bold) + `kind` (a small tag) + a one-line `desc`. `kind` is free text; `input` / `step` / `output` / `decision` get subtle color variants, any other kind gets a neutral style. A stage carrying `detail` gets a **details** button that opens the page's shared modal with the rendered `detail` markdown — stages without `detail` have no button. Author `detail` as a `detail: |` block scalar (literal — no quoting); a block scalar is NOT valid inside an inline `{…}` flow map, so any stage with a `detail: |` MUST be authored as a block-style mapping (one `key: value` per line, as `capture` above). Reserve inline `{…}` for simple stages with no block scalar. Like every fenced block, the block is fence-extracted, so NEVER put a nested ``` fence inside a `flow` block. Glossary tooltips apply to `caption`/`desc`, never inside `detail` code.

**Tabs** (inline tabbed content — variants of one thing in a single space, e.g. the same example in several languages; clicking a tab shows its panel and hides the others):
````
```tabs
caption: the same fetch, two languages       # optional
tabs:                                         # a list of {label, body}; first tab active by default
  - label: Python
    body: |
      Use `requests`:

          r = requests.get(url, headers={"Authorization": f"Bearer {tok}"})
  - label: shell
    body: |
      One curl:

          curl -H "Authorization: Bearer $TOK" "$URL"
```
````
`tabs` is a list of `{label, body}`. Each `body` is a `body: |` block scalar of markdown rendered through the same engine as prose, so lists, **bold**, `| tables |`, and code all work — and code blocks inherit the **Copy + Expand** toolbar. Multiple `tabs` blocks on one page never cross-wire (each switches within its own container). Like every fenced block, the body is fence-extracted, so NEVER put a nested ``` fence inside a tab `body` — author any code in a body as a **4-space-INDENTED** block (as above), never a nested ``` fence. Glossary tooltips apply to `caption` + body prose only.

**Annotated code** (teach code line-by-line — a code block with a left line-number gutter where specific lines carry a clickable marker that opens that line's explanation in the page's shared wide modal). **Fence keyword: `anncode`** (one word, NO hyphen — the fence parser matches `^```(\w+)` and `\w` excludes hyphens, so a hyphenated keyword would silently fail to register):
````
```anncode
caption: how the script reads the secret        # optional — prose label above the block
lang: python                                     # optional — display label only (top-left tag)
code: |                                          # required — a LITERAL block scalar (no quoting/escaping)
  import os, requests
  token = os.environ["CRM_TOKEN"]
  r = requests.get(url, headers={"Authorization": f"Bearer {token}"})
annotations:                                     # optional — list of {line, note, label?}
  - line: 2                                      # 1-based line number into `code`
    label: 'secret'                              # optional — shown as the marker text (else a ● dot)
    note: |                                      # the explanation (markdown), shown in the modal
      The token is read from the **environment** — never passed as an argument,
      never in the model's context.
  - line: 3
    note: 'The script builds the Authorization header itself, server-side.'
```
````
`code` is a `code: |` block scalar rendered VERBATIM (escaped + syntax-highlighted) with a line-number gutter. `annotations` is a list of `{line, note, label?}`: each annotated line is tinted and carries a marker (the `label`, or a ● dot) that opens the page's shared wide modal showing the `note` (markdown) under an `L{line}`/`label` heading. A line with no annotation renders plain; out-of-range or duplicate `line` numbers are skipped silently. Like every fenced block, the block is fence-extracted, so NEVER put a nested ``` fence inside an `anncode` block (`code` is a block scalar, never a nested fence). Glossary tooltips apply to `note`/`caption` prose only, NEVER to the code lines.

## Citations & provenance

Back any prose claim with an inline citation — a superscript marker that shows its provenance on hover and links to a footnote at the page end. Two kinds:

| In prose | Backs a claim that is… | Renders as |
|----------|------------------------|------------|
| `[^N]` (`N` = integer ≥1) | grounded in the corpus | violet superscript `N`; hover shows `from your wiki: {subject}` |
| `[^gN]` (`g` + integer) | general knowledge (training data), not from the corpus | amber superscript `g`; hover shows `general knowledge (training data): {desc}` |

Place the marker IMMEDIATELY after the claim it backs — e.g. `Working memory is the in-context RAM.[^1] Decay is a common model.[^g1]`.

**Footnote definitions** — one per line, anywhere in the body (convention: collect them at the END of the page). The builder pulls them OUT of the prose flow (they never render as literal text):

```
[^1]: {subject: Agent memory, page: agent-memory}
[^g1]: forgetting-curve / Ebbinghaus background
```

- A SOURCE def (`[^N]`) is a flow map `{subject: ..., page: ...}` — quote any value containing `:` or `#`. `page` is the wiki note's name or path; the builder hyperlinks `{subject}` to that note in Obsidian (the SAME link as `sources.wiki`, resolved by note name). Omit `page` (or give a bare subject string) for a subject with no corpus link.
- A TRAINING def (`[^gN]`) is a plain one-line description — no corpus link.

The builder renders a **Footnotes** section at the page end, split into **Sources** (each `{subject}` corpus-linked) and **General knowledge** (plain text). Each footnote carries id `fn-N` / `fn-gN`, so every inline marker anchor-links to its definition.

- Numbering is taken AS-AUTHORED — do NOT renumber on enrich; a later assembly step guarantees page-wide uniqueness.
- Citations are PROSE-only — markers inside `graph`/`chart`/`quiz`/`trace`/`deeper`/code blocks are NOT processed, and def-shaped lines inside code are left intact.

## Reader affordances (builder-emitted — no authoring needed)

The builder adds these disclosure controls automatically; author content as normal and they appear.

- **Shared wide modal.** Every page carries ONE modal (`<div class="lib-modal" id="libModal">`, body `.lib-modal-body`). Any element with class `js-modal-open` and attribute `data-modal-src="<hidden-element-id>"` opens it, populated from that hidden element's `innerHTML`. Closes on ×, on scrim click, or Escape. The trace **View I/O** button, the code **Expand**, and the diagram **Zoom** all reuse this one modal — there is no per-block modal. A block that wants the modal emits a hidden `.lib-modal-src` source div plus a `js-modal-open` trigger pointing at its id.
- **Code Copy + Expand.** Every visible prose/markdown code block (fenced ` ``` ` in the body or inside a `deeper`) gets a small toolbar: **Copy** (copies the code text) and **Expand ⤢** (opens the same code in the shared modal so long lines have room). Trace `code:` payloads already live in the modal and are not re-wrapped.
- **Diagram Zoom.** Every `graph` and `chart` gets a **Zoom ⤢** button (top-right) that opens its SVG in the shared modal at full width, for cramped diagrams.
- **Syntax highlighting on code blocks.** Every visible code block is conservatively colorized (keywords, strings, comments, numbers, booleans/null — json/js/python/bash-ish). It is best-effort and fail-safe: ambiguous tokens stay plain and the highlighted text is byte-identical to the source, so **Copy** still yields clean code.
- **Wide tables scroll horizontally.** Every rendered markdown table gets a horizontal-scroll wrapper with a **sticky first column** (stays visible while you scroll sideways) and a subtle right-edge fade cue signalling there is more to the right.

## Rules

- `slug` is the page's identity — NEVER change it on re-build or enrich, or links/index break.
- Author content only; never write HTML/CSS/JS — the builder owns all presentation.
- **Scannable prose — bullets over walls:** prefer bulleted/numbered lists and tables over dense paragraphs; render any enumerable set (methods, status codes, steps, tradeoffs) as a list or table, not a prose wall — inside `deeper` blocks too. (Quality bar item 8 in `library-protocol.md`.)
- **YAML quoting (graph/chart/quiz/trace blocks):** any FLOW value containing a colon (`:`), a `#`, or quote marks MUST be quoted — use single quotes and double any inner apostrophe (`q: 'An agent asks: "is it X?" — Tecer''s case'`). An unquoted colon breaks the block. Exempt: `deeper` bodies, a `trace` cell's `code: |` block scalar, and a `tabs` tab's `body: |` block scalar are LITERAL (no quoting/escaping) — but none may contain a nested ` ``` ` fence. (The builder degrades a malformed block to a warning note rather than failing the page, but the block is lost until fixed.)
- Build after writing: `python {sb_os_path}/wiki/scripts/sb-tutor-build-library.py --library-root {library_root} [--topic {slug}]`.
