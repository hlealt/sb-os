"""Regression tests for p5-4: the tool-builder companion.

The companion (`finance/workflows/tool-builder/tool-builder.md`) is a
markdown-step sub-agent workflow; its two MECHANIZED, enforceable contracts are
the schema-conformance primitive and the schema-gap dual-surfacing — both in
`lib.tool_schema_check`, the substrate every generated `write` tool's
schema-validation test calls. These tests prove the two flag-worthy behaviors:

  1. Authority boundary — the schema-conformance / dual-surfacing primitives
     write NOTHING: `destination_schema` is read-only, `surface_schema_gap`
     only emits an audit event + returns text. A gap is never silently
     flattened (it is named in both surfaces) and never unilaterally migrated
     (no store is mutated).
  2. Schema-gap surfacing path — a gap dual-surfaces (a user-facing prompt AND a
     `schema_gap_finding` audit event), not a silent flatten/mutate.

Plus a doc-contract check on the workflow file (the binding authority-boundary
and schema-gap clauses are present, and the companion is dispatch-callable from
a sibling).

Audit isolation is provided by conftest.py's autouse `_isolate_audit` fixture
(points lib.audit at a tmp vault + tmp log dir). `lib` is importable via
conftest's sys.path insert.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from lib import audit
from lib import tool_schema_check as tsc
from lib.tool_schema_check import (
    SCHEMA_GAP_EVENT_TYPE,
    SchemaGapError,
    assert_conforms,
    conformance_gap,
    destination_schema,
    gap_prompt,
    surface_schema_gap,
)


# Repo paths (vault-root-independent: derived from this test file).
_TESTS_DIR = Path(__file__).resolve().parent
_FINANCE_DIR = _TESTS_DIR.parents[2]  # scripts/shared/tests -> finance/
_WORKFLOW_FILE = _FINANCE_DIR / "workflows" / "tool-builder" / "tool-builder.md"


def _read_events() -> list[dict]:
    audit_dir = Path(os.environ["BOOKKEEPER_AUDIT_LOG_DIR"])
    if not audit_dir.exists():
        return []
    out: list[dict] = []
    for p in sorted(audit_dir.glob("events-*.jsonl")):
        out.extend(
            json.loads(line)
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return out


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ===========================================================================
# destination_schema — read-only field-set resolution
# ===========================================================================


class TestDestinationSchema:
    def test_csv_header_is_the_schema(self, tmp_path):
        dest = tmp_path / "balcao.csv"
        dest.write_text(
            "product_id,date,operation,amount,source\n"
            "cra_x,2026-01-01,aplicacao,100.0,safra\n",
            encoding="utf-8",
        )
        assert destination_schema(dest) == {
            "product_id",
            "date",
            "operation",
            "amount",
            "source",
        }

    def test_json_object_top_level_keys(self, tmp_path):
        dest = tmp_path / "portfolio.json"
        dest.write_text(
            json.dumps({"positions": [], "meta": {}, "totals": {}}),
            encoding="utf-8",
        )
        assert destination_schema(dest) == {"positions", "meta", "totals"}

    def test_json_array_of_objects_uses_record_keys(self, tmp_path):
        dest = tmp_path / "value_based.json"
        dest.write_text(
            json.dumps([{"vendor": "X", "amount": 100, "category": "carro"}]),
            encoding="utf-8",
        )
        assert destination_schema(dest) == {"vendor", "amount", "category"}

    def test_field_ownership_yaml_uses_classified_fields(self, tmp_path):
        config = tmp_path / "config"
        config.mkdir()
        (config / "_field_ownership.yaml").write_text(
            "_meta:\n"
            "  schema_version: 1\n"
            "  manifest_version: '1.0'\n"
            "  primary_key: id\n"
            "fields:\n"
            "  name:\n"
            "    class: curated\n"
            "  indexer:\n"
            "    class: source_bound\n"
            "    owners: [safra_titulos]\n",
            encoding="utf-8",
        )
        # primary_key (id) is folded in alongside the classified fields.
        assert destination_schema(config / "_field_ownership.yaml") == {
            "id",
            "name",
            "indexer",
        }

    def test_missing_artifact_fails_loud(self, tmp_path):
        with pytest.raises(SchemaGapError, match="does not exist"):
            destination_schema(tmp_path / "ghost.csv")

    def test_unsupported_suffix_fails_loud(self, tmp_path):
        dest = tmp_path / "notes.txt"
        dest.write_text("hello", encoding="utf-8")
        with pytest.raises(SchemaGapError, match="derivable field schema"):
            destination_schema(dest)

    def test_destination_schema_does_not_mutate_the_artifact(self, tmp_path):
        """Authority boundary: reading a schema never writes to the artifact."""
        dest = tmp_path / "assets.csv"
        dest.write_text("id,name,asset_class\ncra_x,Foo,rf\n", encoding="utf-8")
        before = _sha(dest)
        destination_schema(dest)
        assert _sha(dest) == before  # byte-for-byte unchanged


# ===========================================================================
# conformance_gap / assert_conforms — the schema-conformance default
# ===========================================================================


class TestConformance:
    def test_conforming_output_has_empty_gap(self):
        schema = {"product_id", "date", "amount"}
        assert conformance_gap({"product_id", "amount"}, schema) == set()

    def test_extra_field_is_a_gap(self):
        schema = {"product_id", "date", "amount"}
        assert conformance_gap(
            {"product_id", "amount", "settlement_date"}, schema
        ) == {"settlement_date"}

    def test_assert_conforms_passes_for_subset(self):
        assert_conforms({"a", "b"}, {"a", "b", "c"})  # no raise

    def test_assert_conforms_raises_on_gap(self):
        with pytest.raises(SchemaGapError, match="settlement_date"):
            assert_conforms(
                {"product_id", "settlement_date"},
                {"product_id", "date"},
                destination="balcao.csv",
            )

    def test_assert_conforms_does_not_emit_audit_event(self):
        """assert_conforms is the test-time hard assertion — surfacing (the
        audit event) is surface_schema_gap's job, not the assertion's."""
        with pytest.raises(SchemaGapError):
            assert_conforms({"x"}, {"y"})
        assert _read_events() == []

    def test_generated_write_tool_schema_validation_pattern(self, tmp_path):
        """The exact shape of a generated write tool's mandatory schema-
        validation test (tool-builder Step 5.1): derive the destination
        schema, then assert the tool's output fields conform."""
        dest = tmp_path / "balcao.csv"
        dest.write_text(
            "product_id,date,operation,amount,source\n", encoding="utf-8"
        )
        tool_output_fields = {"product_id", "date", "operation", "amount", "source"}
        # Passes — a conforming parser.
        assert_conforms(
            tool_output_fields, destination_schema(dest), destination=dest
        )


