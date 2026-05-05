"""One-shot runner for B3 parser.

Usage: python run_b3.py <xlsx_path> <output_dir>

Writes b3_orders.csv, b3_proventos.csv, b3_balcao.csv, b3_corporate.csv into
<output_dir> and prints a summary of unknowns and flagged operations.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from parsers.b3_parser import B3Parser
from parsers.name_map import NameMapResolver
from utils import (
    ORDERS_COLUMNS, PROVENTOS_COLUMNS, BALCAO_COLUMNS,
    CORPORATE_ACTIONS_COLUMNS, write_ledger_csv,
)

LEDGER_COLUMNS = {
    'orders':    ORDERS_COLUMNS,
    'proventos': PROVENTOS_COLUMNS,
    'balcao':    BALCAO_COLUMNS,
    'corporate': CORPORATE_ACTIONS_COLUMNS,
}


def main():
    xlsx_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    parser = B3Parser()
    name_map = NameMapResolver()
    result = parser.parse(xlsx_path, name_map=name_map)

    print(f"== B3 Parser run ==")
    print(f"Source: {xlsx_path}")
    print(f"Total rows produced: {result.total_rows}")
    for key, rows in result.outputs.items():
        out_file = out_dir / f"b3_{key}.csv"
        write_ledger_csv(out_file, rows, LEDGER_COLUMNS[key])
        print(f"  b3_{key}.csv  -> {len(rows)} rows  ({out_file})")

    print(f"\n== Unknowns ({len(result.unknowns)}) ==")
    for u in result.unknowns[:50]:
        print(f"  [{u.source}/{u.field}] L{u.line_number}: {u.raw_value!r}")
    if len(result.unknowns) > 50:
        print(f"  ... and {len(result.unknowns)-50} more")

    print(f"\n== Flags ({len(result.flags)}) ==")
    by_reason = {}
    for f in result.flags:
        by_reason.setdefault(f.reason, []).append(f)
    for reason, items in by_reason.items():
        print(f"  {reason}: {len(items)}")
        for f in items[:3]:
            print(f"    L{f.line_number} {f.date} {f.operation!r} :: {f.product}")


if __name__ == '__main__':
    main()
