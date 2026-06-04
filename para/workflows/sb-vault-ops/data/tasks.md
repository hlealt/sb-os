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

## Sub-bullets

### Context prefixes

| Prefix | Purpose |
|--------|---------|
| `_Why:_` | Justification for MoSCoW priority — when classification is not obvious |
| `_Goal:_` | Why this task exists — when objective is not obvious from the action |
| `_Context:_` | Execution-relevant knowledge gathered, discovered, or available at creation time — facts, exact paths, root causes, prior attempts, related artifacts. Always include at creation |
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
| Completion | `[x]` + `✅ YYYY-MM-DD` at end |
| Cleanup | Weekly review deletes completed tasks. Git preserves history |

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
- **Zero duplication.** Each task exists in ONE file only.
- **When in doubt**, area wins over project. Move to project when scope becomes clear.
- **Weekly review** checks for duplicates between area and linked projects.
