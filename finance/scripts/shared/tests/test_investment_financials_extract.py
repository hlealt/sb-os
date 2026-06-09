"""Tests for investment_financials_extract — the SOLE writer of entity
`## Financials` table sections (§10 capture→Financials extraction).

Design contract: investor-agent.md §10 + parent build resolutions.

Coverage (TDD — written before the implementation):
  - vocab hard-gate: off-vocab metric/unit/period_type/method → row REJECTED;
  - suffix-family acceptance (_guidance/_non_gaap/_growth_yoy, exactly one) and
    stacking rejection;
  - lane-2 anchor verification: verified→`structured` with TOOL-parsed value;
    anchor missing→reject; anchor ambiguous→reject; scale/sign/percent parsing;
  - upsert: no-op / method upgrade in place / downgrade no-op / value conflict
    surfaced not written / new-row insert; differing sources coexist;
  - canonical sort; section creation position (before ## Related / ## Sources /
    append); source-not-in-raw reject;
  - entity missing→exit 1; wrong kind→refuse; cik cross-check mismatch→error;
  - lane-1 XBRL: corroborate-only default vs --since open mode, latest-filed-
    wins, duration classification (quarterly/annual/skip-YTD), USD→USD_mn;
  - PROPOSAL rows → vocab_proposals never written;
  - dry-run writes nothing byte-for-byte;
  - 7-column schema conformance of the written table.

Import-by-file-path pattern mirrors test_sb_wiki_capture_source.py.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import the tool by file path (matches test_sb_wiki_capture_source.py)
# ---------------------------------------------------------------------------
_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
_INVESTIMENTOS_DIR = _SCRIPTS_DIR.parent / "investimentos"

for _p in (_SCRIPTS_DIR, _INVESTIMENTOS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_MOD_PATH = _INVESTIMENTOS_DIR / "investment_financials_extract.py"
_spec = importlib.util.spec_from_file_location("investment_financials_extract", _MOD_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["investment_financials_extract"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore

extract = _mod.extract
main = _mod.main


# ---------------------------------------------------------------------------
# Vocab fixture — the EXACT target state the parent guarantees (company/equity
# bases + Allowed Sets + Suffix Families). Tests bind to this, not the live file.
# ---------------------------------------------------------------------------
_VOCAB_FIXTURE = """# Metric Vocabulary — Finance Extension

## Vocabulary by Entity Kind

### company / equity

`revenue, gross_profit, ebitda, ebit, operating_income, net_income, gross_margin, ebitda_margin, operating_margin, net_margin, roic, roe, net_debt, net_debt_ebitda, fcf, operating_cash_flow, capex, rpo, crpo, subscription_revenue, subscription_support_revenue, cloud_revenue, data_center_revenue, data_cloud_ai_arr, cash_and_securities`

Valuation point metrics (use `period_type: point`):

`market_cap, ev_ebitda, pe, dividend_yield`

### country / macro

`gdp_growth, inflation, policy_rate, unemployment, debt_gdp, fiscal_balance, current_account, fx_rate`

### asset — fixed income

`yield, duration, coupon, credit_rating, spread, price`

### sector

Comparative / aggregate metrics: `sector_revenue_growth, sector_margin`

---

## Allowed Sets

**units:** `BRL_mn, USD_mn, pct, pct_yoy, pct_mom, x, bps, years, rating, BRL, USD, index`

**period_type:** `annual, quarterly, monthly, ttm, point`

**method:** `xbrl, structured, llm, manual`

---

## Suffix Families

`_growth_yoy, _guidance, _non_gaap`
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENTITY_HEADER = """---
type: entity
kind: company
created: 2026-06-02
---

# atlassian

Atlassian is an Australian enterprise-software company.

## What it is

Some prose.

"""

_FINANCIALS_BLOCK = """## Financials

| metric | period_type | period_end | value | unit | source | method |
|--------|-------------|------------|-------|------|--------|--------|
| revenue | quarterly | 2025-12-31 | 1586 | USD_mn | [[2026-06-03-team-q2.md]] | llm |
| fcf | quarterly | 2025-12-31 | 169 | USD_mn | [[2026-06-03-team-q2.md]] | llm |

"""

_TAIL = """## Related

- [[atlassian-ai-overdiscount.md]]

## Sources

[^1]: [[2026-06-03-team-q2.md]]
"""

# A real-ish raw filing body whose normalized text contains the anchors below.
_RAW_BODY = (
    "<html><body>"
    "<div>Revenue of $1,586 million, up 23% year-over-year</div>"
    "<div>Cloud revenue of $1,067 million, up 26% year-over-year</div>"
    # RPO printed contiguously (as the real press-release prose is), plus a
    # split-across-tags variant to exercise tag-stripping normalization.
    "<div>Remaining performance obligations of $3,814 million, up 44% year-over-year</div>"
    "<div>Cash and securities of </div><div>$2,500 million</div>"
    "<div>GAAP&#160;operating margin of (3)% and non-GAAP operating margin&#160;of 27%</div>"
    "<div>Free cash flow of $169 million</div>"
    "<div>FY26 revenue is expected to be approximately $6.5 billion</div>"
    "</body></html>"
)


def _make_vault(tmp_path: Path) -> Path:
    cfg = {"wiki_root": "knowledge-base"}
    (tmp_path / "sb-os.json").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "knowledge-base" / "raw" / "sec").mkdir(parents=True)
    return tmp_path


