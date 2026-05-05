"""Test suite for the sb_os_path field added in manifest.py (v0.2.0).

Validates five assertions introduced by the p2-1 fix:

  Test 1 (fresh)       — create_initial() writes sb_os_path with the supplied value.
  Test 2 (upgrade back-fill) — update_for_upgrade() back-fills sb_os_path on a
                          legacy manifest that lacks the field.
  Test 3 (idempotency / preserve user value) — update_for_upgrade() does NOT
                          overwrite an existing sb_os_path value.
  Test 4 (no-arg upgrade) — update_for_upgrade() with no sb_os_path arg leaves
                          the field absent when the manifest lacks it.
  Test 5 (key order)   — _KEY_ORDER contains "sb_os_path" exactly once and in the
                          expected position (between user_context_root and
                          created_paths).

Run with:
  python -m pytest 3-resources/tools/sb-os/install/tests/test_manifest_sb_os_path.py -v
OR:
  python 3-resources/tools/sb-os/install/tests/test_manifest_sb_os_path.py

Both forms work. The test file uses stdlib unittest so pytest is optional.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Import bootstrap — make ``install.manifest`` importable regardless of
# the working directory from which the test is executed.
# ---------------------------------------------------------------------------

def _bootstrap() -> None:
    """Insert the sb-os repo root onto sys.path so imports resolve."""
    # This file lives at: <sb-os-repo>/install/tests/test_manifest_sb_os_path.py
    tests_dir = Path(__file__).resolve().parent
    install_dir = tests_dir.parent          # install/
    repo_root = install_dir.parent          # sb-os repo root
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


_bootstrap()

from install import manifest  # noqa: E402  (after bootstrap)


# ---------------------------------------------------------------------------
# Constants (mirror the values used by fresh.py and upgrade.py)
# ---------------------------------------------------------------------------

_DEFAULT_SB_OS_PATH = "3-resources/tools/sb-os/"
_DEFAULT_WIKI_ROOT = "3-resources/knowledge-base/"
_DEFAULT_USER_CONTEXT_ROOT = ".user/context/"
_CUSTOM_SB_OS_PATH = "custom/sb-os-location/"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _write_legacy_manifest(vault_root: Path, *, include_sb_os_path: bool = False) -> None:
    """Write a minimal v0.1.x-style manifest WITHOUT sb_os_path (or with it,
    depending on the flag) so tests can exercise the upgrade back-fill path."""
    data: dict = {
        "version": "0.1.0",
        "installed_at": "2026-01-01T00:00:00Z",
        "mode": "fresh",
        "wiki_root": _DEFAULT_WIKI_ROOT,
        "user_context_root": _DEFAULT_USER_CONTEXT_ROOT,
        "created_paths": ["1-projects/"],
    }
    if include_sb_os_path:
        data["sb_os_path"] = _CUSTOM_SB_OS_PATH
    path = vault_root / manifest.MANIFEST_FILENAME
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestManifestSbOsPath(unittest.TestCase):

    def test_1_fresh_path_writes_sb_os_path(self) -> None:
        """create_initial() must include sb_os_path in both the returned dict
        and the JSON file written by write()."""
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = Path(tmp)

            initial = manifest.create_initial(
                vault_root=vault_root,
                mode="fresh",
                wiki_root=_DEFAULT_WIKI_ROOT,
                user_context_root=_DEFAULT_USER_CONTEXT_ROOT,
                sb_os_path=_DEFAULT_SB_OS_PATH,
                created_paths=[],
            )

            # The returned dict must contain the field.
            self.assertIn(
                "sb_os_path",
                initial,
                msg="create_initial() return value missing 'sb_os_path' key",
            )
            self.assertEqual(
                initial["sb_os_path"],
                _DEFAULT_SB_OS_PATH,
                msg="create_initial() returned unexpected sb_os_path value",
            )

            # Persist and re-read to confirm write() round-trips the field.
            manifest.write(vault_root, initial)
            on_disk = manifest.read(vault_root)
            self.assertIsNotNone(on_disk, msg="manifest.read() returned None after write")
            self.assertIn(
                "sb_os_path",
                on_disk,
                msg="sb_os_path missing from persisted JSON",
            )
            self.assertEqual(
                on_disk["sb_os_path"],
                _DEFAULT_SB_OS_PATH,
                msg="Persisted sb_os_path value does not match what was written",
            )

    def test_2_upgrade_back_fills_sb_os_path(self) -> None:
        """update_for_upgrade() must back-fill sb_os_path when the existing
        manifest lacks the field; other fields must be preserved."""
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = Path(tmp)
            _write_legacy_manifest(vault_root, include_sb_os_path=False)

            updated = manifest.update_for_upgrade(
                vault_root,
                sb_os_path=_DEFAULT_SB_OS_PATH,
            )
            manifest.write(vault_root, updated)

            on_disk = manifest.read(vault_root)
            self.assertIsNotNone(on_disk)

            # sb_os_path back-filled.
            self.assertEqual(
                on_disk.get("sb_os_path"),
                _DEFAULT_SB_OS_PATH,
                msg="upgrade did not back-fill sb_os_path",
            )
            # wiki_root and user_context_root preserved.
            self.assertEqual(
                on_disk.get("wiki_root"),
                _DEFAULT_WIKI_ROOT,
                msg="upgrade corrupted wiki_root",
            )
            self.assertEqual(
                on_disk.get("user_context_root"),
                _DEFAULT_USER_CONTEXT_ROOT,
                msg="upgrade corrupted user_context_root",
            )
            # mode flipped to 'upgrade'.
            self.assertEqual(
                on_disk.get("mode"),
                "upgrade",
                msg="mode was not flipped to 'upgrade'",
            )

    def test_3_upgrade_preserves_existing_sb_os_path(self) -> None:
        """update_for_upgrade() must NOT overwrite an existing user-set
        sb_os_path — even when a different value is passed as the argument."""
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = Path(tmp)
            _write_legacy_manifest(vault_root, include_sb_os_path=True)
            # The manifest now has sb_os_path == _CUSTOM_SB_OS_PATH.

            updated = manifest.update_for_upgrade(
                vault_root,
                sb_os_path=_DEFAULT_SB_OS_PATH,  # different value — must be ignored
            )
            manifest.write(vault_root, updated)

            on_disk = manifest.read(vault_root)
            self.assertIsNotNone(on_disk)
            self.assertEqual(
                on_disk.get("sb_os_path"),
                _CUSTOM_SB_OS_PATH,
                msg=(
                    "update_for_upgrade() overwrote an existing sb_os_path; "
                    "it must preserve the user-set value verbatim"
                ),
            )

    def test_4_upgrade_no_arg_leaves_field_absent(self) -> None:
        """When update_for_upgrade() is called with no sb_os_path argument and
        the manifest lacks the field, the field must stay absent (no spurious
        empty write)."""
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = Path(tmp)
            _write_legacy_manifest(vault_root, include_sb_os_path=False)

            # No sb_os_path argument passed.
            updated = manifest.update_for_upgrade(vault_root)
            manifest.write(vault_root, updated)

            on_disk = manifest.read(vault_root)
            self.assertIsNotNone(on_disk)
            self.assertNotIn(
                "sb_os_path",
                on_disk,
                msg=(
                    "update_for_upgrade(no arg) wrote sb_os_path when neither "
                    "the existing manifest nor the caller provided a value"
                ),
            )

    def test_5_key_order_contains_sb_os_path(self) -> None:
        """_KEY_ORDER must contain 'sb_os_path' exactly once and positioned
        between 'user_context_root' and 'created_paths'."""
        key_order = manifest._KEY_ORDER
        self.assertIn(
            "sb_os_path",
            key_order,
            msg="'sb_os_path' is missing from manifest._KEY_ORDER",
        )
        count = list(key_order).count("sb_os_path")
        self.assertEqual(
            count,
            1,
            msg=f"'sb_os_path' appears {count} time(s) in _KEY_ORDER; expected exactly 1",
        )
        idx = list(key_order).index("sb_os_path")
        try:
            idx_ucr = list(key_order).index("user_context_root")
            idx_cp = list(key_order).index("created_paths")
        except ValueError as exc:
            self.fail(f"_KEY_ORDER is missing a required field: {exc}")

        self.assertGreater(
            idx,
            idx_ucr,
            msg="'sb_os_path' must come AFTER 'user_context_root' in _KEY_ORDER",
        )
        self.assertLess(
            idx,
            idx_cp,
            msg="'sb_os_path' must come BEFORE 'created_paths' in _KEY_ORDER",
        )


# ---------------------------------------------------------------------------
# Entry point for direct execution (stdlib only — no pytest required)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
