# Step 08 — Final Verification (Triple Check)

## Purpose

Rigorous cross-verification: plan <-> vault <-> priorities <-> session log. Record the plan in the weekly note. Archive the session log. Process context injection per `sb-workflow-context.md` before proceeding.

## Execution

### 1. Triple Check

Execute the verifications in order:

**a) Plan → Vault**
For each task planned in step 07, verify it exists as `- [ ]` with the correct date in the vault. The expected format follows the `sb-vault-ops` skill (date after checkbox: `- [ ] 📅 YYYY-MM-DD action`).

Build table:
```
| Plan item | Exists? | File | Date |
|-----------|---------|------|------|
| [Plan item] | yes | [area].md | 📅 [date] |
```
If any does NOT have a match → correct immediately.

**b) Priorities → Vault**
For each Must/Should priority defined in step 03, verify it has at least one corresponding `- [ ]`:
```
| Priority (step 03) | Corresponding task? | File |
|--------------------|---------------------|------|
| [Priority A] | yes | [project].md |
| [Priority B] | yes | [area].md |
```
If a priority does NOT have a task → create now.

**c) Session Log → Vault**
Re-read the entire session log. For each item in "Tasks mentioned" and "Items not to forget":
- Was it processed? Does it exist in the vault?
- If NOT → flag and resolve

**d) Axes → Frontmatter**
Verify that the weekly note frontmatter has the axes key filled in (one entry per configured life axis, none empty). The frontmatter key defaults to `axes`. If context YAML provides `frontmatter.axes-key`, verify that key instead. The expected entry count equals the number of axes provided by context injection (`text.life-axes`); if no value is configured, default to seven entries. If missing → ask the user now.

**e) Vault → Plan**
Tasks with a date in the week that are NOT in the plan:
```
These tasks have a date in the week but are not in the daily plan:
- [task] 📅 dd/mm (file.md)
Are they residue from previous planning? Include in plan or reschedule?
```

**f) Inventory → Routing (daily completeness)**
Re-read the "Daily inventory" section of the session log. For each daily, verify that all items were processed in Step 05 (routed, created as task, or captured as review note). If any item was left without a destination → resolve now.

**g) Structural integrity**
1. Verify that NO `type: index` file contains checkboxes (`- [ ]` or `- [x]`). Tasks live ONLY in `*-tasks.md`.
2. Verify that each `*-tasks.md` has `#### Must`, `#### Should`, `#### Could` headings.
3. Duplicate scan: for each area with linked projects, compare tasks between `{area}-tasks.md` and `{project}-tasks.md`. Flag similar tasks (same verb + same subject).

### 2. Intention vs. load contrast

Before recording the plan, contrast what the user said mattered (Step 03) with what ended up in the week.

**Execution:**
1. Retrieve Step 03 intentions (Must and Should from weekly note, week-intention section)
2. List all `- [ ]` tasks with a date in the planned week that exist in the vault
3. Present side by side:

```
## What you said mattered (Step 03)
Must: [list]
Should: [list]

## What ended up in your week (vault)
[table: task | date | file | aligned with which intention?]

Tasks with no clear link to any intention:
- [task] — [file]
```

4. Ask: "Is there anything here that doesn't serve these intentions? Want to defer, cut, or keep anyway?"
5. Execute the cuts/deferrals the user decides (remove date or move to Could/backlog)

**Why this step exists:** A common pattern is task accumulation during planning. This final checkpoint ensures the week reflects the intentions, not the noise of the process.

### 3. Record plan in the weekly note

Write the daily plan in the weekly note using simple bullets (NO checkboxes) with `[[links]]`:

```markdown
## Daily plan

### Monday dd
- Task A → [[project-file]]
- Task B → [[area-file]]
- **HH:mm: Meeting X**

### Tuesday dd
...
```

**IMPORTANT:** Do NOT use `- [ ]` in the weekly note. The note is a map with links. Actual tasks live in the project/area files.

### 4. Completed task cleanup

Search for all `- [x]` in the `{name}-tasks.md` files of areas and projects. Delete the completed ones (git preserves history). Present summary.

### 5. File verification by folder

For each folder in `1-projects/`, `2-areas/`, `3-resources/`:
1. List `.md` files in the folder (excluding `CLAUDE.md`, the index and the `*-tasks.md`)
2. Read the files-listing table inside the folder's index file. Default heading: `## Files`. If context YAML provides `section.files-table.heading`, use that heading instead.
3. Compare: files in folder vs rows in table

```
| Folder | Files | In table | Discrepancies |
|--------|-------|----------|---------------|
| folder-1/ | N | N | OK |
| folder-2/ | N | N | OK |
```

If there are discrepancies → correct the files-listing table in the index file immediately (add missing files, remove references to deleted files).

### 6. Orphan detection

Resolve the orphan-detection script path. Default `3-resources/tools/sb-os/workflows/sb-life-planner/weekly-review/orphan-detection.py`. If context YAML provides `path.script.orphan-detection`, use that value instead.

Run the detection script:
```bash
python {orphan-detection-path} --vault-path "." --json
```

If `count > 0`: present list grouped by folder. For each orphan, ask the user:
- **Link** — add `[[link]]` in the `{name}-tasks.md` or appropriate parent file
- **Archive** — move to `4-archives/`
- **Ignore** — legitimate file without backlinks (e.g.: external references)

If `count == 0`: report in the final summary as `No orphan files`.

### 7. Cleanup and finalization

- Delete the agent-notes section from the weekly note (heading prefix from `section.agent-notes.heading`, default `Agent notes`; the section was created in step 03 with the `(steps 01–03)` suffix and extended in step 05). Temporary scaffolding, no longer needed.
- Add `reviewed` and `routed` tags to the weekly note
- Update `last-weekly-review` in the user state file. Default path `.user/state/reviews.md`. If context YAML provides `path.state.reviews`, use that value instead. If the file does not exist, skip silently.
- Remove `stepsCompleted`, `closingWeek`, `planningWeek` from frontmatter (session continuity fields)

### 8. Archive session log

1. Re-read session log one last time — check if anything is still pending
2. If everything was processed → move to the archive path. Default `0-periodic-notes/weekly/archive/{week}-session-log.md`. If context YAML provides `path.weekly.session-log-archive`, use that value instead.
3. If something is still pending → inform the user before archiving

### 9. Present final summary

```
Weekly review complete.

Week closed: Wnn (dd/mm-dd/mm)
Week planned: Wnn+1 (dd/mm-dd/mm)

Tasks planned: X (Y created, Z updated)
Review items deferred: W
Chronic stragglers handled: N
Backlog without date: V

Verifications:
- Plan → Vault: all tasks exist
- Priorities → Vault: all priorities have a task
- Session Log → Vault: all items processed
- Axes → Frontmatter: all axes filled
- Vault → Plan: no residual tasks
- Inventory → Routing: all dailies 100% processed
- CLAUDE.md per folder: all updated
- Orphans: no files without backlinks

Session log archived at: archive/{week}-session-log.md
Weekly note: {weekly-note-path}
```

## Menu

```
→ [D] Done — review complete
→ [R] Re-verify (run triple check again)
→ [F] Fix — correct a specific task
```
