# Home Dashboard — Idea

A home dashboard is the surface you see when you open your vault. It is yours. This document describes what such a surface is *for*, the capabilities it could expose, the patterns that work, the principles that keep it useful, the failures that recur, and how to build one. Read it, then build your own `Home.md` to your spec — by hand, or with an AI agent.

The unit shipped here is **intent**. The materialization is yours.

---

## Purpose

`Home.md` is the surface the user sees on vault open. It exists to **aggregate, summarize, and orient** — not to store content.

A good home dashboard answers, at a glance: *what needs my attention right now?* It does not become a place where notes accumulate. Content lives in its proper PARA destination. The home dashboard reads from there, presents a curated slice, and gets out of the way.

If you find yourself capturing into the home dashboard, that is a routing failure — the dashboard pulled you in instead of pointing you out.

---

## Capabilities

These are surfaces a home dashboard *could* expose. Pick the ones that match how you actually work; ignore the rest. Grouped by family so you can pick across categories rather than picking everything in one.

### Temporal orientation

| Capability | What it shows |
|------------|---------------|
| Time-of-day greeting | "Good morning / afternoon / evening, {name}" — small, but it makes the surface feel personal |
| Today's date | Long-form date prominently rendered |
| Calendar overlay | Today's reading from a cultural / astrological / religious / lunar calendar (e.g. "favorable", "neutral", "unfavorable" with color-coded text) |
| Daily quote | A rotating quote drawn from a source file, deterministically picked from the day-of-year so the same day always yields the same quote |
| Periodic-note quick links | One-click jumps to today's daily, this week's weekly, this month's monthly, this quarter's quarterly. The daily link should also **create** today's note from the daily template (`.user/config/templates/periodic-notes/Daily.md`) when it doesn't exist yet — one click takes you from a fresh vault open to a writable note |

### Intent and direction

| Capability | What it shows |
|------------|---------------|
| Multi-horizon intention compass | Strategic (quarterly), thematic (monthly), and tactical (weekly) intentions side by side. Shows "who you're trying to be" at three time horizons — qualitative, not tasks. **Fed by `/sb-life-planner`**: each tier writes an `Intentions` subsection inside its periodic note (`0-periodic-notes/{period}/`); the dashboard parses those subsections and surfaces the latest one per horizon. Run the review on cadence → the compass stays current. Skip a review → that horizon goes stale. Intentions are broader than tasks: things to read, remember, and embody throughout the period |
| Goals / OKRs / key results | Per life area, the result you're committing to this period |
| Status per life area | A traffic-light or RAG indicator per area, sourced from your latest weekly review |

### Tasks

| Capability | What it shows |
|------------|---------------|
| Today's tasks | Tasks scheduled for today across the vault |
| Date-bucketed kanban | Overdue → Today → Tomorrow → This week → Next week → Later. Each bucket is a column on desktop, a collapsible section on mobile |
| Recurring tasks | Always surfaced in "Today" regardless of due date, so they don't get buried |
| Tasks without dates | A separate bucket for the work that has no when — surfaced explicitly so it doesn't disappear |
| Per-bucket counters | A small badge on each bucket's header showing the count of visible tasks |
| Priority filters | Clickable pills for whatever priority scheme you use (MoSCoW, p0/p1/p2, ABC, none) |
| Area / project / context filters | Clickable pills that solo or unsolo a slice. Filter state is the dashboard's primary interaction surface. Discover pills from `{name}-tasks.md` files' frontmatter (identity tag = first tag, defaulting to the folder name; parent via `area:`; optional `color:` on the sibling index) rather than a hardcoded list — folders without a tasks file get no pill, and a project's tasks stay filterable by its own pill or its parent area's pill |
| Aggregate stats | "X open, Y completed" rolled up across the visible scope, recomputed when filters change |
| Inline task actions | Check / uncheck with undo, link out to source file, see the task's tags |
| Active projects list | Projects in `1-projects/` you are pushing on, optionally with last-touched timestamp |

### Recurring obligations

| Capability | What it shows |
|------------|---------------|
| Payments / bills / renewals | Pending obligations for the current month, grouped by day |
| Overdue and urgent flagging | Color-coding for past-due (red) and imminent (yellow, e.g. ≤2 days) items |
| Auto-advance month | When the current month is fully resolved and the month is nearly over, surface next month so you stop seeing a "0 due" empty state |
| Inline mark-paid | Check from the dashboard; the write goes back to the source file |
| Running-balance calculator | Optional inline widget — type your current liquid balance, see what's left after each upcoming day's obligations. Extends naturally to **funding-source planning**: when balance < total due, surface how much needs to be moved in (investment withdrawal, transfer, sale) day-by-day to keep payments green. The calculator is a few lines of DVJS plus a numeric input — small surface, high daily value when bills cluster |

