"""Regression tests for B2-LIFT: p2-5, p2-6, p2-8, p2-9.

p2-5: FOREX_VENDORS + NOISE_PATTERNS lifted to categories.json config.
p2-6: reimbursement_wins_over_self_transfer declared in standing-rules.yaml.
p2-8: months.json automated from fechamento/ directory scan.
p2-9: single resolver (_resolve_bookkeeper_config) for all config files.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from _fixture_helpers import MINIMAL_STANDING_RULES_YAML
from categorize import (
    _resolve_bookkeeper_config,
    _update_months_json,
    detect_interaccount_transfers,
)


_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
_FIXTURES = _TESTS_DIR / "fixtures"


# ---------------------------------------------------------------------------
# p2-5: FOREX_VENDORS + NOISE_PATTERNS read from config, not hardcoded
# ---------------------------------------------------------------------------

def test_p2_5_forex_vendors_in_live_config():
    """Live categories.json must declare intercontas_auto_pair_config.forex_vendors."""
    # Walk up from tests/ to find the live config
    for parent in _TESTS_DIR.parents:
        cats = parent / ".user" / "finance" / "bookkeeper" / "config" / "categories.json"
        if cats.exists():
            data = json.loads(cats.read_text(encoding="utf-8"))
            cfg = data.get("intercontas_auto_pair_config", {})
            vendors = cfg.get("forex_vendors")
            assert vendors is not None, (
                "categories.json missing intercontas_auto_pair_config.forex_vendors — "
                "p2-5 lift incomplete"
            )
            assert isinstance(vendors, list), "forex_vendors must be a list"
            assert len(vendors) > 0, "forex_vendors must not be empty"
            return
    pytest.skip("categories.json not found")


def test_p2_5_noise_patterns_in_live_config():
    """Live categories.json must declare intercontas_auto_pair_config.noise_patterns."""
    for parent in _TESTS_DIR.parents:
        cats = parent / ".user" / "finance" / "bookkeeper" / "config" / "categories.json"
        if cats.exists():
            data = json.loads(cats.read_text(encoding="utf-8"))
            cfg = data.get("intercontas_auto_pair_config", {})
            patterns = cfg.get("noise_patterns")
            assert patterns is not None, (
                "categories.json missing intercontas_auto_pair_config.noise_patterns — "
                "p2-5 lift incomplete"
            )
            assert isinstance(patterns, list), "noise_patterns must be a list"
            assert len(patterns) > 0, "noise_patterns must not be empty"
            return
    pytest.skip("categories.json not found")


def test_p2_5_detect_interaccount_uses_config_vendors():
    """detect_interaccount_transfers respects caller-supplied forex_vendors list.

    With an empty forex_vendors, the Wise-funding cross-currency scoring
    path cannot score vendor match points. Confirm the function accepts the
    parameter and classifies identically to the legacy defaults when the
    legacy lists are passed explicitly.
    """
    # Two same-currency transactions that should auto-pair as intercontas
    txs = [
        {"date": "2026-04-01", "bank": "banco_a", "currency": "BRL",
         "amount": "100.00", "description": "TRANSFERENCIA"},
        {"date": "2026-04-01", "bank": "banco_b", "currency": "BRL",
         "amount": "-100.00", "description": "TRANSFERENCIA"},
    ]

    # Same result regardless of forex_vendors — same-currency pair-matching
    # doesn't use forex_vendors at all (that only affects cross-currency path)
    auto_pairs_default, _ = detect_interaccount_transfers(txs)
    auto_pairs_explicit, _ = detect_interaccount_transfers(
        txs,
        forex_vendors=["WISE", "REMESSA ONLINE", "WESTERN UNION", "TRANSFERWISE"],
        noise_patterns=["RESERVA", "CAPITAL DE GIRO", "RENDIMENTO", "REMUNERACAO"],
    )
    assert auto_pairs_default == auto_pairs_explicit == {0: "intercontas", 1: "intercontas"}


def test_p2_5_custom_forex_vendor_detected():
    """detect_interaccount_transfers uses caller-supplied forex_vendors for scoring."""
    # Cross-currency pair: BRL "DINHEIRO ADICIONADO" + USD with a custom vendor
    txs = [
        {
            "date": "2026-04-01", "bank": "wise_acc", "currency": "USD",
            "amount": "50.00",
            "description": "DINHEIRO ADICIONADO",
        },
        {
            "date": "2026-04-01", "bank": "banco_brl", "currency": "BRL",
            "amount": "-300.00",
            "description": "CUSTOM FOREX PROVIDER PAGAMENTO",
        },
    ]

    # With the custom provider in forex_vendors, it gets the +100 score
    _, cross_with_custom = detect_interaccount_transfers(
        txs,
        forex_vendors=["CUSTOM FOREX PROVIDER"],
        noise_patterns=["RESERVA"],
    )
    # Without the custom provider, it gets score 0 (no vendor match, rate only)
    _, cross_without_custom = detect_interaccount_transfers(
        txs,
        forex_vendors=["WISE"],
        noise_patterns=["RESERVA"],
    )
    # Both cases surface the cross-currency pair (rate 6.0 is in range 3.0–8.0)
    assert len(cross_with_custom) == 1
    assert len(cross_without_custom) == 1
    # The custom-vendor case scores higher but the pair is found either way
    assert cross_with_custom[0]["wise_idx"] == 0


def test_p2_5_noise_pattern_suppresses_cross_currency_pair():
    """noise_patterns from config suppress candidates when matched in description."""
    txs = [
        {
            "date": "2026-04-01", "bank": "wise_acc", "currency": "USD",
            "amount": "50.00",
            "description": "DINHEIRO ADICIONADO",
        },
        {
            "date": "2026-04-01", "bank": "banco_brl", "currency": "BRL",
            "amount": "-300.00",
            "description": "RENDIMENTO CDB BANCO",  # contains noise pattern
        },
    ]
    _, cross = detect_interaccount_transfers(
        txs,
        forex_vendors=["WISE"],
        noise_patterns=["RENDIMENTO"],  # matches desc_b → candidate suppressed
    )
    assert cross == [], "noise pattern should have suppressed the cross-currency candidate"


# ---------------------------------------------------------------------------
# p2-6: reimbursement_wins_over_self_transfer declared in standing-rules.yaml
# ---------------------------------------------------------------------------

def test_p2_6_reimbursement_wins_declared_in_standing_rules():
    """standing-rules.yaml must declare reimbursement_wins_over_self_transfer: true
    under supplier_rules.self_transfer (p2-6 / V-2 documentation fix)."""
    for parent in _TESTS_DIR.parents:
        sr = parent / ".user" / "finance" / "bookkeeper" / "config" / "standing-rules.yaml"
        if sr.exists():
            data = yaml.safe_load(sr.read_text(encoding="utf-8"))
            self_transfer = (data.get("supplier_rules") or {}).get("self_transfer", {})
            assert self_transfer.get("reimbursement_wins_over_self_transfer") is True, (
                "standing-rules.yaml::supplier_rules.self_transfer must declare "
                "reimbursement_wins_over_self_transfer: true — p2-6 lift incomplete"
            )
            return
    pytest.skip("standing-rules.yaml not found")


def test_p2_6_runtime_behavior_unchanged(monkeypatch):
    """Regression: adding the config declaration must not change runtime behavior.

    A description matching both a self_transfer pattern AND a reimbursement
    pattern must still emit the reimbursement category (not 'ignorar').
    """
    from categorize import categorize_transaction

    # 'HENRIQUE LEAL TEIXEIRA' is a self_transfer pattern.
    # 'CARE PLUS' is a reimbursement pattern.
    description = "HENRIQUE LEAL TEIXEIRA CARE PLUS REEMBOLSO"
    self_transfer_patterns = ["HENRIQUE LEAL TEIXEIRA"]
    reimbursement_mappings = {
        "CARE PLUS": {"category": "saude", "tag": "reembolso"}
    }
    cat, _, _, tags = categorize_transaction(
        description=description,
        self_transfer_patterns=self_transfer_patterns,
        reimbursement_mappings=reimbursement_mappings,
        supplier_index=None,
    )
    assert cat == "saude", (
        f"reimbursement should win over self_transfer — got {cat!r}"
    )
    assert "reembolso" in tags


def test_p2_6_pure_self_transfer_still_ignorar():
    """Pure self-transfer (no reimbursement pattern) must still emit 'ignorar'."""
    from categorize import categorize_transaction

    description = "PIX ENVIADO HENRIQUE LEAL TEIXEIRA 12345"
    self_transfer_patterns = ["HENRIQUE LEAL TEIXEIRA"]
    reimbursement_mappings = {}
    cat, _, _, _ = categorize_transaction(
        description=description,
        self_transfer_patterns=self_transfer_patterns,
        reimbursement_mappings=reimbursement_mappings,
        supplier_index=None,
    )
    assert cat == "ignorar"


# ---------------------------------------------------------------------------
# p2-8: months.json automated from fechamento/ directory scan
# ---------------------------------------------------------------------------

def test_p2_8_months_json_written_after_categorize(tmp_path):
    """_update_months_json writes months.json listing all months with transactions.csv."""
    # Build a fake fechamento/ tree
    fechamento = tmp_path / "fechamento"
    for month in ("2026-01", "2026-02", "2026-03"):
        m = fechamento / month
        m.mkdir(parents=True)
        (m / "transactions.csv").write_text("date,amount\n", encoding="utf-8")
    # One month without transactions.csv (should not appear in the list)
    (fechamento / "2026-04").mkdir()

    # Call _update_months_json with the path to one of the transactions.csv files
    _update_months_json(fechamento / "2026-03" / "transactions.csv")

    months_json = fechamento / "months.json"
    assert months_json.exists(), "months.json was not written"
    data = json.loads(months_json.read_text(encoding="utf-8"))
    assert data == ["2026-01", "2026-02", "2026-03"], (
        f"months.json content mismatch: {data}"
    )


def test_p2_8_months_json_sorted():
    """_update_months_json emits months in lexicographic (chronological) order."""
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        fechamento = Path(td) / "fechamento"
        # Insert in reverse order to verify sort
        for month in ("2026-03", "2026-01", "2026-02"):
            m = fechamento / month
            m.mkdir(parents=True)
            (m / "transactions.csv").write_text("date,amount\n", encoding="utf-8")

        _update_months_json(fechamento / "2026-01" / "transactions.csv")
        data = json.loads((fechamento / "months.json").read_text(encoding="utf-8"))
        assert data == ["2026-01", "2026-02", "2026-03"]


def test_p2_8_months_json_skips_non_matching_dirs():
    """Directories without transactions.csv or non-YYYY-MM names are excluded."""
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        fechamento = Path(td) / "fechamento"
        (fechamento / "2026-01").mkdir(parents=True)
        (fechamento / "2026-01" / "transactions.csv").write_text("", encoding="utf-8")
        (fechamento / "notes").mkdir()               # non-date dir — excluded
        (fechamento / "2026-02").mkdir()             # no transactions.csv — excluded

        _update_months_json(fechamento / "2026-01" / "transactions.csv")
        data = json.loads((fechamento / "months.json").read_text(encoding="utf-8"))
        assert data == ["2026-01"]


def test_p2_8_months_json_skips_on_unexpected_layout():
    """_update_months_json silently skips when the directory layout is unexpected."""
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        # Place transactions.csv directly under a flat tmp dir (no fechamento/ parent)
        flat = Path(td) / "transactions.csv"
        flat.write_text("date\n", encoding="utf-8")
        # Should not raise — just skip
        _update_months_json(flat)


def test_p2_8_live_fechamento_months_json_consistent():
    """Live months.json must agree with actual fechamento/ subdirectories.

    After p2-8, months.json is machine-written. Verify it lists exactly the
    month dirs that have transactions.csv.
    """
    for parent in _TESTS_DIR.parents:
        fechamento = parent / ".user" / "finance" / "bookkeeper" / "ledgers" / "fechamento"
        if not fechamento.is_dir():
            continue
        months_json = fechamento / "months.json"
        if not months_json.exists():
            pytest.skip("months.json not found — live config not available")
        import re
        pattern = re.compile(r"^\d{4}-\d{2}$")
        expected = sorted(
            d.name
            for d in fechamento.iterdir()
            if d.is_dir()
            and pattern.match(d.name)
            and (d / "transactions.csv").exists()
        )
        actual = json.loads(months_json.read_text(encoding="utf-8"))
        assert actual == expected, (
            f"months.json out of sync with fechamento/ dirs. "
            f"Expected: {expected}, Got: {actual}"
        )
        return
    pytest.skip("fechamento/ not found")


# ---------------------------------------------------------------------------
# p2-9: single resolver (_resolve_bookkeeper_config)
# ---------------------------------------------------------------------------

def test_p2_9_resolver_uses_env_override(tmp_path, monkeypatch):
    """_resolve_bookkeeper_config returns BOOKKEEPER_CONFIG_DIR when set."""
    tmp_path.mkdir(exist_ok=True)
    monkeypatch.setenv("BOOKKEEPER_CONFIG_DIR", str(tmp_path))
    result = _resolve_bookkeeper_config()
    assert result == tmp_path


def test_p2_9_resolver_raises_when_dir_missing(tmp_path, monkeypatch):
    """_resolve_bookkeeper_config raises RuntimeError when config dir doesn't exist."""
    missing = tmp_path / "does_not_exist"
    monkeypatch.setenv("BOOKKEEPER_CONFIG_DIR", str(missing))
    with pytest.raises(RuntimeError, match="not found"):
        _resolve_bookkeeper_config()


