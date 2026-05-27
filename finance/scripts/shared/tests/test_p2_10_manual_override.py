"""Regression tests for p2-10: manual-override marker + conflict detection (S5).

Decision S5: the `manual_override` boolean column on transactions.csv is the
read/output representation; the append-only corrections log
`config/corrections/manual-overrides.csv` is the durable source of truth.
categorize.py re-stamps the column from the log on every regeneration and
surfaces a conflict (never silently rewrites) when a rule/alias change would
reclassify a manually-overridden row.

Required cases (from the p2-10 task file + executor prompt):
  1. A MARKED record survives a retroactive alias change that would otherwise
     reclassify it — the conflict is SURFACED, not auto-applied.
  2. An UNMARKED record reclassifies normally.
  3. The boolean column survives a regeneration (re-stamped from the log).

Row identity = (date, description, amount) — the scheme p2-23 documents for
transactions.csv (the row carries no native tx_id). p3-2 (S4) reuses it.

Invocation strategy mirrors test_categorize_integration.py: run categorize.py
as a subprocess with BOOKKEEPER_CONFIG_DIR pointed at a per-test config dir so
the single resolver (p2-9) uses fixture config, not the real vault.
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

# Fixture row used as the override target. CLARO resolves to the `claro_movel`
# supplier whose default_category is `moradia` in the stock fixture.
_CLARO_DATE = "2026-04-05"
_CLARO_DESC = "CLARO"
_CLARO_AMOUNT = "-120.00"


@pytest.fixture
def month_folder(tmp_path: Path) -> Path:
    target = tmp_path / "month-2026-04"
    shutil.copytree(_MONTH_FIXTURE, target)
    return target


def _build_config(tmp_path: Path) -> Path:
    """Build a per-test config dir from the shared fixture dictionaries.

    Returns the config dir. Tests mutate suppliers.json and/or drop a
    corrections/manual-overrides.csv into it before running categorize.py.
    """
    target = tmp_path / "config"
    target.mkdir()
    shutil.copy(_FIXTURES / "categories.json", target / "categories.json")
    shutil.copy(_FIXTURES / "suppliers.json", target / "suppliers.json")
    shutil.copy(_FIXTURES / "tags.json", target / "tags.json")
    (target / "standing-rules.yaml").write_text(
        MINIMAL_STANDING_RULES_YAML, encoding="utf-8"
    )
    return target


def _set_claro_category(config: Path, new_category: str) -> None:
    """Simulate a retroactive rule change: flip CLARO's default_category."""
    suppliers_path = config / "suppliers.json"
    data = json.loads(suppliers_path.read_text(encoding="utf-8"))
    data["suppliers"]["claro_movel"]["default_category"] = new_category
    suppliers_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _write_override(
    config: Path,
    *,
    tx_date: str,
    tx_description: str,
    tx_amount: str,
    override_category: str,
    override_tags: str = "",
) -> None:
    """Append a manual-override row into config/corrections/manual-overrides.csv."""
    corrections = config / "corrections"
    corrections.mkdir(exist_ok=True)
    path = corrections / "manual-overrides.csv"
    header = (
        "tx_date,tx_description,tx_amount,override_category,override_tags,"
        "month,added_at,source,note\n"
    )
    if not path.exists():
        path.write_text(header, encoding="utf-8")
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            tx_date, tx_description, tx_amount, override_category,
            override_tags, "2026-04", "2026-05-26T00:00:00", "manual",
            "p2-10 regression fixture",
        ])


def _run_categorize(
    month: Path, config: Path, output: Path, force: bool = False
) -> subprocess.CompletedProcess:
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


def _row_by_desc(rows: list[dict], desc: str) -> dict:
    matches = [r for r in rows if r["description"] == desc]
    assert matches, f"no row with description {desc!r}"
    assert len(matches) == 1, f"expected one {desc!r} row, got {len(matches)}"
    return matches[0]


# ---------------------------------------------------------------------------
# Case 1 — marked row survives a retroactive reclassification; conflict surfaced
# ---------------------------------------------------------------------------

