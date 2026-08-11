"""Audit-event protocol — append-only JSONL log of finance pipeline writes.

Every ledger / config / state write performed by a finance script emits a
single structured event to a central log at
`{vault_root}/.user/finance/bookkeeper/audit/events-{YYYY}.jsonl`.

The protocol is best-effort observability — emission failures NEVER raise
into the calling script. Wrapped writes that fail propagate their own
exception unchanged; the audit helper simply skips emission on exception.
"""

from __future__ import annotations

import csv
import inspect
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_SCHEMA_VERSION = 1
_RUN_ID: str | None = None
_VAULT_ROOT: Path | None = None


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def _find_vault_root(start: Path | None = None) -> Path | None:
    """Walk up from `start` looking for `sb-os.json` (vault root marker)."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "sb-os.json").exists():
            return candidate
    return None


def _vault_root() -> Path | None:
    global _VAULT_ROOT
    if _VAULT_ROOT is None:
        _VAULT_ROOT = _find_vault_root()
    return _VAULT_ROOT


def _reset_cache_for_tests() -> None:
    """Test-only: reset module-level caches between cases."""
    global _RUN_ID, _VAULT_ROOT
    _RUN_ID = None
    _VAULT_ROOT = None


def get_run_id() -> str:
    """Return the run id for the current process (cached, env-aware)."""
    global _RUN_ID
    if _RUN_ID is None:
        env = os.environ.get("BOOKKEEPER_RUN_ID")
        _RUN_ID = env if env else str(uuid.uuid4())
    return _RUN_ID


def _actor() -> str:
    return os.environ.get("BOOKKEEPER_ACTOR") or "direct_cli"


def _vault_relative(p: Path | str) -> str:
    # A path that is already RELATIVE is vault-relative by this helper's
    # contract — return it as a clean POSIX string WITHOUT resolving it against
    # cwd (resolving a relative input would wrongly anchor it to the process's
    # working directory). Only absolute inputs (caller source filenames, ledger
    # destinations built from VAULT_ROOT) are made relative to the vault root.
    pp = Path(p)
    if not pp.is_absolute():
        return pp.as_posix()
    root = _vault_root()
    pp = pp.resolve()
    if root is None:
        return str(pp)
    try:
        return pp.relative_to(root).as_posix()
    except ValueError:
        return pp.as_posix()


def _log_path(ts: datetime) -> Path | None:
    root = _vault_root()
    if root is None:
        return None
    return (
        root
        / ".user"
        / "finance"
        / "bookkeeper"
        / "audit"
        / f"events-{ts.year}.jsonl"
    )


def _command_str() -> str:
    cmd = " ".join(sys.argv) if sys.argv else ""
    return cmd[:500]


def _resolve_source_file(depth: int = 2) -> str:
    """Vault-relative path of the caller's source file. `depth` counts
    stack frames above this helper (default 2 = caller of public API)."""
    try:
        frame = inspect.stack()[depth]
        return _vault_relative(frame.filename)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Summary computation
# ---------------------------------------------------------------------------


def _file_size(p: Path) -> int:
    try:
        return p.stat().st_size
    except FileNotFoundError:
        return 0
    except OSError:
        return 0


def _csv_row_count(p: Path) -> int | None:
    try:
        with open(p, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                next(reader)  # header
            except StopIteration:
                return 0
            return sum(1 for _ in reader)
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return None


def _json_summary(p: Path) -> dict[str, Any] | None:
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    out: dict[str, Any] = {}
    if isinstance(data, dict):
        out["top_level_keys"] = sorted(data.keys())[:50]
        out["key_count"] = len(data)
    elif isinstance(data, list):
        out["array_length"] = len(data)
    return out


def _capture_summary(dest: Path, kind: str) -> dict[str, Any]:
    """Snapshot of `dest` for before/after comparison.

    `kind` ∈ {"csv", "json", "auto"}. "auto" picks based on suffix.
    """
    if kind == "auto":
        kind = "csv" if dest.suffix.lower() == ".csv" else "json"
    snap: dict[str, Any] = {"bytes": _file_size(dest), "kind": kind}
    if kind == "csv":
        snap["rows"] = _csv_row_count(dest)
    else:
        snap["json"] = _json_summary(dest)
    return snap


def _summary_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "bytes_before": before.get("bytes", 0),
        "bytes_after": after.get("bytes", 0),
    }
    if before.get("kind") == "csv":
        rb = before.get("rows")
        ra = after.get("rows")
        if rb is not None:
            out["rows_before"] = rb
        if ra is not None:
            out["rows_after"] = ra
        if rb is not None and ra is not None:
            out["delta_rows"] = ra - rb
    else:
        jb = before.get("json") or {}
        ja = after.get("json") or {}
        if "key_count" in jb:
            out["key_count_before"] = jb["key_count"]
        if "key_count" in ja:
            out["key_count_after"] = ja["key_count"]
        if "array_length" in jb:
            out["array_length_before"] = jb["array_length"]
        if "array_length" in ja:
            out["array_length_after"] = ja["array_length"]
        if "top_level_keys" in ja:
            out["top_level_keys"] = ja["top_level_keys"]
    return out


# ---------------------------------------------------------------------------
# Core emit
# ---------------------------------------------------------------------------


def _write_event(event: dict[str, Any]) -> None:
    """Best-effort append. Never raises into the caller."""
    if os.environ.get("BOOKKEEPER_AUDIT_DISABLED") == "1":
        return
    try:
        ts = datetime.fromisoformat(event["ts"].replace("Z", "+00:00"))
    except Exception:
        ts = datetime.now(timezone.utc)
    log_dir_override = os.environ.get("BOOKKEEPER_AUDIT_LOG_DIR")
    if log_dir_override:
        path = Path(log_dir_override) / f"events-{ts.year}.jsonl"
    else:
        path = _log_path(ts)
    if path is None:
        print(
            "[audit] vault root not found; event dropped",
            file=sys.stderr,
        )
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[audit] failed to write event: {e}", file=sys.stderr)


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def emit(
    event_type: str,
    *,
    source_function: str,
    actor: str | None = None,
    destination: str | Path | None = None,
    action: str | None = None,
    materiality: str | None = None,
    summary: dict[str, Any] | None = None,
    trigger_context: dict[str, Any] | None = None,
    gate: dict[str, Any] | None = None,
    _stack_depth: int = 2,
) -> None:
    """Emit a single audit event. Best-effort; never raises."""
    try:
        event: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "ts": _now_iso(),
            "event_type": event_type,
            "actor": actor or _actor(),
            "run_id": get_run_id(),
            "source": {
                "file": _resolve_source_file(depth=_stack_depth),
                "function": source_function,
                "command": _command_str(),
            },
        }
        if destination is not None:
            event["destination"] = _vault_relative(destination)
        if action is not None:
            event["action"] = action
        if materiality is not None:
            event["materiality"] = materiality
        if summary is not None:
            event["summary"] = summary
        if trigger_context is not None:
            event["trigger_context"] = trigger_context
        if gate is not None:
            event["gate"] = gate
        _write_event(event)
    except Exception as e:  # never raise
        print(f"[audit] emit failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


@contextmanager
def track_write(
    destination: str | Path,
    *,
    materiality: str,
    action: str = "overwrite",
    event_type: str = "ledger_write",
    kind: str = "auto",
    source_function: str | None = None,
    actor: str | None = None,
    summary_extra: dict[str, Any] | None = None,
    trigger_context: dict[str, Any] | None = None,
) -> Iterator[None]:
    """Wrap a write block. Captures before/after; emits one event on success.

    On exception, NO event is emitted and the exception propagates.
    """
    dest = Path(destination)
    try:
        before = _capture_summary(dest, kind)
    except Exception:
        before = {"bytes": 0, "kind": kind}

    yield  # caller's write happens here

    try:
        after = _capture_summary(dest, kind)
        summary = _summary_diff(before, after)
        if summary_extra:
            summary.update(summary_extra)
        # Resolve caller function name if not given.
        fn = source_function
        if fn is None:
            try:
                fn = inspect.stack()[2].function
            except Exception:
                fn = ""
        emit(
            event_type,
            source_function=fn,
            actor=actor,
            destination=dest,
            action=action,
            materiality=materiality,
            summary=summary,
            trigger_context=trigger_context,
            _stack_depth=4,
        )
    except Exception as e:
        print(f"[audit] track_write post-emit failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Threshold / gate events
# ---------------------------------------------------------------------------


def emit_coverage(
    metric: str,
    value: float,
    *,
    source_function: str,
    threshold: float | None = None,
    trigger_context: dict[str, Any] | None = None,
) -> None:
    gate: dict[str, Any] = {"metric": metric, "value": value}
    if threshold is not None:
        gate["threshold"] = threshold
    emit(
        "coverage_progress",
        source_function=source_function,
        gate=gate,
        trigger_context=trigger_context,
        _stack_depth=3,
    )


def emit_gate(
    name: str,
    *,
    metric: str,
    value: float,
    threshold: float,
    passed: bool,
    source_function: str,
    trigger_context: dict[str, Any] | None = None,
) -> None:
    emit(
        "gate_pass" if passed else "gate_fail",
        source_function=source_function,
        gate={
            "name": name,
            "metric": metric,
            "value": value,
            "threshold": threshold,
            "passed": passed,
        },
        trigger_context=trigger_context,
        _stack_depth=3,
    )


# ---------------------------------------------------------------------------
# Documentation-currency signal (layer 2 of the Option D Hybrid mechanism)
# ---------------------------------------------------------------------------
#
# When a structural change (a write to a data store / config / dashboard-script
# surface) lands without a matching doc update, the pipeline emits a
# `docs_potentially_stale` event so the staleness is visible and persistent.
# The `doc-maintainer` companion CLEARS this signal by making the docs current
# (it never emits it). The coupling between code/config surfaces and the docs
# that describe them lives in the shared manifest
# `sb-os/finance/docs/doc-currency-manifest.yaml`.

_DOC_CURRENCY_MANIFEST_REL = "3-resources/tools/sb-os/finance/docs/doc-currency-manifest.yaml"
_FINANCE_PREFIX = "3-resources/tools/sb-os/finance/"


def _doc_currency_manifest_path() -> Path | None:
    """Resolve the shared node-doc manifest path, or None if unresolvable.

    Honors BOOKKEEPER_DOC_CURRENCY_MANIFEST for test isolation; otherwise
    resolves vault-relative to the vault root.
    """
    override = os.environ.get("BOOKKEEPER_DOC_CURRENCY_MANIFEST")
    if override:
        return Path(override)
    root = _vault_root()
    if root is None:
        return None
    return root / _DOC_CURRENCY_MANIFEST_REL


def _to_finance_relative(dest: str) -> str:
    """Return a destination as a path relative to `sb-os/finance/` when it lives
    there; otherwise return the vault-relative path unchanged. Used to match a
    written surface against the manifest's finance-relative `code` patterns."""
    if dest.startswith(_FINANCE_PREFIX):
        return dest[len(_FINANCE_PREFIX):]
    return dest


