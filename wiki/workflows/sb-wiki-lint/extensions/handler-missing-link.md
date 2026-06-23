# Lint Step 9 handler — MISSING-LINK PROPOSAL (signal-1 prose-mention)

> **Loaded by** `sb-wiki-lint.md` Step 9 ONLY when the `missing_links` proposal set is non-empty. Paths below are relative to THIS file's location (`wiki/workflows/sb-wiki-lint/extensions/`). Full convention: schema § "Missing-link convention (`related:` cross-links)".

The proposals are signal-1, report-only detections (a target page's exact name appears as UNLINKED prose in the source page where a page by that name exists). NEVER auto-link — apply ONLY accepted rows, append-only, both directions. The MISSING-LINK PROPOSAL set is the MAIN list from `detected.missing_links` (multi-word targets only); the rows below are numbered against that MAIN list.

User response handling for MISSING-LINK PROPOSAL (step 7.8):

| Response | Behavior |
|----------|----------|
| `accept all` | Build a plan of ALL MAIN proposal rows as `{source, target}` (`source` = the row's source file wiki-root-relative path; `target` = the bare `target.md` filename) and run `python {sb_os_path}/wiki/scripts/sb-wiki-lint-deterministic.py update-links --plan <plan.json>` from the vault root. It appends `[[target]]` to the source page's `related:` AND `[[source]]` to the target's `related:` — append-only, idempotent. Then read the returned `applied` / `skipped` / `errors` and resolve every `errors` entry. No log entry. |
| `accept N` (e.g. `accept 1,2`) | Plan + apply the listed rows only. Others defer. |
| `reject N` (e.g. `reject 3`) | For EACH rejected row, append a row to `{wiki_root}/missing-links-rejected.md` (create the file with header `\| term \| proposed-link \|` if absent) recording `\| <term> \| [[<target>]] \|` so the pair is suppressed on every future lint run. Apply nothing. |
| `defer` (default) | No write; proposals persist in `missing-links.md` and re-surface next lint run. |

**Single-token-hub suppressed rows (ADX-7).** The MAIN list is multi-word-target only. Single-token-target rows (`ai.md`, `llm.md`, …) are held out into the report file's "Single-token-hub suppressed" section (`detected.missing_links_hub_suppressed`) and are NOT presented as numbered rows here — they are low-precision (a common word matches in most pages). To apply ONE genuine hub link, the owner promotes it manually: hand-build a `{source, target}` plan row for it and run `update-links --plan` as above. Never bulk-accept the suppressed section.
