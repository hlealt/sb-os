"""Standing-rules loader + rule-fire instrumentation.

Spec: `1-projects/finance-system/finance-system-v2-foundation/phase-1/p1-20.task.md`.

Loads the declarative standing-rules registry from
`.user/finance/bookkeeper/config/standing-rules.yaml` and provides a small
helper for in-script consumers (categorize.py today; more later) to count
rule-fires per script run and emit a single summary `rule_fired` audit event
at the end. Per the audit-event protocol's "one event per (source_file,
destination_path) per script run" granularity choice, per-row events are
intentionally avoided.

Failure mode is fail-loud at startup (per Standing-rules Decision: "Confirm
the same close without the YAML (rename it temporarily) produces a clean
fail-loud (not silent fallback)."). After load, the instrumentation helper
itself is best-effort — never raises into the calling script.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from . import audit


REQUIRED_TOP_LEVEL_SECTIONS = {
    "_meta",
    "supplier_rules",
}

REQUIRED_META_FIELDS = {"schema_version", "rule_set_version"}

SUPPORTED_SCHEMA_VERSION = 1


class StandingRulesError(RuntimeError):
    """Raised when the standing-rules YAML is missing or malformed."""


def standing_rules_path(config_folder: Path | str) -> Path:
    """Canonical path to the rules file inside a bookkeeper config folder."""
    return Path(config_folder) / "standing-rules.yaml"


def load_standing_rules(config_folder: Path | str) -> dict[str, Any]:
    """Load + validate the declarative standing-rules registry.

    Raises `StandingRulesError` on any failure (missing file, parse error,
    missing required section, unsupported schema version). Callers SHOULD
    let the exception propagate so the script halts loudly rather than
    silently degrading.
    """
    path = standing_rules_path(config_folder)
    if not path.exists():
        raise StandingRulesError(
            f"standing-rules.yaml not found at {path}. The categorizer "
            f"requires the declarative rules registry to run."
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise StandingRulesError(
            f"standing-rules.yaml at {path} failed to parse: {e}"
        ) from e

    if not isinstance(data, dict):
        raise StandingRulesError(
            f"standing-rules.yaml at {path} must be a YAML mapping at the top level"
        )

    missing = REQUIRED_TOP_LEVEL_SECTIONS - data.keys()
    if missing:
        raise StandingRulesError(
            f"standing-rules.yaml missing required sections: {sorted(missing)}"
        )

    meta = data.get("_meta") or {}
    if not isinstance(meta, dict):
        raise StandingRulesError("standing-rules.yaml `_meta` must be a mapping")
    missing_meta = REQUIRED_META_FIELDS - meta.keys()
    if missing_meta:
        raise StandingRulesError(
            f"standing-rules.yaml `_meta` missing fields: {sorted(missing_meta)}"
        )
    if meta.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise StandingRulesError(
            f"standing-rules.yaml schema_version "
            f"{meta.get('schema_version')!r} unsupported; expected "
            f"{SUPPORTED_SCHEMA_VERSION}"
        )

    return data


def count_active_rules(rules: dict[str, Any]) -> int:
    """Count top-level rule sections marked `status: active`."""
    n = 0
    for key, value in rules.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and value.get("status") == "active":
            n += 1
    return n


class RuleFireCounter:
    """Aggregator for rule fires across a script run.

    Per-row instrumentation calls `record(...)`. At the end of the run, the
    consumer calls `emit_summary(...)` to produce a single `rule_fired`
    audit event with the aggregated counts.
    """

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._rows_seen: int = 0

    def record(self, rule_name: str) -> None:
        self._counts[rule_name] += 1

    def observe_row(self) -> None:
        self._rows_seen += 1

    @property
    def total_fires(self) -> int:
        return sum(self._counts.values())

    @property
    def rows_seen(self) -> int:
        return self._rows_seen

    def as_dict(self) -> dict[str, int]:
        return dict(self._counts)

    def emit_summary(
        self,
        *,
        source_function: str,
        rule_set_version: str | None = None,
        trigger_context: dict[str, Any] | None = None,
    ) -> None:
        """Emit one `rule_fired` audit event with the aggregated counts.

        Skips emission when no rules fired (no signal worth a log line).
        """
        if not self._counts:
            return
        summary: dict[str, Any] = {
            "rows_seen": self._rows_seen,
            "total_fires": self.total_fires,
            "fires_by_rule": dict(self._counts),
        }
        if rule_set_version is not None:
            summary["rule_set_version"] = rule_set_version
        audit.emit(
            "rule_fired",
            source_function=source_function,
            summary=summary,
            trigger_context=trigger_context,
        )
