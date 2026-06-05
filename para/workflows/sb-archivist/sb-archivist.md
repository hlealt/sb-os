---
name: Archivist
description: Document all session work into the rolling work-log file — completed actions, decisions, rejected alternatives, collaborative refinements, discoveries, files read. On runs with no session work to document, sweep done tasks from vault task files into date-correct work logs.
---

Document all work done in this conversation into the work-log file. Capture the substance, not just the actions.

## Instructions

1. **Read the work-log template.** Read `{sb_os_path}/para/templates/work-log.md` for the canonical format and section layout.

2. **Check today's work-log.** Read `.user/runtime/state/work-log.md`:
   - If the `date` in frontmatter matches today → append to it (do NOT overwrite existing content).
   - If the `date` is older than today → move (`mv`) the stale file to `.user/runtime/state/work-log-archive/{YYYY-MM-DD}-work-log.md` (using the date from its frontmatter), then create a fresh work-log file from the template. Do NOT use `cp` + overwrite.
   - If the file does not exist or is empty → create a fresh work-log file from the template.

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

Runs ONLY when step 3 found no documentable session work. Never run both this sweep and steps 4–6 in the same invocation. Day-rollover handling (step 2) MUST already have run.

1. **Find done tasks.** Content-search `1-projects/` and `2-areas/` for `- [x]` lines in files matching `*-tasks.md`. NEVER conclude task files are absent from a single empty glob result — verify with a content search or directory listing.

2. **Extract verbatim blocks.** A swept block = the top-level `- [x]` line plus ALL its indented continuation lines (sub-bullets, `_Goal_`/`_Context_`/`_Review_` annotations). Preserve blocks exactly — never reformat, summarize, or trim. A checked item nested under an open (`- [ ]`) parent belongs to that open task — do NOT sweep it.

3. **Route by completion date.** Read the `✅ YYYY-MM-DD` marker on the task line:
   - Earlier than today → `.user/runtime/state/work-log-archive/{YYYY-MM-DD}-work-log.md`
   - Today, missing, or malformed → today's `.user/runtime/state/work-log.md`

4. **Create missing archive files.** If a target archive file does not exist, create it with frontmatter (`date: {YYYY-MM-DD}`, `last_updated`), the `# Work Log — {YYYY-MM-DD}` heading, and a `## Completed` section.

5. **Append grouped and deduplicated.** Inside the target's `## Completed` section, group blocks under `### Swept from [[{file-name}]] ({vault-relative-path})`. If the task line is already logged in the target, skip the append — but still remove it from the source.

6. **Remove from source.** Delete each swept block from its task file. Touch nothing else — open tasks, headings, and section structure stay untouched.

7. **Update state and report.** Update `last_updated` in every touched work-log's frontmatter. Report in chat in one line: tasks swept, source files cleaned, work-logs written.

## What NOT to do

- Do NOT summarize in chat — write to the file and confirm what was logged.
- Do NOT skip reading the template — the format is authoritative.
- Do NOT collapse rich content into Updates. If a session had decisions or refinements, populate those tables; do not hide them in narrative bullets.
- Do NOT sweep open (`- [ ]`) tasks or checked sub-items of open tasks.
- Do NOT run the sweep when the session produced documentable work — document the session; done tasks wait for the next fresh run.
