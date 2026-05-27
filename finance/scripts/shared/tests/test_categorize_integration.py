"""End-to-end test for `categorize.py`.

Runs `categorize.py` as a subprocess against a synthetic month folder
containing one row per behavior-matrix scenario plus a `fatura_totals.json`.
Asserts:

  - column count == 20 (data-model §1 + manual_override from p2-10/S5)
  - `subcategory` column is absent
  - new columns (`data_caixa`, `data_competencia`, `supplier_canonical`,
    `tags`) are present
  - per-row `data_caixa` / `data_competencia` match the behavior-matrix
    expected outputs
  - invariant 6: NO row has `supplier_canonical == "Outros"` in storage

Invocation strategy: the script is exec'd via `python -m` from the
parent scripts directory so its relative imports work.
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

from _fixture_helpers import MINIMAL_STANDING_RULES_YAML

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
_FIXTURES = _TESTS_DIR / "fixtures"
_MONTH_FIXTURE = _FIXTURES / "month-2026-04"


@pytest.fixture
def month_folder(tmp_path: Path) -> Path:
    """Copy the fixture month folder into tmp_path so categorize.py can
    write its `categorized/` output without polluting the fixture tree."""
    target = tmp_path / "month-2026-04"
    shutil.copytree(_MONTH_FIXTURE, target)
    return target


@pytest.fixture
def config_folder(tmp_path: Path) -> Path:
    """Build a minimal config folder pointing at the fixture dictionaries.

    categorize.py expects: categories.json, suppliers.json, tags.json,
    standing-rules.yaml (loaded via BOOKKEEPER_CONFIG_DIR env var — p2-9).
    """
    target = tmp_path / "config"
    target.mkdir()
    shutil.copy(_FIXTURES / "categories.json", target / "categories.json")
    shutil.copy(_FIXTURES / "suppliers.json", target / "suppliers.json")
    shutil.copy(_FIXTURES / "tags.json", target / "tags.json")
    # Minimal standing-rules.yaml: required sections + B2-SR1 sections so
    # categorize.py startup loaders do not abort. See conftest.MINIMAL_STANDING_RULES_YAML.
    (target / "standing-rules.yaml").write_text(
        MINIMAL_STANDING_RULES_YAML, encoding="utf-8"
    )
    return target


def _run_categorize(month: Path, config: Path, output: Path) -> None:
    """Invoke categorize.py end-to-end. Pass the per-month `processed/` dir
    directly (new signature: <processed_dir> <config_folder> [output]).

    Sets BOOKKEEPER_CONFIG_DIR so the single resolver (p2-9) uses the
    fixture config dir rather than the real vault config.
    """
    env = os.environ.copy()
    env["BOOKKEEPER_CONFIG_DIR"] = str(config)
    cmd = [
        sys.executable,
        str(_SCRIPTS_DIR / "categorize.py"),
        str(month / "processed"),
        str(config),
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert result.returncode == 0, (
        f"categorize.py failed: stdout=\n{result.stdout}\nstderr=\n{result.stderr}"
    )


def _load_csv(p: Path) -> tuple[list[str], list[dict]]:
    with open(p, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def test_categorize_writes_20_columns(month_folder: Path, config_folder: Path,
                                       tmp_path: Path):
    # 19 base columns (data-model §1) + `manual_override` (p2-10 / S5).
    output = tmp_path / "out"
    _run_categorize(month_folder, config_folder, output)
    fields, _ = _load_csv(output / "transactions.csv")
    assert len(fields) == 20


def test_subcategory_column_is_absent(month_folder: Path, config_folder: Path,
                                       tmp_path: Path):
    output = tmp_path / "out"
    _run_categorize(month_folder, config_folder, output)
    fields, _ = _load_csv(output / "transactions.csv")
    assert "subcategory" not in fields


def test_new_columns_present(month_folder: Path, config_folder: Path,
                              tmp_path: Path):
    output = tmp_path / "out"
    _run_categorize(month_folder, config_folder, output)
    fields, _ = _load_csv(output / "transactions.csv")
    for col in ("data_caixa", "data_competencia", "supplier_canonical", "tags",
                "manual_override"):
        assert col in fields, f"missing required column: {col}"


def test_invariant_6_outros_never_in_storage(month_folder: Path,
                                              config_folder: Path,
                                              tmp_path: Path):
    """No row in the storage CSV may have supplier_canonical == 'Outros'.
    Outros is presentation-only (data-model §6 invariant 6)."""
    output = tmp_path / "out"
    _run_categorize(month_folder, config_folder, output)
    _, rows = _load_csv(output / "transactions.csv")
    assert rows, "categorize.py produced no rows"
    for row in rows:
        assert row["supplier_canonical"] != "Outros"


def test_behavior_matrix_per_row_dates(month_folder: Path, config_folder: Path,
                                        tmp_path: Path):
    """For each scenario row in the fixture, assert the expected
    (data_caixa, data_competencia) pair from spec §R3."""
    output = tmp_path / "out"
    _run_categorize(month_folder, config_folder, output)
    _, rows = _load_csv(output / "transactions.csv")

    # Index rows by description for stable lookup. (Descriptions are unique
    # in the fixture; if duplicates appear in a future fixture extension,
    # switch to original_ref.)
    by_desc = {r["description"]: r for r in rows}

    # Scenario A — Apr 12 single CC purchase, paid May 10.
    a = by_desc["UBER 12345"]
    assert a["data_caixa"] == "2026-05-10"
    assert a["data_competencia"] == "2026-04-12"

    # Scenario B — Mar 10 installment 1/3, paid Apr 10. The fixture's fatura
    # payment_date is May 10 (same fixture invoice for both CC rows in this
    # month — per-invoice caixa pinning, invariant 3). competência collapses
    # to original purchase date.
    b = by_desc["ACTIVESHOP PARC 1/3"]
    assert b["data_caixa"] == "2026-05-10"
    assert b["data_competencia"] == "2026-03-10"

    # Scenario C — Apr 5 utility bill (extrato). Caixa = competência =
    # transaction date (skip-default per Q13a — categorize.py does not run
    # the boundary prompt; the workflow does).
    c = by_desc["CLARO"]
    assert c["data_caixa"] == "2026-04-05"
    assert c["data_competencia"] == "2026-04-05"

    # Scenario D — Apr 30 reimbursement. categorize.py emits competência ==
    # caixa here (no manual override at this stage). The MANUAL OVERRIDE
    # path is verified at the unit-test layer in test_accrual.py.
    d = by_desc["REEMBOLSO PLANO SAUDE"]
    assert d["data_caixa"] == "2026-04-30"
    assert d["data_competencia"] == "2026-04-30"


def test_supplier_canonical_resolved_from_aliases(month_folder: Path,
                                                    config_folder: Path,
                                                    tmp_path: Path):
    """Sanity check the supplier layer ran. UBER and CLARO descriptions
    map to canonical supplier names from the fixture suppliers.json."""
    output = tmp_path / "out"
    _run_categorize(month_folder, config_folder, output)
    _, rows = _load_csv(output / "transactions.csv")
    by_desc = {r["description"]: r for r in rows}
    assert by_desc["UBER 12345"]["supplier_canonical"] == "Uber"
    assert by_desc["CLARO"]["supplier_canonical"] == "Claro"


def test_tags_column_seeded_by_categorize_rules(month_folder: Path,
                                                  config_folder: Path,
                                                  tmp_path: Path):
    """categorize.py seeds tags from config-driven rules (supplier default_tags,
    tag_application_rules, reimbursement_mappings tag keys).

    For the current fixture, no row matches the Care Plus / automotive-insurance
    rules and no fixture supplier declares default_tags, so all rows emit
    tags=''. Pass 1 may add further tags interactively.

    This name/assertion replaces the stale
    test_tags_column_emitted_empty_by_categorize (p2-29): that name implied
    categorize never seeds tags, which is no longer true — tags are
    config-driven from standing-rules.yaml tag_application_rules and
    supplier default_tags (B2-SR1 p2-15).
    """
    output = tmp_path / "out"
    _run_categorize(month_folder, config_folder, output)
    _, rows = _load_csv(output / "transactions.csv")
    # Fixture has no Care Plus / automotive rows and no supplier default_tags,
    # so all rows are empty after the seeding pass.
    for row in rows:
        assert row["tags"] == ""


def test_rule_fired_event_emitted_to_audit_log(month_folder: Path,
                                                 config_folder: Path,
                                                 tmp_path: Path):
    """End-to-end check that categorize.py loads standing-rules.yaml and
    emits a `rule_fired` summary event via the audit-event protocol."""
    output = tmp_path / "out"
    _run_categorize(month_folder, config_folder, output)
    audit_dir = Path(os.environ["BOOKKEEPER_AUDIT_LOG_DIR"])
    events: list[dict] = []
    for p in sorted(audit_dir.glob("events-*.jsonl")):
        events.extend(
            json.loads(line)
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    rule_events = [e for e in events if e["event_type"] == "rule_fired"]
    assert rule_events, (
        f"no rule_fired event in audit log; got types: "
        f"{[e['event_type'] for e in events]}"
    )
    e = rule_events[0]
    assert e["source"]["function"] == "categorize.main"
    assert e["summary"]["rows_seen"] >= 1
    assert e["summary"]["total_fires"] >= 1
    assert isinstance(e["summary"]["fires_by_rule"], dict)
