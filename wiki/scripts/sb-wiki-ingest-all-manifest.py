#!/usr/bin/env python3
"""Discovery manifest + dispatch plan for sb-wiki-ingest-all.

Lists every raw source that has NOT been ingested yet, with an approximate
token count, and (with --plan, the default) packs them into per-subagent
batches, schedules waves, and assigns each batch a model:

- Batches: per origin, greedy consecutive packing <= BATCH_TOKEN_CAP source
  tokens; a lone file above the cap (or with a null estimate) is its own
  batch — a source is never split across subagents.
- Waves: wave K holds batch index K of every origin (distinct origins are
  parallel-safe; same-origin batches serialize across waves), split into
  sub-waves of <= WAVE_CONCURRENCY batches.
- Model: "sonnet" when the batch's token sum <= SONNET_MAX_BATCH_TOKENS and
  every file in it has a non-null estimate; "opus" otherwise.

A raw file is "ingested" when its source page exists at
`wiki/sources/{origin}/{stem}.md`. Files whose raw-index row marks
`Wiki = Duplicate (…)` are confirmed content-duplicates and are SKIPPED
(reported under `duplicates`, never targeted). This script only reads — it
never writes wiki content.
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
BATCH_TOKEN_CAP = 50_000
SONNET_MAX_BATCH_TOKENS = 25_000
WAVE_CONCURRENCY = 5


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


def duplicate_rows(origin_dir: Path) -> set[str]:
    """Filenames whose raw-index row marks `Wiki = Duplicate (…)` (case-insensitive)."""
    index_path = origin_dir / f"{origin_dir.name}.md"
    if not index_path.is_file():
        return set()
    marked: set[str] = set()
    for line in read_text(index_path).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or not cells[-1].lower().startswith("duplicate"):
            continue
        link = re.search(r"\[\[([^\]|]+?)\]\]", cells[0])
        if link:
            marked.add(link.group(1).strip())
    return marked


def build_batches(items: list[dict]) -> dict[str, list[dict]]:
    """Per origin: greedy consecutive packing by filename order, <= BATCH_TOKEN_CAP."""
    by_origin: dict[str, list[dict]] = {}
    for item in items:
        by_origin.setdefault(item["origin"], []).append(item)

    batches: dict[str, list[dict]] = {}
    for origin, origin_items in by_origin.items():
        origin_items.sort(key=lambda i: i["filename"])
        packed: list[list[dict]] = []
        current: list[dict] = []
        current_sum = 0
        for item in origin_items:
            tokens = item["token_estimate"]
            if tokens is None or tokens > BATCH_TOKEN_CAP:
                if current:
                    packed.append(current)
                    current, current_sum = [], 0
                packed.append([item])
                continue
            if current and current_sum + tokens > BATCH_TOKEN_CAP:
                packed.append(current)
                current, current_sum = [], 0
            current.append(item)
            current_sum += tokens
        if current:
            packed.append(current)

        batches[origin] = []
        for index, batch_items in enumerate(packed):
            has_null = any(i["token_estimate"] is None for i in batch_items)
            token_sum = sum(i["token_estimate"] or 0 for i in batch_items)
            model = (
                "sonnet"
                if not has_null and token_sum <= SONNET_MAX_BATCH_TOKENS
                else "opus"
            )
            batches[origin].append({
                "origin": origin,
                "index": index,
                "files": [i["filename"] for i in batch_items],
                "token_sum": token_sum,
                "has_null_estimate": has_null,
                "model": model,
            })
    return batches


def build_waves(batches: dict[str, list[dict]]) -> list[list[dict]]:
    """Wave K = batch index K of each origin, split into sub-waves of <= WAVE_CONCURRENCY."""
    waves: list[list[dict]] = []
    deepest = max((len(b) for b in batches.values()), default=0)
    for k in range(deepest):
        tier = [
            {"origin": origin, "index": k}
            for origin in sorted(batches)
            if len(batches[origin]) > k
        ]
        for start in range(0, len(tier), WAVE_CONCURRENCY):
            waves.append(tier[start:start + WAVE_CONCURRENCY])
    return waves


def collect(wiki_root: Path, exclude: set[str], only_origin: str | None) -> dict:
    raw_root = wiki_root / "raw"
    sources_root = wiki_root / "wiki" / "sources"
    items: list[dict] = []
    origins: dict[str, dict[str, int]] = {}
    raw_total = ingested = duplicates = 0
    duplicate_files: list[str] = []

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
        marked_duplicate = duplicate_rows(origin_dir)
        for raw_file in raw_files:
            raw_total += 1
            source_page = sources_root / origin / f"{raw_file.stem}.md"
            if source_page.exists():
                ingested += 1
                continue
            if raw_file.name in marked_duplicate:
                duplicates += 1
                duplicate_files.append(f"{origin}/{raw_file.name}")
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
            "duplicates": duplicates,
            "missing": len(items),
        },
        "duplicate_files": duplicate_files,
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
    parser.add_argument(
        "--no-plan",
        action="store_true",
        help="omit the batch/wave/model dispatch plan (manifest only)",
    )
    args = parser.parse_args()

    wiki_root = resolve_wiki_root(args.vault_root.resolve())
    exclude = {o.strip() for o in args.exclude_origins.split(",") if o.strip()}
    payload = collect(wiki_root, exclude, args.origin)

    if not args.no_plan:
        batches = build_batches(payload["items"])
        payload["plan"] = {
            "constants": {
                "batch_token_cap": BATCH_TOKEN_CAP,
                "sonnet_max_batch_tokens": SONNET_MAX_BATCH_TOKENS,
                "wave_concurrency": WAVE_CONCURRENCY,
            },
            "batches": batches,
            "waves": build_waves(batches),
            "model_counts": {
                model: sum(
                    1 for bs in batches.values() for b in bs if b["model"] == model
                )
                for model in ("sonnet", "opus")
            },
        }

    output = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