def _write_vocab(tmp_path: Path, content: str = _VOCAB_FIXTURE) -> Path:
    p = tmp_path / "metric-vocab.md"
    p.write_text(content, encoding="utf-8")
    return p


def _write_raw(vault: Path, name: str = "2026-06-03-team-q2.md", body: str = _RAW_BODY) -> Path:
    p = vault / "knowledge-base" / "raw" / "sec" / name
    p.write_text(body, encoding="utf-8")
    return p


def _write_entity(
    tmp_path: Path,
    *,
    frontmatter_kind: str = "company",
    with_financials: bool = True,
    with_related: bool = True,
    with_sources: bool = True,
    cik: str | None = None,
    name: str = "atlassian.md",
) -> Path:
    fm = "---\ntype: entity\nkind: " + frontmatter_kind + "\ncreated: 2026-06-02\n"
    if cik is not None:
        fm += f"cik: {cik}\n"
    fm += "---\n\n# atlassian\n\nAtlassian is an Australian enterprise-software company.\n\n## What it is\n\nSome prose.\n\n"
    body = fm
    if with_financials:
        body += _FINANCIALS_BLOCK
    tail = ""
    if with_related:
        tail += "## Related\n\n- [[atlassian-ai-overdiscount.md]]\n\n"
    if with_sources:
        tail += "## Sources\n\n[^1]: [[2026-06-03-team-q2.md]]\n"
    body += tail
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def _write_targets(tmp_path: Path, targets: list[dict], *, entity: str = "atlassian",
                   source: str = "2026-06-03-team-q2.md") -> Path:
    p = tmp_path / "targets.json"
    p.write_text(json.dumps({"entity": entity, "source": source, "targets": targets}),
                 encoding="utf-8")
    return p


def _read_financials_rows(page_text: str) -> list[list[str]]:
    """Return the data rows (list of cell-lists) of the ## Financials table."""
    lines = page_text.splitlines()
    rows = []
    in_fin = False
    for ln in lines:
        if ln.strip() == "## Financials":
            in_fin = True
            continue
        if in_fin and ln.startswith("## "):
            break
        if in_fin and ln.startswith("|"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            rows.append(cells)
    # rows[0] = header, rows[1] = separator, rest = data
    return rows


def _data_rows(page_text: str) -> list[list[str]]:
    rows = _read_financials_rows(page_text)
    return rows[2:] if len(rows) >= 2 else []


def _header(page_text: str) -> list[str]:
    rows = _read_financials_rows(page_text)
    return rows[0] if rows else []


# ===========================================================================
# Vocabulary hard-gate
# ===========================================================================

CANONICAL_COLUMNS = ["metric", "period_type", "period_end", "value", "unit", "source", "method"]


def test_offvocab_metric_rejected(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "bogus_metric", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$1,586 million", "unit_as_printed": "$",
        "anchor": "Revenue of $1,586 million, up 23% year-over-year",
    }])
    before = entity.read_text(encoding="utf-8")
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert any(r["metric"] == "bogus_metric" for r in result["rejected"])
    assert entity.read_text(encoding="utf-8") == before  # nothing written for bad row


