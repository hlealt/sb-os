"""sb-wiki-pdf-twin.py — Build a table-aware, reading-order PDF text twin (Arm C / OD-3).

Replaces the lossy ``pypdf`` text twin produced at ``/sb-wiki-ingest`` Step 1.5
with a structured twin extracted by **PyMuPDF** (``fitz``): tables are recovered
as markdown tables via ``Page.find_tables()`` and body text is emitted in block
reading order (multi-column text de-interleaved) so dense papers stop silently
losing their tables and multi-column reading order at the first ingest step.

Per OD-3 (owner override of synthesis rec A), the structured twin OVERWRITES the
pypdf twin **in place** under the SAME filename ``raw/{origin}/{title-slug}.md``
and BECOMES the ingest input (Step 2 reads it) — it is NOT a separate
``.twin.md`` detector-only artifact. All existing references (the source page's
``raw:`` frontmatter, footnote wikilinks, raw + wiki-sources indexes) are
filename-based, so regenerating under the same filename leaves every reference
intact; no reference rewrite is needed.

CLI:
    python sb-wiki-pdf-twin.py --pdf PATH
        [--origin ORIGIN]               # destination origin folder under raw/
        [--title TITLE]                 # paper title → {title-slug}.md (else PDF stem)
        [--out PATH]                    # explicit twin output path (overrides origin/title)
        [--vision-file PATH]            # markdown with the agent's figure/chart observations
        [--vault-root PATH]             # auto-detected (walk up for sb-os.json) if omitted
        [--dry-run]                     # print the twin to stdout; write nothing
        [--json]                        # emit a machine-readable result object on stderr/last line

Vision-piggyback (spec Behavior #2): the ingest agent ALREADY reads the PDF with
a vision-capable read at Step 1. Pass its quantitative figure/chart observations
(captions + axis numbers it saw, e.g. "Fig 3: 22%->88% across 5 models") as a
markdown file via ``--vision-file``; the tool appends them verbatim under a
``## Figures & charts (vision-piggyback)`` section of the twin. This captures
chart data at zero new compute and beats OCR (the agent reads rendered pixels;
OCR reads degraded ones).

twin_fidelity fail-loud flag (spec Behavior #5): if PyMuPDF returns empty/garbled
tables on a page that SHOULD have them — detected by a per-page table-signal
heuristic (tabular layout cues present in the page text but find_tables() yielded
no usable grid) — OR the document extracts near-zero text (scanned/image-only) —
the twin is marked ``twin_fidelity: false`` in its frontmatter with a loud
"untrustworthy — table/chart content NOT checked" banner and the offending pages
are listed for unconditional escalation. The tool NEVER silently clears such a
paper: it writes the flag, lists the suspect pages, and returns a non-zero
``escalate`` field in --json. Twin-blind extraction may never look "done".

Determinism: PyMuPDF is pure-Python, fast, no ML model, no OCR — the extraction
is deterministic for a given PDF + library version. ``marker`` (OCR) is DEFERRED
(OD-3 secondary) and is NOT invoked here.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional


@contextlib.contextmanager
def _silence_c_stdout():
    """Redirect the OS-level stdout file descriptor to devnull for the duration.

    PyMuPDF's ``find_tables()`` prints a C-layer advisory ("Consider using the
    pymupdf_layout package…") straight to fd 1, which corrupts ``--json`` output.
    Redirecting the fd (not just ``sys.stdout``) catches the C write; the JSON
    result is printed AFTER this block, to the restored fd, so it stays clean.
    Best-effort: if the fd cannot be duplicated (unusual stream), it no-ops.
    """
    try:
        saved_fd = os.dup(1)
    except (OSError, ValueError, AttributeError):
        yield
        return
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        sys.stdout.flush()
        os.dup2(devnull, 1)
        yield
    finally:
        sys.stdout.flush()
        os.dup2(saved_fd, 1)
        os.close(devnull)
        os.close(saved_fd)


# ---------------------------------------------------------------------------
# Vault-root + path resolution (mirrors sb-wiki-capture-source.py conventions)
# ---------------------------------------------------------------------------

def _find_vault_root(start: Path) -> Path:
    """Walk up from start until sb-os.json is found; return that directory."""
    current = start.resolve()
    for _ in range(20):
        if (current / "sb-os.json").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    raise FileNotFoundError("sb-os.json not found in any ancestor of: " + str(start))


def _wiki_root(vault_root: Path) -> Path:
    cfg = json.loads((vault_root / "sb-os.json").read_text(encoding="utf-8"))
    rel = cfg.get("wiki_root", "3-resources/knowledge-base")
    return vault_root / rel


# ---------------------------------------------------------------------------
# Title-slug — VERBATIM the rule in wiki/workflows/shared/naming-convention.md
# § "Title-slug algorithm" (kept byte-identical to sb-wiki-capture-source.py
# _title_slug so a twin and its PDF always agree on the filename).
# ---------------------------------------------------------------------------

_TITLE_HYPHEN_RE = re.compile(r"[\s+/:–—]+")
_TITLE_DROP_RE = re.compile(r"[^a-z0-9-]")


def _title_slug(title: str) -> str:
    s = _TITLE_HYPHEN_RE.sub("-", title.lower())
    s = _TITLE_DROP_RE.sub("", s)
    return re.sub(r"-{2,}", "-", s).strip("-")


# ---------------------------------------------------------------------------
# Latin typographic ligature normalization — same surgical table as the capture
# script (academic fonts emit "Staﬀ"/"Aﬀairs" as single codepoints).
# ---------------------------------------------------------------------------

_LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
    "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
}
_LIGATURE_TABLE = {ord(k): v for k, v in _LIGATURES.items()}


def _normalize(text: str) -> str:
    """Expand the seven Latin ligature codepoints to ASCII; touch nothing else."""
    return text.translate(_LIGATURE_TABLE)


# ---------------------------------------------------------------------------
# twin_fidelity heuristics
# ---------------------------------------------------------------------------

# Below this many extracted characters on the WHOLE document, the PDF is treated
# as scanned / image-only — find_tables() and block text both yield ~nothing.
# Same floor the capture script uses for its pypdf companion.
_DOC_TEXT_MIN_CHARS = 200

# A page "should have a table" when its text carries strong tabular layout cues.
# Heuristic signals (any TWO fire → table-bearing): a run of 3+ short lines that
# look like a header row of columns; multiple lines sharing a multi-space gutter;
# the literal word "Table N" as a caption. Kept regex-only + deterministic.
_TABLE_CAPTION_RE = re.compile(r"\bTable\s+\d+\b", re.IGNORECASE)
_GUTTER_RE = re.compile(r"\S {2,}\S {2,}\S")          # 3 columns split by 2+ spaces
_PIPEY_RE = re.compile(r"\|.*\|")                       # already-pipe-delimited


@dataclass
class PageReport:
    index: int                       # 0-based page index
    n_tables: int                    # tables find_tables() returned (usable grids)
    table_expected: bool             # heuristic says this page should carry a table
    table_signal_lines: int          # count of gutter/caption signal lines
    text_chars: int                  # extracted text length on this page


@dataclass
class TwinResult:
    out_path: Optional[Path]
    title_slug: str
    page_count: int
    total_tables: int
    total_text_chars: int
    twin_fidelity: bool
    suspect_pages: list = field(default_factory=list)   # 1-based page numbers
    fidelity_reasons: list = field(default_factory=list)
    regenerated_in_place: bool = False
    wrote: bool = False

    def to_dict(self) -> dict:
        return {
            "out_path": str(self.out_path) if self.out_path else None,
            "title_slug": self.title_slug,
            "page_count": self.page_count,
            "total_tables": self.total_tables,
            "total_text_chars": self.total_text_chars,
            "twin_fidelity": self.twin_fidelity,
            "suspect_pages": self.suspect_pages,
            "fidelity_reasons": self.fidelity_reasons,
            "regenerated_in_place": self.regenerated_in_place,
            "wrote": self.wrote,
            # `escalate` is the loud machine flag: a low-fidelity twin MUST be
            # escalated unconditionally (spec #5). Never silently cleared.
            "escalate": (not self.twin_fidelity),
        }


# ---------------------------------------------------------------------------
# Table → markdown
# ---------------------------------------------------------------------------

def _cell(text: Optional[str]) -> str:
    """Render one table cell: normalize, collapse whitespace, escape pipes."""
    if text is None:
        return ""
    s = _normalize(str(text)).replace("\r", " ").replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s.replace("|", "\\|")


def _table_to_markdown(rows: list) -> str:
    """Render a find_tables() row matrix (list of list of cell strings) as a GFM
    markdown table. Columns stay in their native left-to-right reading order.
    """
    # Drop fully-empty trailing columns / rows that fitz sometimes pads.
    cleaned = [[_cell(c) for c in (r or [])] for r in rows if r is not None]
    cleaned = [r for r in cleaned if any(c for c in r)]
    if not cleaned:
        return ""
    width = max(len(r) for r in cleaned)
    cleaned = [r + [""] * (width - len(r)) for r in cleaned]

    header = cleaned[0]
    # If the first row is blank-ish, synthesize a positional header so GFM renders.
    if not any(header):
        header = [f"col{i+1}" for i in range(width)]
        body = cleaned
    else:
        body = cleaned[1:]

    lines = ["| " + " | ".join(header) + " |",
             "| " + " | ".join("---" for _ in range(width)) + " |"]
    for r in body:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def _page_text_blocks(page) -> str:
    """Return page text in block reading order (de-interleaves multi-column).

    PyMuPDF's ``get_text("blocks")`` returns (x0, y0, x1, y1, text, block_no,
    block_type). Sorting by (column-bucket, y0, x0) recovers natural reading
    order: a two-column page reads the whole left column top-to-bottom, then the
    right — instead of the interleaved line-by-line order that garbles it.
    """
    blocks = page.get_text("blocks")
    # Keep text blocks only (block_type 0); drop image blocks (type 1).
    text_blocks = [b for b in blocks if len(b) >= 7 and b[6] == 0 and (b[4] or "").strip()]
    if not text_blocks:
        return ""
    page_mid = page.rect.width / 2.0
    # Column bucket: a block whose horizontal centre is left of the page midline
    # is column 0, else column 1. Single-column pages collapse to one bucket.
    def sort_key(b):
        x0, y0, x1, y1 = b[0], b[1], b[2], b[3]
        centre = (x0 + x1) / 2.0
        col = 0 if centre < page_mid else 1
        return (col, round(y0, 1), round(x0, 1))
    text_blocks.sort(key=sort_key)
    return "\n\n".join(_normalize(b[4].strip()) for b in text_blocks)


def _assess_page(page, page_text: str, n_tables: int) -> PageReport:
    """Decide whether this page SHOULD have carried a table (twin_fidelity input)."""
    signal_lines = 0
    for line in page_text.splitlines():
        if _GUTTER_RE.search(line) or _PIPEY_RE.search(line):
            signal_lines += 1
    has_caption = bool(_TABLE_CAPTION_RE.search(page_text))
    # "Expected" = a caption that literally says "Table N" AND/OR several gutter
    # lines. Two independent signals guard against a single false positive.
    expected = (has_caption and signal_lines >= 1) or signal_lines >= 4
    return PageReport(
        index=page.number,
        n_tables=n_tables,
        table_expected=expected,
        table_signal_lines=signal_lines + (1 if has_caption else 0),
        text_chars=len(page_text),
    )


def build_twin_markdown(pdf_path: Path, title: str, vision_text: str = "") -> tuple[str, TwinResult]:
    """Extract the structured twin markdown for ``pdf_path``; return (markdown, result).

    Imports ``fitz`` lazily so the module loads even where PyMuPDF is absent
    (the caller then sees a clean error rather than an import crash).
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover - exercised via the env check
        raise SystemExit(
            "PyMuPDF (fitz) is required. Install it: pip install PyMuPDF"
        ) from exc

    slug = _title_slug(title) if title else _title_slug(pdf_path.stem)
    doc = fitz.open(str(pdf_path))

    body_parts: list[str] = []
    page_reports: list[PageReport] = []
    total_tables = 0
    total_chars = 0

    # Silence PyMuPDF's C-layer find_tables() advisory (it writes to fd 1 and
    # would corrupt --json / --dry-run stdout). The result is printed AFTER this
    # block to the restored fd.
    with _silence_c_stdout():
        for page in doc:
            page_text = _page_text_blocks(page)
            total_chars += len(page_text)

            # Tables first — find_tables() returns a TableFinder; .tables is the list.
            try:
                finder = page.find_tables()
                tables = list(finder.tables)
            except Exception:
                tables = []
            usable = 0
            table_md_chunks: list[str] = []
            for t in tables:
                try:
                    rows = t.extract()
                except Exception:
                    rows = []
                md = _table_to_markdown(rows)
                if md:
                    usable += 1
                    table_md_chunks.append(md)
            total_tables += usable

            report = _assess_page(page, page_text, usable)
            page_reports.append(report)

            # Emit the page: its block-ordered text, then any tables recovered on it.
            seg = [f"<!-- page {page.number + 1} -->", page_text]
            for i, md in enumerate(table_md_chunks, 1):
                seg.append(f"\n**Table (page {page.number + 1}, #{i}) — extracted by PyMuPDF find_tables()**\n")
                seg.append(md)
            body_parts.append("\n".join(p for p in seg if p))

    doc.close()

    # ---- twin_fidelity assessment (fail loud) ----
    suspect_pages: list[int] = []
    reasons: list[str] = []
    for r in page_reports:
        if r.table_expected and r.n_tables == 0:
            suspect_pages.append(r.index + 1)  # 1-based for humans
    if suspect_pages:
        reasons.append(
            f"PyMuPDF find_tables() returned NO usable table on {len(suspect_pages)} "
            f"page(s) whose layout signals a table: pages {suspect_pages}"
        )
    if total_chars < _DOC_TEXT_MIN_CHARS:
        reasons.append(
            f"document extracted only {total_chars} chars of text "
            f"(< {_DOC_TEXT_MIN_CHARS}) — likely scanned / image-only PDF"
        )
        if doc.page_count and not suspect_pages:
            # whole-doc thinness still escalates every page
            suspect_pages = list(range(1, doc.page_count + 1))
    twin_fidelity = not reasons

    result = TwinResult(
        out_path=None,
        title_slug=slug,
        page_count=len(page_reports),
        total_tables=total_tables,
        total_text_chars=total_chars,
        twin_fidelity=twin_fidelity,
        suspect_pages=suspect_pages,
        fidelity_reasons=reasons,
    )

    md = _render_twin(slug, title, pdf_path, result, body_parts, vision_text)
    return md, result


