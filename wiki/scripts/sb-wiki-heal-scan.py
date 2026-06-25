#!/usr/bin/env python3
"""Scan every wiki source page + its raw, compute per-source metrics,
write the heal-triage sidecar, and MERGE the heal-index.

Sidecar:   3-resources/tools/obsidian-dashboards/heal-triage.data.json
Heal-index: 3-resources/knowledge-base/heal-index.md

Merge rule (heal-index):
  - Appends any corpus source NOT already a row, as heal=no.
  - NEVER overwrites an existing row's heal value.
  - Rows are keyed by the wiki path.
  - Write-back rewrites the WHOLE table from an in-memory list.

Usage:
  python sb-wiki-heal-scan.py            # sidecar + heal-index merge
  python sb-wiki-heal-scan.py --no-merge # sidecar only
  python sb-wiki-heal-scan.py --seed-from-tags
      # one-shot seed: compute ORIGINAL/HEALED sets and overwrite
      # heal column per the seed algorithm; implies sidecar + merge.
"""

import argparse
import datetime
import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
VAULT = Path(__file__).resolve().parents[5]          # .../second-brain
SRC   = VAULT / "3-resources/knowledge-base/wiki/sources"
RAW   = VAULT / "3-resources/knowledge-base/raw"
SIDECAR   = VAULT / "3-resources/tools/obsidian-dashboards/heal-triage.data.json"
HEAL_IDX  = VAULT / "3-resources/knowledge-base/heal-index.md"

# Candidate-flag thresholds (same as original gen.py)
THIN_SECTIONS, THIN_TABLES, THIN_RATIO = 6, 2, 0.10

# The 11 whole-origin leaf-tagged origins for seed algorithm
LEAF_TAGGED_ORIGINS = frozenset([
    "papers", "lennys-podcast", "a16z", "bain", "dario-amodei",
    "hbr", "mckinsey", "prof-g", "stratechery", "towardsai", "ycombinator",
])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def words(t: str) -> int:
    return len(t.split())


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def rel(p: Path) -> str:
    """Vault-relative POSIX path."""
    return p.relative_to(VAULT).as_posix()


# ---------------------------------------------------------------------------
# Corpus scan — produce flat list of per-source dicts
# ---------------------------------------------------------------------------

def scan_corpus() -> list[dict]:
    """Return one dict per wiki source page (leaf indexes excluded)."""
    sources = []
    for od in sorted(SRC.iterdir()):
        if not od.is_dir():
            continue
        origin = od.name
        for sp in sorted(od.glob("*.md")):
            if sp.stem == origin:       # skip origin leaf index
                continue
            txt = read(sp)

            # healed stamp (durable "already healed, don't heal again" marker;
            # source-page frontmatter `healed: YYYY-MM-DD`). The dashboard reads
            # this from the sidecar to filter healed pages out of the queue.
            hm = re.search(r'^healed:\s*"?(\d{4}-\d{2}-\d{2})"?', txt, re.M)
            healed = hm.group(1) if hm else None

            # Substance word count
            m = re.search(r"^##\s+Substance\s*$(.*?)(^##\s|\Z)", txt, re.S | re.M)
            sw = words(m.group(1)) if m else 0

            # Raw file resolution
            rm = re.search(r'raw:\s*"?\[\[([^\]]+)\]\]"?', txt)
            rawp = None
            rw = 0
            if rm:
                cand = RAW / origin / rm.group(1)
                if cand.exists():
                    rawp = cand
                    rtxt = read(cand)
                    rw = words(rtxt)
                    rt = rtxt.count("\n|")
                    rs = len(re.findall(r"^#{2,3}\s", rtxt, re.M))
                else:
                    rt = rs = 0
            else:
                rt = rs = 0

            ratio = round(sw / rw, 3) if rw else None
            thin  = bool(
                (rs >= THIN_SECTIONS or rt >= THIN_TABLES)
                and ratio is not None
                and ratio < THIN_RATIO
            )

            sources.append(dict(
                origin  = origin,
                stem    = sp.stem,
                wiki    = rel(sp),
                raw     = (rel(rawp) if rawp else None),
                ratio   = ratio,
                rawWords= rw,
                subWords= sw,
                thin    = thin,
                healed  = healed,
            ))
    return sources


# ---------------------------------------------------------------------------
# Sidecar write
# ---------------------------------------------------------------------------

def write_sidecar(sources: list[dict]) -> None:
    payload = dict(
        generated    = datetime.date.today().isoformat(),
        total_sources= len(sources),
        sources      = sources,
    )
    SIDECAR.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Heal-index read / write
# ---------------------------------------------------------------------------

HEAL_IDX_HEADER = """\
# heal-index
<!-- The wiki heal queue. heal=yes rows are the targets /sb-wiki-ingest-healing consumes.
     Managed by sb-wiki-heal-scan.py (scan MERGES: new sources added as heal=no, existing heal values never overwritten)
     and by the wiki-heal-triage dashboard (toggles rewrite the WHOLE table). Sort/grouping is presentation-only; row order is not semantic. -->

| raw | wiki | heal |
|-----|------|------|
"""


