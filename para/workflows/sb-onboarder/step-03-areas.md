---
name: Areas
description: Convert the confirmed domain list into area folders and indexes; create a tasks file only for areas with elicited tasks. Write only after batch confirmation.
nextStepFile: step-04-projects.md
---

# Step 03 — Areas

**Goal:** For each domain in `onboarder_state.domains_proposed`, create the standard area scaffold under `2-areas/`: a folder and an index file. A tasks file is created ONLY for areas where the user names at least one pending task — never preemptively (dashboards discover task files; empty ones only add noise). Batch-confirm before writing.

---

## Mandatory Sequence

### 1. Build the proposal table

For every domain in `onboarder_state.domains_proposed`, render a row:

| Domain | Folder | Index file |
|--------|--------|------------|
| finance | `2-areas/area-finance/` | `2-areas/area-finance/area-finance.md` |
| health | `2-areas/area-health/` | `2-areas/area-health/area-health.md` |
| ... | ... | ... |

Naming convention: `area-{domain}` for the folder and the index file basename. Tasks files (`area-{domain}-tasks.md`) are NOT part of the default scaffold — step 3 below adds one per area only when the user names pending tasks for it.

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

Show one fully-resolved example to the user.

### 3. Elicit descriptions and pending tasks

For each area, ask two things:

1. "One line — what does this area cover for you?" Accept short answers; offer a default ("e.g., 'money in, money out, investments, taxes'") if the user is stuck.
2. "Any pending to-dos in this area right now? Name them — or say 'none'."

Capture descriptions into the proposed index contents.

For each area where the user named at least one task, propose `area-{domain}-tasks.md` with this template (tasks without a stated deadline go under `Should`; tasks with one get `📅 YYYY-MM-DD` after the checkbox):

```markdown
---
type: tasks
tags:
  - {domain}
---

#### Must

#### Should

- [ ] {elicited task}

#### Could
```

Areas with no named tasks get NO tasks file. Tell the user: "No tasks file for {domain} — it's created automatically when your first task for it lands."

### 4. Batch-confirm

Show the full list of files about to be created — tasks files appear ONLY for areas with elicited tasks:

```
About to create:
  2-areas/area-finance/                      (folder)
  2-areas/area-finance/area-finance.md       (index, with description)
  2-areas/area-finance/area-finance-tasks.md (tasks — 2 elicited)
  2-areas/area-health/                       (folder)
  2-areas/area-health/area-health.md         (index, with description)
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