def test_marked_row_survives_retroactive_reclassification(
    month_folder: Path, tmp_path: Path
):
    """A manually-overridden row keeps its override category after a rule/alias
    change that would reclassify it. The conflict is SURFACED, not auto-applied.
    """
    config = _build_config(tmp_path)
    # The user manually fixed the CLARO row to `compras`.
    _write_override(
        config,
        tx_date=_CLARO_DATE,
        tx_description=_CLARO_DESC,
        tx_amount=_CLARO_AMOUNT,
        override_category="compras",
    )
    # Later, a rule change flips CLARO's supplier default to `transporte`.
    _set_claro_category(config, "transporte")

    output = tmp_path / "out"
    result = _run_categorize(month_folder, config, output)
    assert result.returncode == 0, f"categorize failed: {result.stderr}"

    rows = _load_rows(output / "transactions.csv")
    claro = _row_by_desc(rows, _CLARO_DESC)

    # Override PRESERVED — not rewritten to the new rule's category.
    assert claro["category"] == "compras", (
        f"override not preserved: category={claro['category']!r} "
        f"(rule change to transporte must NOT win over the manual override)"
    )
    assert claro["manual_override"] == "true"

    # Conflict SURFACED in the run report (the new rule disagrees).
    combined = result.stdout + result.stderr
    assert "MANUAL-OVERRIDE CONFLICT" in combined, (
        "conflict was not surfaced in categorize.py output"
    )
    assert "transporte" in combined and "compras" in combined


def test_conflict_emits_audit_event(month_folder: Path, tmp_path: Path):
    """The surfaced conflict also emits a `manual_override_conflict` audit event
    (best-effort observability — provenance of the disagreement)."""
    config = _build_config(tmp_path)
    _write_override(
        config,
        tx_date=_CLARO_DATE,
        tx_description=_CLARO_DESC,
        tx_amount=_CLARO_AMOUNT,
        override_category="compras",
    )
    _set_claro_category(config, "transporte")

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
    conflict_events = [
        e for e in events if e["event_type"] == "manual_override_conflict"
    ]
    assert conflict_events, (
        f"no manual_override_conflict event; got types "
        f"{[e['event_type'] for e in events]}"
    )
    e = conflict_events[0]
    assert e["summary"]["conflict_count"] == 1
    c = e["summary"]["conflicts"][0]
    assert c["classifier_category"] == "transporte"
    assert c["override_category"] == "compras"


