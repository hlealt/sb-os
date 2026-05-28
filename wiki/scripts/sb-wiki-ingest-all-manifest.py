#!/usr/bin/env python3
"""Discovery manifest for sb-wiki-ingest-all.

Lists every raw source that has NOT been ingested yet, with an approximate
token count so the orchestrator can pack files into per-subagent batches.

A raw file is "ingested" when its source page exists at
`wiki/sources/{origin}/{stem}.md`. This script only reads — it never writes
wiki content. Judgment (topical relevance, batching) is the orchestrator's job;
this script supplies the mechanical inputs.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from pathlib import Path

logging.getLogger("pypdf").setLevel(logging.ERROR)
logging.getLogger("PyPDF2").setLevel(logging.ERROR)

CHARS_PER_TOKEN = 4
DEFAULT_EXCLUDE = {"assets", "_assets"}
NON_SOURCE_FILES = {"AGENTS.md", "CLAUDE.md", "README.md"}


def _fspath(path: Path) -> str:
    """Return an OS path safe to open on Windows past the 260-char MAX_PATH."""
    raw = os.path.abspath(os.fspath(path))
    if os.name == "nt" and len(raw) >= 260 and not raw.startswith("\\\\?\\"):
        return "\\\\?\\" + raw
    return raw


def read_text(path: Path) -> str:
    with open(_fspath(path), "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, flags=re.S)
    if not match:
        return {}
    data: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key_match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if key_match:
            data[key_match.group(1)] = key_match.group(2).strip().strip("\"'")
    return data


def first_h1(text: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", text, flags=re.M)
    return match.group(1).strip() if match else ""


def filename_date(name: str) -> str:
    match = re.match(r"^(\d{4})[-_](\d{2})[-_](\d{2})", name)
    return "-".join(match.groups()) if match else ""


def estimate_pdf_tokens(path: Path) -> int | None:
    """Extract PDF text and estimate tokens. None when no PDF library is present."""
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except ImportError:
            return None
    try:
        reader = PdfReader(_fspath(path))
        chars = sum(len(page.extract_text() or "") for page in reader.pages)
    except Exception:
        return None
    return chars // CHARS_PER_TOKEN if chars else None


def describe_md(path: Path) -> tuple[str, str, int]:
    text = read_text(path)
    fm = frontmatter(text)
    title = fm.get("title", "") or first_h1(text) or path.stem
    date = fm.get("date", "") or fm.get("created", "") or filename_date(path.name)
    return title, date, len(text) // CHARS_PER_TOKEN


def describe_pdf(path: Path) -> tuple[str, str, int | None]:
    return path.stem, filename_date(path.name), estimate_pdf_tokens(path)


def resolve_wiki_root(vault_root: Path) -> Path:
    manifest = json.loads(read_text(vault_root / "sb-os.json"))
    return vault_root / manifest["wiki_root"]


def collect(wiki_root: Path, exclude: set[str], only_origin: str | None) -> dict:
    raw_root = wiki_root / "raw"
    sources_root = wiki_root / "wiki" / "sources"
    items: list[dict] = []
    origins: dict[str, dict[str, int]] = {}
    raw_total = ingested = 0

    origin_dirs = sorted(
        p for p in raw_root.iterdir()
        if p.is_dir() and p.name not in exclude
        and (only_origin is None or p.name == only_origin)
    )
    for origin_dir in origin_dirs:
        origin = origin_dir.name
        index_name = f"{origin}.md"
        raw_files = sorted(
            f for f in origin_dir.iterdir()
            if f.is_file() and f.suffix in (".md", ".pdf")
            and f.name != index_name and f.name not in NON_SOURCE_FILES
        )
        for raw_file in raw_files:
            raw_total += 1
            source_page = sources_root / origin / f"{raw_file.stem}.md"
            if source_page.exists():
                ingested += 1
                continue
            is_pdf = raw_file.suffix == ".pdf"
            title, date, tokens = describe_pdf(raw_file) if is_pdf else describe_md(raw_file)
            items.append({
                "path": raw_file.relative_to(wiki_root.parent).as_posix(),
                "origin": origin,
                "filename": raw_file.name,
                "stem": raw_file.stem,
                "is_pdf": is_pdf,
                "title": title,
                "date": date,
                "token_estimate": tokens,
            })
            bucket = origins.setdefault(origin, {"missing": 0, "token_sum": 0})
            bucket["missing"] += 1
            bucket["token_sum"] += tokens or 0

    return {
        "totals": {
            "origins_with_missing": len(origins),
            "raw_total": raw_total,
            "ingested": ingested,
            "missing": len(items),
        },
        "origins": origins,
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, default=Path.cwd())
    parser.add_argument("--report", type=Path, help="optional JSON report path")
    parser.add_argument(
        "--exclude-origins",
        default=",".join(sorted(DEFAULT_EXCLUDE)),
        help="comma-separated raw subfolders to skip (asset folders)",
    )
    parser.add_argument("--origin", help="scope the scan to a single origin")
    args = parser.parse_args()

    wiki_root = resolve_wiki_root(args.vault_root.resolve())
    exclude = {o.strip() for o in args.exclude_origins.split(",") if o.strip()}
    payload = collect(wiki_root, exclude, args.origin)

    output = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