### Personal lifecycle

| Capability | What it shows |
|------------|---------------|
| Streak counters | Days since X (smoke-free, alcohol-free) or consecutive days of Y (exercise, journaling) |
| Habit tracker rollup | Today's checklist for the habits you're tracking, optionally a heat-map of recent history |
| Reading list snapshot | The next few items in your reading queue |
| Upcoming milestones | Birthdays, anniversaries, deadlines in the next N days |
| Privacy toggle | Eye icon that hides sensitive counters (substance use, weight, money) so you can screen-share without anxiety |

### Quick interaction

| Capability | What it shows |
|------------|---------------|
| Inline capture | Input field at the top that routes to a chosen destination (daily note, inbox, a specific tasks file) |
| Quick-link launcher | A row of buttons that jump to high-frequency pages — habits, study list, goals, daily check |
| Source link on every item | An arrow icon next to every aggregated row that opens its source file. Without this, the dashboard becomes a dead-end view |

A dashboard with three well-chosen surfaces beats one with twelve competing widgets. Resist the urge to include a capability "in case." Cut it; add it back when you actually miss it.

---

## Surface patterns

The capabilities above are *what* you might surface. These are *how* surfaces tend to behave when they work well.

| Pattern | What it does |
|---------|--------------|
| Pills | Clickable filter chips with a clearly-visible active state. Multi-select for area filters; mutually exclusive for priority filters |
| Kanban | Visual time horizons rendered as columns. Each column has a count badge in its header |
| Collapsible sections | Default-open for the things you read every day; default-closed for the things you check occasionally. State persists across re-renders |
| Stats badges in section headers | Counts and aggregates inline with the section title — no separate "stats" panel |
| Inline write-back | Checkboxes, calculators, marks-as-done that mutate the source file directly. The dashboard becomes interactive, not just read-only |
| Privacy toggle | A single icon hides multiple sensitive widgets. Defaults to hidden so a casual screen-share doesn't leak |
| Mobile-aware layout | Same data, different shape. Kanban becomes vertical; pills stack into rows; column defaults change (only "Overdue" and "Today" open by default on a phone) |
| Empty-state messages | Every dynamic block has a meaningful message when its query returns nothing. No blank rectangles, no "no results" |
| Per-item source link | Every aggregated row carries a tiny icon that opens its source file. Aggregation without a return path is a dead end |

---

## Design principles

These principles are non-negotiable if you want the dashboard to remain useful as your vault grows.

| Principle | Why |
|-----------|-----|
| Degrade gracefully without Dataview / Tasks plugins | Anyone reading your vault without those plugins should still see meaningful content — not blank query blocks |
| Discover taxonomy from the filesystem | Read folder names, frontmatter, and tags at query time. Never hardcode "the four areas are X, Y, Z, W" — that breaks the moment you rename or add one |
| Persist UI state in localStorage | Tab selections, expanded sections, filter choices — keep them across sessions so the dashboard feels yours, not reset on every open. Critical because Dataview re-renders on *every* vault modification — without persistence, every checkbox you tick resets your filter |
| One entry point, not seven competing widgets | A scannable hierarchy beats a wall of equally-loud panels. Make the most important thing the most prominent thing |
| Plugin-missing fallback for every dynamic block | If Dataview is disabled, the block should render a useful message or a static fallback — not a stack trace or blank space |
| Source link from every aggregated item | If you can't act on what you see — open the source, edit it, follow it — the dashboard becomes a passive feed |
| Inline write-back where it makes sense | Reading the dashboard and acting on it should not require leaving the dashboard. Check a task, mark a payment paid, expand an item — write back to the source |
| Auto-advance temporal context | Don't make the user manually update "current month" or "current week." The dashboard knows the date — let it advance scope automatically when the current bucket is done |
| Mobile-aware, not mobile-only or mobile-ignored | Decide explicitly what changes on a phone. "Same as desktop" is rarely the right answer. "No mobile" is a valid answer if you commit to it |
| Defensive queries | Every query handles the missing case — missing frontmatter, missing file, missing folder. A query that assumes `priority::` exists silently drops every note that lacks it |

These compound. A dashboard that violates one principle usually violates several, because they share the same root cause: assumptions baked into the dashboard about your vault's specific shape.

---

## Lifecycle

A home dashboard is a live artifact. Some behaviors only make sense once you understand how it changes over time.

