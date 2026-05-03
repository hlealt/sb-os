---
name: Home (optional)
description: Optionally build a Home.md dashboard at the vault root, driven by ideas/home-dashboard.md.
nextStepFile: step-07-finalize.md
---

# Step 06 — Home (optional)

**Goal:** Offer the user the chance to build a `Home.md` dashboard at the vault root. If accepted, read the design idea, elicit which surfaces they want, generate `Home.md`, and print Obsidian plugin install instructions.

---

## Mandatory Sequence

### 1. Frame the offer

Tell the user:

> "`Home.md` is the surface you see when you open your vault. It aggregates and orients — today's tasks, active projects, recent activity, periodic links. It does NOT store content. It's optional, and you can build it later anytime by re-running `/sb-onboarder` and choosing 'Jump to Home'."

Ask: "Want to build one now?"

| Answer | Action |
|--------|--------|
| Yes / Sure / OK | Continue to step 2 |
| No / Skip / Later | Set `onboarder_state.home_built: false`, append step to `completed_steps`, write state, load `step-07-finalize.md` |

### 2. Read the design idea

Read `{sb_os_path}/ideas/home-dashboard.md` in full. Internalize: capabilities table, design principles (especially "degrade gracefully without Dataview"), anti-patterns (especially "no hardcoded area names"), reference points.

### 3. Print plugin requirements upfront

Tell the user — BEFORE eliciting surfaces — that Home requires two Obsidian community plugins:

```
Required Obsidian plugins:
  1. Dataview      (Settings → Community plugins → Browse → Dataview)
                   Enable "Dataview JS Queries" in Dataview's settings.
  2. Templater     (Settings → Community plugins → Browse → Templater)

Without these, Home will render but its dynamic blocks will show fallback text.
```

Confirm the user has installed and enabled them, OR is willing to do so right after this step. If they refuse, proceed but warn that dynamic blocks will fall back to static placeholders.

### 4. Elicit surfaces

Show the **Capabilities to consider** table from `ideas/home-dashboard.md`. Ask:

> "Pick 2–4 of these. Two well-chosen views beats seven competing widgets."

Capture the user's selection plus any custom additions. Optionally ask filter preferences (priority scheme? task plugin emoji conventions? language label preferences? — but offer the user-supplied option, never assume).

### 5. Generate Home.md

Generate `Home.md` at the vault root, following the design principles in the idea doc:

- Read folder structure from the filesystem at query time — never hardcode area/project names.
- Provide plugin-missing fallback for every dynamic block.
- Persist UI state in localStorage where DVJS is involved.
- Order surfaces by user-stated priority.

Show the user the generated file before writing. After explicit approval, invoke `sb-vault-ops` and write `Home.md`. Run `sb-vault-integrity` post-op.

### 6. Update state

Set `onboarder_state.home_built: true`, append `"step-06-home"` to `completed_steps`, set `last_step`. Write `sb-os.json`.

---

## Step Menu

| Option | Action |
|--------|--------|
| [C] Continue | Proceed to step-07-finalize.md |
| [?] Ask | Help handler |
| [X] Exit | Stop. State preserved. |

HALT and WAIT for user input.
