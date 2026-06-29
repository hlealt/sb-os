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

## Rules

- `slug` is the page's identity — NEVER change it on re-build or enrich, or links/index break.
- Author content only; never write HTML/CSS/JS — the builder owns all presentation.
- **Scannable prose — bullets over walls:** prefer bulleted/numbered lists and tables over dense paragraphs; render any enumerable set (methods, status codes, steps, tradeoffs) as a list or table, not a prose wall — inside `deeper` blocks too. (Quality bar item 8 in `library-protocol.md`.)
- **YAML quoting (graph/chart/quiz blocks):** any value containing a colon (`:`), a `#`, or quote marks MUST be quoted — use single quotes and double any inner apostrophe (`q: 'An agent asks: "is it X?" — Tecer''s case'`). An unquoted colon breaks the block. (The builder degrades a malformed block to a warning note rather than failing the page, but the block is lost until fixed.)
- Build after writing: `python {sb_os_path}/wiki/scripts/sb-tutor-build-library.py --library-root {library_root} [--topic {slug}]`.
