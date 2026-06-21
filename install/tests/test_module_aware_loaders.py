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
            description="Two-stage ingest of a raw source into the wiki.",
        )
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("description: Two-stage ingest of a raw source into the wiki.", text)
        self.assertIn(
            "Read and execute `3-resources/tools/sb-os/wiki/commands/sb-wiki-ingest.md`.",
            text,
        )

    def test_command_description_sourced_from_frontmatter(self) -> None:
        cmds = {name: desc for name, desc, _mod in loaders.manifest_commands()}
        # sb-wiki-ingest-all's description contains a colon — exercises the
        # single-quote round-trip through the frontmatter parser.
        self.assertIn("sb-wiki-ingest-all", cmds)
        self.assertEqual(
            cmds["sb-wiki-ingest-all"],
            "Backfill the wiki: ingest every non-ingested raw source via "
            "one sub-agent per source (Sonnet for small sources, Opus for "
            "sources at or above 5k tokens), run strictly sequentially, then "
            "lint. A bare large/small keyword scopes the run by size.",
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
        # The declared module must be a real on-disk module folder (para, wiki,
        # finance, ...). Checking the folder exists keeps this test from going
        # stale every time a new module folder is added.
        repo_root = Path(__file__).resolve().parent.parent.parent

        def _valid(module: str) -> bool:
            return bool(module) and "/" not in module and (repo_root / module).is_dir()

        skills = loaders.manifest_skills()
        commands = loaders.manifest_commands()
        rules = loaders.manifest_rules()
        for name, _desc, module in skills:
            self.assertTrue(_valid(module), msg=f"skill {name}: module {module!r} is not an on-disk folder")
        for name, _desc, module in commands:
            self.assertTrue(_valid(module), msg=f"command {name}: module {module!r} is not an on-disk folder")
        for filename, module in rules:
            self.assertTrue(_valid(module), msg=f"rule {filename}: module {module!r} is not an on-disk folder")

    def test_skill_description_sourced_from_frontmatter(self) -> None:
        # sb-vault-ops' source SKILL.md frontmatter carries the long, narrowed
        # description; the manifest's old short string must NOT be what ships.
        skills = {name: desc for name, desc, _mod in loaders.manifest_skills()}
        self.assertIn("sb-vault-ops", skills)
        self.assertTrue(
            skills["sb-vault-ops"].startswith("Use when creating or routing tasks"),
            msg=f"expected frontmatter-sourced description, got: {skills['sb-vault-ops']!r}",
        )
        self.assertNotEqual(
            skills["sb-vault-ops"],
            "Gatekeeper for vault content and component modifications.",
            msg="skill description must come from SKILL.md frontmatter, not the manifest",
        )

    def test_manifest_carries_no_skill_descriptions(self) -> None:
        import json

        manifest_path = Path(__file__).resolve().parent.parent / "module-manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        for mod_name, mod in data["modules"].items():
            for skill in mod.get("skills", []):
                self.assertNotIn(
                    "description", skill,
                    msg=f"skill {skill.get('name')!r} in module {mod_name!r} still has a manifest description",
                )

    def test_manifest_carries_no_command_descriptions(self) -> None:
        import json

        manifest_path = Path(__file__).resolve().parent.parent / "module-manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        for mod_name, mod in data["modules"].items():
            for cmd in mod.get("commands", []):
                self.assertNotIn(
                    "description", cmd,
                    msg=f"command {cmd.get('name')!r} in module {mod_name!r} still has a manifest description",
                )

    def test_parse_frontmatter_description_variants(self) -> None:
        self.assertEqual(
            loaders._parse_frontmatter_description("---\nname: x\ndescription: hello world\n---\nbody"),
            "hello world",
        )
        self.assertEqual(
            loaders._parse_frontmatter_description("---\ndescription: 'quoted: ok'\n---\n"),
            "quoted: ok",
        )
        self.assertIsNone(loaders._parse_frontmatter_description("no frontmatter here"))
        self.assertIsNone(loaders._parse_frontmatter_description("---\nname: x\n---\n"))

    def test_manifest_rule_sources_paths_module_prefixed(self) -> None:
        for filename, source_rel, module in loaders.manifest_rule_sources():
            self.assertTrue(
                source_rel.startswith(f"{module}/rules/"),
                msg=f"rule {filename} source {source_rel!r} not under {module}/rules/",
            )

    def test_flatten_skips_stale_entries(self) -> None:
        modules = {
            "core": {
                "rules": [
                    {"name": "live", "target": ".claude/rules/live.md", "module": "para"},
                    {"name": "dead", "target": ".claude/rules/dead.md", "module": "para", "stale": True},
                ]
            }
        }
        names = [e["name"] for e in loaders._flatten(modules, "rules")]
        self.assertIn("live", names)
        self.assertNotIn("dead", names, msg="stale entry must be skipped by _flatten")

    def test_stale_rules_excluded_from_manifest_rules(self) -> None:
        rule_names = {fn for fn, _mod in loaders.manifest_rules()}
        self.assertNotIn("sb-user-preferences.md", rule_names)
        self.assertNotIn("sb-workflow-context.md", rule_names)
        # non-stale core rules are still shipped
        self.assertIn("sb-source-of-truth.md", rule_names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
