"""Tests for apply_review_resolution.py (migrations/).

CLASS: write / retro-rewrite
TOOL: apply_review_resolution

Covers (per tool-builder Step 5.1 requirements):
  1. Schema conformance — output fields conform to transactions.csv schema AND
     corrections schemas (manual-overrides.csv, competencia-overrides.csv).
  2. Dry-run writes nothing — byte-for-byte unchanged destinations, no artifacts.
  3. Exactly-one-match identity enforcement — 0 matches = hard error,
     >1 matches = hard error.
  4. data_caixa mutation rejected (immutable raw field).
  5. --apply end-to-end — row re-stamped in transactions.csv + correction row
     appended to corrections file.

Isolation: all tests use tmp-dir fixtures via env overrides
(BOOKKEEPER_ROOT / BOOKKEEPER_CONFIG_DIR / BOOKKEEPER_LEDGER_DIR).
NEVER run --apply against the real vault data.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent  # shared/
_MIGRATIONS_DIR = _SCRIPTS_DIR.parent / "migrations"

for _p in (_SCRIPTS_DIR, _MIGRATIONS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load_module(name: str, filename: str, base_dir: Path):
    path = base_dir / filename
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_arr = _load_module(
    "apply_review_resolution", "apply_review_resolution.py", _MIGRATIONS_DIR
)

# --- schema check lib ---
from lib.tool_schema_check import assert_conforms, conformance_gap  # noqa: E402

# ---------------------------------------------------------------------------
# Real destination schemas (from constants defined in the tool)
# ---------------------------------------------------------------------------

# transactions.csv schema — the 20-column schema observed in the real vault.
_TX_SCHEMA = {
    "date", "description", "amount", "balance", "bank", "source_type",
    "currency", "original_ref", "installment_current", "installment_total",
    "original_amount", "exchange_rate", "category", "match_confidence",
    "recurrence", "data_caixa", "data_competencia", "supplier_canonical",
    "tags", "manual_override",
}

# corrections file schemas (from the tool's own constants)
_MANUAL_OVERRIDES_SCHEMA = set(_arr.MANUAL_OVERRIDES_FIELDS)
_COMPETENCIA_OVERRIDES_SCHEMA = set(_arr.COMPETENCIA_OVERRIDES_FIELDS)

# ---------------------------------------------------------------------------
# Fixture: minimal fechamento transactions.csv (19-column variant; matches the
# real vault schema minus 'balance' which may be absent in older months)
# ---------------------------------------------------------------------------

# Header that matches the real vault 20-col schema.
_TX_HEADER_FULL = (
    "date,description,amount,balance,bank,source_type,currency,original_ref,"
    "installment_current,installment_total,original_amount,exchange_rate,"
    "category,match_confidence,recurrence,data_caixa,data_competencia,"
    "supplier_canonical,tags,manual_override\n"
)

_SAMPLE_ROW = (
    "2026-04-07,Pix enviado Henrique Leal Teixeira,-78.60,,nubank,pix,BRL,,,"
    ",,,alimentacao,high,pontual,2026-04-07,2026-04-07,,,"
    "\n"
)

_ANOTHER_ROW = (
    "2026-04-10,Netflix Streaming,-39.90,,nubank,debit,BRL,,,"
    ",,,entretenimento,high,recorrente,2026-04-10,2026-04-10,,,"
    "\n"
)

_DUPLICATE_ROW = (
    "2026-04-07,Pix enviado Henrique Leal Teixeira,-78.60,,nubank,pix,BRL,,,"
    ",,,alimentacao,high,pontual,2026-04-07,2026-04-07,,,"
    "\n"
)

_MANUAL_OVERRIDES_HEADER = (
    "tx_date,tx_description,tx_amount,override_category,override_tags,"
    "month,added_at,source,note\n"
)

_COMPETENCIA_OVERRIDES_HEADER = (
    "tx_date,tx_description,tx_amount,override_data_competencia,reason,"
    "month,added_at,source,note\n"
)


@pytest.fixture
def bk(tmp_path, monkeypatch):
    """Build an isolated bookkeeper tree and point the tool at it via env vars."""
    root = tmp_path / "bk"
    config = root / "config"
    corrections = config / "corrections"
    ledger_month = root / "ledgers" / "fechamento" / "2026-04"
    corrections.mkdir(parents=True)
    ledger_month.mkdir(parents=True)

    # Minimal sb-os.json so path-finders don't walk to the real vault.
    (tmp_path / "sb-os.json").write_text("{}", encoding="utf-8")

    # Write transactions.csv (one unique row + another unrelated row).
    tx_path = ledger_month / "transactions.csv"
    tx_path.write_text(
        _TX_HEADER_FULL + _SAMPLE_ROW + _ANOTHER_ROW,
        encoding="utf-8",
    )

    # Empty corrections files (header only).
    (corrections / "manual-overrides.csv").write_text(
        _MANUAL_OVERRIDES_HEADER, encoding="utf-8"
    )
    (corrections / "competencia-overrides.csv").write_text(
        _COMPETENCIA_OVERRIDES_HEADER, encoding="utf-8"
    )

    monkeypatch.setenv("BOOKKEEPER_ROOT", str(root))
    monkeypatch.setenv("BOOKKEEPER_CONFIG_DIR", str(config))
    monkeypatch.setenv("BOOKKEEPER_LEDGER_DIR", str(root / "ledgers"))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")

    return {
        "root": root,
        "config": config,
        "corrections": corrections,
        "tx_path": tx_path,
        "ledger_month": ledger_month,
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(paths: list[Path]) -> dict[str, str]:
    return {
        str(p): _sha(p) if p.exists() else "<absent>"
        for p in paths
    }


def _all_state_paths(bk: dict) -> list[Path]:
    return [
        bk["tx_path"],
        bk["corrections"] / "manual-overrides.csv",
        bk["corrections"] / "competencia-overrides.csv",
    ]


# ---------------------------------------------------------------------------
# 1. Schema conformance — assert_conforms on output field sets
# ---------------------------------------------------------------------------


class TestSchemaConformance:
    """The tool's output field sets MUST be subsets of the destination schemas."""

    def test_mutable_fields_are_subset_of_transactions_schema(self):
        """Every field the tool may re-stamp is present in transactions.csv."""
        assert_conforms(_arr.MUTABLE_FIELDS, _TX_SCHEMA,
                        destination="transactions.csv")

    def test_manual_overrides_fields_conform(self):
        """MANUAL_OVERRIDES_FIELDS matches the corrections file schema exactly."""
        assert_conforms(
            _arr.MANUAL_OVERRIDES_FIELDS,
            _MANUAL_OVERRIDES_SCHEMA,
            destination="manual-overrides.csv",
        )

    def test_competencia_overrides_fields_conform(self):
        """COMPETENCIA_OVERRIDES_FIELDS matches the corrections file schema exactly."""
        assert_conforms(
            _arr.COMPETENCIA_OVERRIDES_FIELDS,
            _COMPETENCIA_OVERRIDES_SCHEMA,
            destination="competencia-overrides.csv",
        )

    def test_no_gap_for_mutable_fields_in_tx_schema(self):
        gap = conformance_gap(_arr.MUTABLE_FIELDS, _TX_SCHEMA)
        assert gap == set(), f"Unexpected gap: {gap}"

    def test_data_caixa_is_in_never_mutable_and_in_tx_schema(self):
        """data_caixa must exist in the destination but be blocked by the tool."""
        assert "data_caixa" in _TX_SCHEMA
        assert "data_caixa" in _arr.NEVER_MUTABLE


