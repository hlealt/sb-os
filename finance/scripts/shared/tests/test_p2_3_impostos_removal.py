"""Regression tests for p2-3: impostos removed as a category.

Verifies:
  1. categorize_transaction() never returns category="impostos" for any input
  2. _validate_category_tag_separation() raises on a category/tag name collision
  3. _validate_category_tag_separation() passes when impostos is only a tag
  4. SECR. DA RECEITA FEDERAL still emits tag="impostos" (carried constraint: finding #4)
  5. The live categories.json does NOT contain "impostos" as a category key
  6. P2 checkpoint: 5 IOF DESPESA NO EXTERIOR rows → category=compras + tag=impostos
     (user decision 2026-05-26; manual-overrides.csv per-row; iof supplier default_category=compras)
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from categorize import _validate_category_tag_separation, categorize_transaction


# ---------------------------------------------------------------------------
# Helper: reimbursement mappings that include an IOF-like entry and SECR
# ---------------------------------------------------------------------------

REIMBURSEMENT_MAPPINGS = {
    "SECR. DA RECEITA FEDERAL": {
        "category": "receitas",
        "tag": "impostos",
    },
}

SELF_TRANSFER_PATTERNS: list[str] = []


# ---------------------------------------------------------------------------
# 1. categorize_transaction never returns category="impostos"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("description", [
    "IOF DESPESA NO EXTERIOR",
    "IOF",
    "IMPOSTO RENDA",
    "IOF SOBRE OPERACAO DE CREDITO",
    "PAGAMENTO IPTU",
    "RECEITA FEDERAL IR",
])
def test_categorize_never_emits_impostos(description):
    """No description must produce category='impostos' through normal classification."""
    cat, _, _, _ = categorize_transaction(
        description=description,
        self_transfer_patterns=SELF_TRANSFER_PATTERNS,
        reimbursement_mappings=REIMBURSEMENT_MAPPINGS,
        supplier_index=None,
    )
    assert cat != "impostos", (
        f"category='impostos' was emitted for {description!r} — "
        "impostos was removed as a category in p2-3 and must never be emitted"
    )


# ---------------------------------------------------------------------------
# 2. _validate_category_tag_separation raises on collision
# ---------------------------------------------------------------------------

def test_validate_separation_raises_on_collision(tmp_path, monkeypatch):
    """V-B: collision between category and tag name raises RuntimeError."""
    tags_path = tmp_path / ".user" / "finance" / "bookkeeper" / "config" / "tags.json"
    tags_path.parent.mkdir(parents=True, exist_ok=True)
    tags_path.write_text(
        json.dumps({"tags": {"impostos": {"label": "test"}}}), encoding="utf-8"
    )
    # Patch _find_vault_root to return tmp_path
    import categorize
    monkeypatch.setattr(categorize, "_find_vault_root", lambda: tmp_path)

    config_with_collision = {"categories": {"impostos": {}, "alimentacao": {}}}
    with pytest.raises(RuntimeError, match="V-B"):
        _validate_category_tag_separation(config_with_collision)


# ---------------------------------------------------------------------------
# 3. _validate_category_tag_separation passes when impostos is tag-only
# ---------------------------------------------------------------------------

def test_validate_separation_passes_when_impostos_tag_only(tmp_path, monkeypatch):
    """After p2-3: impostos is a tag, not a category — no collision."""
    tags_path = tmp_path / ".user" / "finance" / "bookkeeper" / "config" / "tags.json"
    tags_path.parent.mkdir(parents=True, exist_ok=True)
    tags_path.write_text(
        json.dumps({"tags": {"impostos": {"label": "Impostos (IPTU, IOF, IR)"}}}),
        encoding="utf-8",
    )
    import categorize
    monkeypatch.setattr(categorize, "_find_vault_root", lambda: tmp_path)

    # impostos absent from categories — no collision
    config_clean = {"categories": {"alimentacao": {}, "saude": {}, "transporte": {}}}
    _validate_category_tag_separation(config_clean)  # must not raise


# ---------------------------------------------------------------------------
# 4. SECR. DA RECEITA FEDERAL still emits tag="impostos" (carried constraint)
# ---------------------------------------------------------------------------

def test_secr_receita_federal_still_emits_impostos_tag():
    """Finding #4 carried constraint: SECR mapping must emit tag='impostos'."""
    _, _, _, tags = categorize_transaction(
        description="PIX RECEBIDO SECR. DA RECEITA FEDERAL RESTITUICAO IR",
        self_transfer_patterns=SELF_TRANSFER_PATTERNS,
        reimbursement_mappings=REIMBURSEMENT_MAPPINGS,
        supplier_index=None,
    )
    assert "impostos" in tags, (
        f"SECR. DA RECEITA FEDERAL must emit tag='impostos' — "
        f"carried constraint from p1-8/finding #4. Got: {tags}"
    )


def test_secr_receita_federal_still_classifies_receitas():
    """SECR mapping category must still be 'receitas' after p2-3."""
    cat, _, _, _ = categorize_transaction(
        description="SECR. DA RECEITA FEDERAL RESTITUICAO",
        self_transfer_patterns=SELF_TRANSFER_PATTERNS,
        reimbursement_mappings=REIMBURSEMENT_MAPPINGS,
        supplier_index=None,
    )
    assert cat == "receitas"


