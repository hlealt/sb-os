<!--
sb-os managed file — installs to `{vault}/{wiki_root}/CLAUDE.md` when the
wiki feature is enabled. `wiki_root` is configured in `sb-os.json` (default:
`3-resources/knowledge-base/`). Content INSIDE markers is overwritten on
`python install.py --upgrade`; content OUTSIDE is preserved.

v1 placeholder — wiki contents and schema deferred to v2 (architecture §12).
-->

<!-- sb:start v=1 -->
# {wiki_root}/

Wiki root — synthesis space for consumed external content. Path configured at install time (`wiki_root` in `sb-os.json`).

Synthesized knowledge (your summaries, cross-links, atomic notes, topic pages) lives here. Raw consumption — original articles, papers, transcripts — belongs in a sibling `raw/` folder under the same parent.

**v1 placeholder.** Wiki schema is deferred to v2. Until then, populate this folder with your own convention (Zettelkasten, MOCs, topic pages — your choice) and document it in the user-owned section below.

<!-- sb:end -->

<!-- =====================================================================
     User-owned section — preserved on `--upgrade`. Add anything below.
     ===================================================================== -->

<!-- Add your own content below — anything outside the sb:start/sb:end markers survives --upgrade. -->
