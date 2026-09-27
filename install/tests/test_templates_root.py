"""Tests for the optional sb-os.json ``templates_root`` field.

Mirrors the ``finance_root`` precedent (sb-os commit 183ed3c): an absent or
empty field keeps the historical default (other users unchanged); a set
field rebases installer template targets onto the configured root and
renders the root CLAUDE.md path table at the configured location.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


def _bootstrap() -> Path:
    tests_dir = Path(__file__).resolve().parent
    repo_root = tests_dir.parent.parent
    for entry in (str(repo_root), str(repo_root / "finance" / "scripts" / "shared")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    return repo_root


_REPO_ROOT = _bootstrap()

from install import fresh, loaders, upgrade  # noqa: E402
from lib import manifest_roots  # noqa: E402


class _VaultTestCase(unittest.TestCase):
    """Test case that creates disposable vault roots with an sb-os.json."""

    def make_vault(self, fields: dict) -> Path:
        vault = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, vault, ignore_errors=True)
        vault.joinpath("sb-os.json").write_text(
            json.dumps(fields), encoding="utf-8"
        )
        return vault


_DAILY = ("para/templates/periodic-notes/Daily.md",
          ".user/config/templates/periodic-notes/Daily.md")
_REBASED_DAILY = ".user/docs/templates/periodic-notes/Daily.md"


class TestResolver(_VaultTestCase):

    def test_default_when_field_absent(self) -> None:
        vault = self.make_vault({})
        self.assertEqual(
            manifest_roots.templates_root_rel(vault),
            manifest_roots.DEFAULT_TEMPLATES_ROOT,
        )

    def test_default_when_field_empty(self) -> None:
        vault = self.make_vault({"templates_root": "  "})
        self.assertEqual(
            manifest_roots.templates_root_rel(vault),
            manifest_roots.DEFAULT_TEMPLATES_ROOT,
        )

    def test_default_when_manifest_unreadable(self) -> None:
        vault = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, vault, ignore_errors=True)
        vault.joinpath("sb-os.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(
            manifest_roots.templates_root_rel(vault),
            manifest_roots.DEFAULT_TEMPLATES_ROOT,
        )

    def test_configured_root_wins(self) -> None:
        vault = self.make_vault({"templates_root": ".user/docs/templates"})
        self.assertEqual(manifest_roots.templates_root_rel(vault), ".user/docs/templates")

    def test_rebase_identity_when_unset(self) -> None:
        vault = self.make_vault({})
        self.assertEqual(
            manifest_roots.rebase_manifest_rel(vault, _DAILY[1]), _DAILY[1]
        )

    def test_rebase_rewrites_only_default_prefix(self) -> None:
        vault = self.make_vault({"templates_root": ".user/docs/templates"})
        self.assertEqual(
            manifest_roots.rebase_manifest_rel(vault, _DAILY[1]), _REBASED_DAILY
        )
        self.assertEqual(
            manifest_roots.rebase_manifest_rel(vault, ".claude/rules/sb-foo.md"),
            ".claude/rules/sb-foo.md",
        )

    def test_finance_rebase_still_applies(self) -> None:
        vault = self.make_vault({"finance_root": ".user/docs/finance"})
        self.assertEqual(
            manifest_roots.rebase_manifest_rel(
                vault, ".user/finance/investor/source-policy.md"
            ),
            ".user/docs/finance/investor/source-policy.md",
        )


class TestTemplateRebasing(_VaultTestCase):

    def test_install_if_missing_writes_rebased_target(self) -> None:
        vault = self.make_vault({"templates_root": ".user/docs/templates"})
        written = loaders.install_template_if_missing(
            target_root=vault,
            sb_os_root=_REPO_ROOT,
            source_rel=_DAILY[0],
            target_rel=_DAILY[1],
        )
        self.assertEqual(written, vault / _REBASED_DAILY)
        self.assertTrue(written.is_file())
        self.assertFalse((vault / _DAILY[1]).exists())

    def test_install_if_missing_writes_default_target_when_unset(self) -> None:
        vault = self.make_vault({})
        written = loaders.install_template_if_missing(
            target_root=vault,
            sb_os_root=_REPO_ROOT,
            source_rel=_DAILY[0],
            target_rel=_DAILY[1],
        )
        self.assertEqual(written, vault / _DAILY[1])

    def test_fresh_plan_rebases_template_targets(self) -> None:
        vault = self.make_vault({"templates_root": ".user/docs/templates"})
        plan = fresh.build_fresh_plan(vault, _REPO_ROOT, ("core",), ())
        targets = [a.target for a in plan.actions]
        self.assertIn(_REBASED_DAILY, targets)
        self.assertNotIn(_DAILY[1], targets)

    def test_upgrade_plan_rebases_template_targets(self) -> None:
        vault = self.make_vault({"templates_root": ".user/docs/templates"})
        plan = upgrade.build_upgrade_plan(
            "3-resources/knowledge-base/", ".user/context/", ("core",), set(),
            install_wiki=False, target_root=vault,
        )
        targets = [a.target for a in plan.actions]
        self.assertIn(_REBASED_DAILY, targets)
        self.assertNotIn(_DAILY[1], targets)


class TestRootClaudeMdRendering(_VaultTestCase):

    def _source(self) -> str:
        return (_REPO_ROOT / "para" / "claude-mds" / "root.md").read_text(
            encoding="utf-8"
        )

    def test_source_carries_placeholder_not_hardcoded_default(self) -> None:
        text = self._source()
        self.assertIn("{templates_root}/periodic-notes/Daily.md", text)
        self.assertNotIn(".user/config/templates", text)

    def test_render_uses_configured_root(self) -> None:
        vault = self.make_vault({"templates_root": ".user/docs/templates"})
        rendered = loaders.render_claude_md(self._source(), vault)
        self.assertIn(_REBASED_DAILY, rendered)
        self.assertNotIn("{templates_root}", rendered)
        self.assertNotIn(".user/config/templates/", rendered)

    def test_render_defaults_to_historical_root_without_field(self) -> None:
        vault = self.make_vault({})
        rendered = loaders.render_claude_md(self._source(), vault)
        self.assertIn(_DAILY[1], rendered)
        self.assertNotIn("{templates_root}", rendered)


if __name__ == "__main__":
    unittest.main()
