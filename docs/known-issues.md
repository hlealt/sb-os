# Known Issues

Issues, limitations, and deferrals tracked for sb-os v1.

## Deferred to v2

| Item | Why deferred | Reference |
|------|--------------|-----------|
| `sb-onboarding` skill | Interactive PARA bootstrap not in v1; v1 ships static structure only via `install.py --fresh` | architecture §5, §12; Decisions Log #22 |
| `/sb-life-planner` command | Generic shipping deferred — life-planner remains a personal-only workflow under the user's `.user/` in v1; no source files shipped from sb-os | architecture §5, §12; Decisions Log #23 |
| `subagents/` source folder | No v1 sub-agents to ship; folder reintroduced in v2 with the first `sb-*` sub-agent | architecture §4, §12; Decisions Log #24 |
| Wiki contents and schema | v1 ships only the config slot (`wiki_root`), the empty default folder, and a placeholder managed CLAUDE.md; the wiki feature itself ships in v2 | architecture §12 |
| Hooks that auto-write `.claude/settings.json` | Hook snippets ship as docs only; users add manually. Auto-write deferred indefinitely (settings.json is user-managed per §8) | architecture §10 item 14, §12; Decisions Log #25 |
| `--integrate` install mode | YAGNI for v1. Add when real users hit non-sb-os PARA-like folders and request it | architecture §6, §12 |
| Automatic backup / rollback flags | YAGNI. `git tag` covers rollback for v1 | architecture §6, §12 |
| Non-Claude-Code agent harnesses | Components are written portable where possible, but Claude Code is the only validated target in v1 | architecture §12 |
