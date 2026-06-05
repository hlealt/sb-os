"""Tests for gates #1/#2/#3 — tagged despesas coverage before commit (p4-20/21/22).

S7 RESOLVED: threshold = 90% R$ tagged (gate #1), 90% rows (gate #2), R$100 floor (gate #3).
All three gates are ANDed in a single gate_coverage.py call.
"""

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gate_coverage import (
    compute_coverage,
    compute_row_coverage,
    find_large_untagged,
    main,
    _COVERAGE_THRESHOLD_FALLBACK,
    _UNTAGGED_FLOOR_FALLBACK,
)


# ---------------------------------------------------------------------------
# compute_coverage unit tests
# ---------------------------------------------------------------------------


def _make_rows(data: list[dict]) -> list[dict]:
    """Build minimal transaction row dicts."""
    return [
        {
            "date": r.get("date", "2026-03-15"),
            "description": r.get("description", "X"),
            "amount": str(r.get("amount", -100)),
            "category": r.get("category", "alimentacao"),
            "tags": r.get("tags", ""),
        }
        for r in data
    ]


def test_fully_tagged_returns_100pct():
    rows = _make_rows([
        {"amount": -100, "category": "alimentacao", "tags": "refeicao"},
        {"amount": -50, "category": "transporte", "tags": "uber"},
    ])
    coverage, tagged, total = compute_coverage(rows)
    assert coverage == 1.0
    assert tagged == 150.0
    assert total == 150.0


def test_fully_untagged_returns_0pct():
    rows = _make_rows([
        {"amount": -100, "category": "alimentacao", "tags": ""},
        {"amount": -50, "category": "transporte", "tags": ""},
    ])
    coverage, tagged, total = compute_coverage(rows)
    assert coverage == 0.0
    assert tagged == 0.0
    assert total == 150.0


def test_partial_coverage():
    rows = _make_rows([
        {"amount": -90, "category": "alimentacao", "tags": "refeicao"},  # tagged
        {"amount": -10, "category": "transporte", "tags": ""},           # untagged
    ])
    coverage, tagged, total = compute_coverage(rows)
    assert coverage == pytest.approx(0.90)
    assert tagged == 90.0
    assert total == 100.0


def test_excluded_categories_not_counted():
    """receitas, intercontas, ignorar, venda are excluded from coverage calc."""
    rows = _make_rows([
        {"amount": 1000, "category": "receitas", "tags": ""},   # income → excluded
        {"amount": -100, "category": "intercontas", "tags": ""},  # transfer → excluded
        {"amount": -200, "category": "alimentacao", "tags": ""},  # despesa, untagged
    ])
    coverage, tagged, total = compute_coverage(rows)
    # Only -200 counts; it is untagged → 0%.
    assert total == 200.0
    assert tagged == 0.0
    assert coverage == 0.0


def test_positive_amounts_excluded():
    """Positive amounts (income rows not in excluded categories) are skipped."""
    rows = _make_rows([
        {"amount": 500, "category": "alimentacao", "tags": "some_tag"},  # positive → not a despesa
        {"amount": -100, "category": "alimentacao", "tags": "refeicao"},  # despesa
    ])
    coverage, tagged, total = compute_coverage(rows)
    assert total == 100.0
    assert tagged == 100.0
    assert coverage == 1.0


def test_empty_rows_returns_1():
    """No despesas → vacuous full coverage (nothing to tag)."""
    coverage, tagged, total = compute_coverage([])
    assert coverage == 1.0
    assert total == 0.0


def test_threshold_fallback_is_90pct():
    """The hard-coded fallback threshold matches the S7 resolved value."""
    assert _COVERAGE_THRESHOLD_FALLBACK == 0.90


def test_untagged_floor_fallback_is_100():
    """The hard-coded fallback floor matches the S7 resolved R$100 value."""
    assert _UNTAGGED_FLOOR_FALLBACK == 100.0


# ---------------------------------------------------------------------------
# Gate #2 — compute_row_coverage
# ---------------------------------------------------------------------------


