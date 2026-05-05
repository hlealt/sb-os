---
name: Discover Domains
description: Elicit the user's life domains using curated inspiration, never cold quizzing.
nextStepFile: step-03-areas.md
---

# Step 02 — Discover Domains

**Goal:** Surface the user's actual life domains by presenting curated examples and inviting reactions. Output a `domains_proposed` list seeded with the user's confirmations + additions.

---

## Mandatory Sequence

### 1. Present the inspiration menu

Read `data/life-domain-inspiration.md`. Show the user the **Common areas** table — this is the conversation starter. Frame it explicitly:

> "Here's a menu of domains many people track. I'm NOT saying you should have all of these. I'm asking you to react: which ring true, which don't fit your life, which are missing?"

Show the table. Do NOT show the projects/resources tables yet — those come in steps 03+ and 04+ where they're more useful.

### 2. Walk through together

Go row by row. For each row, ask one of:

- "Does `area-X` fit?" (if it's a near-universal one like finance or health)
- "Anything you'd track here, or skip?" (if it's a maybe like creative or business)

Accept short answers. Note ambiguities. If the user names a domain not in the table, capture it.

If the user says "all of them" or "none of them" — push back gently. "All" means they haven't filtered; "none" means we haven't found their language. Ask one clarifying question.

### 3. Surface the borderline cases

Show the **Domains that often surface but resist clean PARA mapping** table. Ask: "Any of these come up for you? If so, which mode are you in — bounded project, ongoing area, or just reference?"

Capture answers. Do NOT commit to project/area/resource yet — that's step 03/04/05.

### 4. Capture resource hints (passive)

While walking through domains, listen for mentions of: tools, prompts, repos, articles, references. When the user mentions one, capture it into `onboarder_state.resources_surfaced` with `{name, type, mentioned_in_context}`. Do NOT propose a destination yet — step 05 handles that.

### 5. Confirm the domain list

Present back the user's domain list:

```
Domains we'll structure together:
- area-finance
- area-health
- area-learning
- (user's custom domain)
- ...
```

Ask: "Anything to add or remove before we start creating folders?"

### 6. Update state

Save the confirmed list to `onboarder_state.domains_proposed`. Append `"step-02-discover-domains"` to `completed_steps`, set `last_step`. Write `sb-os.json`.

---

## Step Menu

| Option | Action |
|--------|--------|
| [C] Continue | Proceed to step-03-areas.md |
| [?] Ask | Help handler |
| [X] Exit | Stop. State preserved. |

HALT and WAIT for user input.
