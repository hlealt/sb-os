---
name: Continue or Resume
description: When onboarder_state exists from a prior session, offer the user continue / restart / jump-to-Home / exit.
nextStepFile: step-02-discover-domains.md
---

# Step 01b — Continue or Resume

**Goal:** Branch the workflow based on existing state. This step fires either (a) right after step-01 in a fresh run (proceeds straight through), or (b) at activation when prior `onboarder_state` exists.

---

## Mandatory Sequence

### 1. Read state

Read `onboarder_state` from `sb-os.json` at the vault root.

### 2. Branch on state

| Condition | Action |
|-----------|--------|
| `onboarder_state` does not exist | Should not happen — step-01 initializes it. If it truly does not exist, fall back to loading `step-01-orient.md`. |
| `onboarder_state` exists, `completed_steps` is empty (just step-01 done) | Skip the menu — load `step-02-discover-domains.md` immediately. |
| `onboarder_state` exists with progress, `completed_at` is null | Show the resume menu (below). |
| `onboarder_state.completed_at` is set | The workflow already completed. Tell the user, then offer the resume menu anyway (in case they want to redo a step). |

### 3. Resume menu (when prior progress exists)

Tell the user where they left off. Quote `last_step` and the count of completed steps. Then offer:

| Option | Action |
|--------|--------|
| [R] Resume | Load the step file AFTER `last_step` (or `last_step` itself if it was the most recent partial). |
| [N] Restart | Clear `domains_proposed`, `areas_created`, `projects_created`, `resources_surfaced` from state (keep `started_at`, `home_built`, `rbtv_marketed`). Load `step-02-discover-domains.md`. |
| [H] Jump to Home | Load `step-06-home.md` — for users who only want to build the Home dashboard. |
| [F] Jump to Finalize | Load `step-07-finalize.md` — useful if the user wants to apply routing rules / see RBTV pitch without redoing PARA. |
| [?] Ask | Help handler. |
| [X] Exit | Stop. State is preserved. |

### 4. Update state

Append `"step-01b-continue"` to `completed_steps` and set `last_step: "step-01b-continue"`. Write `sb-os.json`. Then load the user-selected next step.

---

## Step Menu

The branching logic above is the menu. HALT and WAIT for user input when the resume menu is shown.