def lookup_stale_docs(destination: str | Path) -> list[dict[str, Any]]:
    """Look up which doc surfaces a write to `destination` puts at risk.

    Reads the shared node-doc manifest and returns the list of
    `{node_id, doc_sections_at_risk}` couplings whose `code` patterns match the
    written surface. Returns an empty list when the surface is not coupled to
    any doc, or when the manifest is missing / unreadable (fail-soft — a missing
    manifest must never break a pipeline write).
    """
    try:
        import fnmatch

        import yaml  # imported lazily — audit.py must import even without PyYAML

        manifest_path = _doc_currency_manifest_path()
        if manifest_path is None or not manifest_path.exists():
            return []
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        couplings = data.get("couplings") or []

        rel = _to_finance_relative(_vault_relative(destination))
        hits: list[dict[str, Any]] = []
        for coupling in couplings:
            if not isinstance(coupling, dict):
                continue
            patterns = coupling.get("code") or []
            if not any(fnmatch.fnmatch(rel, pat) for pat in patterns):
                continue
            sections: list[str] = []
            for doc in coupling.get("docs") or []:
                if isinstance(doc, dict):
                    for sec in doc.get("sections") or []:
                        sections.append(f"{doc.get('path')}#{sec}")
            hits.append(
                {
                    "node_id": coupling.get("node_id"),
                    "doc_sections_at_risk": sections,
                }
            )
        return hits
    except Exception:  # never raise into the caller (fail-soft invariant)
        return []


