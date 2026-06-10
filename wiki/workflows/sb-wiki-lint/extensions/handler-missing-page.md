# Lint Step 9 handler — MISSING-PAGE PROPOSAL (broken-link bucket B)

> **Loaded by** `sb-wiki-lint.md` Step 9 ONLY when the broken-link bucket-B proposal set is non-empty. Paths below are relative to THIS file's location (`wiki/workflows/sb-wiki-lint/extensions/`).

User response handling for MISSING-PAGE PROPOSAL (broken-link bucket B, step 5):

| Response | Behavior |
|----------|----------|
| `accept all` | For EACH accepted target, invoke `rbtv-web-searching` to verify what the concept/entity actually is (one authoritative source), then author a stub per `../../shared/stub-policy.md` + `../../shared/frontmatter-schemas.md` at `wiki/concepts/{slug}.md` or `wiki/entities/{slug}.md` (matching `kind:` subfolder per the type folder's `CLAUDE.md` routing). A 1–2 sentence definition lead line + a `## Sources` section with the citation. After authoring, run `python {sb_os_path}/wiki/scripts/sb-wiki-fill-index-descriptions.py --apply` to add each stub's leaf-index Description row. NEVER invent a definition. No log entry — the page is the record. |
| `accept N` (e.g. `accept 1,2`) | Author the listed stubs only. Others defer. |
| `reject` | All defer; targets re-surface next lint run. |
| `defer` (default) | Same as `reject` for this run. |
