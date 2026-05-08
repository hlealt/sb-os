# Proactive Fix

Same-file fix scope for explicit one-file cleanup or when `sb-vault-integrity` is already active for a structural mutation.

This reference is NOT an invocation trigger. Ordinary edits to existing routed files must not invoke `sb-vault-integrity` just to scan for possible cleanup.

## Verifiable (auto-fix in the same edit)

| Class | Examples |
|-------|----------|
| Filename pattern | `yyyy-mm-dd-*` for daily, `yyyy-Wnn` for weekly, area task file `{name}-tasks.md` |
| Frontmatter schema | Missing `type:`, missing required area tag |
| Format pattern | Task line missing `📅` or starting verb (per the `sb-vault-ops` workflow's `data/tasks.md`) |
| Broken wikilink | `[[Target]]` where target file does not exist |
| Stale folder reference | Path to a folder that has been deleted or renamed |
| Stale rule reference | `.claude/rules/{name}.md` path where the file no longer exists at that name |
| Duplicate content | Same list/table repeated within the file with no functional difference |

## Subjective (flag, do not fix)

| Class | Examples |
|-------|----------|
| Style judgment | "Verbose", "could be leaner", "tone unclear" |
| Categorization | "This task should be Should not Must" |
| Routing | "This file might fit better in another folder" |
| Rule interpretation | When the rule's wording allows multiple readings |

For subjective issues: state the observation in the response and ask the user before changing anything.

## Scope Rules

| Rule | Detail |
|------|--------|
| Same file only | Never propagate fixes to other files in the same operation. Reference sweeps fire only on rename/move/delete (separate trigger). |
| No content deletion | Never delete user content under "fix" pretext (e.g., completed tasks, old notes, draft entries) |
| Surgical | Fix only the specific violation. Never refactor unrelated content in the same edit. |
| Size cap | If a fix would touch >5 lines, ask first |
| Disclose every fix | List each applied fix in the response: rule + change. The user must see what was changed beyond their request. |
| Skip if uncertain | If a violation is plausible but not verifiable from explicit rule wording, flag it instead of fixing |
