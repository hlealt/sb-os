"""Tests for the `docs_potentially_stale` signal — layer 2 of the
documentation-currency mechanism (p5-10).

The signal fires when a structural write lands on a code/config surface that
the shared node-doc manifest couples to a doc. It carries
`{destination, node_id, doc_sections_at_risk}` (the payload doc-maintainer
clears) and MUST stay fail-soft (never raise into the caller).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lib import audit


_MANIFEST = """\
version: "1.0"
couplings:
  - node_id: expenses_schema_and_classifier
    code:
      - "scripts/shared/categorize.py"
      - ".user/finance/bookkeeper/config/categories.json"
    docs:
      - path: "docs/expenses-data.md"
        sections:
          - "Schema"
          - "Classifier"
  - node_id: tool_registry
    code:
      - "scripts/shared/gate_*.py"
    docs:
      - path: "scripts/tools-index.md"
        sections:
          - "Registered Tools"
"""


def _audit_dir() -> Path:
    return Path(os.environ["BOOKKEEPER_AUDIT_LOG_DIR"])


def _read_events() -> list[dict]:
    out: list[dict] = []
    audit_dir = _audit_dir()
    if not audit_dir.exists():
        return out
    for p in sorted(audit_dir.glob("events-*.jsonl")):
        out.extend(
            json.loads(line)
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return out


@pytest.fixture(autouse=True)
def _install_manifest(tmp_path, monkeypatch):
    """Write the test manifest and point the audit lookup at it."""
    manifest_path = tmp_path / "doc-currency-manifest.yaml"
    manifest_path.write_text(_MANIFEST, encoding="utf-8")
    monkeypatch.setenv("BOOKKEEPER_DOC_CURRENCY_MANIFEST", str(manifest_path))
    yield


def test_emits_for_coupled_finance_relative_surface():
    audit.emit_docs_potentially_stale(
        "3-resources/tools/sb-os/finance/scripts/shared/categorize.py",
        source_function="categorize.main",
    )
    events = _read_events()
    assert len(events) == 1
    e = events[0]
    assert e["event_type"] == "docs_potentially_stale"
    assert e["materiality"] == "high"
    assert e["destination"] == "3-resources/tools/sb-os/finance/scripts/shared/categorize.py"
    ctx = e["trigger_context"]
    assert ctx["node_id"] == "expenses_schema_and_classifier"
    assert "docs/expenses-data.md#Schema" in ctx["doc_sections_at_risk"]
    assert "docs/expenses-data.md#Classifier" in ctx["doc_sections_at_risk"]


def test_emits_for_coupled_user_config_surface():
    audit.emit_docs_potentially_stale(
        ".user/finance/bookkeeper/config/categories.json",
        source_function="bookkeeper.review",
    )
    events = _read_events()
    assert len(events) == 1
    assert events[0]["trigger_context"]["node_id"] == "expenses_schema_and_classifier"


def test_glob_pattern_matches():
    audit.emit_docs_potentially_stale(
        "3-resources/tools/sb-os/finance/scripts/shared/gate_coverage.py",
        source_function="t",
    )
    events = _read_events()
    assert len(events) == 1
    assert events[0]["trigger_context"]["node_id"] == "tool_registry"


def test_uncoupled_surface_emits_nothing():
    # A pipeline scratch file no manifest row couples to a doc.
    audit.emit_docs_potentially_stale(
        ".user/finance/bookkeeper/investimentos/tmp-processed/scratch.csv",
        source_function="t",
    )
    assert _read_events() == []


def test_caller_trigger_context_is_merged():
    audit.emit_docs_potentially_stale(
        "3-resources/tools/sb-os/finance/scripts/shared/categorize.py",
        source_function="t",
        trigger_context={"month": "2026-04"},
    )
    ctx = _read_events()[0]["trigger_context"]
    assert ctx["month"] == "2026-04"
    assert ctx["node_id"] == "expenses_schema_and_classifier"  # not clobbered


def test_missing_manifest_is_fail_soft(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "BOOKKEEPER_DOC_CURRENCY_MANIFEST", str(tmp_path / "does-not-exist.yaml")
    )
    # Must not raise and must emit nothing.
    audit.emit_docs_potentially_stale(
        "3-resources/tools/sb-os/finance/scripts/shared/categorize.py",
        source_function="t",
    )
    assert _read_events() == []


def test_malformed_manifest_is_fail_soft(monkeypatch, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("couplings: [this: is: not: valid", encoding="utf-8")
    monkeypatch.setenv("BOOKKEEPER_DOC_CURRENCY_MANIFEST", str(bad))
    # Malformed YAML must be swallowed (fail-soft), emit nothing, never raise.
    audit.emit_docs_potentially_stale(
        "3-resources/tools/sb-os/finance/scripts/shared/categorize.py",
        source_function="t",
    )
    assert _read_events() == []


def test_lookup_returns_couplings_directly():
    hits = audit.lookup_stale_docs(
        "3-resources/tools/sb-os/finance/scripts/shared/categorize.py"
    )
    assert len(hits) == 1
    assert hits[0]["node_id"] == "expenses_schema_and_classifier"


def test_emit_never_raises_even_if_emit_internals_break(monkeypatch):
    """The fail-soft invariant holds even if the underlying emit explodes."""

    def boom(*a, **k):
        raise RuntimeError("emit blew up")

    monkeypatch.setattr(audit, "emit", boom)
    # Should be swallowed, not propagated.
    audit.emit_docs_potentially_stale(
        "3-resources/tools/sb-os/finance/scripts/shared/categorize.py",
        source_function="t",
    )
