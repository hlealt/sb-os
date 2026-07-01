#!/usr/bin/env python3
"""sb-tutor-lint-page — pre-build linter for learning-library page-sources.

Validates ``{library_root}/topics/*.md`` BEFORE the builder
(``sb-tutor-build-library.py``) silently degrades a malformed block, and reports
every problem with the page path and the 1-based line number of the offending
block/line. Designed to gate a build (exit 1 on issues).

Usage:
  python sb-tutor-lint-page.py --library-root PATH [--topic SLUG] [--json]

Checks (the real footguns this template hits):
  1. Nested ``` fence inside a `deeper`/`trace` block body — the builder extracts
     these with a NON-GREEDY fence regex, so a nested fence silently truncates the
     block. ERROR.
  2. YAML parse errors in YAML-bodied blocks (graph/chart/quiz/trace + any future
     YAML block) — the common cause is an unquoted colon/`#` or an unescaped
     apostrophe inside a single-quoted flow scalar. ERROR.
  3. Required-field checks per known block (graph/chart/quiz/trace); every graph
     node AND edge needs a `desc` (quality bar) — WARN.
  4. Frontmatter sanity — title/slug presence, symbol-only glossary keys.

The set of special block kinds is DERIVED from the builder at runtime (imported by
path), so blocks other agents add (flow/tabs/annotated-code, ...) auto-inherit the
YAML + nested-fence checks. Schema: learning-library/page-source-schema.md.
"""
from __future__ import annotations
import argparse, importlib.util, json, re, sys
from pathlib import Path

try:
    import yaml
except ImportError as e:  # deterministic dependency (shared with the builder)
    sys.stderr.write(f"missing dependency: {e}. Run: pip install pyyaml\n")
    sys.exit(2)

BUILDER = Path(__file__).resolve().parent / "sb-tutor-build-library.py"

# Sensible fallbacks if the builder can't be imported (kept in sync with its module
# constants). The import below is the source of truth so new block kinds are covered.
_FALLBACK_SPECIAL = {"graph", "chart", "quiz", "deeper", "trace"}
_FALLBACK_FENCE = re.compile(r"^```(\w+)[ \t]*\n(.*?)\n```[ \t]*$", re.DOTALL | re.MULTILINE)

# Blocks whose body is fence-extracted LITERAL text (no YAML) and so must never
# contain a nested ``` fence. `trace` is YAML-bodied but its `code: |` scalars are
# literal and the whole block is fence-extracted, so it is fence-sensitive too.
LITERAL_BLOCKS = {"deeper", "trace"}


def load_builder_constants():
    """Import SPECIAL + FENCE from the builder BY PATH (its module name has hyphens,
    so importlib.util.spec_from_file_location). Falls back to local copies on any
    failure (incl. the builder's hard-exit if a heavy dep like `markdown` is absent)."""
    try:
        spec = importlib.util.spec_from_file_location("sb_tutor_build_library", BUILDER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        special = set(getattr(mod, "SPECIAL", _FALLBACK_SPECIAL)) or set(_FALLBACK_SPECIAL)
        fence = getattr(mod, "FENCE", _FALLBACK_FENCE)
        return special, fence, True
    except BaseException:  # SystemExit (missing markdown) or any import error
        return set(_FALLBACK_SPECIAL), _FALLBACK_FENCE, False


SPECIAL, FENCE, _BUILDER_OK = load_builder_constants()
# YAML-bodied blocks = every special block except the literal `deeper` expander.
YAML_KINDS = SPECIAL - {"deeper"}

FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)
FENCE_LINE = re.compile(r"^(```+)([^\n`]*)$")  # a fence-delimiter line; info = group(2)


# ---------- issue collection ----------
class Issues:
    def __init__(self):
        self.items = []

    def add(self, file, line, level, kind, message):
        self.items.append({"file": str(file), "line": int(line),
                           "level": level, "kind": kind, "message": message})

    def err(self, *a):
        self.add(*a[:1], a[1], "ERROR", *a[2:])

    def warn(self, *a):
        self.add(*a[:1], a[1], "WARN", *a[2:])


def line_of(raw: str, offset: int) -> int:
    """1-based line number of a character offset in `raw`."""
    return raw.count("\n", 0, offset) + 1


def yaml_error_line(err, body_start_line: int) -> int:
    """Map a yaml error's 0-based problem_mark to a file line; fall back to the block start."""
    mark = getattr(err, "problem_mark", None)
    if mark is not None and getattr(mark, "line", None) is not None:
        return body_start_line + mark.line
    return body_start_line


