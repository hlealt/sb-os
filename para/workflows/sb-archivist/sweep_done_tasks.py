r"""
sb-archivist — deterministic day-rollover + Done-Task Sweep.

Performs, from a vault root, the two mechanical operations the `sb-archivist`
workflow used to describe for an agent to do by hand:

  1. Day-rollover (workflow step 2): if `.user/runtime/state/work-log.md` carries
     a frontmatter `date` older than today, MOVE it to
     `.user/runtime/state/work-log-archive/{its-date}-work-log.md` and create a
     fresh today-dated work-log from the template. Missing/empty -> create fresh.
  2. Done-Task Sweep (workflow steps 1-7): find every top-level `- [x]` task in
     `*-tasks.md` under `1-projects/`+`2-areas/`, extract each block VERBATIM,
     route it by its `✅ YYYY-MM-DD` marker (today -> work-log.md, past -> that
     date's archive log), append it under a per-source group inside the target's
     `## Completed` section (dedup by task line), and remove it from the source.

Block boundary = the `- [x]` line plus following lines until the next top-level
list item (`^- \[`), the next heading (`^#`), or EOF. Checked items indented
under an open `- [ ]` parent are column-0-excluded and never swept. Source files
keep their original CRLF/LF; work-log content is written LF.

FAIL-SAFE (data-loss floor): the sweep moves a `- [x]` block ONLY when it can
route it with confidence — i.e. the task line carries exactly one calendar-valid
`✅ YYYY-MM-DD`. A block whose task line has NO `✅ YYYY-MM-DD`, a non-calendar
date (e.g. `✅ 2026-13-40`, unpadded `✅ 2026-6-1`), or two or more DIFFERENT
`✅` dates is SKIPPED: left byte-for-byte in its source, never written to any
work-log, and reported with its source file + reason. A source file that cannot
be decoded as UTF-8 is skipped whole. The strict completed-task format contract
the parser keys on is documented in
`para/workflows/sb-vault-ops/data/tasks.md` (§ Sweep contract). Skip-not-delete
is the invariant: on ANY routing doubt the sweep refuses to remove content.

Usage:
    python sweep_done_tasks.py [--vault-path PATH] [--rollover-only]
                               [--dry-run] [--json] [--today YYYY-MM-DD]
                               [--template PATH]

Options:
    --vault-path PATH   Vault root (default: current directory).
    --rollover-only     Perform day-rollover only; skip the sweep
                        (workflow step 2 on runs that document session work).
    --dry-run           Report intended actions; write nothing.
    --json              Emit a machine-readable JSON report instead of text.
    --today YYYY-MM-DD  Override "today" (default: system date) — for testing.
    --template PATH     Work-log template (default: the repo template located
                        relative to this script).

Default action (no --rollover-only): day-rollover (idempotent) then the sweep.
Exit code 0 on success; non-zero on an unrecoverable error.
"""

import os
import re
import sys
import json
import shutil
import argparse
import datetime
from pathlib import Path
from collections import OrderedDict

