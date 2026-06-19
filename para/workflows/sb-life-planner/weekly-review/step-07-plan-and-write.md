# Step 07 — Plan and Write (Batch)

## Purpose

Propose the entire week's plan at once, adjust in batch with the user, and write everything to the vault after confirmation. When this step ends, the Home is already 100% correct. Context injection loads automatically via the hook.

## Fundamental rule

**Complete view before decision.** The user sees the entire week as a table before confirming anything. This prevents the last days of the week from receiving less attention due to decision fatigue.

## Execution

### 1. Build the full week proposal

Using context from previous steps, build complete table:

| Day | Task | Area/Project | MoSCoW | Status |
|-----|------|--------------|--------|--------|
| Day 1 dd | [Meeting with stakeholder] | [project] | Must | already exists |
| Day 1 dd | [Review proposal] | [area] | Must | new |
| Day 2 dd | [Research task] | [area] | Should | reschedule |
| ... | ... | ... | ... | ... |
| Day 6 dd | Buffer / overflow | — | — | — |

**Inputs for building the table:**
- Must/Should priorities from step 03 (intentions)
- Meetings/events from step 04 (calendar)
- Overdue tasks, review items and stragglers handled in step 06
- Tasks created by routing in step 05
- Logical dependencies (e.g.: preparation before a meeting)

**Distribution rules:**
- Must before Should on each day
- Meetings/fixed events as day anchors
- Realistic maximum tasks per day (consider time-consuming events)
- Buffer on the second-to-last or last day for overflow
- Habits as separate intentions (not as tasks)

### 2. Present to the user

```
## Proposal — Week Wnn+1 (dd/mm–dd/mm)

| Day | Task | Area | MoSCoW | Status |
|-----|------|------|--------|--------|
| ... | ... | ... | ... | ... |

Summary: X tasks (Y Must, Z Should)
Fixed events: W meetings
Buffer: [day]

Week habits/intentions: [examples — drawn from what the user defined in step 03 and any habit metrics agreed in step 06]

Adjustments? You can:
- Move tasks between days
- Add or remove tasks
- Change priorities
- Adjust buffer
```

The "Week habits/intentions" line surfaces the user's own habit/intention shorthand from step 03 — never invent illustrative content here.

### 3. Adjust in batch

Process all user adjustments at once. If needed, present updated table for re-confirmation. Repeat until the user confirms.

### 4. Write everything to the vault

After final confirmation, process ALL tasks at once:

**For each task in the confirmed table:**

| Status | Action |
|--------|--------|
| **new** | Create `- [ ]` in the correct `{name}-tasks.md`, following the `sb-vault-ops` skill (tasks path) |
| **already exists** | Check date. If it needs to change → edit in-place |
| **reschedule** | Edit date + add/increment sub-bullet `_Rescheduled Nx (origin: 📅 original-date)_` |

**For tasks with `_Review:_` that were planned:**
- Remove `_Review:_` sub-bullet
- Update date to the planned day

**For tasks with `_Review:_` that were deferred:**
- Update date to the last day of the NEXT week
- Update sub-bullet: `_Review:_ prioritize in Wnn+1 closing / Wnn+2 planning`

### 5. Present write summary

```
Vault write completed:

| Action | Task | File |
|--------|------|------|
| Created | [New task] 📅 [date] | [area].md |
| Updated | [Existing task] 📅 [date] | [area].md |
| Rescheduled | [Task] 📅 [date] (2x) | [project].md |
| ... | ... | ... |
```

### 6. Reconcile with session log

Re-read the entire session log. For each "Task mentioned" that has not been covered in the plan:

```
The session log has these items that didn't make it into the plan:
- [item] — mentioned in step X
Include in a day, add to backlog, or discard?
```

Resolve each item before advancing.

7. Update `stepsCompleted`

## Menu

```
Plan written to vault: X tasks across Y days (Z created, W updated, V rescheduled).

→ [C] Continue to Step 08 (Final verification)
→ [X] Pause review
```
