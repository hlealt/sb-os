#!/usr/bin/env python3
"""sb-task — agent CLI for sb-os vault task files (`*-tasks.md`).

Run `sb-task -h` for the command inventory and `sb-task <command> -h` for
per-command help. This docstring deliberately does not re-list commands —
the argument parser is the single source of truth.

Format contract: para/workflows/sb-vault-ops/data/tasks.md (sb-os repo).
"""

import argparse
import contextlib
import difflib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------- constants

PROG = "sb-task"
DATE_EMOJI = "\U0001F4C5"   # 📅
DONE_EMOJI = "✅"       # ✅

NUMBER_RE = re.compile(r"^\d+(?:\.\d+)*[a-z]?$")
LINE_REF_RE = re.compile(r"^[Ll](\d+)$")   # positional ref: L110 = file line 110
TASK_LINE_RE = re.compile(r"^- \[( |x)\] (.*)$")
DUE_RE = re.compile(DATE_EMOJI + r" (\d{4}-\d{2}-\d{2})")
DONE_RE = re.compile(DONE_EMOJI + r" ?(\d{4}-\d{2}-\d{2})")
TAG_RE = re.compile(r"(?:(?<=\s)|^)#([A-Za-z0-9_/-]+)")
HEADING_RE = re.compile(r"^#{1,6} ")
MOSCOW_RE = re.compile(r"^#### (Must|Should|Could)\s*$", re.IGNORECASE)
SUB_CHECKBOX_RE = re.compile(r"^(\s+)- \[( |x)\] (.*)$")
FIELD_RE = re.compile(r"^(\s+)- _([A-Za-z][A-Za-z-]*):_\s*(.*)$")

MOSCOW_LEVELS = ["Must", "Should", "Could"]
DIFF_CANON = {"easy": "easy", "med": "med", "hard": "hard",
              "low": "easy", "medium": "med", "high": "hard"}
FIELD_ORDER = ["Why", "Goal", "Context", "Criteria", "Ref", "Depends",
               "Done-after", "Review", "Reschedule", "Subtasks"]
DUE_BUCKETS = ["overdue", "today", "tomorrow", "week", "month", "later", "none"]

USE_COLOR = False


class CliError(Exception):
    """Teaching refusal: what was refused, why, the fix, the escape."""

    def __init__(self, code, message, hint=None, exit_code=1):
        super().__init__(message)
        self.code = code
        self.hint = hint
        self.exit_code = exit_code


# ---------------------------------------------------------------- output

def emit(args, text_lines, json_obj):
    if args.json:
        print(json.dumps(json_obj, ensure_ascii=False, indent=2))
    else:
        for ln in text_lines:
            print(ln)


def color(s, c):
    if not USE_COLOR:
        return s
    codes = {"dim": 2, "red": 31, "green": 32, "yellow": 33, "cyan": 36}
    return f"\x1b[{codes[c]}m{s}\x1b[0m"


def fail(args, err: CliError):
    if args.json:
        print(json.dumps({"ok": False, "error": {
            "code": err.code, "message": str(err), "hint": err.hint}},
            ensure_ascii=False, indent=2))
    else:
        print(f"refused: {err}", file=sys.stderr)
        if err.hint:
            print(err.hint, file=sys.stderr)
    return err.exit_code


def text_arg(value):
    """Shell-safe free text: @path reads a file, @- reads stdin."""
    if value is None:
        return None
    if value == "@-":
        return sys.stdin.read().strip()
    if value.startswith("@") and len(value) > 1:
        p = Path(value[1:])
        if not p.is_file():
            raise CliError("bad-at-file", f"@file not found: {p}",
                           hint="pass literal text, or @<path> to an existing file, or @- for stdin")
        return p.read_text(encoding="utf-8").strip()
    return value


# ---------------------------------------------------------------- vault + files

def find_vault_root(explicit):
    candidates = []
    if explicit:
        candidates.append(Path(explicit).resolve())
    env = os.environ.get("SB_TASK_VAULT")
    if env:
        candidates.append(Path(env).resolve())
    for start in (Path.cwd(), Path(__file__).resolve().parent):
        cur = start
        while True:
            candidates.append(cur)
            if cur.parent == cur:
                break
            cur = cur.parent
    for c in candidates:
        if (c / "sb-os.json").is_file():
            return c
    raise CliError("no-vault",
                   "no vault root found (no sb-os.json walking up from cwd or the CLI's own path)",
                   hint="run from inside the vault, or pass --vault <vault-root>", exit_code=3)


def sb_os_root(vault):
    cfg = vault / "sb-os.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        p = data.get("sb_os_path")
        if p:
            resolved = (vault / p) if not Path(p).is_absolute() else Path(p)
            if resolved.is_dir():
                return resolved
    except (OSError, json.JSONDecodeError):
        pass
    # fall back to this file's own repo (…/para/cli/sb-task/sb_task.py)
    return Path(__file__).resolve().parents[3]


def load_sweep_validator(vault):
    p = sb_os_root(vault) / "para" / "workflows" / "sb-archivist" / "sweep_done_tasks.py"
    if not p.is_file():
        return None, str(p)
    spec = importlib.util.spec_from_file_location("sweep_done_tasks", p)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return None, str(p)
    return getattr(mod, "validate_completion_line", None), str(p)


def discover_task_files(vault):
    out = []
    for top in ("1-projects", "2-areas"):
        base = vault / top
        if not base.is_dir():
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in sorted(files):
                if f.endswith("-tasks.md"):
                    out.append(Path(root) / f)
    return sorted(out)


def resolve_task_file(vault, spec_str):
    """<file> = vault-relative path OR unique task-file name substring."""
    direct = (vault / spec_str)
    if direct.is_file():
        return direct.resolve()
    if Path(spec_str).is_file():
        return Path(spec_str).resolve()
    known = discover_task_files(vault)
    needle = spec_str.lower().removesuffix(".md").removesuffix("-tasks")
    hits = [p for p in known if needle in p.name.lower()]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        exact = [p for p in hits if p.name.lower() == f"{needle}-tasks.md"]
        if len(exact) == 1:
            return exact[0]
    rel = [str(p.relative_to(vault)) for p in known]
    if not hits:
        sugg = difflib.get_close_matches(spec_str, [p.stem for p in known], n=3, cutoff=0.4)
        raise CliError("file-not-found",
                       f"'{spec_str}' matches no task file",
                       hint=("did you mean: " + ", ".join(sugg) + "\n" if sugg else "")
                       + "list them all: sb-task files", exit_code=2)
    raise CliError("file-ambiguous",
                   f"'{spec_str}' matches {len(hits)} task files",
                   hint="matches:\n  " + "\n  ".join(str(p.relative_to(vault)) for p in hits),
                   exit_code=2)


# ---------------------------------------------------------------- file model

class TaskFile:
    """Line-precise model: per-line eol preserved; untouched lines never reformatted."""

    def __init__(self, path):
        self.path = path
        try:
            raw = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            raise CliError("bad-encoding", f"{path} is not valid UTF-8", exit_code=3)
        self.bom = raw.startswith("﻿")
        if self.bom:
            raw = raw[1:]
        self.lines, self.eols = [], []
        for piece in raw.splitlines(keepends=True):
            body = piece.rstrip("\r\n")
            self.lines.append(body)
            self.eols.append(piece[len(body):])
        counts = {}
        for e in self.eols:
            if e:
                counts[e] = counts.get(e, 0) + 1
        self.default_eol = max(counts, key=counts.get) if counts else "\n"
        self.mtime = path.stat().st_mtime
        self.parse()

    # -- parsing

    def parse(self):
        self.tasks = []
        section = None
        i, n = 0, len(self.lines)
        while i < n:
            line = self.lines[i]
            m = MOSCOW_RE.match(line)
            if m:
                section = m.group(1).capitalize()
                i += 1
                continue
            if HEADING_RE.match(line):
                section = None
                i += 1
                continue
            tm = TASK_LINE_RE.match(line)
            if tm:
                end = i + 1
                while end < n and not TASK_LINE_RE.match(self.lines[end]) \
                        and not HEADING_RE.match(self.lines[end]):
                    end += 1
                while end > i + 1 and self.lines[end - 1].strip() == "":
                    end -= 1
                self.tasks.append(Task(self, i, end, tm.group(1) == "x", tm.group(2), section))
                i = end
                continue
            i += 1

    def reparse(self):
        self.parse()

    def find_section(self, level):
        for i, line in enumerate(self.lines):
            m = MOSCOW_RE.match(line)
            if m and m.group(1).capitalize() == level:
                return i
        return None

    def ensure_section(self, level):
        idx = self.find_section(level)
        if idx is not None:
            return idx
        if self.lines and self.lines[-1].strip() != "":
            self.insert_line(len(self.lines), "")
        self.insert_line(len(self.lines), f"#### {level}")
        self.insert_line(len(self.lines), "")
        return len(self.lines) - 2

    # -- line surgery

    def insert_line(self, idx, text, eol=None):
        if self.lines and self.eols[-1] == "" and idx > len(self.lines) - 1:
            self.eols[-1] = self.default_eol
        self.lines.insert(idx, text)
        self.eols.insert(idx, eol if eol is not None else self.default_eol)

    def remove_lines(self, start, end):
        removed = self.lines[start:end]
        del self.lines[start:end]
        del self.eols[start:end]
        if start < len(self.lines) and self.lines[start].strip() == "" \
                and (start == 0 or self.lines[start - 1].strip() == ""):
            del self.lines[start]
            del self.eols[start]
        return removed

    def insert_block(self, heading_idx, block_lines):
        idx = heading_idx + 1
        if idx < len(self.lines) and self.lines[idx].strip() == "":
            idx += 1
        else:
            self.insert_line(idx, "")
            idx += 1
        for off, text in enumerate(block_lines):
            self.insert_line(idx + off, text)
        after = idx + len(block_lines)
        if after < len(self.lines) and self.lines[after].strip() != "":
            self.insert_line(after, "")
        return idx

    def save(self, args):
        if getattr(args, "dry_run", False):
            return False
        if self.path.exists() and self.path.stat().st_mtime != self.mtime:
            raise CliError("file-changed",
                           f"{self.path.name} changed on disk since it was read",
                           hint="re-run the command (it re-reads the file); nothing was written",
                           exit_code=3)
        payload = ("﻿" if self.bom else "") + "".join(
            body + eol for body, eol in zip(self.lines, self.eols))
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".sbtask~")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(payload)
            # A sync client / file watcher (Obsidian, AV) can hold the target
            # briefly after a preceding write; retry before refusing.
            last = None
            for pause in (0, 0.05, 0.1, 0.25, 0.5, 1.0):
                if pause:
                    time.sleep(pause)
                try:
                    os.replace(tmp, self.path)
                    last = None
                    break
                except PermissionError as e:
                    last = e
            if last is not None:
                raise CliError("file-locked",
                               f"{self.path.name} is held by another process "
                               f"(sync client / file watcher?) — gave up after 6 attempts",
                               hint="nothing was written; wait a moment and re-run the same command",
                               exit_code=3)
        finally:
            if os.path.exists(tmp):
                with contextlib.suppress(OSError):
                    os.remove(tmp)
        self.mtime = self.path.stat().st_mtime
        return True


