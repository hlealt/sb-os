# Life-Domain Inspiration

Curated example domains drawn from common patterns — NOT a personal vault. Use these as conversation starters with the user during step-02. The onboarder presents them as "here's a menu of domains many people track; tell me which resonate, which don't, what's missing."

Never present this list as prescriptive. The user's actual life shape always wins.

---

## Common areas (ongoing responsibilities)

| Area | What it covers | Typical sub-content |
|------|----------------|--------------------|
| `area-finance` | Money in, money out, investments, taxes, budgeting | monthly closes, account snapshots, tax docs |
| `area-health` | Physical and mental health, fitness, medical | check-ups, exercise log, therapy notes, supplements |
| `area-learning` | Topics of ongoing study and the reading-list backbone | reading-list, study notes, courses in progress |
| `area-work` | Current employment / primary professional context | meetings, OKRs, 1:1 notes, performance |
| `area-relationships` | People you actively maintain connection with | birthdays, gift ideas, shared plans, family |
| `area-home` | Household — domicile, maintenance, possessions | bills, repairs, inventory, neighborhood |
| `area-creative` | Personal creative practice (writing, music, art) | drafts, sketches, project ideas |
| `area-tech` | Personal tech setup, hardware, dotfiles, configs | my-setup, hardware inventory, troubleshooting |
| `area-business` | Owned ventures, side projects with ongoing operations | finances, ops, strategy |

Sub-areas (kebab-case) nest naturally: `area-finance/taxes/`, `area-work/meetings/`.

---

## Common projects (bounded with a "done")

| Project type | Examples |
|--------------|----------|
| Personal milestones | move-apartment, plan-trip-japan, ship-website-v1 |
| Work deliverables | q2-launch, customer-research-report, hire-engineer-2 |
| Creative work | write-novel-draft-1, record-album, design-logo |
| Learning goals | learn-french-a2, finish-mit-ocw-6.006 |
| Life events | wedding, baby-prep, buy-first-home |

Project names are kebab-case verbs or noun-phrases that imply completion.

---

## Common resources (reference, on-demand)

| Resource folder | What goes inside |
|-----------------|------------------|
| `tools/` | catalogs of tools you use, reusable prompts, installed code repos |
| `knowledge-base/` (or wiki_root) | external articles, transcripts, derived notes |
| `references/` | cheatsheets, glossaries, quick lookups |
| `templates/` | reusable document templates |

Resources are NOT places to dump content "just in case" — only what you'll actually consult.

---

## Domains that often surface but resist clean PARA mapping

These come up in conversation but need clarification before you commit to a folder. Ask which mode the user is in:

| Domain | Project? Area? Resource? |
|--------|--------------------------|
| Therapy / coaching | Usually `area-health/therapy/` (ongoing) — sometimes a project if time-boxed |
| Career planning | Project (job-search-2026) when active; area (`area-career`) when ambient |
| A specific relationship | Usually inside `area-relationships/{name}/` — rarely its own area |
| Travel | Project per trip; resource folder for travel info that recurs |
| Hobby with no output | Area, not project — unless there's a specific deliverable |

---

## Anti-patterns to gently steer away from

| User says | Steer toward |
|-----------|--------------|
| "I want a folder for everything I might ever need" | Resources are on-demand. Start with what you'll consult this month; add later |
| "Each person I know should be a folder" | One `area-relationships/` with sub-files — folders only when stewardship is active |
| "Let me just dump this in `0-periodic-notes/`" | Routing is the point. Daily is the fallback, not the default |
| "Can I have a folder called `misc`?" | No. `misc` becomes a graveyard. If it doesn't fit, ask why — it usually wants a real category or it doesn't belong |
| "I want everything bilingual" | sb-os ships English-default. The user can mix languages inside files freely; folder names stay English |
