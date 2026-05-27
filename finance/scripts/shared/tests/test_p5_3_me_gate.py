"""Tests for the structural non-overlap (ME) semantic gate — p5-3.

The gate fires on any data-store/config/dashboard-script edit and detects, at
the SEMANTIC level (does this data already exist elsewhere?), whether the edit
overlaps one of the 23 p2-7 canonical stores. Two task-mandated cases:
  - a second store for an already-tracked concept (new vendor->category dict)
    is caught and surfaced (REFUSE / exit 1);
  - a genuinely new concept passes (exit 0).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import me_gate
from lib import source_of_truth_registry as registry


# ---------------------------------------------------------------------------
# Registry — the 23-domain p2-7 transcription
# ---------------------------------------------------------------------------


def test_registry_has_all_23_domains():
    """p2-7 §1.1–§1.23 = 23 data domains. The registry transcribes all of them."""
    assert len(registry.all_entries()) == 23


def test_every_entry_cites_a_p2_7_section_and_canonical():
    for entry in registry.all_entries():
        assert entry.section, f"{entry.concept} missing p2-7 section provenance"
        assert entry.canonical, f"{entry.concept} missing canonical store"
        assert entry.concept


def test_concepts_are_unique():
    concepts = [e.concept for e in registry.all_entries()]
    assert len(concepts) == len(set(concepts))


# ---------------------------------------------------------------------------
# find_overlaps — semantic lookup
# ---------------------------------------------------------------------------


def test_vendor_category_dict_overlaps_suppliers_default_category():
    """A new vendor->category dict overlaps suppliers.json::default_category (p2-7 §1.1)."""
    hits = registry.find_overlaps("a new vendor to category dict")
    assert hits
    sections = {h.section for h in hits}
    assert "1.1" in sections


def test_default_category_keyword_matches():
    hits = registry.find_overlaps("storing default_category per vendor")
    assert any(h.section == "1.1" for h in hits)


def test_genuinely_new_concept_has_no_overlap():
    """A concept none of the 23 domains cover returns no overlap."""
    hits = registry.find_overlaps(
        "monthly carbon-footprint estimate per transaction"
    )
    assert hits == []


def test_separator_insensitive_matching():
    """'value-based', 'value_based', 'Value Based' all match the same entry."""
    for phrase in ("value-based category rules", "value_based mappings", "Value Based overrides"):
        hits = registry.find_overlaps(phrase)
        assert any(h.section == "1.2" for h in hits), phrase


def test_extra_terms_contribute_to_match():
    """A vague concept + a telling config key still matches via extra_terms."""
    hits = registry.find_overlaps("a small lookup table", extra_terms=["tags.json"])
    assert any(h.section == "1.20" for h in hits)


def test_target_basename_only_no_false_positive_from_path():
    """A new, unrelated store whose PATH happens to live near config/ does not
    match purely on directory noise — the concept drives the match."""
    result = me_gate.evaluate(
        "weekly mood score",
        target="config/wellbeing/mood.csv",
    )
    assert result.passed
    assert result.overlaps == []


# ---------------------------------------------------------------------------
# evaluate() — the gate's decision
# ---------------------------------------------------------------------------


def test_evaluate_refuses_overlapping_concept():
    result = me_gate.evaluate(
        "new vendor to category dict",
        store_name="vendor_categories",
    )
    assert result.passed is False
    assert any(e.section == "1.1" for e in result.overlaps)


def test_evaluate_passes_new_concept():
    result = me_gate.evaluate("per-merchant loyalty-points balance")
    assert result.passed is True
    assert result.overlaps == []


def test_evaluate_second_tag_store_is_caught():
    """Adding a parallel tag store overlaps tags.json (p2-7 §1.20)."""
    result = me_gate.evaluate(
        "a second tag vocabulary file",
        target="config/extra_tags.json",
        store_name="tag list",
    )
    assert result.passed is False
    assert any(e.section == "1.20" for e in result.overlaps)


def test_evaluate_portfolio_duplicate_is_caught():
    result = me_gate.evaluate(
        "a parallel computed positions snapshot",
        target="ledgers/investimentos/portfolio.json",
    )
    assert result.passed is False
    assert any(e.section == "1.13" for e in result.overlaps)


# ---------------------------------------------------------------------------
# Tertiary cross-config net — graceful "not-yet-built" fallback
# ---------------------------------------------------------------------------


def test_tertiary_net_absent_does_not_block(monkeypatch):
    """The deferred audit-data-duplication.py is not importable; the gate runs
    on the primary registry check alone and reports the net as unavailable."""
    # Ensure the module is genuinely absent (it is deferred — plan p5-12).
    monkeypatch.setitem(sys.modules, "audit_data_duplication", None)
    result = me_gate.evaluate("new vendor to category dict")
    # Primary check still decides — overlap is still caught.
    assert result.passed is False
    assert result.tertiary_net_available is False
    assert result.tertiary_net_hits == []


def test_tertiary_net_absent_new_concept_still_passes(monkeypatch):
    monkeypatch.setitem(sys.modules, "audit_data_duplication", None)
    result = me_gate.evaluate("annual travel-miles accrual")
    assert result.passed is True
    assert result.tertiary_net_available is False


def test_tertiary_net_present_is_composed(monkeypatch):
    """When the net exists and flags duplicates, the gate surfaces them as a
    secondary confirmation (without changing the primary pass/refuse outcome)."""
    import types

    fake = types.ModuleType("audit_data_duplication")

    def find_cross_config_duplicates(concept, target):  # noqa: ARG001
        return ["categories.json::x mirrors suppliers.json::y"]

    fake.find_cross_config_duplicates = find_cross_config_duplicates
    monkeypatch.setitem(sys.modules, "audit_data_duplication", fake)

    result = me_gate.evaluate("brand-new concept with no registry overlap")
    assert result.tertiary_net_available is True
    assert result.tertiary_net_hits == ["categories.json::x mirrors suppliers.json::y"]


def test_tertiary_net_buggy_does_not_break_gate(monkeypatch):
    """A net that raises must not break the gate (best-effort)."""
    import types

    fake = types.ModuleType("audit_data_duplication")

    def find_cross_config_duplicates(concept, target):  # noqa: ARG001
        raise RuntimeError("net exploded")

    fake.find_cross_config_duplicates = find_cross_config_duplicates
    monkeypatch.setitem(sys.modules, "audit_data_duplication", fake)

    result = me_gate.evaluate("new vendor to category dict")
    assert result.tertiary_net_available is True
    assert result.tertiary_net_hits == []
    assert result.passed is False  # primary check unaffected


# ---------------------------------------------------------------------------
# main() — CLI exit codes
# ---------------------------------------------------------------------------


def test_main_refuse_exit_1_on_overlap(monkeypatch, capsys):
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "me_gate.py",
        "--concept", "new vendor to category dict",
    ])
    assert me_gate.main() == 1
    err = capsys.readouterr().err
    # Surfaces the three named options (reuse / justify-new / consolidate).
    assert "[R]" in err and "[J]" in err and "[C]" in err
    assert "p2-7" in err


def test_main_pass_exit_0_on_new_concept(monkeypatch, capsys):
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "me_gate.py",
        "--concept", "per-merchant loyalty points balance",
    ])
    assert me_gate.main() == 0
    out = capsys.readouterr().out
    assert "PASS" in out


def test_main_requires_concept_or_manifest(monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", ["me_gate.py"])
    assert me_gate.main() == 2


def test_main_keys_flag_is_an_overlap_signal(monkeypatch):
    """A vague concept + a telling --keys value is still caught."""
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "me_gate.py",
        "--concept", "a small new lookup",
        "--keys", "reimbursement_mappings,reembolso",
    ])
    assert me_gate.main() == 1


# ---------------------------------------------------------------------------
# Manifest sweep — pre-commit / quarterly surface
# ---------------------------------------------------------------------------


def test_manifest_sweep_flags_any_overlap(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    manifest = tmp_path / "proposed.json"
    manifest.write_text(json.dumps([
        {"concept": "annual carbon estimate"},               # new → ok
        {"concept": "another supplier registry file",
         "store_name": "suppliers"},                          # overlaps §1.19
    ]), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["me_gate.py", "--manifest", str(manifest)])
    assert me_gate.main() == 1


def test_manifest_sweep_all_new_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    manifest = tmp_path / "proposed.json"
    manifest.write_text(json.dumps([
        {"concept": "annual carbon estimate"},
        {"concept": "per-store loyalty points"},
    ]), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["me_gate.py", "--manifest", str(manifest)])
    assert me_gate.main() == 0


def test_manifest_missing_file_exit_2(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "me_gate.py", "--manifest", str(tmp_path / "nope.json"),
    ])
    assert me_gate.main() == 2


def test_manifest_entry_without_concept_exit_2(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    manifest = tmp_path / "bad.json"
    manifest.write_text(json.dumps([{"target": "x.csv"}]), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["me_gate.py", "--manifest", str(manifest)])
    assert me_gate.main() == 2


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------


def test_gate_fail_event_emitted_on_overlap(tmp_path, monkeypatch):
    import lib.audit as audit_mod
    audit_mod._reset_cache_for_tests()
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    monkeypatch.setenv("BOOKKEEPER_AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "0")
    monkeypatch.setattr(sys, "argv", [
        "me_gate.py", "--concept", "new vendor to category dict",
    ])
    assert me_gate.main() == 1
    files = list(audit_dir.glob("events-*.jsonl"))
    assert files
    events = [json.loads(l) for l in files[0].read_text(encoding="utf-8").splitlines() if l.strip()]
    fail = [e for e in events if e.get("event_type") == "gate_fail"]
    assert fail
    assert fail[0]["gate"]["name"] == "me_non_overlap"
    audit_mod._reset_cache_for_tests()


def test_gate_pass_event_emitted_on_new_concept(tmp_path, monkeypatch):
    import lib.audit as audit_mod
    audit_mod._reset_cache_for_tests()
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    monkeypatch.setenv("BOOKKEEPER_AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "0")
    monkeypatch.setattr(sys, "argv", [
        "me_gate.py", "--concept", "per-store loyalty points balance",
    ])
    assert me_gate.main() == 0
    files = list(audit_dir.glob("events-*.jsonl"))
    assert files
    events = [json.loads(l) for l in files[0].read_text(encoding="utf-8").splitlines() if l.strip()]
    passed = [e for e in events if e.get("event_type") == "gate_pass"]
    assert passed
    assert passed[0]["gate"]["name"] == "me_non_overlap"
    audit_mod._reset_cache_for_tests()
