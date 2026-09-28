---
name: sb-wiki-create-concept
description: Create a wiki concept page from a proposed mention. Use when the user expresses intent to create or promote a concept — "create a concept for X", "promote the {slug} concept", "make a concept page about Y", a dashboard dispatch `/sb-wiki-create-concept {slug}`, or any phrasing that asks for a new concept in the wiki from a candidate-mention (slug + seed source). Do NOT use to create entity, topic, or thesis pages — entities use `sb-wiki-create-entity`, topics use `sb-wiki-create-topic`, theses use `sb-fin-create-thesis`. Do NOT use for ingest stub creation — `/sb-wiki-ingest` still writes stubs when the stub rule fires.
---

Read and execute `{sb_os_path}/wiki/workflows/sb-wiki-create-concept/sb-wiki-create-concept.md`.
