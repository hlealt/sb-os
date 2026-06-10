# Lint Step 9 handler — GRADUATION PROPOSAL (mature `questions.md` entries)

> **Loaded by** `sb-wiki-lint.md` Step 9 ONLY when the `graduation-proposals` set is non-empty (which requires the questions layer ON). Paths below are relative to THIS file's location (`wiki/workflows/sb-wiki-lint/extensions/`).

User response handling for GRADUATION PROPOSAL (mature `questions.md` entries, step 7.7b):

| Response | Behavior |
|----------|----------|
| `accept all` | For EACH proposed entry, **invoke the `sb-wiki-create-topic` skill** with the entry's question + accreted `answer:` content + `relates:` targets as the proposed topic. The skill carries its OWN `extend N` (fold into an existing topic) / `new` (create a new page) overlap check and writes the page — lint NEVER authors a page directly. The graduated entry is NOT removed here; step 8 prunes it on the next lint run once the page exists (resolution = page exists). No log entry. |
| `accept N` (e.g. `accept 1,2`) | Invoke `sb-wiki-create-topic` for the listed entries only, exactly as `accept all` above. Other entries defer. |
| `reject` | All entries defer; the answered entries persist in `questions.md` and re-surface as GRADUATION PROPOSAL rows next lint run. |
| `defer` (default) | Same as `reject` for this run; mature entries re-surface in subsequent runs until graduated or retired. |

**Graduation NEVER auto-authors.** A page is created ONLY by `sb-wiki-create-topic` on explicit user accept. Lint proposes; the skill authors. This preserves the schema rule "Agent NEVER auto-creates topic pages" (`../../../docs/wiki-schema.md` § "Topic page" and "Questions layer — questions.md" → Lifecycle).
