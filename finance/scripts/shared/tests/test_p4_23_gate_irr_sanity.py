"""Tests for gate #9 — IRR sanity (--strict) + rf_balcao band (p4-23).

S7-2 RESOLVED: rf_balcao expected-return band is [7%, 15%].
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_irr_sanity as gis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_portfolio(positions: list[dict]) -> dict:
    return {
        "meta": {"cut_date": "2026-03-31", "generated_at": "2026-03-31T00:00:00Z"},
        "summary": {"total_value": 1000.0, "total_pnl": 100.0, "irr": {"total": 0.10, "per_class": {}}},
        "positions": positions,
    }


def _rf_pos(pid: str, irr: float | None, current_value: float = 100.0) -> dict:
    return {
        "id": pid,
        "type": "cdb",
        "asset_class": "fixed_income",
        "currency": "BRL",
        "valuation_method": "balcao",
        "current_value": current_value,
        "irr": irr,
        "irr_quality": "complete",
    }


def _equity_pos(pid: str, irr: float | None) -> dict:
    return {
        "id": pid,
        "type": "acao",
        "asset_class": "variable_income",
        "currency": "BRL",
        "irr": irr,
    }


# ---------------------------------------------------------------------------
# check_rf_balcao_band
# ---------------------------------------------------------------------------

def test_rf_balcao_band_pass_within_range():
    portfolio = _make_portfolio([_rf_pos("cdb_a", irr=0.10)])  # 10% — within [7,15]
    violations, exempt_notes = gis.check_rf_balcao_band(portfolio, 7.0, 15.0)
    assert violations == []
    assert exempt_notes == []


def test_rf_balcao_band_fail_below_min():
    portfolio = _make_portfolio([_rf_pos("cdb_a", irr=0.05)])  # 5% — below 7%
    violations, _ = gis.check_rf_balcao_band(portfolio, 7.0, 15.0)
    assert len(violations) == 1
    assert "cdb_a" in violations[0]


def test_rf_balcao_band_fail_above_max():
    portfolio = _make_portfolio([_rf_pos("cdb_a", irr=0.20)])  # 20% — above 15%
    violations, _ = gis.check_rf_balcao_band(portfolio, 7.0, 15.0)
    assert len(violations) == 1
    assert "cdb_a" in violations[0]


def test_rf_balcao_band_none_irr_skipped():
    """Positions with irr=None are skipped (no data, not a violation)."""
    portfolio = _make_portfolio([_rf_pos("cdb_a", irr=None)])
    violations, _ = gis.check_rf_balcao_band(portfolio, 7.0, 15.0)
    assert violations == []


def test_rf_balcao_band_equity_not_checked():
    """Equity positions are not rf_balcao — not checked by band."""
    portfolio = _make_portfolio([_equity_pos("ITSA3", irr=0.02)])  # 2% — would fail band
    violations, _ = gis.check_rf_balcao_band(portfolio, 7.0, 15.0)
    assert violations == []


def test_rf_balcao_band_multiple_violations():
    portfolio = _make_portfolio([
        _rf_pos("cdb_a", irr=0.05),   # 5% below band
        _rf_pos("cdb_b", irr=0.10),   # 10% within band
        _rf_pos("lca_c", irr=0.25),   # 25% above band
    ])
    violations, _ = gis.check_rf_balcao_band(portfolio, 7.0, 15.0)
    assert len(violations) == 2
    ids = " ".join(violations)
    assert "cdb_a" in ids
    assert "lca_c" in ids


# ---------------------------------------------------------------------------
# Band exemptions (band_exempt_ids)
# ---------------------------------------------------------------------------

def test_band_exempt_out_of_band_is_note_not_violation():
    """An exempt position outside the band → no violation, one visible note."""
    portfolio = _make_portfolio([_rf_pos("cra_marked", irr=0.05)])  # below 7%
    violations, exempt_notes = gis.check_rf_balcao_band(
        portfolio, 7.0, 15.0, exemptions={"cra_marked": "marked-to-market IPCA paper"}
    )
    assert violations == []
    assert len(exempt_notes) == 1
    assert "cra_marked" in exempt_notes[0]
    assert "band-exempt" in exempt_notes[0]
    assert "marked-to-market IPCA paper" in exempt_notes[0]


def test_band_exempt_in_band_produces_no_note():
    """An exempt position INSIDE the band → no violation AND no note (no noise)."""
    portfolio = _make_portfolio([_rf_pos("cra_marked", irr=0.10)])  # within band
    violations, exempt_notes = gis.check_rf_balcao_band(
        portfolio, 7.0, 15.0, exemptions={"cra_marked": "reason"}
    )
    assert violations == []
    assert exempt_notes == []


def test_band_exempt_missing_reason_flagged_in_note():
    """An exemption without a reason still notes, asking for the reason."""
    portfolio = _make_portfolio([_rf_pos("cra_marked", irr=0.05)])
    violations, exempt_notes = gis.check_rf_balcao_band(
        portfolio, 7.0, 15.0, exemptions={"cra_marked": ""}
    )
    assert violations == []
    assert "no reason recorded" in exempt_notes[0]


def test_band_exempt_does_not_cover_other_positions():
    """Exempting one id leaves other out-of-band positions as violations."""
    portfolio = _make_portfolio([
        _rf_pos("cra_marked", irr=0.05),
        _rf_pos("cdb_low", irr=0.04),
    ])
    violations, exempt_notes = gis.check_rf_balcao_band(
        portfolio, 7.0, 15.0, exemptions={"cra_marked": "reason"}
    )
    assert len(violations) == 1
    assert "cdb_low" in violations[0]
    assert len(exempt_notes) == 1


def test_load_band_exemptions_parses_mappings_and_strings(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "standing-rules.yaml").write_text(
        "_meta:\n  schema_version: 1\n  rule_set_version: '1.0'\n"
        "supplier_rules:\n  matching_order: []\n"
        "investment_rules:\n  status: pending_consumer\n"
        "  sanity_bands:\n    rf_balcao:\n"
        "      expected_return_pct_min: 7\n      expected_return_pct_max: 15\n"
        "      band_exempt_ids:\n"
        "        - id: cra_a\n          reason: 'marked paper'\n"
        "        - cdb_bare\n",
        encoding="utf-8",
    )
    exemptions = gis._load_band_exemptions(config_dir)
    assert exemptions == {"cra_a": "marked paper", "cdb_bare": ""}


def test_load_band_exemptions_absent_key_returns_empty(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "standing-rules.yaml").write_text(
        "_meta:\n  schema_version: 1\n  rule_set_version: '1.0'\n"
        "supplier_rules:\n  matching_order: []\n"
        "investment_rules:\n  status: pending_consumer\n"
        "  sanity_bands:\n    rf_balcao:\n"
        "      expected_return_pct_min: 7\n      expected_return_pct_max: 15\n",
        encoding="utf-8",
    )
    assert gis._load_band_exemptions(config_dir) == {}


# ---------------------------------------------------------------------------
# run_gate (integration with validate_calculate internals)
# ---------------------------------------------------------------------------

def test_run_gate_pass_clean_portfolio(tmp_path):
    portfolio = _make_portfolio([
        _rf_pos("cdb_ok", irr=0.10),
    ])
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    # Write minimal standing-rules.yaml with rf_balcao band.
    (config_dir / "standing-rules.yaml").write_text(
        "_meta:\n  schema_version: 1\n  rule_set_version: '1.0'\n"
        "supplier_rules:\n  matching_order: []\n"
        "investment_rules:\n  status: pending_consumer\n"
        "  sanity_bands:\n    rf_balcao:\n"
        "      expected_return_pct_min: 7\n      expected_return_pct_max: 15\n",
        encoding="utf-8",
    )

    passed, violations, exempt_notes = gis.run_gate(portfolio_path, config_dir)
    assert passed
    assert violations == []
    assert exempt_notes == []


def test_run_gate_fail_rf_balcao_out_of_band(tmp_path):
    portfolio = _make_portfolio([
        _rf_pos("cdb_low", irr=0.02),  # 2% < 7% → violation
    ])
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "standing-rules.yaml").write_text(
        "_meta:\n  schema_version: 1\n  rule_set_version: '1.0'\n"
        "supplier_rules:\n  matching_order: []\n"
        "investment_rules:\n  status: pending_consumer\n"
        "  sanity_bands:\n    rf_balcao:\n"
        "      expected_return_pct_min: 7\n      expected_return_pct_max: 15\n",
        encoding="utf-8",
    )

    passed, violations, _ = gis.run_gate(portfolio_path, config_dir)
    assert not passed
    assert any("cdb_low" in v for v in violations)


def test_run_gate_fail_irr_out_of_band(tmp_path):
    """|irr| > 200% on a position → strict violation."""
    portfolio = _make_portfolio([
        {
            "id": "crazy_pos",
            "type": "acao",
            "asset_class": "variable_income",
            "currency": "BRL",
            "irr": 3.5,  # 350% — exceeds 200% band
        }
    ])
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "standing-rules.yaml").write_text(
        "_meta:\n  schema_version: 1\n  rule_set_version: '1.0'\n"
        "supplier_rules:\n  matching_order: []\n"
        "investment_rules:\n  status: pending_consumer\n"
        "  sanity_bands:\n    rf_balcao:\n"
        "      expected_return_pct_min: 7\n      expected_return_pct_max: 15\n",
        encoding="utf-8",
    )

    passed, violations, _ = gis.run_gate(portfolio_path, config_dir)
    assert not passed
    assert any("crazy_pos" in v for v in violations)


_EXEMPT_CONFIG_YAML = (
    "_meta:\n  schema_version: 1\n  rule_set_version: '1.0'\n"
    "supplier_rules:\n  matching_order: []\n"
    "investment_rules:\n  status: pending_consumer\n"
    "  sanity_bands:\n    rf_balcao:\n"
    "      expected_return_pct_min: 7\n      expected_return_pct_max: 15\n"
    "      band_exempt_ids:\n"
    "        - id: cra_marked\n"
    "          reason: 'IPCA paper bought at cycle-low real rates; MTM legitimate'\n"
)


def test_run_gate_pass_with_band_exempt_position(tmp_path):
    """Out-of-band but exempt → gate passes, exempt note surfaced."""
    portfolio = _make_portfolio([_rf_pos("cra_marked", irr=0.05)])  # 5% < 7%
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "standing-rules.yaml").write_text(_EXEMPT_CONFIG_YAML, encoding="utf-8")

    passed, violations, exempt_notes = gis.run_gate(portfolio_path, config_dir)
    assert passed
    assert violations == []
    assert len(exempt_notes) == 1
    assert "cra_marked" in exempt_notes[0]


def test_run_gate_exemption_does_not_bypass_strict_checks(tmp_path):
    """A band-exempt id with |irr| > 200% still fails the strict check."""
    portfolio = _make_portfolio([_rf_pos("cra_marked", irr=3.5)])  # 350%
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "standing-rules.yaml").write_text(_EXEMPT_CONFIG_YAML, encoding="utf-8")

    passed, violations, _ = gis.run_gate(portfolio_path, config_dir)
    assert not passed
    assert any("cra_marked" in v for v in violations)


# ---------------------------------------------------------------------------
# main() exit codes + event emission
# ---------------------------------------------------------------------------

def test_main_pass_exit_0(tmp_path, monkeypatch):
    portfolio = _make_portfolio([_rf_pos("cdb_ok", irr=0.10)])
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")

    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_irr_sanity.py",
        "--portfolio-path", str(portfolio_path),
    ])
    assert gis.main() == 0


def test_main_fail_exit_1_on_violation(tmp_path, monkeypatch):
    portfolio = _make_portfolio([_rf_pos("cdb_low", irr=0.02)])
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")

    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_irr_sanity.py",
        "--portfolio-path", str(portfolio_path),
    ])
    assert gis.main() == 1


def test_main_error_exit_2_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_irr_sanity.py",
        "--portfolio-path", str(tmp_path / "nope.json"),
    ])
    assert gis.main() == 2


def test_main_gate_event_emitted(tmp_path, monkeypatch):
    """gate_fail event emitted on violation."""
    import shared.lib.audit as audit_mod
    audit_mod._reset_cache_for_tests()

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()

    portfolio = _make_portfolio([_rf_pos("cdb_low", irr=0.02)])
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")

    monkeypatch.setenv("BOOKKEEPER_AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "0")
    monkeypatch.setattr(sys, "argv", [
        "gate_irr_sanity.py",
        "--portfolio-path", str(portfolio_path),
    ])

    result = gis.main()
    assert result == 1

    event_files = list(audit_dir.glob("events-*.jsonl"))
    assert event_files
    events = [json.loads(line) for line in event_files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    gate_events = [e for e in events if e.get("event_type") == "gate_fail"]
    assert gate_events
    assert gate_events[0]["gate"]["name"] == "gate_9_irr_sanity"

    audit_mod._reset_cache_for_tests()
