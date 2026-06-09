---
stepId: investor-research
runtime: agent-loop
---

# Research Mode (B2 — Evidence)

The `/sb-investor` reasoning mode that discovers, proposes, captures, and auto-files OPEN-web sources in service of a thesis or research question, so research stops dying in chat. **This mode NEVER hand-writes a raw source file or a wiki page** — it reasons and proposes; the `investment_source_capture` tool persists to `raw/`, and `sb-wiki-ingest` (run via sub-agents) files into the wiki (delegate-not-replace).

**Loaded by:** `./investor.md` reads-and-follows this file when `./capability-manifest.md` routes the `research` (B2) intent. The invariants, policy read-rules wiring, present-and-confirm pattern, issue-surfacing, Rule A, and the per-step Investor Checkpoint in `./investor-loop.md` are already in force when this file runs — this file does NOT restate them. Read `./investor-loop.md` before acting on any step below.

**Access mechanisms (this mode):** discovery = web-search sub-agent (plugin-agnostic) · capture = `investment_source_capture` registered tool (`../../scripts/tools-index.md`) · auto-ingest = `/sb-wiki-ingest silent <slug>` run via one sub-agent per source · extract = scan sub-agent + `investment_financials_extract` registered tool (Step 7b). All are declared in `./capability-manifest.md` § `research`.

**Source lifecycle states (this mode drives them):** `rejected` → `approved_for_capture` → `captured_to_raw` → `ingested_to_wiki`; gated sources take the `gated_pending_access` branch; an unreachable/failed fetch is `blocked`. Each step below names the state it sets.

---

## Step 1 — Policy gate (MANDATORY, FIRST)

Before ANY web work, load the policy file(s) `../../CLAUDE.md` § Policy Read-Rules requires — per `./investor-loop.md` § Policy read-rules wiring. Researching sources for an investment is such an action: `research-policy.md` is required (scope / priorities / exclusions / horizon); load `source-policy.md` too (it weighs and trusts the sources this mode discovers). NEVER restate the read-rules table — read it.

If `research-policy.md` marks the research topic out-of-scope or excluded, say so and STOP, or offer to widen scope via the `policy` thin mode — do NOT reason past an exclusion (`./investor-loop.md` § Policy read-rules wiring; Rule A). This gate runs before Step 2 every time; no discovery dispatches before it clears.

## Step 2 — Anchor

Tie the research to its subject before discovering anything:

| Anchor | When | Effect |
|--------|------|--------|
| Existing thesis (preferred) | The ask names or implies a thesis already in the wiki | Discovery, ranking, and the "relation to the thesis" column are scoped to that thesis's claim and entities |
| Nascent thesis | The user is forming a belief not yet persisted | Anchor to the in-progress claim; the captured evidence later feeds `thesis` (B1) |
| Exploratory research question | A bare topic with no thesis ("dig into `<topic>`") | Register the question; exploratory findings MAY later fire a `candidate-thesis` trigger (Step 8) that feeds B1 |

Identify the entity(ies) the research touches — they scope discovery and become the `--thesis` / origin context passed to capture.

## Step 2.5 — Decompose (atomic sub-questions + coverage matrix)

Before discovering anything, split the anchor (the thesis claim or research question fixed in Step 2) into **atomic sub-questions** — the smallest standalone questions whose answers, taken together, settle the anchor. Decomposition is ANCHORED: every sub-question must trace to the anchor's claim and the entity(ies) from Step 2; do not drift into adjacent topics the anchor does not raise, and respect the `research-policy` scope/exclusions loaded in Step 1 (a sub-question that probes an excluded topic is dropped here, not searched).

Build a **coverage matrix** mapping each sub-question to the angle and source-type that will address it. The matrix is the contract the Step 3 width sweep fans out against (one discovery wave per sub-question) and the yardstick the Step 4 Propose step measures coverage gaps against:

```
| # | sub-question | angle / source-type that will address it |
```

Decompose reasons only; it writes nothing and fetches nothing. Keep it lightweight — atomic sub-questions and one matrix, not a research plan. This step adds no web access and no new write path.

## Step 3 — Discover (parallel width sweep — one sub-agent wave per sub-question)

Run a **parallel width sweep**: fan out web-search sub-agents — **one wave per Step 2.5 sub-question** — dispatched concurrently so breadth is covered in a single pass rather than one serial search. Each wave hunts OPEN sources for its own sub-question and the angle/source-type the coverage matrix assigned it. The fan-out MUST keep the mode plugin-agnostic — discovery is NOT wired to any single search plugin, preserving sb-os finance-module portability.

**The Step 7a Disconfirm wave fires in THIS same discovery pass** (it is numbered 7a for dispatch-identity only — see Step 7a § Where it runs; it is NOT a post-ingest step). Dispatch it concurrently with the width-sweep waves here; its disconfirming candidates merge into the same Step 4 Propose table. The remaining acquisition steps (Capture → Gated → Auto-ingest, Steps 5–7) act ONLY on approved sources — the Step 4 user-approved subset plus any standing-policy AUTO captures (Step 4 auto-capture partition).