def _render_twin(slug: str, title: str, pdf_path: Path, result: TwinResult,
                 body_parts: list[str], vision_text: str) -> str:
    """Assemble the full twin markdown (frontmatter + body + tables + vision)."""
    front = [
        "---",
        f"twin_extractor: pymupdf",
        f"twin_fidelity: {'true' if result.twin_fidelity else 'false'}",
        f"twin_generated: {date.today().isoformat()}",
        f"source_pdf: {pdf_path.name}",
        f"pages: {result.page_count}",
        f"tables_extracted: {result.total_tables}",
    ]
    if not result.twin_fidelity:
        front.append(f"escalate_pages: {result.suspect_pages}")
    front.append("---")

    parts = ["\n".join(front), ""]
    parts.append(
        f"<!-- Structured text twin of {pdf_path.name}, extracted by PyMuPDF "
        f"(find_tables + block reading-order) for the wiki ingest. "
        f"Regenerable from the immutable PDF; this twin IS the ingest input (OD-3). -->"
    )
    parts.append("")

    if not result.twin_fidelity:
        parts.append(
            "> [!warning] twin_fidelity = FALSE — twin UNTRUSTWORTHY; "
            "table/chart content NOT checked. This page-set is escalated "
            "UNCONDITIONALLY for native-PDF review. Reasons:"
        )
        for r in result.fidelity_reasons:
            parts.append(f"> - {r}")
        parts.append("")

    if title:
        parts.append(f"# {title}")
        parts.append("")

    parts.append("\n\n".join(body_parts))

    if vision_text.strip():
        parts.append("")
        parts.append("---")
        parts.append("")
        parts.append("## Figures & charts (vision-piggyback)")
        parts.append("")
        parts.append(
            "<!-- The ingest agent's own vision read of the PDF figures/charts "
            "(captions + axis numbers). Persisted at zero new compute — beats OCR. -->"
        )
        parts.append("")
        parts.append(vision_text.strip())
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Output destination
# ---------------------------------------------------------------------------

