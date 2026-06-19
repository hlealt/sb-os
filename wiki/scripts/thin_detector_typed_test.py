#!/usr/bin/env python3
"""Unit tests for thin_detector_typed.py.

Primary purpose: VALIDATE T3 table-row retention (row-shingle + token-set
fallback). The calibration silver-ablation set has ZERO table-bearing ablations
(keystone flag in calibration/README design notes), so T3 cannot be validated
against the manifest -- it is proven here with CONSTRUCTED table fixtures. These
are legitimate for T3 because no real table ablation exists yet; calibration-set
T3 coverage is a documented backfill follow-up, NOT faked gold.

Also covers: numeric multiset retention (the count-aware fix), min-count guards,
the compare-set boundary (My take / Sources excluded), and named-entity /
caveat / rule-label retention on small constructed pages.

Run:
    python thin_detector_typed_test.py            # all tests
    python thin_detector_typed_test.py -v         # verbose

Exit 0 = all pass; non-zero = a failure (unittest convention).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import thin_detector_typed as td  # noqa: E402


def _page(substance: str = "", methodology: str = "", notable: str = "",
          counterpoints: str = "", my_take: str = "", sources: str = "") -> str:
    """Build a minimal source page with the given section bodies."""
    parts = ["---", "type: source", "tags: [source]", "---", "", "# Test page", ""]
    if substance:
        parts += ["## Substance", "", substance, ""]
    if counterpoints:
        parts += ["## Counterpoints", "", counterpoints, ""]
    if methodology:
        parts += ["## Methodology", "", methodology, ""]
    if notable:
        parts += ["## Notable quotes", "", notable, ""]
    parts += ["---", ""]
    if my_take:
        parts += ["## My take", "", my_take, ""]
    parts += ["## Sources", "", sources or "[^1]: [[raw.md]]", ""]
    return "\n".join(parts)


# Reusable table fixtures --------------------------------------------------
TABLE_RAW = """\
Comparison of approaches:

