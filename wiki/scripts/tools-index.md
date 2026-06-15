# Wiki Tool Registry (`tools-index.md`)

> Canonical registry of the **wiki module's tool layer** under `sb-os/wiki/scripts/`. Wiki workflows and agents (`sb-wiki-ingest`, `sb-wiki-query`, `sb-wiki-lint`, `sb-tutor`) read this index to discover available tools by class and use; the same tools are reached for by the finance module from their new wiki home (the capture tool is general — it writes wiki raw — so it lives here and finance calls it from this path). This file is the single source of truth for "what wiki tools exist, what class they are, and how to invoke them."

> **Scope — what belongs here.** A registry entry is a **registered wiki tool**: a capture, search, or index/validation utility that an agent reaches for to read or mutate wiki content (`{wiki_root}/raw/`, `{wiki_root}/wiki/`, the source-lifecycle queue) on the user's behalf. The deterministic wiki-internal scripts that a workflow drives as a single fixed step (e.g. the lint deterministic pass, the index-description filler, the ingest-all manifest builder) are not registry tools — they are workflow machinery, not agent-discoverable capabilities. Register the capture/search/diagnostic tools that an agent chooses to invoke.

---

## Per-Entry Schema (YAML block per entry)

Each tool is one fenced ```yaml block below the `## Registered Tools` heading — a flat map of labeled fields (NOT a wide-table row), so sibling agents parse each entry reliably and a maintainer updates a single field as a one-line diff. This mirrors the finance tool registry schema (`finance/scripts/tools-index.md`) so an agent that knows one knows both.

Every entry MUST carry exactly these keys, in this order:

| Field | Meaning |
|-------|---------|
| `tool` | Invocation name (the CLI name or `python` target the agent calls). |
| `purpose` | One sentence: what question the tool answers or what mutation it performs. |
| `owner_script` | Repo-relative path (from `sb-os/wiki/scripts/`) to the script that implements the tool. |
| `class` | `write` or `read`. `write` mutates wiki content (raw/, wiki/, queue); `read` only observes. |
| `use` | One of `parser` / `retro-rewrite` / `upsert` / `audit-diagnostic` / `validation-gate` (same taxonomy as the finance registry). |
| `expected_inputs` | The arguments and the files / stores the tool reads. |
| `outputs` | What the tool emits (report shape, or the artifacts it writes). |
| `canonical_reader_writer` | The canonical artifact(s) this tool reads from or writes to. |
| `dry_run` | `available` / `not-applicable` / `default`. `write` tools MUST be `available` or `default`. Read tools are `not-applicable`. |
| `last_validated` | ISO date (`YYYY-MM-DD`) the tool was last confirmed working, or `pending`. |

---

## Registered Tools

