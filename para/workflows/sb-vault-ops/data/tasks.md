# Tasks

Canonical rule for creation, format, routing, and lifecycle of tasks in the vault.

## Main Line Format

```
- [ ] 📅 YYYY-MM-DD Verb + concise action
```

| Rule | Detail |
|------|--------|
| Checkbox first | `- [ ]` or `- [x]` |
| Date after checkbox | `📅 YYYY-MM-DD` — mandatory with deadline. No date = backlog |
| Action starts with verb | "Close", "Write", "Review", "Configure" |
| Max ~60 chars | Use sub-bullet for explanation |

Completion: `- [x] 📅 2026-03-31 Close design partner ✅ 2026-04-01` — keep original `📅`, add `✅ YYYY-MM-DD`.

## Sweep Contract (the archivist Done-Task Sweep keys on this)

The `sb-archivist` Done-Task Sweep (`sweep_done_tasks.py`) moves completed tasks out of `*-tasks.md` into the work-log and REMOVES them from source. Because it deletes from source, it routes a block ONLY when it can do so with confidence; on ANY doubt it SKIPS the block (leaves it byte-for-byte in source, never writes it to a work-log) and logs the reason. To be swept, a completed task MUST satisfy this contract:

| # | Rule | A block that violates it is |
|---|------|-----------------------------|
| 1 | The task line starts at **column 0** with `- [x] ` (a leading space → indented child, never a top-level task). | Not a sweep target — an indented `- [x]` under an open parent is never swept. |
| 2 | The task line carries a completion marker `✅ YYYY-MM-DD` with a **single space** after `✅` and a **zero-padded, calendar-valid** date (`✅ 2026-04-01`, never `✅2026-04-01`, `✅ 2026-4-1`, or `✅ 2026-13-40`). | **Skipped + logged** (no valid date / invalid date). |
| 3 | The task line carries **exactly one** distinct `✅` date. Two or more different `✅` dates on one line is ambiguous. | **Skipped + logged** (multiple distinct dates). |
| 4 | The source file is valid UTF-8. | **Skipped whole + logged** (unreadable source). |

Trailing prose after the date is allowed (`✅ 2026-04-01 — note…`) and does NOT block the sweep. The block body is every following line up to the next column-0 `- [` or heading — sub-bullets travel with the task verbatim.

**Author takeaway:** a completed task with no `✅` date, or a malformed/ambiguous one, will NOT be swept and WILL be reported as a skip — it stays in the file until corrected. This is intentional: it guarantees the sweep can never move or drop content it cannot route. Column-0 `- [x]` checklist items that are NOT work-log tasks (e.g. domain tracking checkboxes without a `✅` date) are safely left in place by this same rule.

### Write-Time Validation (enforced on completion — BLOCK)

When this skill **completes a task** — writes a new `- [x] … ✅ YYYY-MM-DD` line, or flips an existing `- [ ]` to `- [x]` and appends `✅ YYYY-MM-DD` — it MUST validate that exact line against the Sweep Contract above BEFORE finalizing the write, by running the sweep's own checker:

```
python {sb_os_path}/para/workflows/sb-archivist/sweep_done_tasks.py --validate-line="<the completed task line>"
```

`{sb_os_path}` resolves from `sb-os.json`. Use the `=` form shown — a value starting with `-` is otherwise parsed as a flag. Gate on the EXIT CODE (encoding-independent):

| Exit | Verdict | Action |
|------|---------|--------|
| `0` | `CONFORMING` | Line satisfies the contract and will sweep cleanly. Finalize the write. |
| `1` | `VIOLATION: <reason>` | Column-0 `- [x]` but the `✅` date is missing, malformed (no space, unpadded, impossible calendar date), or ambiguous (two distinct dates). **BLOCK** — do NOT finalize. Correct the line per `<reason>` and re-run until exit `0`. |
| `2` | `NOT-A-TASK: <reason>` | Line is not a column-0 `- [x] ` top-level task. If you intended a top-level completion, the line is mis-formed (leading whitespace, or not `- [x] `) — fix it to column 0 and re-validate. |

Invoke ONLY on a genuine completion. Do NOT validate indented subtasks, `~~strikethrough~~` relocation cross-refs, or domain tracking checkboxes — those are never sweep targets and carry no `✅` date by design; the checker sees only the line and would wrongly flag a column-0 one as a `VIOLATION`. The completion operation is the trigger; nothing else.

## Sub-bullets

### Context prefixes

