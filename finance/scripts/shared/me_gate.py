"""Structural non-overlap (ME) semantic gate — p5-3.

Fires on ANY agent edit that creates or modifies a data store, a config schema,
or a dashboard-consumed script. Before that edit lands, this gate asks the
SEMANTIC question: "does the logical concept this edit introduces already have a
canonical store somewhere in the finance system?" — NOT the filesystem question
"does this exact file already exist?".

The reference is the p2-7 sources-of-truth inventory (23 data domains),
transcribed into `lib/source_of_truth_registry.py`. When an edit's declared
concept overlaps an existing registered concept, the gate REFUSES and surfaces
three named options (matching the gatekeeper-loop's voice):

  [R] Reuse the existing store.
  [J] Justify a new store (genuinely new concept) — requires registering
      the new store in the registry/p2-7 in the same change.
  [C] Consolidate — merge the new store into the existing one.

A genuinely new concept (no overlap with any of the 23 domains) PASSES.

Why semantic, not filesystem: the whole class of bug this gate prevents is "a
second store for data we already track" — e.g. adding a new vendor->category
dict when `suppliers.json::default_category` already owns that concept. A
filesystem check would happily let a new file through because the *path* is new;
the data overlap is invisible to it. The registry encodes the concept ownership,
so the check is auditable (every refusal cites the p2-7 §-number).

Three call surfaces (all route through `evaluate`):
  1. Workflow start (the bookkeeper gatekeeper loop, Rule A structural check).
  2. Pre-commit hook (block a commit that introduces an overlapping store).
  3. Quarterly review (sweep declared/changed stores for overlap drift).

Tertiary cross-config safety net: when the optional `audit-data-duplication.py`
cross-config duplicate auditor exists, this gate composes it as a SECONDARY
confirmation. That tool was deferred (see plan task p5-12); until it ships, the
gate runs on the PRIMARY registry check alone and notes the net as not-yet-built
(it NEVER blocks on the missing net).

Usage:
    # Evaluate a proposed edit by concept (the primary surface):
    python me_gate.py --concept "new vendor to category dict" \\
        [--target PATH] [--keys k1,k2] [--store-name NAME]

    # Pre-commit / quarterly sweep over a manifest of proposed stores:
    python me_gate.py --manifest proposed-stores.json

Exit codes:
    0   Pass — concept is genuinely new (no overlap); edit may proceed.
    1   Refuse — concept overlaps an existing canonical store; options surfaced.
    2   Error — bad arguments or unreadable manifest.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import audit
from lib import source_of_truth_registry as registry

# Optional tertiary cross-config net (deferred — plan task p5-12).
# Imported lazily inside _run_tertiary_net so the gate never hard-depends on it.
_TERTIARY_NET_MODULE = "audit_data_duplication"

_GATE_NAME = "me_non_overlap"


@dataclass
class GateResult:
    """Outcome of evaluating one proposed edit."""

    concept: str
    passed: bool
    overlaps: list[registry.RegistryEntry]
    tertiary_net_available: bool
    tertiary_net_hits: list[str]


def evaluate(
    concept: str,
    *,
    target: str | None = None,
    keys: list[str] | None = None,
    store_name: str | None = None,
) -> GateResult:
    """Evaluate one proposed store/config/dashboard-script edit.

    `concept` is the logical concept the edit introduces (required). `target`,
    `keys`, and `store_name` are optional extra signals (the target path's
    basename, the config keys the edit adds, the store's name) folded into the
    semantic lookup. Returns a GateResult; never raises on a normal evaluation.
    """
    extra: list[str] = []
    if store_name:
        extra.append(store_name)
    if keys:
        extra.extend(keys)
    if target:
        # Only the basename is a meaningful signal; the directory is noise.
        extra.append(Path(target).name)

    overlaps = registry.find_overlaps(concept, extra_terms=extra)
    passed = len(overlaps) == 0

    net_available, net_hits = _run_tertiary_net(concept, target)

    return GateResult(
        concept=concept,
        passed=passed,
        overlaps=overlaps,
        tertiary_net_available=net_available,
        tertiary_net_hits=net_hits,
    )


def _run_tertiary_net(concept: str, target: str | None) -> tuple[bool, list[str]]:
    """Compose the optional cross-config duplicate auditor as a secondary net.

    Returns (available, hits). When the deferred `audit-data-duplication.py`
    tool is not importable, returns (False, []) — the gate NEVER blocks on the
    missing net (graceful "not-yet-built" fallback, same pattern as the
    gatekeeper-loop companion seams). When it exists, it is expected to expose
    `find_cross_config_duplicates(concept, target) -> list[str]`.
    """
    try:
        import importlib

        mod = importlib.import_module(_TERTIARY_NET_MODULE)
    except ImportError:
        return False, []
    finder = getattr(mod, "find_cross_config_duplicates", None)
    if not callable(finder):
        return True, []
    try:
        hits = list(finder(concept, target))
    except Exception:  # net is best-effort; a buggy net must not break the gate
        return True, []
    return True, hits


def _options_block(result: GateResult) -> str:
    """Refusal block matching the gatekeeper-loop's voice (Rule A)."""
    lines = [
        f"This is outside the current structure: the concept \"{result.concept}\" "
        "already has a canonical store.",
        "",
        "Existing stores covering this concept:",
    ]
    for entry in result.overlaps:
        lines.append(f"  - {entry.canonical}  (p2-7 §{entry.section})")
    lines += [
        "",
        "How do you want to proceed?",
        "  [R] Reuse the existing store — I read/write the data through it; "
        "nothing new is created.",
        "  [J] Justify a new store — only if the concept is genuinely new; "
        "requires registering the new store in the registry (p2-7) in the same change.",
        "  [C] Consolidate — merge the new store into the existing one.",
    ]
    return "\n".join(lines)


def _print_result(result: GateResult) -> None:
    if result.passed:
        print(
            f"me_gate PASS — \"{result.concept}\" is a new concept "
            "(no overlap with the 23 p2-7 canonical stores)."
        )
    else:
        print(_options_block(result), file=sys.stderr)
        print(
            f"me_gate REFUSE — \"{result.concept}\" overlaps "
            f"{len(result.overlaps)} existing canonical store(s).",
            file=sys.stderr,
        )
    if not result.tertiary_net_available:
        print(
            "[me_gate] tertiary cross-config net (audit-data-duplication.py) "
            "not yet available — primary check (registry p2-7) is "
            "authoritative; pending item recorded (plan p5-12).",
            file=sys.stderr,
        )
    elif result.tertiary_net_hits:
        print(
            f"[me_gate] tertiary net confirmed {len(result.tertiary_net_hits)} "
            "cross-config duplicate(s):",
            file=sys.stderr,
        )
        for h in result.tertiary_net_hits:
            print(f"    - {h}", file=sys.stderr)


def _emit_event(result: GateResult, *, source_function: str) -> None:
    """Emit one gate_pass / gate_fail audit event (best-effort, never raises)."""
    audit.emit_gate(
        _GATE_NAME,
        metric="overlap_count",
        value=float(len(result.overlaps)),
        threshold=0.0,  # zero overlaps required to pass
        passed=result.passed,
        source_function=source_function,
        trigger_context={
            "concept": result.concept,
            "overlapping_sections": [e.section for e in result.overlaps],
            "tertiary_net_available": result.tertiary_net_available,
            "tertiary_net_hits": result.tertiary_net_hits,
        },
    )


def _evaluate_manifest(manifest_path: Path) -> int:
    """Sweep a manifest of proposed stores (pre-commit / quarterly surface).

    Manifest schema: a JSON list of objects, each with a required `concept`
    field and optional `target` / `keys` / `store_name`. Exit 1 if ANY proposed
    store overlaps an existing one; exit 0 if all are genuinely new.
    """
    try:
        proposed = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: could not read manifest {manifest_path}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(proposed, list):
        print("ERROR: manifest must be a JSON list of proposed stores", file=sys.stderr)
        return 2

    any_overlap = False
    for item in proposed:
        if not isinstance(item, dict) or "concept" not in item:
            print(f"ERROR: manifest entry missing 'concept': {item!r}", file=sys.stderr)
            return 2
        result = evaluate(
            item["concept"],
            target=item.get("target"),
            keys=item.get("keys"),
            store_name=item.get("store_name"),
        )
        _print_result(result)
        _emit_event(result, source_function="me_gate.manifest")
        if not result.passed:
            any_overlap = True
    return 1 if any_overlap else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Structural non-overlap (ME) semantic gate — refuse a second "
        "store for a concept the 23 p2-7 domains already own."
    )
    parser.add_argument(
        "--concept",
        help="The logical concept the edit introduces (e.g. 'new vendor to category dict').",
    )
    parser.add_argument("--target", help="Target path of the store/config/script being edited.")
    parser.add_argument(
        "--keys",
        help="Comma-separated config keys / column names the edit adds (extra overlap signal).",
    )
    parser.add_argument("--store-name", help="Name of the store being created (extra overlap signal).")
    parser.add_argument(
        "--manifest",
        help="Path to a JSON list of proposed stores (pre-commit / quarterly sweep).",
    )
    args = parser.parse_args()

    if args.manifest:
        return _evaluate_manifest(Path(args.manifest))

    if not args.concept:
        print("ERROR: --concept is required (or use --manifest)", file=sys.stderr)
        return 2

    keys = [k.strip() for k in args.keys.split(",")] if args.keys else None
    result = evaluate(
        args.concept,
        target=args.target,
        keys=keys,
        store_name=args.store_name,
    )
    _print_result(result)
    _emit_event(result, source_function="me_gate.main")
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
