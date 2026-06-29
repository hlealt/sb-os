# Capability — wiki-search

A named, reusable capability the tutor CONSUMES (it does not own it): a deterministic semantic + keyword search over the wiki page tree. This file is the single source of truth for HOW to invoke it and WHAT it returns; consumers reference this file instead of re-stating the command.

## Invocation

1. Resolve `{sb_os_path}` from `sb-os.json` at the vault root (the `sb_os_path` field) — never hardcode.
2. Run:

   `python {sb_os_path}/wiki/scripts/sb-wiki-search.py search "<query>" --k 5 --json`

   - `<query>` is REQUIRED — the helper is a ranked searcher, NOT a no-query enumerator. To list candidates with no query, use the leaf indexes (step-01-boot's No-Topic Menu Procedure).
   - `--k N` caps results (5 = tutor default). `--type concept,topic,entity,source,thesis,decision` optionally filters page kinds; omit to span ALL kinds (finance thesis/decision included automatically when that extension is installed).

## Output contract

Stdout is one JSON object (always valid, exit 0 even when unavailable — a caller never hard-fails on shape):

```
{ "available": true|false, "mode": "hybrid"|"fts-only"|"unavailable",
  "query": "<query>", "results": [ { "path", "anchor", "score", "snippet" }, ... ] }
```

| Field | Meaning |
|-------|---------|
| `available` | `false` → wiki not installed/usable (envelope still valid, `results: []`) |
| `mode` | `hybrid` = semantic + keyword; `fts-only` = keyword-only (Voyage key absent) — degraded but still ranked; `unavailable` = no wiki |
| `results[].path` | wiki-root-relative page path (e.g. `wiki/concepts/protocol/model-context-protocol.md`) |
| `results[].anchor` | the matched `##` section ("" = page preamble) |
| `results[].score` | relevance (higher = closer match); compare the TOP score to the C7 grounding bar |
| `results[].snippet` | ~240-char excerpt of the matched chunk |

## What it does and does NOT do

- DOES: return RANKED page chunks for one query. Cheap, deterministic, self-syncing (re-indexes changed pages before answering).
- Does NOT synthesize an answer or read across pages — that is `/sb-wiki-query` (heavier; NOT used by the front door).
- Does NOT return the wikilink graph — `results` are chunks, not neighbors. To get a page's linked-concept neighborhood (front-door stage-1 syllabus skeleton), READ the returned pages and harvest their `##` headings + wikilinks.
- DEGRADE: if the helper is missing or hard-crashes (a process error, NOT a search miss), fall back to a grep over the wiki; never hard-fail the lesson.

## Consumers

| Consumer | Use |
|----------|-----|
| Mandatory Wiki Check (step-01-boot, C6) | per-subject grounding gate — ONE query per subject; branch on the envelope into outcomes A/B/C/D |
| Front-door stage 1 — TERRAIN (front-door.md) | terrain mapping — one query per sub-ask; grounding pages + (after reading them) the syllabus skeleton |
