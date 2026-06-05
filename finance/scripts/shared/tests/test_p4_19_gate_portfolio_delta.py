"""Tests for gate #8 — Portfolio delta anomaly detector (p4-19)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gate_portfolio_delta import compute_anomalies, main


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _pos(id_: str, qty: float, val_brl: float) -> dict:
    return {"id": id_, "quantity": qty, "current_value_brl": val_brl}


# ---------------------------------------------------------------------------
# compute_anomalies unit tests
# ---------------------------------------------------------------------------


def test_no_anomalies_when_stable():
    """Small delta + same quantity → no anomalies."""
    current = [_pos("PETR4", 100, 3800.0)]
    prior = [_pos("PETR4", 100, 3700.0)]  # 2.7% change < 20%
    anomalies = compute_anomalies(current, prior)
    assert anomalies == []


def test_variacao_gt_20pct_detected():
    """Position value increase >20% → variacao_gt_20pct anomaly."""
    current = [_pos("PETR4", 100, 5000.0)]
    prior = [_pos("PETR4", 100, 3700.0)]  # ~35% increase
    anomalies = compute_anomalies(current, prior)
    assert len(anomalies) == 1
    assert anomalies[0]["anomaly_type"] == "variacao_gt_20pct"
    assert anomalies[0]["id"] == "PETR4"


def test_position_zeroed_detected():
    """Position with qty>0 in prior, qty=0 now → position_zeroed anomaly."""
    current = [_pos("MGLU3", 0, 0.0)]
    prior = [_pos("MGLU3", 500, 2000.0)]
    anomalies = compute_anomalies(current, prior)
    assert len(anomalies) == 1
    assert anomalies[0]["anomaly_type"] == "position_zeroed"


def test_new_unknown_ticker_detected():
    """New position not in prior snapshot → new_unknown_ticker anomaly."""
    current = [_pos("NEWCO", 100, 1000.0)]
    prior = []
    anomalies = compute_anomalies(current, prior)
    assert len(anomalies) == 1
    assert anomalies[0]["anomaly_type"] == "new_unknown_ticker"


def test_multiple_anomaly_types():
    """Multiple anomaly types in one call."""
    current = [
        _pos("PETR4", 100, 5000.0),   # variacao >20%
        _pos("MGLU3", 0, 0.0),         # zeroed
        _pos("NEWCO", 10, 500.0),      # new unknown
    ]
    prior = [
        _pos("PETR4", 100, 3700.0),
        _pos("MGLU3", 500, 2000.0),
    ]
    anomalies = compute_anomalies(current, prior)
    types = {a["anomaly_type"] for a in anomalies}
    assert "variacao_gt_20pct" in types
    assert "position_zeroed" in types
    assert "new_unknown_ticker" in types


def test_exactly_20pct_does_not_trigger():
    """Exactly 20% change does NOT trigger (threshold is strictly >20%)."""
    current = [_pos("PETR4", 100, 4440.0)]
    prior = [_pos("PETR4", 100, 3700.0)]  # exactly 20%
    anomalies = compute_anomalies(current, prior)
    assert anomalies == []


def test_prior_zero_value_skips_variacao():
    """Prior value = 0 → variacao check skipped (div-by-zero guard)."""
    current = [_pos("PETR4", 100, 1000.0)]
    prior = [_pos("PETR4", 100, 0.0)]
    anomalies = compute_anomalies(current, prior)
    # Should not raise; no variacao anomaly (skipped).
    variacao_anomalies = [a for a in anomalies if a["anomaly_type"] == "variacao_gt_20pct"]
    assert variacao_anomalies == []


# ---------------------------------------------------------------------------
# main() exit-code integration tests
# ---------------------------------------------------------------------------


def _write_portfolio(path: Path, positions: list[dict]):
    data = {"meta": {}, "summary": {}, "positions": positions, "income": {}}
    path.write_text(json.dumps(data), encoding="utf-8")


def test_main_pass_exit_0_no_anomalies(tmp_path, monkeypatch):
    portfolio_path = tmp_path / "portfolio.json"
    prior_path = tmp_path / "portfolio-2025-12-31.json"
    _write_portfolio(portfolio_path, [_pos("PETR4", 100, 3800.0)])
    _write_portfolio(prior_path, [_pos("PETR4", 100, 3700.0)])  # <20% change
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_portfolio_delta.py",
        "--portfolio", str(portfolio_path),
        "--prior-snapshot", str(prior_path),
    ])
    assert main() == 0


def test_main_fail_exit_1_variacao(tmp_path, monkeypatch):
    portfolio_path = tmp_path / "portfolio.json"
    prior_path = tmp_path / "portfolio-2025-12-31.json"
    _write_portfolio(portfolio_path, [_pos("PETR4", 100, 5000.0)])
    _write_portfolio(prior_path, [_pos("PETR4", 100, 3700.0)])   # >20% → anomaly
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_portfolio_delta.py",
        "--portfolio", str(portfolio_path),
        "--prior-snapshot", str(prior_path),
    ])
    assert main() == 1


def test_main_pass_exit_0_when_anomaly_flagged(tmp_path, monkeypatch):
    """Anomaly present but flagged by user → gate passes."""
    portfolio_path = tmp_path / "portfolio.json"
    prior_path = tmp_path / "portfolio-2025-12-31.json"
    _write_portfolio(portfolio_path, [_pos("PETR4", 100, 5000.0)])
    _write_portfolio(prior_path, [_pos("PETR4", 100, 3700.0)])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_portfolio_delta.py",
        "--portfolio", str(portfolio_path),
        "--prior-snapshot", str(prior_path),
        "--flagged-ids", "PETR4",
    ])
    assert main() == 0


def test_main_missing_portfolio_exit_2(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_portfolio_delta.py",
        "--portfolio", str(tmp_path / "nope.json"),
        "--prior-snapshot", str(tmp_path / "also-nope.json"),
    ])
    assert main() == 2


def test_gate_event_emitted(tmp_path, monkeypatch):
    """gate_fail event emitted when unflagged anomalies exist."""
    import lib.audit as audit_mod
    audit_mod._reset_cache_for_tests()

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    portfolio_path = tmp_path / "portfolio.json"
    prior_path = tmp_path / "portfolio-2025-12-31.json"
    _write_portfolio(portfolio_path, [_pos("PETR4", 100, 5000.0)])
    _write_portfolio(prior_path, [_pos("PETR4", 100, 3700.0)])

    monkeypatch.setenv("BOOKKEEPER_AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "0")
    monkeypatch.setattr(sys, "argv", [
        "gate_portfolio_delta.py",
        "--portfolio", str(portfolio_path),
        "--prior-snapshot", str(prior_path),
    ])

    result = main()
    assert result == 1

    event_files = list(audit_dir.glob("events-*.jsonl"))
    assert event_files
    events = [json.loads(line) for line in event_files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    gate_events = [e for e in events if e.get("event_type") == "gate_fail"]
    assert gate_events
    assert gate_events[0]["gate"]["name"] == "gate_8_portfolio_delta"

    audit_mod._reset_cache_for_tests()