# A swept task: top-level `- [x] ` at column 0 only.
DONE_RE = re.compile(r"^- \[x\] ")
# Block boundary: any top-level list item (requires the `[`) OR any heading.
# Requiring `[` ignores non-checkbox top-level `-` continuations (e.g. `- *Ref:*`).
BOUNDARY_RE = re.compile(r"^- \[|^#")
# Completion-date marker on the task line. Zero-padded 4-2-2 shape required;
# calendar validity (e.g. no month 13) is checked separately by valid_iso_date.
DATE_RE = re.compile(r"✅ (\d{4}-\d{2}-\d{2})")
# Frontmatter date of a work-log.
FM_DATE_RE = re.compile(r"^date:\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)

SCAN_DIRS = ("1-projects", "2-areas")
TASKFILE_SUFFIX = "-tasks.md"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def is_boundary(line):
    return bool(BOUNDARY_RE.match(line))


def to_lf(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def valid_iso_date(s):
    """True iff `s` is a real, zero-padded YYYY-MM-DD calendar date.

    datetime.date.fromisoformat rejects both impossible dates (2026-13-40,
    2026-02-30) and unpadded ones (2026-6-1), giving a strict validity check.
    """
    try:
        datetime.date.fromisoformat(s)
        return True
    except (ValueError, TypeError):
        return False


def routed_date(task_line, today):
    """Decide the routing date for a `- [x]` task line, fail-safe.

    Returns (date, None) when the line can be routed WITH CONFIDENCE, or
    (None, reason) when it cannot and the block must be skipped (left in source,
    never moved). Confidence requires exactly one calendar-valid `✅ YYYY-MM-DD`
    on the task line. The `today` argument is accepted for signature symmetry and
    intentionally NOT used as a fallback — a missing/invalid date is a skip, never
    a silent route-to-today (that was the data-loss path this replaces).
    """
    dates = DATE_RE.findall(task_line)
    if not dates:
        return None, "no valid ✅ YYYY-MM-DD on task line"
    valid = [d for d in dates if valid_iso_date(d)]
    if not valid:
        return None, f"✅ date not a valid calendar date: {dates[0]}"
    distinct = set(valid)
    if len(distinct) > 1:
        return None, f"multiple distinct ✅ dates: {sorted(distinct)}"
    return valid[0], None


def default_template_path():
    # script: {sb_os}/para/workflows/sb-archivist/sweep_done_tasks.py
    # template: {sb_os}/para/templates/work-log.md
    return Path(__file__).resolve().parents[2] / "templates" / "work-log.md"


def render_fresh_worklog(template_path, today, now_hm):
    """Build a fresh work-log skeleton from the template.

    Keeps frontmatter, every heading, and table header/separator rows; drops the
    `{placeholder}` example rows and instructional prose; sets today's date.
    Reproduces the de-facto "fresh from template" shape (section skeleton with
    empty bodies, table headers retained). Returns LF text ending in a newline.
    """
    lines = to_lf(Path(template_path).read_text(encoding="utf-8")).split("\n")
    out = []
    in_fm = False
    for idx, line in enumerate(lines):
        if idx == 0 and line.strip() == "---":
            in_fm = True
            out.append(line)
            continue
        if in_fm:
            if line.startswith("date:"):
                out.append(f"date: {today}")
            elif line.startswith("last_updated:"):
                out.append(f"last_updated: {today}T{now_hm}")
            else:
                out.append(line)
            if line.strip() == "---":
                in_fm = False
            continue
        # body
        if line.startswith("# Work Log"):
            out.append(f"# Work Log — {today}")
        elif "{" in line:                      # placeholder example row -> dropped
            continue
        elif line.startswith("#"):            # any section heading
            out.append(line)
        elif line.lstrip().startswith("|"):    # table header / separator row
            out.append(line)
        elif line.strip() == "":               # blank line
            out.append(line)
        # else: instruction prose -> dropped
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)     # collapse runs of blank lines
    if not text.endswith("\n"):
        text += "\n"
    return text


# --------------------------------------------------------------------------- #
# Day-rollover
# --------------------------------------------------------------------------- #

def parse_worklog_date(path):
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = FM_DATE_RE.search(raw)
    return m.group(1) if m else None


def day_rollover(state_dir, archive_dir, template_path, today, now_hm, dry_run):
    """Roll over a stale work-log. Returns a (action, detail-dict) report."""
    worklog = state_dir / "work-log.md"

    empty = (not worklog.exists()) or worklog.stat().st_size == 0
    if not empty:
        # whitespace-only counts as empty too
        try:
            empty = worklog.read_text(encoding="utf-8").strip() == ""
        except OSError:
            empty = False

    if empty:
        if not dry_run:
            state_dir.mkdir(parents=True, exist_ok=True)
            worklog.write_text(render_fresh_worklog(template_path, today, now_hm),
                               encoding="utf-8", newline="")
        return ("created-fresh", {"reason": "missing-or-empty", "date": today})

    date = parse_worklog_date(worklog)
    if date is None:
        return ("skipped", {"reason": "unparseable-date",
                            "detail": "work-log.md has no parseable frontmatter date; left as-is"})
    if date == today:
        return ("noop", {"reason": "already-today", "date": date})
    if date > today:
        return ("skipped", {"reason": "future-date",
                            "detail": f"work-log.md date {date} is after today {today}; left as-is",
                            "date": date})

    # date < today -> archive + fresh
    target = archive_dir / f"{date}-work-log.md"
    if target.exists():
        return ("skipped", {"reason": "archive-exists",
                            "detail": f"{target.name} already exists; refusing to overwrite, "
                                      f"work-log.md left as-is",
                            "date": date, "target": str(target)})
    if not dry_run:
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(worklog), str(target))          # byte-preserving rename
        worklog.write_text(render_fresh_worklog(template_path, today, now_hm),
                           encoding="utf-8", newline="")
    return ("rolled-over", {"date": date, "target": str(target), "fresh_date": today})


