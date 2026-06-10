"""Tests for the non-interactive upgrade confirm skip.

``install.py --non-interactive`` must complete an upgrade with zero
prompts. Historically ``main()`` passed ``skip_confirm`` to ``run_fresh``
but never to ``run_upgrade``, so scripted upgrades stalled on the
"Proceed with the upgrade?" prompt.

Contract under test:

* ``run_upgrade(..., skip_confirm=True)`` never calls ``cli.confirm``;
* the default (``skip_confirm=False``) still prompts exactly once —
  interactive runs keep their confirm;
* declining the interactive confirm still aborts;
* ``main(["--target", X, "--non-interactive"])`` wires
  ``skip_confirm=True`` through to ``run_upgrade``.

The heavy internals (``_preflight_markers``, ``_execute_upgrade``) are
stubbed — the seam under test is the confirm gate, not the file writes.
"""
from __future__ import annotations

import importlib.util
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

from install import cli, manifest, upgrade  # noqa: E402


def _minimal_manifest(root: Path) -> None:
    manifest.write(root, {
        "version": manifest.VERSION,
        "installed_at": "2026-01-01T00:00:00Z",
        "mode": "fresh",
        "wiki_root": "3-resources/knowledge-base/",
        "user_context_root": ".user/context/",
        "sb_os_path": "sb-os/",
        "selected_modules": ["core"],
        "excluded_components": [],
        "created_paths": [],
    })


class _ConfirmSpy:
    """Recording stand-in for ``cli.confirm`` with a fixed answer."""

    def __init__(self, answer: bool = True) -> None:
        self.answer = answer
        self.questions: list[str] = []

    def __call__(self, question: str, default: bool = True) -> bool:
        self.questions.append(question)
        return self.answer


class TestUpgradeConfirmGate(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        _minimal_manifest(self.root)
        # sb-os clone path inside the vault — pure path math, never read
        # because _execute_upgrade is stubbed out.
        self.sb_os_root = self.root / "sb-os"
        self._orig_preflight = upgrade._preflight_markers
        self._orig_execute = upgrade._execute_upgrade
        self._orig_confirm = cli.confirm
        upgrade._preflight_markers = lambda *a, **k: True
        upgrade._execute_upgrade = lambda **k: []

    def tearDown(self) -> None:
        upgrade._preflight_markers = self._orig_preflight
        upgrade._execute_upgrade = self._orig_execute
        cli.confirm = self._orig_confirm
        self._tmp.cleanup()

    def test_skip_confirm_true_never_prompts(self) -> None:
        spy = _ConfirmSpy(answer=True)
        cli.confirm = spy
        code = upgrade.run_upgrade(
            self.root, self.sb_os_root, skip_confirm=True
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            spy.questions, [],
            msg="skip_confirm=True must complete with zero prompts",
        )

    def test_default_still_prompts_once(self) -> None:
        spy = _ConfirmSpy(answer=True)
        cli.confirm = spy
        code = upgrade.run_upgrade(self.root, self.sb_os_root)
        self.assertEqual(code, 0)
        self.assertEqual(len(spy.questions), 1)
        self.assertIn("Proceed with the upgrade?", spy.questions[0])

    def test_default_decline_aborts(self) -> None:
        spy = _ConfirmSpy(answer=False)
        cli.confirm = spy
        with self.assertRaises(SystemExit):
            upgrade.run_upgrade(self.root, self.sb_os_root)


class TestMainWiring(unittest.TestCase):

    def test_non_interactive_passes_skip_confirm_to_run_upgrade(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent.parent
        spec = importlib.util.spec_from_file_location(
            "sb_os_install_entry", repo_root / "install.py"
        )
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _minimal_manifest(root)

            captured: dict = {}

            def fake_run_upgrade(target, sb_os, **kwargs):
                captured.update(kwargs)
                return 0

            orig = upgrade.run_upgrade
            upgrade.run_upgrade = fake_run_upgrade
            try:
                code = entry.main(["--target", str(root), "--non-interactive"])
            finally:
                upgrade.run_upgrade = orig

            self.assertEqual(code, 0)
            self.assertTrue(
                captured.get("skip_confirm"),
                msg="--non-interactive must pass skip_confirm=True to run_upgrade",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
