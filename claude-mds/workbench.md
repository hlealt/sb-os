<!--
sb-os managed file — installs to `{vault}/5-workbench/CLAUDE.md`.

Content INSIDE `<!-- sb:start v=1 -->` ... `<!-- sb:end -->` is overwritten
on `python install.py --upgrade`. Edit it in the sb-os source repo.

Content OUTSIDE the markers is yours — list your nested repos, document
per-repo conventions, or point agents to per-repo CLAUDE.mds.
-->

<!-- sb:start v=1 -->
# 5-workbench/

Extended-PARA layer — project workspaces that maintain their own structure and version history independently of the vault.

---

## Definition

A **workbench entry** is a folder backed by an external git repository. Each entry:

1. Has its own internal layout — sb-os does NOT impose vault conventions inside it
2. Has its own commit history — independent from the vault's git
3. Hosts code or content that needs a real repo (releases, branches, CI, collaborators)

If a project has notes and tasks but no code repo, it belongs in `1-projects/{project-name}/`. If it has a code repo, the repo lives here and the per-project notes/tasks may stay in `1-projects/` and reference the repo path.

---

## Folder Convention

| Item | Rule |
|------|------|
| One folder per repo | `5-workbench/{repo-name}/` (lowercase kebab-case) |
| Repo internals | Governed by the repo's own `CLAUDE.md` and conventions — NOT by the vault's |
| Per-repo `CLAUDE.md` | Lives at the repo root. User-owned (sb-os does not manage it) |
| Vault index for the repo | Optional `1-projects/{project-name}/{project-name}.md` that links to the workbench path |
| Sub-files | Loose `.md` files at the `5-workbench/` root (siblings of repo folders) are user-owned and freeform — sb-os does not manage their structure or naming |

Use evocative folder names matching the repo: `client-website-2027/`, `ml-experiments/`, `personal-blog/`. Treat those as illustrations only — pick names that match your repos.

---

## Nested Git Repos

Subfolders under `5-workbench/` ARE independent git repositories. The contract:

- The vault's own `.gitignore` excludes them — they are not tracked by the vault repo
- Each maintains its own commit history, branches, hooks, and conventions
- Edits inside a workbench repo follow that repo's rules — never the vault's
- Commit, push, branch, and PR operations target the nested repo, not the vault

---

## Workbench vs Projects

| Question | If yes → `1-projects/` | If yes → `5-workbench/` |
|----------|------------------------|-------------------------|
| Has a code/content repo with its own version history? | | X |
| Notes, tasks, and references only? | X | |
| Needs CI, releases, branches, external collaborators? | | X |
| Time-bound goal with deadline (and no repo)? | X | |

Many real workspaces use BOTH: `1-projects/{project-name}/` for vault-side notes and tasks, plus `5-workbench/{repo-name}/` for the actual code repo. Cross-link them in the project's index file.

---

## Cross-References

- **Projects (`1-projects/`)** — vault-side companion. A workbench repo MAY have a matching project folder for tasks and notes that live in the vault.
- **Resources (`3-resources/tools/`)** — third-party installed tools (also nested git repos, also gitignored). Distinguished from workbench by purpose: workbench = your active project repos; resources/tools = installed tooling that provides functionality to the vault.

<!-- sb:end -->

<!-- Add your own content below — anything outside the sb:start/sb:end markers survives --upgrade. -->
