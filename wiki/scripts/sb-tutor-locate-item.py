#!/usr/bin/env python3
"""sb-tutor-locate-item — deterministically locate a section in a learning-library page-source.

Given a topic page-source (``{library_root}/topics/{slug}.md``) and an item key — the
section ANCHOR-ID the built page exposes (``s-...``; the hover-copy prompt carries it) OR
the section TITLE — return that section's CURRENT markdown block, its 1-based inclusive
line range in the file, and the topic ``slug``. The tutor's ENRICH pipeline runs this to
frame the EXACT block a research/update agent must deepen — no guessing which section.

Deterministic locate only — the reasoning about WHAT to add stays the tutor's.

Usage:
  python sb-tutor-locate-item.py --library-root PATH --source topics/SLUG.md --item ANCHOR_OR_TITLE [--json]
  python sb-tutor-locate-item.py --source /abs/path/topics/SLUG.md --item "Section Title" --json

Exit codes: 0 single match | 2 bad args / file not found | 3 no match | 4 ambiguous match.
Anchor ids match the builder exactly: s-{slugify(title)}. slugify() below MIRRORS
sb-tutor-build-library.py — keep the two in lockstep (the section anchor-id contract).
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

HEADING = re.compile(r"^##\s+(.+?)\s*$")  # level-2 only; mirrors the builder's ^##\s+ split (### never matches)


def slugify(s: str) -> str:
    # MUST match sb-tutor-build-library.py slugify(): the section anchor-id contract
    # id="s-{slugify(title)}" that the built page, the hover-copy payload, and this
    # locator all key on. Change both together.
    s = re.sub(r"[^\w\s-]", "", str(s).lower()).strip()
    return re.sub(r"[\s_-]+", "-", s) or "topic"


def find_body_start(lines):
    """0-based index where the markdown body begins (after a leading --- YAML frontmatter)."""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return i + 1
    return 0


def extract_slug(lines, src_path):
    """frontmatter ``slug:`` wins; else the filename stem (CREATE convention: filename == slug)."""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                break
            m = re.match(r"slug\s*:\s*(.+?)\s*$", lines[i])
            if m:
                return m.group(1).strip().strip('"').strip("'")
    return src_path.stem


def scan_sections(lines):
    """[{title, anchor, start, end, block}] with 1-based inclusive file line ranges.
    A section = a line matching ^##\\s+ (mirrors the builder), spanning to the line before
    the next such heading or EOF."""
    start = find_body_start(lines)
    heads = []
    for i in range(start, len(lines)):
        m = HEADING.match(lines[i])
        if m:
            heads.append((i, m.group(1).strip()))
    sections = []
    for j, (idx, title) in enumerate(heads):
        end_idx = heads[j + 1][0] - 1 if j + 1 < len(heads) else len(lines) - 1
        sections.append({
            "title": title,
            "anchor": "s-" + slugify(title),
            "start": idx + 1,                 # 1-based
            "end": end_idx + 1,               # 1-based inclusive
            "block": "\n".join(lines[idx:end_idx + 1]),
        })
    return sections


def match_item(sections, item):
    """Anchor matches win over title matches. Accepts `s-...`, `#s-...`, the exact title, or a
    slugified title. Returns the list of matching sections (0, 1, or >1)."""
    key = item.strip()
    bare = key.lstrip("#")
    keyl = key.lower()
    skey = slugify(key)
    anchor_hits = [s for s in sections if s["anchor"] in (key, bare)]
    if anchor_hits:
        return anchor_hits
    return [s for s in sections if s["title"].lower() == keyl or slugify(s["title"]) == skey]


def main():
    ap = argparse.ArgumentParser(description="Locate a section block in a learning-library page-source.")
    ap.add_argument("--source", required=True, help="page-source path; relative to --library-root, or absolute")
    ap.add_argument("--library-root", help="library root (resolves a relative --source)")
    ap.add_argument("--item", required=True, help="section anchor-id (s-...) or title")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.is_absolute():
        if not args.library_root:
            sys.stderr.write("error: --source is relative but --library-root was not given\n")
            return 2
        src = Path(args.library_root) / args.source
    src = src.resolve()
    if not src.is_file():
        sys.stderr.write(f"error: source not found: {src}\n")
        return 2

    lines = src.read_text(encoding="utf-8").splitlines()
    sections = scan_sections(lines)
    slug = extract_slug(lines, src)
    index = [{"anchor": s["anchor"], "title": s["title"], "start": s["start"], "end": s["end"]} for s in sections]
    hits = match_item(sections, args.item)

    if len(hits) == 1:
        s = hits[0]
        out = {"source": str(src), "slug": slug,
               "matched": {k: s[k] for k in ("title", "anchor", "start", "end", "block")},
               "sections": index}
        if args.json:
            print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            print(f'MATCH  {s["anchor"]}  "{s["title"]}"  lines {s["start"]}-{s["end"]}  slug={slug}')
            print(f'source: {src}')
            print("----- current block -----")
            print(s["block"])
        return 0

    err = "no section matched" if not hits else f"ambiguous: {len(hits)} sections matched"
    out = {"error": err, "item": args.item, "source": str(src), "slug": slug,
           "candidates": [{"anchor": s["anchor"], "title": s["title"]} for s in hits],
           "sections": index}
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        sys.stderr.write(f'{err} for item {args.item!r} in {src}\n')
        sys.stderr.write("available sections:\n")
        for s in sections:
            sys.stderr.write(f'  {s["anchor"]}  "{s["title"]}"  (lines {s["start"]}-{s["end"]})\n')
    return 3 if not hits else 4


if __name__ == "__main__":
    sys.exit(main())
