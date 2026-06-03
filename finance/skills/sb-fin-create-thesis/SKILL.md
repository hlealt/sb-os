---
name: sb-fin-create-thesis
description: Persist an investment thesis as a wiki thesis page. Invoked ONLY by the `sb-investor` agent in its investor-orchestrated mode — when `/sb-investor thesis` authors a new thesis the user reasoned through, or when `/sb-investor review` extends an existing thesis. The agent reasons; this skill persists. NEVER auto-fire on standalone user intent ("create a thesis for X") — `/sb-investor thesis` is the sole front door for thesis authoring; route such intent there. Do NOT use to create decision, concept, entity, or topic pages — decisions are authored by `sb-fin-create-decision`, and concept/entity/topic pages by `/sb-wiki-ingest` or `sb-wiki-create-topic`.
---

Read and execute `{sb_os_path}/finance/workflows/sb-fin-create-thesis/sb-fin-create-thesis.md`.
