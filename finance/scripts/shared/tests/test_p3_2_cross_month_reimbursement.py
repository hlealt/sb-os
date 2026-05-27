"""Regression tests for p3-2: cross-month reimbursement Pass 3 (decision S4).

Decision S4 (user, already made): wire the dormant
`accrual.compute_data_competencia(manual_override=...)` path (finding #6) via a
Pass-3 queue in `lib/queue.py`, and back the override with the SAME append-only
corrections substrate as S5 — a sibling `competencia-overrides.csv` keyed by the
SAME composite identity `tx_date | tx_description | tx_amount`. The
`manual-overrides.csv` schema overrides category/tags and CANNOT host a
`data_competencia` date, so a minimal sibling file was added (documented in
corrections/CONVENTION.md).

Two layers under test:
  1. PURE — `build_pass_3_queue` / `apply_pass_3_resolution` in lib/queue.py:
     detection of cross-month reimbursement rows + idempotence (already-attributed
     rows are not re-queued) + the in-memory attribution edit (caixa never moves).
  2. INTEGRATION — categorize.py re-stamps a competencia-overrides.csv entry onto
     the row's data_competencia on every regeneration and emits a
     `competencia_override` audit event. Canonical case: a March medical expense
     reimbursed by REEMBOLSO PLANO SAUDE on 2026-04-30 attributes to MARCH on
     competência (no false April income spike) while the cash date stays April.

Integration harness mirrors test_p2_10_manual_override.py: run categorize.py as a
subprocess with BOOKKEEPER_CONFIG_DIR pointed at a per-test fixture config dir.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from lib import queue as q
from _fixture_helpers import MINIMAL_STANDING_RULES_YAML

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
_FIXTURES = _TESTS_DIR / "fixtures"
_MONTH_FIXTURE = _FIXTURES / "month-2026-04"

# Canonical reimbursement row from the shared fixture: received 2026-04-30,
# matches reimbursement_mappings `REEMBOLSO → saude`. The originating medical
# expense is in March 2026.
_REIMB_DATE = "2026-04-30"
_REIMB_DESC = "REEMBOLSO PLANO SAUDE"
_REIMB_AMOUNT = "200.00"
_ORIGIN_MONTH = "2026-03-15"  # March — where the expense was incurred

_MAPPINGS = {"REEMBOLSO": "saude", "CARE PLUS": {"category": "saude", "tag": "reembolso"}}


# ---------------------------------------------------------------------------
# Layer 1 — pure queue.py Pass 3 logic
# ---------------------------------------------------------------------------

def test_build_pass_3_queues_cross_month_reimbursement():
    """A reimbursement row whose competência month == caixa month (the
    un-overridden skip-default) is queued for a Pass 3 override prompt."""
    txs = [
        {
            "description": "REEMBOLSO PLANO SAUDE",
            "amount": "200.00",
            "data_caixa": "2026-04-30",
            "data_competencia": "2026-04-30",  # skip-default, not yet overridden
        }
    ]
    items = q.build_pass_3_queue(txs, _MAPPINGS)
    assert len(items) == 1
    item = items[0]
    assert item.item_type == "reimbursement_competencia"
    assert item.transaction_id == 0
    assert item.context["received_month"] == "2026-04"


def test_build_pass_3_skips_non_reimbursement_rows():
    """Rows that don't match any reimbursement pattern are never queued."""
    txs = [
        {
            "description": "UBER 12345",
            "amount": "-50.00",
            "data_caixa": "2026-04-12",
            "data_competencia": "2026-04-12",
        }
    ]
    assert q.build_pass_3_queue(txs, _MAPPINGS) == []


def test_build_pass_3_is_idempotent_when_already_attributed():
    """A reimbursement row already attributed to a DIFFERENT month (override in
    effect, re-stamped from the log) is NOT re-queued — Pass 3 is idempotent
    across regenerations."""
    txs = [
        {
            "description": "REEMBOLSO PLANO SAUDE",
            "amount": "200.00",
            "data_caixa": "2026-04-30",
            "data_competencia": "2026-03-15",  # already moved to March
        }
    ]
    assert q.build_pass_3_queue(txs, _MAPPINGS) == []


