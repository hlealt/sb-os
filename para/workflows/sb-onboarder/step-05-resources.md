---
name: Resources (conditional)
description: Place concrete resources surfaced in earlier steps. Skips silently if nothing surfaced.
nextStepFile: step-06-home.md
---

# Step 05 — Resources (conditional)

**Goal:** Route concrete resource candidates surfaced in steps 02–04 to their proper homes under `3-resources/`. This step is **conditional** — it fires only when there's something real to place.

---

## Mandatory Sequence

### 1. Trigger gate

Read `onboarder_state.resources_surfaced`. Apply this rule:

| Condition | Action |
|-----------|--------|
| `resources_surfaced` is empty | **Skip silently.** Append `"step-05-resources"` (with note `"skipped: no candidates"`) to `completed_steps`, set `last_step`, write `sb-os.json`, and load `step-06-home.md` immediately. Do NOT show this step to the user. |
| `resources_surfaced` contains entries | Continue with the rest of this step. |

This trigger gate exists by design — without concrete candidates, this step would feel pushy. Resources usually emerge over time, not during onboarding.

### 2. Re-confirm each candidate

For every entry in `resources_surfaced`, ask: "You mentioned `{name}` earlier in the context of `{mentioned_in_context}`. Want to bring it into the vault now, or skip and come back later?"

Drop entries the user wants to skip.

### 3. Propose destinations

Map each remaining entry to a `3-resources/` destination using these defaults:

| Type | Default destination |
|------|--------------------|
| `tool` | `3-resources/tools/catalogs/{appropriate-catalog}.md` (append) |
| `prompt` | `3-resources/tools/prompts/{prompt-name}.md` (new file) |
| `repo` | `3-resources/tools/{repo-name}/` (instruct user to `git clone` themselves; do NOT clone from the workflow — keep boundaries clean) |
| `article` / `transcript` / `paper` | `{wiki_root}/raw/{source}/` — point to `/sb-wiki-ingest` instead of writing here |
| Other reference | `3-resources/{category}/` (ask user to name the category) |

For repos and wiki content, the onboarder does NOT write directly — it points to the right command (`git clone` for repos, `/sb-wiki-ingest` for sources) and lets the user run it.

### 4. Batch-confirm and write

Show the proposed destinations. After explicit user approval, invoke `sb-vault-ops` skill and write only the items that are direct file writes (catalog appends, prompt files). For the others, print the exact next-step command(s) for the user.

Run `sb-vault-integrity` post-op sweep.

### 5. Update state

For each resource handled (written or pointed-out), update its entry in `onboarder_state.resources_surfaced` with its resolved destination. Append `"step-05-resources"` to `completed_steps`, set `last_step`. Write `sb-os.json`.

---

## Step Menu

| Option | Action |
|--------|--------|
| [C] Continue | Proceed to step-06-home.md |
| [?] Ask | Help handler |
| [X] Exit | Stop. State preserved. |

HALT and WAIT for user input.
