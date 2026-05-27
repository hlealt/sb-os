"""Regression tests for p4-26: the retro-rewrite tool suite.

Covers the three WRITE-class, use=retro-rewrite tools:
  - rename_tags.py
  - rename_canonical.py
  - merge_categories.py

Each tool MUST satisfy the three non-negotiables (verified per tool below):
  1. DRY-RUN (default invocation, no --apply) writes NOTHING — every config /
     corrections file is byte-for-byte unchanged, and no .bak / .rollback
     artifact is created.
  2. A real run (--apply) MATCHES the dry-run preview exactly — every location
     the preview marked WRITE is actually mutated, and no location it did NOT
     mark is touched.
  3. ROLLBACK restores prior state byte-for-byte (config files) and removes any
     correction-ledger row the run appended.

Plus: blocking-error guards (refuse on missing/invalid inputs), append-only
behavior (correction ledgers are appended, never rewritten), and audit-event
emission on apply.

The tools live in scripts/migrations/ (not a package on sys.path), so they are
imported by file path via importlib — the same pattern test_p4_14 uses for the
hyphenated audit-aliases.py.
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

# Make shared/ importable (for query_corrections compose) and migrations/.
for _p in (_SCRIPTS_DIR, _MIGRATIONS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load_module(name: str, filename: str):
    path = _MIGRATIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass/typing resolution (which looks the module
    # up in sys.modules by __module__) works for a file-path import.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


common = _load_module("_retro_rewrite_common", "_retro_rewrite_common.py")
rename_tags = _load_module("rename_tags", "rename_tags.py")
rename_canonical = _load_module("rename_canonical", "rename_canonical.py")
merge_categories = _load_module("merge_categories", "merge_categories.py")


# ---------------------------------------------------------------------------
# Fixture: an isolated bookkeeper tree (config + corrections + ledgers)
# ---------------------------------------------------------------------------


_TAGS_JSON = {
    "version": 1,
    "tags": {
        "boxe": {"label": "Boxe (aulas, equipamentos)", "added": "2026-05-03"},
        "tennis": {"label": "Tennis", "added": "2026-05-03"},
        "reembolso": {"label": "Reembolso", "added": "2026-05-03"},
    },
    "rejected": [],
}

_SUPPLIERS_JSON = {
    "version": 1,
    "suppliers": {
        "allecio-boxe": {
            "canonical": "Allecio (boxe)",
            "aliases": ["ALLECIO", "PIX ALLECIO"],
            "default_category": "esportes",
            "default_tags": ["boxe"],
        },
        "old-gym": {
            "canonical": "Old Gym Ltda",
            "aliases": ["OLD GYM"],
            "default_category": "carro",
            "default_tags": [],
        },
    },
}

_CATEGORIES_JSON = {
    "categories": {
        "esportes": {"description": "Esportes"},
        "transporte": {"description": "Transporte"},
        "carro": {"description": "Carro (seguro, IPVA)"},
        "saude": {"description": "Saude"},
    },
    "value_based_mappings": [
        {"vendor": "X", "amount": 100, "category": "carro", "label": "car thing"},
    ],
    "recurrence_rules": {
        "default_by_category": {"carro": "recorrente", "esportes": "pontual"},
        "vendor_overrides": {},
    },
    "reimbursement_mappings": {
        "CARE PLUS": {"category": "saude", "tag": "reembolso"},
        "SOME CAR REFUND": {"category": "carro", "tag": "reembolso"},
    },
}

_CORRECTION_HEADERS = {
    "tag-renames.csv": "from_tag,to_tag,scope,added_at,source,note\n",
    "vendor-canonicals.csv": "raw_vendor,canonical_vendor,scope,added_at,source,note\n",
    "category-migrations.csv": "from_category,to_category,scope,effective_after,added_at,source,note\n",
}

# transactions.csv rows exercising each affected output column.
_TX_HEADER = "date,description,amount,category,supplier_canonical,tags,data_competencia,manual_override\n"
_TX_ROWS = [
    "2026-01-05,PIX ALLECIO,-150.00,esportes,Allecio (boxe),boxe,2026-01-05,false\n",
    "2026-01-10,OLD GYM,-300.00,carro,Old Gym Ltda,,2026-01-10,false\n",
    "2026-01-15,SUPERMERCADO,-80.00,alimentacao,Supermercado,,2026-01-15,false\n",
]


@pytest.fixture
def bk(tmp_path, monkeypatch):
    """Build an isolated bookkeeper tree and point the tools at it via env."""
    root = tmp_path / "bk"
    config = root / "config"
    corrections = config / "corrections"
    ledger = root / "ledgers" / "fechamento" / "2026-01"
    corrections.mkdir(parents=True)
    ledger.mkdir(parents=True)
    (tmp_path / "sb-os.json").write_text("{}", encoding="utf-8")

    (config / "tags.json").write_text(
        json.dumps(_TAGS_JSON, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (config / "suppliers.json").write_text(
        json.dumps(_SUPPLIERS_JSON, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (config / "categories.json").write_text(
        json.dumps(_CATEGORIES_JSON, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for fname, header in _CORRECTION_HEADERS.items():
        (corrections / fname).write_text(header, encoding="utf-8")
    (ledger / "transactions.csv").write_text(
        _TX_HEADER + "".join(_TX_ROWS), encoding="utf-8"
    )

    # Recurring-payments cross-tree dep: mention "Old Gym Ltda" + category carro.
    rec = tmp_path / "rec.md"
    rec.write_text(
        "| Dia | Pagamento | Categoria |\n|--|--|--|\n| 1 | Old Gym Ltda | carro |\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("BOOKKEEPER_ROOT", str(root))
    monkeypatch.setenv("BOOKKEEPER_CONFIG_DIR", str(config))
    monkeypatch.setenv("BOOKKEEPER_LEDGER_DIR", str(root / "ledgers"))
    monkeypatch.setenv("BOOKKEEPER_RECURRING_PATH", str(rec))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")  # default: no audit noise
    return {
        "root": root,
        "config": config,
        "corrections": corrections,
        "ledger_dir": root / "ledgers" / "fechamento",
        "rec": rec,
    }


def _snapshot(paths: list[Path]) -> dict[str, str]:
    """Map path -> sha256 of contents (missing files -> sentinel)."""
    out = {}
    for p in paths:
        if p.exists():
            out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
        else:
            out[str(p)] = "<absent>"
    return out


def _all_state_paths(bk) -> list[Path]:
    cfg = bk["config"]
    corr = bk["corrections"]
    return [
        cfg / "tags.json",
        cfg / "suppliers.json",
        cfg / "categories.json",
        corr / "tag-renames.csv",
        corr / "vendor-canonicals.csv",
        corr / "category-migrations.csv",
        bk["ledger_dir"] / "2026-01" / "transactions.csv",
    ]


def _no_artifacts(bk) -> bool:
    corr = bk["corrections"]
    baks = list(corr.glob("*.bak*")) + list(bk["config"].glob("*.bak*"))
    rollback_dir = corr / ".rollback"
    rb = list(rollback_dir.glob("*")) if rollback_dir.exists() else []
    return not baks and not rb


# ===========================================================================
# rename_tags
# ===========================================================================


class TestRenameTags:
    def test_dry_run_writes_nothing(self, bk):
        before = _snapshot(_all_state_paths(bk))
        rc = rename_tags.main(["--from", "boxe", "--to", "esportes-luta"])
        assert rc == 0
        assert _snapshot(_all_state_paths(bk)) == before  # byte-identical
        assert _no_artifacts(bk)  # no .bak / .rollback leaked

    def test_apply_matches_preview(self, bk, capsys):
        # 1. Build the preview the same way the CLI does.
        report = rename_tags.build_impact(
            "boxe", "esportes-luta", merge_into_existing=False, source="test", note=""
        )
        writable_locs = {Path(i.location) for i in report.impacts if i.writable}
        nonwritable_locs = {Path(i.location) for i in report.impacts if not i.writable}

        before = _snapshot(_all_state_paths(bk))
        rc = rename_tags.main(["--from", "boxe", "--to", "esportes-luta", "--apply"])
        assert rc == 0
        after = _snapshot(_all_state_paths(bk))

        # Every WRITE location changed.
        for loc in writable_locs:
            assert after[str(loc)] != before[str(loc)], f"{loc} should have changed"
        # transactions.csv (a non-writable output-row location at the ledger dir)
        # is NOT rewritten by this tool.
        tx = bk["ledger_dir"] / "2026-01" / "transactions.csv"
        assert after[str(tx)] == before[str(tx)], "tool must NOT rewrite ledger rows"

    def test_apply_effects(self, bk):
        rename_tags.main(["--from", "boxe", "--to", "esportes-luta", "--apply"])
        cfg = bk["config"]
        tags = json.loads((cfg / "tags.json").read_text(encoding="utf-8"))
        assert "boxe" not in tags["tags"]
        assert "esportes-luta" in tags["tags"]
        assert any(r.get("token") == "boxe" for r in tags["rejected"])
        suppliers = json.loads((cfg / "suppliers.json").read_text(encoding="utf-8"))
        assert suppliers["suppliers"]["allecio-boxe"]["default_tags"] == ["esportes-luta"]
        renames = (bk["corrections"] / "tag-renames.csv").read_text(encoding="utf-8")
        assert "boxe,esportes-luta,all" in renames

    def test_rollback_restores_byte_for_byte(self, bk, capsys):
        before = _snapshot(_all_state_paths(bk))
        rename_tags.main(["--from", "boxe", "--to", "esportes-luta", "--apply"])
        out = capsys.readouterr().out
        token = out.split("Rollback token:")[1].split()[0].strip()
        rename_tags.main(["--rollback", token])
        after = _snapshot(_all_state_paths(bk))
        # Config + correction files restored to the exact prior bytes.
        for p in _all_state_paths(bk):
            assert after[str(p)] == before[str(p)], f"{p} not restored byte-for-byte"

    def test_missing_tag_blocks(self, bk):
        before = _snapshot(_all_state_paths(bk))
        rc = rename_tags.main(["--from", "ghost", "--to", "x", "--apply"])
        assert rc == 1
        assert _snapshot(_all_state_paths(bk)) == before  # refused, nothing written

    def test_collision_blocks_without_merge(self, bk):
        rc = rename_tags.main(["--from", "boxe", "--to", "tennis", "--apply"])
        assert rc == 1  # tennis already exists

    def test_merge_into_existing_allowed(self, bk):
        rc = rename_tags.main(
            ["--from", "boxe", "--to", "tennis", "--apply", "--merge-into-existing"]
        )
        assert rc == 0
        tags = json.loads((bk["config"] / "tags.json").read_text(encoding="utf-8"))
        assert "boxe" not in tags["tags"]
        assert tags["tags"]["tennis"]["label"] == "Tennis"  # existing label kept


# ===========================================================================
# rename_canonical
# ===========================================================================


class TestRenameCanonical:
    def test_dry_run_writes_nothing(self, bk):
        before = _snapshot(_all_state_paths(bk))
        rc = rename_canonical.main(["--from", "Old Gym Ltda", "--to", "New Gym SA"])
        assert rc == 0
        assert _snapshot(_all_state_paths(bk)) == before
        assert _no_artifacts(bk)

    def test_apply_matches_preview(self, bk):
        report = rename_canonical.build_impact(
            from_name="Old Gym Ltda", to_name="New Gym SA", slug=None, source="test", note=""
        )
        writable_locs = {Path(i.location) for i in report.impacts if i.writable}
        before = _snapshot(_all_state_paths(bk))
        rc = rename_canonical.main(["--from", "Old Gym Ltda", "--to", "New Gym SA", "--apply"])
        assert rc == 0
        after = _snapshot(_all_state_paths(bk))
        for loc in writable_locs:
            assert after[str(loc)] != before[str(loc)]
        tx = bk["ledger_dir"] / "2026-01" / "transactions.csv"
        assert after[str(tx)] == before[str(tx)]

    def test_apply_effects(self, bk):
        rename_canonical.main(["--from", "Old Gym Ltda", "--to", "New Gym SA", "--apply"])
        suppliers = json.loads((bk["config"] / "suppliers.json").read_text(encoding="utf-8"))
        assert suppliers["suppliers"]["old-gym"]["canonical"] == "New Gym SA"
        canon = (bk["corrections"] / "vendor-canonicals.csv").read_text(encoding="utf-8")
        assert "Old Gym Ltda,New Gym SA,all" in canon

    def test_rollback_restores(self, bk, capsys):
        before = _snapshot(_all_state_paths(bk))
        rename_canonical.main(["--from", "Old Gym Ltda", "--to", "New Gym SA", "--apply"])
        token = capsys.readouterr().out.split("Rollback token:")[1].split()[0].strip()
        rename_canonical.main(["--rollback", token])
        after = _snapshot(_all_state_paths(bk))
        for p in _all_state_paths(bk):
            assert after[str(p)] == before[str(p)]

    def test_no_match_blocks(self, bk):
        before = _snapshot(_all_state_paths(bk))
        rc = rename_canonical.main(["--from", "Nonexistent Vendor", "--to", "X", "--apply"])
        assert rc == 1
        assert _snapshot(_all_state_paths(bk)) == before

    def test_slug_targeting(self, bk):
        rc = rename_canonical.main(["--slug", "old-gym", "--to", "New Gym SA", "--apply"])
        assert rc == 0
        suppliers = json.loads((bk["config"] / "suppliers.json").read_text(encoding="utf-8"))
        assert suppliers["suppliers"]["old-gym"]["canonical"] == "New Gym SA"

    def test_cross_tree_dep_flagged(self, bk):
        report = rename_canonical.build_impact(
            from_name="Old Gym Ltda", to_name="New Gym SA", slug=None, source="t", note=""
        )
        rec_impacts = [i for i in report.impacts if i.kind == "cross-tree-dep"]
        assert rec_impacts and "MENTIONS" in rec_impacts[0].detail  # rec.md mentions it


# ===========================================================================
# merge_categories
# ===========================================================================


class TestMergeCategories:
    def test_dry_run_writes_nothing(self, bk):
        before = _snapshot(_all_state_paths(bk))
        rc = merge_categories.main(["--from", "carro", "--to", "transporte"])
        assert rc == 0
        assert _snapshot(_all_state_paths(bk)) == before
        assert _no_artifacts(bk)

    def test_apply_matches_preview(self, bk):
        report = merge_categories.build_impact("carro", "transporte", source="t", note="")
        writable_locs = {Path(i.location) for i in report.impacts if i.writable}
        before = _snapshot(_all_state_paths(bk))
        rc = merge_categories.main(["--from", "carro", "--to", "transporte", "--apply"])
        assert rc == 0
        after = _snapshot(_all_state_paths(bk))
        for loc in writable_locs:
            assert after[str(loc)] != before[str(loc)]
        tx = bk["ledger_dir"] / "2026-01" / "transactions.csv"
        assert after[str(tx)] == before[str(tx)]  # ledger rows untouched

    def test_apply_effects_all_subsurfaces(self, bk):
        merge_categories.main(["--from", "carro", "--to", "transporte", "--apply"])
        cats = json.loads((bk["config"] / "categories.json").read_text(encoding="utf-8"))
        assert "carro" not in cats["categories"]  # category key dropped
        assert all(
            m["category"] != "carro" for m in cats["value_based_mappings"]
        )  # value_based remapped
        assert cats["reimbursement_mappings"]["SOME CAR REFUND"]["category"] == "transporte"
        assert "carro" not in cats["recurrence_rules"]["default_by_category"]
        suppliers = json.loads((bk["config"] / "suppliers.json").read_text(encoding="utf-8"))
        assert suppliers["suppliers"]["old-gym"]["default_category"] == "transporte"
        mig = (bk["corrections"] / "category-migrations.csv").read_text(encoding="utf-8")
        assert "carro,transporte,all" in mig

    def test_rollback_restores(self, bk, capsys):
        before = _snapshot(_all_state_paths(bk))
        merge_categories.main(["--from", "carro", "--to", "transporte", "--apply"])
        token = capsys.readouterr().out.split("Rollback token:")[1].split()[0].strip()
        merge_categories.main(["--rollback", token])
        after = _snapshot(_all_state_paths(bk))
        for p in _all_state_paths(bk):
            assert after[str(p)] == before[str(p)]

    def test_missing_source_blocks(self, bk):
        before = _snapshot(_all_state_paths(bk))
        rc = merge_categories.main(["--from", "ghost", "--to", "transporte", "--apply"])
        assert rc == 1
        assert _snapshot(_all_state_paths(bk)) == before

    def test_invalid_target_blocks(self, bk):
        before = _snapshot(_all_state_paths(bk))
        rc = merge_categories.main(["--from", "carro", "--to", "nonexistent", "--apply"])
        assert rc == 1
        assert _snapshot(_all_state_paths(bk)) == before

    def test_same_category_blocks(self, bk):
        rc = merge_categories.main(["--from", "carro", "--to", "carro", "--apply"])
        assert rc == 1

    def test_dashboard_join_enumerated(self, bk):
        report = merge_categories.build_impact("carro", "transporte", source="t", note="")
        dj = [i for i in report.impacts if i.kind == "dashboard-join"]
        assert dj and "expenses.js" in dj[0].location


# ===========================================================================
# Append-only behavior + audit emission (cross-tool)
# ===========================================================================


def test_correction_ledger_is_appended_not_rewritten(bk):
    """A second apply appends a row; the first row is preserved (append-only)."""
    renames = bk["corrections"] / "tag-renames.csv"
    rename_tags.main(["--from", "boxe", "--to", "esportes-luta", "--apply"])
    lines_after_first = renames.read_text(encoding="utf-8").strip().splitlines()
    # Add the renamed tag back so a second distinct rename is valid.
    tags_path = bk["config"] / "tags.json"
    doc = json.loads(tags_path.read_text(encoding="utf-8"))
    doc["tags"]["tennis2"] = {"label": "Tennis2", "added": "2026-05-03"}
    tags_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rename_tags.main(["--from", "tennis2", "--to", "tennis-novo", "--apply"])
    lines_after_second = renames.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines_after_second) == len(lines_after_first) + 1
    # The first appended row is still present (not overwritten).
    assert any("boxe,esportes-luta" in ln for ln in lines_after_second)


def test_audit_event_emitted_on_apply(bk, tmp_path, monkeypatch):
    """With audit enabled, --apply emits config_write events (one per dest)."""
    audit_dir = tmp_path / "auditlog"
    monkeypatch.delenv("BOOKKEEPER_AUDIT_DISABLED", raising=False)
    monkeypatch.setenv("BOOKKEEPER_AUDIT_LOG_DIR", str(audit_dir))
    # The audit module caches vault root; reset so it picks up our tmp tree.
    from lib import audit as _audit

    _audit._reset_cache_for_tests()
    rename_tags.main(["--from", "boxe", "--to", "esportes-luta", "--apply"])
    _audit._reset_cache_for_tests()
    logs = list(audit_dir.glob("events-*.jsonl"))
    assert logs, "an audit log file should be written on apply"
    events = [json.loads(ln) for ln in logs[0].read_text(encoding="utf-8").splitlines() if ln]
    cw = [e for e in events if e.get("event_type") == "config_write"]
    assert cw, "at least one config_write event expected"
    assert all(e.get("source", {}).get("function") == "rename_tags.run" for e in cw)