def test_offvocab_unit_rejected(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    # printed unit that maps to nothing in the deterministic table
    targets = _write_targets(tmp_path, [{
        "metric": "revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "1586 widgets", "unit_as_printed": "widgets",
        "anchor": "Revenue of $1,586 million, up 23% year-over-year",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert any(r["metric"] == "revenue" for r in result["rejected"])


def test_offvocab_period_type_rejected(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "revenue", "period_type": "weekly", "period_end": "2025-12-31",
        "value_as_printed": "$1,586 million", "unit_as_printed": "$",
        "anchor": "Revenue of $1,586 million, up 23% year-over-year",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert any("period_type" in r["reason"].lower() or r["metric"] == "revenue"
               for r in result["rejected"])


# ===========================================================================
# Suffix families
# ===========================================================================

@pytest.mark.parametrize("metric,printed,unit,anchor", [
    ("revenue_guidance", "$6.5 billion", "$", "FY26 revenue is expected to be approximately $6.5 billion"),
    ("operating_margin_non_gaap", "27%", "%", "non-GAAP operating margin of 27%"),
])
def test_suffix_family_accepted(tmp_path, metric, printed, unit, anchor):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": metric, "period_type": "annual" if "guidance" in metric else "quarterly",
        "period_end": "2026-06-30" if "guidance" in metric else "2025-12-31",
        "value_as_printed": printed, "unit_as_printed": unit, "anchor": anchor,
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert not any(r["metric"] == metric for r in result["rejected"]), result["rejected"]
    assert result["written"]["structured"] >= 1
    assert any(r[0] == metric for r in _data_rows(entity.read_text(encoding="utf-8")))


def test_suffix_growth_yoy_accepted(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "crpo_growth_yoy", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "44%", "unit_as_printed": "%",
        "anchor": "Remaining performance obligations of $3,814 million, up 44% year-over-year",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert not any(r["metric"] == "crpo_growth_yoy" for r in result["rejected"]), result["rejected"]


def test_suffix_stacking_rejected(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "revenue_guidance_growth_yoy", "period_type": "annual", "period_end": "2026-06-30",
        "value_as_printed": "22%", "unit_as_printed": "%",
        "anchor": "FY26 revenue is expected to be approximately $6.5 billion",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert any(r["metric"] == "revenue_guidance_growth_yoy" for r in result["rejected"])


# ===========================================================================
# Lane-2 anchor verification + number parsing
# ===========================================================================

def test_anchor_verified_writes_structured_with_tool_value(tmp_path):
    vault = _make_vault(tmp_path)
    # entity WITHOUT a financials section so this is a clean insert
    entity = _write_entity(tmp_path, with_financials=False)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "cloud_revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$1,067 million", "unit_as_printed": "$",
        "anchor": "Cloud revenue of $1,067 million, up 26% year-over-year",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert result["written"]["structured"] == 1
    rows = _data_rows(entity.read_text(encoding="utf-8"))
    crow = [r for r in rows if r[0] == "cloud_revenue"][0]
    assert crow[3] == "1067"       # tool re-parsed value, millions
    assert crow[4] == "USD_mn"
    assert crow[6] == "structured"


def test_anchor_missing_rejected(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    before = entity.read_text(encoding="utf-8")
    targets = _write_targets(tmp_path, [{
        "metric": "ebitda", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$999 million", "unit_as_printed": "$",
        "anchor": "This exact phrase does not appear anywhere in the raw filing text",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert any(r["metric"] == "ebitda" for r in result["rejected"])
    assert entity.read_text(encoding="utf-8") == before


def test_anchor_ambiguous_rejected(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)
    # anchor with two numbers and no value_as_printed disambiguation
    _write_raw(vault, body="<html><body><div>Two figures here: 100 and 200 both appear</div></body></html>")
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "ebitda", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "", "unit_as_printed": "USD",
        "anchor": "Two figures here: 100 and 200 both appear",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert any(r["metric"] == "ebitda" and "ambig" in r["reason"].lower()
               for r in result["rejected"]), result["rejected"]


def test_ambiguous_resolved_by_value_as_printed(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False)
    _write_raw(vault, body="<html><body><div>Two figures here: 100 and 200 both appear</div></body></html>")
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "ebitda", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "200", "unit_as_printed": "USD",
        "anchor": "Two figures here: 100 and 200 both appear",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert result["written"]["structured"] == 1
    crow = [r for r in _data_rows(entity.read_text(encoding="utf-8")) if r[0] == "ebitda"][0]
    assert crow[3] == "200"


def test_billion_scale_to_usd_mn(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "revenue_guidance", "period_type": "annual", "period_end": "2026-06-30",
        "value_as_printed": "$6.5 billion", "unit_as_printed": "$",
        "anchor": "FY26 revenue is expected to be approximately $6.5 billion",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    crow = [r for r in _data_rows(entity.read_text(encoding="utf-8")) if r[0] == "revenue_guidance"][0]
    assert crow[3] == "6500"      # 6.5 billion → 6500 USD_mn
    assert crow[4] == "USD_mn"


def test_negative_parenthesis_sign(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "operating_margin", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "(3)%", "unit_as_printed": "%",
        "anchor": "GAAP operating margin of (3)% and non-GAAP operating margin of 27%",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    crow = [r for r in _data_rows(entity.read_text(encoding="utf-8")) if r[0] == "operating_margin"][0]
    assert crow[3] == "-3"
    assert crow[4] == "pct"


def test_half_rounds_up_not_bankers(tmp_path):
    # 168.5 must round to 169 (financial half-up), not 168 (Python banker's).
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False)
    _write_raw(vault, body="<html><body><div>free cash flow was $168.5 million for the quarter</div></body></html>")
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "fcf", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$168.5 million", "unit_as_printed": "$",
        "anchor": "free cash flow was $168.5 million for the quarter",
    }])
    extract(entity_path=entity, xbrl_path=None, targets_path=targets,
            vault_root=vault, vocab_path=vocab, dry_run=False)
    crow = [r for r in _data_rows(entity.read_text(encoding="utf-8")) if r[0] == "fcf"][0]
    assert crow[3] == "169"


def test_percent_keeps_one_decimal(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False)
    _write_raw(vault, body="<html><body><div>net margin of 18.2% this quarter</div></body></html>")
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "net_margin", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "18.2%", "unit_as_printed": "%",
        "anchor": "net margin of 18.2% this quarter",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    crow = [r for r in _data_rows(entity.read_text(encoding="utf-8")) if r[0] == "net_margin"][0]
    assert crow[3] == "18.2"
    assert crow[4] == "pct"


# ===========================================================================
# Bare scale-word units — currency from value_as_printed (real-data defect)
# ===========================================================================
# Real filings print rows whose unit_as_printed is a BARE scale word
# ("million" / "billion" / "B"), with the currency living only in
# value_as_printed (e.g. "$1,586.3 million"). The resolver must combine the
# bare scale word with the currency detected in value_as_printed; a scale word
# already inside value_as_printed must NOT double-scale.

@pytest.mark.parametrize("metric,vap,unit,anchor,expect_val,expect_unit", [
    # ("$1,586.3 million", "million") → 1586 USD_mn (ROUND_HALF_UP)
    ("revenue", "$1,586.3 million", "million",
     "Revenue of $1,586.3 million for the quarter", "1586", "USD_mn"),
    # ("$1,286.5 million", "million") → 1287 (half rounds up)
    ("revenue", "$1,286.5 million", "million",
     "Revenue of $1,286.5 million for the quarter", "1287", "USD_mn"),
    # ("$9.552 billion", "billion") → 9552
    ("revenue", "$9.552 billion", "billion",
     "Total revenue of $9.552 billion for the year", "9552", "USD_mn"),
    # ("$1.1B", "B") → 1100
    ("revenue", "$1.1B", "B",
     "Revenue reached $1.1B in the period", "1100", "USD_mn"),
    # ("over $1.2 billion", "billion") → 1200
    ("revenue", "over $1.2 billion", "billion",
     "Revenue of over $1.2 billion this year", "1200", "USD_mn"),
    # ("nearly $15 billion", "billion") → 15000
    ("revenue", "nearly $15 billion", "billion",
     "Revenue of nearly $15 billion for the year", "15000", "USD_mn"),
    # ("$2.360 billion", "billion") → 2360
    ("revenue", "$2.360 billion", "billion",
     "Revenue of $2.360 billion for the year", "2360", "USD_mn"),
])
def test_bare_scale_word_unit_with_dollar_currency(
    tmp_path, metric, vap, unit, anchor, expect_val, expect_unit
):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False)
    _write_raw(vault, body=f"<html><body><div>{anchor}</div></body></html>")
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": metric, "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": vap, "unit_as_printed": unit, "anchor": anchor,
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert not any(r["metric"] == metric for r in result["rejected"]), result["rejected"]
    crow = [r for r in _data_rows(entity.read_text(encoding="utf-8")) if r[0] == metric][0]
    assert crow[3] == expect_val
    assert crow[4] == expect_unit


def test_bare_scale_word_unit_with_brl_currency(tmp_path):
    # R$ in value_as_printed → BRL_mn (R$ must be checked before $)
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False)
    body = "<html><body><div>Receita de R$1,586.3 milhao no trimestre</div></body></html>"
    _write_raw(vault, body=body)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "R$1,586.3 million", "unit_as_printed": "million",
        "anchor": "Receita de R$1,586.3 milhao no trimestre",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert not any(r["metric"] == "revenue" for r in result["rejected"]), result["rejected"]
    crow = [r for r in _data_rows(entity.read_text(encoding="utf-8")) if r[0] == "revenue"][0]
    assert crow[3] == "1586"
    assert crow[4] == "BRL_mn"


def test_bare_scale_word_no_currency_rejected(tmp_path):
    # No currency anywhere (unit "million", value "1,586") → unmapped printed unit
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)
    _write_raw(vault, body="<html><body><div>Revenue of 1,586 in the period</div></body></html>")
    vocab = _write_vocab(tmp_path)
    before = entity.read_text(encoding="utf-8")
    targets = _write_targets(tmp_path, [{
        "metric": "revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "1,586", "unit_as_printed": "million",
        "anchor": "Revenue of 1,586 in the period",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    rej = [r for r in result["rejected"] if r["metric"] == "revenue"]
    assert rej and "unmapped printed unit" in rej[0]["reason"], result["rejected"]
    assert entity.read_text(encoding="utf-8") == before


def test_bare_scale_word_no_double_scale(tmp_path):
    # value_as_printed carries the scale word AND unit is the same scale word:
    # resolve the scale ONCE. "$1.8 billion" + unit "billion" → 1800, not 1.8M.
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False)
    _write_raw(vault, body="<html><body><div>Revenue of $1.8 billion for the year</div></body></html>")
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "revenue", "period_type": "annual", "period_end": "2025-06-30",
        "value_as_printed": "$1.8 billion", "unit_as_printed": "billion",
        "anchor": "Revenue of $1.8 billion for the year",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert not any(r["metric"] == "revenue" for r in result["rejected"]), result["rejected"]
    crow = [r for r in _data_rows(entity.read_text(encoding="utf-8")) if r[0] == "revenue"][0]
    assert crow[3] == "1800"
    assert crow[4] == "USD_mn"


def test_bare_scale_word_lane3_llm(tmp_path):
    # Lane 3 (no anchor / unverifiable): bare scale word + $ in value_as_printed.
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$1,586.3 million", "unit_as_printed": "million",
        "anchor": "", "unverifiable": True, "reason": "model-supplied",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert not any(r["metric"] == "revenue" for r in result["rejected"]), result["rejected"]
    crow = [r for r in _data_rows(entity.read_text(encoding="utf-8")) if r[0] == "revenue"][0]
    assert crow[3] == "1586"
    assert crow[4] == "USD_mn"


def test_existing_unit_forms_unchanged(tmp_path):
    # Regression guard: explicit-currency, percent, and vocab-unit forms must
    # behave exactly as before the bare-scale-word change.
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False)
    _write_raw(vault, body=(
        "<html><body>"
        "<div>Revenue of $1,586 million, up 23% year-over-year</div>"
        "<div>net margin of 18.2% this quarter</div>"
        "<div>Cloud revenue of $1,067 million in the quarter</div>"
        "</body></html>"
    ))
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [
        # "$ millions" explicit currency+scale unit
        {"metric": "revenue", "period_type": "quarterly", "period_end": "2025-12-31",
         "value_as_printed": "$1,586 million", "unit_as_printed": "$ millions",
         "anchor": "Revenue of $1,586 million, up 23% year-over-year"},
        # "%"
        {"metric": "net_margin", "period_type": "quarterly", "period_end": "2025-12-31",
         "value_as_printed": "18.2%", "unit_as_printed": "%",
         "anchor": "net margin of 18.2% this quarter"},
        # "USD millions" word currency
        {"metric": "cloud_revenue", "period_type": "quarterly", "period_end": "2025-12-31",
         "value_as_printed": "$1,067 million", "unit_as_printed": "USD millions",
         "anchor": "Cloud revenue of $1,067 million in the quarter"},
    ])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert not result["rejected"], result["rejected"]
    rows = {r[0]: r for r in _data_rows(entity.read_text(encoding="utf-8"))}
    assert rows["revenue"][3] == "1586" and rows["revenue"][4] == "USD_mn"
    assert rows["net_margin"][3] == "18.2" and rows["net_margin"][4] == "pct"
    assert rows["cloud_revenue"][3] == "1067" and rows["cloud_revenue"][4] == "USD_mn"


# ===========================================================================
# Source resolution
# ===========================================================================

def test_source_not_in_raw_rejected(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    # per-target source override that doesn't exist on disk
    targets = _write_targets(tmp_path, [{
        "metric": "revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$1,586 million", "unit_as_printed": "$",
        "anchor": "Revenue of $1,586 million, up 23% year-over-year",
        "source": "2099-01-01-does-not-exist.md",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert any(r["metric"] == "revenue" for r in result["rejected"])


# ===========================================================================
# Upsert
# ===========================================================================

def test_upsert_method_upgrade_in_place_same_value(tmp_path):
    # existing row: revenue quarterly 2025-12-31 = 1586 USD_mn method llm
    # incoming: same value, structured (verified) → method UPGRADES in place
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)  # has the llm revenue row
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$1,586 million", "unit_as_printed": "$",
        "anchor": "Revenue of $1,586 million, up 23% year-over-year",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert result["upgraded"] == 1
    assert result["written"]["structured"] == 0  # upgrade is not a new write
    rows = _data_rows(entity.read_text(encoding="utf-8"))
    rev = [r for r in rows if r[0] == "revenue" and r[2] == "2025-12-31"][0]
    assert rev[6] == "structured"   # method upgraded
    assert rev[3] == "1586"         # value unchanged
    # exactly one revenue row for that period+source (no duplicate)
    assert len([r for r in rows if r[0] == "revenue" and r[2] == "2025-12-31"]) == 1


def test_upsert_downgrade_is_noop(tmp_path):
    # existing structured row; incoming llm (weaker) same value → no-op skipped
    vault = _make_vault(tmp_path)
    fm = _ENTITY_HEADER + (
        "## Financials\n\n"
        "| metric | period_type | period_end | value | unit | source | method |\n"
        "|--------|-------------|------------|-------|------|--------|--------|\n"
        "| revenue | quarterly | 2025-12-31 | 1586 | USD_mn | [[2026-06-03-team-q2.md]] | structured |\n\n"
        + _TAIL
    )
    entity = tmp_path / "atlassian.md"
    entity.write_text(fm, encoding="utf-8")
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    # an llm (unverifiable) incoming row, same value
    targets = _write_targets(tmp_path, [{
        "metric": "revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "1586", "unit_as_printed": "USD_mn",
        "anchor": "", "unverifiable": True, "reason": "no anchor",
    }])
    before = entity.read_text(encoding="utf-8")
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert result["skipped"] >= 1
    assert result["upgraded"] == 0
    rev = [r for r in _data_rows(entity.read_text(encoding="utf-8")) if r[0] == "revenue"][0]
    assert rev[6] == "structured"   # unchanged — no downgrade


def test_upsert_value_conflict_surfaced_not_written(tmp_path):
    # existing 1586; incoming verified-but-different value at SAME key → conflict
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)
    _write_raw(vault, body="<html><body><div>Revenue of $1,600 million, up 24% year-over-year</div></body></html>")
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$1,600 million", "unit_as_printed": "$",
        "anchor": "Revenue of $1,600 million, up 24% year-over-year",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert len(result["conflicts"]) == 1
    c = result["conflicts"][0]
    assert c["metric"] == "revenue"
    assert str(c["existing_value"]) == "1586"
    assert str(c["incoming_value"]) == "1600"
    # original value untouched
    rev = [r for r in _data_rows(entity.read_text(encoding="utf-8")) if r[0] == "revenue"][0]
    assert rev[3] == "1586"


def test_upsert_new_row_insert(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "cloud_revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$1,067 million", "unit_as_printed": "$",
        "anchor": "Cloud revenue of $1,067 million, up 26% year-over-year",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert result["written"]["structured"] == 1
    assert any(r[0] == "cloud_revenue" for r in _data_rows(entity.read_text(encoding="utf-8")))


def test_identical_row_is_noop(tmp_path):
    # existing structured row identical to incoming → skipped, no change
    vault = _make_vault(tmp_path)
    fm = _ENTITY_HEADER + (
        "## Financials\n\n"
        "| metric | period_type | period_end | value | unit | source | method |\n"
        "|--------|-------------|------------|-------|------|--------|--------|\n"
        "| cloud_revenue | quarterly | 2025-12-31 | 1067 | USD_mn | [[2026-06-03-team-q2.md]] | structured |\n\n"
        + _TAIL
    )
    entity = tmp_path / "atlassian.md"
    entity.write_text(fm, encoding="utf-8")
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "cloud_revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$1,067 million", "unit_as_printed": "$",
        "anchor": "Cloud revenue of $1,067 million, up 26% year-over-year",
    }])
    before = entity.read_text(encoding="utf-8")
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert result["skipped"] >= 1
    assert result["written"]["structured"] == 0
    assert entity.read_text(encoding="utf-8") == before


def test_different_sources_coexist(tmp_path):
    # same (metric, period_type, period_end) but a DIFFERENT source → both rows
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)  # revenue 2025-12-31 from team-q2
    _write_raw(vault)
    other = _write_raw(vault, name="2026-06-10-team-alt.md",
                       body="<html><body><div>Revenue of $1,586 million in the quarter</div></body></html>")
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$1,586 million", "unit_as_printed": "$",
        "anchor": "Revenue of $1,586 million in the quarter",
        "source": "2026-06-10-team-alt.md",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert result["written"]["structured"] == 1
    rows = _data_rows(entity.read_text(encoding="utf-8"))
    rev_rows = [r for r in rows if r[0] == "revenue" and r[2] == "2025-12-31"]
    assert len(rev_rows) == 2  # two sources coexist


# ===========================================================================
# Canonical sort + schema conformance
# ===========================================================================

def test_canonical_sort(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False)
    _write_raw(vault, body=(
        "<html><body>"
        "<div>net margin of 18.2% this quarter</div>"
        "<div>Revenue of $1,586 million, up 23% year-over-year</div>"
        "<div>annual revenue total of $5,000 million for the year</div>"
        "</body></html>"
    ))
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [
        {"metric": "net_margin", "period_type": "quarterly", "period_end": "2025-12-31",
         "value_as_printed": "18.2%", "unit_as_printed": "%", "anchor": "net margin of 18.2% this quarter"},
        {"metric": "revenue", "period_type": "quarterly", "period_end": "2025-12-31",
         "value_as_printed": "$1,586 million", "unit_as_printed": "$",
         "anchor": "Revenue of $1,586 million, up 23% year-over-year"},
        {"metric": "revenue", "period_type": "annual", "period_end": "2025-06-30",
         "value_as_printed": "$5,000 million", "unit_as_printed": "$",
         "anchor": "annual revenue total of $5,000 million for the year"},
    ])
    extract(entity_path=entity, xbrl_path=None, targets_path=targets,
            vault_root=vault, vocab_path=vocab, dry_run=False)
    rows = _data_rows(entity.read_text(encoding="utf-8"))
    keys = [(r[0], r[2], r[1]) for r in rows]
    # metric asc, then period_end asc, then period_type enum (annual<quarterly)
    assert keys == sorted(
        keys,
        key=lambda k: (k[0], k[1], ["annual", "quarterly", "monthly", "ttm", "point"].index(k[2])),
    )
    # net_margin sorts after revenue (n > r is false; 'net_margin' < 'revenue') -> check explicit
    assert keys[0][0] == "net_margin"


def test_seven_column_schema_conformance(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "cloud_revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$1,067 million", "unit_as_printed": "$",
        "anchor": "Cloud revenue of $1,067 million, up 26% year-over-year",
    }])
    extract(entity_path=entity, xbrl_path=None, targets_path=targets,
            vault_root=vault, vocab_path=vocab, dry_run=False)
    page = entity.read_text(encoding="utf-8")
    assert _header(page) == CANONICAL_COLUMNS
    for r in _data_rows(page):
        assert len(r) == 7, f"row not 7 cells: {r}"


# ===========================================================================
# Section creation position
# ===========================================================================

def test_section_created_before_related(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False, with_related=True, with_sources=True)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "cloud_revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$1,067 million", "unit_as_printed": "$",
        "anchor": "Cloud revenue of $1,067 million, up 26% year-over-year",
    }])
    extract(entity_path=entity, xbrl_path=None, targets_path=targets,
            vault_root=vault, vocab_path=vocab, dry_run=False)
    page = entity.read_text(encoding="utf-8")
    assert page.index("## Financials") < page.index("## Related")
    assert page.index("## Financials") > page.index("## What it is")