| Behavior | What to know |
|----------|--------------|
| Re-renders on every file modification | Dataview blocks re-run whenever the vault is modified. Every checkbox you click, every captured note, fires a full re-render. State that lives only in the page is destroyed; state that lives in `localStorage` survives |
| Date-relative views update automatically | "Today's tasks" reflects the current calendar day. As midnight passes, the view shifts. No code change required |
| Auto-advance of temporal scope | When the current period (month, week) is fully resolved or near its end, the dashboard can roll forward to the next one. Otherwise the user lands on an empty "0 due" view |
| Filter state survives, scroll state does not | `localStorage` handles filter persistence. Scroll position resets on re-render — keep the dashboard short enough that scrolling isn't a primary navigation mode |
| Deferred loading | Heavy queries (full vault scans) can be wrapped in an expand/collapse to skip evaluation until the user opens the section. Useful as the vault grows |

---

## Anti-patterns

If you catch your dashboard doing any of these, refactor before they spread.

| Anti-pattern | What goes wrong |
|--------------|-----------------|
| Hardcoded area names | Renaming `area-work/` to `work/` breaks every query that mentions the old name |
| Locale-bound labels | Labels in one language ("Hoje", "Esta semana") fight a future shift to another, and bury the dashboard for collaborators |
| Rigid priority schemes | MoSCoW is one option among many. Hardcoding it shuts out users who think in p0/p1/p2, ABC, urgency-importance, or no scheme at all |
| Personal taxonomies (semáforo, 1/2/3, ABC) | Bake your own classification in and you cannot share, fork, or adapt — the dashboard becomes unportable to even your future self |
| Fixed render order | Today's-tasks-then-projects-then-recent looks fine until you decide projects matter more this quarter — and you cannot reorder without surgery |
| Queries that assume specific frontmatter fields exist | A query on `priority::` silently drops every note that does not have it. Defensive queries handle "field missing" as a normal case |
| Dashboard owns the parser | When the dashboard parses workflow output (regexes against headings, frontmatter shapes, table layouts), every workflow tweak breaks the dashboard. Keep the parser thin and obvious so you can fix it fast — or, better, push structure into frontmatter the dashboard can read declaratively |
| No source link on aggregated items | A list of tasks you can't open is a wall, not a dashboard. Every row must have a return path |
| Re-renders that destroy filter state | Without `localStorage`, every modification resets the user's view. The user learns to stop touching the dashboard. Don't ship without persisted state |
| Always-visible sensitive counters | Substance, money, weight counters that you can't hide on screen-share become a privacy tax. A single toggle is enough |
| Single layout for desktop and mobile | Cramped on a phone, sparse on a monitor. Either commit to one platform or branch the layout |

The common thread: every anti-pattern is a place where the dashboard *decided for you* instead of *reading from you*.

---

## Reference points

These exist; learn what they offer before you start. None are mandatory.

| Reference | What to take from it |
|-----------|----------------------|
| **Dataview query syntax** | The query DSL most home dashboards rely on for dynamic content (today's tasks, recent files, project lists). Learn the table/list/task query forms before deciding whether you need them |
| **Tasks plugin emoji conventions** | The de facto convention for scheduled (`📅`), due (`🔼`), priority, recurrence (`🔁`), and completion (`✅`) markers. If you adopt them, your tasks become queryable across the ecosystem |
| **DVJS (Dataview JS)** | When Dataview's declarative form runs out, DVJS gives you the full programmatic surface — interactive UI, custom rendering, persisted state, anything JavaScript can do in the page |
| **Obsidian DOM API** | Inside DVJS, build UI programmatically with `createDiv`, `createEl`, `createSpan`, `setCssStyles`. Cleaner than string-concatenated HTML and plays better with Obsidian's lifecycle |
| **`localStorage`** | Available inside DVJS. The right place for filter state, expanded sections, privacy toggles — anything that should survive an involuntary re-render |
| **Luxon** | Bundled with Dataview as `dv.date(...)`. Use it for date math instead of native `Date` to avoid timezone surprises |
| **Karpathy's "weak second brain" gist concept** | The framing: the human ships intent; the agent does the materialization. This idea doc is itself an instance of that pattern. Your dashboard is another |

---

## Build approach

1. Open your vault in Claude Code (or your AI agent of choice).
2. Read this idea doc.
3. Pick the *one* surface that would change your behavior tomorrow morning. Start there. Add others only after the first earns its place.
4. Decide your re-render-stability strategy early — what state needs to survive a checkbox click? Wire `localStorage` before adding a third filter.
5. Wire a source link on every aggregated item before adding more views. If you can't act on what you see, the dashboard becomes a passive feed.
6. Decide your mobile story explicitly. "No mobile" is a valid answer; commit to it intentionally.
7. Generate `Home.md` to your spec.
8. Open it. Use it for a week.
9. Iterate. Add a section, drop a section, change the order, change the queries. The dashboard is a living surface — it should evolve as your work evolves.

You do not need to get it right on the first pass. You need to get it *yours*.
