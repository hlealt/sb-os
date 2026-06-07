"""Schema-validation + contract tests for restamp_supplier_canonical.

WRITE-class, use=retro-rewrite. Non-negotiables verified:
  1. DRY-RUN (default) writes NOTHING — transactions.csv byte-for-byte
     unchanged, no .bak / .rollback artifact created.
  2. --apply re-stamps ONLY the supplier_canonical column on exactly the
     matching rows; header and every other field preserved (schema
     conformance: no field added or dropped).
  3. ROLLBACK restores the written files byte-for-byte.
  4. Live-pipeline guard: --to values the name-canonicalization pipeline
     would not stamp are REFUSED (blocking error, exit 1).
  5. data_caixa (`date` column) is never touched.

Import idiom mirrors test_p4_26_retro_rewrite.py (file-path import from
scripts/migrations/).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent  # shared/
_MIGRATIONS_DIR = _SCRIPTS_DIR.parent / "migrations"

for _p in (_SCRIPTS_DIR, _MIGRATIONS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load_module(name: str, filename: str):
    path = _MIGRATIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


restamp = _load_module("restamp_supplier_canonical", "restamp_supplier_canonical.py")


_SUPPLIERS_JSON = {
    "version": 1,
    "suppliers": {
        "mercado-livre": {
            "canonical": "Mercado Livre",
            "aliases": ["MERCADOLIVRE"],
            "default_category": "compras",
        },
        "iof": {
            "canonical": "IOF",
            "aliases": ["IOF CAMBIO"],
            "default_category": "compras",
        },
    },
}

_STANDING_RULES = """\
_meta:
  schema_version: 1
  rule_set_version: test
supplier_rules: {}
name_canonicalization:
  status: active
  default_style: titlecase_accented
  exceptions: [IOF]