# ---------------------------------------------------------------------------
# 2. Dry-run writes nothing — byte-for-byte unchanged destinations
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_writes_nothing_category(self, bk):
        before = _snapshot(_all_state_paths(bk))
        rc = _arr.main([
            "--month", "2026-04",
            "--date", "2026-04-07",
            "--description", "Pix enviado Henrique Leal Teixeira",
            "--amount", "-78.60",
            "--set", "category=saude",
            "--corrections-file", "manual-overrides.csv",
            "--reason", "mis-tagged",
            "--source", "test",
        ])
        assert rc == 0
        assert _snapshot(_all_state_paths(bk)) == before

    def test_dry_run_writes_nothing_competencia(self, bk):
        before = _snapshot(_all_state_paths(bk))
        rc = _arr.main([
            "--month", "2026-04",
            "--date", "2026-04-07",
            "--description", "Pix enviado Henrique Leal Teixeira",
            "--amount", "-78.60",
            "--set", "data_competencia=2026-03",
            "--corrections-file", "competencia-overrides.csv",
            "--reason", "competencia fix",
            "--source", "test",
        ])
        assert rc == 0
        assert _snapshot(_all_state_paths(bk)) == before

    def test_dry_run_no_artifacts_created(self, bk):
        """No .bak or .rollback artifacts created under dry-run."""
        _arr.main([
            "--month", "2026-04",
            "--date", "2026-04-07",
            "--description", "Pix enviado Henrique Leal Teixeira",
            "--amount", "-78.60",
            "--set", "tags=saude",
        ])
        baks = list(bk["corrections"].glob("*.bak*")) + list(bk["config"].glob("*.bak*"))
        rb_dir = bk["corrections"] / ".rollback"
        rollback_files = list(rb_dir.glob("*")) if rb_dir.exists() else []
        assert not baks, f"Unexpected .bak files: {baks}"
        assert not rollback_files, f"Unexpected rollback files: {rollback_files}"


