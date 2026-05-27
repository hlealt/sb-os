"""Tests for gate #10 — bucket IRR divergence gate (p4-24).

5% threshold is the evidence-based default from p2-15.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_bucket_divergence as gbd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_portfolio(positions: list[dict], per_class: dict | None = None) -> dict:
    return {
        "meta": {"cut_date": "2026-03-31", "generated_at": "2026-03-31T00:00:00Z"},
        "summary": {
            "total_value": 1000.0,
            "total_pnl": 100.0,
            "irr": {
                "total": 0.10,
                "per_class": per_class or {},
            },
        },
        "positions": positions,
    }


# ---------------------------------------------------------------------------
# check_divergences (via bucket_sanity_check.check_buckets)
# ---------------------------------------------------------------------------

def test_no_divergence_within_threshold():
    """Single rv_br position whose IRR matches stored bucket exactly → 0 divergences."""
    positions = [{"id": "ITSA3", "type": "acao", "asset_class": "variable_income",
                  "currency": "BRL", "irr": 0.10}]
    per_class = {"rv_br": {"irr": 0.10, "terminal_value": 1000.0, "flow_count": 5}}
    portfolio = _make_portfolio(positions, per_class)

    divergences = gbd.check_divergences(portfolio, "rv_br", 0.05)
    assert divergences == 0


def test_divergence_detected_above_threshold():
    """rv_eua: stored IRR 0.0599, simple avg 0.5264 → delta 0.4665 > 0.05 → 1 divergence."""
    positions = [
        {"id": "BRK.B", "type": "acao", "asset_class": "variable_income",
         "currency": "USD", "irr": 0.5264},
    ]
    per_class = {"rv_eua": {"irr": 0.0599, "terminal_value": 5000.0, "flow_count": 10}}
    portfolio = _make_portfolio(positions, per_class)

    divergences = gbd.check_divergences(portfolio, "rv_eua", 0.05)
    assert divergences == 1


def test_no_positions_in_bucket():
    """A bucket with no positions is skipped (not a divergence)."""
    portfolio = _make_portfolio([], {"crypto": {"irr": 0.10, "terminal_value": 0.0, "flow_count": 0}})
    divergences = gbd.check_divergences(portfolio, "crypto", 0.05)
    assert divergences == 0


def test_positions_without_irr_skipped():
    """Positions with irr=None are excluded from simple avg (bucket reports cannot compute → skip)."""
    positions = [{"id": "IVVB11", "type": "etf", "asset_class": "variable_income",
                  "currency": "BRL", "irr": None}]
    per_class = {"rv_br": {"irr": 0.10, "terminal_value": 100.0, "flow_count": 1}}
    portfolio = _make_portfolio(positions, per_class)
    # No irr values → cannot compute simple avg → skipped, not a divergence.
    divergences = gbd.check_divergences(portfolio, "rv_br", 0.05)
    assert divergences == 0


# ---------------------------------------------------------------------------
# main() exit codes + event emission
# ---------------------------------------------------------------------------

def test_main_pass_exit_0(tmp_path, monkeypatch):
    """No divergences → exit 0."""
    positions = [{"id": "ITSA3", "type": "acao", "asset_class": "variable_income",
                  "currency": "BRL", "irr": 0.10}]
    per_class = {"rv_br": {"irr": 0.10, "terminal_value": 1000.0, "flow_count": 5}}
    portfolio = _make_portfolio(positions, per_class)
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")

    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_bucket_divergence.py",
        "--portfolio-path", str(portfolio_path),
    ])
    assert gbd.main() == 0


def test_main_fail_exit_1_on_divergence(tmp_path, monkeypatch):
    """Divergence detected → exit 1."""
    positions = [{"id": "BRK.B", "type": "acao", "asset_class": "variable_income",
                  "currency": "USD", "irr": 0.5264}]
    per_class = {"rv_eua": {"irr": 0.0599, "terminal_value": 5000.0, "flow_count": 10}}
    portfolio = _make_portfolio(positions, per_class)
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")

    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_bucket_divergence.py",
        "--portfolio-path", str(portfolio_path),
    ])
    assert gbd.main() == 1


def test_main_error_exit_2_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_bucket_divergence.py",
        "--portfolio-path", str(tmp_path / "nope.json"),
    ])
    assert gbd.main() == 2


def test_main_gate_event_emitted(tmp_path, monkeypatch):
    """gate_fail event emitted on divergence."""
    import shared.lib.audit as audit_mod
    audit_mod._reset_cache_for_tests()

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()

    positions = [{"id": "BRK.B", "type": "acao", "asset_class": "variable_income",
                  "currency": "USD", "irr": 0.5264}]
    per_class = {"rv_eua": {"irr": 0.0599, "terminal_value": 5000.0, "flow_count": 10}}
    portfolio = _make_portfolio(positions, per_class)
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")

    monkeypatch.setenv("BOOKKEEPER_AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "0")
    monkeypatch.setattr(sys, "argv", [
        "gate_bucket_divergence.py",
        "--portfolio-path", str(portfolio_path),
    ])

    result = gbd.main()
    assert result == 1

    event_files = list(audit_dir.glob("events-*.jsonl"))
    assert event_files
    events = [json.loads(line) for line in event_files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    gate_events = [e for e in events if e.get("event_type") == "gate_fail"]
    assert gate_events
    assert gate_events[0]["gate"]["name"] == "gate_10_bucket_divergence"

    audit_mod._reset_cache_for_tests()


def test_main_gate_pass_event_emitted(tmp_path, monkeypatch):
    """gate_pass event emitted on clean portfolio."""
    import shared.lib.audit as audit_mod
    audit_mod._reset_cache_for_tests()

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()

    positions = [{"id": "ITSA3", "type": "acao", "asset_class": "variable_income",
                  "currency": "BRL", "irr": 0.10}]
    per_class = {"rv_br": {"irr": 0.10, "terminal_value": 1000.0, "flow_count": 5}}
    portfolio = _make_portfolio(positions, per_class)
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")

    monkeypatch.setenv("BOOKKEEPER_AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "0")
    monkeypatch.setattr(sys, "argv", [
        "gate_bucket_divergence.py",
        "--portfolio-path", str(portfolio_path),
    ])

    result = gbd.main()
    assert result == 0

    event_files = list(audit_dir.glob("events-*.jsonl"))
    assert event_files
    events = [json.loads(line) for line in event_files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    gate_events = [e for e in events if e.get("event_type") == "gate_pass"]
    assert gate_events
    assert gate_events[0]["gate"]["name"] == "gate_10_bucket_divergence"

    audit_mod._reset_cache_for_tests()
