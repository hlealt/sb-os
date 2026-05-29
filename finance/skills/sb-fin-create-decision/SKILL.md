---
name: sb-fin-create-decision
description: Create a wiki decision page recording a dated investment action and its reasoning. Use when the user expresses intent to record an investment decision — "record my decision to sell X", "log that I'm holding Y", "write a decision page for passing on Z", or any phrasing that asks to capture a buy/sell/trim/add/hold/pass/reject/pause/review/rebalance call in the wiki. Also invoked by the `investor` agent when the user elects to record a decision the agent reasoned through (B5). Records reasoning only — transaction price/qty live in the bookkeeper ledger, never here. Do NOT use to create thesis, concept, entity, or topic pages — theses are authored by `sb-fin-create-thesis`, and concept/entity/topic pages by `/sb-wiki-ingest` or `sb-wiki-create-topic`.
---

Read and execute `{sb_os_path}/finance/workflows/sb-fin-create-decision/sb-fin-create-decision.md`.
