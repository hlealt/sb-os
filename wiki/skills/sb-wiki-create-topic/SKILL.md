---
name: sb-wiki-create-topic
description: Create a wiki topic page from a candidate or freshly-proposed topic. Use when the user expresses intent to create or promote a topic — "create a topic for X", "promote the {candidate} topic", "promote the {slug} candidate", "make a topic page about Y", or any phrasing that asks for a new topic in the wiki. Also invoked mid-ingest by `/sb-wiki-ingest` Stage 1 acceptance and by `/sb-wiki-query` Step 7 when the user files a query answer back as a Topic. Do NOT use to create concept or entity pages — those are created by `/sb-wiki-ingest` stub rules or written directly by `/sb-wiki-query` Step 7b file-back.
---

Read and execute `{sb_os_path}/wiki/workflows/sb-wiki-create-topic/sb-wiki-create-topic.md`.