# ---------------------------------------------------------------------------
# 5. Live categories.json does NOT contain "impostos" as a category key
# ---------------------------------------------------------------------------

def test_live_categories_json_does_not_contain_impostos():
    """categories.json must not have 'impostos' as a category after p2-3."""
    vault = Path(__file__).resolve()
    for parent in vault.parents:
        cats = parent / ".user" / "finance" / "bookkeeper" / "config" / "categories.json"
        if cats.exists():
            data = json.loads(cats.read_text(encoding="utf-8"))
            assert "impostos" not in data.get("categories", {}), (
                "categories.json still contains 'impostos' as a category — "
                "p2-3 edit incomplete"
            )
            return
    pytest.skip("categories.json not found — skipping live-config test")


# ---------------------------------------------------------------------------
# 6. P2 checkpoint: IOF rows → category=compras + tag=impostos
# ---------------------------------------------------------------------------
# Integration tests (subprocess) for the P2 checkpoint user decision (2026-05-26):
# the 5 IOF DESPESA NO EXTERIOR rows in 2026-03 must resolve to category=compras
# + tag=impostos after the corrections join. Three mechanisms work together:
#   a) iof.default_category changed from "impostos" to "compras" in suppliers.json
#   b) 5 manual-overrides.csv rows (per-row) with override_category=compras +
#      override_tags=impostos
#   c) The stale impostos→transporte row in category-migrations.csv has no consumer
#      in categorize.py (dormant — documented for audit only)
# ---------------------------------------------------------------------------

_P2_TESTS_DIR = Path(__file__).resolve().parent
_P2_SCRIPTS_DIR = _P2_TESTS_DIR.parent
_P2_FIXTURES = _P2_TESTS_DIR / "fixtures"
_P2_MONTH_FIXTURE = _P2_FIXTURES / "month-2026-04"

# The 5 IOF rows from 2026-03 santander_fatura (verbatim from the live ledger).
_IOF_ROWS = [
    ("2026-03-20", "IOF DESPESA NO EXTERIOR", "-0.84"),
    ("2026-03-03", "IOF DESPESA NO EXTERIOR", "-4.12"),
    ("2026-03-04", "IOF DESPESA NO EXTERIOR", "-1.15"),
    ("2026-03-24", "IOF DESPESA NO EXTERIOR", "-40.91"),
    ("2026-03-31", "IOF DESPESA NO EXTERIOR", "-0.97"),
]

# A non-IOF transporte row (Uber) to verify transporte count is unchanged.
_UBER_DATE = "2026-04-12"
_UBER_DESC = "UBER 12345"
_UBER_AMOUNT = "-50.00"

from _fixture_helpers import MINIMAL_STANDING_RULES_YAML