def test_section_created_before_sources_when_no_related(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False, with_related=False, with_sources=True)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "cloud_revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$1,067 million", "unit_as_printed": "$",
        "anchor": "Cloud revenue of $1,067 million, up 26% year-over-year",
    }])
    extract(entity_path=entity, xbrl_path=None, targets_path=targets,
            vault_root=vault, vocab_path=vocab, dry_run=False)
    page = entity.read_text(encoding="utf-8")
    assert page.index("## Financials") < page.index("## Sources")


def test_section_appended_when_no_related_no_sources(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False, with_related=False, with_sources=False)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "cloud_revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$1,067 million", "unit_as_printed": "$",
        "anchor": "Cloud revenue of $1,067 million, up 26% year-over-year",
    }])
    extract(entity_path=entity, xbrl_path=None, targets_path=targets,
            vault_root=vault, vocab_path=vocab, dry_run=False)
    page = entity.read_text(encoding="utf-8")
    assert "## Financials" in page
    # appended at end → nothing of substance after the table
    assert page.index("## Financials") > page.index("## What it is")


def test_frontmatter_untouched(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False)
    original_fm = entity.read_text(encoding="utf-8").split("---\n\n")[0]
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "cloud_revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$1,067 million", "unit_as_printed": "$",
        "anchor": "Cloud revenue of $1,067 million, up 26% year-over-year",
    }])
    extract(entity_path=entity, xbrl_path=None, targets_path=targets,
            vault_root=vault, vocab_path=vocab, dry_run=False)
    new_fm = entity.read_text(encoding="utf-8").split("---\n\n")[0]
    assert new_fm == original_fm


