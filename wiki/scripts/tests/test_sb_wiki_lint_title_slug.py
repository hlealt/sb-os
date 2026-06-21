"""Tests for `title_slug` — naming-convention.md § Title-slug algorithm.

Regression focus: step 3 ("Remove ? ! , . " ' ( ) [ ] and other punctuation")
must strip `#` and any other punctuation, not only the explicitly-listed set.
A title containing `#` (e.g. "AI Matters #3: …") previously slugged to
`ai-matters-#3-…`, producing a spurious — and link-breaking — PDF rename
proposal for a file already named `ai-matters-3-…`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_MOD_PATH = _SCRIPTS_DIR / "sb-wiki-lint-deterministic.py"
_spec = importlib.util.spec_from_file_location("sb_wiki_lint_deterministic", _MOD_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["sb_wiki_lint_deterministic"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore

title_slug = _mod.title_slug


def test_hash_is_stripped():
    """The reported bug: `#` must be removed, leaving the bare number."""
    title = "AI Matters #3: A large productivity takeoff is ahead - just not immediately"
    assert title_slug(title) == (
        "ai-matters-3-a-large-productivity-takeoff-is-ahead-just-not-immediately"
    )


def test_other_punctuation_is_stripped():
    """The general "and other punctuation" clause: `&`, `;`, `@`, `%` all drop."""
    assert title_slug("Q&A: Tips @ Scale; 100% Done!") == "qa-tips-scale-100-done"


def test_canonical_examples_unchanged():
    """The naming-convention.md worked examples still slug correctly."""
    assert title_slug("International AI Safety Report 2026") == (
        "international-ai-safety-report-2026"
    )
    assert title_slug("You Only Look Once: Unified, Real-Time Object Detection") == (
        "you-only-look-once-unified-real-time-object-detection"
    )
    assert title_slug('Is there "Secret Sauce" in Large Language Model Development?') == (
        "is-there-secret-sauce-in-large-language-model-development"
    )
    assert title_slug(
        "Machine Learning: The High-Interest Credit Card of Technical Debt"
    ) == "machine-learning-the-high-interest-credit-card-of-technical-debt"