# ---------- checks ----------
def check_frontmatter(raw: str, fpath: Path, iss: Issues):
    """Frontmatter presence + YAML parse + title/slug/glossary sanity. Returns meta dict (or {})."""
    m = FRONTMATTER.match(raw)
    if not m:
        iss.warn(fpath, 1, "frontmatter", "no YAML frontmatter (--- block) found; "
                 "title/slug/glossary will be derived from the filename")
        return {}, m
    fm_text = m.group(1)
    fm_start_line = line_of(raw, m.start(1))  # line where frontmatter content begins
    try:
        meta = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as e:
        iss.err(fpath, yaml_error_line(e, fm_start_line), "frontmatter",
                f"frontmatter YAML parse error: {str(e).splitlines()[0]}")
        return {}, m
    if not isinstance(meta, dict):
        iss.err(fpath, fm_start_line, "frontmatter", "frontmatter is not a YAML mapping")
        return {}, m
    if not meta.get("title"):
        iss.warn(fpath, fm_start_line, "frontmatter", "missing `title` (builder will derive from filename)")
    if not meta.get("slug"):
        iss.warn(fpath, fm_start_line, "frontmatter",
                 "missing `slug` (will be derived from title; keep it STABLE across rebuilds or links break)")
    gloss = meta.get("glossary") or {}
    if isinstance(gloss, dict):
        for term in gloss:
            t = str(term)
            if not (re.search(r"^\w", t) and re.search(r"\w$", t)):
                iss.warn(fpath, fm_start_line, "glossary",
                         f"glossary key {t!r} is symbol-edged; the builder's \\b word-boundary match "
                         "will never highlight it in prose")
    return meta, m


def check_nested_fences(raw: str, body: str, body_start_line: int, fpath: Path, iss: Issues):
    """Walk body lines tracking fence state; flag any info-string fence opened INSIDE a
    deeper/trace block (the non-greedy builder regex truncates the block there)."""
    open_word = None          # info-word of the currently-open fence, or None
    open_is_literal = False   # is the open block a deeper/trace (fence-extracted literal)?
    open_line = 0
    for i, ln in enumerate(body.split("\n")):
        fm = FENCE_LINE.match(ln)
        if not fm:
            continue
        info = fm.group(2).strip()
        word = info.split()[0] if info else ""
        fileline = body_start_line + i
        if open_word is None:
            # opening fence
            open_word = word or "__bare__"
            open_is_literal = word in LITERAL_BLOCKS
            open_line = fileline
        else:
            if info == "":
                # bare ``` closes the current block
                open_word = None
                open_is_literal = False
            elif open_is_literal:
                # an info-string fence while inside a deeper/trace body = the footgun
                iss.err(fpath, fileline, "nested-fence",
                        f"nested ```{word} fence inside the `{open_word}` block opened at "
                        f"line {open_line}: the builder's non-greedy fence regex will truncate "
                        f"the block here (everything after is lost). Move code into a `code: |` "
                        f"scalar (trace) or out of the block; never nest ``` inside deeper/trace.")
            # for a non-literal open block, an info line is treated as content (markdown
            # fences don't nest) — a bare ``` later closes it.
    if open_word is not None and open_is_literal:
        iss.warn(fpath, open_line, "nested-fence",
                 f"`{open_word}` block opened here is never closed by a bare ``` line")


def _is_list(x):
    return isinstance(x, list)


def check_block_fields(kind: str, spec, line: int, fpath: Path, iss: Issues):
    """Required-field checks for the block kinds we know; unknown kinds get YAML-only."""
    if not isinstance(spec, dict):
        iss.err(fpath, line, kind, f"`{kind}` block body is not a YAML mapping")
        return
    if kind == "graph":
        nodes = spec.get("nodes") or []
        edges = spec.get("edges") or []
        if not nodes:
            iss.err(fpath, line, "graph", "graph block has no `nodes`")
        for n in (nodes if _is_list(nodes) else []):
            if not isinstance(n, dict):
                iss.err(fpath, line, "graph", f"graph node is not a mapping: {n!r}")
                continue
            if not n.get("id"):
                iss.err(fpath, line, "graph", f"graph node missing `id`: {n!r}")
            if not n.get("label"):
                iss.err(fpath, line, "graph", f"graph node {n.get('id', '?')!r} missing `label`")
            if not n.get("desc"):
                iss.warn(fpath, line, "graph", f"graph node {n.get('id', '?')!r} missing `desc` "
                         "(click-to-explain text; quality-bar requirement)")
        for e in (edges if _is_list(edges) else []):
            if not isinstance(e, dict):
                iss.err(fpath, line, "graph", f"graph edge is not a mapping: {e!r}")
                continue
            if not e.get("from"):
                iss.err(fpath, line, "graph", f"graph edge missing `from`: {e!r}")
            if not e.get("to"):
                iss.err(fpath, line, "graph", f"graph edge missing `to`: {e!r}")
            if not e.get("desc"):
                iss.warn(fpath, line, "graph",
                         f"graph edge {e.get('from', '?')}->{e.get('to', '?')} missing `desc` "
                         "(click-to-explain text; quality-bar requirement)")
    elif kind == "chart":
        if not (spec.get("series") or []):
            iss.warn(fpath, line, "chart", "chart block has no `series`")
        if not (spec.get("x") or []):
            iss.warn(fpath, line, "chart", "chart block has no `x` axis values")
    elif kind == "quiz":
        if not spec.get("q"):
            iss.err(fpath, line, "quiz", "quiz block missing `q`")
        opts = spec.get("options") or []
        if not opts:
            iss.err(fpath, line, "quiz", "quiz block missing `options`")
        elif _is_list(opts):
            if not any(isinstance(o, dict) and o.get("correct") for o in opts):
                iss.err(fpath, line, "quiz", "quiz block has no option marked `correct: true`")
    elif kind == "trace":
        cols = spec.get("columns") or []
        steps = spec.get("steps") or []
        if not cols:
            iss.err(fpath, line, "trace", "trace block missing `columns`")
        if not steps:
            iss.err(fpath, line, "trace", "trace block missing `steps`")
        for si, step in enumerate(steps if _is_list(steps) else []):
            if not isinstance(step, dict):
                iss.err(fpath, line, "trace", f"trace step {si + 1} is not a mapping")
                continue
            for ci, cell in enumerate(step.get("cells") or []):
                if isinstance(cell, dict) and not cell.get("summary"):
                    iss.warn(fpath, line, "trace",
                             f"trace step {si + 1} cell {ci + 1} missing `summary` "
                             "(the always-visible narrow-column text)")
    # unknown YAML block kinds: YAML already validated upstream, no field rules.