"""

_TX_HEADER = (
    "date,description,amount,category,supplier_canonical,tags,"
    "data_competencia,manual_override\n"
)
_TX_2026_01 = [
    "2026-01-05,MERCADOLIVRE*X,-150.00,compras,Mercado livre,,2026-01-05,false\n",
    "2026-01-10,IOF CAMBIO,-3.00,compras,IOF,impostos,2026-01-10,false\n",
    "2026-01-15,OTHER,-80.00,alimentacao,Other,,2026-01-15,false\n",
]
_TX_2026_02 = [
    "2026-02-02,MERCADOLIVRE*Y,-50.00,compras,Mercado livre,,2026-02-02,false\n",
    "2026-02-03,IOF DESP,-1.50,compras,Iof,impostos,2026-02-03,false\n",
]


@pytest.fixture
def bk(tmp_path, monkeypatch):
    root = tmp_path / "bk"
    config = root / "config"
    corrections = config / "corrections"
    config.mkdir(parents=True)
    corrections.mkdir(parents=True)
    for month, rows in (("2026-01", _TX_2026_01), ("2026-02", _TX_2026_02)):
        d = root / "ledgers" / "fechamento" / month
        d.mkdir(parents=True)
        (d / "transactions.csv").write_text(_TX_HEADER + "".join(rows),
                                            encoding="utf-8")
    (config / "suppliers.json").write_text(
        json.dumps(_SUPPLIERS_JSON, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (config / "standing-rules.yaml").write_text(_STANDING_RULES, encoding="utf-8")

    monkeypatch.setenv("BOOKKEEPER_ROOT", str(root))
    monkeypatch.setenv("BOOKKEEPER_CONFIG_DIR", str(config))
    monkeypatch.setenv("BOOKKEEPER_LEDGER_DIR", str(root / "ledgers"))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    return {
        "root": root,
        "config": config,
        "corrections": corrections,
        "fechamento": root / "ledgers" / "fechamento",
    }


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _tx(bk, month: str) -> Path:
    return bk["fechamento"] / month / "transactions.csv"


# ---------------------------------------------------------------------------
# 1. Dry-run writes nothing
# ---------------------------------------------------------------------------

def test_dry_run_writes_nothing(bk):
    before = {m: _sha(_tx(bk, m)) for m in ("2026-01", "2026-02")}
    rc = restamp.main(["--from", "Mercado livre", "--to", "Mercado Livre"])
    assert rc == 0
    for m, h in before.items():
        assert _sha(_tx(bk, m)) == h, f"{m} mutated by dry-run"
    assert not list(bk["fechamento"].rglob("*.bak.*"))
    assert not (bk["corrections"] / ".rollback").exists()


# ---------------------------------------------------------------------------
# 2. Apply re-stamps only the matching rows' supplier_canonical
# ---------------------------------------------------------------------------

def test_apply_restamps_only_target_column(bk):
    import csv

    rc = restamp.main(["--from", "Mercado livre", "--to", "Mercado Livre",
                       "--apply"])
    assert rc == 0
    for month, expect_changed in (("2026-01", 1), ("2026-02", 1)):
        with open(_tx(bk, month), encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = list(reader.fieldnames or [])
            rows = list(reader)
        # Schema conformance: header unchanged, no field added/dropped.
        assert header == _TX_HEADER.strip().split(",")
        assert sum(1 for r in rows
                   if r["supplier_canonical"] == "Mercado Livre") == expect_changed
        assert all(r["supplier_canonical"] != "Mercado livre" for r in rows)
    # Untouched columns survive: data_caixa (date), amounts, categories.
    with open(_tx(bk, "2026-01"), encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["date"] == "2026-01-05"
    assert rows[0]["amount"] == "-150.00"
    assert rows[1]["supplier_canonical"] == "IOF"  # non-matching row untouched
    assert rows[2]["supplier_canonical"] == "Other"


def test_months_scope_limits_writes(bk):
    before_02 = _sha(_tx(bk, "2026-02"))
    rc = restamp.main(["--from", "Mercado livre", "--to", "Mercado Livre",
                       "--months", "2026-01", "--apply"])
    assert rc == 0
    assert _sha(_tx(bk, "2026-02")) == before_02


# ---------------------------------------------------------------------------
# 3. Rollback restores byte-for-byte
# ---------------------------------------------------------------------------

def test_rollback_restores(bk):
    before = {m: _sha(_tx(bk, m)) for m in ("2026-01", "2026-02")}
    rc = restamp.main(["--from", "Iof", "--to", "IOF", "--apply"])
    assert rc == 0
    assert _sha(_tx(bk, "2026-02")) != before["2026-02"]
    manifests = list((bk["corrections"] / ".rollback").glob(
        "restamp_supplier_canonical-*.json"))
    assert len(manifests) == 1
    token = json.loads(manifests[0].read_text(encoding="utf-8"))["token"]
    rc = restamp.main(["--rollback", token])
    assert rc == 0
    for m, h in before.items():
        assert _sha(_tx(bk, m)) == h, f"{m} not restored"


# ---------------------------------------------------------------------------
# 4. Live-pipeline guard refuses divergent targets
# ---------------------------------------------------------------------------

def test_refuses_non_live_target(bk):
    before = _sha(_tx(bk, "2026-01"))
    rc = restamp.main(["--from", "Mercado livre", "--to", "Mercado livre X",
                       "--apply"])
    assert rc == 1  # blocking error
    assert _sha(_tx(bk, "2026-01")) == before


def test_refuses_identical_from_to(bk):
    rc = restamp.main(["--from", "IOF", "--to", "IOF"])
    assert rc == 1


# ---------------------------------------------------------------------------
# 5. Unique backup tokens across back-to-back applies
# ---------------------------------------------------------------------------

def test_back_to_back_applies_get_distinct_tokens(bk):
    rc1 = restamp.main(["--from", "Mercado livre", "--to", "Mercado Livre",
                        "--apply"])
    rc2 = restamp.main(["--from", "Iof", "--to", "IOF", "--apply"])
    assert rc1 == 0 and rc2 == 0
    manifests = list((bk["corrections"] / ".rollback").glob(
        "restamp_supplier_canonical-*.json"))
    assert len(manifests) == 2, "same-second applies must not share a manifest"
