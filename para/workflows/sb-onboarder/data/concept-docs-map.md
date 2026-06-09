# Concept Docs Map

Topic → doc-path map for the onboarder's `[?] Ask` help handler. When the user picks `[?]` from a step menu and names a topic, match against this table and read the linked file(s) before answering.

If no row matches, the handler falls back to: read `{sb_os_path}/CLAUDE.md`, `{sb_os_path}/docs/architecture.md`, and `{sb_os_path}/README.md`, then answer using the closest relevant section.

---

| Topic keywords | Read these files |
|----------------|------------------|
| `para`, `projects`, `areas`, `resources`, `archives` | `{sb_os_path}/docs/architecture.md` |
| `periodic`, `daily`, `weekly`, `monthly`, `quarterly` | `{sb_os_path}/docs/architecture.md` |
| `workbench`, `5-workbench`, `nested repo` | `{sb_os_path}/docs/architecture.md`, `{sb_os_path}/CLAUDE.md` |
| `tags`, `tagging` | `{sb_os_path}/CLAUDE.md` (Tags section) |
| `wiki`, `knowledge-base`, `raw`, `synthesis`, `ingest`, `wiki-query` | `{sb_os_path}/wiki/docs/wiki-schema.md`, `{sb_os_path}/wiki/claude-mds/wiki.md` |
| `home`, `dashboard`, `home.md` | `{sb_os_path}/ideas/home-dashboard.md` |
| `dataview`, `dvjs`, `templater`, `obsidian plugin` | `{sb_os_path}/ideas/home-dashboard.md` |
| `install`, `installer`, `sb-os.json`, `manifest` | `{sb_os_path}/README.md`, `{sb_os_path}/docs/architecture.md` |
| `routing`, `capture`, `where does X go` | `{sb_os_path}/para/claude-mds/root.md` |
| `agents`, `claude code`, `commands`, `skills`, `workflows` | `{sb_os_path}/docs/architecture.md`, `{sb_os_path}/CLAUDE.md` |
| `life-planner`, `sb-life-planner`, `weekly review`, `monthly review`, `quarterly review`, `objectives`, `goals`, `traps`, `intentions`, `review tier` | `{sb_os_path}/para/workflows/sb-life-planner/sb-life-planner.md`, `{sb_os_path}/para/workflows/sb-life-planner/monthly-review.md`, `{sb_os_path}/para/workflows/sb-life-planner/quarterly-review.md`, `{sb_os_path}/para/workflows/sb-onboarder/data/concept-primer.md` (Life planner section) |
| `tutor`, `learning sessions` | `{sb_os_path}/wiki/workflows/sb-tutor/sb-tutor.md` |
| `archivist`, `work-log` | `{sb_os_path}/para/workflows/sb-archivist/sb-archivist.md` |
| `rbtv`, `business plugin`, `coaching` | `{sb_os_path}/README.md` (RBTV section, if present) — fallback: tell user to visit RBTV repo |
| `marker block`, `managed claude.md` | `{sb_os_path}/docs/architecture.md` |
| `user_context_root`, `.user`, `personal extensions` | `{sb_os_path}/docs/architecture.md`, `{sb_os_path}/CLAUDE.md` |
| `context injection`, `yaml context`, `workflow context`, `personalize workflow`, `inject data`, `sb-inject-context` | `{sb_os_path}/para/rules/sb-workflow-context.md`, `{sb_os_path}/para/workflows/sb-inject-context/sb-inject-context.md`, `{sb_os_path}/para/workflows/sb-onboarder/data/concept-primer.md` (Context injection section) |
| `naming`, `kebab-case`, `prefixes` | `{sb_os_path}/CLAUDE.md`, `{sb_os_path}/docs/component-prefixes.md` |

---

## Handler protocol

1. Receive a topic string from the user.
2. Match against the keywords column (case-insensitive substring match — match any keyword in the row).
3. Read every file listed in the matched row.
4. Answer concretely using only the loaded content. Cite the file you used.
5. If no row matched, run the fallback (CLAUDE.md, architecture.md, README.md) and say so.
6. Return to the step's menu.