def emit_docs_potentially_stale(
    destination: str | Path,
    *,
    source_function: str,
    actor: str | None = None,
    trigger_context: dict[str, Any] | None = None,
) -> None:
    """Emit a `docs_potentially_stale` signal for a structural write to
    `destination` IFF that surface is coupled to a doc in the shared manifest.

    Carries `{destination, node_id, doc_sections_at_risk}` — the payload the
    `doc-maintainer` companion reads (its Dispatch Contract `stale_events`
    field) to know which surfaces to reconcile. When the destination is not
    coupled to any doc, NOTHING is emitted (no noise for unmapped writes).

    Best-effort; never raises into the caller (the layer-2 fail-soft invariant).
    A caller's extra `trigger_context` is merged under the looked-up coupling
    so call-site context (e.g. the run's month) is preserved.
    """
    try:
        hits = lookup_stale_docs(destination)
        if not hits:
            return
        # Store the vault-relative form so the event's `destination` matches the
        # surface that was matched against the manifest (consistent for both an
        # absolute path and an already-vault-relative string input).
        dest_rel = _vault_relative(destination)
        # One event per coupled surface; each names its node + at-risk sections.
        for hit in hits:
            ctx: dict[str, Any] = {
                "node_id": hit.get("node_id"),
                "doc_sections_at_risk": hit.get("doc_sections_at_risk"),
            }
            if trigger_context:
                ctx.update(trigger_context)
            emit(
                "docs_potentially_stale",
                source_function=source_function,
                actor=actor,
                destination=dest_rel,
                materiality="high",
                trigger_context=ctx,
                _stack_depth=3,
            )
    except Exception as e:  # never raise
        print(f"[audit] emit_docs_potentially_stale failed: {e}", file=sys.stderr)