# --------------------------------------------------------------------------- #
# Done-Task Sweep
# --------------------------------------------------------------------------- #

def discover_sources(vault):
    """Vault-relative paths of every `*-tasks.md` under the scan dirs."""
    sources = []
    for top in SCAN_DIRS:
        base = vault / top
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                if fn.endswith(TASKFILE_SUFFIX):
                    rel = (Path(dirpath) / fn).relative_to(vault).as_posix()
                    sources.append(rel)
    return sorted(sources)


def extract_blocks(lines, today):
    """From a source file's lines, return (blocks, remove_ranges, skips).

    blocks: list of (block_text_LF, date) — block_text byte-faithful (LF), trailing
            blanks stripped. Only blocks routed WITH CONFIDENCE appear here.
    remove_ranges: list of (start, end) line ranges (end exclusive) to drop. Only
            ranges for blocks that are actually swept — a skipped block is NEVER
            added here, so it stays in source byte-for-byte (fail-safe).
    skips: list of (task_line_stripped, reason) for every `- [x]` block the parser
            could not route with confidence and therefore left in place.
    """
    n = len(lines)
    blocks, remove_ranges, skips = [], [], []
    i = 0
    while i < n:
        if DONE_RE.match(lines[i]):
            start = i
            j = i + 1
            while j < n and not is_boundary(lines[j]):
                j += 1
            date, reason = routed_date(lines[start], today)
            if reason is not None:
                # Cannot route with confidence -> SKIP: leave in source, do not
                # move, record why. No remove_range, no block appended.
                skips.append((lines[start].rstrip("\r\n").strip(), reason))
                i = j
                continue
            bl = list(lines[start:j])
            while bl and bl[-1].strip() == "":
                bl.pop()
            block_text = to_lf("".join(bl)).rstrip("\n")
            blocks.append((block_text, date))
            remove_ranges.append((start, j))
            i = j
        else:
            i += 1
    return blocks, remove_ranges, skips