# ===========================================================================
# Schema-gap dual-surfacing — the load-bearing authority-boundary behavior
# ===========================================================================


class TestSchemaGapDualSurfacing:
    def test_prompt_names_field_and_three_options(self):
        prompt = gap_prompt({"settlement_date"}, "balcao.csv")
        assert "settlement_date" in prompt
        assert "balcao.csv" in prompt
        # The three options are present (extend / flatten / defer).
        assert "[E]" in prompt and "[F]" in prompt and "[J]" in prompt

    def test_surface_emits_schema_gap_finding_event(self):
        prompt = surface_schema_gap(
            {"settlement_date"}, "balcao.csv", tool_name="parse_newbroker"
        )
        events = [
            e for e in _read_events() if e["event_type"] == SCHEMA_GAP_EVENT_TYPE
        ]
        assert len(events) == 1
        ev = events[0]
        assert ev["trigger_context"]["tool"] == "parse_newbroker"
        assert ev["trigger_context"]["gap_fields"] == ["settlement_date"]
        assert ev["materiality"] == "high"
        # AND returns the user-facing prompt (the second surface).
        assert "settlement_date" in prompt

    def test_surface_returns_prompt_for_user(self):
        prompt = surface_schema_gap(
            {"fx_rate", "settlement_date"}, "orders.csv", tool_name="t"
        )
        # Both gap fields appear in the user-facing prompt (never silently dropped).
        assert "fx_rate" in prompt and "settlement_date" in prompt

    def test_surface_writes_nothing_to_destination(self, tmp_path):
        """Authority boundary: surfacing a gap NEVER mutates the destination —
        not flattened (fields reported), not migrated (no schema rewrite)."""
        dest = tmp_path / "balcao.csv"
        dest.write_text("product_id,date,amount\n", encoding="utf-8")
        before = _sha(dest)
        surface_schema_gap({"settlement_date"}, dest, tool_name="t")
        # Destination schema is unchanged: the field was NOT auto-added.
        assert _sha(dest) == before
        assert destination_schema(dest) == {"product_id", "date", "amount"}
        assert "settlement_date" not in destination_schema(dest)

    def test_surface_is_fail_soft_on_audit_write_failure(self, monkeypatch):
        """Dual-surfacing rides the best-effort audit protocol — a real
        audit-WRITE failure (e.g. disk full inside _write_event) is swallowed by
        audit.emit's never-raise contract, so the companion still returns the
        prompt. Matches the field_ownership precedent (direct emit, no guard)."""

        def _boom(*a, **k):
            raise OSError("disk full")

        # Fail the underlying write, not emit() itself — emit() wraps its body
        # in try/except and is contractually never-raising. This exercises the
        # realistic failure path the companion relies on.
        monkeypatch.setattr(audit, "_write_event", _boom)
        prompt = surface_schema_gap({"x"}, "balcao.csv", tool_name="t")
        assert "balcao.csv" in prompt  # user-facing surface still works
        # No event landed (the write failed) but nothing raised.
        assert [e for e in _read_events() if e["event_type"] == SCHEMA_GAP_EVENT_TYPE] == []


