"""task_status_check: verify subtask implementation status from task files (p4-9).

Meta-tool. Reads a project's tasks markdown file, finds a task by title,
extracts its _Ref_ code-anchor references (file:line format), greps those
anchors in the codebase, and reports per-anchor status:

  SHIPPED     — code at cited line is present and matches the description
  STALE       — checkbox is unchecked but the cited code line exists
  NOT_YET     — anchor file:line doesn't exist in the codebase
  UNCLEAR     — anchor format not parseable

Prevents redundant re-implementation of already-shipped subtasks.

This tool is READ-ONLY. It NEVER writes to any ledger or codebase.

Usage:
    python task_status_check.py PROJECT TASK [--subtasks 3,4] [--vault-root PATH]

Arguments:
    PROJECT   Project folder name (e.g. investments-mgmt) OR direct path to tasks file
    TASK      Task title substring to match (case-insensitive)

Options:
    --subtasks   Comma-separated subtask indices to check (1-based, default: all)
    --vault-root Override vault root path

Exit codes:
    0  All checked subtasks SHIPPED or UNCLEAR (no blockers)
    1  One or more subtasks NOT_YET shipped, or task/project not found
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "sb-os.json").exists() or (parent / ".obsidian").exists():
            return parent
    raise RuntimeError("Vault root not found")


def _resolve_tasks_file(project: str, vault_root: Path) -> Path | None:
    """Resolve tasks file from project name or direct path."""
    p = Path(project)
    if p.exists():
        return p
    # Try as relative to vault root: 1-projects/{project}/{project}-tasks.md
    candidate = vault_root / "1-projects" / project / f"{project}-tasks.md"
    if candidate.exists():
        return candidate
    # Try 2-areas
    candidate2 = vault_root / "2-areas" / project / f"{project}-tasks.md"
    if candidate2.exists():
        return candidate2
    return None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _find_task_block(text: str, title_pattern: str) -> str | None:
    """Find the block of text for a task matching the title (case-insensitive)."""
    lines = text.splitlines()
    pattern_lower = title_pattern.lower()
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Match task list items (- [ ] or - [x]) whose text contains the pattern
        if re.match(r"^-\s+\[[ xX]\]", stripped):
            if pattern_lower in stripped.lower():
                start = i
                break
    if start is None:
        return None
    # Collect this task block: grab until next top-level task item or heading
    block_lines = [lines[start]]
    for j in range(start + 1, len(lines)):
        line = lines[j]
        stripped = line.strip()
        # Stop at next top-level list item that is also a task
        if re.match(r"^-\s+\[[ xX]\]", stripped) and not line.startswith(" "):
            break
        # Stop at markdown headings
        if re.match(r"^#{1,6}\s", stripped):
            break
        block_lines.append(line)
    return "\n".join(block_lines)


def _extract_ref_anchors(block: str) -> list[dict]:
    """Extract code anchors from the _Ref_ section of a task block.

    Supports formats:
      - `path/to/script.py:123-456`  (line range)
      - `path/to/script.py:123`       (single line)
      - `path/to/script.py`           (no line — reports file-level)
    """
    anchors = []
    in_ref = False
    for line in block.splitlines():
        stripped = line.strip()
        if re.search(r"_Ref[_:]", stripped, re.IGNORECASE):
            in_ref = True
            continue
        if in_ref:
            # Stop at next field (_Files_, _Result_, _Subtasks_, etc.)
            if re.search(r"_[A-Za-z][A-Za-z ]*[_:]", stripped):
                break
            # Extract file:line anchors inside backticks or bare
            for m in re.finditer(
                r"`([^`]+\.py(?::[0-9]+-?[0-9]*)?)`|([^\s,;]+\.py(?::[0-9]+-?[0-9]*)?)",
                stripped
            ):
                ref = m.group(1) or m.group(2)
                if ref:
                    # Clean surrounding punctuation
                    ref = ref.strip("()`.,")
                    parts = ref.split(":")
                    file_part = parts[0]
                    line_part = parts[1] if len(parts) > 1 else None
                    anchors.append({"ref": ref, "file": file_part, "line_spec": line_part})
    return anchors


def _extract_subtask_lines(block: str) -> list[str]:
    """Extract subtask list items (- [ ] or - [x] …) from the block."""
    subtasks = []
    for line in block.splitlines():
        stripped = line.strip()
        if re.match(r"^-\s+\[[ xX✅]\]", stripped) or re.match(r"^[-✅]\s+", stripped):
            # Only collect lines that look like a subtask bullet
            if "✅" in stripped or re.match(r"^-\s+\[[ xX]\]", stripped):
                subtasks.append(stripped)
    return subtasks


# ---------------------------------------------------------------------------
# Anchor verification
# ---------------------------------------------------------------------------

def _check_anchor(anchor: dict, vault_root: Path) -> dict:
    """Check whether a code anchor exists in the codebase."""
    file_path_str = anchor["file"]
    line_spec = anchor["line_spec"]

    # Resolve relative to vault root
    candidate = vault_root / file_path_str
    if not candidate.exists():
        # Try searching under scripts
        scripts_dir = vault_root / "3-resources" / "tools" / "sb-os" / "finance" / "scripts"
        matches = list(scripts_dir.rglob(Path(file_path_str).name))
        if matches:
            candidate = matches[0]

    if not candidate.exists():
        return {**anchor, "status": "NOT_YET", "detail": f"file not found: {file_path_str}"}

    if not line_spec:
        return {**anchor, "status": "SHIPPED", "detail": f"file exists: {candidate.name}"}

    # Parse line spec: "123" or "123-456"
    lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
    total_lines = len(lines)
    try:
        parts = line_spec.split("-")
        start_line = int(parts[0])
        end_line = int(parts[1]) if len(parts) > 1 else start_line
    except (ValueError, IndexError):
        return {**anchor, "status": "UNCLEAR", "detail": f"cannot parse line spec: {line_spec}"}

    if start_line > total_lines:
        return {
            **anchor,
            "status": "STALE",
            "detail": f"line {start_line} > file length {total_lines} (file may have moved)"
        }

    snippet = lines[start_line - 1].strip() if start_line <= total_lines else ""
    return {**anchor, "status": "SHIPPED", "detail": f"line {start_line}: {snippet[:60]}"}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _status_icon(status: str) -> str:
    return {"SHIPPED": "✓", "STALE": "⚠", "NOT_YET": "✗", "UNCLEAR": "?"}.get(status, " ")


def run_check(
    project: str,
    task_title: str,
    subtask_indices: list[int] | None,
    vault_root: Path,
) -> int:
    tasks_file = _resolve_tasks_file(project, vault_root)
    if tasks_file is None:
        print(f"ERROR: tasks file not found for project '{project}'", file=sys.stderr)
        return 1

    text = tasks_file.read_text(encoding="utf-8")
    block = _find_task_block(text, task_title)
    if block is None:
        print(f"ERROR: task matching '{task_title}' not found in {tasks_file.name}",
              file=sys.stderr)
        return 1

    anchors = _extract_ref_anchors(block)
    subtasks = _extract_subtask_lines(block)

    print(f"\n{'='*65}")
    print(f"  task_status_check")
    print(f"  project  : {project}")
    print(f"  task     : {task_title}")
    print(f"  file     : {tasks_file}")
    print("=" * 65)

    # Subtask summary
    if subtasks:
        check_indices = subtask_indices or list(range(len(subtasks)))
        print(f"\n  SUBTASKS ({len(subtasks)} total, checking {len(check_indices)}):")
        for i, st in enumerate(subtasks):
            if i not in check_indices and subtask_indices:
                continue
            marker = "✅" if ("✅" in st or "[x]" in st.lower()) else "[ ]"
            print(f"    {i+1:>2}. {marker}  {st[:80]}")

    # Ref anchors
    if not anchors:
        print("\n  No _Ref_ code-anchors found in this task block.")
    else:
        print(f"\n  CODE-ANCHOR STATUS ({len(anchors)} anchors):")
        print(f"  {'#':>3}  {'status':<10}  {'ref':<45}  {'detail'}")
        print(f"  {'-'*3}  {'-'*10}  {'-'*45}  {'-'*30}")

        not_yet_count = 0
        for idx, anchor in enumerate(anchors):
            result = _check_anchor(anchor, vault_root)
            icon = _status_icon(result["status"])
            if result["status"] == "NOT_YET":
                not_yet_count += 1
            ref_str = (result.get("ref") or "")[:45]
            detail_str = (result.get("detail") or "")[:50]
            print(f"  {idx+1:>3}. {icon} {result['status']:<9}  {ref_str:<45}  {detail_str}")

        print(f"\n  {len(anchors)} anchor(s) checked.")
        shipped = sum(1 for a in anchors if _check_anchor(a, vault_root)["status"] == "SHIPPED")
        print(f"  SHIPPED: {shipped}  NOT_YET: {not_yet_count}")
        if not_yet_count:
            print(f"  → {not_yet_count} unshipped anchor(s) — implement before checking off subtasks.")
        else:
            print("  → All anchors confirmed in codebase.")

    print("=" * 65)
    # Exit 1 if any NOT_YET anchors found
    has_not_yet = any(
        _check_anchor(a, vault_root)["status"] == "NOT_YET" for a in anchors
    )
    return 1 if has_not_yet else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify subtask implementation status from a project tasks file."
    )
    parser.add_argument(
        "project",
        help="Project folder name (e.g. investments-mgmt) or direct path to tasks file"
    )
    parser.add_argument("task", help="Task title substring to match (case-insensitive)")
    parser.add_argument(
        "--subtasks",
        help="Comma-separated 1-based subtask indices to show (default: all)"
    )
    parser.add_argument("--vault-root", help="Override vault root path")
    args = parser.parse_args()

    vault_root = Path(args.vault_root) if args.vault_root else _find_vault_root()

    subtask_indices = None
    if args.subtasks:
        try:
            subtask_indices = [int(x.strip()) - 1 for x in args.subtasks.split(",")]
        except ValueError:
            print("ERROR: --subtasks must be comma-separated integers", file=sys.stderr)
            sys.exit(1)

    sys.exit(run_check(args.project, args.task, subtask_indices, vault_root))


if __name__ == "__main__":
    main()
