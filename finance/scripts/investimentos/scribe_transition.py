#!/usr/bin/env python3
"""Scribe transition script — mechanical bookkeeping for thesis/decision persistence.

Replaces the scribe workflows' Steps 3–5 (cross-links + last-touched bumps,
log-entry resolution, leaf-index row) with a single atomic CLI call.

Usage:
    python scribe_transition.py --payload <json-file> [--vault-root PATH] [--dry-run]
    python scribe_transition.py --payload - [--vault-root PATH] [--dry-run]   # stdin

Exit codes:
    0  Success (or dry-run)
    1  Validation error, missing file, or partial write failure
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TODAY = date.today().isoformat()

_H2_BLOCK_RE = re.compile(r"^(## .+?)(?=\n## |\Z)", re.MULTILINE | re.DOTALL)
_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter_dict, body)."""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    fm: dict[str, str] = {}
    for line in m.group(1).split("\n"):
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            fm[key.strip()] = val.strip()
    return fm, text[m.end() :]


def _set_frontmatter_field(text: str, key: str, value: str) -> str:
    """Set or add a flat key: value in YAML frontmatter."""
    m = _FM_RE.match(text)
    if not m:
        return f"---\n{key}: {value}\n---\n\n{text}"
    lines = m.group(1).split("\n")
    new_lines: list[str] = []
    found = False
    for line in lines:
        if line.startswith(f"{key}:"):
            new_lines.append(f"{key}: {value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}: {value}")
    new_yaml = "\n".join(new_lines)
    return text[: m.start()] + f"---\n{new_yaml}\n---\n\n" + text[m.end() :].lstrip()


# ---------------------------------------------------------------------------
# Cross-link helpers
# ---------------------------------------------------------------------------