class Task:
    def __init__(self, tf, start, end, done, rest, section):
        self.tf = tf
        self.start = start
        self.end = end
        self.done = done
        self.section = section
        self.rest = rest
        self.due = None
        self.number = None
        m = DUE_RE.match(rest)
        work = rest
        if m:
            self.due = m.group(1)
            work = rest[m.end():].lstrip()
        first, _, tail = work.partition(" ")
        if NUMBER_RE.match(first) and tail:
            self.number = first
            work = tail
        self.title_raw = work
        dm = DONE_RE.search(rest)
        self.done_date = dm.group(1) if dm else None
        self.tags = TAG_RE.findall(rest)
        self.difficulty = next((t[2:] for t in self.tags if t.startswith("d/")), None)
        self.batch = next((t.split("/", 1)[1] for t in self.tags
                           if t.startswith(("b/", "batch/"))), None)
        self.wip = "wip" in self.tags

    @property
    def line(self):
        return self.tf.lines[self.start]

    def title_clean(self):
        t = self.title_raw
        t = DONE_RE.sub("", t)
        t = TAG_RE.sub("", t)
        t = re.sub(r"\s*→\s+\S+.*$", "", t)   # trailing "→ path (notes)"
        return re.sub(r"\s{2,}", " ", t).strip()

    def block_lines(self):
        return self.tf.lines[self.start:self.end]

    # -- sub-bullet structure

    def field_line(self, name):
        for i in range(self.start + 1, self.end):
            fm = FIELD_RE.match(self.tf.lines[i])
            if fm and fm.group(2).lower() == name.lower():
                return i
        return None

    def field_extent(self, idx):
        """[idx, j) — the field line plus its deeper-indented children."""
        indent = len(FIELD_RE.match(self.tf.lines[idx]).group(1))
        j = idx + 1
        while j < self.end:
            line = self.tf.lines[j]
            if line.strip() == "":
                break
            cur = len(line) - len(line.lstrip())
            if cur <= indent:
                break
            j += 1
        return j

    def present_fields(self):
        out = {}
        for i in range(self.start + 1, self.end):
            fm = FIELD_RE.match(self.tf.lines[i])
            if fm:
                out.setdefault(fm.group(2).capitalize(), i)
        return out

    def field_insert_idx(self, name):
        """Insertion point honoring the canonical field order."""
        present = self.present_fields()
        try:
            rank = FIELD_ORDER.index(name)
        except ValueError:
            rank = len(FIELD_ORDER)
        idx = self.start + 1
        for f, i in present.items():
            if f in FIELD_ORDER and FIELD_ORDER.index(f) < rank:
                idx = max(idx, self.field_extent(i))
        return idx

    def subtasks(self):
        fl = self.field_line("Subtasks")
        out = []
        if fl is None:
            return fl, out
        for i in range(fl + 1, self.field_extent(fl)):
            sm = SUB_CHECKBOX_RE.match(self.tf.lines[i])
            if sm:
                out.append({"idx": i, "done": sm.group(2) == "x", "text": sm.group(3)})
        return fl, out

    def depends(self):
        fl = self.field_line("Depends")
        if fl is None:
            return fl, []
        val = FIELD_RE.match(self.tf.lines[fl]).group(3)
        return fl, [d.strip() for d in val.split(",") if d.strip()]

    def done_after(self):
        """Finish-to-finish gates: refs this task may not complete before."""
        fl = self.field_line("Done-after")
        if fl is None:
            return fl, []
        val = FIELD_RE.match(self.tf.lines[fl]).group(3)
        return fl, [d.strip() for d in val.split(",") if d.strip()]

    def to_json(self):
        _, subs = self.subtasks()
        _, deps = self.depends()
        _, gates = self.done_after()
        return {
            "number": self.number,
            "title": self.title_clean(),
            "status": "done" if self.done else ("wip" if self.wip else "open"),
            "moscow": self.section.lower() if self.section else None,
            "due": self.due,
            "done_date": self.done_date,
            "difficulty": self.difficulty,
            "batch": self.batch,
            "wip": self.wip,
            "subtasks": {"done": sum(1 for s in subs if s["done"]), "total": len(subs)},
            "depends": deps,
            "done_after": gates,
            "tags": self.tags,
            "line": self.start + 1,
        }


# ---------------------------------------------------------------- task refs

def resolve_task(tf, ref, vault):
    by_number = [t for t in tf.tasks if t.number == ref]
    if len(by_number) == 1:
        return by_number[0]
    if len(by_number) > 1:
        raise CliError("ref-ambiguous",
                       f"number '{ref}' appears on {len(by_number)} tasks (numbers must be unique)",
                       hint="fix the duplicates: sb-task edit <file> <title-substring> --number <new>",
                       exit_code=2)
    m = LINE_REF_RE.match(ref)
    if m:
        n = int(m.group(1))
        # a line anywhere inside a task's block resolves to that task
        hit = [t for t in tf.tasks if t.start + 1 <= n <= t.end]
        if len(hit) == 1:
            return hit[0]
        raise CliError("ref-not-found",
                       f"line {n} is not inside any task block in {tf.path.name}",
                       hint=f"line refs shift on every edit — re-read them: "
                            f"sb-task list {tf.path.name}",
                       exit_code=2)
    low = ref.lower()
    exact = [t for t in tf.tasks if t.title_clean().lower() == low]
    if len(exact) == 1:
        return exact[0]
    subs = [t for t in tf.tasks if low in t.title_clean().lower()]
    if len(subs) == 1:
        return subs[0]
    if len(subs) > 1:
        listing = "\n  ".join(f"{t.number or '-'}  {t.title_clean()[:70]}" for t in subs[:8])
        raise CliError("ref-ambiguous",
                       f"'{ref}' matches {len(subs)} tasks in {tf.path.name}",
                       hint="matches:\n  " + listing + "\nuse the number, or a longer substring",
                       exit_code=2)
    titles = [t.title_clean() for t in tf.tasks] + [t.number for t in tf.tasks if t.number]
    sugg = difflib.get_close_matches(ref, titles, n=3, cutoff=0.3)
    raise CliError("ref-not-found",
                   f"no task matching '{ref}' in {tf.path.name}",
                   hint=("did you mean: " + " | ".join(sugg) + "\n" if sugg else "")
                   + f"see them all: sb-task list {tf.path.name}", exit_code=2)


def parse_depend_ref(ref):
    """'1.2' (same file) or 'path/to/x-tasks.md#1.2' (cross-file)."""
    if "#" in ref:
        path, _, num = ref.rpartition("#")
        return path, num
    return None, ref


def check_edge_refs(tf, task, refs, vault, field):
    numbers = {t.number for t in tf.tasks if t.number}
    for d in refs:
        path, num = parse_depend_ref(d)
        if path is None:
            if not NUMBER_RE.match(num):
                raise CliError(f"bad-{field}", f"'{d}' is not a task number",
                               hint=f"{field} refs are task numbers like 1.2 or 3b; "
                                    "cross-file: <vault-relative-path>#<number>")
            if num not in numbers:
                sugg = difflib.get_close_matches(num, sorted(numbers), n=3, cutoff=0.3)
                raise CliError(f"bad-{field}",
                               f"{field} ref '{num}' matches no numbered task in {tf.path.name}",
                               hint=("did you mean: " + ", ".join(sugg) + "\n" if sugg else "")
                               + "numbers present: " + (", ".join(sorted(numbers)) or "(none)"))
            if num == task.number:
                raise CliError(f"bad-{field}", f"a task cannot {field.replace('-', ' ')} itself")
        else:
            other = vault / path
            if not other.is_file():
                raise CliError(f"bad-{field}", f"cross-file {field} target not found: {path}",
                               hint="the path is vault-relative; check: sb-task files")
            otf = TaskFile(other)
            if num not in {t.number for t in otf.tasks if t.number}:
                raise CliError(f"bad-{field}",
                               f"'{num}' matches no numbered task in {path}")


def validate_depends(tf, task, deps, vault, done_after=None):
    """Validate refs + acyclicity of the UNION of _Depends:_ and _Done-after:_.

    Both relations order FINISH times (depends: A starts — so also finishes —
    after B finishes; done-after: A finishes after B finishes), so a cycle in
    the union is a real deadlock even when each relation alone is acyclic.
    `deps` / `done_after` are the proposed sets for `task`; None keeps current.
    """
    if deps is None:
        deps = task.depends()[1]
    if done_after is None:
        done_after = task.done_after()[1]
    check_edge_refs(tf, task, deps, vault, "depends")
    check_edge_refs(tf, task, done_after, vault, "done-after")
    same = lambda refs: [parse_depend_ref(x)[1] for x in refs
                         if parse_depend_ref(x)[0] is None]
    edges = {}
    for t in tf.tasks:
        if not t.number:
            continue
        edges[t.number] = same(t.depends()[1]) + same(t.done_after()[1])
    if task.number:
        edges[task.number] = same(deps) + same(done_after)
    state = {}
    def dfs(node, trail):
        state[node] = "gray"
        for nxt in edges.get(node, []):
            if state.get(nxt) == "gray":
                cycle = " -> ".join(trail + [node, nxt])
                raise CliError("dag-cycle",
                               f"ordering cycle across _Depends:_/_Done-after:_ — {cycle}",
                               hint="this would deadlock: every task in the cycle finishes "
                                    "after another in it, so none can ever complete. Remove "
                                    "one edge (--remove-depends / --remove-done-after), or "
                                    "split the gated task so its build half and its delivery "
                                    "half are separate tasks")
            if state.get(nxt) != "black":
                dfs(nxt, trail + [node])
        state[node] = "black"
    for node in edges:
        if state.get(node) != "black":
            dfs(node, [])


