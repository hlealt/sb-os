"""Tests for gates #1/#2/#3 — tagged despesas coverage before commit (p4-20/21/22).

2026-06-05 REDESIGN contract:
  Gate #1 (R$ coverage): R$-coverage >= config threshold (standing-rules.yaml
    gates.step_5_5_coverage.threshold, recalibrated to 0.75). Fallback in code
    is 0.75 (lowered from 0.90 to match config; the config drives the gate).
  Gate #2 (row coverage): INFORMATIONAL ONLY — computed and printed but NEVER
    fails the gate. Audit event still emitted.
  Gate #3 (large untagged): no UNACKNOWLEDGED untagged despesa with
    abs(amount) > floor (config tag_coverage.gate.untagged_amount_threshold_brl,
    recalibrated to 300). Acked rows print as visible ACK notes, not violations.
    Ack side-ledger: .user/finance/bookkeeper/config/corrections/tag-review-acks.csv
    (header: tx_date,tx_description,tx_amount,month,acked_at,source,note).

Exit codes:
  0  Pass — gate #1 passes AND no unacknowledged untagged despesa > floor
  1  Fail — gate #1 fails OR unacknowledged untagged despesa > floor
  2  Error — transactions file missing or malformed; ack file present but
             missing required identity columns (tx_date, tx_description, tx_amount)
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
    load_tag_review_acks,
    main,
    _COVERAGE_THRESHOLD_FALLBACK,
    _UNTAGGED_FLOOR_FALLBACK,
)


# ---------------------------------------------------------------------------
# Helpers
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


def _write_csv(path: Path, rows: list[dict]):
    fieldnames = ["date", "description", "amount", "category", "tags"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_ack_csv(path: Path, rows: list[dict]):
    """Write an ack file with the canonical header."""
    fieldnames = ["tx_date", "tx_description", "tx_amount", "month", "acked_at", "source", "note"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# compute_coverage unit tests (unchanged behaviour)
# ---------------------------------------------------------------------------


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


def test_threshold_fallback_is_75pct():
    """Code fallback = 0.75 — matches the config-recalibrated value (2026-06-05).

    The old value was 0.90; it is now 0.75 to match standing-rules.yaml
    gates.step_5_5_coverage.threshold. The config drives the gate; this fallback
    is the in-code safe default when config is unreachable.
    """
    assert _COVERAGE_THRESHOLD_FALLBACK == 0.75


def test_untagged_floor_fallback_is_100():
    """The hard-coded fallback floor stays R$100.

    The config has been recalibrated to R$300 (tag_coverage.gate.
    untagged_amount_threshold_brl). The code fallback stays at R$100 (more
    conservative) to match the original S7 value; the config drives the gate
    in production.
    """
    assert _UNTAGGED_FLOOR_FALLBACK == 100.0


# ---------------------------------------------------------------------------
# Gate #2 — compute_row_coverage (behaviour unchanged; semantics changed)
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
# Gate #2 — INFORMATIONAL ONLY: low row coverage NEVER fails the gate
# ---------------------------------------------------------------------------


def test_gate2_row_coverage_never_fails_gate(tmp_path, monkeypatch):
    """Gate #2 redesign (2026-06-05): row coverage is informational, never exit 1.

    R$ coverage fine (100%), row coverage = 10% (1/10) — under any threshold.
    With the new contract gate #2 cannot cause failure → exit 0.
    """
    tx_path = tmp_path / "transactions.csv"
    # 1 tagged at R$999, 9 untagged at R$1 — R$=999/1008≈99%, rows=1/10=10%.
    # All untagged amounts <= R$100, so gate #3 also passes.
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
    # Row coverage 10% is informational; R$ ≈ 99% >= 75%; no untagged > floor → PASS.
    assert main() == 0


def test_gate2_row_coverage_printed_as_informational(tmp_path, monkeypatch, capsys):
    """Row coverage line is printed and marked as informational in the output."""
    tx_path = tmp_path / "transactions.csv"
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
    main()
    captured = capsys.readouterr()
    # Row coverage must appear in output (stdout or stderr) with the word "informational"
    combined = captured.out + captured.err
    assert "row" in combined.lower()
    assert "informational" in combined.lower()


# ---------------------------------------------------------------------------
# Gate #3 — find_large_untagged (no ack logic — pure violation detection)
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
# Gate #3 ack side-ledger — load_tag_review_acks
# ---------------------------------------------------------------------------


def test_load_tag_review_acks_absent_path_returns_empty_set(tmp_path):
    """(f) Missing ack file → empty ack set (fail-soft)."""
    acks = load_tag_review_acks(tmp_path / "does_not_exist.csv")
    assert acks == set()


def test_load_tag_review_acks_valid_file(tmp_path):
    """Valid ack file → correct identity keys in returned set."""
    ack_path = tmp_path / "tag-review-acks.csv"
    _write_ack_csv(ack_path, [
        {"tx_date": "2026-04-02", "tx_description": "Pix enviado Romeu",
         "tx_amount": "-400.0", "month": "2026-04", "acked_at": "2026-06-05T00:00:00",
         "source": "review-mode-2026-04", "note": "no tag applies"},
    ])
    acks = load_tag_review_acks(ack_path)
    assert len(acks) == 1
    # Identity: (date, description, repr(float(amount)))
    assert ("2026-04-02", "Pix enviado Romeu", repr(float("-400.0"))) in acks


def test_load_tag_review_acks_missing_identity_columns_exit_2(tmp_path):
    """(c) Ack file present but missing required identity columns → raises SystemExit(2)."""
    ack_path = tmp_path / "tag-review-acks.csv"
    # Write a CSV that lacks tx_amount (required identity column)
    with open(ack_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["tx_date", "tx_description", "month"])
        writer.writeheader()
        writer.writerow({"tx_date": "2026-04-02", "tx_description": "Foo", "month": "2026-04"})
    with pytest.raises(SystemExit) as exc_info:
        load_tag_review_acks(ack_path)
    assert exc_info.value.code == 2


def test_load_tag_review_acks_trailing_zero_normalization(tmp_path):
    """(e) Identity parity with categorize._tx_amount_key: -400.0 == -400.00."""
    ack_path = tmp_path / "tag-review-acks.csv"
    _write_ack_csv(ack_path, [
        {"tx_date": "2026-04-02", "tx_description": "Foo",
         "tx_amount": "-400.00",  # trailing-zero variant
         "month": "2026-04", "acked_at": "2026-06-05T00:00:00",
         "source": "test", "note": ""},
    ])
    acks = load_tag_review_acks(ack_path)
    # repr(float("-400.00")) == repr(float("-400.0")) == "-400.0"
    assert ("2026-04-02", "Foo", repr(float("-400.0"))) in acks
    # The -400.0 and -400.00 variants must resolve to the SAME key
    assert ("2026-04-02", "Foo", repr(float("-400.00"))) in acks


def test_load_tag_review_acks_integer_amount_parity(tmp_path):
    """(e) -400 (int-like) matches -400.0 (float-like) — same categorize normalization."""
    ack_path = tmp_path / "tag-review-acks.csv"
    _write_ack_csv(ack_path, [
        {"tx_date": "2026-04-02", "tx_description": "Foo",
         "tx_amount": "-400",
         "month": "2026-04", "acked_at": "2026-06-05T00:00:00",
         "source": "test", "note": ""},
    ])
    acks = load_tag_review_acks(ack_path)
    # repr(float("-400")) == "-400.0"
    assert ("2026-04-02", "Foo", "-400.0") in acks


# ---------------------------------------------------------------------------
# Gate #3 ack integration — acked rows produce ACK note, not violation
# ---------------------------------------------------------------------------


def test_gate3_acked_row_above_floor_exits_0(tmp_path, monkeypatch):
    """(a) Acked row above floor → exit 0 + ACK note in output (not a violation)."""
    tx_path = tmp_path / "transactions.csv"
    ack_path = tmp_path / "tag-review-acks.csv"
    # R$ coverage: 1 tagged at R$1000, 1 untagged at R$400 (above floor R$100 fallback).
    # R$ = 1000/1400 ≈ 71.4% — use fallback 75% threshold: FAILS gate #1 unless we
    # make R$ higher. Use: tagged=R$1000, untagged=R$400 → 71.4%. That fails gate #1.
    # Use: tagged=R$2000, untagged=R$400 → 83.3% >= 75% → passes gate #1.
    _write_csv(tx_path, [
        {"date": "2026-04-02", "description": "BigTagged", "amount": "-2000",
         "category": "alimentacao", "tags": "refeicao"},
        {"date": "2026-04-02", "description": "AckedRow", "amount": "-400.0",
         "category": "alimentacao", "tags": ""},
    ])
    _write_ack_csv(ack_path, [
        {"tx_date": "2026-04-02", "tx_description": "AckedRow", "tx_amount": "-400.0",
         "month": "2026-04", "acked_at": "2026-06-05T00:00:00",
         "source": "review-mode-2026-04", "note": "no tag applies"},
    ])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
        "--ack-file", str(ack_path),
    ])
    assert main() == 0


def test_gate3_acked_row_prints_ack_note(tmp_path, monkeypatch, capsys):
    """(a) Acked row prints a visible ACK note (never silent skip)."""
    tx_path = tmp_path / "transactions.csv"
    ack_path = tmp_path / "tag-review-acks.csv"
    _write_csv(tx_path, [
        {"date": "2026-04-02", "description": "BigTagged", "amount": "-2000",
         "category": "alimentacao", "tags": "refeicao"},
        {"date": "2026-04-02", "description": "AckedRow", "amount": "-400.0",
         "category": "alimentacao", "tags": ""},
    ])
    _write_ack_csv(ack_path, [
        {"tx_date": "2026-04-02", "tx_description": "AckedRow", "tx_amount": "-400.0",
         "month": "2026-04", "acked_at": "2026-06-05T00:00:00",
         "source": "review-mode-2026-04", "note": "no tag applies"},
    ])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
        "--ack-file", str(ack_path),
    ])
    main()
    combined = capsys.readouterr().out + capsys.readouterr().err
    assert "ACK" in combined


def test_gate3_unacked_row_above_floor_exits_1(tmp_path, monkeypatch):
    """(b) Unacked row above floor → exit 1."""
    tx_path = tmp_path / "transactions.csv"
    ack_path = tmp_path / "tag-review-acks.csv"
    # R$: tagged=R$2000, untagged=R$400 → 83.3% >= 75% → gate #1 passes.
    # Gate #3: unacked row at R$400 > R$100 floor → FAIL.
    _write_csv(tx_path, [
        {"date": "2026-04-02", "description": "BigTagged", "amount": "-2000",
         "category": "alimentacao", "tags": "refeicao"},
        {"date": "2026-04-02", "description": "UnackedRow", "amount": "-400.0",
         "category": "alimentacao", "tags": ""},
    ])
    # Empty ack file — UnackedRow has no ack.
    _write_ack_csv(ack_path, [])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
        "--ack-file", str(ack_path),
    ])
    assert main() == 1


def test_gate3_ack_file_missing_identity_columns_exits_2(tmp_path, monkeypatch):
    """(c) Ack file present but missing tx_amount column → exit 2 (SystemExit(2))."""
    tx_path = tmp_path / "transactions.csv"
    ack_path = tmp_path / "tag-review-acks.csv"
    _write_csv(tx_path, [
        {"date": "2026-04-02", "description": "A", "amount": "-100",
         "category": "alimentacao", "tags": "tag"},
    ])
    # Write a broken ack file missing tx_amount.
    with open(ack_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["tx_date", "tx_description", "month"])
        writer.writeheader()
        writer.writerow({"tx_date": "2026-04-02", "tx_description": "A", "month": "2026-04"})
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
        "--ack-file", str(ack_path),
    ])
    # load_tag_review_acks calls sys.exit(2) directly — main never returns.
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 2


def test_gate3_missing_ack_file_behaves_as_empty_ack_set(tmp_path, monkeypatch):
    """(f) Missing ack file → behaves as empty ack set (fail-soft).

    No violations above floor → exit 0 even without an ack file.
    """
    tx_path = tmp_path / "transactions.csv"
    # All untagged are below floor (R$50 < R$100), so gate #3 passes.
    # R$: tagged=R$100 → 100/150=66.7% — below 75% fallback, gate #1 fails.
    # Use: tagged=R$200, untagged=R$50 → 200/250=80% >= 75%.
    _write_csv(tx_path, [
        {"date": "2026-04-02", "description": "Tagged", "amount": "-200",
         "category": "alimentacao", "tags": "refeicao"},
        {"date": "2026-04-02", "description": "SmallUntagged", "amount": "-50",
         "category": "transporte", "tags": ""},
    ])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    # Do NOT pass --ack-file; default path should be missing → empty ack set.
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
        "--ack-file", str(tmp_path / "nonexistent_acks.csv"),
    ])
    # No violations above floor → exit 0.
    assert main() == 0


def test_gate3_ack_identity_parity_with_categorize(tmp_path, monkeypatch):
    """(e) Ack key uses same normalization as categorize.tx_identity.

    An ack row with amount '-400.00' must match a tx row with amount '-400.0'
    (float normalization: repr(float('-400.00')) == repr(float('-400.0'))).
    """
    tx_path = tmp_path / "transactions.csv"
    ack_path = tmp_path / "tag-review-acks.csv"
    _write_csv(tx_path, [
        {"date": "2026-04-02", "description": "BigTagged", "amount": "-2000",
         "category": "alimentacao", "tags": "refeicao"},
        # Transaction uses -400.0 (trailing zero, float format from parser)
        {"date": "2026-04-02", "description": "AckedRow", "amount": "-400.0",
         "category": "alimentacao", "tags": ""},
    ])
    # Ack file uses -400.00 (extra zero — drift between ledger and corrections file)
    _write_ack_csv(ack_path, [
        {"tx_date": "2026-04-02", "tx_description": "AckedRow", "tx_amount": "-400.00",
         "month": "2026-04", "acked_at": "2026-06-05T00:00:00",
         "source": "test", "note": ""},
    ])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
        "--ack-file", str(ack_path),
    ])
    # The -400.00 ack must match the -400.0 tx → exit 0 (not a violation).
    assert main() == 0


def test_gate3_acked_count_in_audit_trigger_context(tmp_path, monkeypatch):
    """gate3_acked_skips count is present in the gate event's trigger_context."""
    import lib.audit as audit_mod
    import json
    audit_mod._reset_cache_for_tests()

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    tx_path = tmp_path / "transactions.csv"
    ack_path = tmp_path / "tag-review-acks.csv"
    _write_csv(tx_path, [
        {"date": "2026-04-02", "description": "BigTagged", "amount": "-2000",
         "category": "alimentacao", "tags": "refeicao"},
        {"date": "2026-04-02", "description": "AckedRow", "amount": "-400.0",
         "category": "alimentacao", "tags": ""},
    ])
    _write_ack_csv(ack_path, [
        {"tx_date": "2026-04-02", "tx_description": "AckedRow", "tx_amount": "-400.0",
         "month": "2026-04", "acked_at": "2026-06-05T00:00:00",
         "source": "test", "note": ""},
    ])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "0")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
        "--ack-file", str(ack_path),
    ])
    result = main()
    assert result == 0

    event_files = list(audit_dir.glob("events-*.jsonl"))
    assert event_files
    events = [json.loads(line) for line in event_files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    gate_events = [e for e in events if e.get("event_type") in ("gate_pass", "gate_fail")]
    assert gate_events
    # trigger_context is a top-level event field, not nested inside gate.
    tc = gate_events[0]["trigger_context"]
    assert "gate3_acked_skips" in tc
    assert tc["gate3_acked_skips"] == 1

    audit_mod._reset_cache_for_tests()


# ---------------------------------------------------------------------------
# main() integration tests (updated for new contract)
# ---------------------------------------------------------------------------


def test_main_pass_exit_0_r75_pct_no_violations(tmp_path, monkeypatch):
    """Gate #1: R$>=75%, gate #2 informational, gate #3 no unacked violations → exit 0."""
    tx_path = tmp_path / "transactions.csv"
    # R$: tagged=R$75, untagged=R$25 → 75% >= 75% (exact threshold).
    _write_csv(tx_path, [
        {"date": "2026-03-01", "description": "A", "amount": "-75",
         "category": "alimentacao", "tags": "refeicao"},
        {"date": "2026-03-02", "description": "B", "amount": "-25",
         "category": "transporte", "tags": ""},
    ])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
    ])
    # R$=75%, row=50% (informational), no untagged > R$100 floor → PASS.
    assert main() == 0


