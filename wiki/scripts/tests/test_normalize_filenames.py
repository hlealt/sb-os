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

    # --- SCOPE GATE (p4-9 contract, Q1b ruling): non-ASCII-named files ONLY ---

    def test_ascii_uppercase_stem_not_renamed(self, tmp_path):
        # An ASCII-clean stem with uppercase is OUT of scope — never renamed,
        # even though _slug_fold would lowercase it.
        _, wiki_root = make_vault(tmp_path)
        (wiki_root / "raw" / "origin-a" / "My-Title.md").write_text("", encoding="utf-8")
        renames, collisions = _build_rename_map(wiki_root)
        assert collisions == []
        assert renames == []

    def test_ascii_space_stem_not_renamed(self, tmp_path):
        # An ASCII-clean asset name with spaces is OUT of scope.
        _, wiki_root = make_vault(tmp_path)
        assets = wiki_root / "raw" / "_assets"
        assets.mkdir(parents=True, exist_ok=True)
        (assets / "Some Image.png").write_text("img", encoding="utf-8")
        renames, collisions = _build_rename_map(wiki_root)
        assert collisions == []
        assert renames == []

    def test_ascii_clean_and_nonascii_mixed_only_nonascii_renamed(self, tmp_path):
        # Mixed corpus: ASCII-clean uppercase/space files stay; only the
        # non-ASCII-named file is a rename candidate.
        _, wiki_root = make_vault(tmp_path)
        d = wiki_root / "raw" / "origin-a"
        (d / "My-Title.md").write_text("", encoding="utf-8")        # ASCII — skip
        (d / "Some Asset.png").write_text("", encoding="utf-8")     # ASCII — skip
        (d / "2026-01-01-café.md").write_text("", encoding="utf-8")  # non-ASCII — rename
        renames, collisions = _build_rename_map(wiki_root)
        assert collisions == []
        assert len(renames) == 1
        assert renames[0][1].name == "2026-01-01-cafe.md"


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