# ---------------------------------------------------------------- line builders

def build_main_line(done, due, number, title, difficulty=None, batch=None,
                    wip=False, done_date=None, tags=None):
    parts = [f"- [{'x' if done else ' '}]"]
    if due:
        parts.append(f"{DATE_EMOJI} {due}")
    if number:
        parts.append(number)
    parts.append(title)
    if difficulty:
        parts.append(f"#d/{difficulty}")
    if batch:
        parts.append(f"#b/{batch}")
    for t in (tags or []):
        parts.append(f"#{t}")
    if wip:
        parts.append("#wip")
    if done_date:
        parts.append(f"{DONE_EMOJI} {done_date}")
    return " ".join(parts)


def check_date(value, flag):
    if value in (None, "none"):
        return value
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        raise CliError("bad-date", f"{flag} must be YYYY-MM-DD (zero-padded), got '{value}'")
    y, mo, d = map(int, value.split("-"))
    try:
        date(y, mo, d)
    except ValueError:
        raise CliError("bad-date", f"{flag}: '{value}' is not a calendar date")
    return value


def check_number(tf, value, current_task=None):
    if value in (None, "none"):
        return value
    if not NUMBER_RE.match(value):
        raise CliError("bad-number",
                       f"'{value}' is not a valid task number (digits/dots + optional letter, e.g. 1.2 or 3b)")
    for t in tf.tasks:
        if t.number == value and t is not current_task:
            raise CliError("number-taken",
                           f"number '{value}' is already on: {t.title_clean()[:60]}",
                           hint="numbers are unique per file; pick a free one "
                                f"(sb-task list {tf.path.name} shows them)")
    return value


def canon_tag(value):
    """Normalize + validate a free tag; the structured ones have their own flags."""
    tag = value.lstrip("#").strip()
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_/-]*", tag):
        raise CliError("bad-tag", f"'{value}' is not a valid tag",
                       hint="tags are #kebab-or-slash words, e.g. decision, mod/ignite")
    if tag.startswith(("d/", "b/", "batch/")) or tag == "wip":
        raise CliError("bad-tag", f"'#{tag}' is a structured tag with its own flag",
                       hint="use --difficulty / --batch / --status wip instead")
    return tag


def canon_difficulty(value):
    if value in (None, "none"):
        return value
    low = value.lower()
    if low not in DIFF_CANON:
        raise CliError("bad-difficulty",
                       f"difficulty '{value}' unknown",
                       hint="use easy | med | hard (aliases: low->easy, high->hard)")
    return DIFF_CANON[low]


def due_bucket(due_str, today):
    if not due_str:
        return "none"
    d = date.fromisoformat(due_str)
    if d < today:
        return "overdue"
    if d == today:
        return "today"
    if d == today + timedelta(days=1):
        return "tomorrow"
    sunday = today + timedelta(days=(6 - today.weekday()))
    if d <= sunday:
        return "week"
    nxt = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    if d < nxt:
        return "month"
    return "later"


# --------------------------------------------------- surgical line edits

def replace_token(line, pattern, replacement):
    """Replace pattern in line; drop the token cleanly when replacement is ''."""
    m = pattern.search(line)
    if not m:
        return line, False
    if replacement:
        return line[:m.start()] + replacement + line[m.end():], True
    start, end = m.start(), m.end()
    if start > 0 and line[start - 1] == " ":
        start -= 1
    elif end < len(line) and line[end] == " ":
        end += 1
    return line[:start] + line[end:], True


def add_trailing_token(line, token):
    """Insert before the ✅ stamp when present, else append."""
    m = DONE_RE.search(line)
    if m:
        return line[:m.start()] + token + " " + line[m.start():]
    return line + " " + token


def set_line(tf, task, new_line):
    tf.lines[task.start] = new_line


# ---------------------------------------------------------------- commands

def cmd_doctor(args):
    issues = []
    try:
        vault = find_vault_root(args.vault)
    except CliError as e:
        emit(args, [f"vault: MISSING — {e}"], {"ok": False, "error": {
            "code": e.code, "message": str(e), "hint": e.hint}})
        return e.exit_code
    validator, vpath = load_sweep_validator(vault)
    if validator is None:
        issues.append(f"sweep validator not importable at {vpath} — "
                      "`edit --status done` will refuse")
    files = discover_task_files(vault)
    if not files:
        issues.append("no *-tasks.md files under 1-projects/ or 2-areas/")
    ok = not issues
    emit(args, [
        f"vault: {vault}",
        f"sb-os: {sb_os_root(vault)}",
        f"sweep validator: {'ok' if validator else 'MISSING'}",
        f"task files: {len(files)}",
        *(f"issue: {i}" for i in issues),
        "next: sb-task files",
    ], {"ok": ok, "vault": str(vault), "sb_os": str(sb_os_root(vault)),
        "validator": bool(validator), "task_files": len(files), "issues": issues})
    return 0 if ok else 1


def first_tag(path):
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:600]
    except OSError:
        return None
    if not head.startswith("---"):
        return None
    m = re.search(r"^tags:\s*\n\s*-\s*(\S+)", head, re.MULTILINE) \
        or re.search(r"^tags:\s*\[?\s*([^,\]\n]+)", head, re.MULTILINE)
    return m.group(1).strip().strip('"') if m else None


def cmd_files(args):
    vault = find_vault_root(args.vault)
    rows = []
    for p in discover_task_files(vault):
        rel = str(p.relative_to(vault)).replace(os.sep, "/")
        tf = TaskFile(p)
        rows.append({
            "path": rel,
            "tag": first_tag(p) or p.parent.name,
            "kind": "project" if rel.startswith("1-projects") else "area",
            "open": sum(1 for t in tf.tasks if not t.done),
            "done": sum(1 for t in tf.tasks if t.done),
        })
    lines = [f"{r['open']:>3} open {r['done']:>3} done  {r['kind']:<7} {r['path']}"
             for r in rows]
    if not args.json and lines:
        lines.insert(0, f"{'open':<8} {'done':<8}  {'kind':<7} path")
    lines.append(f"-- {len(rows)} task files")
    lines.append("next: sb-task list <file>   (any unique name substring works)")
    emit(args, lines, {"ok": True, "count": len(rows), "files": rows})
    return 0


def task_matches(t, args, today):
    if args.status != "all":
        st = "done" if t.done else ("wip" if t.wip else "open")
        if args.status == "open" and t.done:
            return False
        if args.status == "done" and not t.done:
            return False
        if args.status == "wip" and st != "wip":
            return False
    if args.moscow and (t.section or "").lower() != args.moscow:
        return False
    if args.difficulty and t.difficulty != canon_difficulty(args.difficulty):
        return False
    if args.batch and t.batch != args.batch:
        return False
    if args.due and due_bucket(t.due, today) != args.due:
        return False
    if getattr(args, "tag", None) and args.tag.lstrip("#") not in t.tags:
        return False
    return True


def format_digest(t, wide=False, show_line=False):
    _, subs = t.subtasks()
    _, deps = t.depends()
    bits = [
        "x" if t.done else ("w" if t.wip else "."),
        f"{(t.number or '-'):>6}",
        f"{(t.section or '-').lower():<6}",
        f"{(t.due or '-'):<10}",
    ]
    if show_line:
        bits.append(f"L{t.start + 1:<5}")
    extras = []
    if t.difficulty:
        extras.append(f"#d/{t.difficulty}")
    if t.batch:
        extras.append(f"#b/{t.batch}")
    extras += [f"#{tag}" for tag in t.tags
               if not tag.startswith(("d/", "b/", "batch/")) and tag != "wip"]
    if subs:
        extras.append(f"sub:{sum(1 for s in subs if s['done'])}/{len(subs)}")
    if deps:
        extras.append("dep:" + ",".join(deps))
    _, gates = t.done_after()
    if gates:
        extras.append("done-after:" + ",".join(gates))
    title = t.title_clean()
    if not wide:
        title = title[:70]
    return " ".join(bits) + " " + title + ("  " + " ".join(extras) if extras else "")


def digest_header(show_line=False):
    bits = ["s", f"{'number':>6}", f"{'moscow':<6}", f"{'due':<10}"]
    if show_line:
        bits.append(f"{'line':<6}")
    return " ".join(bits) + " title  tags"


def cmd_list(args):
    vault = find_vault_root(args.vault)
    tf = TaskFile(resolve_task_file(vault, args.file))
    today = date.today()
    hits = [t for t in tf.tasks if task_matches(t, args, today)]
    shown = hits[:args.limit]
    wide = getattr(args, "wide", False)
    lines = [format_digest(t, wide, show_line=True) for t in shown]
    if not args.json and lines:
        lines.insert(0, digest_header(show_line=True))
    if len(hits) > len(shown):
        lines.append(f"-- {len(hits) - len(shown)} more — re-run with --limit {len(hits)}")
    lines.append(f"-- {len(hits)}/{len(tf.tasks)} tasks ({args.status}) in {tf.path.name}")
    lines.append(f"next: sb-task read {args.file} <number|Lline|title>")
    emit(args, lines, {"ok": True, "file": str(tf.path.relative_to(vault)).replace(os.sep, "/"),
                       "count": len(hits), "shown": len(shown),
                       "tasks": [t.to_json() for t in shown]})
    return 0