def parse_heal_index() -> dict[str, dict]:
    """Return existing rows keyed by wiki path: {wiki: {raw, heal}}."""
    if not HEAL_IDX.exists():
        return {}
    rows: dict[str, dict] = {}
    for line in HEAL_IDX.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if len(cells) != 3:
            continue
        raw_val, wiki_val, heal_val = cells
        if wiki_val == "wiki" or heal_val == "heal":  # header row
            continue
        if heal_val not in ("yes", "no"):
            continue
        rows[wiki_val] = {"raw": raw_val, "heal": heal_val}
    return rows


def write_heal_index(rows: dict[str, dict]) -> None:
    """Rewrite the WHOLE table from the in-memory rows dict."""
    lines = [HEAL_IDX_HEADER.rstrip("\n")]
    for wiki_path, data in rows.items():
        raw_val  = data.get("raw") or "(none)"
        heal_val = data.get("heal", "no")
        lines.append(f"| {raw_val} | {wiki_path} | {heal_val} |")
    HEAL_IDX.write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge_heal_index(sources: list[dict]) -> dict[str, dict]:
    """Merge corpus sources into the heal-index; return updated rows."""
    existing = parse_heal_index()
    for s in sources:
        wiki = s["wiki"]
        if wiki not in existing:
            existing[wiki] = {
                "raw" : s["raw"] if s["raw"] else "(none)",
                "heal": "no",
            }
        # never overwrite existing heal value
    return existing


# ---------------------------------------------------------------------------
# Seed algorithm (one-time migration)
# ---------------------------------------------------------------------------

def compute_seed_sets() -> tuple[set[str], set[str]]:
    """Return (original_flagged, healed) as sets of wiki vault-rel paths."""

    # ORIGINAL: inline-#reingest pages (excluding leaf indexes)
    inline_tagged: set[str] = set()
    for od in SRC.iterdir():
        if not od.is_dir():
            continue
        origin = od.name
        for sp in od.glob("*.md"):
            if sp.stem == origin:
                continue
            if "#reingest" in read(sp):
                inline_tagged.add(rel(sp))

    # ORIGINAL: every source page of the 11 leaf-tagged origins
    whole_origin: set[str] = set()
    for origin in LEAF_TAGGED_ORIGINS:
        od = SRC / origin
        if od.is_dir():
            for sp in od.glob("*.md"):
                if sp.stem == origin:
                    continue
                whole_origin.add(rel(sp))

    original = inline_tagged | whole_origin

    # HEALED: filenames from both ledgers
    def parse_ledger(ledger_path: Path, wiki_subdir: str) -> set[str]:
        healed: set[str] = set()
        if not ledger_path.exists():
            return healed
        txt = ledger_path.read_text(encoding="utf-8", errors="replace")
        for line in txt.splitlines():
            m = re.match(r"\|\s*\d+\s*\|\s*([^|]+)\s*\|", line)
            if not m:
                continue
            fname = m.group(1).strip()
            if not fname or fname in ("paper filename", "source filename"):
                continue
            healed.add(f"3-resources/knowledge-base/wiki/sources/{wiki_subdir}/{fname}")
        return healed

    papers_healed = parse_ledger(
        VAULT / "3-resources/knowledge-base/healing-progress-papers.md", "papers"
    )
    lenny_healed = parse_ledger(
        VAULT / "3-resources/knowledge-base/healing-progress-lenny.md", "lennys-podcast"
    )
    healed = papers_healed | lenny_healed

    return original, healed


def apply_seed(rows: dict[str, dict]) -> dict[str, dict]:
    """Set heal=yes iff wiki path in ORIGINAL and NOT in HEALED."""
    original, healed = compute_seed_sets()
    seeded = 0
    for wiki_path, data in rows.items():
        if wiki_path in original and wiki_path not in healed:
            data["heal"] = "yes"
            seeded += 1
        else:
            data["heal"] = "no"
    print(
        f"  seed: original={len(original)}, healed={len(healed)}, "
        f"heal_yes={seeded}"
    )
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Wiki heal-triage scan + sidecar/heal-index writer.")
    parser.add_argument("--no-merge",      action="store_true",
                        help="Write sidecar only; skip heal-index touch.")
    parser.add_argument("--seed-from-tags", action="store_true",
                        help="One-shot: seed heal=yes per ORIGINAL-minus-HEALED algorithm.")
    args = parser.parse_args()

    # 1. Scan corpus
    sources = scan_corpus()

    # 2. Write sidecar (always)
    write_sidecar(sources)
    print(f"sidecar written: {SIDECAR}  ({len(sources)} sources)")

    if args.no_merge:
        return

    # 3. Merge heal-index
    rows = merge_heal_index(sources)

    # 4. Optional seed
    if args.seed_from_tags:
        rows = apply_seed(rows)

    # 5. Write heal-index (whole-table rewrite)
    write_heal_index(rows)
    heal_yes = sum(1 for d in rows.values() if d["heal"] == "yes")
    print(
        f"heal-index written: {HEAL_IDX}  "
        f"({len(rows)} rows, {heal_yes} heal=yes)"
    )


if __name__ == "__main__":
    main()