# ===========================================================================
# Entity validation
# ===========================================================================

def test_entity_missing_exits_1(tmp_path):
    vault = _make_vault(tmp_path)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$1,586 million", "unit_as_printed": "$",
        "anchor": "Revenue of $1,586 million, up 23% year-over-year",
    }])
    rc = main([
        "--entity", str(tmp_path / "nonexistent.md"),
        "--targets", str(targets),
        "--vault-root", str(vault),
        "--vocab", str(vocab),
    ])
    assert rc == 1


def test_wrong_kind_refused(tmp_path):
    vault = _make_vault(tmp_path)
    # kind: person carries no ## Financials
    entity = _write_entity(tmp_path, frontmatter_kind="person", with_financials=False)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$1,586 million", "unit_as_printed": "$",
        "anchor": "Revenue of $1,586 million, up 23% year-over-year",
    }])
    rc = main([
        "--entity", str(entity), "--targets", str(targets),
        "--vault-root", str(vault), "--vocab", str(vocab),
    ])
    assert rc == 1


def test_cik_cross_check_mismatch_errors(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, cik="1650372", with_financials=False)
    vocab = _write_vocab(tmp_path)
    # companyfacts with a DIFFERENT cik
    cf = tmp_path / "cf.json"
    cf.write_text(json.dumps({"cik": 9999999, "facts": {"us-gaap": {}}}), encoding="utf-8")
    rc = main([
        "--entity", str(entity), "--xbrl", str(cf),
        "--vault-root", str(vault), "--vocab", str(vocab),
    ])
    assert rc == 1