def test_row_coverage_fully_tagged():
    rows = _make_rows([
        {"amount": -100, "category": "alimentacao", "tags": "refeicao"},
        {"amount": -50, "category": "transporte", "tags": "uber"},
    ])
    cov, tagged, total = compute_row_coverage(rows)
    assert cov == 1.0
    assert tagged == 2
    assert total == 2


def test_row_coverage_fully_untagged():
    rows = _make_rows([
        {"amount": -100, "category": "alimentacao", "tags": ""},
        {"amount": -50, "category": "transporte", "tags": ""},
    ])
    cov, tagged, total = compute_row_coverage(rows)
    assert cov == 0.0
    assert tagged == 0
    assert total == 2


def test_row_coverage_partial():
    rows = _make_rows([
        {"amount": -10, "category": "alimentacao", "tags": "refeicao"},  # tagged
        {"amount": -1000, "category": "transporte", "tags": ""},         # untagged (large)
        {"amount": -5, "category": "saude", "tags": ""},                 # untagged (small)
        {"amount": -5, "category": "lazer", "tags": ""},                 # untagged (small)
        {"amount": -5, "category": "moradia", "tags": ""},               # untagged (small)
        {"amount": -5, "category": "carro", "tags": ""},                 # untagged (small)
        {"amount": -5, "category": "compras", "tags": ""},               # untagged (small)
        {"amount": -5, "category": "pessoal", "tags": ""},               # untagged (small)
        {"amount": -5, "category": "educacao", "tags": ""},              # untagged (small)
        {"amount": -10, "category": "assinaturas", "tags": ""},          # untagged
    ])
    cov, tagged, total = compute_row_coverage(rows)
    assert total == 10
    assert tagged == 1
    assert cov == pytest.approx(0.10)


def test_row_coverage_excludes_non_despesas():
    rows = _make_rows([
        {"amount": 1000, "category": "receitas", "tags": ""},     # excluded (positive + receitas)
        {"amount": -100, "category": "intercontas", "tags": ""},  # excluded category
        {"amount": -100, "category": "alimentacao", "tags": "ok"},
    ])
    cov, tagged, total = compute_row_coverage(rows)
    assert total == 1
    assert tagged == 1
    assert cov == 1.0


def test_row_coverage_empty():
    cov, tagged, total = compute_row_coverage([])
    assert cov == 1.0
    assert total == 0


# ---------------------------------------------------------------------------
# Gate #3 — find_large_untagged
# ---------------------------------------------------------------------------


def test_find_large_untagged_none_above_floor():
    rows = _make_rows([
        {"amount": -50, "category": "alimentacao", "tags": ""},   # untagged but <= 100
        {"amount": -100, "category": "transporte", "tags": ""},   # exactly at floor (not >, so OK)
        {"amount": -200, "category": "saude", "tags": "medico"},  # tagged, any amount
    ])
    violations = find_large_untagged(rows, 100.0)
    assert violations == []


def test_find_large_untagged_detects_violation():
    rows = _make_rows([
        {"amount": -500, "category": "alimentacao", "tags": ""},   # untagged > 100 → violation
        {"amount": -50, "category": "transporte", "tags": ""},     # untagged but <= 100 → ok
    ])
    violations = find_large_untagged(rows, 100.0)
    assert len(violations) == 1
    assert abs(float(violations[0]["amount"])) == 500.0


def test_find_large_untagged_tagged_rows_excluded():
    rows = _make_rows([
        {"amount": -500, "category": "alimentacao", "tags": "refeicao"},  # tagged → ok
    ])
    violations = find_large_untagged(rows, 100.0)
    assert violations == []


def test_find_large_untagged_excluded_categories_skipped():
    rows = _make_rows([
        {"amount": -500, "category": "receitas", "tags": ""},    # excluded
        {"amount": -500, "category": "intercontas", "tags": ""}, # excluded
        {"amount": -500, "category": "ignorar", "tags": ""},     # excluded
        {"amount": -500, "category": "venda", "tags": ""},       # excluded
    ])
    violations = find_large_untagged(rows, 100.0)
    assert violations == []


