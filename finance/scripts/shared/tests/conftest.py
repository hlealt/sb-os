"""pytest configuration — make `lib`, `utils`, `categorize` importable.

The bookkeeper scripts directory is not on a stable PYTHONPATH, and the
implementation modules live one level above `tests/`. We insert the parent
directory at import time so `from lib.accrual import ...` and
`from utils import NORMALIZED_COLUMNS` resolve cleanly when pytest is run
from any cwd.

We also isolate the audit log so tests never write to the real vault's
audit stream. Each test gets a fresh tmp vault root for `lib.audit`.

A session-scoped fixture additionally guards the REAL assets.csv against
mutation by the suite itself (capture-before / compare-after).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
_TESTS_DIR = Path(__file__).resolve().parent
for _p in (_SCRIPTS_DIR, _TESTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------------------------------------------------------------------------
# Real assets.csv mutation guard (session-scoped)
# ---------------------------------------------------------------------------

_VAULT_ROOT = next(
    (p for p in Path(__file__).resolve().parents if (p / "CLAUDE.md").exists() and (p / ".user").is_dir()),
    None,
)
_REAL_ASSETS_CSV = (
    _VAULT_ROOT / ".user" / "finance" / "bookkeeper" / "data" / "assets.csv"
    if _VAULT_ROOT
    else None
)


@pytest.fixture(scope="session", autouse=True)
def real_assets_sha_before_suite():
    """Capture the real assets.csv SHA-256 BEFORE the first test runs.

    Mutation guard for the REAL vault file: tests must never write to it.
    `test_upsert_assets.py::test_real_assets_csv_not_mutated` consumes the
    captured hash for an in-suite comparison; the teardown re-check below
    is the backstop for tests that run after that module. Fails only if
    this very session mutated the file — never on legitimate out-of-band
    edits (no hardcoded hash to re-stamp). Yields None outside a vault.
    """
    if _REAL_ASSETS_CSV is None or not _REAL_ASSETS_CSV.exists():
        yield None
        return
    before = hashlib.sha256(_REAL_ASSETS_CSV.read_bytes()).hexdigest()
    yield before
    after = hashlib.sha256(_REAL_ASSETS_CSV.read_bytes()).hexdigest()
    if after != before:
        raise AssertionError(
            "REAL assets.csv was mutated during this test session!\n"
            f"  before suite: {before}\n"
            f"  after suite:  {after}\n"
            "A test wrote to the real file — investigate immediately."
        )


@pytest.fixture(autouse=True)
def _isolate_audit(tmp_path, monkeypatch):
    """Point lib.audit at a tmp vault root + tmp log dir for every test.

    Sets BOOKKEEPER_AUDIT_LOG_DIR so subprocess-based tests (categorize
    integration) also write into the tmp dir, not the real vault.
    """
    from lib import audit
    (tmp_path / "sb-os.json").write_text("{}", encoding="utf-8")
    audit._reset_cache_for_tests()
    monkeypatch.setattr(audit, "_VAULT_ROOT", tmp_path)
    monkeypatch.setenv("BOOKKEEPER_AUDIT_LOG_DIR", str(tmp_path / "audit"))
    for var in ("BOOKKEEPER_RUN_ID", "BOOKKEEPER_ACTOR"):
        monkeypatch.delenv(var, raising=False)
    yield
    audit._reset_cache_for_tests()