**Cost cap (every discovery wave — width sweep AND the Step 7a Disconfirm wave).** This is the explicit cheap-model override the deepening mandates (it overrides the `sb-sub-agents` default of `sonnet`); name it in each wave's dispatch:

| Knob | Value |
|------|-------|
| Model | **Haiku** (high-volume discovery does not need deep reasoning) |
| Max fetches per wave | **≤ 5** |
| Wave shape | **single-pass** — each wave fires once, returns, and NEVER loops |
| Concurrency | parallel fan-out, bounded by the per-wave fetch cap |

Each discovery sub-agent's prompt MUST:

1. **Invoke the `rbtv-web-searching` skill before any web work and follow it exactly** (per the sub-agents rule — a sub-agent does not inherit this requirement; the parent states it explicitly and imperatively).
2. Carry its assigned sub-question, the anchor (thesis claim / research question), the entity(ies), and the `research-policy` scope and exclusions so the sub-agent does not surface excluded topics.
3. **Verify every candidate URL is live before returning it** — the wave's own fetch of the page, or a HEAD-level liveness check when the page was not fetched, MUST confirm the URL resolves. A dead, 404, or unresolvable URL is dropped, NEVER returned as a candidate.
4. **Assign each candidate's trust class against the rubric carried in the prompt.** The parent passes the `source-policy.md` trust tiers (loaded in Step 1) into the wave prompt; while those tiers are unfilled, pass the seed rubric: `1 = primary (filings, regulator/company official) · 2 = trusted analysis (named research firm/analyst with a track record) · 3 = established press · 4 = unverified (blog / UGC / aggregator)`. When in doubt between two classes, assign the LOWER trust (the higher number) — never inflate.
5. **Return ONLY ranked candidates + metadata** — `| title | url | source | trust class | why it matters | relation to the thesis |`. The **full source text MUST stay inside the sub-agent** and NEVER returns to this mode or `sb-investor.md` (anti-context-rot — the parent context stays clean; only ranked candidates + metadata cross back). **Wave-figure status (BINDING):** any figure a wave sub-agent cites in its metadata is UNVERIFIED by default and is NEVER citable until an ingest confirms it in the captured source (Step 7 item 3 figures-to-verify RETURN). Wave rankers MUST watch for the correction classes catalogued in `./data/correction-classes.md` — these are the named failure modes a figure can carry before ingest verification.

Merge the waves' returned candidates and rank them by relevance to the anchor AND by `source-policy` trust class (loaded in Step 1). A candidate that fails the `source-policy` trust bar is surfaced per `./investor-loop.md` § Issue-surfacing — never silently dropped or silently kept. Discovery writes NOTHING; it only returns ranked candidates with metadata. The merged candidate set (plus the Step 7a disconfirming candidates) is what Step 4 Propose presents.

### D25 — Reachability probe (parent runs AFTER wave returns)

After the Step 3 fan-out returns — before presenting Step 4 — the PARENT issues one HEAD request per election candidate (each URL from the merged candidate set). This is a HINT ONLY:

| Result | Action |
|--------|--------|
| Non-2xx | Flag the row "possibly blocked — bridge link required"; PREPEND its bridge link in the candidates table. The row STAYS in the table — a non-2xx probe NEVER auto-removes a row |
| 2xx | No change to the row |

**Counter-lesson (BINDING).** Wave-side fetch failure does NOT predict tool-side capturability. Real evidence: IMF, JPM, BLS, pv-magazine all returned 403s during the Step 3 wave AND were captured cleanly by the tool afterward. ALWAYS attempt capture on approved candidates; the probe only adds a bridge link, it NEVER skips a row.

## Step 4 — Propose (present-and-confirm; DEFAULT = propose before capture)

**Auto-capture partition (standing pre-approval — runs FIRST).** If `source-policy.md` (loaded in Step 1) declares an `Auto-Capture Pre-Approved Origins` table, partition the merged candidates (width-sweep and Step 7a disconfirming alike) BEFORE presenting:

- **AUTO** — the candidate URL is `https` AND its host equals a listed host pattern or ends with `.` + the pattern (dot-boundary suffix, never substring — `sec.gov.evil.com` does not match `sec.gov`), AND the candidate addresses the anchor or a Step 2.5 sub-question (the same relevance bar as the propose table — pre-approval covers trust, never relevance). Set state `approved_for_capture` (granted by standing policy — record `approved_by: policy`) and capture via Step 5 IMMEDIATELY, before this checkpoint presents; the allowlist row IS the user's confirmation (`./investor-loop.md` § Present-and-confirm, standing carve-out).
- **REST** — every other candidate, including an allowlist match that fails the relevance bar (flag its row `allowlist-match, low relevance`) → the propose flow below, unchanged.

Agent-judged trust class NEVER triggers auto-capture — only the deterministic URL-host match does. No such table in `source-policy.md` → no partition; every candidate is REST.

