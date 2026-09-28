---
name: sb-wiki-create-entity
description: Create a wiki entity page from a proposed mention. Use when the user expresses intent to create or promote an entity — "create an entity for X", "promote the {slug} entity", "make an entity page about Y", a dashboard dispatch `/sb-wiki-create-entity {slug}`, or any phrasing that asks for a new entity in the wiki from a candidate-mention (slug + seed source). Do NOT use to create concept, topic, or thesis pages — concepts use `sb-wiki-create-concept`, topics use `sb-wiki-create-topic`, theses use `sb-fin-create-thesis`. Do NOT use for ingest stub creation — `/sb-wiki-ingest` still writes stubs when the stub rule fires.
---

Read and execute `{sb_os_path}/wiki/workflows/sb-wiki-create-entity/sb-wiki-create-entity.md`.
