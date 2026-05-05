---
name: Projects
description: Elicit current bounded efforts and create project folders, indexes, and tasks files.
nextStepFile: step-05-resources.md
---

# Step 04 — Projects

**Goal:** Identify the user's current bounded efforts (with a "done"), then create project scaffolds under `1-projects/`: folder, index, tasks file.

---

## Mandatory Sequence

### 1. Elicit projects via concrete prompts

Don't ask "what are your projects?" cold. Instead, walk through these prompts in order:

| Prompt | What it surfaces |
|--------|------------------|
| "What's a goal you're actively working on right now that has a clear finish line?" | Active personal projects |
| "Anything you're trying to ship or launch in the next 90 days?" | Time-boxed deliverables |
| "Any milestone — move, trip, learn X — you're preparing for?" | Life-event projects |
| "Any work deliverable that's yours to drive end-to-end?" | Work projects |
| "Anything you started but stalled? Worth listing or worth letting go?" | Capture stalled work explicitly |

The user might list 0, 1, or 10. All are fine. If they list 0, skip to step 5 (no projects to create).

For each project named, capture:

- A kebab-case name (verb-led or noun-phrase that implies completion — e.g., `move-apartment`, `q2-launch`, `write-novel-draft-1`)
- One-line description
- Optional: target finish date

### 2. Reality-check the list

If the user lists more than 5 projects, gently ask: "These are all *active* — meaning you're pushing on them this week or next? If some are paused or aspirational, we can leave them out for now. You can add later." Move paused ones to a separate "later" list — do not create folders for those.

### 3. Build the proposal table

| Project | Folder | Index | Tasks |
|---------|--------|-------|-------|
| move-apartment | `1-projects/move-apartment/` | `1-projects/move-apartment/move-apartment.md` | `1-projects/move-apartment/move-apartment-tasks.md` |
| ... | ... | ... | ... |

Project index template:

```markdown
---
tags:
  - {primary-area-tag if any}
---

# {Project title}

{One-line description.}

**Target:** {date or "TBD"}
**Status:** Active

## Notes

(running notes, decisions, links)
```

### 4. Batch-confirm

Show all folders + files about to be created. Ask: "Approve all, or edit?"

### 5. Write — invoke sb-vault-ops

Invoke `sb-vault-ops` skill, follow it exactly, write approved folders and files. Then invoke `sb-vault-integrity` for the post-op sweep.

### 6. Update state

Append created project folder paths to `onboarder_state.projects_created`. Append `"step-04-projects"` to `completed_steps`, set `last_step`. Write `sb-os.json`.

---

## Step Menu

| Option | Action |
|--------|--------|
| [C] Continue | Proceed to step-05-resources.md |
| [?] Ask | Help handler |
| [X] Exit | Stop. State preserved. |

HALT and WAIT for user input.