def test_apply_pass_3_sets_competencia_and_preserves_caixa():
    """Applying the user's answer moves data_competencia to the originating
    month and NEVER mutates data_caixa (spec Q12 / invariant 4). Input list is
    not mutated (pure)."""
    txs = [
        {
            "description": "REEMBOLSO PLANO SAUDE",
            "amount": "200.00",
            "data_caixa": "2026-04-30",
            "data_competencia": "2026-04-30",
        }
    ]
    item = q.build_pass_3_queue(txs, _MAPPINGS)[0]
    out = q.apply_pass_3_resolution(
        txs, item, {"data_competencia": date(2026, 3, 15)}
    )
    assert out[0]["data_competencia"] == "2026-03-15"
    assert out[0]["data_caixa"] == "2026-04-30"  # caixa never moves
    # Input untouched (pure).
    assert txs[0]["data_competencia"] == "2026-04-30"


def test_apply_pass_3_rejects_wrong_item_type():
    bad = q.QueueItem(transaction_id=0, item_type="category")
    with pytest.raises(ValueError):
        q.apply_pass_3_resolution([{}], bad, {"data_competencia": "2026-03-15"})


# ---------------------------------------------------------------------------
# Layer 2 — categorize.py integration (re-stamp from corrections log + audit)
# ---------------------------------------------------------------------------

@pytest.fixture
def month_folder(tmp_path: Path) -> Path:
    target = tmp_path / "month-2026-04"
    shutil.copytree(_MONTH_FIXTURE, target)
    return target


def _build_config(tmp_path: Path) -> Path:
    target = tmp_path / "config"
    target.mkdir()
    shutil.copy(_FIXTURES / "categories.json", target / "categories.json")
    shutil.copy(_FIXTURES / "suppliers.json", target / "suppliers.json")
    shutil.copy(_FIXTURES / "tags.json", target / "tags.json")
    (target / "standing-rules.yaml").write_text(
        MINIMAL_STANDING_RULES_YAML, encoding="utf-8"
    )
    return target


def _write_competencia_override(
    config: Path,
    *,
    tx_date: str,
    tx_description: str,
    tx_amount: str,
    override_data_competencia: str,
    reason: str = "cross_month_reimbursement",
) -> None:
    corrections = config / "corrections"
    corrections.mkdir(exist_ok=True)
    path = corrections / "competencia-overrides.csv"
    header = (
        "tx_date,tx_description,tx_amount,override_data_competencia,reason,"
        "month,added_at,source,note\n"
    )
    if not path.exists():
        path.write_text(header, encoding="utf-8")
    with open(path, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            tx_date, tx_description, tx_amount, override_data_competencia,
            reason, "2026-04", "2026-05-27T00:00:00", "p3-2-test",
            "p3-2 regression fixture",
        ])


