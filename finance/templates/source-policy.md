---
type: reference
tags: [finance, investor, policy]
---

# Source Policy

> [!note] User-Owned Content
> This file is user-owned. The `sb-investor` agent reads it before source discovery, capture, or weighing (per `finance/CLAUDE.md` § Policy Read-Rules) and changes it only via the policy mode (present-and-confirm). This skeleton was bootstrapped by the sb-os installer — fill the `_Fill in_` slots; the installer never overwrites this file.

---

## Hard Invariant (non-negotiable)

The agent operates under these constraints regardless of any user configuration:

- **Legitimate user access only** — never bypass paywalls or access controls.
- **News/research-portal credentials** — used only with explicit user approval for each credential.
- **Financial-account credentials (bank, brokerage)** — **never used** under any circumstances.

---

## Capture User-Agent

The `investment_source_capture` tool sends this UA on every fetch (`--user-agent`). Fair-access endpoints (SEC EDGAR) 403 non-contact UAs — keep this contact-bearing (name + email).

```
_Fill in: Your Name your-email@example.com_
```

---

## Source Trust Tiers

**Trust class** = the tier number (1–4). Every discovered candidate, captured raw file, and weighed wiki source carries one, derived from its ORIGIN (the publisher) — never from how convincing the individual piece reads.

**Assignment procedure (deterministic):**

1. Match the origin against the § Named-Origin Map below — the map wins.
2. Unmapped origin → classify by the tier criteria.
3. Uncertain between two tiers → take the LOWER trust (the higher number). NEVER assign tier 1–2 to an unmapped origin unless it unambiguously meets the criteria.
4. Publisher cannot be established at all → tier 4.

| Tier | Name | Criteria (for unmapped origins) |
|------|------|--------------------------------|
| 1 | Primary / Official | Regulator-filed or regulator-published documents (securities regulators, central banks, statistical agencies); official company IR documents (filings, shareholder letters, earnings releases); primary datasets and registries. Legally accountable or origin-of-record for the facts they state. |
| 2 | Trusted Analysis | Institutional research with named accountable authors: major consulting/research houses; established independent analysts with a track record the user trusts (named in the map); peer-reviewed or widely-cited academic papers. |
| 3 | Established Press | Professional newsrooms and trade press with editorial standards; established industry publications and podcasts; primary-party communications NOT regulator-filed (company blogs, PR, founder/executive essays); data vendors without independently-verified methodology. |
| 4 | Unverified | Everything else: unknown blogs and newsletters, forums and social posts, anonymous or AI-generated content, aggregator scrapes, retail-content sites with weak provenance. BELOW the evidence bar (§ Allowed-Use Rules). |

### Named-Origin Map

Tier assignments for known origins (`raw/{origin}/`). The user owns this map — promote/demote via the policy mode. New origins enter by criteria; add a row here once recurring.

| Origin | Tier | Note |
|--------|------|------|
| _Fill in — one row per recurring origin_ | | |

Not origins (never weighed as external evidence): _Fill in — list `raw/` folders that hold your own synthesis, assets, or unrouted holding content._

---

## Allowed-Use Rules

**The trust bar sits between tiers 3 and 4.** Tiers 1–3 are evidence-grade; tier 4 (or unclassifiable) is **below the bar** — "fails the `source-policy` trust bar" in the investor workflows means exactly this.

| Tier | Capture gating | Evidence use |
|------|----------------|--------------|
| 1 | Origins listed in § Auto-Capture Pre-Approved Origins capture zero-touch — the allowlist, not the tier, is the key; all other tier-1 origins propose-first. | May stand as SOLE support for factual claims. Invalidation criteria and thesis-critical claims may rest on tier 1 alone. |
| 2 | Propose-first. | Primary analytical support. Thesis-critical claims and invalidation criteria carry tier 1–2 backing. |
| 3 | Propose-first. | Corroboration and context. A thesis-critical claim resting ONLY on tier 3 is flagged at review (deferrable issue). A primary-party communication is authoritative for the bare fact of its own statement ("X announced Y"), promotional for everything else. News is evidence, not a thesis. |
| 4 | Propose-first; the candidate row arrives FLAGGED `4 — below evidence bar` in the Step 4 Propose table. Capturing it is the user's explicit, eyes-open call. | NEVER sole support for any claim. Reliance on a tier-4 source in thesis/review reasoning = BLOCKING issue (investor-loop § Issue-surfacing). A tier-4 lead is a search target: hunt the tier 1–2 source behind it. |

**Ranking (research.md Steps 3/7a):** relevance to the anchor dominates; trust class breaks ties — between candidates of comparable relevance, the lower tier number ranks first.

**Gating (research.md Step 4):** below-bar candidates arrive flagged in the Propose table — that flag IS the issue-surfacing for discovery candidates; the user decides at the checkpoint. No separate inline stop per flagged row.

**Weighing (review.md / thesis.md):** the evidence-use rules above bind whenever a source backs a claim; below-bar reliance is blocking.

**Recency:** no recency rules here — staleness is `review`'s machinery (`last_reviewed`, horizon cadence), not a source-trust property.

---

## Auto-Capture Pre-Approved Origins

Standing capture pre-approval. `/sb-investor research` captures a discovered candidate from a listed origin WITHOUT the per-run propose→approve checkpoint — zero-touch capture; ingest still stops once at the Ingest gate. A row here IS the user's approval, granted in advance. Match semantics and the runtime branch live in `research.md` Step 4 (deterministic `https` dot-boundary URL-host match; relevance bar retained; agent-judged tier NEVER triggers).

| Origin | Host pattern(s) | Added | Note |
|--------|-----------------|-------|------|
| _Fill in — one row per pre-approved origin_ | | | |

- Intended for tier-1 primary/structured origins; the growth prompt MAY add others — always the user's explicit, per-origin call.
- The agent NEVER adds, edits, or removes a row on its own initiative — changes happen ONLY via the policy mode or the research Ingest-gate growth prompt, both user-approved. Mirrors the watchlist invariant.

**Declined origins (growth prompt never re-offers):** —

---

## Gated-Source Policy

- A gated source (paywall / login / IR portal / broker portal) is NEVER fetched — it registers as `gated_pending_access` via the capture tool's `--gated` path (research.md Step 6).
- **Never bypass a paywall or access control. Never use bank/brokerage credentials** (Hard Invariant above).
- Manual bridge: the USER fetches the page by their own legitimate means and provides a local file; the agent saves it via the capture tool's `--mode manual --manual-file <path>` — the tool stays the sole writer.
