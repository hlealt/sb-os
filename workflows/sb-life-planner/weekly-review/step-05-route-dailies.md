# Step 05 — Route Daily Content

## Purpose

Distribute daily note content to the correct vault files, ensuring NO item is left behind. Uses the inventories produced by sub-agents in Step 01. Process context injection per `sb-workflow-context.md` before proceeding.

## Principle: Verifiable completeness

Each item from each daily MUST have a classification and a destination (or justification for discard). At the end of the step, the sum of processed items = sum of inventoried items. No exceptions.

## Execution

### 0a. WhatsApp self-chat scan (optional)

Ask the user:

> Do you want to scan your WhatsApp self-chat for items to route?

If **yes**:

1. Resolve the WhatsApp extractor script path. Default `3-resources/tools/sb-os/workflows/sb-life-planner/weekly-review/data/whatsapp-extract.js`. If context YAML provides `path.script.whatsapp-extract`, use that value instead.
2. Read the script and present it to the user with instructions:
   - Open WhatsApp Web → select self-chat ("Message yourself")
   - Scroll up to load older messages if needed
   - Press F12 → Console tab → paste the script → Enter
   - Ctrl+V here to paste the extracted messages
3. When the user pastes the messages, add them to the session log under a new `### WhatsApp self-chat` subsection in the daily inventory section
4. These items are classified and routed together with daily note content in sub-steps 2–6

If **no** → proceed directly.

### 0b. Detect already processed dailies (adaptive)

Before loading inventories, check which dailies of the week have already been processed:

1. For each daily of the week, check if it has both `reviewed` AND `routed` tags in frontmatter
2. Dailies with both tags → **already processed**. Report to user and skip:
   ```
   Dailies already processed by daily close: dd/mm, dd/mm (2 of 5)
   Processing the remaining 3.
   ```
3. Dailies without tags or with only one → **not processed**. Inventory normally
4. If ALL dailies have already been processed → skip directly to completeness verification (sub-step 6) and then advance

### 1. Load inventories

Read the "Daily inventory" section of the session log. Each **unprocessed** daily has a table with all items and their suggested types (Routable / Review note / Task).

For dailies already processed by daily close: check if the session log has a record of what was routed. If not → produce retroactive inventory to confirm completeness in sub-step 6.

### 2. Triage low-confidence items

Before presenting the full routing table, extract all items with Confidence = LOW from the inventories. These come from flat dumps or Inbox overloads where the sub-agent inferred classification without strong structural signal.

Present them grouped by daily:

```
## Triage needed (N items from unstructured content)

| Daily | # | Content | Sub-agent suggested | Your call? |
|-------|---|---------|---------------------|------------|
| dd/mm | N | "content description..." | Task → {area}-tasks | |
| dd/mm | N | "idea or insight..." | Idea → {project}-tasks | |
| dd/mm | N | URL: example.com/article | Routable → reading-list.md | |
```

For each item, the user confirms, reclassifies, or discards. Update the inventory with the user's decision before proceeding to the aggregated view.

If there are zero low-confidence items → skip this sub-step and proceed directly.

### 3. Present aggregated inventory to the user

Group by suggested classification and present as a table for confirmation:

```
## Routable (X items)
| Daily | # | Content | Suggested destination |
|-------|---|---------|-----------------------|
| dd/mm | N | Link about topic X | destination from context injection |
| dd/mm | N | Idea about Y | destination from context injection |
| ... | ... | ... | ... |

## Identified tasks (Y items)
| Daily | # | Content | Suggested index file |
|-------|---|---------|-----------------------|
| dd/mm | N | Action item description | {area}-tasks.md or {project}-tasks.md |
| ... | ... | ... | ... |

## Review notes (Z items) — will go to weekly note
| Daily | # | Content |
|-------|---|---------|
| dd/mm | N | Self-observation: noticed pattern of avoiding hard tasks |
| ... | ... | ... |

Confirm classifications? Anything to change category?
```

Use the content routing table from CLAUDE.md to determine destinations. Ambiguous items → classification "Ask" → resolve with the user.

**File-level destinations (mandatory):** The "Suggested destination" column MUST contain the actual file path, not just the folder. Use the routing destinations provided by context injection. Read the destination folder's CLAUDE.md to identify which file the content belongs in. When a Project exists for the topic (check `1-projects/`), route tasks there instead of the Area.

### 4. Resolve ambiguous items

For each item with classification "Ask":

> "This item has no obvious destination: [content]. Where do you want it to go?"

Options: name a destination, convert to review note, convert to task.

### 5. Execute routing

After user confirmation, process each item:

| Classification | Action |
|----------------|--------|
| **Routable** | If it fits in an existing file → append. If it's standalone → create new file with `type` in frontmatter. If it's temporal → `log` file |
| **Task** | Create `- [ ]` in the correct `{name}-tasks.md`, following the `sb-vault-ops` skill (tasks path) |
| **Review note** | Write to `## Review notes` section in the weekly note. Monthly review may promote to structured files |
| **Already exists** | No action (content is already reflected in the vault) |

Update `{name}-tasks.md`, index files and CLAUDE.md of folders that gained new files or tasks.

### 6. Completeness verification

After routing, build reconciliation table:

```
## Completeness verification
| Daily | Items inventoried | Routed | Tasks created | Review notes | Already existed | Total processed | Pass |
|-------|-------------------:|--------|---------------|--------------|-----------------|-----------------|------|
| dd/mm | 5 | 2 | 1 | 2 | 0 | 5 | OK |
| dd/mm | 3 | 1 | 0 | 1 | 1 | 3 | OK |
```

If "Total processed" != "Items inventoried" for any daily → **STOP**. Identify the missing item and resolve before continuing.

### 7. Mark dailies and record

1. Add `reviewed` + `routed` tags to the frontmatter of each processed daily
2. Update inventories in the session log: add "Final destination" column with the actual path of each item

3. Record in the weekly note:
```markdown
## Routed items

### [area/project]
- [description] → [[destination-file]]
- ...

### Tasks created
- [task] → [[index-file]]
- ...
```

4. **Continuous reconciliation:** check session log for pending items that should have been handled
5. Update `stepsCompleted`

### 8. Context handoff (Block B → Block C)

This is a **hard boundary**. Steps 04-05 (calendar + routing) are complete. Steps 06-08 (planning + verification) will run in a fresh session.

Before ending:

1. Ensure the session log has complete daily inventories with final destinations
2. Update the agent-notes section in the weekly note — append a `### Routing context (steps 04–05)` subsection with:
   - Calendar events that affect planning (meetings, fixed commitments)
   - Routing decisions that created new tasks (so step 06 knows they exist)
   - Any items the user flagged for planning discussion

   The agent-notes heading prefix comes from `section.agent-notes.heading` (default `Agent notes`); append this subsection under that block.
3. Update `stepsCompleted`

Default handoff message:

> **Steps 04-05 complete.** Calendar read and dailies routed.
>
> To continue: start a new session and run the entry-point command → Week. The next agent will pick up from step 06.

Replace any reference to the entry-point command with the value of `command.entry-point` (default `/sb-life-planner`).

## Menu

```
X items routed, Y tasks created, Z review notes captured from W dailies.
Completeness verified: all items processed.

→ Steps 04-05 complete. Start a new session to continue from step 06.
```
