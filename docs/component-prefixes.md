# Component Prefixes

Prefix system for system components (workflow folders, skills, commands, rules) inside an sb-os install.

## Prefix Tiers

| Prefix | Scope | Meaning | Examples |
|--------|-------|---------|----------|
| `sb-` | Vault-native, shareable | Components shipped by sb-os. Fully user-agnostic — no personal paths, data, or routing. Open-source ready. | `sb-archivist`, `sb-vault-ops`, `sb-tutor` |
| `{plugin}-` | Plugin | Installed from a third-party plugin repo via its own installer. Overwritten on re-install. Source of truth is the plugin repo. | `rbtv-commit`, `rbtv-web-searching` |
| *(none)* | Personal or not-yet-agnostic | Contains user-specific content (paths, sync targets, guard entries, personal routing). Not shareable without refactoring. | personal workflows under `.user/` |

## Qualifying for `sb-`

A component qualifies for the `sb-` prefix when it contains NO:

- User-specific file paths or sync targets
- Personal routing tables or guard entries
- Hardcoded references to a specific vault's directory structure
- Examples that only make sense for one user

User-specific data that a component needs at runtime must come from context injection (configured user-context root, default `.user/context/`), not from the component file itself.

## Relationship to Other Conventions

| Convention | Governed by |
|------------|-------------|
| What skills vs commands are named after (activity vs role) | sb-os component conventions (`{sb_os_path}/workflows/sb-vault-ops/data/components.md`) |
| Where prefixed components are placed | The vault root `CLAUDE.md` shipped by sb-os → Component Placement |
| sb-os source-of-truth rules | The installed sb-os components are thin loaders or copies — never edit them directly; edit at the source repo |