def check_yaml_blocks(raw: str, body: str, body_start_char: int, fpath: Path, iss: Issues):
    """For each special YAML-bodied block, parse its body with the SAME extraction the
    builder uses (the imported FENCE) and run YAML + required-field checks."""
    for m in FENCE.finditer(body):
        kind = m.group(1).lower()
        if kind not in YAML_KINDS:
            continue
        open_line = line_of(raw, body_start_char + m.start())
        body_text = m.group(2)
        body_line = line_of(raw, body_start_char + m.start(2))
        try:
            spec = yaml.safe_load(body_text)
        except yaml.YAMLError as e:
            iss.err(fpath, yaml_error_line(e, body_line), kind,
                    f"`{kind}` block YAML parse error: {str(e).splitlines()[0]} "
                    "(quote any flow value with a colon/# and double inner apostrophes)")
            continue
        if spec is None:
            iss.warn(fpath, open_line, kind, f"`{kind}` block is empty")
            continue
        check_block_fields(kind, spec, open_line, fpath, iss)


def lint_file(fpath: Path, iss: Issues):
    raw = fpath.read_text(encoding="utf-8")
    meta, m = check_frontmatter(raw, fpath, iss)
    if m:
        body = m.group(2)
        body_start_char = m.start(2)
    else:
        body = raw
        body_start_char = 0
    body_start_line = line_of(raw, body_start_char)
    check_nested_fences(raw, body, body_start_line, fpath, iss)
    check_yaml_blocks(raw, body, body_start_char, fpath, iss)
    return meta


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description="Lint Lumen learning-library page-sources.")
    ap.add_argument("--library-root", required=True)
    ap.add_argument("--topic", help="lint only this slug's (or filename's) page")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.library_root).resolve()
    topics_dir = root / "topics"
    if not topics_dir.is_dir():
        sys.stderr.write(f"no topics dir: {topics_dir}\n")
        return 2

    iss = Issues()
    files = sorted(topics_dir.glob("*.md"))
    linted = 0
    for src in files:
        try:
            meta = lint_file(src, iss)
        except Exception as e:  # never let one bad file abort the lint
            iss.add(src, 1, "ERROR", "lint", f"could not lint file: {type(e).__name__}: {e}")
            continue
        if args.topic:
            slug = (meta or {}).get("slug")
            if slug != args.topic and src.stem != args.topic:
                # drop issues collected for a non-matching file
                iss.items = [it for it in iss.items if it["file"] != str(src)]
                continue
        linted += 1

    errors = [it for it in iss.items if it["level"] == "ERROR"]
    warns = [it for it in iss.items if it["level"] == "WARN"]

    if args.json:
        print(json.dumps({
            "library_root": str(root),
            "builder_import": _BUILDER_OK,
            "special_blocks": sorted(SPECIAL),
            "files_linted": linted,
            "error_count": len(errors),
            "warning_count": len(warns),
            "issues": sorted(iss.items, key=lambda x: (x["file"], x["line"])),
        }, indent=2))
    else:
        by_file = {}
        for it in iss.items:
            by_file.setdefault(it["file"], []).append(it)
        for f in sorted(by_file):
            print(f)
            for it in sorted(by_file[f], key=lambda x: x["line"]):
                print(f'  {it["file"]}:{it["line"]}: [{it["level"]}] ({it["kind"]}) {it["message"]}')
        flag = "" if _BUILDER_OK else " (builder import FAILED — using fallback block set)"
        print(f'\nLinted {linted} page(s): {len(errors)} error(s), {len(warns)} warning(s){flag}.')

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