Run `./investor-loop.md` § Present-and-confirm. Default behavior is propose-before-capture: present the ranked candidates and STOP for the user's selection — NEVER capture a REST candidate before approval (AUTO candidates above carry standing approval). When the AUTO partition captured sources, open the presentation with an informational **auto-captured block** — `| source (slug) | origin | state | saved path | relation to the thesis |` (disconfirming candidates tagged) — it reports completed captures and asks nothing. If REST is empty, SKIP this checkpoint's STOP — proceed to Step 7, whose Ingest gate presents the block instead (zero-touch capture; the run still stops ONCE, at that gate). Present each candidate as a row, including the Step 7a disconfirming candidates merged into the same table:

```
| # | title | url | source | trust class | why it matters | relation to the thesis |
```

Tag every Step 7a Disconfirm-wave candidate in its `relation to the thesis` cell as **disconfirming (evidence-against)** so the user sees, in one table, both the sources that support the anchor and the source(s) that would overturn it — never an undifferentiated list. (Step 7a defines the disconfirming wave; its candidates arrive here pre-tagged.)

**Below-bar flag (trust gate).** A candidate below the `source-policy` trust bar (tier 4 / unclassifiable) arrives with its `trust class` cell flagged `4 — below evidence bar`. This flag IS the Step 3 issue-surfacing for discovery candidates — the user approves or rejects it eyes-open at this checkpoint; NEVER add a separate inline stop per flagged row, and NEVER drop a flagged candidate silently. **Pre-table exclusion is NOT permitted:** a below-bar candidate MUST appear as a flagged row in this Propose table — never struck or dropped before presentation behind a summary note. The flagged in-table row is the contracted discovery surface; striking below-bar candidates pre-table defeats the eyes-open election.

**Sponsored / advertorial flag.** When a candidate's discovery metadata (title, source, `why it matters`) suggests sponsored or advertorial content, flag its row `sponsored?` so the user weighs it eyes-open. Discovery metadata cannot always reveal sponsorship — this is a HINT surfaced when the signal is present, never a guarantee and never a gate; a candidate discovered clean may still prove sponsored at ingest.

**Known-blocked flag (capture routing).** When a candidate's origin matches `source-policy.md` § Known-Blocked Origins (a tool-confirmed repeat-blocker), flag its row `known-blocked → manual bridge` so the user elects it eyes-open knowing its capture will route to the manual bridge, not a fetch (Step 5 skips the doomed fetch for these). The flag NEVER drops the candidate — the user may still elect it for manual bridging.

**Coverage gaps (from Step 2.5).** Cross-check the merged candidates against the Step 2.5 coverage matrix and surface, beneath the table, any **sub-question with no candidate** — an explicit "coverage gaps" note so the user sees what the sweep did not cover before approving:

```
Coverage gaps: sub-questions {#…} have zero candidates.
```

A coverage gap is informational, not blocking — the user MAY approve the subset anyway, widen scope, or re-run discovery for the uncovered sub-questions.

**Source tensions (lightweight flag).** From the candidates' titles and `why it matters` / `relation to the thesis` metadata ALREADY on the table — never by pulling full source text (anti-context-rot holds) — flag pairs or clusters of candidates that **contradict each other** (e.g. opposite conclusions on the same sub-question). Surface them as a short note beneath the table so the user weighs the disagreement instead of an undifferentiated list:

```
Source tensions: #{a} ↔ #{b} — {one-line description of the disagreement}.
```

This is a flag the user can act on, not a separate analysis pass: it reads only the metadata already returned. If no contradiction is evident from the metadata, write none — do not fetch text to manufacture one. The signal stays legible for `review` to consume downstream.

The user approves a SUBSET (supporting and/or disconfirming candidates alike). Approved OPEN candidates → state `approved_for_capture` (Step 5). Candidates the user rejects → state `rejected` (no capture, no record beyond the turn). Candidates the user (or discovery metadata) marks gated/paywalled → the gated branch (Step 6). The coverage-gap and source-tension notes do not change this subset-approval flow — they inform it. This is a mode checkpoint per `./investor-loop.md` § Per-Step Checkpoint.

## Step 5 — Capture approved OPEN sources

For EACH `approved_for_capture` OPEN source, call the registered `investment_source_capture` tool (`../../scripts/tools-index.md`) — the SOLE writer of `raw/` files; the agent NEVER hand-writes a raw source file (`./investor-loop.md` § Own-workspace-writes boundary). Pass the url, the origin folder, the fetch mode, and the anchoring thesis slug per the tool's `expected_inputs`.

**User-Agent.** If `source-policy.md` (loaded in Step 1) declares a `Capture User-Agent`, pass it via `--user-agent` on EVERY capture call. Fair-access endpoints (e.g. SEC EDGAR) 403 non-contact UAs — the tool's default UA is NOT sufficient there; the contact-bearing UA from `source-policy.md` is.