def _run_categorize(month: Path, config: Path, output: Path, force: bool = False):
    env = os.environ.copy()
    env["BOOKKEEPER_CONFIG_DIR"] = str(config)
    cmd = [
        sys.executable,
        str(_SCRIPTS_DIR / "categorize.py"),
        str(month / "processed"),
        str(config),
        str(output),
    ]
    if force:
        cmd.append("--force")
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def _load_rows(p: Path) -> list[dict]:
    with open(p, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _reimb_row(rows: list[dict]) -> dict:
    matches = [r for r in rows if r["description"] == _REIMB_DESC]
    assert matches, f"no reimbursement row {_REIMB_DESC!r}"
    assert len(matches) == 1
    return matches[0]


def test_canonical_cross_month_attributes_to_origin_month(
    month_folder: Path, tmp_path: Path
):
    """CANONICAL CASE: a March medical expense reimbursed on 2026-04-30 is
    attributed to MARCH on competência — no false April income spike — while
    the cash date (data_caixa) stays April (cash-basis view unchanged)."""
    config = _build_config(tmp_path)
    _write_competencia_override(
        config,
        tx_date=_REIMB_DATE,
        tx_description=_REIMB_DESC,
        tx_amount=_REIMB_AMOUNT,
        override_data_competencia=_ORIGIN_MONTH,
    )
    output = tmp_path / "out"
    result = _run_categorize(month_folder, config, output)
    assert result.returncode == 0, f"categorize failed: {result.stderr}"

    row = _reimb_row(_load_rows(output / "transactions.csv"))
    # Competência moved to the originating-expense month (March).
    assert row["data_competencia"] == _ORIGIN_MONTH, (
        f"competência not attributed to origin month: {row['data_competencia']!r}"
    )
    assert row["data_competencia"].startswith("2026-03")
    # Cash-basis view UNCHANGED — data_caixa stays the received date (April).
    assert row["data_caixa"] == _REIMB_DATE
    # Reimbursement still classified to its category (categorization intact).
    assert row["category"] == "saude"


def test_without_override_collapses_to_received_month(
    month_folder: Path, tmp_path: Path
):
    """Without an override, the reimbursement collapses to the received month
    (April) — this is the pre-fix gap the override corrects."""
    config = _build_config(tmp_path)  # no competencia-overrides.csv
    output = tmp_path / "out"
    result = _run_categorize(month_folder, config, output)
    assert result.returncode == 0, f"categorize failed: {result.stderr}"

    row = _reimb_row(_load_rows(output / "transactions.csv"))
    assert row["data_competencia"] == _REIMB_DATE  # April == caixa (skip-default)
    assert row["data_caixa"] == _REIMB_DATE


def test_override_survives_regeneration(month_folder: Path, tmp_path: Path):
    """The competência attribution is re-derived from the corrections log on
    every run — it survives a wholesale --force regeneration of transactions.csv
    (the row-only value would otherwise be wiped)."""
    config = _build_config(tmp_path)
    _write_competencia_override(
        config,
        tx_date=_REIMB_DATE,
        tx_description=_REIMB_DESC,
        tx_amount=_REIMB_AMOUNT,
        override_data_competencia=_ORIGIN_MONTH,
    )
    output = tmp_path / "out"

    r1 = _run_categorize(month_folder, config, output)
    assert r1.returncode == 0, f"first run failed: {r1.stderr}"
    assert _reimb_row(_load_rows(output / "transactions.csv"))[
        "data_competencia"
    ] == _ORIGIN_MONTH

    r2 = _run_categorize(month_folder, config, output, force=True)
    assert r2.returncode == 0, f"regeneration failed: {r2.stderr}"
    assert _reimb_row(_load_rows(output / "transactions.csv"))[
        "data_competencia"
    ] == _ORIGIN_MONTH, "override wiped on regeneration — not re-stamped from log"


def test_override_emits_competencia_override_audit_event(
    month_folder: Path, tmp_path: Path
):
    """Each applied override emits one competencia_override audit event carrying
    the row identity + before/after competência + the reason."""
    config = _build_config(tmp_path)
    _write_competencia_override(
        config,
        tx_date=_REIMB_DATE,
        tx_description=_REIMB_DESC,
        tx_amount=_REIMB_AMOUNT,
        override_data_competencia=_ORIGIN_MONTH,
    )
    output = tmp_path / "out"
    result = _run_categorize(month_folder, config, output)
    assert result.returncode == 0, f"categorize failed: {result.stderr}"

    audit_dir = Path(os.environ["BOOKKEEPER_AUDIT_LOG_DIR"])
    events: list[dict] = []
    for p in sorted(audit_dir.glob("events-*.jsonl")):
        events.extend(
            json.loads(line)
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    overrides = [e for e in events if e["event_type"] == "competencia_override"]
    assert len(overrides) == 1, (
        f"expected exactly one competencia_override event; got "
        f"{[e['event_type'] for e in events]}"
    )
    s = overrides[0]["summary"]
    assert s["overridden_data_competencia"] == _ORIGIN_MONTH
    assert s["original_data_competencia"] == _REIMB_DATE  # was the received date
    assert s["override_reason"] == "cross_month_reimbursement"
    assert _REIMB_DESC in s["transaction_id"]


def test_malformed_competencia_overrides_file_raises(
    month_folder: Path, tmp_path: Path
):
    """A competencia-overrides.csv missing a required column is fail-loud —
    categorize.py must NOT silently default to no-overrides."""
    config = _build_config(tmp_path)
    corrections = config / "corrections"
    corrections.mkdir()
    # Header missing override_data_competencia + tx_amount.
    (corrections / "competencia-overrides.csv").write_text(
        "tx_date,tx_description,reason,month,added_at,source,note\n",
        encoding="utf-8",
    )
    output = tmp_path / "out"
    result = _run_categorize(month_folder, config, output)
    assert result.returncode != 0, "expected non-zero exit on malformed file"
    assert "CORRECTIONS ERROR" in (result.stdout + result.stderr)