def test_main_fail_gate1_r_below_threshold(tmp_path, monkeypatch):
    """R$ coverage < 75% (fallback threshold) → exit 1 regardless of row coverage."""
    tx_path = tmp_path / "transactions.csv"
    _write_csv(tx_path, [
        {"date": "2026-03-01", "description": "A", "amount": "-74",
         "category": "alimentacao", "tags": "refeicao"},
        {"date": "2026-03-02", "description": "B", "amount": "-26",
         "category": "transporte", "tags": ""},
    ])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
    ])
    assert main() == 1


def test_main_fail_gate3_large_untagged_no_ack(tmp_path, monkeypatch):
    """Unacked untagged despesa > floor → exit 1 (gate #3 fails).

    Uses --config-dir pointing to a temp dir so the fallback floor (R$100)
    applies — this ensures the test is not coupled to the user's real config.
    An untagged R$101 row is above the R$100 fallback floor.
    """
    tx_path = tmp_path / "transactions.csv"
    # R$: tagged=R$9000, untagged=R$101 → 9000/9101≈99% → gate #1 passes.
    # Gate #3: R$101 unacked > R$100 fallback floor → FAIL.
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
        "--config-dir", str(tmp_path),  # no standing-rules.yaml → fallback R$100 floor
    ])
    assert main() == 1