**Known-blocked pre-check (skip the doomed fetch).** Before calling the capture tool to FETCH an `approved_for_capture` OPEN source, check its origin against `source-policy.md` § Known-Blocked Origins (loaded in Step 1). On a match — a curated, user-approved tool-confirmed repeat-blocker — SKIP the fetch attempt entirely: emit the source's ready-to-act block per `./investor-loop.md` § Manual-bridge handoff and register it as pending via the capture tool's no-fetch path (`--gated`) so `{wiki_root}/source-queue.md` tracks it. This applies ONLY to origins on the curated Known-Blocked list — NEVER to a Step-3 / D25 wave-side reachability hint (counter-lesson: wave-side failure does NOT predict tool-side capturability; only a tool-confirmed repeat pattern lists an origin). An origin that later captures cleanly leaves the list via the policy mode.

**Worked examples (B11).**

```
# Standard open capture
investment_source_capture --url https://example.com/report.html --origin spglobal --title "S&P Report 2025" --thesis my-thesis-slug

# Gated registration (no fetch)
investment_source_capture --gated --gated-why "requires brokerage login" --url https://broker.example.com/report --origin broker --title "Broker Report 2025" --thesis my-thesis-slug

# Manual file (user-fetched content)
investment_source_capture --mode manual --manual-file /path/to/downloaded.html --url https://example.com/report.html --origin spglobal --title "S&P Report 2025" --thesis my-thesis-slug

# PDF with text extraction
investment_source_capture --pdf-text --url https://example.com/doc.pdf --origin imf --title "IMF Article IV 2025" --thesis my-thesis-slug
```

**Preservation rules (B11 — BINDING).** User originals are NEVER deleted. Binaries (PDFs, images) are filed at `raw/{origin}/{title-slug}.{ext}` with a raw-index row — NEVER moved ad-hoc. ONLY byte-identical agent-generated temp files are removable. Clipper-duplicate disposal: an Obsidian-clipper " 1.md" copy of a verbatim-captured text original is byte-identical to the already-captured file → removable under the same byte-identical temp rule.

**Referenced-file capture (A10).** When the user directs capture/ingest of a file not yet in `raw/{origin}/` — present in Downloads or `raw/_unrouted/` — route it via `investment_source_capture --mode manual --manual-file <path> --url <URL> --origin <origin> --title "<title>"`. The tool is the SOLE raw writer; NEVER move or copy the file ad-hoc. Infer origin from file provenance and CONFIRM with the user when origin is ambiguous. When the user states a source has images at given paths, move each into `{wiki_root}/raw/_assets/` with a descriptive slug and embed `![[slug.png]]` in place of the original path; flag uncertain placement for user review.

The tool saves to `{wiki_root}/raw/{origin}/` and returns a **metadata summary only** (state, saved path, title, origin, related thesis, byte count) — full source text NEVER enters this mode's context. On success → state `captured_to_raw`; capture the returned raw filename for Step 7. A tool result of `state=blocked` (unreachable / fetch failed) → surface it per `./investor-loop.md` § Issue-surfacing; that source stops at `blocked` and is NOT ingested.

**Blocked-fetch recovery (manual path).** The tool itself transparently retries a transport-level fetch failure (403 / bot-fingerprint rejection / connection reset) via an in-tool subprocess-curl fallback with the same UA BEFORE returning `state=blocked` — the metadata return records which method fetched (`fetch_method: httpx | curl-fallback`), so a returned `blocked` already means BOTH methods failed. The tool also registers the blocked source in `{wiki_root}/source-queue.md` (dedup by state+url), so an unrecovered block survives the session and `sb-wiki-lint` surfaces it as a retry candidate. When an approved source (user-approved or standing-policy AUTO) still returns `state=blocked`, offer the manual path at the checkpoint instead of escalating an unstructured doubt: the USER fetches the page by their own means and provides a local file path; the agent re-runs the tool with `--mode manual --manual-file <path>` — the tool (still the SOLE writer) saves it into `raw/{origin}/` with standard naming and the source resumes the normal lifecycle (`captured_to_raw` → Step 7). The agent NEVER fetches outside the tool, NEVER stores files outside `raw/`, and NEVER hand-places the content itself.

## Step 6 — Gated sources register (NOT fetched)

A gated source (paywall / login / IR / broker portal) is NEVER fetched — the permanent source boundary in `./investor-loop.md` (no paywall bypass, no bank/brokerage credentials). Register it as `gated_pending_access` by calling the `investment_source_capture` tool with its `--gated` path — the SOLE writer of the gated record (it appends to `{wiki_root}/source-queue.md` without fetching — the investment source queue that `sb-wiki-lint` surfaces and prunes; the agent NEVER hand-writes that record, per `./investor-loop.md` § Own-workspace-writes boundary). Pass title, url, origin, the related thesis slug, and why it matters per the tool's `expected_inputs`; the tool records the required user action. So the gated source surfaces at end-of-interaction instead of dying in chat, ALSO record it as a deferrable issue per `./investor-loop.md` § Issue-surfacing. State → `gated_pending_access`. Never advance a gated source to capture or ingest.