def cmd_read(args):
    vault = find_vault_root(args.vault)
    tf = TaskFile(resolve_task_file(vault, args.file))
    t = resolve_task(tf, args.ref, vault)
    block = t.block_lines()
    lines = list(block)
    lines.append(f"-- line {t.start + 1}, section {t.section or '(none)'}")
    lines.append(f"next: sb-task edit {args.file} {t.number or args.ref} --status wip   (when starting work)")
    emit(args, lines, {"ok": True, "task": t.to_json(), "block": "\n".join(block)})
    return 0


def build_block(args_ns, tf):
    """Build the new task's lines from create flags."""
    due = check_date(args_ns.due, "--due")
    number = check_number(tf, args_ns.number)
    difficulty = canon_difficulty(args_ns.difficulty)
    title = text_arg(args_ns.title).strip()
    if TASK_LINE_RE.match(title):
        raise CliError("bad-title", "--title is the plain title text, not a '- [ ]' line")
    first, _, tail = title.partition(" ")
    if NUMBER_RE.match(first) and tail and not number:
        raise CliError("bad-title",
                       f"title starts with '{first}', which parses as a task number",
                       hint=f"pass it explicitly: --number {first} --title \"{tail}\"")
    tags = [canon_tag(t) for t in (getattr(args_ns, "tag", None) or [])]
    block = [build_main_line(False, due, number, title,
                             difficulty, args_ns.batch, args_ns.wip, tags=tags)]
    for name, flag in [("Why", "why"), ("Goal", "goal"), ("Context", "context"),
                       ("Criteria", "criteria")]:
        val = text_arg(getattr(args_ns, flag))
        if val:
            block.append(f"  - _{name}:_ {val}")
    for r in (args_ns.ref or []):
        if "  - _Ref:_" not in block:
            block.append("  - _Ref:_")
        block.append(f"    - {text_arg(r)}")
    if args_ns.depends:
        block.append(f"  - _Depends:_ {', '.join(x.strip() for x in args_ns.depends.split(','))}")
    if getattr(args_ns, "done_after", None):
        block.append(f"  - _Done-after:_ {', '.join(x.strip() for x in args_ns.done_after.split(','))}")
    if args_ns.sub:
        block.append("  - _Subtasks:_")
        for s in args_ns.sub:
            block.append(f"    - [ ] {text_arg(s)}")
    return block


def cmd_create(args):
    vault = find_vault_root(args.vault)
    tf = TaskFile(resolve_task_file(vault, args.file))
    if not args.force and not (args.context and args.criteria):
        missing = [f for f, v in (("--context", args.context), ("--criteria", args.criteria)) if not v]
        raise CliError("cold-start",
                       f"missing {' and '.join(missing)} — every task must be executable "
                       "by an agent with zero session memory (cold-start sufficiency)",
                       hint="add the missing field(s), or override deliberately: --force")
    block = build_block(args, tf)
    if args.depends or args.done_after:
        deps = [x.strip() for x in (args.depends or "").split(",") if x.strip()]
        gates = [x.strip() for x in (args.done_after or "").split(",") if x.strip()]
        probe = Task(tf, 0, 0, False, "", None)
        probe.number = args.number
        validate_depends(tf, probe, deps, vault, done_after=gates)
    level = (args.moscow or "should").capitalize()
    if level not in MOSCOW_LEVELS:
        raise CliError("bad-moscow", f"--moscow must be must|should|could, got '{args.moscow}'")
    heading = tf.ensure_section(level)
    at = tf.insert_block(heading, block)
    wrote = tf.save(args)
    lines = block + [
        f"-- {'DRY-RUN, not written' if not wrote else f'created under #### {level}, line {at + 1}'}",
        f"next: sb-task read {args.file} {args.number or 'this title'}",
    ]
    emit(args, lines, {"ok": True, "action": "create", "written": wrote,
                       "file": str(tf.path.relative_to(vault)).replace(os.sep, "/"),
                       "line": at + 1, "block": "\n".join(block)})
    return 0


def relocate(tf, key):
    for t in tf.tasks:
        if key[0] == "number" and t.number == key[1]:
            return t
        if key[0] == "line" and t.start == key[1]:
            return t
    for t in tf.tasks:
        if key[0] == "title" and t.title_clean() == key[1]:
            return t
    raise CliError("internal", "task lost after an edit step (re-run to inspect)", exit_code=3)


