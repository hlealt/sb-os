#!/usr/bin/env python3
"""Deterministic support pass for sb-wiki-lint.

This script handles only mechanical wiki maintenance. It never writes
judgment-bearing index cells such as Description, Scope, or What it says.
Those gaps are emitted as a JSON queue for the LLM lint workflow.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


RAW_HEADER = "| File | Title | Date | Wiki |\n|------|-------|------|------|\n"
CONCEPT_HEADER = "| File | Description |\n|------|-------------|\n"
ENTITY_HEADER = "| File | Description |\n|------|-------------|\n"
TOPIC_HEADER = "| File | Scope |\n|------|-------|\n"
DASH = "\u2014"
NON_SOURCE_FILES = {"AGENTS.md", "CLAUDE.md", "README.md"}


@dataclass
class Report:
    mode: str
    writes: list[str] = field(default_factory=list)
    judgment_needed: list[dict[str, str]] = field(default_factory=list)
    detected: dict[str, list[str]] = field(default_factory=dict)


def _fspath(path: Path) -> str:
    """Return an OS path safe to open on Windows past the 260-char MAX_PATH.

    Local-drive paths at/over the limit get the extended-length prefix so the
    standard file APIs can open them. Non-Windows and short paths pass through.
    """
    raw = os.path.abspath(os.fspath(path))
    if os.name == "nt" and len(raw) >= 260 and not raw.startswith("\\\\?\\"):
        return "\\\\?\\" + raw
    return raw


def read_text(path: Path) -> str:
    with open(_fspath(path), "r", encoding="utf-8") as handle:
        return handle.read()


def write_text(path: Path, content: str, report: Report, apply_changes: bool) -> None:
    old = read_text(path) if os.path.exists(_fspath(path)) else None
    if old == content:
        return
    report.writes.append(str(path))
    if apply_changes:
        os.makedirs(_fspath(path.parent), exist_ok=True)
        with open(_fspath(path), "w", encoding="utf-8") as handle:
            handle.write(content)


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


def table_links(text: str) -> set[str]:
    return set(re.findall(r"\[\[([^\]]+?\.md)\]\]", text))


def make_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def derive_raw_title_and_date(path: Path) -> tuple[str, str]:
    text = read_text(path)
    fm = frontmatter(text)
    title = fm.get("title", "") or first_h1(text)
    date = fm.get("date", "") or fm.get("created", "")
    if not date:
        match = re.match(r"^(\d{4})[-_](\d{2})[-_](\d{2})", path.name)
        if match:
            date = "-".join(match.groups())
    return title, date


def sync_raw_indexes(wiki_root: Path, report: Report, apply_changes: bool) -> None:
    raw_root = wiki_root / "raw"
    if not raw_root.exists():
        return
    for origin_dir in sorted(p for p in raw_root.iterdir() if p.is_dir() and p.name != "assets"):
        index_path = origin_dir / f"{origin_dir.name}.md"
        index_text = read_text(index_path) if index_path.exists() else RAW_HEADER
        if not index_path.exists():
            write_text(index_path, index_text, report, apply_changes)
        links = table_links(index_text)
        lines = index_text.rstrip("\n").splitlines() if index_text.strip() else RAW_HEADER.rstrip("\n").splitlines()
        changed = False
        for raw_file in sorted(origin_dir.glob("*.md")):
            if raw_file.name == index_path.name or raw_file.name in NON_SOURCE_FILES or raw_file.name in links:
                continue
            title, date = derive_raw_title_and_date(raw_file)
            if title and date:
                lines.append(make_row([f"[[{raw_file.name}]]", title, date, "No"]))
                changed = True
            else:
                report.judgment_needed.append(
                    {
                        "index": str(index_path),
                        "file": str(raw_file),
                        "cell": "Title/Date",
                        "reason": "raw index row missing and title/date are not fully deterministic",
                    }
                )
        if changed:
            write_text(index_path, "\n".join(lines) + "\n", report, apply_changes)


def sync_wiki_leaf_headers_and_queue(wiki_root: Path, report: Report, apply_changes: bool) -> None:
    specs = [
        ("concepts", "concepts.md", CONCEPT_HEADER, "Description"),
        ("entities", "entities.md", ENTITY_HEADER, "Description"),
        ("topics", "topics.md", TOPIC_HEADER, "Scope"),
    ]
    for folder, index_name, header, judgment_cell in specs:
        leaf_dir = wiki_root / "wiki" / folder
        if not leaf_dir.exists():
            continue
        index_path = leaf_dir / index_name
        if not index_path.exists():
            write_text(index_path, header, report, apply_changes)
            index_text = header
        else:
            index_text = read_text(index_path)
        links = table_links(index_text)
        for page in sorted(leaf_dir.glob("*.md")):
            if page.name == index_name or page.name in links:
                continue
            report.judgment_needed.append(
                {
                    "index": str(index_path),
                    "file": str(page),
                    "cell": judgment_cell,
                    "reason": f"wiki leaf row missing; {judgment_cell} requires LLM judgment",
                }
            )


def section_body(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##+\s+{re.escape(heading)}\s*$", flags=re.M)
    match = pattern.search(text)
    if not match:
        return ""
    rest = text[match.end() :]
    next_heading = re.search(r"^##+\s+", rest, flags=re.M)
    body = rest[: next_heading.start()] if next_heading else rest
    return re.sub(r"^\s*---\s*$", "", body, flags=re.M).strip()


def preview(text: str) -> str:
    one_line = re.sub(r"\s+", " ", text).strip()
    if len(one_line) <= 280:
        return one_line
    return one_line[:277].rstrip() + "..."


def sync_source_my_take_and_queue(wiki_root: Path, report: Report, apply_changes: bool) -> None:
    sources_root = wiki_root / "wiki" / "sources"
    if not sources_root.exists():
        return
    for origin_dir in sorted(p for p in sources_root.iterdir() if p.is_dir()):
        index_path = origin_dir / f"{origin_dir.name}.md"
        if not index_path.exists():
            continue
        lines = read_text(index_path).splitlines()
        changed = False
        linked = table_links("\n".join(lines))
        for source_page in sorted(origin_dir.glob("*.md")):
            if source_page.name == index_path.name or source_page.name in linked:
                continue
            report.judgment_needed.append(
                {
                    "index": str(index_path),
                    "file": str(source_page),
                    "cell": "What it says",
                    "reason": "wiki sources row missing; factual summary requires LLM judgment",
                }
            )
        for idx, line in enumerate(lines):
            if not line.strip().startswith("|") or re.match(r"^\s*\|\s*-+", line):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 3 or cells[0] == "File":
                continue
            match = re.search(r"\[\[([^\]]+?\.md)\]\]", cells[0])
            if not match:
                continue
            source_path = origin_dir / match.group(1)
            if not os.path.exists(_fspath(source_path)):
                continue
            body = section_body(read_text(source_path), "My take")
            if body:
                new_value = preview(body)
            elif cells[2] in {DASH, "pending"}:
                new_value = cells[2]
            else:
                new_value = "pending"
            if new_value != cells[2]:
                cells[2] = new_value
                lines[idx] = make_row(cells)
                changed = True
        if changed:
            write_text(index_path, "\n".join(lines) + "\n", report, apply_changes)


SUBDIVISION_NAMING_POLICY: dict[str, tuple[str, bool]] = {
    "model": ("ai-models", True),
    "person": ("persons", False),
    "company": ("organizations", False),
    "tool": ("tools", False),
    "product": ("products", False),
    "benchmark": ("ai-benchmarks", True),
    "data-format": ("data-formats", False),
    "inference-scaffold": ("inference-scaffolds", False),
    "automation-economics": ("automation-economics", False),
    "cognitive-displacement": ("cognitive-displacements", False),
    "ai-collaboration-model": ("ai-collaboration-models", False),
}
SUBDIVISION_PROPOSE_FLOOR = 5
SUBDIVISION_TYPE_FOLDERS = ("concepts", "entities")


def collect_kind_pages(type_dir: Path) -> tuple[dict[str, list[Path]], list[Path]]:
    """Walk a type folder (flat root + per-kind subfolders) and group by `kind:`.

    Returns (kinds_map, kind_missing_pages).
    """
    pages: list[Path] = []
    leaf_index_names = {f"{type_dir.name}.md"}
    for item in type_dir.iterdir():
        if item.is_file() and item.suffix == ".md":
            if item.name in leaf_index_names or item.name in NON_SOURCE_FILES:
                continue
            pages.append(item)
        elif item.is_dir():
            sub_index = f"{item.name}.md"
            for sub in item.glob("*.md"):
                if sub.name == sub_index or sub.name in NON_SOURCE_FILES:
                    continue
                pages.append(sub)

    kinds: dict[str, list[Path]] = {}
    missing: list[Path] = []
    for page in pages:
        fm = frontmatter(read_text(page))
        kind = fm.get("kind", "").strip()
        if not kind:
            missing.append(page)
            continue
        kinds.setdefault(kind, []).append(page)
    return kinds, missing


def detect_subdivision(wiki_root: Path, report: Report) -> None:
    """Detect kinds in concepts/ and entities/ that warrant subdivision.

    Emits subdivision_proposals (count >=5) and kind_missing (pages without
    a kind: value). Never moves files; the LLM lint workflow surfaces
    proposals at step 9 and executes on user accept.
    """
    proposals: list[dict] = []
    kind_missing: list[str] = []
    for type_folder in SUBDIVISION_TYPE_FOLDERS:
        type_dir = wiki_root / "wiki" / type_folder
        if not type_dir.exists():
            continue
        kinds, missing = collect_kind_pages(type_dir)
        for page in missing:
            kind_missing.append(str(page.relative_to(wiki_root)).replace("\\", "/"))
        for kind, pages in kinds.items():
            count = len(pages)
            if count < SUBDIVISION_PROPOSE_FLOOR:
                continue
            subfolder, prefixed = SUBDIVISION_NAMING_POLICY.get(
                kind, (kind + "s" if not kind.endswith("s") else kind, False)
            )
            sample = sorted(p.stem for p in pages)[:5]
            proposals.append(
                {
                    "type": type_folder,
                    "kind": kind,
                    "count": count,
                    "suggested_subfolder": subfolder,
                    "domain_prefix_applied": prefixed,
                    "sample_pages": sample,
                    "naming_heuristic_applied": kind not in SUBDIVISION_NAMING_POLICY,
                }
            )
    report.detected["subdivision_proposals"] = proposals
    report.detected["kind_missing"] = kind_missing


def detect_broken_wikilinks(wiki_root: Path, report: Report) -> None:
    targets: set[str] = set()
    for root in [wiki_root / "wiki", wiki_root / "raw"]:
        if not root.exists():
            continue
        for item in root.rglob("*.md"):
            if "raw/assets" not in item.as_posix():
                targets.add(item.name)
    broken: list[str] = []
    wiki_dir = wiki_root / "wiki"
    if wiki_dir.exists():
        for page in wiki_dir.rglob("*.md"):
            text = read_text(page)
            for embed, target in re.findall(r"(!)?\[\[([^\]|#]+)", text):
                if embed and not target.endswith(".md"):
                    continue
                if target.endswith(".md") and Path(target).name not in targets:
                    broken.append(f"{page}: [[{target}]]")
    report.detected["broken_wikilinks"] = broken


def resolve_wiki_root(vault_root: Path) -> Path:
    manifest = json.loads(read_text(vault_root / "sb-os.json"))
    return vault_root / manifest["wiki_root"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true", help="write deterministic changes")
    parser.add_argument("--report", type=Path, help="optional JSON report path")
    args = parser.parse_args()

    wiki_root = resolve_wiki_root(args.vault_root.resolve())
    report = Report(mode="apply" if args.apply else "check")

    sync_raw_indexes(wiki_root, report, args.apply)
    sync_wiki_leaf_headers_and_queue(wiki_root, report, args.apply)
    sync_source_my_take_and_queue(wiki_root, report, args.apply)
    detect_broken_wikilinks(wiki_root, report)
    detect_subdivision(wiki_root, report)

    payload = {
        "mode": report.mode,
        "writes": report.writes,
        "judgment_needed": report.judgment_needed,
        "detected": report.detected,
    }
    output = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.report and args.apply:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