**Preservation rules carry forward (B11).** User-provided originals for gated sources are NEVER deleted — the same byte-identical-temp-only deletion rule applies. No file moves outside the tool's write path.

## Step 7 — Auto-ingest (one sub-agent per captured source, SEQUENTIAL)

### Ingest gate (MANDATORY — ONE stop before any ingest dispatch)

Fires on EVERY run that captured at least one source — even when every capture was pre-approved (a zero-touch capture run stops HERE, once). Ingest is the heavy, shared-surface half of the pipeline; this gate is the user's ingest delegation / context-refresh point and the no-silent-ingest guarantee. Before dispatching the FIRST ingest sub-agent:

1. **Present the consolidated capture state** — every capture this run, auto and user-approved alike, plus failures:

   ```
   | source (slug) | origin | approved_by (user/policy) | state | saved path | extract? |
   ```

   A `blocked` row names its error; the Step 5 manual path is its recovery. `extract?` defaults ON for fundamentals-bearing primary sources (filings, IR documents, macro releases) and OFF otherwise; the user may toggle any row at this gate. `[S]` authorizes the ingest dispatch AND Step 7b extraction for the `extract? = yes` rows, including the lane-1 companion companyfacts capture (Step 7b.1).

2. **Growth prompt (batched, non-blocking).** If this run captured sources whose origins are NOT in `source-policy.md` § Auto-Capture Pre-Approved Origins and NOT on its declined line, offer ONCE — every such origin in one prompt, each with a proposed host pattern derived from the captured URL host. Approval → append the row(s) to that table; decline → record the origin on the table's declined line and never re-offer it. Both are user-approved policy edits inside the own-workspace boundary (this exchange IS their present-and-confirm). The answers never block ingest. Skip silently when `source-policy.md` has no such table.

3. **STOP and offer:**

   ```
     [S] Ingest all now — sequential dispatch per § Dispatch below.
     [E] Adjust — exclude sources from this ingest, or hand the list to another agent / a fresh session (non-ingested sources stay captured_to_raw).
     [N] Defer — nothing ingests; record the deferred set per ./investor-loop.md § Issue-surfacing so it cannot rot silently.
   ```

Wait for the user's choice — this is a mode checkpoint per `./investor-loop.md` § Per-Step Checkpoint.

**Deferred captures (BINDING — name them on the durable page).** Every source captured this run but NOT ingested — `[E]` exclusions or an `[N]` deferral — is recorded to `.user/finance/investor/log.md` per `./investor-loop.md` § Issue-surfacing AND named on the anchoring thesis/topic page under a `Captured — pending ingest` list (`slug · origin · trust class · why it matters · raw path`), so the deferred set lives on the durable page the user reads — not only in the log. When the run chains to `thesis`/`review`, hand the pending-ingest list to `sb-fin-create-thesis` for that section; a bare research question with no thesis names them on its candidate-topic/topic page instead. A deferred capture present in neither the log NOR a durable page has violated this rule.

### Dispatch

