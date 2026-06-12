"""Tests for the non-interactive target-confirm skip.

``install.py --non-interactive`` (no ``--target``) must complete with zero
prompts when an existing install is auto-detected via upward search.
Historically ``_resolve_target`` never received ``args``, so it always called
``cli.confirm("Use this as the target?")``; in a non-tty shell that confirm
hit ``EOFError`` and aborted with "Aborted by user" — even though
``--non-interactive`` promises no prompts.

Contract under test:

* ``_resolve_target(..., non_interactive=True)`` accepts the upward-detected
  install without calling ``cli.confirm``;
* ``_resolve_target(..., non_interactive=False)`` still prompts (interactive
  behavior unchanged);
* ``main(["--non-interactive"])`` from inside a vault completes EXIT 0 with
  zero prompts, wiring the detected target through to ``run_upgrade``.

The heavy upgrade internals are stubbed — the seam under test is the
target-confirm gate, not the file writes.
"""
from __future__ import annotations

import importlib.util
import os
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


def _load_entry():
    repo_root = Path(__file__).resolve().parent.parent.parent
    spec = importlib.util.spec_from_file_location(
        "sb_os_install_entry", repo_root / "install.py"
    )
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    return entry


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


class TestResolveTargetGate(unittest.TestCase):
    """``_resolve_target`` honors the non_interactive flag."""

    def setUp(self) -> None:
        self.entry = _load_entry()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        _minimal_manifest(self.root)
        self._orig_confirm = cli.confirm
        self._orig_cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self) -> None:
        os.chdir(self._orig_cwd)
        cli.confirm = self._orig_confirm
        self._tmp.cleanup()

    def test_non_interactive_accepts_without_prompt(self) -> None:
        spy = _ConfirmSpy(answer=True)
        cli.confirm = spy
        target, has_manifest = self.entry._resolve_target(
            cli, manifest, self.root, non_interactive=True
        )
        self.assertEqual(target, self.root)
        self.assertTrue(has_manifest)
        self.assertEqual(
            spy.questions, [],
            msg="non_interactive=True must accept the detected install with zero prompts",
        )

    def test_interactive_still_prompts(self) -> None:
        spy = _ConfirmSpy(answer=True)
        cli.confirm = spy
        target, has_manifest = self.entry._resolve_target(
            cli, manifest, self.root, non_interactive=False
        )
        self.assertEqual(target, self.root)
        self.assertTrue(has_manifest)
        self.assertEqual(
            len(spy.questions), 1,
            msg="interactive runs must still confirm the detected target",
        )


class TestResolveTargetNoInstall(unittest.TestCase):
    """non_interactive with no detectable install fails loud, never prompts."""

    def setUp(self) -> None:
        self.entry = _load_entry()
        self._orig_find = cli.find_manifest_upward
        self._orig_prompt = cli.prompt_target
        self._orig_confirm = cli.confirm
        cli.find_manifest_upward = lambda start: None

    def tearDown(self) -> None:
        cli.find_manifest_upward = self._orig_find
        cli.prompt_target = self._orig_prompt
        cli.confirm = self._orig_confirm

    def test_non_interactive_no_install_raises_without_prompting(self) -> None:
        def _boom(*a, **k):
            raise AssertionError("prompt_target must not be called under --non-interactive")

        cli.prompt_target = _boom
        cli.confirm = _boom
        with self.assertRaises(SystemExit) as ctx:
            self.entry._resolve_target(
                cli, manifest, Path.cwd(), non_interactive=True
            )
        # Non-zero exit; SystemExit carries an explanatory message (not None/0).
        self.assertNotIn(ctx.exception.code, (0, None))

    def test_interactive_no_install_still_prompts(self) -> None:
        captured: dict = {}

        def fake_prompt_target(default=None):
            captured["called"] = True
            return Path(default or ".").resolve()

        cli.prompt_target = fake_prompt_target
        target, has_manifest = self.entry._resolve_target(
            cli, manifest, Path.cwd(), non_interactive=False
        )
        self.assertTrue(captured.get("called"))


class TestMainNonInteractiveTarget(unittest.TestCase):
    """``main(["--non-interactive"])`` with no --target completes cleanly."""

    def setUp(self) -> None:
        self.entry = _load_entry()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        _minimal_manifest(self.root)
        self._orig_confirm = cli.confirm
        self._orig_run_upgrade = upgrade.run_upgrade
        self._orig_cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self) -> None:
        os.chdir(self._orig_cwd)
        cli.confirm = self._orig_confirm
        upgrade.run_upgrade = self._orig_run_upgrade
        self._tmp.cleanup()

    def test_no_target_non_interactive_uses_detected_install(self) -> None:
        spy = _ConfirmSpy(answer=True)
        cli.confirm = spy

        captured: dict = {}

        def fake_run_upgrade(target, sb_os, **kwargs):
            captured["target"] = target
            captured.update(kwargs)
            return 0

        upgrade.run_upgrade = fake_run_upgrade

        code = self.entry.main(["--non-interactive"])

        self.assertEqual(code, 0)
        self.assertEqual(
            spy.questions, [],
            msg="--non-interactive (no --target) must complete with zero prompts",
        )
        self.assertEqual(captured.get("target"), self.root)
        self.assertTrue(captured.get("skip_confirm"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