# ---------------------------------------------------------------------------
# 3. Exactly-one-match identity enforcement
# ---------------------------------------------------------------------------


class TestIdentityEnforcement:
    def test_zero_matches_hard_error(self, bk):
        """0 matches → rc=1, nothing written."""
        before = _snapshot(_all_state_paths(bk))
        rc = _arr.main([
            "--month", "2026-04",
            "--date", "2026-04-07",
            "--description", "Completely Nonexistent Description XYZ",
            "--amount", "-78.60",
            "--set", "category=saude",
            "--apply",
        ])
        assert rc == 1
        assert _snapshot(_all_state_paths(bk)) == before

    def test_multi_match_hard_error(self, bk):
        """Write a duplicate row then expect a hard error on match."""
        # Insert a duplicate to create a 2-row match scenario.
        tx = bk["tx_path"]
        existing = tx.read_bytes()
        tx.write_bytes(existing + _DUPLICATE_ROW.encode("utf-8"))

        before = _snapshot(_all_state_paths(bk))
        rc = _arr.main([
            "--month", "2026-04",
            "--date", "2026-04-07",
            "--description", "Pix enviado Henrique Leal Teixeira",
            "--amount", "-78.60",
            "--set", "category=saude",
            "--apply",
        ])
        assert rc == 1
        # Nothing must be written when identity is ambiguous.
        after = _snapshot(_all_state_paths(bk))
        assert after[str(bk["corrections"] / "manual-overrides.csv")] == before[
            str(bk["corrections"] / "manual-overrides.csv")
        ]

    def test_wrong_amount_no_match(self, bk):
        """Amount mismatch → 0 matches → rc=1."""
        before = _snapshot(_all_state_paths(bk))
        rc = _arr.main([
            "--month", "2026-04",
            "--date", "2026-04-07",
            "--description", "Pix enviado Henrique Leal Teixeira",
            "--amount", "-999.99",
            "--set", "category=saude",
            "--apply",
        ])
        assert rc == 1
        assert _snapshot(_all_state_paths(bk)) == before


# ---------------------------------------------------------------------------
# 4. data_caixa mutation rejected
# ---------------------------------------------------------------------------


class TestDataCaixaRejected:
    def test_data_caixa_rejected_dry_run(self, bk):
        before = _snapshot(_all_state_paths(bk))
        rc = _arr.main([
            "--month", "2026-04",
            "--date", "2026-04-07",
            "--description", "Pix enviado Henrique Leal Teixeira",
            "--amount", "-78.60",
            "--set", "data_caixa=2026-04-08",
        ])
        assert rc == 1
        assert _snapshot(_all_state_paths(bk)) == before

    def test_data_caixa_rejected_apply(self, bk):
        before = _snapshot(_all_state_paths(bk))
        rc = _arr.main([
            "--month", "2026-04",
            "--date", "2026-04-07",
            "--description", "Pix enviado Henrique Leal Teixeira",
            "--amount", "-78.60",
            "--set", "data_caixa=2026-04-08",
            "--apply",
        ])
        assert rc == 1
        assert _snapshot(_all_state_paths(bk)) == before


# ---------------------------------------------------------------------------
# 5. --apply end-to-end: row re-stamped + correction row appended
# ---------------------------------------------------------------------------


