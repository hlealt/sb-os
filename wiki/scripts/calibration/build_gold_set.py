#!/usr/bin/env python3
"""Validate the hand-checked GOLD set and merge it into the ground-truth manifest.

Reads `gold-set.yaml` (the builder's hand-checked real (page, raw) labels,
stratified by source kind, with a cal/test split) and:

  1. VALIDATES every entry — page file exists, raw file exists, required fields
     present, label in {thin, faithful}, kind in {paper, article, podcast},
     split in {cal, test}, and a thin entry carries a non-empty `missing` list;
  2. MERGES the validated entries into the manifest's top-level `gold` array
     (keyed on `page`, so re-runs update in place);
  3. REPORTS the stratification: per-kind counts, per-label counts, and the
     calibration vs test split sizes — the keystone-quality evidence OD-1 demands.

The manifest (default `data/ground-truth-manifest.json`) is the SINGLE structured
file tasks 2.2 / 2.3 / 2.4 consume. Its shape:

    {
      "schema": "silver-ablation/1",
      "ablations": [ {ablation record}, ... ],   # from silver_ablation.py
      "gold":      [ {gold record},      ... ]    # from this script
    }

A gold record:
    {
      "page": "<vault-rel page path>",
      "raw":  "<vault-rel raw path>",
      "kind": "paper|article|podcast",
      "label": "thin|faithful",
      "split": "cal|test",
      "check": "deep|signal",
      "missing":  [ "<dropped load-bearing item>", ... ],   # thin entries
      "retained": [ "<preserved load-bearing item>", ... ], # faithful entries (optional)
      "note": "<free-text>"                                  # optional
    }

Exit codes: 0 ok; 2 a validation error (missing file / bad field) — manifest NOT
written; 3 the YAML or manifest path is unusable.

Usage
-----
    python build_gold_set.py \
        --gold     <this-dir>/data/gold-set.yaml \
        --manifest <this-dir>/data/ground-truth-manifest.json \
        [--vault-root <vault>] [--check-only]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import yaml

SCHEMA_VERSION = "silver-ablation/1"
VALID_KINDS = {"paper", "article", "podcast"}
VALID_LABELS = {"thin", "faithful"}
VALID_SPLITS = {"cal", "test"}
VALID_CHECKS = {"deep", "signal"}
REQUIRED = ("page", "raw", "kind", "label", "split", "check")


def _vault_root_from(path: Path) -> Path:
    p = path.resolve()
    for anc in [p, *p.parents]:
        if (anc / "sb-os.json").exists():
            return anc
    return Path(__file__).resolve().parents[5]


def validate(entries: list[dict], vault_root: Path) -> tuple[list[dict], list[str]]:
    records: list[dict] = []
    errors: list[str] = []
    seen_pages: set[str] = set()
    for i, e in enumerate(entries):
        tag = f"entry[{i}] ({e.get('page', '?')})"
        for f in REQUIRED:
            if not e.get(f):
                errors.append(f"{tag}: missing required field '{f}'")
        if errors and errors[-1].startswith(tag):
            continue
        if e["kind"] not in VALID_KINDS:
            errors.append(f"{tag}: kind '{e['kind']}' not in {VALID_KINDS}")
        if e["label"] not in VALID_LABELS:
            errors.append(f"{tag}: label '{e['label']}' not in {VALID_LABELS}")
        if e["split"] not in VALID_SPLITS:
            errors.append(f"{tag}: split '{e['split']}' not in {VALID_SPLITS}")
        if e["check"] not in VALID_CHECKS:
            errors.append(f"{tag}: check '{e['check']}' not in {VALID_CHECKS}")
        if e["page"] in seen_pages:
            errors.append(f"{tag}: duplicate page")
        seen_pages.add(e["page"])
        # file existence (the keystone integrity check — no phantom pages)
        page_p = vault_root / e["page"]
        raw_p = vault_root / e["raw"]
        if not page_p.exists():
            errors.append(f"{tag}: page file not found at {page_p}")
        if not raw_p.exists():
            errors.append(f"{tag}: raw file not found at {raw_p}")
        # a thin entry must say WHAT is missing (else it is not a usable label)
        if e["label"] == "thin" and not e.get("missing") and not e.get("note"):
            errors.append(f"{tag}: thin entry has neither a 'missing' list nor a 'note'")
        rec = {
            "page": e["page"], "raw": e["raw"], "kind": e["kind"],
            "label": e["label"], "split": e["split"], "check": e["check"],
        }
        for opt in ("missing", "retained", "note", "page_flagged_reingest"):
            if e.get(opt) is not None:
                rec[opt] = e[opt]
        records.append(rec)
    return records, errors


def report(records: list[dict]) -> str:
    by_kind = Counter(r["kind"] for r in records)
    by_label = Counter(r["label"] for r in records)
    by_split = Counter(r["split"] for r in records)
    by_check = Counter(r["check"] for r in records)
    # kind x label cross-tab
    cross = Counter((r["kind"], r["label"]) for r in records)
    lines = [
        f"GOLD SET: {len(records)} hand-checked real (page, raw) pairs",
        f"  by kind  : " + ", ".join(f"{k}={by_kind[k]}" for k in sorted(by_kind)),
        f"  by label : " + ", ".join(f"{k}={by_label[k]}" for k in sorted(by_label)),
        f"  by split : " + ", ".join(f"{k}={by_split[k]}" for k in sorted(by_split)),
        f"  by check : " + ", ".join(f"{k}={by_check[k]}" for k in sorted(by_check)),
        "  kind x label:",
    ]
    for kind in sorted(VALID_KINDS):
        t = cross.get((kind, "thin"), 0)
        f = cross.get((kind, "faithful"), 0)
        lines.append(f"    {kind:8s} thin={t} faithful={f}")
    # split x label (calibration must hold both labels; test must hold both)
    lines.append("  split x label:")
    for split in sorted(VALID_SPLITS):
        t = sum(1 for r in records if r["split"] == split and r["label"] == "thin")
        f = sum(1 for r in records if r["split"] == split and r["label"] == "faithful")
        lines.append(f"    {split:4s} thin={t} faithful={f}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--vault-root", default=None)
    ap.add_argument("--check-only", action="store_true",
                    help="validate + report only; do not write the manifest")
    args = ap.parse_args(argv)

    gold_path = Path(args.gold)
    if not gold_path.exists():
        print(f"gold YAML not found: {gold_path}", file=sys.stderr)
        return 3
    vault_root = Path(args.vault_root).resolve() if args.vault_root else _vault_root_from(gold_path)

    try:
        data = yaml.safe_load(gold_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as ex:
        print(f"gold YAML parse error: {ex}", file=sys.stderr)
        return 3
    entries = (data or {}).get("entries", [])
    if not entries:
        print("gold YAML has no 'entries'", file=sys.stderr)
        return 3

    records, errors = validate(entries, vault_root)
    if errors:
        print(f"VALIDATION FAILED ({len(errors)} error(s)) — manifest NOT written:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 2

    print(report(records))

    if args.check_only:
        print("\n--check-only: manifest not written.")
        return 0

    mpath = Path(args.manifest)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": SCHEMA_VERSION, "ablations": [], "gold": []}
    if mpath.exists():
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
            manifest.setdefault("schema", SCHEMA_VERSION)
            manifest.setdefault("ablations", [])
            manifest.setdefault("gold", [])
        except json.JSONDecodeError:
            pass
    # merge gold by page key
    idx = {g["page"]: i for i, g in enumerate(manifest["gold"])}
    for r in records:
        if r["page"] in idx:
            manifest["gold"][idx[r["page"]]] = r
        else:
            manifest["gold"].append(r)
    mpath.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nMerged {len(records)} gold records into {mpath} "
          f"(ablations: {len(manifest['ablations'])}, gold: {len(manifest['gold'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
