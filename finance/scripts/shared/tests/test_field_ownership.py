"""Tests for the field-ownership loader + write-permission gate (`lib.field_ownership`).

Spec: p1-21 task — `1-projects/finance-system/finance-system-v2-foundation/phase-1/p1-21.task.md`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lib import field_ownership
from lib.field_ownership import (
    FieldOwnershipError,
    assert_known_fields,
    can_write,
    load_field_ownership,
)


VALID_YAML = """
_meta:
  schema_version: 1
  manifest_version: "1.0"
  primary_key: id
fields:
  name:
    class: curated
  asset_class:
    class: derived
  indexer:
    class: source_bound
    owners: [safra_titulos]
  application_date:
    class: source_bound
    owners: [safra_titulos, safra_rf_movimentacoes]
"""


def _write_manifest(tmp_path: Path, body: str) -> Path:
    config = tmp_path / "config"
    config.mkdir()
    (config / "_field_ownership.yaml").write_text(body, encoding="utf-8")
    return config


def _audit_dir() -> Path:
    return Path(os.environ["BOOKKEEPER_AUDIT_LOG_DIR"])


def _read_events() -> list[dict]:
    audit_dir = _audit_dir()
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


# ---- Loader -----------------------------------------------------------------


def test_load_returns_expected_manifest(tmp_path):
    config = _write_manifest(tmp_path, VALID_YAML)
    data = load_field_ownership(config)
    assert data["_meta"]["manifest_version"] == "1.0"
    assert data["fields"]["name"]["class"] == "curated"
    assert data["fields"]["application_date"]["owners"] == [
        "safra_titulos",
        "safra_rf_movimentacoes",
    ]


def test_missing_file_fails_loud(tmp_path):
    with pytest.raises(FieldOwnershipError, match="not found"):
        load_field_ownership(tmp_path / "nonexistent")


def test_missing_required_section_fails_loud(tmp_path):
    body = """
_meta:
  schema_version: 1
  manifest_version: "1.0"
"""
    config = _write_manifest(tmp_path, body)
    with pytest.raises(FieldOwnershipError, match="missing required sections"):
        load_field_ownership(config)


def test_unsupported_schema_version_fails_loud(tmp_path):
    body = """
_meta:
  schema_version: 99
  manifest_version: "1.0"
fields:
  name:
    class: curated
"""
    config = _write_manifest(tmp_path, body)
    with pytest.raises(FieldOwnershipError, match="schema_version"):
        load_field_ownership(config)


def test_unknown_class_fails_loud(tmp_path):
    body = """
_meta:
  schema_version: 1
  manifest_version: "1.0"
fields:
  name:
    class: pretend_class
"""
    config = _write_manifest(tmp_path, body)
    with pytest.raises(FieldOwnershipError, match="unknown class"):
        load_field_ownership(config)


def test_source_bound_without_owners_fails_loud(tmp_path):
    body = """
_meta:
  schema_version: 1
  manifest_version: "1.0"
fields:
  indexer:
    class: source_bound
"""
    config = _write_manifest(tmp_path, body)
    with pytest.raises(FieldOwnershipError, match="non-empty `owners`"):
        load_field_ownership(config)


# ---- can_write --------------------------------------------------------------


def _manifest(tmp_path):
    return load_field_ownership(_write_manifest(tmp_path, VALID_YAML))


def test_curated_blocked_on_update(tmp_path):
    m = _manifest(tmp_path)
    assert can_write(m, "name", source_id="safra_titulos", is_insert=False) is False


def test_curated_allowed_on_insert(tmp_path):
    m = _manifest(tmp_path)
    assert can_write(m, "name", source_id="safra_titulos", is_insert=True) is True


def test_source_bound_allows_owner(tmp_path):
    m = _manifest(tmp_path)
    assert can_write(m, "indexer", source_id="safra_titulos", is_insert=False) is True


def test_source_bound_blocks_non_owner(tmp_path):
    m = _manifest(tmp_path)
    assert can_write(m, "indexer", source_id="safra_fundos", is_insert=False) is False


def test_source_bound_multi_owner(tmp_path):
    m = _manifest(tmp_path)
    assert can_write(m, "application_date", source_id="safra_rf_movimentacoes", is_insert=False) is True
    assert can_write(m, "application_date", source_id="b3", is_insert=False) is False


def test_derived_always_writable(tmp_path):
    m = _manifest(tmp_path)
    assert can_write(m, "asset_class", source_id="anyone", is_insert=False) is True


def test_primary_key_always_writable(tmp_path):
    m = _manifest(tmp_path)
    assert can_write(m, "id", source_id="anyone", is_insert=False) is True


def test_unknown_field_emits_event_and_raises(tmp_path):
    m = _manifest(tmp_path)
    with pytest.raises(FieldOwnershipError, match="not classified"):
        can_write(m, "ghost_field", source_id="safra_titulos", is_insert=False)
    events = [e for e in _read_events() if e["event_type"] == "field_ownership_unknown"]
    assert len(events) == 1
    assert events[0]["trigger_context"]["field"] == "ghost_field"


# ---- assert_known_fields ----------------------------------------------------


def test_assert_known_passes_for_classified(tmp_path):
    m = _manifest(tmp_path)
    assert_known_fields(m, ["name", "asset_class", "id"])
    assert _read_events() == []


def test_assert_known_emits_one_event_for_batch(tmp_path):
    m = _manifest(tmp_path)
    with pytest.raises(FieldOwnershipError, match="unknown fields"):
        assert_known_fields(m, ["name", "ghost_a", "ghost_b"])
    events = [e for e in _read_events() if e["event_type"] == "field_ownership_unknown"]
    assert len(events) == 1
    assert events[0]["trigger_context"]["unknown_fields"] == ["ghost_a", "ghost_b"]


# ---- Real vault sanity check ------------------------------------------------


def test_real_vault_manifest_loads():
    """Sanity: the real `.user/finance/bookkeeper/config/_field_ownership.yaml`
    parses + validates against the loader."""
    vault_root = Path(__file__).resolve().parents[7]
    real_yaml = (
        vault_root
        / ".user"
        / "finance"
        / "bookkeeper"
        / "config"
        / "_field_ownership.yaml"
    )
    if not real_yaml.exists():
        pytest.skip("Real _field_ownership.yaml not present (running outside vault).")
    data = load_field_ownership(real_yaml.parent)
    assert data["_meta"]["schema_version"] == 1
    assert "name" in data["fields"]
    assert data["fields"]["name"]["class"] == "curated"


# ---- KLABIN regression replay ----------------------------------------------


def test_klabin_regression_blocked(tmp_path):
    """The original bug: a parser with a partial/different value overwrites
    the curated `name` (and `issuer`). With the manifest in place, neither
    write is allowed on update."""
    m = _manifest(tmp_path)
    assert can_write(m, "name", source_id="b3", is_insert=False) is False
    assert can_write(m, "name", source_id="safra_titulos", is_insert=False) is False
