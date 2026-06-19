<!-- SILVER-ABLATION FIXTURE -- DO NOT INGEST. grade=0.5 deleted=22 from=3-resources/knowledge-base/wiki/sources/every/2026-06-02-agent-native-product-management.md schema=silver-ablation/1 -->
---
type: source
created: 2026-06-02
last-touched: 2026-06-02
raw: "[[2026-06-02-agent-native-product-management.md]]"
url: https://every.to/guides/ai-product-management-guide
author: "Marcus Moretti"
related:
  - "[[compound-engineering.md]]"
  - "[[compound-engineering-plugin.md]]"
  - "[[claude-code.md]]"
  - "[[product-pulse.md]]"
  - "[[product-management.md]]"
  - "[[marcus-moretti.md]]"
tags: [source]
---

# Agent-native Product Management

## Substance

- The work is framed as a plan → ship → review → repeat loop ([[spec-driven-development.md|SDLC]]), with product management concentrated in the  and **review** stages; per , software has shifted from 20% planning / 80% execution to % planning / 20% execution, so the strategy is now the foundation.[^1]
- The strategy artifact is a `strategy.md` produced by the `ce-strategy` skill, whose structure is taken from Richard Rumelt's *Good Strategy Bad Strategy*. Five required components: **target problem** (recurring, expensive pain), **approach** (one or two sentences of guiding policy — not a goal or a feature),  (ideally one beachhead persona, per *Crossing the Chasm*),  (–5, S.M.A.R.T., value-realization not vanity), and  (2–4 multi-month capability initiatives; >4 signals lack of focus). Two optional sections — "Not working on" and "Marketing/positioning." The agent interviews the user to fill it and pushes back on vague answers; rerun every few months so the agent's sharper, context-loaded questions compound.[^1]
- Shipping no longer involves writing tickets: an issue tracker with an agent integration ( or similar — GitHub Issues or Linear) lets the agent write tickets, move the board, and keep statuses, while the human only talks about them. Status is a now/next/later Kanban (this week / next week / later), no sprints — just "In Progress" and "Done."[^1]
- The `ce-product-pulse` skill generates a [[product-pulse.md]]: an on-demand, single-page (~–40 terminal lines) product-health report with four parts —  (top bullets),  (engagement, value-realization, conversions, strategy-metric deltas), **system performance** (p50/p95/p99 latency, top- error signatures; omitted if no tracing tool), and **followups** (1– specific things to investigate). It pulls from up to four data-source categories — product analytics (PostHog, Mixpanel, Amplitude), application tracing (Datadog, Sentry, Logfire, Honeycomb), payments (Stripe, Paddle), and a read-only database connection — and skips any section whose source is absent, so a team with one source still gets a useful pulse.[^1]
- Both PM skills ship in Every's open-source , and when `docs/strategy.md` is present the other compound-engineering skills (`ce-ideate`, `ce-brainstorm`, `ce-plan`) read it as grounding. Explicitly not yet included: prioritization, pulse-to-pulse diffing, and per-stack customization paths. The author's claim is that agents reduce PM to "the interesting parts" — dreaming up features, designing, looking at data, and talking to users.[^1]

## Notable quotes

- "All of my product management work happens in conversation with, in my case, Claude Code. The conversation is the work."[^1]
- "Software development has shifted from  percent planning and 80 percent execution to  percent planning and 20 percent execution." (attributed to Kieran Klaassen)[^1]
- "You no longer read or write tickets; you just talk about them with your agent."[^1]
- "There is no substitute for talking to users. You will never cease to be surprised by what they say."[^1]

## Connections

- Extends [[compound-engineering.md]] into the product-management domain — the plan/review half of the loop, plus the `ce-strategy` and `ce-product-pulse` skills.[^1]
- Adds two product-management skills to [[compound-engineering-plugin.md]]'s catalog and a Routines-based scheduling use to [[claude-code.md]].[^1]
- Introduces [[product-pulse.md]] as a named practice; relates to [[agent-native-architecture.md]] (the workflow assumes an agent-first environment) and [[ai-coding-adoption-ladder.md]] (PM at post-AI shipping speed).[^1]
- Uses [[model-context-protocol.md]] as the connector layer for the pulse's analytics, tracing, and payments data sources.[^1]

---

## My take

---

## Sources

[^1]: [[2026-06-02-agent-native-product-management.md]]
