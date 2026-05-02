<!--
sb-os managed file — installs to `{vault}/3-resources/CLAUDE.md`.

Content INSIDE `<!-- sb:start v=1 -->` ... `<!-- sb:end -->` is overwritten
on `python install.py --upgrade`. Edit it in the sb-os source repo.

Content OUTSIDE the markers is yours — list your own resource categories,
document per-category conventions, or extend the routing rules.
-->

<!-- sb:start v=1 -->
# 3-resources/

PARA Resources layer — reference content and topics of ongoing interest. Not actively managed responsibilities (those go in `2-areas/`) or active goals (those go in `1-projects/`).

---

## Definition

A **resource** is material consulted on demand. It has:

1. No defined outcome or deadline
2. No standard of performance to uphold
3. Topical interest that may seed future projects or inform current work

When a resource starts requiring active stewardship, promote it to an area. When it seeds a time-bound goal, spin up a project.

---

## Folder Convention

| Item | Rule |
|------|------|
| Top-level subfolders | One per category. Lowercase kebab-case. Examples (replace with your own): `category-a/`, `category-b/` |
| Reserved subfolder — `tools/` | Active tooling: tool catalogs, reusable prompts, installed code repos. Provides functionality to the vault but is not itself vault content |
| Reserved subfolder — wiki | Synthesis space for consumed external content. Path is configurable per install (`wiki_root` in `sb-os.json`); the installer creates `{wiki_root}/CLAUDE.md` when the wiki feature is enabled |
| Index file | `{category-name}.md` inside each leaf category folder when it holds many similar files. Container folders (multiple subfolders with distinct purposes) skip the index — the folder's `CLAUDE.md` does the navigation |
| Sub-files | Loose `.md` files at the `3-resources/` root (siblings of category folders) are user-owned and freeform — sb-os does not manage their structure or naming |

---

## Routing Rules

| Situation | Action |
|-----------|--------|
| New tool, prompt, or installable repo | Place under `3-resources/tools/` |
| Saved external content (articles, papers, transcripts) | Place originals under `{wiki_root}/raw/`; place synthesis derived from them elsewhere under `{wiki_root}/`. Agents resolve `wiki_root` from `sb-os.json` |
| Topic of interest with no active stewardship | Create `3-resources/{category-name}/` |
| Resource gains active stewardship | Promote to `2-areas/{area-name}/` |
| Resource seeds a time-bound goal | Spin up `1-projects/{project-name}/`; the resource folder may remain as reference |

---

## Raw vs Synthesis

Saved external content splits into two layers:

- **Raw originals** — articles, papers, transcripts captured verbatim from a source. Live under `{wiki_root}/raw/` and are treated as **immutable**: never edit a saved source. The original record stays auditable.
- **Synthesis** — notes, summaries, cross-links, and structured knowledge derived from raw sources. Lives elsewhere under `{wiki_root}/` and may evolve freely.

Agents append new captures to `raw/` and write derived notes to the synthesis layer — never overwrite a raw file.

---

## Nested Git Repos

Subfolders under `3-resources/tools/` MAY be independent git repositories (installed code, third-party tooling, sb-os itself). When they are:

- The vault's own `.gitignore` excludes them — they are not tracked by the vault repo
- Each maintains its own commit history and conventions
- Edits inside an installed repo follow that repo's rules — never the vault's
- Re-installing or upgrading the repo is the supported way to update its contents

---

## Cross-References

- **Areas (`2-areas/`)** — active responsibilities. A resource may "graduate" to an area when it requires ongoing stewardship.
- **Projects (`1-projects/`)** — time-bound goals. A resource may seed a project; the original folder stays as reference.
- **Archives (`4-archives/`)** — destination when a resource is no longer relevant.

<!-- sb:end -->

<!-- =====================================================================
     User-owned section — preserved on `--upgrade`. Add anything below.
     ===================================================================== -->

<!-- Add your own content below — anything outside the sb:start/sb:end markers survives --upgrade. -->
