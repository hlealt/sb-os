# Step 03 — Week Intention

## Purpose

Define what a good week would look like — clean reflection, without bias from backlog, overdue tasks, or calendar. The user defines OUTCOMES, not tasks.

## Principle: Clean Room

The agent does NOT load any vault read-context before this step. Write-mode context injection still applies per `sb-workflow-context.md`. The only input is:
- The retrospective from step 01 (accomplishments, blockers, learnings)
- What the user brings from memory

This ensures priorities reflect what REALLY matters, not what is pending.

## Execution

### 1. "Good week" reflection

Default prompt:

> **"Next week will be a good week if..."**
>
> Think about OUTCOMES you want to achieve, not tasks. What will make you feel the week was worthwhile?

If context YAML provides `prompt.step-03.good-week`, use that text instead.

### 2. Objective-driven: definition of done

For each outcome the user mentions, ask. Default prompt:

> **"How will you know it's done? What is the 'done'?"**

If context YAML provides `prompt.step-03.definition-of-done`, use that text instead.

This reduces the 8/80 pattern (extreme or minimal intensity). With a clear definition of done, the user knows when to stop.

### 3. Separate Must vs. Should

Default prompt:

> **Separate into Must (the week fails without this) and Should (good if you can).**

If context YAML provides `prompt.step-03.must-should`, use that text instead.

The agent can question ("deadline is tomorrow — is it really Should?") but NEVER categorizes on its own.

### 4. Habits and self-care

Default prompt:

> **"How are the habits? Anything you want to maintain or resume this week?"**

If context YAML provides `prompt.step-03.habits`, use that text instead.

Habits tend to drop when product focus intensifies. This explicit question serves as a guardrail.

### 5. Record in the weekly note

Default headings used in the block below:
- Top heading: `Week intention ({week})` — overridable via `section.intention.heading`
- Must subheading: `Must — the week fails without this` — overridable via `section.must.heading`
- Should subheading: `Should — good if you can` — overridable via `section.should.heading`
- Habits subheading: `Habits / self-care` — overridable via `section.habits.heading`

```markdown
## Week intention ({week})

### Must — the week fails without this
1. [outcome] — _Criteria:_ [definition of done]
2. ...

### Should — good if you can
1. [outcome] — _Criteria:_ [definition of done]
2. ...

### Habits / self-care
- [intentions]
```

Apply the YAML-provided heading text whenever the corresponding key is present.

### 6. Draft and review the intentions list with the user

After recording Must/Should/Habits, the agent drafts an intentions-list subsection and **presents it to the user for review before writing**. This is what the vault Home displays as "Week intention" — it is the user's strategic compass for the week.

Default subheading: `Intentions`. If context YAML provides `section.intentions-list.heading`, use that value. The same key MUST be used by step-06 and any Home parser.

**Process:**
1. Draft 4–7 bullet points from the discussion context
2. Present the draft to the user. Default prompt: `Here's what I'd put as your Intentions this week — adjust, add, or remove?`. If context YAML provides `prompt.step-03.intentions-review`, use that text instead.
3. Incorporate feedback — add items the user requests, reword what doesn't resonate, remove what feels wrong
4. Write ONLY after the user confirms

**Why review matters:** The intentions list is the ONE section the user sees every day on Home. If it misses something important (like a reading intention), the user loses a week of reinforcement. The agent's synthesis is a starting point, not the final word.

**Input:** The agent synthesizes from everything discussed so far:
- Axis assessments from step 02 (especially warnings, patterns, semaphore reds/yellows)
- Learnings and blockers from step 01
- The habits and self-care intentions just captured
- The *why* behind Must/Should items (not the items themselves)
- Anything the user explicitly said they want as an intention

**Output:** 4–7 bullet points that capture the qualitative compass for the week — mindset, behavioral patterns to watch, themes.

**Format — every bullet is one line:**

```
- **Bold header.** One short phrase.
```

| Element | Constraint |
|---------|------------|
| Bold header | 3–8 words. A mantra, a claim, or the user's own line. Must stand alone if the phrase is removed. |
| Phrase after | A single short phrase — NOT a sentence with multiple clauses. The most concrete operational hint. End with a period. |
| Total length | One rendered line. If it wraps in normal markdown, it's too long. |