def _ensure_related_link(text: str, wikilink_line: str) -> tuple[str, str]:
    """Append *wikilink_line* to the ## Related section if absent.

    Returns (new_text, status) where status is one of:
        'added'              – link was appended to existing section
        'already-linked'     – link already present
        'created-section'    – ## Related did not exist, created it
    """
    # Look for ## Related section (must be at line start, H2 level)
    related_re = re.compile(r"^(## Related\s*\n)(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    m = related_re.search(text)
    if m:
        section_body = m.group(2)
        # Normalise whitespace for robust "already present" check
        if wikilink_line in section_body:
            return text, "already-linked"
        insert_pos = m.end(2)
        prefix = text[:insert_pos].rstrip()
        suffix = text[insert_pos:]
        new_text = prefix + "\n" + wikilink_line + "\n" + suffix
        return new_text, "added"

    # No Related section — append at EOF
    new_text = text.rstrip() + "\n\n## Related\n\n" + wikilink_line + "\n"
    return new_text, "created-section"


# ---------------------------------------------------------------------------
# Log helpers
# ---------------------------------------------------------------------------

def _delete_log_entry(text: str, entry_type: str, ref: dict) -> tuple[str, bool]:
    """Delete the matching H2 block from a log file.

    Returns (new_text, found).
    """
    lines = text.split("\n")
    h2_positions = [i for i, line in enumerate(lines) if line.startswith("## ")]

    for idx, start in enumerate(h2_positions):
        end = h2_positions[idx + 1] if idx + 1 < len(h2_positions) else len(lines)
        h2_line = lines[start]
        block = "\n".join(lines[start:end])

        if entry_type == "proposed-new-thesis":
            timestamp = ref.get("timestamp", "")
            slug = ref.get("slug", "")
            if timestamp in h2_line and slug in h2_line:
                new_lines = lines[:start] + lines[end:]
                return "\n".join(new_lines), True

        elif entry_type == "speculative-thesis-update":
            target = ref.get("target_thesis", "")
            if "- target thesis:" in block and f"[[{target}.md]]" in block:
                new_lines = lines[:start] + lines[end:]
                return "\n".join(new_lines), True

        elif entry_type == "decision-queue":
            # Generic match: timestamp+slug in H2, or target_thesis in body
            timestamp = ref.get("timestamp", "")
            slug = ref.get("slug", "")
            target = ref.get("target_thesis", "")
            if timestamp and slug and timestamp in h2_line and slug in h2_line:
                new_lines = lines[:start] + lines[end:]
                return "\n".join(new_lines), True
            if target and "- target thesis:" in block and f"[[{target}.md]]" in block:
                new_lines = lines[:start] + lines[end:]
                return "\n".join(new_lines), True

    return text, False


# ---------------------------------------------------------------------------
# Source-queue helpers
# ---------------------------------------------------------------------------

def _normalize_url(u: str) -> str:
    """Normalize a URL for authoritative equality: strip quotes, scheme, www, trailing slash; lowercase.

    Mirrors the adjudication matcher's normalization so a stored entry url and
    the ref passed by the scribe compare equal across scheme/www/trailing-slash
    variation.
    """
    if not u:
        return ""
    u = u.strip().strip('"').strip("'").lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


def _delete_source_queue_entry(text: str, ref: dict) -> tuple[str, bool]:
    """Delete the matching H2 block from {wiki_root}/source-queue.md.

    The entry is identified by ``ref['url']`` (authoritative — matched after
    URL normalization) or, when no url is given, ``ref['title']`` (exact match).
    Returns (new_text, found). The first matching block (H2 header + body, up to
    the next H2 or EOF) is removed; non-matching blocks and any preamble before
    the first H2 are preserved.
    """
    want_url = _normalize_url(ref.get("url", ""))
    want_title = (ref.get("title") or "").strip()

    lines = text.split("\n")
    h2_positions = [i for i, line in enumerate(lines) if line.startswith("## ")]

    for idx, start in enumerate(h2_positions):
        end = h2_positions[idx + 1] if idx + 1 < len(h2_positions) else len(lines)
        block_url = ""
        block_title = ""
        for bl in lines[start:end]:
            m = re.match(r"^-\s+url:\s*(.+)$", bl)
            if m and not block_url:
                block_url = m.group(1).strip()
            m = re.match(r"^-\s+title:\s*(.+)$", bl)
            if m and not block_title:
                block_title = m.group(1).strip()

        if want_url:
            matched = bool(block_url) and _normalize_url(block_url) == want_url
        else:
            matched = bool(want_title) and block_title == want_title

        if matched:
            new_lines = lines[:start] + lines[end:]
            return "\n".join(new_lines), True

    return text, False


# ---------------------------------------------------------------------------
# Index helpers
# ---------------------------------------------------------------------------

def _has_index_row(text: str, file_wikilink: str) -> bool:
    """Check whether the file wikilink already appears in a table row."""
    # Look for the wikilink preceded by '|' and whitespace inside a line
    pattern = re.compile(r"^\|[^\n]*" + re.escape(file_wikilink) + r"[^\n]*\|", re.MULTILINE)
    return bool(pattern.search(text))


def _count_table_columns(header_line: str) -> int:
    """Count columns from a markdown table header or separator line."""
    parts = header_line.split("|")
    # parts[0] and parts[-1] are empty because of leading/trailing |
    return len([p for p in parts[1:-1] if p.strip()]) if len(parts) > 2 else 2


def _append_index_row(text: str, file_wikilink: str, description: str) -> str:
    """Append a row to the leaf index, creating it if absent."""
    desc = description if len(description) <= 280 else description[:277] + "..."

    stripped = text.strip()
    if not stripped:
        row = f"| {file_wikilink} | {desc} |"
        return "---\ntype: index\n---\n\n| File | Description |\n|------|-------------|\n" + row + "\n"

    lines = stripped.split("\n")
    # Find the separator line (|---|...|) to determine column count
    insert_after = -1
    col_count = 2
    for i, line in enumerate(lines):
        if re.match(r"^\|[\-:\s|]+\|$", line.strip()):
            insert_after = i
            col_count = _count_table_columns(line)

    # Build row with empty cells for extra columns
    cells = [f" {file_wikilink} ", f" {desc} "] + [" "] * (col_count - 2)
    row = "|" + "|".join(cells) + "|"

    if insert_after == -1:
        lines.append(row)
    else:
        lines.insert(insert_after + 1, row)

    return "\n".join(lines) + "\n"


def _update_index_description(text: str, file_wikilink: str, description: str) -> tuple[str, bool]:
    """Update the Description cell of an existing row. Returns (new_text, updated)."""
    desc = description if len(description) <= 280 else description[:277] + "..."
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if file_wikilink in line and line.strip().startswith("|"):
            parts = line.split("|")
            if len(parts) >= 3:
                parts[2] = f" {desc} "
                lines[i] = "|".join(parts)
                return "\n".join(lines), True
    return text, False


# ---------------------------------------------------------------------------
# Vault / path resolution
# ---------------------------------------------------------------------------

def _resolve_wiki_root(vault_root: Path) -> Path:
    sb_os_json = vault_root / "sb-os.json"
    if not sb_os_json.exists():
        raise ValueError(f"sb-os.json not found at {sb_os_json}")
    with open(sb_os_json, "r", encoding="utf-8") as f:
        config = json.load(f)
    wiki_root_raw = config.get("wiki_root")
    if not wiki_root_raw:
        raise ValueError("wiki_root not defined in sb-os.json")
    wiki_root = Path(wiki_root_raw)
    # sb-os.json stores wiki_root vault-relative (e.g. "3-resources/knowledge-base/").
    # Resolve it UNDER the vault root so every path derives from --vault-root —
    # the isolation seam. An absolute wiki_root (as test fixtures write) is used as-is.
    if not wiki_root.is_absolute():
        wiki_root = vault_root / wiki_root
    return wiki_root


def _entity_path(wiki_root: Path, kind: str, slug: str) -> Path:
    return wiki_root / "wiki" / "entities" / kind / f"{slug}.md"


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def run(payload: dict, vault_root: Path, dry_run: bool) -> dict:
    """Validate and (optionally) execute the transition.

    Returns a report dict with keys:
        mode, edits, skipped, errors, dry_run (bool), partial (bool)
    """
    report: dict = {
        "mode": payload.get("mode"),
        "edits": [],
        "skipped": [],
        "errors": [],
        "dry_run": dry_run,
        "partial": False,
    }

    # 1. Resolve wiki_root
    try:
        wiki_root = _resolve_wiki_root(vault_root)
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        report["errors"].append(str(exc))
        return report

    mode = payload.get("mode")
    today = _TODAY

    # 2. Validate mode + required fields
    if mode == "thesis-new":
        slug = payload.get("slug")
        if not slug:
            report["errors"].append("Missing required field: slug")
            return report
        page_path = wiki_root / "wiki" / "theses" / f"{slug}.md"
        file_wikilink = f"[[{slug}.md]]"
    elif mode == "thesis-extend":
        slug = payload.get("slug")
        if not slug:
            report["errors"].append("Missing required field: slug")
            return report
        page_path = wiki_root / "wiki" / "theses" / f"{slug}.md"
        file_wikilink = f"[[{slug}.md]]"
    elif mode == "decision":
        filename = payload.get("filename")
        if not filename:
            report["errors"].append("Missing required field: filename")
            return report
        page_path = wiki_root / "wiki" / "decisions" / filename
        file_wikilink = f"[[{filename}]]"
    else:
        report["errors"].append(f"Unknown mode: {mode}")
        return report

    # 3. Page must already exist (agent writes it before calling us)
    if not page_path.exists():
        report["errors"].append(f"Page does not exist: {page_path}")
        return report

    # -----------------------------------------------------------------------
    # Build operation list (validate-all-then-write)
    # -----------------------------------------------------------------------
    Operation = tuple[Path, str, str, str]  # path, original, new, description
    operations: list[Operation] = []

    # 4. Cross-links
    if mode in ("thesis-new", "thesis-extend"):
        link_targets = payload.get("entities" if mode == "thesis-new" else "new_entities", [])
    else:
        link_targets = payload.get("links", [])

    for item in link_targets:
        kind = item.get("kind")
        item_slug = item.get("slug")
        if not kind or not item_slug:
            report["errors"].append(f"Invalid link entry: {item}")
            return report

        if mode in ("thesis-new", "thesis-extend"):
            wikilink_line = f"- [[{slug}.md]]"
        else:
            wikilink_line = f"- [[{filename.replace('.md', '')}.md]]"

        if kind == "theses":
            target_path = wiki_root / "wiki" / "theses" / f"{item_slug}.md"
        else:
            target_path = _entity_path(wiki_root, kind, item_slug)

        if not target_path.exists():
            report["skipped"].append(
                {"kind": kind, "slug": item_slug, "reason": "page-not-found", "path": str(target_path)}
            )
            continue

        try:
            original = target_path.read_text(encoding="utf-8")
        except OSError as exc:
            report["errors"].append(f"Cannot read {target_path}: {exc}")
            return report

        new_text, status = _ensure_related_link(original, wikilink_line)
        if status != "already-linked":
            new_text = _set_frontmatter_field(new_text, "last-touched", today)

        if new_text != original:
            operations.append((target_path, original, new_text, f"cross-link {kind}/{item_slug}: {status}"))
            report["edits"].append(
                {"path": str(target_path), "action": f"cross-link {status}", "kind": kind, "slug": item_slug}
            )
        else:
            report["edits"].append(
                {"path": str(target_path), "action": "cross-link already-linked", "kind": kind, "slug": item_slug}
            )

    # 5. Log resolution
    log_ref = payload.get("log_ref") or payload.get("queue_ref")
    if log_ref:
        log_path = wiki_root / "logs" / "theses.md"
        if not log_path.exists():
            report["errors"].append(f"Log file not found: {log_path}")
            return report

        try:
            original_log = log_path.read_text(encoding="utf-8")
        except OSError as exc:
            report["errors"].append(f"Cannot read {log_path}: {exc}")
            return report

        if mode == "thesis-new":
            new_log, found = _delete_log_entry(original_log, "proposed-new-thesis", log_ref)
        elif mode == "thesis-extend":
            new_log, found = _delete_log_entry(original_log, "speculative-thesis-update", log_ref)
        else:
            new_log, found = _delete_log_entry(original_log, "decision-queue", log_ref)

        if not found:
            report["errors"].append(f"Referenced log entry not found: {json.dumps(log_ref)}")
            return report

        if new_log != original_log:
            operations.append((log_path, original_log, new_log, "resolve log entry"))
            report["edits"].append({"path": str(log_path), "action": "resolve-log-entry", "ref": log_ref})

    # 5b. Source-queue resolution (decision mode only)
    # The agent JUDGES whether a source-queue entry is spent (agent-side, per
    # source-queue.md's own rule); the script performs the mechanical deletion.
    source_queue_ref = payload.get("source_queue_ref")
    if source_queue_ref:
        if mode != "decision":
            report["errors"].append("source_queue_ref is only valid in decision mode")
            return report
        if not (source_queue_ref.get("url") or source_queue_ref.get("title")):
            report["errors"].append("source_queue_ref must contain 'url' or 'title'")
            return report

        sq_path = wiki_root / "source-queue.md"
        if not sq_path.exists():
            report["errors"].append(f"Source queue file not found: {sq_path}")
            return report

        try:
            original_sq = sq_path.read_text(encoding="utf-8")
        except OSError as exc:
            report["errors"].append(f"Cannot read {sq_path}: {exc}")
            return report

        new_sq, found = _delete_source_queue_entry(original_sq, source_queue_ref)
        if not found:
            report["errors"].append(
                f"Referenced source-queue entry not found: {json.dumps(source_queue_ref)}"
            )
            return report

        if new_sq != original_sq:
            operations.append((sq_path, original_sq, new_sq, "resolve source-queue entry"))
            report["edits"].append(
                {"path": str(sq_path), "action": "resolve-source-queue-entry", "ref": source_queue_ref}
            )

    # 6. Index
    if mode in ("thesis-new", "thesis-extend"):
        index_path = wiki_root / "wiki" / "theses" / "theses.md"
    else:
        index_path = wiki_root / "wiki" / "decisions" / "decisions.md"

    description = payload.get("description") or payload.get("updated_description", "")

    if mode in ("thesis-new", "decision"):
        if index_path.exists():
            try:
                original_index = index_path.read_text(encoding="utf-8")
            except OSError as exc:
                report["errors"].append(f"Cannot read {index_path}: {exc}")
                return report
            if _has_index_row(original_index, file_wikilink):
                report["errors"].append(f"Duplicate index row for {file_wikilink}")
                return report
            new_index = _append_index_row(original_index, file_wikilink, description)
        else:
            original_index = ""
            new_index = _append_index_row("", file_wikilink, description)

        if new_index != original_index:
            operations.append((index_path, original_index, new_index, "append index row"))
            report["edits"].append(
                {"path": str(index_path), "action": "append-index-row", "file": file_wikilink, "description": description}
            )

    elif mode == "thesis-extend":
        if description and index_path.exists():
            try:
                original_index = index_path.read_text(encoding="utf-8")
            except OSError as exc:
                report["errors"].append(f"Cannot read {index_path}: {exc}")
                return report
            new_index, updated = _update_index_description(original_index, file_wikilink, description)
            if updated:
                operations.append((index_path, original_index, new_index, "update index description"))
                report["edits"].append(
                    {
                        "path": str(index_path),
                        "action": "update-index-description",
                        "file": file_wikilink,
                        "description": description,
                    }
                )

    # -----------------------------------------------------------------------
    # All validation passed — apply or report
    # -----------------------------------------------------------------------
    if dry_run:
        return report

    partial = False
    for path, _original, new_text, _desc in operations:
        try:
            path.write_text(new_text, encoding="utf-8")
        except OSError as exc:
            report["errors"].append(f"Write failed for {path}: {exc}")
            partial = True

    if partial:
        report["partial"] = True

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_report_text(report: dict) -> str:
    lines: list[str] = []
    lines.append(f"mode: {report.get('mode')}")
    lines.append(f"dry_run: {report.get('dry_run', False)}")
    lines.append("")
    if report.get("edits"):
        # Pre-write validation failure: no writes occurred; label edits as planned-only.
        # Mid-run partial failure (report["partial"] is True): some edits landed; keep
        # label as "edits:" so the caller can distinguish landed vs not-landed.
        pre_write_failure = bool(report.get("errors")) and not report.get("partial")
        edits_label = "planned (NOT applied — validation failed):" if pre_write_failure else "edits:"
        lines.append(edits_label)
        for edit in report["edits"]:
            lines.append(f"  - {edit['action']}: {edit.get('path', edit.get('file', ''))}")
    if report.get("skipped"):
        lines.append("skipped:")
        for skip in report["skipped"]:
            lines.append(f"  - {skip['kind']}/{skip['slug']}: {skip['reason']}")
    if report.get("errors"):
        lines.append("errors:")
        for err in report["errors"]:
            lines.append(f"  - {err}")
    if report.get("partial"):
        lines.append("WARNING: partial write — some edits landed, others did not")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Atomic scribe bookkeeping: cross-links, log resolution, leaf-index row."
    )
    parser.add_argument(
        "--payload",
        required=True,
        help="Path to JSON payload file, or '-' for stdin.",
    )
    parser.add_argument(
        "--vault-root",
        type=Path,
        default=None,
        help="Vault root directory (default: current working directory).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report every edit that would happen without writing.",
    )
    args = parser.parse_args(argv)

    vault_root = args.vault_root if args.vault_root else Path.cwd()
    vault_root = vault_root.resolve()

    # Load payload
    try:
        if args.payload == "-":
            payload = json.load(sys.stdin)
        else:
            with open(args.payload, "r", encoding="utf-8") as f:
                payload = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: cannot read payload: {exc}", file=sys.stderr)
        return 1

    report = run(payload, vault_root, args.dry_run)

    print(_build_report_text(report), end="")

    if report.get("errors"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