def test_marked_row_without_rule_change_no_conflict(
    month_folder: Path, tmp_path: Path
):
    """An override that AGREES with the classifier marks the row but raises no
    conflict (override == current rule)."""
    config = _build_config(tmp_path)
    # Override to the SAME category the supplier already yields (moradia).
    _write_override(
        config,
        tx_date=_CLARO_DATE,
        tx_description=_CLARO_DESC,
        tx_amount=_CLARO_AMOUNT,
        override_category="moradia",
    )

    output = tmp_path / "out"
    result = _run_categorize(month_folder, config, output)
    assert result.returncode == 0, f"categorize failed: {result.stderr}"

    rows = _load_rows(output / "transactions.csv")
    claro = _row_by_desc(rows, _CLARO_DESC)
    assert claro["manual_override"] == "true"
    assert claro["category"] == "moradia"
    assert "MANUAL-OVERRIDE CONFLICT" not in (result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# Case 2 — unmarked row reclassifies normally
# ---------------------------------------------------------------------------

def test_unmarked_row_reclassifies_normally(month_folder: Path, tmp_path: Path):
    """With no override recorded, a rule/alias change reclassifies the row
    normally and the row is marked manual_override=false."""
    config = _build_config(tmp_path)
    # No manual-overrides.csv written. Flip the CLARO rule to transporte.
    _set_claro_category(config, "transporte")

    output = tmp_path / "out"
    result = _run_categorize(month_folder, config, output)
    assert result.returncode == 0, f"categorize failed: {result.stderr}"

    rows = _load_rows(output / "transactions.csv")
    claro = _row_by_desc(rows, _CLARO_DESC)
    assert claro["category"] == "transporte", (
        "unmarked row must follow the new rule"
    )
    assert claro["manual_override"] == "false"
    assert "MANUAL-OVERRIDE CONFLICT" not in (result.stdout + result.stderr)


def test_all_rows_false_when_no_overrides_file(
    month_folder: Path, tmp_path: Path
):
    """Fail-soft: absent manual-overrides.csv => every row manual_override=false."""
    config = _build_config(tmp_path)  # no corrections/ dir at all
    output = tmp_path / "out"
    result = _run_categorize(month_folder, config, output)
    assert result.returncode == 0, f"categorize failed: {result.stderr}"
    rows = _load_rows(output / "transactions.csv")
    assert rows
    for r in rows:
        assert r["manual_override"] == "false"


# ---------------------------------------------------------------------------
# Case 3 — boolean survives regeneration (re-stamped from the log)
# ---------------------------------------------------------------------------

def test_override_marker_survives_regeneration(
    month_folder: Path, tmp_path: Path
):
    """The manual_override marker is re-derived from the corrections log on
    every run — it survives a wholesale regeneration of transactions.csv
    (the row-only flag would otherwise be wiped, which is the reason S5 backs
    the column with the append-only log)."""
    config = _build_config(tmp_path)
    _write_override(
        config,
        tx_date=_CLARO_DATE,
        tx_description=_CLARO_DESC,
        tx_amount=_CLARO_AMOUNT,
        override_category="compras",
    )

    output = tmp_path / "out"

    # First close.
    result1 = _run_categorize(month_folder, config, output)
    assert result1.returncode == 0, f"first run failed: {result1.stderr}"
    claro1 = _row_by_desc(_load_rows(output / "transactions.csv"), _CLARO_DESC)
    assert claro1["manual_override"] == "true"
    assert claro1["category"] == "compras"

    # Regenerate (wholesale rewrite) with --force; the corrections log is the
    # source of truth, so the marker + override category must persist.
    result2 = _run_categorize(month_folder, config, output, force=True)
    assert result2.returncode == 0, f"regeneration failed: {result2.stderr}"
    claro2 = _row_by_desc(_load_rows(output / "transactions.csv"), _CLARO_DESC)
    assert claro2["manual_override"] == "true", (
        "marker was wiped on regeneration — the column is not being re-stamped "
        "from the corrections log"
    )
    assert claro2["category"] == "compras"


def test_amount_format_drift_still_binds(month_folder: Path, tmp_path: Path):
    """Row identity normalizes amount as a float: an override logged with
    `-120.0` still binds to a ledger row whose amount is `-120.00`."""
    config = _build_config(tmp_path)
    _write_override(
        config,
        tx_date=_CLARO_DATE,
        tx_description=_CLARO_DESC,
        tx_amount="-120.0",  # trailing-zero drift vs the ledger's -120.00
        override_category="compras",
    )
    output = tmp_path / "out"
    result = _run_categorize(month_folder, config, output)
    assert result.returncode == 0, f"categorize failed: {result.stderr}"
    claro = _row_by_desc(_load_rows(output / "transactions.csv"), _CLARO_DESC)
    assert claro["manual_override"] == "true"
    assert claro["category"] == "compras"


# ---------------------------------------------------------------------------
# Fail-loud — malformed corrections file raises
# ---------------------------------------------------------------------------

def test_malformed_overrides_file_raises(month_folder: Path, tmp_path: Path):
    """A manual-overrides.csv missing a required identity column is a fail-loud
    condition — categorize.py must NOT silently default to no-overrides."""
    config = _build_config(tmp_path)
    corrections = config / "corrections"
    corrections.mkdir()
    # Header missing tx_amount + override_category.
    (corrections / "manual-overrides.csv").write_text(
        "tx_date,tx_description,month,added_at,source,note\n",
        encoding="utf-8",
    )
    output = tmp_path / "out"
    result = _run_categorize(month_folder, config, output)
    assert result.returncode != 0, "expected non-zero exit on malformed file"
    assert "CORRECTIONS ERROR" in (result.stdout + result.stderr)