def _resolve_out_path(args, slug: str) -> Path:
    if args.out:
        return Path(args.out)
    vault_root = Path(args.vault_root) if args.vault_root else _find_vault_root(Path.cwd())
    if not args.origin:
        raise SystemExit("--origin is required to resolve raw/{origin}/{title-slug}.md "
                         "(or pass --out for an explicit path).")
    wiki = _wiki_root(vault_root)
    return wiki / "raw" / args.origin / f"{slug}.md"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sb-wiki-pdf-twin.py",
        description="Build a table-aware, reading-order PDF text twin (PyMuPDF). "
                    "Regenerates the twin IN PLACE under raw/{origin}/{title-slug}.md "
                    "(OD-3) — the twin IS the ingest input.",
    )
    p.add_argument("--pdf", required=True, help="Path to the source PDF.")
    p.add_argument("--origin", default=None, help="Destination origin folder under raw/.")
    p.add_argument("--title", default="", help="Paper title → {title-slug}.md (else the PDF stem).")
    p.add_argument("--out", default=None, help="Explicit twin output path (overrides origin/title).")
    p.add_argument("--vision-file", default=None,
                   help="Markdown file with the agent's figure/chart observations (vision-piggyback).")
    p.add_argument("--vault-root", default=None, help="Vault root (auto-detected via sb-os.json if omitted).")
    p.add_argument("--dry-run", action="store_true", help="Print the twin to stdout; write nothing.")
    p.add_argument("--json", action="store_true", help="Print the result object as JSON (last stdout line).")
    return p