# ===========================================================================
# Lane 1 — XBRL
# ===========================================================================

def _companyfacts(cik: int, facts: dict) -> dict:
    return {"cik": cik, "entityName": "ATLASSIAN", "facts": {"us-gaap": facts}}


def _usd_fact(start, end, val, form="10-Q", filed="2026-02-01", frame=None):
    d = {"start": start, "end": end, "val": val, "form": form, "filed": filed, "accn": "x", "fy": 2026, "fp": "Q2"}
    if frame:
        d["frame"] = frame
    return d


def test_lane1_corroborate_only_default(tmp_path):
    # default: only facts whose (metric, period_type, period_end) already exist
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)  # has revenue quarterly 2025-12-31, fcf quarterly 2025-12-31
    vocab = _write_vocab(tmp_path)
    cf = tmp_path / "cf.json"
    facts = {
        "Revenues": {"units": {"USD": [
            _usd_fact("2025-10-01", "2025-12-31", 1586000000),  # matches existing key → corroborate
            _usd_fact("2026-01-01", "2026-03-31", 1787000000),  # new key → skipped in corroborate-only
        ]}},
        "NetIncomeLoss": {"units": {"USD": [
            _usd_fact("2025-10-01", "2025-12-31", 100000000),   # net_income not in table → skipped
        ]}},
    }
    cf.write_text(json.dumps(_companyfacts(1650372, facts)), encoding="utf-8")
    result = extract(entity_path=entity, xbrl_path=cf, targets_path=None,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert result["lane1_mode"] == "corroborate-only"
    # only the corroborating revenue row is written (new source = the companyfacts file)
    assert result["written"]["xbrl"] == 1
    rows = _data_rows(entity.read_text(encoding="utf-8"))
    xbrl_rows = [r for r in rows if r[6] == "xbrl"]
    assert len(xbrl_rows) == 1
    assert xbrl_rows[0][0] == "revenue"
    assert xbrl_rows[0][3] == "1586"  # USD → USD_mn


def test_lane1_since_open_mode(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False)
    vocab = _write_vocab(tmp_path)
    cf = tmp_path / "cf.json"
    facts = {
        "Revenues": {"units": {"USD": [
            _usd_fact("2025-10-01", "2025-12-31", 1586000000),
            _usd_fact("2026-01-01", "2026-03-31", 1787000000),
        ]}},
    }
    cf.write_text(json.dumps(_companyfacts(1650372, facts)), encoding="utf-8")
    result = extract(entity_path=entity, xbrl_path=cf, targets_path=None,
                     vault_root=vault, vocab_path=vocab, dry_run=False, since="2026-01-01")
    assert result["lane1_mode"] == "since:2026-01-01"
    # open mode, since filter → only the 2026-03-31 fact (period_end >= 2026-01-01)
    rows = _data_rows(entity.read_text(encoding="utf-8"))
    xbrl_rows = [r for r in rows if r[6] == "xbrl"]
    assert len(xbrl_rows) == 1
    assert xbrl_rows[0][2] == "2026-03-31"


def test_lane1_latest_filed_wins(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False)
    vocab = _write_vocab(tmp_path)
    cf = tmp_path / "cf.json"
    facts = {
        "Revenues": {"units": {"USD": [
            _usd_fact("2025-10-01", "2025-12-31", 1586000000, filed="2026-02-01"),
            _usd_fact("2025-10-01", "2025-12-31", 1590000000, filed="2026-05-01"),  # restatement, later filed
        ]}},
    }
    cf.write_text(json.dumps(_companyfacts(1650372, facts)), encoding="utf-8")
    extract(entity_path=entity, xbrl_path=cf, targets_path=None,
            vault_root=vault, vocab_path=vocab, dry_run=False, since="2025-01-01")
    rows = [r for r in _data_rows(entity.read_text(encoding="utf-8")) if r[6] == "xbrl"]
    assert len(rows) == 1
    assert rows[0][3] == "1590"  # latest filed wins


def test_lane1_duration_classification(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False)
    vocab = _write_vocab(tmp_path)
    cf = tmp_path / "cf.json"
    facts = {
        "Revenues": {"units": {"USD": [
            _usd_fact("2025-10-01", "2025-12-31", 1586000000),   # ~92d → quarterly
            _usd_fact("2025-01-01", "2025-12-31", 5000000000),   # ~365d → annual
            _usd_fact("2025-04-01", "2025-12-31", 4000000000),   # ~275d YTD 9mo → SKIP
        ]}},
    }
    cf.write_text(json.dumps(_companyfacts(1650372, facts)), encoding="utf-8")
    extract(entity_path=entity, xbrl_path=cf, targets_path=None,
            vault_root=vault, vocab_path=vocab, dry_run=False, since="2024-01-01")
    rows = [r for r in _data_rows(entity.read_text(encoding="utf-8")) if r[6] == "xbrl"]
    ptypes = sorted(r[1] for r in rows)
    assert ptypes == ["annual", "quarterly"]  # YTD 9mo skipped


def test_lane1_usd_to_usd_mn_scaling(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path, with_financials=False)
    vocab = _write_vocab(tmp_path)
    cf = tmp_path / "cf.json"
    facts = {
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [
            _usd_fact("2025-10-01", "2025-12-31", 12300000),  # 12.3M → 12 (rounded int >=10)
        ]}},
    }
    cf.write_text(json.dumps(_companyfacts(1650372, facts)), encoding="utf-8")
    extract(entity_path=entity, xbrl_path=cf, targets_path=None,
            vault_root=vault, vocab_path=vocab, dry_run=False, since="2024-01-01")
    rows = [r for r in _data_rows(entity.read_text(encoding="utf-8")) if r[6] == "xbrl"]
    assert len(rows) == 1
    assert rows[0][0] == "capex"
    assert rows[0][3] == "12"
    assert rows[0][4] == "USD_mn"