def ensure_archive_worklog(path, date):
    """Create a missing target work-log (minimal skeleton). No-op if it exists."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        f"---\ndate: {date}\nlast_updated: {date}T00:00\n---\n\n"
        f"# Work Log — {date}\n\n## Completed\n"
    )
    path.write_text(content, encoding="utf-8", newline="")


def task_line_of(block_text):
    return block_text.splitlines()[0].strip()


def append_to_worklog(path, groups, today, now_hm):
    """Append swept groups into the target's ## Completed section.

    groups: list of (basename, relpath, [block_text, ...]).
    Returns the count of blocks actually appended (after dedup).
    """
    content = to_lf(path.read_text(encoding="utf-8"))
    lines = content.split("\n")

    comp_idx = next((k for k, l in enumerate(lines) if l.strip() == "## Completed"), None)
    if comp_idx is None:
        raise RuntimeError(f"No '## Completed' section in {path}")

    end_idx = len(lines)
    for k in range(comp_idx + 1, len(lines)):
        if lines[k].startswith("## "):
            end_idx = k
            break

    head, section, tail = lines[:comp_idx], lines[comp_idx:end_idx], lines[end_idx:]

    def find_group_end(sec, header):
        for k, l in enumerate(sec):
            if l.strip() == header:
                e = len(sec)
                for mm in range(k + 1, len(sec)):
                    if sec[mm].startswith("### ") or sec[mm].startswith("## "):
                        e = mm
                        break
                return e
        return None

    existing = {l.strip() for l in section if l.startswith("- [x] ")}
    appended = 0

    for basename, relpath, blocks in groups:
        header = f"### Swept from [[{basename}]] ({relpath})"
        fresh = [b for b in blocks if task_line_of(b) not in existing]
        if not fresh:
            continue
        chunk = []
        for b in fresh:
            chunk.append("")                       # blank line before each block
            chunk.extend(b.split("\n"))
            existing.add(task_line_of(b))
            appended += 1
        ge = find_group_end(section, header)
        if ge is not None:
            section = section[:ge] + chunk + section[ge:]
        else:
            addition = []
            if section and section[-1].strip() != "":
                addition.append("")
            addition.append(header)
            addition.extend(chunk)
            section = section + addition

    new_lines = head + section + tail
    out = [f"last_updated: {today}T{now_hm}" if l.startswith("last_updated:") else l
           for l in new_lines]
    path.write_text("\n".join(out), encoding="utf-8", newline="")
    return appended


def sweep(vault, state_dir, archive_dir, today, now_hm, dry_run):
    """Run the Done-Task Sweep. Returns a report dict."""
    sources = discover_sources(vault)

    # target_path -> ordered list of (basename, relpath, date, [block_text,...])
    by_target = OrderedDict()
    source_removals = OrderedDict()   # rel -> (lines, remove_ranges)
    total_blocks = 0
    skipped = []                      # [{source, task, reason}, ...] (fail-safe)

    for rel in sources:
        fpath = vault / rel
        try:
            with open(fpath, "r", encoding="utf-8", newline="") as f:   # preserve endings
                lines = f.readlines()
        except (UnicodeDecodeError, OSError) as e:
            # Cannot safely read the file -> skip it whole, touch nothing.
            skipped.append({"source": rel, "task": None,
                            "reason": f"unreadable source ({type(e).__name__}); file left untouched"})
            continue
        blocks, remove_ranges, file_skips = extract_blocks(lines, today)
        for task_line, reason in file_skips:
            skipped.append({"source": rel, "task": task_line, "reason": reason})
        if not blocks:
            continue
        basename = Path(rel).stem
        source_removals[rel] = (lines, remove_ranges)
        for block_text, date in blocks:
            total_blocks += 1
            tp = state_dir / "work-log.md" if date == today else archive_dir / f"{date}-work-log.md"
            tp = str(tp)
            groups = by_target.setdefault(tp, OrderedDict())
            key = (basename, rel, date)
            groups.setdefault(key, []).append(block_text)

    report = {
        "sources_scanned": len(sources),
        "tasks_swept": total_blocks,
        "tasks_skipped": len(skipped),
        "skipped": skipped,
        "sources_cleaned": list(source_removals.keys()),
        "worklogs_written": [],
        "appended_per_target": {},
    }

    if dry_run or total_blocks == 0:
        report["worklogs_written"] = [Path(tp).name for tp in by_target]
        report["dry_run"] = bool(dry_run)
        return report

    # Write order is APPEND-THEN-REMOVE so a block is never deleted from its
    # source before it is safely persisted in a work-log. If a target append
    # fails (e.g. a pre-existing work-log a user stripped of its `## Completed`
    # heading), the source still holds the content — the run fails loud with
    # nothing dropped, never the reverse (remove-then-append would lose the
    # block in the gap between the two writes).

    # 1) Append into each target work-log.
    for tp, groups in by_target.items():
        tp_path = Path(tp)
        date = next(iter(groups))[2]   # first group's routed date
        ensure_archive_worklog(tp_path, date)
        grouped = [(bn, rel, blocks) for (bn, rel, _d), blocks in groups.items()]
        appended = append_to_worklog(tp_path, grouped, today, now_hm)
        report["worklogs_written"].append(tp_path.name)
        report["appended_per_target"][tp_path.name] = appended

    # 2) Remove swept blocks from each source (line-ending preserving). Runs
    #    only after every append above has succeeded.
    for rel, (lines, remove_ranges) in source_removals.items():
        drop = set()
        for s, e in remove_ranges:
            drop.update(range(s, e))
        newlines = [lines[k] for k in range(len(lines)) if k not in drop]
        with open(vault / rel, "w", encoding="utf-8", newline="") as f:
            f.writelines(newlines)

    return report


# --------------------------------------------------------------------------- #
# Reporting + entry point
# --------------------------------------------------------------------------- #

def format_text_report(rollover, sweep_report):
    lines = []
    action, detail = rollover
    if action == "rolled-over":
        lines.append(f"[rollover] archived work-log.md ({detail['date']}) -> "
                     f"work-log-archive/{detail['date']}-work-log.md; "
                     f"created fresh work-log.md ({detail['fresh_date']})")
    elif action == "created-fresh":
        lines.append(f"[rollover] created fresh work-log.md ({detail['date']}) "
                     f"[{detail['reason']}]")
    elif action == "noop":
        lines.append(f"[rollover] work-log.md already current ({detail['date']}) — no change")
    else:  # skipped
        lines.append(f"[rollover] SKIPPED ({detail['reason']}): {detail.get('detail', '')}")

    if sweep_report is None:
        lines.append("[sweep] skipped (--rollover-only)")
    else:
        n = sweep_report["tasks_swept"]
        srcs = len(sweep_report["sources_cleaned"])
        logs = len(set(sweep_report["worklogs_written"]))
        prefix = "[sweep] (dry-run) would sweep" if sweep_report.get("dry_run") else "[sweep] swept"
        if n == 0:
            lines.append(f"[sweep] no done tasks to sweep "
                         f"({sweep_report['sources_scanned']} task files scanned)")
        else:
            lines.append(f"{prefix} {n} task(s) from {srcs} source file(s) "
                         f"into {logs} work-log(s)")
        skips = sweep_report.get("skipped", [])
        if skips:
            lines.append(f"[sweep] SKIPPED {len(skips)} unparseable/ambiguous "
                         f"`- [x]` block(s) — left in source, not swept:")
            for s in skips:
                where = s["source"] if s.get("task") is None else f"{s['source']}: {s['task']}"
                lines.append(f"  - SKIP ({s['reason']}) — {where}")
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description="sb-archivist day-rollover + Done-Task Sweep.")
    p.add_argument("--vault-path", default=".", help="Vault root (default: current dir)")
    p.add_argument("--rollover-only", action="store_true",
                   help="Day-rollover only; skip the sweep")
    p.add_argument("--dry-run", action="store_true", help="Report only; write nothing")
    p.add_argument("--json", action="store_true", help="Emit JSON report")
    p.add_argument("--today", default=None, help="Override today (YYYY-MM-DD), for testing")
    p.add_argument("--template", default=None, help="Work-log template path override")
    args = p.parse_args(argv)

    vault = Path(args.vault_path).resolve()
    state_dir = vault / ".user" / "runtime" / "state"
    archive_dir = state_dir / "work-log-archive"
    today = args.today or datetime.date.today().isoformat()
    now_hm = datetime.datetime.now().strftime("%H:%M")
    template_path = Path(args.template) if args.template else default_template_path()

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", today):
        print(f"error: --today must be YYYY-MM-DD, got {today!r}", file=sys.stderr)
        return 2
    if not template_path.exists():
        print(f"error: template not found: {template_path}", file=sys.stderr)
        return 2

    rollover = day_rollover(state_dir, archive_dir, template_path, today, now_hm, args.dry_run)
    sweep_report = None
    if not args.rollover_only:
        sweep_report = sweep(vault, state_dir, archive_dir, today, now_hm, args.dry_run)

    if args.json:
        print(json.dumps({"rollover": {"action": rollover[0], **rollover[1]},
                          "sweep": sweep_report}, indent=2, ensure_ascii=False))
    else:
        print(format_text_report(rollover, sweep_report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
