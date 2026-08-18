---
name: Archivist
description: Document all session work into the rolling work-log file — completed actions, decisions, rejected alternatives, collaborative refinements, discoveries, files read. On runs with no session work to document, sweep done tasks from vault task files into date-correct work logs.
---

Document all work done in this conversation into the work-log file. Capture the substance, not just the actions.

## Instructions

1. **Read the work-log template.** Read `{sb_os_path}/para/templates/work-log.md` for the canonical format and section layout.

2. **Day-rollover.** Run the archivist script (resolve `{sb_os_path}` from `sb-os.json` at the vault root):
   ```
   python {sb_os_path}/para/workflows/sb-archivist/sweep_done_tasks.py --vault-path "." --rollover-only
   ```
   It archives a stale `work-log.md` to `.user/runtime/state/work-log-archive/{its-frontmatter-date}-work-log.md` and creates a fresh today-dated work-log from the template; it is a no-op when the log already carries today's date (you append this session's work to it in steps 4–6). Read its one-line report.

3. **Review the full conversation history.** Scan the entire session and extract:
   - Files read, created, edited, or deleted
   - Decisions made with the user
   - Alternatives considered and rejected (with the trade-off you accepted)
   - Moments where you and the user challenged each other (collaborative refinements)
   - Discoveries — corrections, structural changes, surprises, things you learned
   - Tasks completed, created, or rescheduled

   If the scan finds NO documentable work (fresh session — no files touched, no decisions, no tasks), skip steps 4–6 and run the Done-Task Sweep below instead.

4. **Write to the work-log.** Populate the appropriate section per the template:

   | Section | What goes here | Format |
   |---------|----------------|--------|
   | **Completed** | Tasks the user marked done or that the session finished | `- [x] {action} ✅ YYYY-MM-DD` |
   | **New Tasks Created** | Tasks created or rescheduled during the session | `- {task} → 📅 YYYY-MM-DD in [[{file}]]` |
   | **Updates** | Status changes, pivots, context shifts, topic transitions — narrative prose | Free-form bullets |
   | **Problem Understanding** | What the user articulated as hard / unclear / avoided for each substantive problem worked on, plus the agent's restatement that the user confirmed | `**{Topic}** — {articulation}` followed by quoted restatement |
   | **Key Decisions** | Decisions made with the user — what was decided, what was chosen, why | Table row: `\| decision \| choice \| rationale \|` |
   | **Rejected Alternatives and Trade-offs** | Options that were considered and dropped, with the trade-off accepted by rejecting | Table row: `\| option \| why rejected \| trade-off \|` |
   | **Collaborative Refinements** | User and agent challenged each other, position evolved | Table row: `\| topic \| user position \| agent challenge \| resolution \|` |
   | **Discoveries** | Corrections, structural changes, surprises, lessons | `- YYYY-MM-DD \| {discovery}` |
   | **Files Read** | Files consulted during the session and what was learned | Table row: `\| file \| why \| key insight \|` |

   Update `last_updated` in frontmatter to current timestamp.

5. **Be comprehensive but concise.** Capture every meaningful action and decision — not just big deliverables but also corrections, file operations, pushbacks. One row or one bullet per item. Group related items when a single action touched multiple files.

6. **When appending to an existing work-log**, add new items under the appropriate sections. Do not duplicate items already logged. If a section does not yet exist in the file, create it.

## Done-Task Sweep (fresh-session runs only)

Runs ONLY when step 3 found no documentable session work. Never run both this sweep and steps 4–6 in the same invocation.

Resolve `{sb_os_path}` from `sb-os.json`. Run the sweep in two stages — a check stage that surfaces what would be swept, then a targeted act stage on the files the user chooses.

**Stage 1 — check (always dry-run first).** Run:

```
python {sb_os_path}/para/workflows/sb-archivist/sweep_done_tasks.py --vault-path "." --dry-run --json
```

Read the `sweep.per_source` map — one entry per task file holding done tasks, each with its sweepable count, skipped count, and routed work-log(s). Present these to the user as a numbered list (file → sweepable count → target log). If `per_source` is empty, report "no done tasks to sweep" and stop. Ask which files to sweep: all, or a chosen subset.

**Stage 2 — act (targeted).** Run the chosen subset by passing their vault-relative paths to `--only` (comma-separated, exact paths from `per_source` keys); omit `--only` to sweep all:

```
python {sb_os_path}/para/workflows/sb-archivist/sweep_done_tasks.py --vault-path "." --json --only "1-projects/foo/foo-tasks.md,2-areas/bar/bar-tasks.md"
```

An `--only` path that matches no task file exits 2 with an error — pass paths verbatim from the Stage-1 keys.

Both stages perform day-rollover (idempotent) then the sweep: every top-level `- [x]` task in `*-tasks.md` under `1-projects/` and `2-areas/` (within the chosen scope) is extracted verbatim, routed by its `✅ YYYY-MM-DD` marker (today → `work-log.md`, earlier → `{date}-work-log.md` in the archive), appended under a `### Swept from [[{file-name}]] ({vault-relative-path})` group inside the target's `## Completed` section (deduplicated by task line; missing archive files created with frontmatter + `# Work Log` heading + `## Completed`), and removed from the source. Each block is preserved byte-for-byte, each source file's line endings are kept, and a checked item nested under an open `- [ ]` parent is never swept.

Any remaining task whose `_Depends:_` / `_Done-after:_` pointed at a task just swept has that ref dropped (a swept task is done, so its edge is satisfied) — otherwise `sb-task deps` fails on the whole file. Each drop is listed in `sweep.refs_scrubbed`.

Report the act-stage result in chat in one line: tasks swept, source files cleaned, work-logs written, refs scrubbed (list them if any).

## What NOT to do

- Do NOT summarize in chat — write to the file and confirm what was logged.
- Do NOT skip reading the template — the format is authoritative.
- Do NOT collapse rich content into Updates. If a session had decisions or refinements, populate those tables; do not hide them in narrative bullets.
- Do NOT sweep open (`- [ ]`) tasks or checked sub-items of open tasks.
- Do NOT run the sweep when the session produced documentable work — document the session; done tasks wait for the next fresh run.