# ---------------------------------------------------------------------------
# main() exit-code integration tests
# ---------------------------------------------------------------------------


def _write_csv(path: Path, rows: list[dict]):
    fieldnames = ["date", "description", "amount", "category", "tags"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_main_pass_exit_0_all_three_gates(tmp_path, monkeypatch):
    """All three gates pass: R$>=90%, rows>=90%, no untagged>R$100 → exit 0.

    10 rows: 9 tagged at various amounts, 1 untagged at R$50 (< floor).
    R$ coverage: (90+80+70+60+50+40+30+20+10)/(90+80+70+60+50+40+30+20+10+50) = 450/500 = 90%.
    Row coverage: 9/10 = 90%.
    No untagged > R$100.
    """
    tx_path = tmp_path / "transactions.csv"
    rows = [
        {"date": "2026-03-01", "description": f"T{i}", "amount": str(-amount),
         "category": "alimentacao", "tags": "refeicao"}
        for i, amount in enumerate([90, 80, 70, 60, 50, 40, 30, 20, 10], 1)
    ]
    rows.append({"date": "2026-03-10", "description": "Untagged", "amount": "-50",
                 "category": "transporte", "tags": ""})
    _write_csv(tx_path, rows)
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
    ])
    assert main() == 0


def test_main_fail_gate2_rows_below_90pct(tmp_path, monkeypatch):
    """R$ coverage fine but rows coverage < 90% → exit 1."""
    tx_path = tmp_path / "transactions.csv"
    # 1 tagged row at R$999, 9 untagged at R$1 each. R$ coverage=999/1008≈99%, rows=1/10=10%.
    rows = [{"date": "2026-03-01", "description": "Big", "amount": "-999",
              "category": "alimentacao", "tags": "refeicao"}]
    rows += [
        {"date": "2026-03-02", "description": f"Small{i}", "amount": "-1",
         "category": "transporte", "tags": ""}
        for i in range(9)
    ]
    _write_csv(tx_path, rows)
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
    ])
    assert main() == 1


def test_main_fail_gate3_large_untagged(tmp_path, monkeypatch):
    """R$ and rows coverage fine but untagged row > R$100 → exit 1."""
    tx_path = tmp_path / "transactions.csv"
    # 9 tagged at R$10 each + 1 untagged at R$101. R$ coverage=90/191≈47%? No.
    # Use: 9 tagged at R$1000 each + 1 untagged at R$101. R$=9000/9101≈99%, rows=9/10=90%.
    rows = [
        {"date": "2026-03-01", "description": f"T{i}", "amount": "-1000",
         "category": "alimentacao", "tags": "refeicao"}
        for i in range(9)
    ]
    rows.append({"date": "2026-03-10", "description": "BigUntagged", "amount": "-101",
                 "category": "transporte", "tags": ""})
    _write_csv(tx_path, rows)
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
    ])
    assert main() == 1


def test_main_pass_exit_0_at_90pct(tmp_path, monkeypatch):
    """Simple 90% R$ coverage (original gate #1 test, preserved)."""
    tx_path = tmp_path / "transactions.csv"
    _write_csv(tx_path, [
        {"date": "2026-03-01", "description": "A", "amount": "-90", "category": "alimentacao", "tags": "refeicao"},
        {"date": "2026-03-02", "description": "B", "amount": "-10", "category": "transporte", "tags": ""},
    ])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
    ])
    # Row coverage: 1/2 = 50% < 90% → FAIL (gate #2 fails).
    # The original test expected pass; it now correctly fails due to gate #2.
    # Update: R$=90%, rows=50% → combined FAIL.
    assert main() == 1