After the gate clears (`[S]`, or `[E]`'s adjusted list), file each `captured_to_raw` source into the wiki by dispatching **one sub-agent per source, ONE AT A TIME — never in parallel**. Full text still stays in each sub-agent's context, so this mode and `sb-investor.md` stay clean (anti-context-rot holds). The agent invokes the real ingest command via the sub-agent; it NEVER reimplements ingest.

**Why sequential (BINDING).** Ingest sub-agents write SHARED wiki surfaces — topic hubs, concept/entity stubs, leaf indexes, `log.md` — and parallel ingests race on them (observed 2026-06-03: a lost-then-restored section and four duplicate-stub clusters from a 16-agent fan-out). Dispatch sub-agent N+1 only after sub-agent N returns its summary. Parallel ingest dispatch returns ONLY if `sb-wiki-ingest` ever gains page-level write locking.

**Commit policy (BINDING).** NO git command runs during ingestion — ingest sub-agents NEVER git-commit, and this mode NEVER commits per source, per batch, or per wave (mirrors `sb-wiki-ingest-all` § single git commit). A sub-agent's per-file status `committed` means staged FILE changes written to disk, NEVER git. The run produces EXACTLY ONE git commit at the very end — after ALL ingests, Step 7b extractions, and any chained `thesis`/`review` authoring finish — covering every change the run produced, made via the workspace commit path (`rbtv-commit`). Skip when the vault root is not a git repository.

Each sub-agent prompt MUST direct it to:

1. **Run `/sb-wiki-ingest silent <slug>`** — the non-interactive form (`<slug>` = the raw filename returned by Step 5). The `silent` keyword makes the run emit no checkpoints and return a structured per-file summary, per `sb-wiki-ingest`'s Silent Mode.
2. **Invoke the `sb-wiki-ingest` skill and follow it exactly**, and **invoke the `sb-vault-ops` skill before the file operations it performs and follow it exactly** (per the sub-agents rule — stated explicitly and imperatively because a sub-agent does not inherit these requirements).
3. **Return only the structured summary** (per-file status `committed` / `partial (<reason>)` / `failed (<reason>)`, plus pages created/updated and any candidate-topic or lint flags). The full source text MUST NOT be returned to the parent. **Figures-to-verify contract (BINDING):** the RETURN MUST include, for every headline figure the source page captured, the exact figure AND the location in the captured source where it appears (the citation-verification record). This is the verification record B13 couples to: a wave-returned figure is UNVERIFIED until an ingest return confirms it against the captured source.
4. **NEVER add, modify, or delete `## Financials` rows on any entity page** — the sole writer of that section is the `investment_financials_extract` tool (Step 7b), per `section-menus.ext.md` § `## Financials`. Extractable fundamentals found during ingest are reported as extraction candidates in the summary, never written.
5. **Run NO git commands** (no `add` / `commit` / `push`) — return the summary only; per § Commit policy the orchestrator makes the run's single commit at the very end.
6. **NEVER create or edit thesis pages** — per the `sb-wiki-ingest` write-surface contract (thesis pages scribe-only; A7). Thesis-relevant figures, conclusions, or data found during ingest MUST be reported in the return summary — NEVER written to a thesis page.
7. **Environment caveats (A8 — these do NOT inherit from the parent session):**
   - **Verify absence with a second method** before concluding a file is missing: a content search, directory listing, or per-directory pattern MUST confirm absence — Glob on Windows silently returns empty or partial results (false-negative).
   - **Platform write path:** use PowerShell / the Write and Edit tools; NEVER construct phantom WSL paths (e.g., `/mnt/c/…`) — the vault is on Windows.
8. **Accept-all pre-approval (gate-approved runs — BINDING).** Once the Ingest gate is approved (`[S]` or `[E]`'s adjusted list), the dispatch carries accept-all pre-approval: the ingest sub-agent NEVER re-prompts the user per source mid-run. The gate `[S]` IS the authorization for every source in the approved set; sequential dispatch does not create additional checkpoints.
9. **`{IF MANUAL-BRIDGED BINARY}`** When the ingested raw is a manual-bridged binary (PDF captured via `--mode manual` or `--pdf-text`), the ingest MUST write the body line `Original PDF: [[{title-slug}.pdf]]` on the source page immediately after frontmatter (the A6 convention; ADX-2). This line is a body line — NEVER a frontmatter key.
10. **Model: `sonnet`.** Ingest sub-agents run on `sonnet` — NEVER Haiku. Numeric and structured content demands the reasoning capacity; Haiku is cost-cap for discovery only (Step 3 / Step 7a).

On a returned summary → state `ingested_to_wiki` for that source. A `failed` / `partial` status is surfaced per `./investor-loop.md` § Issue-surfacing — never silently treated as ingested.

### Post-ingest report (MANDATORY — replaces a pre-ingest confirm)

After all sub-agents return, present a consolidated report so a misfire is catchable:

```
| source (slug) | ingest status | pages created/updated | scope-overlaps / lint flags |
```

Summarize the pages created/updated and any scope-overlaps or lint flags the sub-agents surfaced. A flag is an issue → route it per `./investor-loop.md` § Issue-surfacing (blocking vs deferrable). The report is informational-by-default; it does NOT re-prompt for the already-committed ingests (the Ingest gate authorized the dispatch).

## Step 7b — Extract fundamentals (per-source, sequential, after its Step 7 ingest returns)

Runs for each source whose Ingest-gate row was marked `extract? = yes`, AFTER that source's ingest sub-agent returns (ingest precedes extraction — the entity page must exist). The registered `investment_financials_extract` tool (`../../scripts/tools-index.md`) is the SOLE writer of entity `## Financials` (conventions in `section-menus.ext.md`); this mode NEVER hand-writes a row.

1. **Lane-1 artifact (SEC-registrant entities):** ensure a current companyfacts artifact exists — when absent, or older than the filing being extracted, capture `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` via `investment_source_capture` with `--ext json`, `--origin sec`, `--title "{entity} xbrl companyfacts"`, and the `source-policy.md` § Capture User-Agent. The gate's `extract?` approval authorizes this companion capture; it appears in the post-extraction report — no silent writes. `{cik}` = the entity page's `cik:` frontmatter zero-padded to 10 digits; on a company's first SEC extraction, PROPOSE adding `cik:` (user-approved edit per `frontmatter-schemas.ext.md`).
2. **Scan dispatch (one sub-agent per source+entity):** model **Sonnet** — NEVER Haiku for numeric work; **Opus opt-in** when the source feeds an active thesis. Pass the captured raw path(s), the entity + kind, that kind's vocabulary from `metric-vocab.md` (incl. § Suffix Families), and any active-thesis focus. The sub-agent returns ONLY extraction-target rows — `| metric (vocab id or PROPOSAL:<name·kind·unit>) | period_type | period_end | value-as-printed | unit-as-printed | anchor (verbatim) | unverifiable? + reason |` — **stated figures only** (no derived values; derivations happen at read time, never at write time); anchors MUST be contiguous printed phrases (never a figure straddling HTML-tag boundaries — the tool's normalized re-match fails on markup-split text); the full source text stays inside the sub-agent (anti-context-rot). Write the returned targets to a JSON file under `.user/finance/investor/` (path transport — never inline in a prompt).
3. **Vocab proposals:** surface any `PROPOSAL:` rows at the checkpoint. Approved → the parent applies the addition to `metric-vocab.md` (an sb-os edit: investor proposes, user approves, parent applies + commits), then the row extracts; rejected → dropped. Nothing off-vocabulary is ever written.
4. **Run the tool:** lane 1 `--xbrl <artifact>` (corroborate-only by default; pass `--since <filing period start>` to extract the new filing's periods), then lanes 2/3 `--targets <json>`. The gate's `extract?` approval authorizes the write — auto-write, no per-figure gate (spec §4.4).
5. **Post-extraction report (MANDATORY** — mirrors the post-ingest report): `| entity | source | rows written (xbrl/structured/llm) | upgraded | rejected (reason) | conflicts | vocab proposals |`. Conflicts and rejects route per `./investor-loop.md` § Issue-surfacing.

The **standalone extract route** (`./capability-manifest.md` § `extract`) runs these same steps 1–5 against already-captured raw — the backfill/reconciliation path. Its authorization is the user's ask itself, gated once: run the tool `--dry-run` first, present the step-5 report, and apply only on confirm (present-and-confirm; no Ingest gate exists on a non-capturing run).

## Step 7a — Disconfirm (adversarial discovery wave)

The highest-value discovery primitive: instead of asking "what supports the anchor?", it asks **"what source would OVERTURN the anchor?"** and hunts for it — making the rigor spine (evidence → counter-evidence → invalidation) an ACTIVE search, not a reasoned-from-context afterthought. Step 7a is the **stable, dispatchable home** of this wave: `thesis` (B1) and `review` (B3) reach it by DISPATCHING `research` (the existing `review`→`research` sub-agent precedent), never by re-implementing discovery. Keep its interface below stable — consumers depend on it.

**Where it runs (sequencing).** Although numbered 7a, the Disconfirm wave is a DISCOVERY operation: it fires in the discovery pass **alongside the Step 3 width sweep**, and its candidates merge into the **Step 4 Propose** table tagged `disconfirming (evidence-against)` — they are NOT a post-ingest step. Capture/ingest (Steps 5–7) act only on the subset the user approves at Step 4; a disconfirming candidate the user approves flows through capture-and-ingest exactly like any other approved source. The 7a label marks the wave's identity and dispatch interface, not a runtime position after ingest.

**Interface (DOCUMENTED — keep stable; `thesis`/`review` dispatch against this):**

| Side | Contract |
|------|----------|
| **Input** | The anchor claim / assumption (the Step 2 thesis claim, or — when dispatched by a consumer — the specific assumption or near/untested invalidation criterion the consumer hands in) + the entity(ies) + the `research-policy` scope/exclusions |
| **Output** | **Ranked disconfirming candidates + metadata ONLY**, each carrying a **why-it-would-overturn** note (what about the source, if true, falsifies the anchor) in addition to the standard `| title | url | source | trust class | why it matters | relation to the thesis |` fields. Full source text NEVER returns to the parent. |

**Dispatch.** Prompt ONE sub-agent (native dispatch — NOT the `deep-research` skill) to find the strongest source that would FALSIFY the anchor. The prompt MUST:

1. **Invoke the `rbtv-web-searching` skill before any web work and follow it exactly** (the sub-agent does not inherit this requirement; state it explicitly and imperatively), keeping the wave plugin-agnostic (no hard-wired search plugin).
2. Frame the hunt adversarially: search for the data, analysis, or primary source that, if it exists and holds, breaks the anchor — not for confirmation of it.
3. Obey the **same cost cap as the width sweep** (Step 3 table): **Haiku model · ≤ 5 fetches · single-pass, never loops**.
4. Carry the **same URL-liveness verification and trust-class rubric requirements as the Step 3 wave prompts** (Step 3 prompt items 3–4).
5. **Return ONLY ranked disconfirming candidates + metadata + the why-it-would-overturn note.** The **full source text MUST stay inside the sub-agent** (anti-context-rot — the parent context stays clean).

Rank the returned disconfirming candidates by `source-policy` trust class (loaded in Step 1) exactly as Step 3 does; a candidate that fails the trust bar is surfaced per `./investor-loop.md` § Issue-surfacing — never silently dropped or kept. The wave writes NOTHING and fetches nothing into this mode; it adds no new data-access path. Its candidates feed the Step 4 Propose checkpoint, where the user approves or rejects them through the unchanged present-and-confirm subset flow — nothing disconfirming is captured before approval, per-run or standing (the Step 4 auto-capture partition applies to disconfirming candidates identically).

### B10 — Canonical Disconfirm-Wave Prompt Skeleton (SINGLE SOURCE — `thesis.md` Step 2b dispatches this)

This is the CANONICAL skeleton. `thesis.md` (Step 2b) DISPATCHES `research` pointing at this skeleton — do NOT duplicate it there.

```
You are a disconfirm-wave sub-agent. Your SOLE job is to find the strongest source(s) that would FALSIFY the anchor claim below. Do NOT search for confirmation.

MANDATORY — invoke the `rbtv-web-searching` skill before any web work and follow it exactly.

--- INPUT CONTRACT ---
Anchor claim: {anchor_claim}
Entity/entities: {entities}
Specific assumption or invalidation criterion (if dispatched by thesis/review): {specific_assumption_or_criterion}
Research-policy scope: {scope}
Research-policy exclusions: {exclusions}
Source-policy trust tiers: {trust_tiers}
--- END INPUT CONTRACT ---

SCOPE: adversarial only — hunt for data, analysis, or primary sources that, if true, break the anchor claim. Respect the research-policy exclusions above; drop any candidate touching an excluded topic.

HARD BOUNDARIES:
- Model: Haiku
- Max fetches: ≤ 5
- Wave shape: single-pass, NEVER loop
- Return ONLY ranked candidates + metadata (full source text MUST stay inside this sub-agent — anti-context-rot)
- Verify every candidate URL is live before returning it (HEAD or page fetch); drop dead / 404 / unresolvable URLs
- Trust-class assignment: when uncertain between two tiers, assign the LOWER trust (higher number) — NEVER inflate

TRUST-TIER SEED RUBRIC (use tiers from INPUT CONTRACT if filled; fall back to this):
1 = primary (filings, regulator / company official)
2 = trusted analysis (named research firm / analyst with a track record)
3 = established press
4 = unverified (blog / UGC / aggregator)
Uncertain → assign LOWER trust (higher tier number).

ORCHESTRATION LESSONS (BINDING):
(a) Worklist / input notes are LEADS, not citation mandates — a lead points to a domain, not a pre-approved source; verify and qualify independently.
(b) Input notes are point-in-time — RE-VERIFY every claim against the live wiki before acting on it; a stale note is not ground truth.

RETURN SHAPE — return ONLY this table, no other text:
| title | url | source | trust class | why it matters | relation to the thesis | why-it-would-overturn |
(Tag each row: disconfirming (evidence-against))

WAVE-FIGURE STATUS (BINDING): any figure cited in the metadata above is UNVERIFIED by default — NEVER citable until a Step 7 ingest confirms it in the captured source. Watch for the correction classes in `./data/correction-classes.md` when assigning trust and why-it-would-overturn.
```

## Step 8 — Feed forward

Ingested sources are now evidence available to other modes:

- They feed `thesis` (B1) authoring as sourced evidence-for / evidence-against.
- They feed `review` (B3) when an existing thesis is re-evaluated against fresh sources.
- A `candidate-thesis` trigger (Recurring Claim / Mispricing Signal / Thesis Invalidation / Thesis-Shaped Page Created, per the finance module's `candidate-thesis-triggers.md`) MAY fire from the new evidence — surface it; a `Thesis Invalidation` fire suggests `review` (B3), the other three suggest `thesis` (B1). Surfacing a candidate-thesis is a proposal, never an auto-author — the agent NEVER writes a thesis page from this mode.

State the chain options to the user; do NOT auto-chain without the routing the user confirms (`./capability-manifest.md` § Multi-mode chaining).

---

## Boundaries (this mode)

- Read-only on portfolio/ledger data; position data ONLY through registered read tools (`./investor-loop.md` § Tools-only data access). This mode reads no position data directly.
- Writes ONLY to `raw/` via the `investment_source_capture` tool (which also registers gated/blocked entries in `{wiki_root}/source-queue.md`), to `.user/finance/investor/` own-workspace files (deferred-issue records per § Issue-surfacing; Step 7b extraction-target JSONs), to entity `## Financials` ONLY via the registered `investment_financials_extract` tool (Step 7b — the sole writer of that section), to `metric-vocab.md` ONLY as a user-approved vocab-proposal application (Step 7b.3), to `source-policy.md` § Auto-Capture Pre-Approved Origins ONLY via the Ingest-gate growth prompt (a user-approved policy edit), and to the wiki via `sb-wiki-ingest` run through sub-agents — the agent NEVER hand-writes a raw source file or a wiki page (`./investor-loop.md` § Own-workspace-writes boundary).
- NEVER bypasses a paywall and NEVER uses bank/brokerage credentials — gated sources register `gated_pending_access` only (permanent source boundary in `./investor-loop.md`).
- Never mutates ledgers, `portfolio.json`, or the dashboard. A request to do so, to bypass a paywall, or to hand-write a raw/wiki file is out-of-structure → Rule A in `./investor-loop.md`.
- Every user-facing turn ends at an Investor Checkpoint (`./investor-loop.md` § Per-Step Checkpoint).