# ===========================================================================
# PROPOSAL rows
# ===========================================================================

def test_proposal_rows_never_written(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    before = entity.read_text(encoding="utf-8")
    targets = _write_targets(tmp_path, [{
        "metric": "PROPOSAL:billings·company·USD_mn", "period_type": "quarterly",
        "period_end": "2025-12-31", "value_as_printed": "$2,000 million", "unit_as_printed": "$",
        "anchor": "Revenue of $1,586 million, up 23% year-over-year",
    }])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=False)
    assert len(result["vocab_proposals"]) == 1
    assert "billings" in result["vocab_proposals"][0]
    assert entity.read_text(encoding="utf-8") == before  # never written
    assert result["written"]["structured"] == 0


# ===========================================================================
# Dry-run
# ===========================================================================

def test_dry_run_writes_nothing_byte_for_byte(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    before = entity.read_text(encoding="utf-8")
    targets = _write_targets(tmp_path, [
        {"metric": "cloud_revenue", "period_type": "quarterly", "period_end": "2025-12-31",
         "value_as_printed": "$1,067 million", "unit_as_printed": "$",
         "anchor": "Cloud revenue of $1,067 million, up 26% year-over-year"},
        {"metric": "revenue", "period_type": "quarterly", "period_end": "2025-12-31",
         "value_as_printed": "$1,586 million", "unit_as_printed": "$",
         "anchor": "Revenue of $1,586 million, up 23% year-over-year"},
    ])
    result = extract(entity_path=entity, xbrl_path=None, targets_path=targets,
                     vault_root=vault, vocab_path=vocab, dry_run=True)
    assert result["dry_run"] is True
    # computation still happens (would-write counts populated)
    assert result["written"]["structured"] == 1   # cloud_revenue new
    assert result["upgraded"] == 1                 # revenue llm→structured
    # but the file is byte-for-byte unchanged
    assert entity.read_text(encoding="utf-8") == before


# ===========================================================================
# CLI smoke + exit codes
# ===========================================================================

def test_cli_success_exit_0_even_with_rejects(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "bogus", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "1", "unit_as_printed": "USD", "anchor": "nope",
    }])
    rc = main([
        "--entity", str(entity), "--targets", str(targets),
        "--vault-root", str(vault), "--vocab", str(vocab), "--dry-run",
    ])
    assert rc == 0  # rejects are surfaced state, not a usage error


def test_cli_requires_xbrl_or_targets(tmp_path):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)
    vocab = _write_vocab(tmp_path)
    rc = main([
        "--entity", str(entity), "--vault-root", str(vault), "--vocab", str(vocab),
    ])
    assert rc == 1  # at least one of --xbrl/--targets required


def test_cli_emits_metadata_json_only(tmp_path, capsys):
    vault = _make_vault(tmp_path)
    entity = _write_entity(tmp_path)
    _write_raw(vault)
    vocab = _write_vocab(tmp_path)
    targets = _write_targets(tmp_path, [{
        "metric": "cloud_revenue", "period_type": "quarterly", "period_end": "2025-12-31",
        "value_as_printed": "$1,067 million", "unit_as_printed": "$",
        "anchor": "Cloud revenue of $1,067 million, up 26% year-over-year",
    }])
    rc = main([
        "--entity", str(entity), "--targets", str(targets),
        "--vault-root", str(vault), "--vocab", str(vocab), "--dry-run",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)  # must be valid JSON
    assert payload["entity"]
    assert "written" in payload and "rejected" in payload and "conflicts" in payload
    # no raw filing body leaked into stdout
    assert "Cloud revenue of $1,067 million" not in out