def test_main_fail_exit_1_below_90pct(tmp_path, monkeypatch):
    """R$ 89% coverage → exit 1 (gate #1 fails; gate #2 also fails: 1/2 rows = 50%)."""
    tx_path = tmp_path / "transactions.csv"
    _write_csv(tx_path, [
        {"date": "2026-03-01", "description": "A", "amount": "-89", "category": "alimentacao", "tags": "refeicao"},
        {"date": "2026-03-02", "description": "B", "amount": "-11", "category": "transporte", "tags": ""},
    ])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
    ])
    assert main() == 1


def test_main_missing_file_exit_2(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tmp_path / "nope.csv"),
    ])
    assert main() == 2


def test_main_max_loop_guard_surfaces_prompt(tmp_path, monkeypatch, capsys):
    """After 3 loops, gate surfaces a user prompt instead of auto-looping."""
    tx_path = tmp_path / "transactions.csv"
    # Single untagged row — fails gate #1, #2, and #3 (if > 100). Use R$50 so only #1/#2 fail.
    _write_csv(tx_path, [
        {"date": "2026-03-01", "description": "A", "amount": "-50", "category": "alimentacao", "tags": ""},
    ])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
        "--loop-count", "3",
    ])
    result = main()
    assert result == 1
    captured = capsys.readouterr()
    # The max-loop guard message must appear in stderr — including the exact
    # prompt step-05-review.md § completion gate quotes ([S/N] keys are contract).
    assert "Proceed anyway? [S/N]" in captured.err
    assert "Insufficient coverage" in captured.err


def test_gate_events_emitted_on_fail(tmp_path, monkeypatch):
    """coverage_progress + gate_fail events are emitted when gate #1 fails."""
    import lib.audit as audit_mod
    import json
    audit_mod._reset_cache_for_tests()

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    tx_path = tmp_path / "transactions.csv"
    # Fully untagged: all three gates fail.
    _write_csv(tx_path, [
        {"date": "2026-03-01", "description": "A", "amount": "-50", "category": "alimentacao", "tags": ""},
    ])

    monkeypatch.setenv("BOOKKEEPER_AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "0")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
    ])

    result = main()
    assert result == 1

    event_files = list(audit_dir.glob("events-*.jsonl"))
    assert event_files
    events = [json.loads(line) for line in event_files[0].read_text(encoding="utf-8").splitlines() if line.strip()]

    event_types = {e.get("event_type") for e in events}
    assert "coverage_progress" in event_types
    assert "gate_fail" in event_types

    gate_fail_events = [e for e in events if e.get("event_type") == "gate_fail"]
    assert gate_fail_events[0]["gate"]["name"] == "gate_1_coverage"
    assert gate_fail_events[0]["gate"]["threshold"] == pytest.approx(0.90)

    audit_mod._reset_cache_for_tests()


def test_gate_pass_event_emitted_on_all_pass(tmp_path, monkeypatch):
    """gate_pass event emitted when all three gates pass."""
    import lib.audit as audit_mod
    import json
    audit_mod._reset_cache_for_tests()

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    tx_path = tmp_path / "transactions.csv"
    # 10 rows: 9 tagged at R$100, 1 untagged at R$50 (<= floor). R$=900/950=94.7%, rows=9/10=90%.
    rows = [
        {"date": "2026-03-01", "description": f"T{i}", "amount": "-100",
         "category": "alimentacao", "tags": "refeicao"}
        for i in range(9)
    ]
    rows.append({"date": "2026-03-10", "description": "Small", "amount": "-50",
                 "category": "transporte", "tags": ""})
    _write_csv(tx_path, rows)

    monkeypatch.setenv("BOOKKEEPER_AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "0")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
    ])

    result = main()
    assert result == 0

    event_files = list(audit_dir.glob("events-*.jsonl"))
    assert event_files
    events = [json.loads(line) for line in event_files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    gate_events = [e for e in events if e.get("event_type") == "gate_pass"]
    assert gate_events
    assert gate_events[0]["gate"]["name"] == "gate_1_coverage"

    audit_mod._reset_cache_for_tests()
