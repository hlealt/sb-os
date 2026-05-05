"""Smoke tests for the module-aware loader generators introduced when sb-os
shippable components were split into per-module folders (`para/` and `wiki/`).

Each generator now requires a `module` argument and emits paths of the form
``{sb_os_path}/{module}/<kind>/<name>...``. The manifest declares the owning
module on every component via the `module` field; loaders.py reads it.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path


def _bootstrap() -> None:
    # <repo>/install/tests/<this-file>
    tests_dir = Path(__file__).resolve().parent
    repo_root = tests_dir.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


_bootstrap()

from install import loaders  # noqa: E402


class TestModuleAwareLoaders(unittest.TestCase):

    def test_skill_loader_includes_module_segment(self) -> None:
        text = loaders.generate_skill_loader(
            name="sb-vault-ops",
            sb_os_path="3-resources/tools/sb-os",
            module="para",
            description="d",
        )
        self.assertIn(
            "Read and execute `3-resources/tools/sb-os/para/skills/sb-vault-ops/SKILL.md`.",
            text,
        )

    def test_command_loader_includes_module_segment(self) -> None:
        text = loaders.generate_command_loader(
            name="sb-wiki-ingest",
            sb_os_path="3-resources/tools/sb-os",
            module="wiki",
        )
        self.assertEqual(
            text.strip(),
            "Read and execute `3-resources/tools/sb-os/wiki/commands/sb-wiki-ingest.md`.",
        )

    def test_missing_module_raises(self) -> None:
        with self.assertRaises(ValueError):
            loaders.generate_skill_loader(
                name="x",
                sb_os_path="repo",
                module="",
            )

    def test_module_with_slash_rejected(self) -> None:
        with self.assertRaises(ValueError):
            loaders.generate_command_loader(
                name="x",
                sb_os_path="repo",
                module="para/extra",
            )

    def test_manifest_entries_carry_module_field(self) -> None:
        skills = loaders.manifest_skills()
        commands = loaders.manifest_commands()
        rules = loaders.manifest_rules()
        for name, _desc, module in skills:
            self.assertIn(module, {"para", "wiki"}, msg=f"skill {name}")
        for name, module in commands:
            self.assertIn(module, {"para", "wiki"}, msg=f"command {name}")
        for filename, module in rules:
            self.assertIn(module, {"para", "wiki"}, msg=f"rule {filename}")

    def test_manifest_rule_sources_paths_module_prefixed(self) -> None:
        for filename, source_rel, module in loaders.manifest_rule_sources():
            self.assertTrue(
                source_rel.startswith(f"{module}/rules/"),
                msg=f"rule {filename} source {source_rel!r} not under {module}/rules/",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
