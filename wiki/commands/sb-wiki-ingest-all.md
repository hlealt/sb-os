---
name: sb-wiki-ingest-all
description: 'Backfill the wiki: ingest every non-ingested raw source via one sub-agent per source (Sonnet for small sources, Opus for sources at or above 5k tokens), run strictly sequentially, then lint. A bare large/small keyword scopes the run by size.'
---

Read and execute `{sb_os_path}/wiki/workflows/sb-wiki-ingest-all/sb-wiki-ingest-all.md`.