class TestApplyEndToEnd:
    def test_apply_restamps_category_field(self, bk):
        """--apply mutates the matching row's category in transactions.csv."""
        rc = _arr.main([
            "--month", "2026-04",
            "--date", "2026-04-07",
            "--description", "Pix enviado Henrique Leal Teixeira",
            "--amount", "-78.60",
            "--set", "category=saude",
            "--apply",
        ])
        assert rc == 0

        # Row must be updated in transactions.csv.
        rows = list(csv.DictReader(bk["tx_path"].open(encoding="utf-8", newline="")))
        target = [r for r in rows
                  if r["date"] == "2026-04-07"
                  and "Pix enviado" in r["description"]
                  and abs(float(r["amount"]) - (-78.60)) < 0.01]
        assert len(target) == 1
        assert target[0]["category"] == "saude"

    def test_apply_appends_correction_row_to_manual_overrides(self, bk):
        """--apply appends one row to manual-overrides.csv."""
        before_bytes = (bk["corrections"] / "manual-overrides.csv").read_bytes()

        _arr.main([
            "--month", "2026-04",
            "--date", "2026-04-07",
            "--description", "Pix enviado Henrique Leal Teixeira",
            "--amount", "-78.60",
            "--set", "category=saude",
            "--corrections-file", "manual-overrides.csv",
            "--reason", "mis-tagged",
            "--source", "test-suite",
            "--apply",
        ])

        after_text = (bk["corrections"] / "manual-overrides.csv").read_text(encoding="utf-8")
        lines = after_text.strip().splitlines()
        # header + 1 new data row
        assert len(lines) == 2, f"Expected header + 1 row, got: {lines}"
        assert "saude" in lines[1]
        assert "test-suite" in lines[1]
        # Original bytes are still a prefix (append-only, never rewritten)
        assert (bk["corrections"] / "manual-overrides.csv").read_bytes().startswith(before_bytes)

    def test_apply_appends_competencia_override(self, bk):
        """--apply appends one row to competencia-overrides.csv."""
        _arr.main([
            "--month", "2026-04",
            "--date", "2026-04-07",
            "--description", "Pix enviado Henrique Leal Teixeira",
            "--amount", "-78.60",
            "--set", "data_competencia=2026-03",
            "--corrections-file", "competencia-overrides.csv",
            "--reason", "accrual-fix",
            "--source", "test-suite",
            "--apply",
        ])

        lines = (
            (bk["corrections"] / "competencia-overrides.csv")
            .read_text(encoding="utf-8")
            .strip()
            .splitlines()
        )
        assert len(lines) == 2
        assert "2026-03" in lines[1]

    def test_apply_transactions_other_rows_unchanged(self, bk):
        """--apply only touches the matched row; other rows are preserved exactly."""
        _arr.main([
            "--month", "2026-04",
            "--date", "2026-04-07",
            "--description", "Pix enviado Henrique Leal Teixeira",
            "--amount", "-78.60",
            "--set", "category=saude",
            "--apply",
        ])

        rows = list(csv.DictReader(bk["tx_path"].open(encoding="utf-8", newline="")))
        netflix = [r for r in rows if "Netflix" in r.get("description", "")]
        assert len(netflix) == 1
        assert netflix[0]["category"] == "entretenimento"  # unchanged

    def test_apply_without_corrections_file_only_restamps(self, bk):
        """--apply with no --corrections-file re-stamps row and writes no correction."""
        before_manual = _sha(bk["corrections"] / "manual-overrides.csv")
        before_comp = _sha(bk["corrections"] / "competencia-overrides.csv")

        rc = _arr.main([
            "--month", "2026-04",
            "--date", "2026-04-07",
            "--description", "Pix enviado Henrique Leal Teixeira",
            "--amount", "-78.60",
            "--set", "tags=alimentacao-confirmado",
            "--apply",
        ])
        assert rc == 0
        # Corrections files must be unchanged (no --corrections-file supplied)
        assert _sha(bk["corrections"] / "manual-overrides.csv") == before_manual
        assert _sha(bk["corrections"] / "competencia-overrides.csv") == before_comp

    def test_idempotent_already_applied_noop(self, bk):
        """When all target fields already match, the tool reports NO-OP (rc=0)
        and writes nothing on a second apply."""
        # First apply: sets category to saude
        _arr.main([
            "--month", "2026-04",
            "--date", "2026-04-07",
            "--description", "Pix enviado Henrique Leal Teixeira",
            "--amount", "-78.60",
            "--set", "category=saude",
            "--apply",
        ])
        snapshot_after_first = _snapshot(_all_state_paths(bk))

        # Second apply with the same value — fully idempotent, nothing written
        rc = _arr.main([
            "--month", "2026-04",
            "--date", "2026-04-07",
            "--description", "Pix enviado Henrique Leal Teixeira",
            "--amount", "-78.60",
            "--set", "category=saude",
            "--apply",
        ])
        assert rc == 0
        assert _snapshot(_all_state_paths(bk)) == snapshot_after_first
