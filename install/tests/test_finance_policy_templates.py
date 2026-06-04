"""Tests for the finance-module investor policy template bootstrap.

The finance module ships user-agnostic policy skeletons
``finance/templates/{source-policy,research-policy}.md`` installed via the
standard manifest-template mechanism to
``.user/finance/investor/{source-policy,research-policy}.md`` (architecture
§3 templates carve-out + §11 behavior change). Fresh installs bootstrap the
designed structure with ``_Fill in_`` slots; upgrade never overwrites; the
templates ship structure only — personal rows (origin-map entries, contact
UA, allowlist hosts) must never appear in the sources.
"""
from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path


def _bootstrap() -> Path:
    # <repo>/install/tests/<this-file>
    tests_dir = Path(__file__).resolve().parent
    repo_root = tests_dir.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    return repo_root


_REPO_ROOT = _bootstrap()

from install import fresh, loaders, upgrade  # noqa: E402


_SOURCE_POLICY = ("finance/templates/source-policy.md",
                  ".user/finance/investor/source-policy.md")
_RESEARCH_POLICY = ("finance/templates/research-policy.md",
                    ".user/finance/investor/research-policy.md")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _table_data_rows(text: str, heading: str) -> list[str]:
    """Return the data rows of the first markdown table under ``heading``."""
    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip().startswith(heading))
    except StopIteration:
        raise AssertionError(f"heading {heading!r} not found")
    rows = []
    in_table = False
    for ln in lines[start + 1:]:
        stripped = ln.strip()
        if stripped.startswith("|"):
            in_table = True
            rows.append(stripped)
        elif in_table:
            break
    if len(rows) < 2:
        raise AssertionError(f"no table under {heading!r}")
    return rows[2:]  # drop header + separator


class TestManifestWiring(unittest.TestCase):

    def test_finance_module_declares_both_policy_templates(self) -> None:
        scoped = loaders.select_modules(("core", "finance"))
        templates = loaders.manifest_templates(scoped)
        self.assertIn(_SOURCE_POLICY, templates)
        self.assertIn(_RESEARCH_POLICY, templates)

    def test_policy_templates_absent_without_finance(self) -> None:
        scoped = loaders.select_modules(("core",))
        templates = loaders.manifest_templates(scoped)
        self.assertNotIn(_SOURCE_POLICY, templates)
        self.assertNotIn(_RESEARCH_POLICY, templates)


class TestTemplateSources(unittest.TestCase):

    def _read(self, source_rel: str) -> str:
        path = _REPO_ROOT / source_rel
        self.assertTrue(path.is_file(), msg=f"missing template source: {path}")
        return path.read_text(encoding="utf-8")

    def test_source_policy_ships_designed_structure(self) -> None:
        text = self._read(_SOURCE_POLICY[0])
        for section in (
            "## Hard Invariant",
            "## Capture User-Agent",
            "## Source Trust Tiers",
            "### Named-Origin Map",
            "## Allowed-Use Rules",
            "## Auto-Capture Pre-Approved Origins",
        ):
            self.assertIn(section, text, msg=f"section {section!r} missing")
        self.assertIn("_Fill in", text)

    def test_research_policy_ships_designed_structure(self) -> None:
        text = self._read(_RESEARCH_POLICY[0])
        for section in (
            "## Scope",
            "## Priorities",
            "## Exclusions",
            "## Watchlist-Approval Rule",
            "## Horizon Preferences",
        ):
            self.assertIn(section, text, msg=f"section {section!r} missing")
        self.assertIn("_Fill in", text)

    def test_no_personal_rows_ship(self) -> None:
        """Origin map + allowlist are skeleton-only; no real contact email."""
        text = self._read(_SOURCE_POLICY[0])
        for heading, label in (
            ("### Named-Origin Map", "named-origin map"),
            ("## Auto-Capture Pre-Approved Origins", "auto-capture allowlist"),
        ):
            for row in _table_data_rows(text, heading):
                self.assertIn(
                    "_Fill in", row,
                    msg=f"{label} ships a concrete row: {row!r}",
                )
        for email in _EMAIL_RE.findall(text):
            self.assertTrue(
                email.rstrip("_").endswith("@example.com"),
                msg=f"non-placeholder email shipped: {email!r}",
            )


class TestInstallIfMissing(unittest.TestCase):

    def test_bootstraps_when_absent_and_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            for source_rel, target_rel in (_SOURCE_POLICY, _RESEARCH_POLICY):
                written = loaders.install_template_if_missing(
                    target_root=target,
                    sb_os_root=_REPO_ROOT,
                    source_rel=source_rel,
                    target_rel=target_rel,
                )
                self.assertEqual(written, target / target_rel)
                self.assertEqual(
                    written.read_text(encoding="utf-8"),
                    (_REPO_ROOT / source_rel).read_text(encoding="utf-8"),
                )
                # User fills the policy; a re-run must not clobber it.
                written.write_text("user-filled sentinel", encoding="utf-8")
                self.assertIsNone(loaders.install_template_if_missing(
                    target_root=target,
                    sb_os_root=_REPO_ROOT,
                    source_rel=source_rel,
                    target_rel=target_rel,
                ))
                self.assertEqual(
                    written.read_text(encoding="utf-8"), "user-filled sentinel"
                )


class TestPlanWiring(unittest.TestCase):

    def test_fresh_plan_includes_policies_when_finance_selected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = fresh.build_fresh_plan(
                Path(td),
                _REPO_ROOT,
                selected_modules=("core", "finance"),
                excluded_components=(),
            )
        targets = [a.target for a in plan.actions]
        self.assertIn(_SOURCE_POLICY[1], targets)
        self.assertIn(_RESEARCH_POLICY[1], targets)

    def test_fresh_plan_excludes_policies_without_finance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = fresh.build_fresh_plan(
                Path(td),
                _REPO_ROOT,
                selected_modules=("core",),
                excluded_components=(),
            )
        targets = [a.target for a in plan.actions]
        self.assertNotIn(_SOURCE_POLICY[1], targets)
        self.assertNotIn(_RESEARCH_POLICY[1], targets)

    def test_upgrade_plan_marks_policies_install_if_missing(self) -> None:
        plan = upgrade.build_upgrade_plan(
            "3-resources/knowledge-base/",
            ".user/context/",
            ("core", "finance"),
            set(),
            install_wiki=False,
        )
        actions = {a.target: a.detail for a in plan.actions}
        for _src, target_rel in (_SOURCE_POLICY, _RESEARCH_POLICY):
            self.assertIn(target_rel, actions)
            self.assertIn("install-if-missing", actions[target_rel])


if __name__ == "__main__":
    unittest.main()
