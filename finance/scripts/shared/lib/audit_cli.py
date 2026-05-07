"""Observer CLI: `python -m lib.audit_cli tail [--last N] [--since DATE] ...`.

Reads `events-{YYYY}.jsonl` files under
`{vault_root}/.user/finance/bookkeeper/audit/` and prints a compact summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import audit


def _iter_events(audit_dir: Path):
    if not audit_dir.exists():
        return
    for path in sorted(audit_dir.glob("events-*.jsonl")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue


def _format_event(e: dict) -> str:
    ts = e.get("ts", "")
    actor = e.get("actor", "?")
    et = e.get("event_type", "?")
    mat = (e.get("materiality") or "").upper()
    src = (e.get("source") or {}).get("file", "?")
    src_short = Path(src).name
    dest = e.get("destination", "")
    summary = e.get("summary") or {}
    delta_bits = []
    if "delta_rows" in summary:
        delta_bits.append(f"{summary['delta_rows']:+d} rows")
    if "bytes_before" in summary and "bytes_after" in summary:
        db = summary["bytes_after"] - summary["bytes_before"]
        delta_bits.append(f"Δ {db:+d} bytes")
    delta = " ".join(delta_bits)
    if et in ("gate_pass", "gate_fail", "coverage_progress"):
        gate = e.get("gate") or {}
        return (
            f"[{ts}] {actor:18s} {et:18s} "
            f"{gate.get('name', gate.get('metric', '?'))} = {gate.get('value', '?')} "
            f"(threshold={gate.get('threshold', '-')})"
        )
    return (
        f"[{ts}] {actor:18s} {et:13s} {mat:5s} "
        f"{src_short} → {dest}  {delta}"
    )


def cmd_tail(args: argparse.Namespace) -> int:
    audit.get_run_id()  # warm cache
    root = audit._vault_root()
    if root is None:
        print("error: could not find sb-os.json walking up from cwd", file=sys.stderr)
        return 2
    audit_dir = root / ".user" / "finance" / "bookkeeper" / "audit"
    events = list(_iter_events(audit_dir))

    since_dt: datetime | None = None
    if args.since:
        try:
            since_dt = datetime.fromisoformat(args.since)
        except ValueError:
            print(f"error: --since must be ISO date/datetime: {args.since}", file=sys.stderr)
            return 2

    def keep(e: dict) -> bool:
        if args.actor and e.get("actor") != args.actor:
            return False
        if args.run and e.get("run_id") != args.run:
            return False
        if args.type and e.get("event_type") != args.type:
            return False
        if since_dt is not None:
            try:
                ts = datetime.fromisoformat(e.get("ts", "").replace("Z", "+00:00"))
            except ValueError:
                return False
            if ts.replace(tzinfo=None) < since_dt.replace(tzinfo=since_dt.tzinfo):
                return False
        return True

    filtered = [e for e in events if keep(e)]
    if args.last:
        filtered = filtered[-args.last:]
    for e in filtered:
        print(_format_event(e))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="audit", description="Finance audit-event observer")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_tail = sub.add_parser("tail", help="Print recent events")
    p_tail.add_argument("--last", type=int, default=20, help="Show last N events (default 20; 0 = all)")
    p_tail.add_argument("--since", help="ISO date/datetime")
    p_tail.add_argument("--actor", help="Filter by actor")
    p_tail.add_argument("--run", help="Filter by run_id")
    p_tail.add_argument("--type", help="Filter by event_type")
    p_tail.set_defaults(func=cmd_tail)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
