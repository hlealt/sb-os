"""pytest configuration — make `lib`, `utils`, `categorize` importable.

The accountant scripts directory is not on a stable PYTHONPATH, and the
implementation modules live one level above `tests/`. We insert the parent
directory at import time so `from lib.accrual import ...` and
`from utils import NORMALIZED_COLUMNS` resolve cleanly when pytest is run
from any cwd.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