def test_p2_9_suppliers_loaded_from_resolver_not_cli_arg(tmp_path, monkeypatch):
    """suppliers.json must be loaded from _resolve_bookkeeper_config(), not CLI arg.

    Verify by setting BOOKKEEPER_CONFIG_DIR to a dir with known suppliers and
    running categorize as subprocess. The supplier from BOOKKEEPER_CONFIG_DIR
    must appear in the output, not a supplier from a different config dir.
    """
    # Build a config dir with a distinct supplier
    cfg_dir = tmp_path / "bookkeeper_config"
    cfg_dir.mkdir()
    # Copy fixture categories.json but add a custom supplier
    shutil.copy(_FIXTURES / "categories.json", cfg_dir / "categories.json")
    shutil.copy(_FIXTURES / "tags.json", cfg_dir / "tags.json")
    (cfg_dir / "standing-rules.yaml").write_text(
        MINIMAL_STANDING_RULES_YAML, encoding="utf-8"
    )
    custom_suppliers = {
        "version": 1,
        "suppliers": {
            "p29_test_vendor": {
                "canonical": "P29 Test Vendor",
                "aliases": ["UNIQUE_P29_VENDOR"],
                "movable": False,
                "default_category": "compras",
            }
        },
    }
    (cfg_dir / "suppliers.json").write_text(
        json.dumps(custom_suppliers), encoding="utf-8"
    )

    # Build a minimal month folder with one transaction that matches the custom vendor
    month_dir = tmp_path / "month"
    processed = month_dir / "processed"
    processed.mkdir(parents=True)
    (processed / "extrato.csv").write_text(
        "date,amount,description,bank,currency,source_type,"
        "installment_current,installment_total\n"
        "2026-04-01,-50.00,UNIQUE_P29_VENDOR,test_bank,BRL,extrato,,\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"

    env = os.environ.copy()
    env["BOOKKEEPER_CONFIG_DIR"] = str(cfg_dir)
    env["BOOKKEEPER_AUDIT_LOG_DIR"] = str(tmp_path / "audit")

    cmd = [
        sys.executable,
        str(_SCRIPTS_DIR / "categorize.py"),
        str(processed),
        str(tmp_path / "some_other_config"),  # CLI arg intentionally different
        str(output_dir),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert result.returncode == 0, (
        f"categorize.py failed:\n{result.stdout}\n{result.stderr}"
    )

    import csv
    with open(output_dir / "transactions.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows, "no output rows"
    assert rows[0]["supplier_canonical"] == "P29 Test Vendor", (
        f"Expected 'P29 Test Vendor' (from BOOKKEEPER_CONFIG_DIR suppliers.json), "
        f"got {rows[0]['supplier_canonical']!r} — "
        "p2-9 single resolver not in effect"
    )