# ===========================================================================
# Workflow doc-contract — the companion's binding clauses
# ===========================================================================


class TestWorkflowDocContract:
    def test_workflow_file_exists(self):
        assert _WORKFLOW_FILE.exists(), f"missing {_WORKFLOW_FILE}"

    def test_authority_boundary_is_absolute_and_named(self):
        text = _WORKFLOW_FILE.read_text(encoding="utf-8").lower()
        assert "authority boundary" in text
        # Output is tools only; never writes ledgers / portfolio.json / dashboard.
        assert "tool code" in text or "output is tool" in text or "tools only" in text
        for forbidden in ("ledger", "portfolio.json", "dashboard"):
            assert forbidden in text, f"boundary must name {forbidden!r}"
        # An explicit refusal mechanism, not just a description.
        assert "refuse" in text

    def test_schema_gap_dual_surfacing_documented(self):
        text = _WORKFLOW_FILE.read_text(encoding="utf-8")
        assert "schema_gap_finding" in text
        lower = text.lower()
        assert "dual-surfac" in lower  # dual-surface / dual-surfacing
        # The two non-allowed silent paths are explicitly forbidden.
        assert "flatten" in lower and "migrat" in lower

    def test_runtime_is_sub_agent_batched_iteration(self):
        lower = _WORKFLOW_FILE.read_text(encoding="utf-8").lower()
        assert "sub-agent" in lower
        assert "agent tool" in lower
        assert "batched iteration" in lower or "batched-iteration" in lower
        # Explicitly NOT a sibling handoff and NOT one-shot.
        assert "one-shot" in lower

    def test_callable_from_bookkeeper_and_investor(self):
        lower = _WORKFLOW_FILE.read_text(encoding="utf-8").lower()
        assert "bookkeeper" in lower  # current caller
        assert "investor" in lower  # design-callable sibling
        assert "seam 1" in lower  # the gatekeeper-loop dispatch point

    def test_tools_index_registration_and_dry_run_required(self):
        lower = _WORKFLOW_FILE.read_text(encoding="utf-8").lower()
        assert "tools-index.md" in lower
        assert "--dry-run" in lower or "dry-run" in lower
        assert "schema-validation test" in lower