**Voice rules:**
- Natural — write how the user would say it out loud, not coach-speak.
- No filler. Default filler list to cut: `It's important`, `Remember that`, `Worth noting`, `We must`, `We should` — they signal motivational coaching. If context YAML provides `text.step-03.filler-words`, use that locale-specific list instead.
- No references the user won't recall cold. No "per the therapist", no "as we discussed", no jargon from the review conversation.
- When the user uttered a strong line during the review, use it verbatim. Their own words beat your synthesis.

**Excluded by format:**
- Multi-sentence bullets
- Narrative bullets ("Given X this week, you should Y because Z")
- Compound bullets packing 2 ideas
- Generic platitudes with no concrete hook
- Specific actions, deadlines, or deliverables (those are tasks, not the compass)
- "Done:" criteria (this is a compass, not a checklist)

**Clarity check:** Each item must mean something specific when read cold on a random morning. Name patterns, not labels. The user will not remember the conversation that produced the bullet.

Default bad/good examples table (English):

| Bad | Why | Good |
|-----|-----|------|
| **Focus.** | Header alone, no phrase, no concrete hook | **Focus on what ships.** Internal meetings can wait. |
| **Balance.** Don't overdo it and stay consistent. | Generic platitude, no operational hint | **Structure > willpower.** A fixed routine holds; motivation doesn't. |
| **Keep the work pace while keeping mental and physical health.** | Multi-clause sentence stuffed into one bullet | **Body first.** When work intensifies, self-care is the first thing to drop. |
| **Remember it's important to start even without full clarity.** | Filler ("Remember", "it's important"), narrative tone | **Start despite uncertainty.** Blockers are ambiguity, not complexity. |

If context YAML provides `text.step-03.bad-good-examples`, use that locale-specific table instead.

Default fictitious example (shape only — adapt to the user's actual week):

```markdown
### Intentions
- **Structure > willpower.** A fixed routine works better than motivation.
- **Body first.** When work intensifies, self-care is the first to drop.
- **Step away to think.** Answers don't come from more screen.
- **One small decision daily.** Don't wait for Sunday to reorganize the week.
```

If context YAML provides `text.step-03.intentions-example`, use that locale-specific block instead.

> **Home dependency:** the vault Home parses the intentions-list subsection inside the week intention section to render the home page. If you change heading names or structure, update the Home parser and `section.intentions-list.heading` / `section.intention.heading` keys must match.

### 7. Write agent notes to weekly note

After completing the intentions list, write an agent-notes section to the weekly note. Default heading: `## Agent notes (steps 01–03)` — derive the prefix from `section.agent-notes.heading` (default `Agent notes`) plus the suffix `(steps 01–03)`. This section carries the rich discussion context forward to the next agent — it is **deleted in step 08** before finalizing.

```markdown
## Agent notes (steps 01–03)

<!-- Temporary section — deleted in step 08 before finalizing the weekly note -->

### Patterns observed
- [patterns from self-knowledge/goals that were active this week]
- [axis warnings — any axis flagged red or yellow, and why]
- [therapy themes that connect to behavioral patterns]

### Challenges from discussion
- [what the agent challenged during steps 01-03 and how the user responded]
- [assumptions the agent tested and the outcome]

### Context for planning (steps 04-08)
- [anything from the retrospective, axis check, or intention that should inform task planning]
- [known avoidance patterns to watch for during planning — e.g., overloading Must, avoiding specific areas]
- [user's stated priorities and the reasoning behind them]

### Open threads
- [unresolved topics the user flagged for later discussion]
- [items mentioned in passing that haven't been captured as tasks yet]
```

Be thorough — the next agent has NOT seen the source materials or the conversation. Everything it needs to challenge effectively during planning must be in this section.

8. Note everything in the session log (priorities, habits, any task the user mentions in passing)
9. Update `stepsCompleted`

### 11. Context handoff

This is a **hard boundary**. Steps 01-03 (reflective/strategic) are complete. Steps 04-08 (operational/planning) will run in a fresh session.

Default handoff message:

> **Steps 01-03 complete.** The retrospective, axis check, and intentions are recorded.
>
> To continue: start a new session and run the entry-point command → Week. The next agent will pick up from step 04 using the weekly note and session log.

If context YAML provides `prompt.step-03.handoff`, use that text instead. Replace any reference to the entry-point command with the value of `command.entry-point` (default `/sb-life-planner`).

Do NOT present the step 04 menu. The session ends here.

## Menu

```
Intentions recorded: X Must, Y Should. Intentions list: N items. Agent notes: written.

→ Steps 01-03 complete. Start a new session to continue from step 04.
```