| Prefix | Purpose |
|--------|---------|
| `_Why:_` | Justification for MoSCoW priority — when classification is not obvious |
| `_Goal:_` | Why this task exists — when objective is not obvious from the action |
| `_Context:_` | Execution-relevant knowledge gathered, discovered, or available at creation time — facts, exact paths, root causes, prior attempts, related artifacts. Always include at creation; must satisfy Cold-Start Sufficiency below |
| `_Criteria:_` | Concrete completion criteria — always include |
| `_Ref:_` | External references (links, IDs, contacts) — each in own sub-bullet |
| `_Review:_` | Weekly review observations |

### Structural groupers

| Prefix | Purpose |
|--------|---------|
| `_Reschedule:_` | Rescheduling history. Each entry: `Nx (origin: 📅 YYYY-MM-DD)` |
| `_Subtasks:_` | Concrete steps, each starting with a verb |

### Order

Why → Goal → Context → Criteria → Ref → Review → Reschedule → Subtasks

## Cold-Start Sufficiency

Every task MUST be executable cold: an agent with **zero memory of the session that created it** can carry it out correctly without re-deriving what the author already knew. The sub-bullets above are the vehicle — encode the goal, the execution-relevant facts (including the state work was left in, the decisions made and why, and what was tried and ruled out), concrete criteria, links to the artifacts, and known next steps.

**Self-check before filing:** _"Could a stranger agent execute this from the task text alone?"_ No → the task is incomplete; add what is missing. The bar scales to the task — a trivial reminder needs little; a handed-off job needs everything the author knew.

## Example

```markdown
#### Must

- [ ] 📅 2026-04-15 Submit court filing for case
  - _Why:_ statutory deadline imminent
  - _Goal:_ ensure evidence specification filed on time
  - _Context:_ lawyer confirmed the evidence list complete on 04-10; filing goes through the court portal under case nº below
  - _Criteria:_ filing protocoled at court
  - _Ref:_
    - Case nº [number]
  - _Subtasks:_
    - Schedule meeting with lawyer

#### Should

- [ ] Map tooling options for [topic]
  - _Criteria:_ list of 10+ tools with category and differentiator

- [x] 📅 2026-03-31 Configure staging environment ✅ 2026-04-01
```

## MoSCoW Prioritization

Tasks live under `####` headings in `{name}-tasks.md`.

| Level | Meaning |
|-------|---------|
| **Must** | Critical path — without this, the objective fails |
| **Should** | Important but not blocking. Deferrable |
| **Could** | Nice-to-have. First to cut |

- Every `{name}-tasks.md` MUST have all three sections, even if empty
- New tasks without clear priority → `Should`
- Moving between sections = changing priority

## Lifecycle

| Phase | Action |
|-------|--------|
| Creation | No date = backlog (appears in "No Date" on Home) |
| Recurrence | `🔁` on the line — always appears in "Today" |
| Execution | Agent starting work on a task MUST append `#wip` to the end of the task line, and MUST remove `#wip` when execution ends (completed or stopped). Marks work-in-progress; dashboards render it as a WIP pill |
| Completion | `[x]` + `✅ YYYY-MM-DD` at end. Validate the line per § Sweep Contract → Write-Time Validation and BLOCK a non-conforming completion |
| Cleanup | Weekly review deletes completed tasks. Git preserves history. Stale `#wip` on tasks with no active execution is removed |

## Progressive Enrichment

Enrich tasks automatically as context evolves — no user action, no announcement.

| Event | Action |
|-------|--------|
| Related context appears (meetings, external info) | Add `_Ref:_` with `[[link]]` or reference |
| Discussed in weekly review | Add `_Review:_` |
| Rescheduled | Add entry to `_Reschedule:_` |
| User explains priority, outcome, or completion criteria | Add `_Why:_`, `_Goal:_`, or `_Criteria:_` |

Never duplicate (update existing). Never remove (additive only). Maintain sub-bullet order.

## Routing

Every task exists in exactly ONE `{name}-tasks.md` file.

### Decision Tree

| # | Question | Yes | No |
|---|----------|-----|-----|
| 1 | Is there an active project for this workstream? | Task goes in `{project}-tasks.md` | Next question |
| 2 | Is the task cross-cutting (touches multiple projects or none)? | Task goes in `{area}-tasks.md` | Next question |
| 3 | Does the task have a concrete deliverable and deadline? | Consider creating a project | `{area}-tasks.md` |

### Routing Rules

- **Source of truth.** Each area's `CLAUDE.md` carries the project-specific routing rules for that area. Read it before creating a task.
- **No tasks file yet?** Create `{name}-tasks.md` on the first task (frontmatter: `type: tasks`, identity tag first; projects add `area`). Task files are optional until then — never create empty ones preemptively.
- **Zero duplication.** Each task exists in ONE file only.
- **When in doubt**, area wins over project. Move to project when scope becomes clear.
- **Weekly review** checks for duplicates between area and linked projects.