```yaml
tool: sb-wiki-capture-source (python wiki/scripts/sb-wiki-capture-source.py --url URL --origin ORIGIN [--mode markdown|html-archive|both|browser|manual] [--ext md|html|json] [--title TITLE] [--thesis SLUG] [--vault-root PATH] [--user-agent UA] [--manual-file PATH|-] [--no-curl-fallback] [--pdf-text] [--queue-file NAME] [--capture-date YYYY-MM-DD] [--dry-run] [--gated] [--gated-why TEXT])
purpose: |
  Save an approved open-web URL to {wiki_root}/raw/{origin}/ and return a metadata summary only
  (title, url, origin, related thesis, saved path, lifecycle state, byte count, fetch method).
  The general wiki-raw capture tool — promoted from finance into the wiki module (D6/O5); finance
  callers invoke it from this path with behavior identical to before the move.

  Queue-target (--queue-file NAME, O1): the source-lifecycle queue file (under {wiki_root}/) that
  gated/blocked rows append to. Default is source-queue.md — the byte-identical legacy queue, so a
  caller that omits the flag (every finance caller) writes the exact same path and format as before.
  Pass a separate name (e.g. study-queue.md) to route lifecycle rows to a distinct queue (the tutor's
  study-source queue) without changing any other capture behavior or output path. The default value
  IS the module constant QUEUE_FILENAME, guaranteeing byte-identical default behavior.

  Content-validation (A1): before returning captured_to_raw, every fetched body is validated:
  (1) byte floor — 0-byte / near-0-byte bodies fail; (2) CAPTCHA/bot-wall fingerprint scan —
  known interstitials (Cloudflare, Imperva, captcha markers) in a 200 body fail;
  (3) article-body density — prose extracted after stripping scripts/nav/boilerplate must
  meet a minimum; pure JS shells (Next.js self.__next_f.push() soup) fail this even if they pass
  the byte floor. On fail: state=blocked, queue row written via the same blocked path as transport
  failures (failure_reason recorded). Manual-file and PDF paths are EXEMPT from density checks
  (user already vetted); only byte floor applies.

  Article-body extraction (A2): for markdown and both modes, a two-tier extractor produces the
  primary .md written to raw/. PRIMARY: trafilatura (lazy optional dep) — purpose-built readability.
  FALLBACK (trafilatura unavailable OR near-empty): BeautifulSoup4 (lazy optional dep) richest-
  container logic — strips scripts/styles/nav/header/footer, evaluates every content-selector
  container plus <body>, keeps the richest-prose result. The full original HTML is preserved as a
  .full.html sidecar (listed under sidecar_paths, NOT saved_paths). extraction_note records the
  extraction regime when not primary-trafilatura.

  Transport fallback: on httpx failure (403/bot-fingerprint rejection/connection reset) retries once
  via subprocess curl with the same UA (fetch_method: curl-fallback) — state=blocked only after BOTH
  fail. Gated sources register gated_pending_access without fetching. Transport-level and content-
  validation blocked outcomes both register a queue entry (dedup by state+url; usage-error blocked
  and dry-run register nothing).

  Manual/browser: saves user-fetched local content via --manual-file without HTTP. PDF --manual-file
  is BINARY-COPIED to {title-slug}.pdf per Raw PDF Title-Conformance (--title required, no date
  prefix, never overwritten on collision); --pdf-text writes a pypdf companion .md.

  --manual-file path contract (A3): paths with Unicode characters (curly quotes, accented letters,
  spaces) MUST be literal-quoted in the shell. PowerShell: --manual-file '"Weird Title".html'
  (single-quote the whole argument). bash: --manual-file $'"Weird Title".html'. Pass '-' to read
  content from stdin (--title MUST be supplied for slug derivation).

  Preservation rules (tool contract): user originals are NEVER deleted. Binaries are filed
  raw/{origin}/{title-slug}.{ext} + a raw-index row. ONLY byte-identical agent-created temp files are
  removable.
owner_script: sb-wiki-capture-source.py
class: write
use: parser
expected_inputs: |
  --url (required); --origin folder name (required); --mode (markdown|html-archive|both|browser|manual,
  default markdown); --ext (md|html|json — overrides the saved-file extension for markdown-mode and
  manual/browser-mode saves; XBRL companyfacts data artifacts use --ext json; html-archive/both
  unaffected; does NOT apply to PDF saves); optional --title, --thesis slug, --vault-root, --dry-run;
  --gated (declare source gated — no fetch, registers gated_pending_access in the queue file);
  --gated-why TEXT (reason recorded in the queue entry); --queue-file NAME (source-lifecycle queue
  filename under {wiki_root}/; default source-queue.md = byte-identical legacy queue; pass a separate
  name to route lifecycle rows to a distinct queue without changing any other behavior); --user-agent
  (fetch modes send it as User-Agent on BOTH httpx and the curl fallback; default = descriptive tool
  UA; fair-access endpoints like SEC EDGAR require a contact-bearing UA); --manual-file PATH or '-'
  (required by browser/manual modes; PDF detection by .pdf extension or %PDF- magic bytes; --title
  REQUIRED for PDF captures — filename is the title-slug; '-' reads from stdin, --title required;
  paths with Unicode characters MUST be literal-quoted — see A3 contract above); --pdf-text (PDF
  manual captures only: write a {title-slug}.md companion via pypdf, a lazy optional dep; extraction
  failure or near-empty scanned-PDF surfaced as transform_error/warning, never fatal);
  --no-curl-fallback (disable subprocess-curl retry; fallback ON by default, binary resolved via
  shutil.which — never a shell alias; missing binary → state=blocked); --capture-date YYYY-MM-DD
  (override the saved raw filename's date prefix; when omitted a manual/browser --manual-file whose
  stem starts with YYYY-MM-DD keeps that original clip date on routing, else today; does not apply to
  PDF saves)

  Worked examples:
    # Gated paywall source — register without fetching (lands a queue row + manual-capture handoff)
    python wiki/scripts/sb-wiki-capture-source.py \
      --url "https://www.example.com/report" --origin example \
      --gated --gated-why "Key data behind a paywall"

    # Route a gated STUDY source to the tutor's separate study queue (O1)
    python wiki/scripts/sb-wiki-capture-source.py \
      --url "https://www.example.com/lecture" --origin example \
      --gated --gated-why "Course reading behind login" --queue-file study-queue.md

    # Manual capture of a user-fetched HTML clip (Unicode filename — PowerShell)
    python wiki/scripts/sb-wiki-capture-source.py \
      --url "https://ft.com/article" --origin ft \
      --mode manual --manual-file '"FT Article 2026".html' --title "FT Article 2026"

    # PDF binary capture with optional pypdf text companion
    python wiki/scripts/sb-wiki-capture-source.py \
      --url "https://www.cms.gov/files/report.pdf" --origin cms \
      --mode manual --manual-file report.pdf \
      --title "CMS Health Spending Highlights 2020" --pdf-text
outputs: |
  JSON metadata summary to stdout (state, url, title, origin, related_thesis, saved_paths, bytes,
  fetch_method, dry_run; manual path adds manual_source; PDF manual path adds format: pdf and lists
  companion in saved_paths when --pdf-text elected; markdown/both modes add sidecar_paths for the
  .full.html full-dump sidecar; extraction_note added when trafilatura unavailable/near-empty or bs4
  fallback runs; content-validation blocked adds failure_reason).
  For gated: state=gated_pending_access + queue_path + queue (registered|already-registered|dry-run).
  For blocked (transport or content-validation): state=blocked + error + failure_reason + queue_path + queue.

  Writes to {wiki_root}/raw/{origin}/:
  - markdown/both: YYYY-MM-DD-{slug}.{ext} (extracted article prose) + YYYY-MM-DD-{slug}.full.html sidecar
  - html-archive/both: YYYY-MM-DD-{slug}.html (full body)
  - manual non-PDF: YYYY-MM-DD-{slug}.{ext} (default .md, honors --ext)
  - manual PDF: {title-slug}.pdf (binary copy, no date prefix, collision → blocked)
  - manual PDF --pdf-text: {title-slug}.md companion (pypdf text extraction)
  - .json data artifacts (--ext json): YYYY-MM-DD-{slug}.json

  The YYYY-MM-DD prefix is the source's CLIP date: a fresh fetch uses today; routing a manual/browser
  --manual-file whose stem already carries a YYYY-MM-DD prefix preserves that original date; --capture-date
  overrides. (The source page's own `created:` frontmatter, set by ingest, stays today — only the raw
  clip-date filename is preserved.)

  Creates {wiki_root}/{queue-file} (default source-queue.md) with type: source-queue frontmatter when
  absent. Dry-run writes nothing.
canonical_reader_writer: writes {wiki_root}/raw/{origin}/<YYYY-MM-DD-slug>.{md,html,json} and <YYYY-MM-DD-slug>.full.html (sidecar) and {wiki_root}/raw/{origin}/<title-slug>.pdf (+ companion .md); appends {wiki_root}/{queue-file} (default source-queue.md; gated + transport-blocked + content-validation-blocked registrations)
dry_run: available
last_validated: 2026-06-14
```