| Approach | Cost | Latency |
|----------|------|---------|
| Amortized hardware | $40M | low |
| Cloud rental | $30M | medium |
| Bottom-up BoM | $5,000 per unit | high |
"""

# page that KEEPS every row verbatim
TABLE_PAGE_FULL = TABLE_RAW

# page that DROPS the whole table
TABLE_PAGE_NO_TABLE = "Approaches are compared in the paper across cost and latency.\n"

# page that keeps a PARAPHRASED version of one row (token overlap >= 0.72) and
# drops the other two rows
TABLE_PAGE_PARAPHRASED = """\
| Approach | Cost | Latency |
|----------|------|---------|
| Amortized hardware | $40M | low |
"""


class TestTableRowT3(unittest.TestCase):
    """T3 row-shingle + token-set fallback -- the class the calibration set
    cannot exercise (zero table ablations)."""

    def test_full_table_retained_no_missing(self):
        raw = _page(substance=TABLE_RAW)
        page = _page(substance=TABLE_PAGE_FULL)
        rep = td.detect(page, raw)
        cr = rep.classes["table_row"]
        self.assertFalse(cr.skipped, "table_row should not be skipped (3 rows >= floor 1)")
        self.assertEqual(cr.missing_count, 0, "verbatim-kept rows must report 0 missing")
        self.assertEqual(cr.retention, 1.0)

    def test_whole_table_dropped_all_rows_missing(self):
        raw = _page(substance=TABLE_RAW)
        page = _page(substance=TABLE_PAGE_NO_TABLE)
        rep = td.detect(page, raw)
        cr = rep.classes["table_row"]
        self.assertFalse(cr.skipped)
        # 3 data rows + 1 header row = 4 rows extracted from raw (separator excluded)
        self.assertEqual(cr.raw_count, 4)
        self.assertEqual(cr.missing_count, 4, "a fully dropped table -> every row missing")
        self.assertEqual(cr.retention, 0.0, "table fully absent -> retention 0 (hard flag)")
        self.assertTrue(rep.flagged)

    def test_token_set_fallback_matches_paraphrased_row(self):
        # The kept row is byte-identical here, but the OTHER two rows are absent.
        # Verify exact-shingle match keeps the identical row and the two dropped
        # rows are reported missing (header + the kept row survive => 2 missing).
        raw = _page(substance=TABLE_RAW)
        page = _page(substance=TABLE_PAGE_PARAPHRASED)
        rep = td.detect(page, raw)
        cr = rep.classes["table_row"]
        missing_texts = [m.text for m in cr.missing]
        self.assertTrue(any("Cloud rental" in t for t in missing_texts),
                        "the dropped 'Cloud rental' row must be reported missing")
        self.assertTrue(any("Bottom-up" in t for t in missing_texts),
                        "the dropped 'Bottom-up BoM' row must be reported missing")
        self.assertFalse(any("Amortized hardware" in t for t in missing_texts),
                         "the kept 'Amortized hardware' row must NOT be reported missing")

    def test_token_set_fallback_on_reordered_cells(self):
        # A row whose cells are reordered/reworded but shares >= 0.72 of tokens
        # should be matched by the token-set fallback (NOT reported missing).
        raw = _page(substance=(
            "| Method | Annual cost | Notes |\n"
            "|--------|-------------|-------|\n"
            "| GPT-4 training run | 40 million dollars | amortized hardware |\n"
        ))
        # page reorders/rewords the same row's tokens, keeping the key terms
        page = _page(substance=(
            "| Method | Notes | Annual cost |\n"
            "|--------|-------|-------------|\n"
            "| GPT-4 training run | amortized hardware | 40 million dollars |\n"
        ))
        rep = td.detect(page, raw)
        cr = rep.classes["table_row"]
        data_missing = [m for m in cr.missing if "gpt-4" in m.text.lower()]
        self.assertEqual(len(data_missing), 0,
                         "token-set fallback (>=0.72 overlap) must match the reordered row")

    def test_paraphrased_below_threshold_is_missing(self):
        # A row sharing FEW tokens with the raw row must be reported missing
        # (token-set fallback must not over-match).
        raw = _page(substance=(
            "| Approach | Cost |\n"
            "|----------|------|\n"
            "| Amortized depreciation of accelerator hardware capex | $40M |\n"
        ))
        page = _page(substance=(
            "| Topic | Value |\n"
            "|-------|-------|\n"
            "| unrelated row about latency budgets | 5ms |\n"
        ))
        rep = td.detect(page, raw)
        cr = rep.classes["table_row"]
        self.assertTrue(any("Amortized depreciation" in m.text for m in cr.missing),
                        "a row with low token overlap must be reported missing")


class TestNumericMultiset(unittest.TestCase):
    """The count-aware numeric retention fix: a magnitude appearing N times in raw
    is retained only if N occurrences survive (set-membership wrongly clears
    duplicated/common values)."""

    def test_duplicated_value_one_dropped_is_missing(self):
        # raw mentions 2.4x twice; page keeps it once -> one occurrence missing
        raw = _page(substance=(
            "The cost grew 2.4x per year. A separate cross-check also gives 2.4x growth. "
            "Other figures: 40 million, 30 million, 5000, 14 percent, 90 percent."
        ))
        page = _page(substance=(
            "The cost grew 2.4x per year. "
            "Other figures: 40 million, 30 million, 5000, 14 percent, 90 percent."
        ))
        rep = td.detect(page, raw)
        cr = rep.classes["numeric"]
        self.assertFalse(cr.skipped)
        self.assertGreaterEqual(cr.missing_count, 1,
                                "the second 2.4x occurrence must be reported missing (multiset)")
        self.assertTrue(any(td._numeric_value(m.text) == 2.4 for m in cr.missing))

    def test_magnitude_tolerance_within_1pct(self):
        # 40,000,000 vs $40M: same magnitude within 1% -> retained (not missing)
        raw = _page(substance="Cost is $40M for the run, plus 30M, 5000, 14, 90, 2.4x.")
        page = _page(substance="Cost is 40,000,000 for the run, plus 30M, 5000, 14, 90, 2.4x.")
        rep = td.detect(page, raw)
        cr = rep.classes["numeric"]
        self.assertFalse(any(td._numeric_value(m.text) == 40e6 for m in cr.missing),
                         "$40M and 40,000,000 are within tolerance -> retained")

    def test_min_count_guard_skips_low_numeric(self):
        # only 2 numeric atoms -> below floor 5 -> class skipped
        raw = _page(substance="Two numbers only: 3 and 7 here.")
        page = _page(substance="Two numbers only: 3 here.")
        rep = td.detect(page, raw)
        cr = rep.classes["numeric"]
        self.assertTrue(cr.skipped, "raw with <5 numeric atoms must skip T2")
        self.assertIsNone(cr.retention)
        self.assertIn("floor", cr.skip_reason)


class TestRuleLabelT4(unittest.TestCase):
    def test_min_count_guard_skips_low_rule(self):
        raw = _page(methodology="**Amortization.** A. **Frontier selection.** B.")
        page = _page(methodology="A. B.")
        rep = td.detect(page, raw)
        cr = rep.classes["rule_label"]
        self.assertTrue(cr.skipped, "raw with <3 rule atoms must skip T4")

    def test_dropped_rule_label_missing(self):
        raw = _page(methodology=(
            "**Amortization.** detail. **Frontier selection.** detail. "
            "**Staff cost.** detail. **TPU costs.** detail."
        ))
        page = _page(methodology="**Amortization.** detail. **Staff cost.** detail.")
        rep = td.detect(page, raw)
        cr = rep.classes["rule_label"]
        self.assertFalse(cr.skipped)
        miss = [m.text for m in cr.missing]
        self.assertTrue(any("Frontier selection" in t for t in miss))
        self.assertTrue(any("TPU costs" in t for t in miss))


class TestNamedEntityT5(unittest.TestCase):
    def test_dropped_entity_missing_present_entity_retained(self):
        raw = _page(substance="See [[gpt-4.md]] and [[gemini-models.md]] and [[epoch-ai.md]].")
        page = _page(substance="See [[epoch-ai.md]] only.")
        rep = td.detect(page, raw)
        cr = rep.classes["named_entity"]
        miss = [m.text for m in cr.missing]
        self.assertTrue(any("gpt-4" in t for t in miss))
        self.assertTrue(any("gemini-models" in t for t in miss))
        self.assertFalse(any("epoch-ai" in t for t in miss),
                         "an entity still named on the page is retained (substring presence)")


class TestCaveatT6(unittest.TestCase):
    def test_dropped_caveat_missing(self):
        raw = _page(counterpoints=(
            "- The authors note this estimate relies on public data and may be conservative.\n"
            "- A second limitation: data-acquisition costs are neglected.\n"
        ))
        page = _page(counterpoints="- The results are strong.\n")
        rep = td.detect(page, raw)
        cr = rep.classes["caveat"]
        self.assertFalse(cr.skipped)
        self.assertGreaterEqual(cr.missing_count, 1, "dropped author caveat must be reported missing")


class TestCompareSetBoundary(unittest.TestCase):
    """The detector must read ONLY Substance/Counterpoints/Methodology/Notable
    quotes -- never My take or Sources (wiki-schema.md compare-set)."""

    def test_my_take_and_sources_excluded(self):
        # numbers/entities ONLY in My take + Sources must not count as raw atoms
        raw = _page(
            substance="Five figures: 10, 20, 30, 40, 50 percent.",
            my_take="My private numbers 999 and 888 and [[secret.md]].",
            sources="[^1]: [[raw.md]] mentioning 777",
        )
        page = _page(substance="Five figures: 10, 20, 30, 40, 50 percent.")
        rep = td.detect(page, raw)
        # the My-take/Sources numbers must NOT appear as missing (they're outside
        # the compare-set, so they were never extracted from raw)
        all_missing = [m.text for m in rep.all_missing()]
        self.assertFalse(any("999" in t or "888" in t or "777" in t for t in all_missing))
        self.assertFalse(any("secret" in t for t in all_missing))
        # and the compare-set numbers are fully retained
        self.assertEqual(rep.classes["numeric"].missing_count, 0)

    def test_silver_ablation_stamp_tolerated(self):
        # an ablated fixture prepends an HTML-comment stamp before frontmatter;
        # the section parser must still find the compare-set sections
        raw = _page(substance="Numbers: 10, 20, 30, 40, 50.")
        stamped_page = "<!-- SILVER-ABLATION FIXTURE -- DO NOT INGEST. grade=0.25 -->\n" + \
                       _page(substance="Numbers: 10, 20, 30.")
        rep = td.detect(stamped_page, raw)
        cr = rep.classes["numeric"]
        self.assertFalse(cr.skipped)
        self.assertGreaterEqual(cr.missing_count, 2, "40 and 50 dropped -> reported missing")


class TestNoNetwork(unittest.TestCase):
    """C1: the detector must not import or require any embedding/LLM/network
    dependency. Proven by the absence of such imports + a key-unset run."""

    def test_runs_with_voyage_key_unset(self):
        import os
        had = os.environ.pop("VOYAGE_API_KEY", None)
        try:
            raw = _page(substance="Figures: 10, 20, 30, 40, 50 and [[x.md]].")
            page = _page(substance="Figures: 10, 20, 30.")
            rep = td.detect(page, raw)
            self.assertTrue(rep.flagged)
        finally:
            if had is not None:
                os.environ["VOYAGE_API_KEY"] = had

    def test_no_embedding_imports_in_module(self):
        src = Path(td.__file__).read_text(encoding="utf-8")
        for banned in ("import voyageai", "import openai", "import anthropic",
                       "import requests", "import httpx", "import numpy"):
            self.assertNotIn(banned, src, f"detector must not depend on {banned}")


if __name__ == "__main__":
    unittest.main()