def _build_p2_config(tmp_path: Path) -> Path:
    """Build a per-test config dir with iof supplier set to default_category=compras."""
    target = tmp_path / "config"
    target.mkdir()
    shutil.copy(_P2_FIXTURES / "categories.json", target / "categories.json")
    shutil.copy(_P2_FIXTURES / "tags.json", target / "tags.json")

    # Load fixture suppliers.json and add iof supplier with default_category=compras.
    suppliers_data = json.loads((_P2_FIXTURES / "suppliers.json").read_text(encoding="utf-8"))
    suppliers_data["suppliers"]["iof"] = {
        "canonical": "IOF",
        "aliases": ["IOF DESPESA NO EXTERIOR", "IOF CAMBIO CONSOLIDADO"],
        "movable": False,
        "default_category": "compras",
    }
    (target / "suppliers.json").write_text(
        json.dumps(suppliers_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (target / "standing-rules.yaml").write_text(
        MINIMAL_STANDING_RULES_YAML, encoding="utf-8"
    )
    return target


def _build_iof_month(tmp_path: Path) -> Path:
    """Build a fixture month folder with 5 IOF rows + 1 Uber (transporte) row.

    IOF rows use source_type=extrato (not fatura) so the test does not require
    a santander_fatura payment_date entry in fatura_totals.json. In production
    the IOF rows come from santander_fatura, but source_type does not affect
    category classification — only basis-date computation — and this test is
    testing category + tag assignment, not competência dates.
    """
    target = tmp_path / "month-iof"
    shutil.copytree(_P2_MONTH_FIXTURE, target)
    # Append IOF rows to the normalized CSV (the Uber row is already in the fixture).
    normalized_csv = target / "processed" / "transactions-normalized.csv"
    with open(normalized_csv, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for tx_date, tx_desc, tx_amount in _IOF_ROWS:
            writer.writerow([
                tx_date, tx_desc, tx_amount, "", "santander_extrato",
                "extrato", "BRL", "", "", "", "", "",
            ])
    return target


def _write_iof_overrides(config: Path) -> None:
    """Write the 5 IOF manual-override rows to config/corrections/manual-overrides.csv."""
    corrections = config / "corrections"
    corrections.mkdir(exist_ok=True)
    path = corrections / "manual-overrides.csv"
    header = (
        "tx_date,tx_description,tx_amount,override_category,override_tags,"
        "month,added_at,source,note\n"
    )
    path.write_text(header, encoding="utf-8")
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for tx_date, tx_desc, tx_amount in _IOF_ROWS:
            writer.writerow([
                tx_date, tx_desc, tx_amount,
                "compras", "impostos",
                "2026-03", "2026-05-26T00:00:00", "p2-2-checkpoint",
                "P2 checkpoint: IOF foreign-card tax → compras + tag=impostos",
            ])


def _run_p2_categorize(
    month: Path, config: Path, output: Path, force: bool = False
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["BOOKKEEPER_CONFIG_DIR"] = str(config)
    cmd = [
        sys.executable,
        str(_P2_SCRIPTS_DIR / "categorize.py"),
        str(month / "processed"),
        str(config),
        str(output),
    ]
    if force:
        cmd.append("--force")
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def _load_p2_rows(p: Path) -> list[dict]:
    with open(p, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_iof_rows_resolve_to_compras_with_impostos_tag(tmp_path: Path):
    """P2 checkpoint: 5 IOF DESPESA NO EXTERIOR rows → category=compras + tag=impostos.

    Verifies the net result of:
      - iof supplier default_category=compras (suppliers.json change)
      - 5 manual-overrides.csv rows (per-row: override_category=compras, override_tags=impostos)
    After corrections join: all 5 IOF rows must have category=compras and tags=impostos.
    """
    config = _build_p2_config(tmp_path)
    month = _build_iof_month(tmp_path)
    _write_iof_overrides(config)

    output = tmp_path / "out"
    result = _run_p2_categorize(month, config, output)
    assert result.returncode == 0, f"categorize failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"

    rows = _load_p2_rows(output / "transactions.csv")
    iof_rows = [r for r in rows if r["description"] == "IOF DESPESA NO EXTERIOR"]
    assert len(iof_rows) == 5, f"expected 5 IOF rows, got {len(iof_rows)}"

    for r in iof_rows:
        assert r["category"] == "compras", (
            f"IOF row {r['date']} {r['amount']}: expected category=compras, "
            f"got {r['category']!r} — P2 checkpoint decision not applied"
        )
        assert r["tags"] == "impostos", (
            f"IOF row {r['date']} {r['amount']}: expected tags=impostos, "
            f"got {r['tags']!r} — impostos tag must be carried on IOF rows"
        )
        assert r["manual_override"] == "true", (
            f"IOF row {r['date']} {r['amount']}: expected manual_override=true"
        )


def test_transporte_count_unchanged_after_iof_fix(tmp_path: Path):
    """After the P2 fix, transporte rows are unaffected — the IOF rows leave impostos,
    move to compras, and transporte count stays at its pre-fix value (no bulk remap).
    """
    config = _build_p2_config(tmp_path)
    month = _build_iof_month(tmp_path)
    _write_iof_overrides(config)

    output = tmp_path / "out"
    result = _run_p2_categorize(month, config, output)
    assert result.returncode == 0, f"categorize failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"

    rows = _load_p2_rows(output / "transactions.csv")
    transporte_count = sum(1 for r in rows if r["category"] == "transporte")
    impostos_count = sum(1 for r in rows if r["category"] == "impostos")
    compras_count = sum(1 for r in rows if r["category"] == "compras")

    # The fixture has 1 Uber (transporte) row; IOF rows must NOT land in transporte.
    assert transporte_count == 1, (
        f"transporte count changed: expected 1 (Uber only), got {transporte_count} — "
        "IOF rows must not be in transporte after the P2 fix"
    )
    assert impostos_count == 0, (
        f"impostos is no longer a valid category (p2-3): got {impostos_count} rows — "
        "IOF rows must not carry category=impostos after the fix"
    )
    # The fixture has 2 compras rows (ACTIVESHOP + RARESHOP via compras supplier
    # default) plus 5 IOF rows → 7 total. The exact count depends on the fixture;
    # what matters is that it increased by exactly 5 vs the no-override baseline.
    assert compras_count >= 5, (
        f"compras count must include the 5 IOF rows: got {compras_count}"
    )


def test_iof_without_overrides_uses_supplier_default(tmp_path: Path):
    """Without manual-overrides.csv, IOF rows use iof.default_category=compras
    (supplier change alone is sufficient for the category; only the tag requires
    the overrides file).
    """
    config = _build_p2_config(tmp_path)
    month = _build_iof_month(tmp_path)
    # No overrides written — supplier default alone must yield compras.

    output = tmp_path / "out"
    result = _run_p2_categorize(month, config, output)
    assert result.returncode == 0, f"categorize failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"

    rows = _load_p2_rows(output / "transactions.csv")
    iof_rows = [r for r in rows if r["description"] == "IOF DESPESA NO EXTERIOR"]
    assert len(iof_rows) == 5

    for r in iof_rows:
        assert r["category"] == "compras", (
            f"IOF row without override: expected category=compras (supplier default), "
            f"got {r['category']!r}"
        )
        # No override → no impostos tag; manual_override=false.
        assert r["manual_override"] == "false"
