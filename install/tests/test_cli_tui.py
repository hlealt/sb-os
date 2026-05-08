"""Tests for interactive checkbox selection in install.cli."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


def _bootstrap() -> None:
    tests_dir = Path(__file__).resolve().parent
    repo_root = tests_dir.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


_bootstrap()

from install import cli  # noqa: E402
from install import tui  # noqa: E402,F401


class TestCliTuiSelection(unittest.TestCase):

    def test_prompt_modules_uses_checkbox_selection(self) -> None:
        modules = {
            "core": {
                "description": "Base system",
                "always_installed": True,
            },
            "learning": {
                "description": "Learning workflows",
            },
            "wiki": {
                "description": "Knowledge base",
                "atomic": True,
            },
        }

        with patch("install.tui.checkbox", return_value=[0, 2]) as checkbox:
            selected = cli.prompt_modules(modules, previously_selected=["wiki"])

        self.assertEqual(selected, ["core", "wiki"])
        _, items = checkbox.call_args.args
        self.assertTrue(items[0]["disabled"])
        self.assertTrue(items[0]["selected"])
        self.assertFalse(items[1]["selected"])
        self.assertTrue(items[2]["selected"])

    def test_prompt_module_components_returns_unchecked_targets(self) -> None:
        modules = {
            "core": {
                "description": "Base system",
                "skills": [
                    {
                        "name": "sb-vault-ops",
                        "target": ".claude/skills/sb-vault-ops/SKILL.md",
                        "description": "Vault edits",
                    }
                ],
                "commands": [
                    {
                        "name": "sb-onboarder",
                        "target": ".claude/commands/sb-onboarder.md",
                        "description": "Onboarding",
                    }
                ],
                "rules": [],
            }
        }
        previous = [".claude/commands/sb-onboarder.md"]

        with patch("install.cli.confirm", return_value=True):
            with patch("install.tui.checkbox", return_value=[0]) as checkbox:
                excluded = cli.prompt_module_components(modules, ["core"], previous)

        self.assertEqual(excluded, [".claude/commands/sb-onboarder.md"])
        _, items = checkbox.call_args.args
        self.assertTrue(items[0]["selected"])
        self.assertFalse(items[1]["selected"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