```yaml
tool: sb-wiki-search (python wiki/scripts/sb-wiki-search.py {index [--full] | search QUERY [--k N] [--type t,..] [--json] [--no-sync] | status | probe})
purpose: Hybrid semantic + keyword search over the wiki page tree ({wiki_root}/wiki/**/*.md) — answers ranked queries for agents, self-healing the index incrementally before each search so results never go stale. Read-only over wiki content; never writes a wiki page.
owner_script: sb-wiki-search.py
class: read
use: audit-diagnostic
expected_inputs: |
  subcommand index|search|status|probe (probe = availability + mode JSON, exit 0, no query, no index
  sync — the boot availability gate). search QUERY positional; optional --k N result count, --type
  comma-separated page-type filter (concept|entity|topic|source|thesis|decision), --json machine
  output, --no-sync to skip the pre-search reindex; index [--full] to (re)build. Reads
  {wiki_root}/wiki/**/*.md and the local index at {wiki_root}/.sb-wiki-search/index.db; reads
  VOYAGE_API_KEY (OS env, else {vault_root}/.user/config/env/.env) — key present → hybrid (FTS5 BM25
  + Voyage vector cosine, RRF-fused); key absent → FTS5-only (no API calls, still ranked).
outputs: |
  search — ranked results (page path, type, score, snippet) as a table or JSON (--json). index —
  build/refresh summary. status — index freshness + active mode as JSON. probe — availability + mode
  verdict as JSON (exit 0 even when unavailable, so a mandatory caller always gets parseable output).
  Exit 0 = success; exit 2
  when the wiki root is unresolvable (callers fall back to grep). Writes only the derived index DB
  ({wiki_root}/.sb-wiki-search/index.db — derived data, kept out of vault git); never a wiki page.
canonical_reader_writer: reads {wiki_root}/wiki/**/*.md; reads/writes the derived index {wiki_root}/.sb-wiki-search/index.db (no wiki-page write)
dry_run: not-applicable
last_validated: pending
```
