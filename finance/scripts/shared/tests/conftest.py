"""pytest configuration — make `lib`, `utils`, `categorize` importable.

The bookkeeper scripts directory is not on a stable PYTHONPATH, and the
implementation modules live one level above `tests/`. We insert the parent
directory at import time so `from lib.accrual import ...` and
`from utils import NORMALIZED_COLUMNS` resolve cleanly when pytest is run
from any cwd.

We also isolate the audit log so tests never write to the real vault's
audit stream. Each test gets a fresh tmp vault root for `lib.audit`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
_TESTS_DIR = Path(__file__).resolve().parent
for _p in (_SCRIPTS_DIR, _TESTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


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
