"""Tests for the p4-9 normalize-filenames subcommand.

Covers:
- _slug_fold: fold map for all char classes (PT accents, mojibake, typographic
  quotes/dashes, emoji, ellipsis, bullet, non-breaking hyphen)
- _build_rename_map: collision detection (type A: multiple→same; type B: target exists)
- dry-run mode: rename map emitted, no files written, exit 0
- dry-run collision: exit 2 with collision payload
- execute mode: renames performed + wikilinks healed + state re-key
- creation-time rule coverage: names born via ingest must be ASCII-only

Run from the sb-os repo root:
    python -m pytest wiki/scripts/tests/test_normalize_filenames.py -v
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Import the module under test directly (hyphen in filename requires importlib).
_SCRIPT_PATH = Path(__file__).parent.parent / "sb-wiki-lint-deterministic.py"
_spec = importlib.util.spec_from_file_location("sb_wiki_lint_deterministic", _SCRIPT_PATH)
_mod = importlib.util.module_from_spec(_spec)
# Register before exec so @dataclass machinery can resolve the module.
sys.modules["sb_wiki_lint_deterministic"] = _mod
_spec.loader.exec_module(_mod)
_slug_fold = _mod._slug_fold
_build_rename_map = _mod._build_rename_map
_is_case_space_candidate = _mod._is_case_space_candidate
_count_reference_classes = _mod._count_reference_classes
_execute_normalize = _mod._execute_normalize
resolve_wiki_root = _mod.resolve_wiki_root

SCRIPT = Path(__file__).parent.parent / "sb-wiki-lint-deterministic.py"


# ---------------------------------------------------------------------------
# Fixture: minimal vault
# ---------------------------------------------------------------------------

def make_vault(tmp_path: Path) -> tuple[Path, Path]:
    """Return (vault_root, wiki_root)."""
    wiki_root = tmp_path / "kb"
    for sub in ("raw/origin-a", "wiki/sources/origin-a", "wiki/topics",
                "wiki/concepts", "wiki/entities", "wiki/logs"):
        (wiki_root / sub).mkdir(parents=True, exist_ok=True)
    (wiki_root / "logs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sb-os.json").write_text(json.dumps({
        "wiki_root": "kb",
        "user_context_root": ".user/context/",
        "sb_os_path": str(SCRIPT.parent.parent),
    }), encoding="utf-8")
    return tmp_path, wiki_root


def run_cmd(vault_root: Path, *extra_args: str) -> tuple[int, dict]:
    cmd = [sys.executable, str(SCRIPT), "normalize-filenames",
           "--vault-root", str(vault_root)] + list(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {"raw_stdout": result.stdout}
    return result.returncode, payload


# ---------------------------------------------------------------------------
# _slug_fold unit tests
# ---------------------------------------------------------------------------

class TestSlugFold:

    def test_ascii_passthrough(self):
        assert _slug_fold("hello-world") == "hello-world"

    def test_em_dash_to_hyphen(self):
        assert _slug_fold("a—b") == "a-b"

    def test_en_dash_to_hyphen(self):
        assert _slug_fold("a–b") == "a-b"

    def test_nonbreaking_hyphen_to_hyphen(self):
        assert _slug_fold("a‑b") == "a-b"

    def test_right_single_quote_dropped_after_apostrophe_fold(self):
        # ' (U+2019) → ' → dropped in post-fold (mid-word apostrophe → nothing)
        assert _slug_fold("it’s") == "its"

    def test_left_single_quote_dropped(self):
        # ' (U+2018) → drop
        assert _slug_fold("‘hello‘") == "hello"

    def test_left_double_quote_to_hyphen(self):
        # U+201C LEFT DOUBLE QUOTATION MARK and U+201D RIGHT -> -
        # leading/trailing hyphens are stripped, so use mid-word placement
        ldq = chr(0x201C)  # LEFT DOUBLE QUOTATION MARK
        rdq = chr(0x201D)  # RIGHT DOUBLE QUOTATION MARK
        assert _slug_fold('a' + ldq + 'b' + rdq + 'c') == 'a-b-c'

    def test_double_quotes_then_collapse(self):
        # Adjacent "" → -- → collapsed to -
        assert _slug_fold("“”") == ""

    def test_ellipsis_dropped(self):
        # … (U+2026) → drop
        assert _slug_fold("foo…") == "foo"

    def test_bullet_to_hyphen(self):
        # • (U+2022) → -
        assert _slug_fold("a•b") == "a-b"

    def test_pt_accent_a_tilde(self):
        # ã → a
        assert _slug_fold("são-paulo") == "sao-paulo"

    def test_pt_accent_a_acute(self):
        # á → a
        assert _slug_fold("água") == "agua"

    def test_pt_accent_e_acute(self):
        # é → e
        assert _slug_fold("café") == "cafe"

    def test_pt_accent_e_circum(self):
        # ê → e
        assert _slug_fold("mês") == "mes"

    def test_pt_accent_c_cedilla(self):
        # ç → c
        assert _slug_fold("França".lower()) == "franca"

    def test_pt_accent_o_tilde(self):
        # õ → o
        assert _slug_fold("sões") == "soes"

    def test_pt_accent_i_acute(self):
        # í → i
        assert _slug_fold("saída") == "saida"

    def test_pt_accent_o_acute(self):
        # ó → o
        assert _slug_fold("sóis") == "sois"

    def test_o_umlaut_german(self):
        # ö → o (German/Swedish)
        assert _slug_fold("könig") == "konig"

    def test_o_slash_nordic(self):
        # ø → o (Nordic)
        assert _slug_fold("ørsted") == "rsted"

    def test_mojibake_Gustav_Soderstrom(self):
        # ├Â sequence → ö → o
        # The live corpus has: gustav-s├Âderstr├Âm
        mojibake = "gustav-s├Âderstr├Âm"
        result = _slug_fold(mojibake)
        assert result == "gustav-soderstrom"

    def test_emoji_dropped(self):
        # 🎧 is U+1F3A7 — a supplementary-plane char
        assert _slug_fold("2026-06-06-\U0001f3a7-podcast-title") == "2026-06-06-podcast-title"

    def test_emoji_rocket_dropped(self):
        # 🚀 is U+1F680 — mid-word so stripping doesn't remove the adjacent hyphen
        assert _slug_fold("a-\U0001f680-launch") == "a-launch"

    def test_collapse_consecutive_hyphens(self):
        # Multiple hyphens from adjacent non-ASCII chars collapse to one
        assert _slug_fold("a——b") == "a-b"

    def test_strip_leading_trailing_hyphens(self):
        # Leading/trailing produced by dropped chars
        assert _slug_fold("…foo…") == "foo"

    def test_lowercase_guard(self):
        # Fold lowercases result
        assert _slug_fold("ABC") == "abc"

    def test_combination(self):
        # Real corpus example: curly-quoted title with em dash
        result = _slug_fold("investidores-estão-“jogando-a-toalha”-no-inter")
        assert result == "investidores-estao--jogando-a-toalha--no-inter".replace("--", "-")

    def test_dario_amodei_em_dash(self):
        # "dario-amodei-—-machines-of-loving-grace" → "dario-amodei-machines-of-loving-grace"
        result = _slug_fold("dario-amodei-—-machines-of-loving-grace")
        assert result == "dario-amodei-machines-of-loving-grace"


# ---------------------------------------------------------------------------
# _build_rename_map collision detection
# ---------------------------------------------------------------------------

class TestBuildRenameMap:

    def test_no_collisions_clean_map(self, tmp_path):
        _, wiki_root = make_vault(tmp_path)
        # Create two files with accented names that fold to distinct ASCII names.
        (wiki_root / "raw" / "origin-a" / "2026-01-01-café.md").write_text("", encoding="utf-8")
        (wiki_root / "raw" / "origin-a" / "2026-01-02-agua.md").write_text("", encoding="utf-8")
        renames, collisions = _build_rename_map(wiki_root)
        assert collisions == []
        assert len(renames) == 1
        assert renames[0][1].name == "2026-01-01-cafe.md"

    def test_collision_two_sources_fold_to_same(self, tmp_path):
        _, wiki_root = make_vault(tmp_path)
        d = wiki_root / "raw" / "origin-a"
        # Both fold to "foo.md"
        (d / "foó.md").write_text("", encoding="utf-8")   # foó → foo
        (d / "foô.md").write_text("", encoding="utf-8")   # foô → foo
        renames, collisions = _build_rename_map(wiki_root)
        assert len(collisions) == 1
        assert collisions[0]["reason"] == "multiple-sources-fold-to-same-name"

    def test_collision_target_already_exists(self, tmp_path):
        _, wiki_root = make_vault(tmp_path)
        d = wiki_root / "raw" / "origin-a"
        # Non-ASCII file that folds to a name that already exists.
        (d / "café.md").write_text("", encoding="utf-8")  # → cafe.md
        (d / "cafe.md").write_text("", encoding="utf-8")        # target already there
        renames, collisions = _build_rename_map(wiki_root)
        assert len(collisions) == 1
        assert collisions[0]["reason"] == "target-name-already-exists"

    # --- SCOPE GATE (p4-9 contract, Q1b ruling): non-ASCII-named files, PLUS
    #     case/space for not-yet-ingested raw files (owner ruling 2026-06-14) ---

    def test_ascii_uppercase_ingested_not_renamed(self, tmp_path):
        # An ASCII uppercase stem that is ALREADY ingested (its source page
        # exists) is protected — case/space normalisation never touches a file
        # with live references (owner ruling 2026-06-14).
        _, wiki_root = make_vault(tmp_path)
        (wiki_root / "raw" / "origin-a" / "My-Title.md").write_text("", encoding="utf-8")
        (wiki_root / "wiki" / "sources" / "origin-a" / "My-Title.md").write_text(
            "---\ntype: source\n---\n", encoding="utf-8")
        renames, collisions = _build_rename_map(wiki_root)
        assert collisions == []
        assert renames == []

    def test_ascii_space_stem_in_assets_not_renamed(self, tmp_path):
        # An ASCII-clean asset name with spaces inside a binary-dump folder is
        # OUT of scope (excluded_dir) — raw/_assets stays user-owned.
        _, wiki_root = make_vault(tmp_path)
        assets = wiki_root / "raw" / "_assets"
        assets.mkdir(parents=True, exist_ok=True)
        (assets / "Some Image.png").write_text("img", encoding="utf-8")
        renames, collisions = _build_rename_map(wiki_root)
        assert collisions == []
        assert renames == []

    def test_ascii_uppercase_wiki_page_not_renamed(self, tmp_path):
        # An ASCII uppercase wiki page (e.g. entities/assets/DXY.md) is NOT a
        # case/space candidate — the rule is bounded to raw/ source files.
        _, wiki_root = make_vault(tmp_path)
        d = wiki_root / "wiki" / "entities" / "assets"
        d.mkdir(parents=True, exist_ok=True)
        (d / "DXY.md").write_text("---\ntype: entity\n---\n", encoding="utf-8")
        renames, collisions = _build_rename_map(wiki_root)
        assert collisions == []
        assert renames == []

    def test_mixed_ascii_nonascii_and_case_space(self, tmp_path):
        # Mixed not-yet-ingested raw corpus (owner ruling 2026-06-14):
        #   - uppercase .md   -> case/space candidate (renamed)
        #   - .png asset      -> not a source suffix (.md/.pdf) -> stays
        #   - non-ASCII .md   -> migration candidate (renamed)
        _, wiki_root = make_vault(tmp_path)
        d = wiki_root / "raw" / "origin-a"
        (d / "My-Title.md").write_text("", encoding="utf-8")          # case  -> rename
        (d / "Some Asset.png").write_text("", encoding="utf-8")       # png   -> stays
        (d / "2026-01-01-café.md").write_text("", encoding="utf-8")    # accent -> rename
        renames, collisions = _build_rename_map(wiki_root)
        assert collisions == []
        new_names = sorted(n.name for _, n in renames)
        assert new_names == ["2026-01-01-cafe.md", "my-title.md"]


# ---------------------------------------------------------------------------
# Dry-run integration tests
# ---------------------------------------------------------------------------

class TestDryRun:

    def test_dry_run_no_nonascii_files_exit_0(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        # No non-ASCII files → rename_count == 0.
        rc, payload = run_cmd(vault)
        assert rc == 0
        assert payload["status"] == "DRY_RUN"
        assert payload["rename_count"] == 0

    def test_dry_run_detects_nonascii(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        (wiki_root / "raw" / "origin-a" / "2026-01-01-café.md").write_text("", encoding="utf-8")
        rc, payload = run_cmd(vault)
        assert rc == 0
        assert payload["rename_count"] == 1
        # path in renames is wiki-root-relative (raw/…), not vault-root-relative (kb/raw/…)
        new_path = payload["renames"][0]["new"]
        assert new_path.endswith("raw/origin-a/2026-01-01-cafe.md")

    def test_dry_run_does_not_write_files(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        old_path = wiki_root / "raw" / "origin-a" / "2026-01-01-café.md"
        old_path.write_text("content", encoding="utf-8")
        run_cmd(vault)
        # Original file must still be at old path.
        assert old_path.exists()
        assert not (wiki_root / "raw" / "origin-a" / "2026-01-01-cafe.md").exists()

    def test_dry_run_collision_exit_2(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        d = wiki_root / "raw" / "origin-a"
        (d / "foó.md").write_text("", encoding="utf-8")
        (d / "foô.md").write_text("", encoding="utf-8")
        rc, payload = run_cmd(vault)
        assert rc == 2
        assert payload["status"] == "COLLISION"
        assert payload["collision_count"] == 1

    def test_dry_run_reference_class_counts_populated(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        d = wiki_root / "raw" / "origin-a"
        (d / "2026-01-01-café.md").write_text("content", encoding="utf-8")
        # Write a topic that wikilinks to this file.
        (wiki_root / "wiki" / "topics" / "my-topic.md").write_text(
            "---\ntype: topic\n---\n\n## Scope\n\nSee [[2026-01-01-café.md]].\n",
            encoding="utf-8",
        )
        rc, payload = run_cmd(vault)
        assert rc == 0
        assert "reference_class_counts" in payload


# ---------------------------------------------------------------------------
# Execute-mode integration tests
# ---------------------------------------------------------------------------

class TestExecuteMode:

    def test_execute_renames_file(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        old = wiki_root / "raw" / "origin-a" / "2026-01-01-café.md"
        old.write_text("content", encoding="utf-8")
        out = tmp_path / "result.json"
        rc, payload = run_cmd(vault, "--execute", "--output", str(out))
        assert rc == 0
        assert not old.exists()
        new = wiki_root / "raw" / "origin-a" / "2026-01-01-cafe.md"
        assert new.exists()
        assert len(payload["renames_performed"]) == 1

    def test_execute_heals_wikilinks(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        old = wiki_root / "raw" / "origin-a" / "2026-01-01-café.md"
        old.write_text("content", encoding="utf-8")
        topic = wiki_root / "wiki" / "topics" / "my-topic.md"
        topic.write_text(
            "---\ntype: topic\n---\n\n## Scope\n\nSee [[2026-01-01-café.md]].\n",
            encoding="utf-8",
        )
        run_cmd(vault, "--execute")
        assert "2026-01-01-cafe.md" in topic.read_text(encoding="utf-8")

    def test_execute_rekeys_state_stamps(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        old_rel = "raw/origin-a/2026-01-01-café.md"
        old = wiki_root / Path(old_rel)
        old.write_text("content", encoding="utf-8")
        # Write a fake state file with a stamp for the old path.
        state = {
            "state_schema_version": "1.0",
            "mode": "check",
            "stamps": {old_rel: "deadbeef"},
            "runs_completed": 3,
        }
        state_path = wiki_root / "lint-deterministic-report.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        run_cmd(vault, "--execute")
        updated = json.loads(state_path.read_text(encoding="utf-8"))
        new_rel = "raw/origin-a/2026-01-01-cafe.md"
        assert new_rel in updated["stamps"]
        assert old_rel not in updated["stamps"]
        # runs_completed must be preserved.
        assert updated["runs_completed"] == 3

    def test_execute_state_rekey_preserves_runs_completed(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        old = wiki_root / "raw" / "origin-a" / "2026-01-01-élégant.md"
        old.write_text("c", encoding="utf-8")
        state = {
            "state_schema_version": "1.0",
            "mode": "apply",
            "stamps": {"raw/origin-a/2026-01-01-élégant.md": "abc123"},
            "runs_completed": 7,
        }
        state_path = wiki_root / "lint-deterministic-report.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        run_cmd(vault, "--execute")
        updated = json.loads(state_path.read_text(encoding="utf-8"))
        assert updated["runs_completed"] == 7

    def test_execute_mojibake_repair(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        # ├Â = U+251C U+00C2 → ö → o
        old = wiki_root / "raw" / "origin-a" / "gustav-s├Âderstr├Âm.md"
        old.write_text("content", encoding="utf-8")
        run_cmd(vault, "--execute")
        new = wiki_root / "raw" / "origin-a" / "gustav-soderstrom.md"
        assert new.exists()

    def test_execute_no_writes_to_assets_unless_renaming(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        # ASCII asset file — must NOT be renamed.
        assets = wiki_root / "raw" / "_assets"
        assets.mkdir(parents=True, exist_ok=True)
        asset = assets / "my-image.png"
        asset.write_text("img", encoding="utf-8")
        run_cmd(vault, "--execute")
        assert asset.exists()  # unchanged

    def test_dry_run_execute_parity(self, tmp_path):
        """Dry-run rename list == execute renames_performed list."""
        vault, wiki_root = make_vault(tmp_path)
        # Create several non-ASCII files.
        files = [
            "2026-01-01-café.md",
            "2026-01-02-são-paulo.md",
            "2026-01-03-dario-—-machines.md",
        ]
        for name in files:
            (wiki_root / "raw" / "origin-a" / name).write_text("c", encoding="utf-8")

        dry_rc, dry_payload = run_cmd(vault)
        assert dry_rc == 0
        dry_new_names = {r["new"] for r in dry_payload["renames"]}

        exec_out = tmp_path / "exec-result.json"
        exec_rc, exec_payload = run_cmd(vault, "--execute", "--output", str(exec_out))
        assert exec_rc == 0
        exec_new_names = {r["new"] for r in exec_payload["renames_performed"]}

        assert dry_new_names == exec_new_names


# ---------------------------------------------------------------------------
# Reference-heal coverage gap (3 shapes the original execute missed; found
# 2026-06-12 during the p4-9 corpus migration). Regression coverage per the
# task criteria: every shape healed by --execute, dry-run counts == execute
# heal counts per class, existing suite stays green.
#
# Shape 1: footnote-form [[file.md]] links on a wiki page inside the semantic
#          `assets/` content folder (wiki/entities/assets/) — the broad
#          excluded_dir() asset skip wrongly dropped that whole content folder.
# Shape 2: a root-level knowledge-base file ({wiki_root}/*.md, e.g.
#          tecer-relevant.md) — never visited by the wiki//raw/ heal loops.
# Shape 3: pending-topic-updates.md bare source-path cells (column 1, a plain
#          `wiki/sources/{origin}/{file}.md` path) — the wikilink regex healed
#          only the column-5 [[file.md]] citation cell.
# ---------------------------------------------------------------------------

class TestReferenceHealCoverageGap:

    # --- Shape 1: assets-folder content page ---

    def test_execute_heals_footnote_link_in_assets_folder(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        (wiki_root / "wiki" / "entities" / "assets").mkdir(parents=True, exist_ok=True)
        (wiki_root / "raw" / "origin-a" / "2026-são.md").write_text("c", encoding="utf-8")
        gold = wiki_root / "wiki" / "entities" / "assets" / "gold.md"
        gold.write_text(
            "---\ntype: entity\n---\n\n## Substance\n\nbody[^1]\n\n[^1]: [[2026-são.md]]\n",
            encoding="utf-8",
        )
        run_cmd(vault, "--execute")
        txt = gold.read_text(encoding="utf-8")
        assert "[[2026-sao.md]]" in txt
        assert "são" not in txt

    def test_assets_folder_link_dry_run_execute_parity(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        (wiki_root / "wiki" / "entities" / "assets").mkdir(parents=True, exist_ok=True)
        (wiki_root / "raw" / "origin-a" / "2026-são.md").write_text("c", encoding="utf-8")
        gold = wiki_root / "wiki" / "entities" / "assets" / "gold.md"
        gold.write_text("body[^1]\n\n[^1]: [[2026-são.md]]\n", encoding="utf-8")
        _, dry = run_cmd(vault)
        _, ex = run_cmd(vault, "--execute")
        assert dry["reference_class_counts"]["wikilinks"] == 1
        assert ex["wikilinks_healed"] == 1

    # --- Shape 2: root-level KB file ---

    def test_execute_heals_root_level_kb_file(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        (wiki_root / "raw" / "origin-a" / "2026-são.md").write_text("c", encoding="utf-8")
        root = wiki_root / "tecer-relevant.md"
        root.write_text("see [[2026-são.md]] here\n", encoding="utf-8")
        run_cmd(vault, "--execute")
        txt = root.read_text(encoding="utf-8")
        assert "[[2026-sao.md]]" in txt
        assert "são" not in txt

    def test_root_level_file_dry_run_execute_parity(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        (wiki_root / "raw" / "origin-a" / "2026-são.md").write_text("c", encoding="utf-8")
        (wiki_root / "tecer-relevant.md").write_text("see [[2026-são.md]] here\n", encoding="utf-8")
        _, dry = run_cmd(vault)
        _, ex = run_cmd(vault, "--execute")
        assert dry["reference_class_counts"]["root_level_files"] == 1
        assert ex["root_level_files_healed"] == 1

    def test_root_level_non_source_files_not_healed(self, tmp_path):
        # CLAUDE.md / AGENTS.md / QWEN.md / README.md at the wiki root are NOT
        # wiki content and must never be rewritten by the heal.
        vault, wiki_root = make_vault(tmp_path)
        (wiki_root / "raw" / "origin-a" / "2026-são.md").write_text("c", encoding="utf-8")
        claude = wiki_root / "CLAUDE.md"
        claude.write_text("mentions [[2026-são.md]]\n", encoding="utf-8")
        run_cmd(vault, "--execute")
        assert claude.read_text(encoding="utf-8") == "mentions [[2026-são.md]]\n"

    # --- Shape 3: pending-topic-updates.md bare source-path cell ---

    def test_execute_heals_pending_artifact_bare_path_and_wikilink(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        src = wiki_root / "wiki" / "sources" / "origin-a" / "2026-são.md"
        src.write_text("c", encoding="utf-8")
        pending = wiki_root / "pending-topic-updates.md"
        pending.write_text(
            "| source page | proposed bullet + citation |\n"
            "|---|---|\n"
            "| wiki/sources/origin-a/2026-são.md | x — [[2026-são.md]] |\n",
            encoding="utf-8",
        )
        run_cmd(vault, "--execute")
        txt = pending.read_text(encoding="utf-8")
        assert "wiki/sources/origin-a/2026-sao.md" in txt   # bare path cell healed
        assert "[[2026-sao.md]]" in txt                       # wikilink cell healed
        assert "são" not in txt

    def test_pending_artifact_dry_run_execute_parity(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        src = wiki_root / "wiki" / "sources" / "origin-a" / "2026-são.md"
        src.write_text("c", encoding="utf-8")
        pending = wiki_root / "pending-topic-updates.md"
        pending.write_text(
            "| source page | proposed bullet + citation |\n"
            "|---|---|\n"
            "| wiki/sources/origin-a/2026-são.md | x — [[2026-são.md]] |\n",
            encoding="utf-8",
        )
        _, dry = run_cmd(vault)
        _, ex = run_cmd(vault, "--execute")
        # Each row carries the renamed filename twice: bare path (col 1) + [[..]] (col 5).
        assert dry["reference_class_counts"]["pending_topic_updates_rows"] == 2
        assert ex["pending_topic_updates_healed"] == 2

    # --- All three shapes in one corpus (task criterion) ---

    def test_corpus_with_all_three_shapes_fully_healed_with_parity(self, tmp_path):
        """A fixture corpus carrying all 3 missed shapes is fully healed by
        --execute, with dry-run counts == execute heal counts per class."""
        vault, wiki_root = make_vault(tmp_path)
        (wiki_root / "wiki" / "entities" / "assets").mkdir(parents=True, exist_ok=True)

        # Two distinct renamed files: a raw source and a wiki/sources source page.
        raw_src = wiki_root / "raw" / "origin-a" / "2026-são.md"
        raw_src.write_text("c", encoding="utf-8")
        page_src = wiki_root / "wiki" / "sources" / "origin-a" / "2026-café.md"
        page_src.write_text("c", encoding="utf-8")

        # Shape 1: footnote-form link on an assets-folder content page.
        gold = wiki_root / "wiki" / "entities" / "assets" / "gold.md"
        gold.write_text("body[^1]\n\n[^1]: [[2026-são.md]]\n", encoding="utf-8")
        # Shape 2: root-level KB file.
        (wiki_root / "tecer-relevant.md").write_text(
            "see [[2026-são.md]] here\n", encoding="utf-8"
        )
        # Shape 3: pending artifact — bare path cell + [[..]] citation cell.
        (wiki_root / "pending-topic-updates.md").write_text(
            "| source page | proposed bullet + citation |\n"
            "|---|---|\n"
            "| wiki/sources/origin-a/2026-café.md | x — [[2026-café.md]] |\n",
            encoding="utf-8",
        )

        _, dry = run_cmd(vault)
        _, ex = run_cmd(vault, "--execute")
        rc = dry["reference_class_counts"]

        # Per-class parity for every shape.
        assert rc["wikilinks"] == ex["wikilinks_healed"] == 1            # shape 1
        assert rc["root_level_files"] == ex["root_level_files_healed"] == 1  # shape 2
        assert (
            rc["pending_topic_updates_rows"] == ex["pending_topic_updates_healed"] == 2
        )  # shape 3 (bare path + wikilink)

        # No residual non-ASCII reference survives anywhere.
        for f in (gold, wiki_root / "tecer-relevant.md", wiki_root / "pending-topic-updates.md"):
            assert "são" not in f.read_text(encoding="utf-8")
            assert "café" not in f.read_text(encoding="utf-8")
        assert ex["errors"] == []


# ---------------------------------------------------------------------------
# Case/space normalisation of NOT-yet-ingested raw files (owner ruling
# 2026-06-14). A raw file with no source page yet has no inbound links, so
# folding its case/spaces to canonical kebab is reference-safe. Already-ingested
# files, wiki/ pages, non-source sentinels, origin indexes, and asset dumps are
# all protected.
# ---------------------------------------------------------------------------

class TestCaseSpaceNotYetIngested:

    def test_space_in_not_yet_ingested_raw_renamed(self, tmp_path):
        _, wiki_root = make_vault(tmp_path)
        (wiki_root / "raw" / "origin-a" / "How This Ends.md").write_text("", encoding="utf-8")
        renames, collisions = _build_rename_map(wiki_root)
        assert collisions == []
        assert [n.name for _, n in renames] == ["how-this-ends.md"]

    def test_uppercase_in_not_yet_ingested_raw_renamed(self, tmp_path):
        _, wiki_root = make_vault(tmp_path)
        (wiki_root / "raw" / "origin-a" / "Made-With-ML.md").write_text("", encoding="utf-8")
        renames, _ = _build_rename_map(wiki_root)
        assert [n.name for _, n in renames] == ["made-with-ml.md"]

    def test_pdf_case_space_not_yet_ingested_renamed(self, tmp_path):
        _, wiki_root = make_vault(tmp_path)
        (wiki_root / "raw" / "origin-a" / "State of AI 2025.pdf").write_text("", encoding="utf-8")
        renames, _ = _build_rename_map(wiki_root)
        assert [n.name for _, n in renames] == ["state-of-ai-2025.pdf"]

    def test_ingested_raw_protected(self, tmp_path):
        # Source page exists → file has live references → never case/space-folded.
        _, wiki_root = make_vault(tmp_path)
        (wiki_root / "raw" / "origin-a" / "Made-With-ML.md").write_text("", encoding="utf-8")
        (wiki_root / "wiki" / "sources" / "origin-a" / "Made-With-ML.md").write_text(
            "---\ntype: source\n---\n", encoding="utf-8")
        renames, _ = _build_rename_map(wiki_root)
        assert renames == []

    def test_candidate_predicate_exclusions(self, tmp_path):
        _, wiki_root = make_vault(tmp_path)
        raw = wiki_root / "raw" / "origin-a"
        # non-source sentinel
        assert _is_case_space_candidate(raw / "README.md", wiki_root) is False
        # origin index file
        assert _is_case_space_candidate(raw / "origin-a.md", wiki_root) is False
        # wiki/ page (not raw/)
        assert _is_case_space_candidate(
            wiki_root / "wiki" / "entities" / "assets" / "DXY.md", wiki_root) is False
        # binary-dump asset folder
        assert _is_case_space_candidate(
            wiki_root / "raw" / "_assets" / "Some Image.png", wiki_root) is False
        # non source suffix
        assert _is_case_space_candidate(raw / "Some Asset.png", wiki_root) is False
        # genuine not-yet-ingested raw .md → True
        (raw / "My File.md").write_text("", encoding="utf-8")
        assert _is_case_space_candidate(raw / "My File.md", wiki_root) is True

    def test_execute_renames_case_space_file_on_disk(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        old = wiki_root / "raw" / "origin-a" / "My Draft.md"
        old.write_text("body", encoding="utf-8")
        rc, payload = run_cmd(vault, "--execute")
        assert rc == 0
        assert not old.exists()
        assert (wiki_root / "raw" / "origin-a" / "my-draft.md").exists()
        assert [r["new"] for r in payload["renames_performed"]] == [
            "raw/origin-a/my-draft.md"]

    def test_case_space_collision_with_existing_ingested_blocks(self, tmp_path):
        # "My File.md" folds to "my-file.md", which already exists (ingested) →
        # collision gate fires, nothing renamed.
        vault, wiki_root = make_vault(tmp_path)
        d = wiki_root / "raw" / "origin-a"
        (d / "My File.md").write_text("", encoding="utf-8")
        (d / "my-file.md").write_text("", encoding="utf-8")
        rc, payload = run_cmd(vault)
        assert rc == 2
        assert payload["status"] == "COLLISION"


# ---------------------------------------------------------------------------
# Bounded rescan (owner ruling 2026-06-14): --scope evaluates only the given
# file(s); an empty rename map short-circuits BOTH the count and execute corpus
# scans so a clean incoming file does O(scope) work, not O(corpus).
# ---------------------------------------------------------------------------

class TestBoundedScope:

    def test_scoped_clean_file_ignores_corpus_nonascii(self, tmp_path):
        # A non-ASCII file sits in the corpus; scoping to a DIFFERENT clean file
        # must find no rename — proving the scan never looked at the corpus.
        _, wiki_root = make_vault(tmp_path)
        (wiki_root / "raw" / "origin-a" / "2026-01-01-café.md").write_text("", encoding="utf-8")
        clean = wiki_root / "raw" / "origin-a" / "already-fine.md"
        clean.write_text("", encoding="utf-8")
        scoped, collisions = _build_rename_map(wiki_root, files=[clean])
        assert scoped == []
        assert collisions == []
        # Unscoped DOES find the corpus non-ASCII file (sanity: scope is the cause).
        full, _ = _build_rename_map(wiki_root)
        assert [n.name for _, n in full] == ["2026-01-01-cafe.md"]

    def test_scoped_to_the_stray_file_finds_it(self, tmp_path):
        _, wiki_root = make_vault(tmp_path)
        stray = wiki_root / "raw" / "origin-a" / "2026-01-01-café.md"
        stray.write_text("", encoding="utf-8")
        scoped, _ = _build_rename_map(wiki_root, files=[stray])
        assert [n.name for _, n in scoped] == ["2026-01-01-cafe.md"]

    def test_cli_scope_leaves_unscoped_stray_untouched(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        stray = wiki_root / "raw" / "origin-a" / "2026-01-01-café.md"
        stray.write_text("", encoding="utf-8")
        clean = wiki_root / "raw" / "origin-a" / "already-fine.md"
        clean.write_text("", encoding="utf-8")
        rc, payload = run_cmd(vault, "--scope", str(clean), "--execute")
        assert rc == 0
        assert payload["renames_performed"] == []
        # The unscoped stray was never evaluated → still at its original path.
        assert stray.exists()

    def test_cli_scope_ignores_paths_outside_wiki_and_assets(self, tmp_path):
        vault, wiki_root = make_vault(tmp_path)
        outside = tmp_path / "outside.md"
        outside.write_text("", encoding="utf-8")
        asset = wiki_root / "raw" / "_assets" / "Some Image.png"
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_text("", encoding="utf-8")
        rc, payload = run_cmd(vault, "--scope", str(outside), "--scope", str(asset))
        assert rc == 0
        assert payload["rename_count"] == 0

    def test_empty_rename_map_short_circuits_corpus_reads(self, tmp_path, monkeypatch):
        # The bounded-rescan win: no renames → neither count nor execute reads
        # any corpus file. Spy on the module's read_text and assert zero calls.
        _, wiki_root = make_vault(tmp_path)
        # Populate a corpus that WOULD be read on a full scan.
        (wiki_root / "wiki" / "topics" / "t.md").write_text("[[x.md]]", encoding="utf-8")
        (wiki_root / "raw" / "origin-a" / "r.md").write_text("[[x.md]]", encoding="utf-8")
        calls = {"n": 0}
        orig = _mod.read_text

        def spy(path):
            calls["n"] += 1
            return orig(path)

        monkeypatch.setattr(_mod, "read_text", spy)
        counts = _count_reference_classes(wiki_root, [])
        result = _execute_normalize(wiki_root, [])
        assert calls["n"] == 0
        assert all(v == 0 for v in counts.values())
        assert result["renames_performed"] == []
        assert result["errors"] == []