def cmd_edit(args):
    vault = find_vault_root(args.vault)
    tf = TaskFile(resolve_task_file(vault, args.file))
    task = resolve_task(tf, args.ref, vault)
    changed = []

    def key_of(t):
        return ("number", t.number) if t.number else ("title", t.title_clean())

    key = key_of(task)

    def touch(label):
        changed.append(label)

    # --- main-line token edits ---------------------------------------
    if args.due is not None:
        due = check_date(args.due, "--due")
        line = task.line
        if due == "none":
            line, hit = replace_token(line, re.compile(DATE_EMOJI + r" \d{4}-\d{2}-\d{2}"), "")
        elif DUE_RE.search(line):
            line, hit = replace_token(line, re.compile(DATE_EMOJI + r" \d{4}-\d{2}-\d{2}"),
                                      f"{DATE_EMOJI} {due}")
        else:
            line = re.sub(r"^(- \[.\] )", rf"\g<1>{DATE_EMOJI} {due} ", line)
        set_line(tf, task, line)
        touch("due")
        tf.reparse(); task = relocate(tf, key)

    if args.number is not None:
        num = check_number(tf, args.number, task)
        line = task.line
        prefix_re = re.compile(r"^(- \[.\] (?:" + DATE_EMOJI + r" \d{4}-\d{2}-\d{2} )?)")
        pm = prefix_re.match(line)
        rest = line[pm.end():]
        if task.number and rest.startswith(task.number + " "):
            rest = rest[len(task.number) + 1:]
        if num != "none":
            rest = f"{num} {rest}"
        set_line(tf, task, line[:pm.end()] + rest)
        touch("number")
        tf.reparse(); task = relocate(tf, ("line", task.start)); key = key_of(task)

    if args.title is not None:
        new_title = text_arg(args.title).strip()
        line = task.line
        old = task.title_raw
        cut = len(old)
        for probe in (" #", " " + DONE_EMOJI, " → "):
            p = old.find(probe)
            if p != -1:
                cut = min(cut, p)
        head_len = len(line) - len(old)
        set_line(tf, task, line[:head_len] + new_title + old[cut:])
        touch("title")
        tf.reparse(); task = relocate(tf, ("line", task.start)); key = key_of(task)

    if args.difficulty is not None:
        diff = canon_difficulty(args.difficulty)
        line = task.line
        line, hit = replace_token(line, re.compile(r"#d/[A-Za-z]+"),
                                  "" if diff == "none" else f"#d/{diff}")
        if not hit and diff != "none":
            line = add_trailing_token(line, f"#d/{diff}")
        set_line(tf, task, line)
        touch("difficulty")
        tf.reparse(); task = relocate(tf, key)

    if args.batch is not None:
        line = task.line
        line, hit = replace_token(line, re.compile(r"#(?:b|batch)/[A-Za-z0-9_-]+"),
                                  "" if args.batch == "none" else f"#b/{args.batch}")
        if not hit and args.batch != "none":
            line = add_trailing_token(line, f"#b/{args.batch}")
        set_line(tf, task, line)
        touch("batch")
        tf.reparse(); task = relocate(tf, key)

    for raw in (args.add_tag or []):
        tag = canon_tag(raw)
        if tag not in task.tags:
            set_line(tf, task, add_trailing_token(task.line, f"#{tag}"))
            touch(f"tag+{tag}")
            tf.reparse(); task = relocate(tf, key)

    for raw in (args.remove_tag or []):
        tag = canon_tag(raw)
        if tag not in task.tags:
            raise CliError("ref-not-found",
                           f"'#{tag}' is not on this task "
                           f"(tags: {', '.join('#' + x for x in task.tags) or 'none'})",
                           exit_code=2)
        line, _ = replace_token(task.line,
                                re.compile("#" + re.escape(tag) + r"(?![\w/-])"), "")
        set_line(tf, task, line)
        touch(f"tag-{tag}")
        tf.reparse(); task = relocate(tf, key)

    # --- status ------------------------------------------------------
    if args.status is not None:
        line = task.line
        if args.status == "wip":
            if task.done:
                raise CliError("bad-status", "task is completed; reopen first",
                               hint=f"sb-task edit {args.file} {args.ref} --status open")
            if not task.wip:
                line = add_trailing_token(line, "#wip")
        elif args.status == "open":
            line = line.replace("- [x]", "- [ ]", 1)
            line, _ = replace_token(line, re.compile(DONE_EMOJI + r" ?\d{4}-\d{2}-\d{2}"), "")
            line, _ = replace_token(line, re.compile(r"#wip\b"), "")
            line = re.sub(r"\s+$", "", line)
        elif args.status == "done":
            _, gates = task.done_after()
            open_gates = []
            for g in gates:
                gpath, gnum = parse_depend_ref(g)
                if gpath is None:
                    gt = next((t for t in tf.tasks if t.number == gnum), None)
                    if gt is None or not gt.done:
                        open_gates.append(g)
                else:
                    gp = vault / gpath
                    gtf = TaskFile(gp) if gp.is_file() else None
                    gt = next((t for t in gtf.tasks if t.number == gnum), None) if gtf else None
                    if gt is None or not gt.done:
                        open_gates.append(g)
            if open_gates and not args.force:
                raise CliError("done-gated",
                               f"cannot complete: _Done-after:_ waits on "
                               f"{', '.join(open_gates)} (still open)",
                               hint="finish those first, or override deliberately: --force")
            if not task.done:
                line = line.replace("- [ ]", "- [x]", 1)
                line, _ = replace_token(line, re.compile(r"#wip\b"), "")
                line = re.sub(r"\s+$", "", line)
                line = line + f" {DONE_EMOJI} {date.today().isoformat()}"
            validator, vpath = load_sweep_validator(vault)
            if validator is None:
                raise CliError("no-validator",
                               f"cannot complete: sweep validator missing at {vpath}",
                               hint="the sb-os repo must be present (sb-os.json sb_os_path)",
                               exit_code=3)
            verdict = validator(line, date.today())
            if verdict.get("status") != "conforming":
                raise CliError("sweep-violation",
                               f"completion line fails the sweep contract: {verdict.get('reason')}",
                               hint="nothing was written; fix the line content and re-run")
        set_line(tf, task, line)
        touch(f"status={args.status}")
        tf.reparse(); task = relocate(tf, key)

    # --- sub-bullet fields -------------------------------------------
    for name, flag in [("Why", "why"), ("Goal", "goal"),
                       ("Context", "context"), ("Criteria", "criteria")]:
        val = getattr(args, flag)
        if val is None:
            continue
        val = text_arg(val)
        fl = task.field_line(name)
        if fl is not None:
            tf.lines[fl] = re.sub(r"(_[A-Za-z]+:_\s*).*$", rf"\g<1>{val}", tf.lines[fl])
        else:
            tf.insert_line(task.field_insert_idx(name), f"  - _{name}:_ {val}")
        touch(flag)
        tf.reparse(); task = relocate(tf, key)

    for r in (args.add_ref or []):
        r = text_arg(r)
        fl = task.field_line("Ref")
        if fl is None:
            at = task.field_insert_idx("Ref")
            tf.insert_line(at, "  - _Ref:_")
            fl = at
        tf.insert_line(task.field_extent(fl), f"    - {r}")
        touch("ref")
        tf.reparse(); task = relocate(tf, key)

    # --- subtasks ----------------------------------------------------
    for s in (args.add_sub or []):
        s = text_arg(s)
        fl = task.field_line("Subtasks")
        if fl is None:
            at = task.field_insert_idx("Subtasks")
            tf.insert_line(at, "  - _Subtasks:_")
            fl = at
        tf.insert_line(task.field_extent(fl), f"    - [ ] {s}")
        touch("add-sub")
        tf.reparse(); task = relocate(tf, key)

    for ref, want in [(r, True) for r in (args.check_sub or [])] + \
                     [(r, False) for r in (args.uncheck_sub or [])]:
        _, subs = task.subtasks()
        if not subs:
            raise CliError("no-subtasks", "this task has no subtasks",
                           hint=f"add one: sb-task edit {args.file} {args.ref} --add-sub \"...\"")
        hit = None
        if ref.isdigit() and 1 <= int(ref) <= len(subs):
            hit = subs[int(ref) - 1]
        else:
            matches = [s for s in subs if ref.lower() in s["text"].lower()]
            if len(matches) == 1:
                hit = matches[0]
            elif len(matches) > 1:
                raise CliError("ref-ambiguous",
                               f"'{ref}' matches {len(matches)} subtasks",
                               hint="\n".join(f"  {i + 1}. {s['text']}" for i, s in enumerate(subs)),
                               exit_code=2)
        if hit is None:
            raise CliError("ref-not-found", f"no subtask matching '{ref}'",
                           hint="\n".join(f"  {i + 1}. {s['text']}" for i, s in enumerate(subs)),
                           exit_code=2)
        mark = "x" if want else " "
        tf.lines[hit["idx"]] = re.sub(r"- \[.\]", f"- [{mark}]", tf.lines[hit["idx"]], count=1)
        touch("check-sub" if want else "uncheck-sub")
        tf.reparse(); task = relocate(tf, key)

    # --- depends ------------------------------------------------------
    if args.add_depends or args.remove_depends:
        _, deps = task.depends()
        deps = list(deps)
        for d in (args.add_depends or "").split(","):
            d = d.strip()
            if d and d not in deps:
                deps.append(d)
        for d in (args.remove_depends or "").split(","):
            d = d.strip()
            if d in deps:
                deps.remove(d)
            elif d:
                raise CliError("ref-not-found",
                               f"'{d}' is not in this task's depends list "
                               f"({', '.join(deps) or 'empty'})", exit_code=2)
        validate_depends(tf, task, deps, vault)
        fl = task.field_line("Depends")
        if deps:
            if fl is not None:
                tf.lines[fl] = f"  - _Depends:_ {', '.join(deps)}"
            else:
                tf.insert_line(task.field_insert_idx("Depends"),
                               f"  - _Depends:_ {', '.join(deps)}")
        elif fl is not None:
            tf.remove_lines(fl, fl + 1)
        touch("depends")
        tf.reparse(); task = relocate(tf, key)

    # --- done-after (finish-to-finish gates) --------------------------
    if args.add_done_after or args.remove_done_after:
        _, gates = task.done_after()
        gates = list(gates)
        for d in (args.add_done_after or "").split(","):
            d = d.strip()
            if d and d not in gates:
                gates.append(d)
        for d in (args.remove_done_after or "").split(","):
            d = d.strip()
            if d in gates:
                gates.remove(d)
            elif d:
                raise CliError("ref-not-found",
                               f"'{d}' is not in this task's done-after list "
                               f"({', '.join(gates) or 'empty'})", exit_code=2)
        validate_depends(tf, task, None, vault, done_after=gates)
        fl = task.field_line("Done-after")
        if gates:
            if fl is not None:
                tf.lines[fl] = f"  - _Done-after:_ {', '.join(gates)}"
            else:
                tf.insert_line(task.field_insert_idx("Done-after"),
                               f"  - _Done-after:_ {', '.join(gates)}")
        elif fl is not None:
            tf.remove_lines(fl, fl + 1)
        touch("done-after")
        tf.reparse(); task = relocate(tf, key)

    # --- moscow move (last: it relocates the block) -------------------
    if args.moscow is not None:
        level = args.moscow.capitalize()
        if level not in MOSCOW_LEVELS:
            raise CliError("bad-moscow", f"--moscow must be must|should|could, got '{args.moscow}'")
        if (task.section or "").capitalize() != level:
            block = tf.remove_lines(task.start, task.end)
            heading = tf.ensure_section(level)
            tf.insert_block(heading, block)
            touch(f"moscow={level.lower()}")
            tf.reparse(); task = relocate(tf, key)

    if not changed:
        raise CliError("no-op", "no edit flags given — nothing to change",
                       hint=f"see the flags: sb-task edit -h")
    wrote = tf.save(args)
    lines = task.block_lines() + [
        f"-- {'DRY-RUN, not written' if not wrote else 'updated: ' + ', '.join(changed)}",
    ]
    emit(args, lines, {"ok": True, "action": "edit", "written": wrote,
                       "changed": changed, "task": task.to_json(),
                       "block": "\n".join(task.block_lines())})
    return 0


def cmd_delete(args):
    vault = find_vault_root(args.vault)
    tf = TaskFile(resolve_task_file(vault, args.file))
    task = resolve_task(tf, args.ref, vault)
    block = task.block_lines()
    if not args.yes:
        raise CliError("confirm-required",
                       f"delete removes this block from {tf.path.name}:\n" + "\n".join(block),
                       hint="re-run with --yes to delete (git history preserves it)")
    dependents = []
    if task.number:
        for t in tf.tasks:
            refs = t.depends()[1] + t.done_after()[1]
            if any(parse_depend_ref(d) == (None, task.number) for d in refs):
                dependents.append(t.number or t.title_clean()[:40])
    if dependents and not args.force:
        raise CliError("has-dependents",
                       f"task {task.number} is a dependency of: {', '.join(dependents)}",
                       hint="remove those _Depends:_ refs first, or delete anyway: --force")
    tf.remove_lines(task.start, task.end)
    wrote = tf.save(args)
    lines = ["deleted:"] + block + \
            [f"-- {'DRY-RUN, not written' if not wrote else 'removed from ' + tf.path.name}"]
    emit(args, lines, {"ok": True, "action": "delete", "written": wrote,
                       "deleted_block": "\n".join(block)})
    return 0


# ---------------------------------------------------------------- deps + sort

def dep_state(tf, vault):
    """Unmet-edge state over the file's not-done tasks.

    Returns (keyed, unmet, external, gate_unmet, gate_external):
      keyed         — [(key, task)] for every not-done task, in file order
                      (key = number, or 'line:N' for unnumbered tasks)
      unmet         — {key: [same-file _Depends:_ numbers not yet done]}
      external      — {key: [cross-file _Depends:_ refs not yet done]}
      gate_unmet    — {key: [same-file _Done-after:_ numbers not yet done]}
      gate_external — {key: [cross-file _Done-after:_ refs not yet done]}
    A missing target counts as unmet. Done tasks satisfy edges and carry no
    entry of their own. Depends blocks STARTING; done-after blocks FINISHING.
    """
    by_num = {t.number: t for t in tf.tasks if t.number}
    other_cache = {}

    def split_refs(refs):
        same, ext = [], []
        for d in refs:
            path, num = parse_depend_ref(d)
            if path is None:
                dt = by_num.get(num)
                if dt is not None and not dt.done:
                    same.append(num)
            else:
                if path not in other_cache:
                    p = vault / path
                    other_cache[path] = TaskFile(p) if p.is_file() else None
                otf = other_cache[path]
                od = next((x for x in otf.tasks if x.number == num), None) if otf else None
                if od is None or not od.done:
                    ext.append(d)
        return same, ext

    keyed, unmet, external = [], {}, {}
    gate_unmet, gate_external = {}, {}
    for t in tf.tasks:
        if t.done:
            continue
        key = t.number or f"line:{t.start + 1}"
        keyed.append((key, t))
        same, ext = split_refs(t.depends()[1])
        unmet[key] = same
        if ext:
            external[key] = ext
        gsame, gext = split_refs(t.done_after()[1])
        gate_unmet[key] = gsame
        if gext:
            gate_external[key] = gext
    return keyed, unmet, external, gate_unmet, gate_external


def topo_waves(keyed, unmet, external):
    """Stable topological waves; externally-blocked tasks (and anything behind
    them or behind a hand-edited cycle) come back separately, never silently."""
    order = {k: i for i, (k, _) in enumerate(keyed)}
    pending = {k: set(v) for k, v in unmet.items() if k not in external}
    waves, placed = [], set()
    while pending:
        ready = sorted((k for k, v in pending.items() if v <= placed),
                       key=order.get)
        if not ready:
            break
        waves.append(ready)
        placed.update(ready)
        for k in ready:
            del pending[k]
    stuck = {k: sorted(v - placed) for k, v in pending.items()}
    return waves, stuck


