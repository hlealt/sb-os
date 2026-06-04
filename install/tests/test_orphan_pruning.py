"""Tests for orphaned-loader pruning on upgrade.

A component rename or removal deletes its ``module-manifest.json`` entry,
so the selection-aware cleanup (``upgrade._clear_orphans``) — which derives
its universe from the CURRENT manifest — can no longer see the old loader.
The orphan-pruning pass closes the gap: scan installed loaders, keep only
those that are sb-os-shaped (their ``Read and execute`` directive resolves
into ``sb_os_path``) AND absent from the manifest, and delete them.

Safety contract under test:

* non-sb-os loaders (RBTV, personal) are NEVER flagged;
* targets present anywhere in the manifest are NEVER flagged;
* targets listed in ``excluded_components`` are NEVER flagged;
* planned deletions surface in the upgrade plan.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


def _bootstrap() -> None:
    # <repo>/install/tests/<this-file>
    tests_dir = Path(__file__).resolve().parent
    repo_root = tests_dir.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


_bootstrap()

from install import loaders, upgrade  # noqa: E402


SB_OS_PATH = "3-resources/tools/sb-os"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestFindOrphanedLoaders(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- detection ------------------------------------------------------

    def test_detects_orphaned_command_loader(self) -> None:
        _write(
            self.root / ".claude" / "commands" / "bookkeeper.md",
            f"Read and execute `{SB_OS_PATH}/finance/commands/bookkeeper.md`.\n",
        )
        orphans = loaders.find_orphaned_loaders(
            self.root, SB_OS_PATH, known_targets=set()
        )
        self.assertEqual(orphans, [".claude/commands/bookkeeper.md"])

    def test_detects_orphaned_skill_loader(self) -> None:
        _write(
            self.root / ".claude" / "skills" / "old-skill" / "SKILL.md",
            "---\n"
            "name: old-skill\n"
            "description: d\n"
            "---\n"
            "\n"
            f"Read and execute `{SB_OS_PATH}/para/skills/old-skill/SKILL.md`.\n",
        )
        orphans = loaders.find_orphaned_loaders(
            self.root, SB_OS_PATH, known_targets=set()
        )
        self.assertEqual(orphans, [".claude/skills/old-skill/SKILL.md"])

    # -- safety: never flag --------------------------------------------

    def test_keeps_loader_with_manifest_entry(self) -> None:
        target = ".claude/commands/sb-bookkeeper.md"
        _write(
            self.root / Path(target),
            f"Read and execute `{SB_OS_PATH}/finance/commands/sb-bookkeeper.md`.\n",
        )
        orphans = loaders.find_orphaned_loaders(
            self.root, SB_OS_PATH, known_targets={target}
        )
        self.assertEqual(orphans, [])

    def test_ignores_non_sb_os_loader(self) -> None:
        _write(
            self.root / ".claude" / "commands" / "rbtv-digest.md",
            "Read and execute `3-resources/tools/rbtv/commands/digest.md`.\n",
        )
        _write(
            self.root / ".claude" / "skills" / "mentor" / "SKILL.md",
            "---\nname: mentor\n---\n\n"
            "Read and execute `.user/workflows/mentor/mentor.md`.\n",
        )
        orphans = loaders.find_orphaned_loaders(
            self.root, SB_OS_PATH, known_targets=set()
        )
        self.assertEqual(orphans, [])

    def test_ignores_file_without_read_directive(self) -> None:
        _write(
            self.root / ".claude" / "skills" / "custom" / "SKILL.md",
            "---\nname: custom\n---\n\nA fully self-contained user skill.\n",
        )
        orphans = loaders.find_orphaned_loaders(
            self.root, SB_OS_PATH, known_targets=set()
        )
        self.assertEqual(orphans, [])

    def test_respects_excluded_components(self) -> None:
        target = ".claude/commands/bookkeeper.md"
        _write(
            self.root / Path(target),
            f"Read and execute `{SB_OS_PATH}/finance/commands/bookkeeper.md`.\n",
        )
        orphans = loaders.find_orphaned_loaders(
            self.root, SB_OS_PATH, known_targets=set(), excluded={target}
        )
        self.assertEqual(orphans, [])

    def test_prefix_match_is_path_segment_aware(self) -> None:
        # A loader into `3-resources/tools/sb-os-extras/...` must NOT match
        # sb_os_path `3-resources/tools/sb-os`.
        _write(
            self.root / ".claude" / "commands" / "extra.md",
            "Read and execute `3-resources/tools/sb-os-extras/commands/extra.md`.\n",
        )
        orphans = loaders.find_orphaned_loaders(
            self.root, SB_OS_PATH, known_targets=set()
        )
        self.assertEqual(orphans, [])

    def test_missing_claude_dir_returns_empty(self) -> None:
        orphans = loaders.find_orphaned_loaders(
            self.root, SB_OS_PATH, known_targets=set()
        )
        self.assertEqual(orphans, [])

    # -- rename scenario: exactly one loader per manifest entry ----------

    def test_rename_leaves_one_loader_per_entry(self) -> None:
        # Simulate the bookkeeper -> sb-bookkeeper rename: both loaders on
        # disk, only the new name in the manifest.
        old = ".claude/commands/bookkeeper.md"
        new = ".claude/commands/sb-bookkeeper.md"
        _write(
            self.root / Path(old),
            f"Read and execute `{SB_OS_PATH}/finance/commands/bookkeeper.md`.\n",
        )
        _write(
            self.root / Path(new),
            f"Read and execute `{SB_OS_PATH}/finance/commands/sb-bookkeeper.md`.\n",
        )
        orphans = loaders.find_orphaned_loaders(
            self.root, SB_OS_PATH, known_targets={new}
        )
        self.assertEqual(orphans, [old])


class TestPruneExecution(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_prune_deletes_command_loader(self) -> None:
        f = self.root / ".claude" / "commands" / "bookkeeper.md"
        _write(f, "Read and execute `x`.\n")
        upgrade._prune_orphaned_loaders(
            self.root, [".claude/commands/bookkeeper.md"]
        )
        self.assertFalse(f.exists())

    def test_prune_deletes_skill_loader_and_empty_dir(self) -> None:
        f = self.root / ".claude" / "skills" / "old-skill" / "SKILL.md"
        _write(f, "Read and execute `x`.\n")
        upgrade._prune_orphaned_loaders(
            self.root, [".claude/skills/old-skill/SKILL.md"]
        )
        self.assertFalse(f.exists())
        self.assertFalse(f.parent.exists(), msg="empty skill dir must be removed")

    def test_prune_preserves_skill_dir_with_user_files(self) -> None:
        skill_dir = self.root / ".claude" / "skills" / "old-skill"
        _write(skill_dir / "SKILL.md", "Read and execute `x`.\n")
        _write(skill_dir / "notes.md", "user-added file\n")
        upgrade._prune_orphaned_loaders(
            self.root, [".claude/skills/old-skill/SKILL.md"]
        )
        self.assertFalse((skill_dir / "SKILL.md").exists())
        self.assertTrue(
            (skill_dir / "notes.md").exists(),
            msg="user files in the skill dir must survive pruning",
        )


class TestPlanSurfacing(unittest.TestCase):

    def test_plan_lists_orphan_deletions(self) -> None:
        plan = upgrade.build_upgrade_plan(
            wiki_root="3-resources/knowledge-base/",
            user_context_root=".user/context/",
            orphaned_loaders=[".claude/commands/bookkeeper.md"],
        )
        deletions = [
            a for a in plan.actions
            if a.target == ".claude/commands/bookkeeper.md"
            and a.category == "delete"
            and "delete" in a.detail.lower()
        ]
        self.assertEqual(len(deletions), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
