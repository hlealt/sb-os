#!/usr/bin/env python3
"""Discovery manifest + dispatch plan for sb-wiki-ingest-all.

Lists every raw source that has NOT been ingested yet, with an approximate
token count, and (with --plan, the default) builds a flat, ordered,
ONE-file-per-subagent dispatch plan:

- Files: each not-yet-ingested source is its own dispatch unit — never
  batched with another source. The orchestrator runs them STRICTLY
  SEQUENTIALLY (one sub-agent at a time), so each source gets a fresh,
  undiluted context. Ordered by origin then filename so same-origin sources
  (which reuse entities/concepts) ingest consecutively.
- Model: per file — "opus" only when the token estimate exceeds
  OPUS_TOKEN_THRESHOLD (or is unknown, the conservative default for an
  un-estimable source); "sonnet" otherwise. A dedicated single-source run
  lets Sonnet ingest at full depth; Opus is reserved for the largest sources.

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
import sys
from pathlib import Path

logging.getLogger("pypdf").setLevel(logging.ERROR)
logging.getLogger("PyPDF2").setLevel(logging.ERROR)

CHARS_PER_TOKEN = 4
DEFAULT_EXCLUDE = {"assets", "_assets"}
NON_SOURCE_FILES = {"AGENTS.md", "CLAUDE.md", "QWEN.md", "README.md"}
OPUS_TOKEN_THRESHOLD = 5_000
SIZE_KEYWORDS = {"large", "small"}


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


def assign_model(token_estimate: int | None) -> str:
    """Per-file model: Sonnet for small sources; Opus when the source reaches
    or exceeds OPUS_TOKEN_THRESHOLD tokens, or when its size is unknown (a PDF
    with no extractable text) — the conservative default for an un-estimable
    source. The same threshold defines the `large`/`small` size buckets: a
    `large` source is exactly one assign_model() routes to Opus; `small`, Sonnet."""
    if token_estimate is None or token_estimate >= OPUS_TOKEN_THRESHOLD:
        return "opus"
    return "sonnet"


def build_plan(items: list[dict]) -> list[dict]:
    """Flat, ordered, ONE-file-per-subagent dispatch plan — no batching, no waves.

    Each not-yet-ingested source is its own dispatch unit, run strictly
    sequentially by the orchestrator so every source gets a fresh, undiluted
    context. Ordered by origin then filename so same-origin sources (which reuse
    entities/concepts) ingest consecutively. Per-file model via assign_model.
    """
    ordered = sorted(items, key=lambda i: (i["origin"], i["filename"]))
    return [
        {
            "index": index,
            "origin": item["origin"],
            "filename": item["filename"],
            "path": item["path"],
            "token_estimate": item["token_estimate"],
            "model": assign_model(item["token_estimate"]),
        }
        for index, item in enumerate(ordered)
    ]


def extract_size_filter(targets: list[str]) -> tuple[str | None, list[str], str | None]:
    """Pull a `large`/`small` size keyword out of the positional targets.

    Returns (size_filter, remaining_targets, error). `large` scopes the run to
    sources Opus would ingest (>= OPUS_TOKEN_THRESHOLD, or un-estimable); `small`
    to the Sonnet bucket (< OPUS_TOKEN_THRESHOLD). At most one keyword is allowed
    and it is removed from the target list so the rest classify normally.
    """
    size_filter: str | None = None
    remaining: list[str] = []
    for token in targets:
        low = token.lower()
        if low in SIZE_KEYWORDS:
            if size_filter and size_filter != low:
                return None, [], "pass at most one size keyword ('large' or 'small')"
            size_filter = low
        else:
            remaining.append(token)
    return size_filter, remaining, None


def apply_size_filter(payload: dict, size_filter: str) -> dict:
    """Restrict an already-collected payload to one size bucket, in place.

    Keeps only items whose assign_model() matches the bucket (`large` -> opus,
    `small` -> sonnet), then recomputes `origins` and the affected totals. The
    informational `raw_total`/`ingested`/`duplicates` describe the full corpus
    and are left untouched; `size_excluded` records how many missing sources the
    keyword dropped from this run.
    """
    keep_model = "opus" if size_filter == "large" else "sonnet"
    kept = [it for it in payload["items"]
            if assign_model(it["token_estimate"]) == keep_model]
    excluded = len(payload["items"]) - len(kept)
    origins: dict[str, dict[str, int]] = {}
    for it in kept:
        bucket = origins.setdefault(it["origin"], {"missing": 0, "token_sum": 0})
        bucket["missing"] += 1
        bucket["token_sum"] += it["token_estimate"] or 0
    payload["items"] = kept
    payload["origins"] = origins
    payload["totals"]["missing"] = len(kept)
    payload["totals"]["origins_with_missing"] = len(origins)
    payload["totals"]["size_excluded"] = excluded
    return payload


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


HAS_EXT = (".md", ".pdf")


def raw_index(wiki_root: Path, exclude: set[str]) -> tuple[list[dict], set[str]]:
    """Every raw source file across origins + the set of origin folder names.

    Used to classify and resolve positional targets. Reads only; does NOT filter
    on ingested/duplicate status — that happens later, per the chosen selection.
    """
    raw_root = wiki_root / "raw"
    index: list[dict] = []
    origin_names: set[str] = set()
    for origin_dir in sorted(
        p for p in raw_root.iterdir() if p.is_dir() and p.name not in exclude
    ):
        origin = origin_dir.name
        origin_names.add(origin)
        index_name = f"{origin}.md"
        for raw_file in sorted(origin_dir.iterdir()):
            if (
                raw_file.is_file()
                and raw_file.suffix in HAS_EXT
                and raw_file.name != index_name
                and raw_file.name not in NON_SOURCE_FILES
            ):
                index.append({
                    "origin": origin,
                    "filename": raw_file.name,
                    "stem": raw_file.stem,
                    "path": raw_file,
                    "_abs": raw_file.resolve(),
                })
    return index, origin_names


def resolve_target(
    target: str, vault_root: Path, wiki_root: Path,
    index: list[dict], by_name: dict, by_stem: dict,
) -> list[dict]:
    """Resolve one positional file target to raw-source item(s), deduped by path.

    Union of strategies: a path under raw/ (joined to cwd / vault / wiki / raw
    roots); `origin/name` or `origin/stem`; a bare filename; a bare stem. The
    caller treats 0 hits as unresolved and >1 hits as ambiguous.
    """
    raw_root = wiki_root / "raw"
    abs_to_item = {it["_abs"]: it for it in index}
    matches: dict[Path, dict] = {}
    normalized = target.replace("\\", "/").strip("/")

    for base in (Path.cwd(), vault_root, wiki_root, raw_root):
        try:
            resolved = (base / target).resolve()
        except (OSError, ValueError):
            continue
        if resolved in abs_to_item:
            matches[resolved] = abs_to_item[resolved]

    parts = normalized.split("/")
    if len(parts) >= 2:
        origin, name = parts[-2], parts[-1]
        name_stem = Path(name).stem
        for it in index:
            if it["origin"] == origin and (it["filename"] == name or it["stem"] == name_stem):
                matches[it["_abs"]] = it
    elif len(parts) == 1:
        name = parts[0]
        for it in by_name.get(name, []):
            matches[it["_abs"]] = it
        for it in by_stem.get(Path(name).stem, []):
            matches[it["_abs"]] = it

    return list(matches.values())


def classify_targets(
    targets: list[str], origin_names: set[str], index: list[dict],
    vault_root: Path, wiki_root: Path,
) -> tuple[str, str | None, list[dict] | None, list]:
    """Deterministically map positional targets to a run mode — never guess.

    Returns (mode, only_origin, selected_items, errors):
      mode    — "all" (no targets) | "origin" | "files"
      errors  — list of (kind, ...) tuples; non-empty means HALT (exit 2).

    Origin mode fires ONLY for a single bare token (no .md/.pdf extension, no
    path separator) that names an origin folder. A bare token that names BOTH an
    origin folder AND a raw-file stem is a collision: halt and demand
    disambiguation. Every other shape is a file list.
    """
    if not targets:
        return "all", None, None, []

    by_name: dict[str, list[dict]] = {}
    by_stem: dict[str, list[dict]] = {}
    for it in index:
        by_name.setdefault(it["filename"], []).append(it)
        by_stem.setdefault(it["stem"], []).append(it)

    if len(targets) == 1:
        token = targets[0]
        bare = (
            Path(token).suffix.lower() not in HAS_EXT
            and "/" not in token
            and "\\" not in token
        )
        if bare:
            stem_hits = by_stem.get(token, [])
            if token in origin_names and stem_hits:
                return "files", None, None, [("collision", token, stem_hits)]
            if token in origin_names:
                return "origin", token, None, []
            # bare, not an origin → fall through to file resolution below

    selected: list[dict] = []
    errors: list = []
    for token in targets:
        hits = resolve_target(token, vault_root, wiki_root, index, by_name, by_stem)
        if not hits:
            errors.append(("unresolved", token))
        elif len(hits) > 1:
            errors.append(("ambiguous", token, hits))
        else:
            selected.append(hits[0])
    return "files", None, selected, errors


def collect_selection(wiki_root: Path, selected: list[dict]) -> dict:
    """Manifest for an explicit file list — same payload shape as collect(),
    plus `skipped_ingested[]` for listed files that already have a wiki page."""
    sources_root = wiki_root / "wiki" / "sources"
    raw_root = wiki_root / "raw"
    items: list[dict] = []
    origins: dict[str, dict[str, int]] = {}
    skipped_ingested: list[str] = []
    duplicate_files: list[str] = []
    duplicates = 0
    dup_cache: dict[str, set[str]] = {}

    for it in selected:
        origin, raw_file = it["origin"], it["path"]
        if (sources_root / origin / f"{it['stem']}.md").exists():
            skipped_ingested.append(f"{origin}/{it['filename']}")
            continue
        if origin not in dup_cache:
            dup_cache[origin] = duplicate_rows(raw_root / origin)
        if it["filename"] in dup_cache[origin]:
            duplicates += 1
            duplicate_files.append(f"{origin}/{it['filename']}")
            continue
        is_pdf = raw_file.suffix == ".pdf"
        title, date, tokens = describe_pdf(raw_file) if is_pdf else describe_md(raw_file)
        items.append({
            "path": raw_file.relative_to(wiki_root.parent).as_posix(),
            "origin": origin,
            "filename": it["filename"],
            "stem": it["stem"],
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
            "raw_total": len(selected),
            "ingested": len(skipped_ingested),
            "duplicates": duplicates,
            "missing": len(items),
        },
        "duplicate_files": duplicate_files,
        "skipped_ingested": skipped_ingested,
        "origins": origins,
        "items": items,
    }


def report_target_errors(errors: list, raw_root: Path) -> None:
    """Print human-readable, actionable messages for classify_targets errors."""
    for err in errors:
        kind = err[0]
        if kind == "collision":
            token, hits = err[1], err[2]
            where = ", ".join(sorted(f"{h['origin']}/{h['filename']}" for h in hits))
            print(
                f"ERROR: '{token}' is AMBIGUOUS - it names an origin folder AND "
                f"matches raw source(s): {where}.", file=sys.stderr)
            print(
                f"  Disambiguate to ingest the file: '{token}.md', '{token}.pdf', "
                f"or '{hits[0]['origin']}/{token}.md'.", file=sys.stderr)
        elif kind == "ambiguous":
            token, hits = err[1], err[2]
            where = ", ".join(sorted(f"{h['origin']}/{h['filename']}" for h in hits))
            print(
                f"ERROR: '{token}' matches multiple raw sources: {where}. Qualify it "
                f"with the origin prefix (e.g. '{hits[0]['origin']}/{token}').",
                file=sys.stderr)
        else:  # unresolved
            print(
                f"ERROR: '{err[1]}' matches no raw source under {raw_root}.",
                file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "targets",
        nargs="*",
        help="an origin folder name (single bare token) OR one-or-more raw "
             "filenames/paths to ingest; empty = every not-yet-ingested source. "
             "A bare 'large' or 'small' keyword scopes the run by size: 'large' "
             "= sources Opus would ingest (>= the opus token threshold or "
             "un-estimable), 'small' = the Sonnet bucket. It composes with an "
             "origin (e.g. 'every large').",
    )
    parser.add_argument("--vault-root", type=Path, default=Path.cwd())
    parser.add_argument("--report", type=Path, help="optional JSON report path")
    parser.add_argument(
        "--exclude-origins",
        default=",".join(sorted(DEFAULT_EXCLUDE)),
        help="comma-separated raw subfolders to skip (asset folders)",
    )
    parser.add_argument(
        "--origin",
        help="DEPRECATED — scope to a single origin (equivalent to passing the "
             "origin name as a positional target). Kept for back-compat.",
    )
    parser.add_argument(
        "--no-plan",
        action="store_true",
        help="omit the per-file model dispatch plan (manifest only)",
    )
    args = parser.parse_args()

    vault_root = args.vault_root.resolve()
    wiki_root = resolve_wiki_root(vault_root)
    exclude = {o.strip() for o in args.exclude_origins.split(",") if o.strip()}

    # Pull any size keyword ('large'/'small') out first; the rest classify as
    # origin/file/all. The keyword scopes WHICH sources run, never their model.
    size_filter, targets, size_error = extract_size_filter(args.targets)
    if size_error:
        print(f"ERROR: {size_error}.", file=sys.stderr)
        return 2

    # Resolve the run mode. --origin is the legacy explicit form; positional
    # targets are classified deterministically (origin folder vs. file list).
    if args.origin:
        if targets:
            print("ERROR: pass either positional targets OR --origin, not both.",
                  file=sys.stderr)
            return 2
        mode, only_origin, selected, errors = "origin", args.origin, None, []
    else:
        index, origin_names = raw_index(wiki_root, exclude)
        if size_filter and size_filter in origin_names:
            print(
                f"ERROR: '{size_filter}' is both a size keyword and an origin "
                f"folder. Use '--origin {size_filter}' to target the origin.",
                file=sys.stderr)
            return 2
        mode, only_origin, selected, errors = classify_targets(
            targets, origin_names, index, vault_root, wiki_root)

    if errors:
        report_target_errors(errors, wiki_root / "raw")
        return 2

    if mode == "files":
        payload = collect_selection(wiki_root, selected)
    else:
        payload = collect(wiki_root, exclude, only_origin)
    payload["mode"] = mode
    payload["size_filter"] = size_filter
    if size_filter:
        apply_size_filter(payload, size_filter)

    if not args.no_plan:
        files = build_plan(payload["items"])
        payload["plan"] = {
            "constants": {
                "opus_token_threshold": OPUS_TOKEN_THRESHOLD,
            },
            "files": files,
            "model_counts": {
                model: sum(1 for f in files if f["model"] == model)
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
