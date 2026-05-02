---
name: Archivist
description: Document all session work into the rolling work-log file — completed actions, decisions, rejected alternatives, collaborative refinements, discoveries, files read.
---

Document all work done in this conversation into the work-log file. Capture the substance, not just the actions.

## Instructions

1. **Read the work-log template.** Read `{sb_os_path}/templates/work-log.md` for the canonical format and section layout.

2. **Check today's work-log.** Read `.user/state/work-log.md`:
   - If the `date` in frontmatter matches today → append to it (do NOT overwrite existing content).
   - If the `date` is older than today → move (`mv`) the stale file to `.user/state/work-log-archive/{YYYY-MM-DD}-work-log.md` (using the date from its frontmatter), then create a fresh work-log file from the template. Do NOT use `cp` + overwrite.
   - If the file does not exist or is empty → create a fresh work-log file from the template.

3. **Review the full conversation history.** Scan the entire session and extract:
   - Files read, created, edited, or deleted
   - Decisions made with the user
   - Alternatives considered and rejected (with the trade-off you accepted)
   - Moments where you and the user challenged each other (collaborative refinements)
   - Discoveries — corrections, structural changes, surprises, things you learned
   - Tasks completed, created, or rescheduled

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

## What NOT to do

- Do NOT summarize in chat — write to the file and confirm what was logged.
- Do NOT skip reading the template — the format is authoritative.
- Do NOT collapse rich content into Updates. If a session had decisions or refinements, populate those tables; do not hide them in narrative bullets.
