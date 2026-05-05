---
name: Areas
description: Convert the confirmed domain list into area folders, indexes, and tasks files. Write only after batch confirmation.
nextStepFile: step-04-projects.md
---

# Step 03 — Areas

**Goal:** For each domain in `onboarder_state.domains_proposed`, create the standard area scaffold under `2-areas/`: a folder, an index file, and a tasks file. Batch-confirm before writing.

---

## Mandatory Sequence

### 1. Build the proposal table

For every domain in `onboarder_state.domains_proposed`, render a row:

| Domain | Folder | Index file | Tasks file |
|--------|--------|------------|-----------|
| finance | `2-areas/area-finance/` | `2-areas/area-finance/area-finance.md` | `2-areas/area-finance/area-finance-tasks.md` |
| health | `2-areas/area-health/` | `2-areas/area-health/area-health.md` | `2-areas/area-health/area-health-tasks.md` |
| ... | ... | ... | ... |

Naming convention: `area-{domain}` for the folder and the index/tasks file basenames.

If the user already used a different name pattern earlier (e.g., they said "I want it called `finance` not `area-finance`"), respect their preference but flag it: "sb-os convention is the `area-` prefix for the directory under `2-areas/` — you can break it but cross-cutting tags assume the bare domain name."

### 2. Show the index file template

Each area index will be created with this minimal template (adapt per domain):

```markdown
---
tags:
  - {domain}
---

# {Domain title}

Ongoing responsibility. {One-line description elicited from the user, or a reasonable default.}

## Sub-areas

(empty — populate as you create sub-folders)

## Active

(notes, decisions, links currently in play)
```

Each tasks file:

```markdown
---
tags:
  - {domain}
---

# {Domain title} — Tasks

- [ ] (add tasks scoped to this area)
```

Show one fully-resolved example to the user.

### 3. Elicit one-line descriptions

For each area, ask: "One line — what does this area cover for you?" Accept short answers; offer a default ("e.g., 'money in, money out, investments, taxes'") if the user is stuck.

Capture descriptions into the proposed file contents.

### 4. Batch-confirm

Show the full list of files about to be created:

```
About to create:
  2-areas/area-finance/                      (folder)
  2-areas/area-finance/area-finance.md       (index, with description)
  2-areas/area-finance/area-finance-tasks.md (tasks)
  2-areas/area-health/                       (folder)
  ...
```

Ask: "Approve all, or call out specific edits?"

### 5. Write — invoke sb-vault-ops

This is a vault content operation. Invoke the `sb-vault-ops` skill before writing and follow it exactly. Then write all approved folders and files.

After writing, run a structural sweep — invoke the `sb-vault-integrity` skill to verify nothing else broke.

### 6. Update state

For each area created, append the folder path to `onboarder_state.areas_created`. Append `"step-03-areas"` to `completed_steps`, set `last_step`. Write `sb-os.json`.

---

## Step Menu

| Option | Action |
|--------|--------|
| [C] Continue | Proceed to step-04-projects.md |
| [?] Ask | Help handler |
| [X] Exit | Stop. State preserved. |

HALT and WAIT for user input.