def cmd_deps(args):
    vault = find_vault_root(args.vault)
    tf = TaskFile(resolve_task_file(vault, args.file))
    keyed, unmet, external, gate_unmet, gate_external = dep_state(tf, vault)
    tasks = dict(keyed)
    fname = tf.path.name
    tag = args.tag.lstrip("#") if getattr(args, "tag", None) else None

    def tagged(t):
        return tag is None or tag in t.tags

    if args.on is not None:
        target = resolve_task(tf, args.on, vault)
        if not target.number:
            raise CliError("no-number",
                           f"'{args.on}' has no task number, so nothing can depend on it",
                           hint=f"give it one: sb-task edit {args.file} \"{args.on}\" --number <n>")
        dependents = [t for t in tf.tasks if not t.done and t is not target
                      and tagged(t)
                      and any(parse_depend_ref(d) == (None, target.number)
                              for d in t.depends()[1] + t.done_after()[1])]
        lines = [format_digest(t, show_line=True) for t in dependents]
        if not args.json and lines:
            lines.insert(0, digest_header(show_line=True))
        lines.append(f"-- {len(dependents)} open tasks depend on {target.number} in {fname}")
        if dependents:
            lines.append(f"next: finish {target.number} first: "
                         f"sb-task edit {args.file} {target.number} --status wip")
        emit(args, lines, {"ok": True, "on": target.number,
                           "dependents": [t.to_json() for t in dependents]})
        return 0

    if args.ready:
        # gates block FINISHING, not starting — a gated task can still be ready
        ready = [(k, t) for k, t in keyed
                 if not unmet.get(k) and k not in external and tagged(t)]
        lines = [format_digest(t, show_line=True) for _, t in ready]
        if not args.json and lines:
            lines.insert(0, digest_header(show_line=True))
        lines.append(f"-- {len(ready)}/{len(keyed)} open tasks are ready "
                     f"(all depends met{f', #{tag} only' if tag else ''}) in {fname}")
        lines.append(f"next: sb-task edit {args.file} <number> --status wip")
        emit(args, lines, {"ok": True, "count": len(ready),
                           "tasks": [t.to_json() for _, t in ready]})
        return 0

    # ordering always computes on the FULL graph; --tag filters the display only
    order_unmet = {k: unmet.get(k, []) + gate_unmet.get(k, []) for k, _ in keyed}
    waves, stuck = topo_waves(keyed, order_unmet, external)
    shown_waves = [[k for k in wave if tagged(tasks[k])] for wave in waves]
    lines = []
    if not args.json and any(shown_waves):
        lines.append("  " + digest_header(show_line=True))
    for i, wave in enumerate(shown_waves, 1):
        if not wave:
            continue
        lines.append(f"wave {i}  ({len(wave)} in parallel)")
        for k in wave:
            lines.append(f"  {format_digest(tasks[k], show_line=True)}")
    for k, refs in sorted(external.items()):
        if tagged(tasks[k]):
            lines.append(f"blocked-external: {k} waits on {', '.join(refs)}")
    for k, refs in sorted(gate_external.items()):
        if tagged(tasks[k]):
            lines.append(f"done-gated-external: {k} may start but not complete before {', '.join(refs)}")
    for k, deps in sorted(stuck.items()):
        if tagged(tasks[k]):
            lines.append(f"blocked: {k} waits on {', '.join(deps) or 'a blocked/cyclic chain'}")
    shown_n = sum(len(w) for w in shown_waves)
    lines.append(f"-- {shown_n}{f'/{len(keyed)} (#{tag})' if tag else ''} open tasks, "
                 f"{len(waves)} waves in {fname}")
    lines.append(f"next: sb-task deps {args.file} --ready")
    emit(args, lines, {"ok": True, "waves": shown_waves, "tag": tag,
                       "blocked_external": external, "blocked": stuck,
                       "done_gated_external": gate_external,
                       "tasks": [t.to_json() for _, t in keyed if tagged(t)]})
    return 0


def cmd_sort(args):
    """Rewrite each contiguous run of task blocks in dependency order.

    The DAG (_Depends:_) stays the single ordering truth — file position is a
    derived, re-runnable view of it. Ties keep their current relative order.
    """
    vault = find_vault_root(args.vault)
    tf = TaskFile(resolve_task_file(vault, args.file))
    by_num = {t.number: t for t in tf.tasks if t.number}

    # contiguous runs: consecutive task blocks separated by blank lines only
    runs, cur = [], []
    for t in tf.tasks:
        if cur and any(tf.lines[i].strip() != ""
                       for i in range(cur[-1].end, t.start)):
            runs.append(cur)
            cur = []
        cur.append(t)
    if cur:
        runs.append(cur)

    changed = []
    for run in reversed(runs):        # bottom-up keeps line indices valid
        if len(run) < 2:
            continue
        in_run = {t.number for t in run if t.number}
        order = {id(t): i for i, t in enumerate(run)}
        pending = []
        for t in run:
            same = set()
            for d in t.depends()[1] + t.done_after()[1]:
                path, num = parse_depend_ref(d)
                dt = by_num.get(num) if path is None else None
                if dt is not None and not dt.done and num in in_run:
                    same.add(num)
            pending.append((t, same))
        placed, new_order = set(), []
        while pending:
            ready = [(t, s) for t, s in pending if s <= placed]
            if not ready:                     # hand-edited cycle: keep as-is
                new_order.extend(t for t, _ in pending)
                break
            ready.sort(key=lambda ts: order[id(ts[0])])
            for t, _ in ready:
                new_order.append(t)
                if t.number:
                    placed.add(t.number)
            pending = [(t, s) for t, s in pending if t not in
                       {x for x, _ in ready}]
        if [id(t) for t in new_order] == [id(t) for t in run]:
            continue
        blocks = [(tf.lines[t.start:t.end], tf.eols[t.start:t.end])
                  for t in new_order]
        lo, hi = run[0].start, run[-1].end
        del tf.lines[lo:hi]
        del tf.eols[lo:hi]
        at = lo
        for i, (bl, be) in enumerate(blocks):
            if i:
                tf.lines.insert(at, "")
                tf.eols.insert(at, tf.default_eol)
                at += 1
            tf.lines[at:at] = bl
            tf.eols[at:at] = be
            at += len(bl)
        changed.append({
            "section": run[0].section or "(none)",
            "before": [t.number or t.title_clean()[:30] for t in run],
            "after": [t.number or t.title_clean()[:30] for t in new_order],
        })
    changed.reverse()

    wrote = False
    if changed:
        tf.reparse()
        wrote = tf.save(args)
    lines = []
    for c in changed:
        lines.append(f"{c['section']}: {' '.join(c['before'])}  ->  {' '.join(c['after'])}")
    if not changed:
        lines.append("already in dependency order — nothing to move")
    else:
        lines.append(f"-- {'DRY-RUN, not written' if not wrote else f'{len(changed)} run(s) reordered in {tf.path.name}'}")
    lines.append(f"next: sb-task deps {args.file}")
    emit(args, lines, {"ok": True, "action": "sort", "written": wrote,
                       "runs_changed": changed})
    return 0


# ---------------------------------------------------------------- selftest

def invoke(*argv):
    """Run the CLI in-process; returns (exit_code, stdout_text)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = main(list(argv))
    return code, buf.getvalue()


FIXTURE = """---
tags:
  - testp
type: tasks
---

# testp — tasks

#### Must

- [ ] \U0001F4C5 2000-01-02 1.1 Ship the fixture feature #d/med
  - _Context:_ fixture context
  - _Criteria:_ fixture criteria

#### Should

- [ ] 2 Review the fixture docs
  - _Criteria:_ docs reviewed