def test_main_pass_exit_0_at_75pct_r(tmp_path, monkeypatch):
    """R$ exactly 75%, rows only 50% — new contract: gate #2 informational → exit 0."""
    tx_path = tmp_path / "transactions.csv"
    _write_csv(tx_path, [
        {"date": "2026-03-01", "description": "A", "amount": "-75",
         "category": "alimentacao", "tags": "refeicao"},
        {"date": "2026-03-02", "description": "B", "amount": "-25",
         "category": "transporte", "tags": ""},
    ])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
    ])
    # Row coverage: 1/2 = 50% — no longer a gate; R$=75% >= 75% → PASS.
    assert main() == 0


def test_main_fail_exit_1_below_75pct(tmp_path, monkeypatch):
    """R$ 74% coverage → exit 1 (gate #1 fails)."""
    tx_path = tmp_path / "transactions.csv"
    _write_csv(tx_path, [
        {"date": "2026-03-01", "description": "A", "amount": "-74",
         "category": "alimentacao", "tags": "refeicao"},
        {"date": "2026-03-02", "description": "B", "amount": "-26",
         "category": "transporte", "tags": ""},
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
    # Fully untagged at R$50 each — gate #1 fails (0% < 75%); gate #3: below floor.
    _write_csv(tx_path, [
        {"date": "2026-03-01", "description": "A", "amount": "-50",
         "category": "alimentacao", "tags": ""},
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
    # Fully untagged: gate #1 fails.
    _write_csv(tx_path, [
        {"date": "2026-03-01", "description": "A", "amount": "-50",
         "category": "alimentacao", "tags": ""},
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
    assert gate_fail_events[0]["gate"]["threshold"] == pytest.approx(0.75)

    audit_mod._reset_cache_for_tests()


def test_gate_pass_event_emitted_on_all_pass(tmp_path, monkeypatch):
    """gate_pass event emitted when all gates pass (gate #2 informational)."""
    import lib.audit as audit_mod
    import json
    audit_mod._reset_cache_for_tests()

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    tx_path = tmp_path / "transactions.csv"
    # R$: 9 tagged at R$100, 1 untagged at R$50 (< floor). R$=900/950=94.7% >= 75%.
    # Row coverage: 9/10 = 90% — informational, not gated.
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


def test_gate_trigger_context_has_gate2_row_coverage(tmp_path, monkeypatch):
    """gate event trigger_context retains gate2_row_coverage as informational field."""
    import lib.audit as audit_mod
    import json
    audit_mod._reset_cache_for_tests()

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    tx_path = tmp_path / "transactions.csv"
    _write_csv(tx_path, [
        {"date": "2026-03-01", "description": "A", "amount": "-75",
         "category": "alimentacao", "tags": "refeicao"},
        {"date": "2026-03-02", "description": "B", "amount": "-25",
         "category": "transporte", "tags": ""},
    ])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "0")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py",
        "--transactions", str(tx_path),
    ])
    main()

    event_files = list(audit_dir.glob("events-*.jsonl"))
    assert event_files
    events = [json.loads(line) for line in event_files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    gate_events = [e for e in events if e.get("event_type") in ("gate_pass", "gate_fail")]
    assert gate_events
    # trigger_context is a top-level event field, not nested inside gate.
    tc = gate_events[0]["trigger_context"]
    assert "gate2_row_coverage" in tc

    audit_mod._reset_cache_for_tests()


# ---------------------------------------------------------------------------
# Threshold provenance (compound cp-sb-bookkeeper-gates-measure-meaning, change 3)
# A config-provided threshold must declare the metric it was decided for, and
# that metric must match the metric the gate applies it to — else exit 2.
# ---------------------------------------------------------------------------

from lib.standing_rules import check_threshold_provenance, ThresholdProvenanceError


def _write_standing_rules(
    config_dir: Path,
    *,
    r_threshold: float = 0.75,
    r_prov_metric: str = "despesas_tagged_brl_pct",
    include_r_prov: bool = True,
    floor: int = 300,
    floor_prov_metric: str = "untagged_despesa_floor_brl",
    include_floor_prov: bool = True,
):
    """Write a minimal valid standing-rules.yaml for gate_coverage provenance tests.

    Satisfies load_standing_rules (_meta + supplier_rules) and load_gates (the
    three required gate sub-sections), then carries (or omits) provenance blocks
    on the two coverage thresholds.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "_meta:",
        "  schema_version: 1",
        '  rule_set_version: "test"',
        "supplier_rules:",
        "  status: active",
        "tag_coverage:",
        "  status: active",
        "  gate:",
        f"    untagged_amount_threshold_brl: {floor}",
    ]
    if include_floor_prov:
        lines += [
            "    untagged_amount_threshold_brl_provenance:",
            f"      metric: {floor_prov_metric}",
            '      decided_on: "2026-06-05"',
        ]
    lines += [
        "gates:",
        "  status: active",
        "  step_01_file_identification:",
        "    user_confirmation_required: true",
        "  step_3d_unmatched_rows:",
        "    enforcement: no_silent_skip",
        "  step_5_5_coverage:",
        f"    threshold: {r_threshold}",
    ]
    if include_r_prov:
        lines += [
            "    threshold_provenance:",
            f"      metric: {r_prov_metric}",
            '      decided_on: "2026-06-05"',
        ]
    (config_dir / "standing-rules.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- pure helper unit tests ---


def test_provenance_match_returns_block():
    parent = {"threshold": 0.75, "threshold_provenance": {"metric": "m1", "decided_on": "2026-06-05"}}
    assert check_threshold_provenance(parent, "threshold", "m1")["metric"] == "m1"


def test_provenance_missing_block_raises():
    with pytest.raises(ThresholdProvenanceError):
        check_threshold_provenance({"threshold": 0.75}, "threshold", "m1")


def test_provenance_metric_mismatch_raises():
    parent = {"threshold": 0.75, "threshold_provenance": {"metric": "other_metric"}}
    with pytest.raises(ThresholdProvenanceError):
        check_threshold_provenance(parent, "threshold", "m1")


def test_provenance_custom_provenance_key():
    parent = {"floor": 300, "floor_prov": {"metric": "m3"}}
    assert check_threshold_provenance(parent, "floor", "m3", provenance_key="floor_prov")["metric"] == "m3"


# --- gate integration: provenance drives the exit code ---


def test_main_provenance_valid_passes(tmp_path, monkeypatch):
    """Valid provenance on both thresholds → gate evaluates normally (exit 0)."""
    cfg = tmp_path / "config"
    _write_standing_rules(cfg)
    tx = tmp_path / "transactions.csv"
    _write_csv(tx, [
        {"date": "2026-04-01", "description": "A", "amount": "-75", "category": "alimentacao", "tags": "x"},
        {"date": "2026-04-02", "description": "B", "amount": "-25", "category": "transporte", "tags": ""},
    ])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py", "--transactions", str(tx), "--config-dir", str(cfg),
    ])
    assert main() == 0


def test_main_provenance_r_metric_mismatch_exits_2(tmp_path, monkeypatch):
    """R$ threshold provenance names a different metric (inheritance) → exit 2."""
    cfg = tmp_path / "config"
    _write_standing_rules(cfg, r_prov_metric="some_other_metric")
    tx = tmp_path / "transactions.csv"
    _write_csv(tx, [{"date": "2026-04-01", "description": "A", "amount": "-75", "category": "alimentacao", "tags": "x"}])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py", "--transactions", str(tx), "--config-dir", str(cfg),
    ])
    assert main() == 2


def test_main_provenance_r_missing_exits_2(tmp_path, monkeypatch):
    """R$ threshold present but no provenance block → exit 2."""
    cfg = tmp_path / "config"
    _write_standing_rules(cfg, include_r_prov=False)
    tx = tmp_path / "transactions.csv"
    _write_csv(tx, [{"date": "2026-04-01", "description": "A", "amount": "-75", "category": "alimentacao", "tags": "x"}])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py", "--transactions", str(tx), "--config-dir", str(cfg),
    ])
    assert main() == 2


def test_main_provenance_floor_metric_mismatch_exits_2(tmp_path, monkeypatch):
    """Untagged-floor provenance names a different metric → exit 2."""
    cfg = tmp_path / "config"
    _write_standing_rules(cfg, floor_prov_metric="some_other_floor")
    tx = tmp_path / "transactions.csv"
    _write_csv(tx, [{"date": "2026-04-01", "description": "A", "amount": "-75", "category": "alimentacao", "tags": "x"}])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py", "--transactions", str(tx), "--config-dir", str(cfg),
    ])
    assert main() == 2


def test_main_provenance_printed_in_output(tmp_path, monkeypatch, capsys):
    """Provenance lines (metric ownership) are printed in the gate output."""
    cfg = tmp_path / "config"
    _write_standing_rules(cfg)
    tx = tmp_path / "transactions.csv"
    _write_csv(tx, [
        {"date": "2026-04-01", "description": "A", "amount": "-75", "category": "alimentacao", "tags": "x"},
        {"date": "2026-04-02", "description": "B", "amount": "-25", "category": "transporte", "tags": ""},
    ])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py", "--transactions", str(tx), "--config-dir", str(cfg),
    ])
    main()
    out = capsys.readouterr().out
    assert "Provenance" in out
    assert "despesas_tagged_brl_pct" in out
    assert "untagged_despesa_floor_brl" in out


def test_main_fallback_path_no_provenance_check(tmp_path, monkeypatch):
    """No standing-rules.yaml (config unreachable) → in-code fallback, NO provenance
    check (the fallback path is not subject to the bar). Untagged below fallback
    floor R$100, R$ above fallback 0.75 → exit 0."""
    tx = tmp_path / "transactions.csv"
    _write_csv(tx, [
        {"date": "2026-04-01", "description": "A", "amount": "-200", "category": "alimentacao", "tags": "x"},
        {"date": "2026-04-02", "description": "B", "amount": "-50", "category": "transporte", "tags": ""},
    ])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_coverage.py", "--transactions", str(tx), "--config-dir", str(tmp_path),
    ])
    assert main() == 0
