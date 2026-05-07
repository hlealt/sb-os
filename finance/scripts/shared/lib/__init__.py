"""Shared primitives for the bookkeeper gastos pipeline.

Both `categorize.py` (monthly close) and the one-shot `backfill.py` import
from this package. NO drift permitted — fixes land here once, both consumers
benefit. See `sb-os/finance/docs/expenses-data.md` for the binding
contracts of every public function in this package.
"""