#### Could
"""


def cmd_selftest(args):
    checks = []

    def ok(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    with tempfile.TemporaryDirectory() as td:
        vault = Path(td)
        real_sb_os = str(sb_os_root(find_vault_root(args.vault))) if _has_real_vault() else ""
        (vault / "sb-os.json").write_text(
            json.dumps({"sb_os_path": real_sb_os}), encoding="utf-8")
        proj = vault / "1-projects" / "testp"
        proj.mkdir(parents=True)
        tasks_md = proj / "testp-tasks.md"
        tasks_md.write_text(FIXTURE.replace("\n", "\r\n"), encoding="utf-8", newline="")
        V = ("--vault", str(vault))

        code, out = invoke(*V, "doctor")
        ok("doctor", code == 0, out)
        code, out = invoke(*V, "--json", "files")
        ok("files", code == 0 and json.loads(out)["count"] == 1, out)

        code, out = invoke(*V, "create", "testp", "--title", "Build the thing")
        ok("create-refused-cold-start", code == 1)
        code, out = invoke(*V, "create", "testp", "--title", "Build the thing",
                           "--context", "ctx", "--criteria", "crit",
                           "--number", "3", "--due", "2099-01-01", "--moscow", "could",
                           "--sub", "step one", "--sub", "step two")
        ok("create", code == 0, out)
        code, out = invoke(*V, "create", "testp", "--title", "Dup number",
                           "--number", "3", "--force")
        ok("create-dup-number-refused", code == 1)
        code, out = invoke(*V, "create", "testp", "--title", "12 leads with number", "--force")
        ok("create-number-in-title-refused", code == 1)

        code, out = invoke(*V, "--json", "read", "testp", "1.1")
        ok("read-by-number", code == 0 and json.loads(out)["task"]["number"] == "1.1", out)
        code, out = invoke(*V, "--json", "read", "testp", "fixture docs")
        ok("read-by-substring", code == 0 and json.loads(out)["task"]["number"] == "2")
        code, out = invoke(*V, "read", "testp", "zzz-nothing")
        ok("read-miss-exit-2", code == 2)

        code, out = invoke(*V, "--json", "read", "testp", "1.1")
        ln = json.loads(out)["task"]["line"] if code == 0 else 0
        code, out = invoke(*V, "--json", "read", "testp", f"L{ln}")
        ok("read-by-line-ref", code == 0 and json.loads(out)["task"]["number"] == "1.1", out)
        code, out = invoke(*V, "--json", "read", "testp", f"L{ln + 1}")
        ok("read-line-ref-midblock", code == 0
           and json.loads(out)["task"]["number"] == "1.1", out)
        code, out = invoke(*V, "read", "testp", "L9999")
        ok("read-line-ref-miss-exit-2", code == 2, out)
        code, out = invoke(*V, "list", "testp")
        ok("list-header", code == 0 and out.splitlines()[0].split() == [
            "s", "number", "moscow", "due", "line", "title", "tags"], out)
        code, out = invoke(*V, "--json", "list", "testp")
        ok("list-header-not-in-json", code == 0 and "tasks" in json.loads(out), out)

        code, out = invoke(*V, "--json", "edit", "testp", "2",
                           "--due", "2099-06-01", "--difficulty", "high", "--batch", "kick")
        j = json.loads(out) if code == 0 else {}
        ok("edit-tokens", code == 0 and j["task"]["due"] == "2099-06-01"
           and j["task"]["difficulty"] == "hard" and j["task"]["batch"] == "kick", out)
        code, out = invoke(*V, "edit", "testp", "2", "--number", "1.1")
        ok("edit-number-taken-refused", code == 1)

        code, out = invoke(*V, "--json", "edit", "testp", "3",
                           "--check-sub", "1")
        j = json.loads(out) if code == 0 else {}
        ok("check-sub", code == 0 and j["task"]["subtasks"] == {"done": 1, "total": 2}, out)

        code, out = invoke(*V, "--json", "edit", "testp", "3", "--add-depends", "1.1")
        ok("add-depends", code == 0 and json.loads(out)["task"]["depends"] == ["1.1"], out)
        code, out = invoke(*V, "edit", "testp", "1.1", "--add-depends", "3")
        ok("dag-cycle-refused", code == 1, out)
        code, out = invoke(*V, "edit", "testp", "3", "--add-depends", "9.9")
        ok("depends-unknown-refused", code == 1)

        code, out = invoke(*V, "--json", "edit", "testp", "2", "--status", "wip")
        ok("wip-on", code == 0 and json.loads(out)["task"]["wip"] is True, out)
        code, out = invoke(*V, "--json", "edit", "testp", "2", "--status", "done")
        if real_sb_os:
            j = json.loads(out) if code == 0 else {}
            ok("done-validated", code == 0 and j["task"]["status"] == "done"
               and j["task"]["wip"] is False and j["task"]["done_date"], out)
            code, out = invoke(*V, "--json", "list", "testp", "--status", "done")
            ok("list-done", code == 0 and json.loads(out)["count"] == 1)
            code, out = invoke(*V, "--json", "edit", "testp", "2", "--status", "open")
            ok("reopen", code == 0 and json.loads(out)["task"]["status"] == "open", out)
        else:
            ok("done-validated", code == 3, "no real sb-os repo; refusal path exercised")
            ok("list-done", True, "skipped (no validator)")
            ok("reopen", True, "skipped (no validator)")

        code, out = invoke(*V, "--json", "edit", "testp", "3", "--moscow", "must")
        ok("moscow-move", code == 0 and json.loads(out)["task"]["moscow"] == "must", out)

        code, out = invoke(*V, "--json", "list", "testp", "--due", "overdue")
        ok("due-bucket-overdue", code == 0 and json.loads(out)["count"] == 1, out)

        # --- deps views (state here: 3 depends on 1.1; 2 independent) ----
        code, out = invoke(*V, "--json", "deps", "testp")
        j = json.loads(out) if code == 0 else {}
        ok("deps-waves", code == 0 and len(j.get("waves", [])) == 2
           and "3" in j["waves"][1] and "1.1" in j["waves"][0], out)
        code, out = invoke(*V, "--json", "deps", "testp", "--ready")
        j = json.loads(out) if code == 0 else {}
        ok("deps-ready", code == 0 and j.get("count") == 2
           and all(t["number"] != "3" for t in j.get("tasks", [])), out)
        code, out = invoke(*V, "--json", "deps", "testp", "--on", "1.1")
        j = json.loads(out) if code == 0 else {}
        ok("deps-on", code == 0
           and [t["number"] for t in j.get("dependents", [])] == ["3"], out)

        # --- sort: 3 sits above 1.1 in Must but depends on it ------------
        code, out = invoke(*V, "--json", "sort", "testp")
        j = json.loads(out) if code == 0 else {}
        ok("sort-reorders", code == 0 and j.get("written") is True
           and j["runs_changed"] and j["runs_changed"][0]["after"] == ["1.1", "3"], out)
        code, out = invoke(*V, "--json", "sort", "testp")
        ok("sort-idempotent", code == 0
           and json.loads(out)["runs_changed"] == [], out)
        code, out = invoke(*V, "--json", "list", "testp", "--moscow", "must", "--status", "all")
        j = json.loads(out) if code == 0 else {}
        ok("sort-order-on-disk", code == 0
           and [t["number"] for t in j.get("tasks", [])] == ["1.1", "3"], out)

        # --- list --wide -------------------------------------------------
        long_title = "Review the fixture docs " + "x" * 70
        code, out = invoke(*V, "edit", "testp", "2", "--title", long_title)
        ok("edit-long-title", code == 0, out)
        code, out = invoke(*V, "list", "testp", "--status", "all")
        ok("list-truncates", code == 0 and long_title not in out, out)
        code, out = invoke(*V, "list", "testp", "--status", "all", "--wide")
        ok("list-wide", code == 0 and long_title in out, out)
        code, out = invoke(*V, "edit", "testp", "2", "--title", "Review the fixture docs")
        ok("edit-title-restore", code == 0, out)

        # --- done-after: finish-to-finish gates --------------------------
        # 3 depends on 1.1; gating 1.1 on 3 would deadlock — must refuse
        code, out = invoke(*V, "edit", "testp", "1.1", "--add-done-after", "3")
        ok("done-after-deadlock-refused", code == 1, out)
        code, out = invoke(*V, "--json", "edit", "testp", "3", "--add-done-after", "2")
        j = json.loads(out) if code == 0 else {}
        ok("done-after-add", code == 0 and j["task"]["done_after"] == ["2"], out)
        code, out = invoke(*V, "edit", "testp", "3", "--add-done-after", "9.9")
        ok("done-after-unknown-refused", code == 1)
        code, out = invoke(*V, "--json", "edit", "testp", "3", "--status", "done")
        ok("done-gate-blocks", code == 1
           and json.loads(out)["error"]["code"] == "done-gated", out)
        code, out = invoke(*V, "--json", "edit", "testp", "3", "--status", "done", "--force")
        if real_sb_os:
            ok("done-gate-force", code == 0
               and json.loads(out)["task"]["status"] == "done", out)
            code, out = invoke(*V, "edit", "testp", "3", "--status", "open")
            ok("done-gate-reopen", code == 0, out)
        else:
            ok("done-gate-force", code == 3, "gate bypassed; validator-missing refusal")
            ok("done-gate-reopen", True, "skipped (no validator)")
        # sort orders by the union: 4 gated on 3 must land after it
        code, out = invoke(*V, "create", "testp", "--title", "Deliver the thing",
                           "--number", "4", "--moscow", "must",
                           "--done-after", "3", "--force")
        ok("create-with-done-after", code == 0, out)
        code, out = invoke(*V, "--json", "sort", "testp")
        j = json.loads(out) if code == 0 else {}
        ok("sort-respects-gates", code == 0 and j["runs_changed"]
           and j["runs_changed"][0]["after"] == ["1.1", "3", "4"], out)
        code, out = invoke(*V, "--json", "edit", "testp", "3", "--remove-done-after", "2")
        ok("done-after-remove", code == 0 and json.loads(out)["task"]["done_after"] == [], out)
        code, out = invoke(*V, "delete", "testp", "3", "--yes")
        ok("delete-gate-dependent-refused", code == 1, out)
        code, out = invoke(*V, "delete", "testp", "4", "--yes")
        ok("delete-gated-task", code == 0, out)

        # --- decision lane: free tags + --tag filters --------------------
        code, out = invoke(*V, "--json", "create", "testp",
                           "--title", "Rule the fixture direction", "--number", "5",
                           "--moscow", "could", "--tag", "decision",
                           "--context", "ctx", "--criteria", "ruled")
        ok("create-with-tag", code == 0 and "#decision" in json.loads(out)["block"], out)
        code, out = invoke(*V, "--json", "list", "testp", "--tag", "decision")
        j = json.loads(out) if code == 0 else {}
        ok("list-tag-filter", code == 0 and j["count"] == 1
           and j["tasks"][0]["number"] == "5"
           and "decision" in j["tasks"][0]["tags"], out)
        code, out = invoke(*V, "--json", "deps", "testp", "--ready", "--tag", "decision")
        j = json.loads(out) if code == 0 else {}
        ok("deps-ready-tag", code == 0 and j["count"] == 1
           and j["tasks"][0]["number"] == "5", out)
        code, out = invoke(*V, "--json", "deps", "testp", "--tag", "decision")
        j = json.loads(out) if code == 0 else {}
        ok("deps-waves-tag", code == 0
           and [k for w in j.get("waves", []) for k in w] == ["5"], out)
        code, out = invoke(*V, "edit", "testp", "5", "--add-tag", "b/nope")
        ok("structured-tag-refused", code == 1)
        code, out = invoke(*V, "--json", "edit", "testp", "5", "--remove-tag", "decision")
        ok("remove-tag", code == 0 and "decision" not in json.loads(out)["task"]["tags"], out)
        code, out = invoke(*V, "--json", "edit", "testp", "5", "--add-tag", "#decision")
        ok("add-tag", code == 0 and "decision" in json.loads(out)["task"]["tags"], out)
        code, out = invoke(*V, "delete", "testp", "5", "--yes")
        ok("delete-decision-task", code == 0, out)

        # --- exact file name beats substring ambiguity -------------------
        extra = vault / "1-projects" / "testp-x"
        extra.mkdir(parents=True)
        (extra / "testp-x-tasks.md").write_text("#### Should\n", encoding="utf-8")
        code, out = invoke(*V, "--json", "list", "testp")
        ok("file-exact-beats-substring", code == 0
           and json.loads(out)["file"].endswith("testp/testp-tasks.md"), out)
        code, out = invoke(*V, "list", "testp-x-tasks-nothere")
        ok("file-miss-exit-2", code == 2)

        # --- save retries while the target is briefly locked -------------
        real_replace = os.replace
        state = {"n": 0}
        def flaky_replace(src, dst):
            state["n"] += 1
            if state["n"] <= 2:
                raise PermissionError(13, "held by a watcher", str(dst), 5)
            return real_replace(src, dst)
        os.replace = flaky_replace
        try:
            code, out = invoke(*V, "edit", "testp", "2", "--batch", "retrykick")
        finally:
            os.replace = real_replace
        ok("save-retry-on-lock", code == 0 and state["n"] == 3, out)
        code, out = invoke(*V, "edit", "testp", "2", "--batch", "none")
        ok("save-retry-cleanup", code == 0, out)

        code, out = invoke(*V, "delete", "testp", "1.1", "--yes")
        ok("delete-dependent-refused", code == 1, out)
        code, out = invoke(*V, "edit", "testp", "3", "--remove-depends", "1.1")
        ok("remove-depends", code == 0, out)
        code, out = invoke(*V, "delete", "testp", "1.1")
        ok("delete-needs-yes", code == 1)
        code, out = invoke(*V, "delete", "testp", "1.1", "--yes")
        ok("delete", code == 0 and "Ship the fixture feature" in out, out)

        content = tasks_md.read_bytes().decode("utf-8")
        ok("crlf-preserved", "\r\n#### Should" in content or "#### Should\r\n" in content,
           "untouched lines keep their \\r\\n endings")
        ok("no-fixture-task-left", "Ship the fixture feature" not in content)

    failed = [(n, d) for n, c, d in checks if not c]
    for n, c, d in checks:
        print(f"{'ok  ' if c else 'FAIL'} {n}" + (f"  {d[:120]}" if not c and d else ""))
    print(f"selftest: {len(checks) - len(failed)}/{len(checks)} checks passed")
    return 0 if not failed else 1


def _has_real_vault():
    try:
        find_vault_root(None)
        return True
    except CliError:
        return False


# ---------------------------------------------------------------- parser

def build_parser():
    # SUPPRESS keeps a subcommand's unset copy of a shared flag from
    # clobbering the value parsed at root level (e.g. `sb-task --json files`).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="machine-readable output")
    common.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS,
                        help="human mode (color)")
    common.add_argument("--vault", default=argparse.SUPPRESS,
                        help="vault root (default: walk up for sb-os.json)")
    common.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS,
                        help="show the result, write nothing")

    p = argparse.ArgumentParser(
        prog=PROG, parents=[common],
        description="agent CLI for sb-os vault task files (*-tasks.md)",
        epilog="per-command help: sb-task <command> -h    "
               "free text flags accept @file / @- (stdin)")
    sub = p.add_subparsers(dest="cmd", metavar="<command>")

    def cmd(name, help_, example, next_):
        sp = sub.add_parser(name, parents=[common], help=help_,
                            formatter_class=argparse.RawDescriptionHelpFormatter,
                            epilog=f"example:\n  {example}\nnext: {next_}")
        return sp

    cmd("doctor", "environment health: vault, validator, task-file census",
        "sb-task --json doctor", "sb-task files")

    cmd("files", "discovery: every *-tasks.md with tag + open/done counts",
        "sb-task --json files", "sb-task list <file>")

    sp = cmd("list", "digest of a file's tasks (one line each), filterable",
             'sb-task list tecer --status open --moscow must',
             "sb-task read <file> <number|Lline|title>")
    sp.add_argument("file", help="vault-relative path or unique task-file name substring")
    sp.add_argument("--status", choices=["open", "wip", "done", "all"], default="open")
    sp.add_argument("--moscow", choices=["must", "should", "could"])
    sp.add_argument("--difficulty", help="easy|med|hard (aliases low/high)")
    sp.add_argument("--batch")
    sp.add_argument("--due", choices=DUE_BUCKETS)
    sp.add_argument("--tag", help="only tasks carrying #TAG (e.g. decision — the owner lane)")
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--wide", action="store_true", help="full titles, no 70-char cut")

    sp = cmd("read", "one task's full block + parsed fields",
             'sb-task read tecer 4.1b',
             "sb-task edit <file> <ref> --status wip")
    sp.add_argument("file")
    sp.add_argument("ref", help="task number, line ref (L110, from the list 'line' column), "
                                "exact title, or unique title substring")

    sp = cmd("create", "add a task (refuses without --context + --criteria; escape: --force)",
             'sb-task create tecer --title "Close the Q3 review" --number 3.2 '
             '--due 2026-08-01 --moscow must --context "..." --criteria "..."',
             "sb-task read <file> <number>")
    sp.add_argument("file")
    sp.add_argument("--title", required=True, help="plain title text, starts with a verb")
    sp.add_argument("--number", help="optional unique label like 1.2 / 3b")
    sp.add_argument("--due", help="YYYY-MM-DD")
    sp.add_argument("--moscow", choices=["must", "should", "could"], help="default: should")
    sp.add_argument("--difficulty", help="easy|med|hard (aliases low/high)")
    sp.add_argument("--batch")
    sp.add_argument("--why"); sp.add_argument("--goal")
    sp.add_argument("--context"); sp.add_argument("--criteria")
    sp.add_argument("--ref", action="append", help="repeatable external reference")
    sp.add_argument("--depends", help="comma-separated task numbers (or path#number)")
    sp.add_argument("--done-after", dest="done_after",
                    help="finish-to-finish gates: may start anytime, may not "
                         "complete before these tasks (numbers or path#number)")
    sp.add_argument("--sub", action="append", help="repeatable subtask text")
    sp.add_argument("--tag", action="append",
                    help="repeatable free tag, e.g. decision (owner-lane task)")
    sp.add_argument("--wip", action="store_true")
    sp.add_argument("--force", action="store_true", help="create without context/criteria")

    sp = cmd("edit", "change any task field; combines flags in one call",
             'sb-task edit tecer 3.2 --status done',
             "sb-task list <file>")
    sp.add_argument("file")
    sp.add_argument("ref")
    sp.add_argument("--status", choices=["open", "wip", "done"],
                    help="done validates the sweep contract + stamps today; wip toggles #wip on")
    sp.add_argument("--due", help="YYYY-MM-DD, or 'none' to clear")
    sp.add_argument("--moscow", help="must|should|could — moves the block between sections")
    sp.add_argument("--difficulty", help="easy|med|hard|none (aliases low/high)")
    sp.add_argument("--batch", help="batch slug/number, or 'none' to clear")
    sp.add_argument("--add-tag", action="append",
                    help="append a free tag, e.g. decision (owner-lane task)")
    sp.add_argument("--remove-tag", action="append", help="remove a free tag")
    sp.add_argument("--number", help="new unique number, or 'none' to clear")
    sp.add_argument("--title", help="replace the title text")
    sp.add_argument("--why"); sp.add_argument("--goal")
    sp.add_argument("--context"); sp.add_argument("--criteria")
    sp.add_argument("--add-ref", action="append", help="append a _Ref:_ entry")
    sp.add_argument("--add-sub", action="append", help="append a subtask checkbox")
    sp.add_argument("--check-sub", action="append", help="tick a subtask (index or substring)")
    sp.add_argument("--uncheck-sub", action="append", help="untick a subtask")
    sp.add_argument("--add-depends", help="comma-separated numbers to add (DAG-checked)")
    sp.add_argument("--remove-depends", help="comma-separated numbers to remove")
    sp.add_argument("--add-done-after",
                    help="add finish-to-finish gates: this task may not be "
                         "marked done before these (DAG-checked with depends)")
    sp.add_argument("--remove-done-after", help="comma-separated gates to remove")
    sp.add_argument("--force", action="store_true",
                    help="override the done-after gate on --status done")

    sp = cmd("deps", "dependency views: parallel waves (default), --ready, --on <ref>",
             'sb-task deps tecer --ready',
             "sb-task edit <file> <number> --status wip")
    sp.add_argument("file")
    sp.add_argument("--ready", action="store_true",
                    help="only open tasks whose depends are all met (startable now)")
    sp.add_argument("--on", metavar="REF",
                    help="open tasks that depend on REF (what finishing it unblocks)")
    sp.add_argument("--tag", help="show only tasks carrying #TAG (ordering still "
                                  "computed on the full graph) — e.g. decision")

    sp = cmd("sort", "rewrite each section's task blocks in dependency order "
             "(derived from _Depends:_; re-run anytime; ties keep current order)",
             'sb-task sort tecer --dry-run',
             "sb-task deps <file>")
    sp.add_argument("file")

    sp = cmd("delete", "remove a task block (prints it; git history preserves it)",
             'sb-task delete tecer 3.2 --yes',
             "sb-task list <file>")
    sp.add_argument("file")
    sp.add_argument("ref")
    sp.add_argument("--yes", action="store_true", help="required to actually delete")
    sp.add_argument("--force", action="store_true", help="delete even with dependents")

    cmd("selftest", "run the embedded check suite in a temp vault",
        "sb-task selftest", "sb-task doctor")

    return p


DISPATCH = {
    "doctor": cmd_doctor, "files": cmd_files, "list": cmd_list, "read": cmd_read,
    "create": cmd_create, "edit": cmd_edit, "delete": cmd_delete,
    "deps": cmd_deps, "sort": cmd_sort, "selftest": cmd_selftest,
}


def main(argv=None):
    global USE_COLOR
    if hasattr(sys.stdout, "reconfigure"):
        with contextlib.suppress(Exception):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    for name, default in (("json", False), ("pretty", False),
                          ("vault", None), ("dry_run", False)):
        if not hasattr(args, name):
            setattr(args, name, default)
    USE_COLOR = bool(getattr(args, "pretty", False)
                     or os.environ.get("SB_TASK_PRETTY") == "1")
    if not args.cmd:
        parser.print_help()
        return 0
    try:
        return DISPATCH[args.cmd](args)
    except CliError as e:
        return fail(args, e)


if __name__ == "__main__":
    sys.exit(main())