def main(argv: Optional[list] = None) -> int:
    args = _build_parser().parse_args(argv)
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        return 2

    vision_text = ""
    if args.vision_file:
        vf = Path(args.vision_file)
        if not vf.exists():
            print(f"ERROR: --vision-file not found: {vf}", file=sys.stderr)
            return 2
        vision_text = vf.read_text(encoding="utf-8")

    md, result = build_twin_markdown(pdf_path, args.title, vision_text)

    if args.dry_run:
        sys.stdout.write(md)
        if args.json:
            print("\n" + json.dumps(result.to_dict(), indent=2))
        # A low-fidelity twin returns 3 so callers can branch on escalation even
        # in dry-run; 0 when the twin is trustworthy.
        return 0 if result.twin_fidelity else 3

    out_path = _resolve_out_path(args, result.title_slug)
    result.regenerated_in_place = out_path.exists()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Regenerate-in-place: OVERWRITE any existing twin at the SAME filename so all
    # filename-based references (raw:/footnotes/indexes) resolve unchanged (OD-3).
    out_path.write_text(md, encoding="utf-8")
    result.out_path = out_path
    result.wrote = True

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        verdict = "OK" if result.twin_fidelity else "ESCALATE (twin_fidelity=false)"
        action = "regenerated in place" if result.regenerated_in_place else "created"
        print(f"twin {action}: {out_path}")
        print(f"  pages={result.page_count} tables={result.total_tables} "
              f"text_chars={result.total_text_chars} twin_fidelity={result.twin_fidelity} [{verdict}]")
        if not result.twin_fidelity:
            for r in result.fidelity_reasons:
                print(f"  ! {r}")

    return 0 if result.twin_fidelity else 3


if __name__ == "__main__":
    raise SystemExit(main())
