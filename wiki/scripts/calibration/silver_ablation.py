#!/usr/bin/env python3
"""Silver-ablation generator for the thin-page detector calibration harness.

Given a FAITHFUL wiki source (page, raw) pair, manufacture KNOWN-THIN copies of
the page by DELETING real failure-mode signal classes -- specific numbers,
decision rules / rule-labels, reasoning chains, and author caveats (NEVER random
sentences) -- and emit the EXACT removed-item ground truth (what was deleted, of
which class, where).

This is the keystone of the detector build (synthesis.md top-1 next step, OD-1):
tasks 2.2 (typed-retention), 2.3 (density + chunked recall), and 2.4 (escalation
ladder + worst-first ranking) all calibrate their thresholds on the set this
produces. The deleted-signal classes deliberately mirror the typed-retention
detector classes so the ground truth aligns with what 2.2 will measure:

    numeric         -> T2 numeric-atom retention
    table_row       -> T3 table-row retention
    rule_label      -> T4 rule/framework-label retention
    named_entity    -> T5 named-entity retention
    caveat          -> T6 caveat survival
    reasoning_chain -> (reasoning-chain dropping -- an UNMEASURED class today;
                        present so OD-6's unmeasured-class guardrail can be
                        exercised by 2.2/2.4: numbers kept but reasoning dropped)

The detector COMPARE-SET (wiki-schema.md): only Substance + Counterpoints +
Methodology + Notable quotes participate; frontmatter, the lead paragraph, the
`My take` user half, and Sources are EXCLUDED. Ablation only ever deletes from
the compare-set sections, so the ground truth matches what a detector reading the
same compare-set would see.

GRADED deletion: `--grade 0.05|0.25|0.50` deletes that fraction of the page's
eligible items, chosen as a PREFIX of one deterministic round-robin order across
the signal classes, so (a) a higher grade is a STRICT superset of a lower grade's
deletions and (b) each grade is spread across every class present -- monotonic,
as OD-7 worst-first ranking validation by 2.4 requires (more deleted => ranked
worse; equal-count grades would be indistinguishable to the ranker).

Output:
  - one ablated `.md` per (source, grade) under the output dir, byte-faithful to
    the original except the deleted spans (and a provenance frontmatter stamp);
  - a JSON ground-truth record per ablated page (the deleted items by class, each
    with verbatim text + the section + a character offset within the section);
  - when run with `--manifest`, all records are merged into one manifest file.

NOT a wiki-corpus writer: outputs are FIXTURES and MUST land under a calibration
data dir (default: this script's `data/` sibling), NEVER under
`{wiki_root}/wiki/sources/` or `{wiki_root}/raw/`. The generator refuses to write
outside its configured output root.

Usage
-----
    # ablate one page at three grades, append to a manifest
    python silver_ablation.py ablate \
        --page  <vault>/3-resources/knowledge-base/wiki/sources/papers/<slug>.md \
        --grades 0.05,0.25,0.50 \
        --out-dir <this-dir>/data/ablated \
        --manifest <this-dir>/data/ground-truth-manifest.json

    # ablate every (page,raw) pair listed in a batch file (one page path per line)
    python silver_ablation.py ablate-batch \
        --batch <this-dir>/data/ablation-batch.txt \
        --grades 0.05,0.25,0.50 \
        --out-dir <this-dir>/data/ablated \
        --manifest <this-dir>/data/ground-truth-manifest.json

    # inspect what WOULD be deleted from a page (no writes)
    python silver_ablation.py classes --page <slug>.md --grade 0.50 --json

Exit codes: 0 ok; 2 usage / bad input; 3 nothing ablatable (page has no eligible
signal in the compare-set -- not a fixture-worthy source).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = "silver-ablation/1"

# Sections that participate in the detector compare-set (wiki-schema.md).
# Frontmatter, the lead paragraph, `My take`, and `Sources` are EXCLUDED.
COMPARE_SECTIONS = ("Substance", "Counterpoints", "Methodology", "Notable quotes")

# ---------------------------------------------------------------------------
# Markdown structure parsing
# ---------------------------------------------------------------------------


@dataclass
class Section:
    """One H2 section of a source page."""

    name: str            # heading text, e.g. "Substance"
    level: int           # heading level (2 for ##)
    start: int           # char offset of the heading line start in the full doc
    body_start: int      # char offset where the body (after the heading line) starts
    end: int             # char offset where this section ends (next heading / EOF)

    def body(self, doc: str) -> str:
        return doc[self.body_start:self.end]


def split_frontmatter(doc: str) -> tuple[str, int]:
    """Return (frontmatter_block_or_empty, body_offset). body_offset is the char
    index in `doc` where content after the closing `---` begins."""
    if doc.startswith("---\n") or doc.startswith("---\r\n"):
        # find the closing fence at the start of a line
        m = re.search(r"^---[ \t]*\r?\n", doc[3:], re.MULTILINE)
        if m:
            close = 3 + m.end()
            return doc[:close], close
    return "", 0


def parse_sections(doc: str) -> list[Section]:
    """Parse all ATX headings (## .. ######) into Section spans. Level-1 (#) title
    is treated as a heading too so its span is bounded, but the compare-set only
    ever selects level-2 sections by name."""
    headings = []
    for m in re.finditer(r"^(#{1,6})[ \t]+(.+?)[ \t]*\r?$", doc, re.MULTILINE):
        level = len(m.group(1))
        name = m.group(2).strip()
        line_start = m.start()
        body_start = m.end()
        # skip the trailing newline of the heading line for body_start
        nl = doc.find("\n", body_start)
        body_start = (nl + 1) if nl != -1 else len(doc)
        headings.append((level, name, line_start, body_start))
    sections: list[Section] = []
    for i, (level, name, line_start, body_start) in enumerate(headings):
        end = headings[i + 1][2] if i + 1 < len(headings) else len(doc)
        sections.append(Section(name, level, line_start, body_start, end))
    return sections


def compare_sections(doc: str) -> list[Section]:
    """The compare-set sections present in the doc, in document order."""
    secs = parse_sections(doc)
    return [s for s in secs if s.level == 2 and s.name in COMPARE_SECTIONS]


# ---------------------------------------------------------------------------
# Signal-class extraction
# ---------------------------------------------------------------------------


@dataclass
class Item:
    """One extracted signal item, eligible for deletion."""

    cls: str             # signal class
    text: str            # verbatim text that will be deleted (number token, line, or sentence)
    section: str         # compare-set section it lives in
    sec_offset: int      # char offset of `text` within the section body
    span: tuple[int, int] = field(default=(0, 0))  # absolute (start,end) in the full doc
    note: str = ""       # optional context (e.g. the enclosing sentence for a number)


# --- numeric atoms (T2) ----------------------------------------------------
# A numeric atom: a number with optional magnitude word / unit / %, EXCLUDING
# bare years, citation markers [^N] / [N], and figure/table/page refs.
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
_NUM_TOKEN_RE = re.compile(
    r"""
    (?<![\w.])                                   # not mid-identifier
    (?:[\$€£]\s?)?                               # optional currency
    \d{1,3}(?:,\d{3})+(?:\.\d+)?                 # 1,234,567(.8)  grouped
    | (?<![\w.])(?:[\$€£]\s?)?\d+(?:\.\d+)?       # 40  3.0  0.14
    """,
    re.VERBOSE,
)
# magnitude / unit suffix that may follow a number (kept with the atom)
_SUFFIX_RE = re.compile(
    r"\s*(?:x|×|%|MW|GW|kW|TW|billion|million|trillion|bn|M|B|K|OOMs?|"
    r"orders? of magnitude|per year|/year|FTE|TPUs?|GPUs?)\b",
    re.IGNORECASE,
)


def _is_citation_or_ref(doc: str, start: int, end: int) -> bool:
    """True if the number at [start,end) is a citation [^N]/[N] or a figure/table/
    page reference, which are NOT droppable signal."""
    # citation footnote marker [^N]
    pre = doc[max(0, start - 2):start]
    if pre.endswith("[^") or pre.endswith("["):
        nxt = doc[end:end + 1]
        if nxt == "]":
            return True
    # figure/table/page/section reference word immediately before
    window = doc[max(0, start - 14):start].lower()
    if re.search(r"\b(figure|fig|table|tbl|page|pg|section|sec|chapter|eq|equation|v)\.?\s*$", window):
        return True
    return False


def extract_numeric(doc: str, sec: Section) -> list[Item]:
    body = sec.body(doc)
    items: list[Item] = []
    for m in _NUM_TOKEN_RE.finditer(body):
        s, e = m.start(), m.end()
        token = m.group(0)
        # strip a leading currency space artifact
        raw_num = re.sub(r"[\$€£,\s]", "", token)
        # bare year exclusion (only if no suffix and no currency/decimal)
        if _YEAR_RE.match(raw_num) and "." not in raw_num and not token.strip().startswith(("$", "€", "£")):
            # peek suffix: a year with a unit (e.g. "2.4x") won't be a bare year anyway
            suff = _SUFFIX_RE.match(body[e:])
            if not suff:
                continue
        abs_s, abs_e = sec.body_start + s, sec.body_start + e
        if _is_citation_or_ref(doc, abs_s, abs_e):
            continue
        # extend to include an immediate magnitude/unit suffix
        suff = _SUFFIX_RE.match(body[e:])
        if suff:
            e = e + suff.end()
            token = body[m.start():e]
        # enclosing sentence as note
        note = _enclosing_sentence(body, m.start())
        items.append(Item(
            cls="numeric", text=token.strip(), section=sec.name, sec_offset=s,
            span=(sec.body_start + m.start(), sec.body_start + e), note=note,
        ))
    return items


# --- table rows (T3) -------------------------------------------------------
def extract_table_rows(doc: str, sec: Section) -> list[Item]:
    body = sec.body(doc)
    items: list[Item] = []
    for m in re.finditer(r"^[ \t]*\|.+\|[ \t]*\r?$", body, re.MULTILINE):
        line = m.group(0)
        # skip the header separator row (|---|---|)
        if re.match(r"^[ \t]*\|[\s:\-|]+\|[ \t]*$", line):
            continue
        # skip the header row itself? No -- a dropped header is signal too; keep all
        items.append(Item(
            cls="table_row", text=line.strip(), section=sec.name, sec_offset=m.start(),
            span=(sec.body_start + m.start(), sec.body_start + m.end()),
        ))
    return items


# --- rule / framework labels (T4) ------------------------------------------
# Bold labels that name a rule / method / test / framework, e.g.
# "**Three cost approaches.**", "**Frontier selection.**", "**Amortization.**",
# "**Limitations the authors state.**"; also inline "Rule:" / "Test:" labels.
_RULE_LABEL_RE = re.compile(
    r"\*\*([^*\n]{2,80}?)\*\*"        # **Label**
    r"|(?<![\w])(Rule|Test|Law|Principle|Theorem|Criterion|Step)\s+\d+\s*[:.]"  # Rule 3:
)


def extract_rule_labels(doc: str, sec: Section) -> list[Item]:
    body = sec.body(doc)
    items: list[Item] = []
    for m in _RULE_LABEL_RE.finditer(body):
        label = (m.group(1) or m.group(0)).strip()
        # caveat-labels are handled by the caveat class; don't double-count the
        # "Limitations the authors state" label as a rule (it is the caveat header)
        if re.search(r"limitation|caveat|threat|uncertain|confidence|neglect", label, re.IGNORECASE):
            continue
        items.append(Item(
            cls="rule_label", text=label, section=sec.name, sec_offset=m.start(),
            span=(sec.body_start + m.start(), sec.body_start + m.end()),
            note=_enclosing_sentence(body, m.start()),
        ))
    return items


# --- caveats (T6) ----------------------------------------------------------
# Author-flagged uncertainty/limitation: a sentence (or bullet) containing a
# caveat marker. The whole sentence is the deletable item (dropping a caveat =
# dropping the author's hedge).
_CAVEAT_MARKERS = re.compile(
    r"\b(limitation|limitations|caveat|threats? to validity|needs? validation|"
    r"unvalidated|unproven|uncertain(?:ty)?|low[- ]confidence|"
    r"the authors? (?:state|note|acknowledge|flag|caution)|neglected|"
    r"may be conservative|understates?|robustness)\b",
    re.IGNORECASE,
)


def extract_caveats(doc: str, sec: Section) -> list[Item]:
    body = sec.body(doc)
    items: list[Item] = []
    seen_spans: set[tuple[int, int]] = set()
    for m in _CAVEAT_MARKERS.finditer(body):
        s, e = _sentence_span(body, m.start())
        key = (s, e)
        if key in seen_spans:
            continue
        seen_spans.add(key)
        text = body[s:e].strip()
        if len(text) < 8:
            continue
        items.append(Item(
            cls="caveat", text=text, section=sec.name, sec_offset=s,
            span=(sec.body_start + s, sec.body_start + e),
        ))
    return items


# --- reasoning chains (UNMEASURED class) -----------------------------------
# A causal/inferential sentence carrying a reasoning connective. Dropping these
# while keeping the numbers is the "numbers kept, reasoning dropped" failure mode
# OD-1 names -- a class the typed-retention detector does NOT measure today.
_REASON_MARKERS = re.compile(
    r"\b(because|therefore|thus|hence|so that|which (?:means|implies)|"
    r"as a result|consequently|implies that|implication|raising|driven by|"
    r"rather than|whereas|since (?!\d))\b",
    re.IGNORECASE,
)


def extract_reasoning(doc: str, sec: Section) -> list[Item]:
    body = sec.body(doc)
    items: list[Item] = []
    seen_spans: set[tuple[int, int]] = set()
    for m in _REASON_MARKERS.finditer(body):
        s, e = _sentence_span(body, m.start())
        key = (s, e)
        if key in seen_spans:
            continue
        seen_spans.add(key)
        text = body[s:e].strip()
        if len(text) < 20:
            continue
        items.append(Item(
            cls="reasoning_chain", text=text, section=sec.name, sec_offset=s,
            span=(sec.body_start + s, sec.body_start + e),
        ))
    return items


# --- named entities (T5) ---------------------------------------------------
# Wikilink targets ([[slug.md]] / [[slug.md|alias]]) -- the page's named, linked
# concepts/entities. Cheapest, highest-precision named-item signal in this corpus.
_WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+?\.md)(?:#[^\]\|]+)?(?:\|[^\]]+)?\]\]")


def extract_named_entities(doc: str, sec: Section) -> list[Item]:
    body = sec.body(doc)
    items: list[Item] = []
    for m in _WIKILINK_RE.finditer(body):
        target = m.group(1)
        items.append(Item(
            cls="named_entity", text=m.group(0), section=sec.name, sec_offset=m.start(),
            span=(sec.body_start + m.start(), sec.body_start + m.end()),
            note=target,
        ))
    return items


EXTRACTORS = {
    "numeric": extract_numeric,
    "table_row": extract_table_rows,
    "rule_label": extract_rule_labels,
    "caveat": extract_caveats,
    "reasoning_chain": extract_reasoning,
    "named_entity": extract_named_entities,
}

# Default classes to ablate. named_entity is deletion-by-token (surgical); the
# sentence-level classes (caveat, reasoning_chain) delete whole sentences;
# numeric deletes the number token only (leaving the sentence, so the
# "magnitude removed but prose kept" case is realistic); table_row deletes a row.
DEFAULT_CLASSES = ("numeric", "table_row", "rule_label", "caveat", "reasoning_chain", "named_entity")


# ---------------------------------------------------------------------------
# Sentence helpers
# ---------------------------------------------------------------------------
def _sentence_span(text: str, pos: int) -> tuple[int, int]:
    """Return the (start, end) char span of the sentence/bullet containing `pos`.
    Bullets (lines starting with - or *) are bounded by their line; prose
    sentences by `. ! ?` terminators and blank lines."""
    # bullet line?
    line_start = text.rfind("\n", 0, pos) + 1
    line_end = text.find("\n", pos)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    if re.match(r"^[ \t]*[-*+]\s", line) or re.match(r"^[ \t]*\d+\.\s", line):
        return line_start, line_end
    # prose: search back to a sentence terminator or blank line
    start = line_start
    back = re.search(r"[.!?]\s+\S(?=[^.!?]*$)", text[line_start:pos][::-1])
    # simpler: scan backward for ". " boundary
    s = pos
    while s > 0:
        if text[s - 1] in ".!?" and (s >= len(text) or text[s:s + 1] in (" ", "\n", "")):
            break
        if text[s - 1] == "\n" and s >= 2 and text[s - 2] == "\n":
            break
        s -= 1
    # forward to terminator
    e = pos
    while e < len(text):
        if text[e] in ".!?":
            e += 1
            break
        if text[e] == "\n" and e + 1 < len(text) and text[e + 1] == "\n":
            break
        e += 1
    return max(s, start if start > 0 else 0), min(e, len(text)) if e > pos else line_end


def _enclosing_sentence(text: str, pos: int) -> str:
    s, e = _sentence_span(text, pos)
    return text[s:e].strip()[:300]


# ---------------------------------------------------------------------------
# Ablation
# ---------------------------------------------------------------------------
@dataclass
class AblationRecord:
    schema: str
    kind: str                       # source kind: paper | article | podcast
    origin: str
    source_page: str                # vault-relative path to the original page
    raw_path: Optional[str]         # vault-relative path to the raw (from frontmatter `raw:`)
    grade: float
    ablated_page: str               # path to the produced thin fixture
    source_sha256: str              # sha of the original page bytes (provenance)
    deleted: list[dict]             # deleted items: {cls, text, section, span, note}
    class_counts: dict              # {cls: {eligible, deleted}}
    label: str = "thin"             # ablated fixtures are thin by construction


def extract_all(doc: str, classes=DEFAULT_CLASSES) -> list[Item]:
    items: list[Item] = []
    for sec in compare_sections(doc):
        for cls in classes:
            items.extend(EXTRACTORS[cls](doc, sec))
    return items


def _global_order(items: list[Item], seed_key: str) -> list[Item]:
    """One deterministic deletion order for the whole page, ROUND-ROBIN across
    classes so any prefix is spread across classes (a 5% cut still touches every
    class present, not just the largest). The order is seeded on page identity so
    it is stable across runs, and selection takes a PREFIX of it -- which makes a
    higher grade a STRICT SUPERSET of a lower grade whenever the pool has more
    items than the lower grade's count (the monotonicity OD-7 worst-first ranking
    requires; equal-count grades on a page would make those grades
    indistinguishable to the ranker)."""
    by_cls: dict[str, list[Item]] = {}
    for it in items:
        by_cls.setdefault(it.cls, []).append(it)
    # shuffle within each class deterministically
    shuffled: dict[str, list[Item]] = {}
    for cls in sorted(by_cls):
        rng = random.Random(f"{seed_key}|{cls}")
        lst = by_cls[cls][:]
        rng.shuffle(lst)
        shuffled[cls] = lst
    # round-robin interleave across classes (stable class order)
    order: list[Item] = []
    classes = sorted(shuffled)
    i = 0
    while any(shuffled[c] for c in classes):
        c = classes[i % len(classes)]
        if shuffled[c]:
            order.append(shuffled[c].pop(0))
        i += 1
    return order


def select_for_grade(items: list[Item], grade: float, seed_key: str) -> list[Item]:
    """Pick ceil(grade * total) items as a PREFIX of the page's single global
    round-robin deletion order. Prefix-of-one-order => a higher grade is a strict
    superset of a lower one (monotonic, OD-7), while the round-robin keeps each
    grade spread across the signal classes present."""
    import math
    if grade <= 0:
        return []
    order = _global_order(items, seed_key)
    k = min(math.ceil(grade * len(order)), len(order))
    return order[:k]


def apply_deletions(doc: str, chosen: list[Item]) -> str:
    """Delete the chosen spans from the doc. Overlapping spans (e.g. a number
    inside a caveat sentence also picked) are coalesced -- the larger span wins,
    deletions never double-cut. Whole-line deletions also drop the trailing
    newline + any now-empty bullet residue is left as a blank line (a detector
    reads content, not blank lines)."""
    if not chosen:
        return doc
    spans = sorted({it.span for it in chosen})
    # coalesce overlaps
    merged: list[list[int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    out = []
    prev = 0
    for s, e in merged:
        out.append(doc[prev:s])
        # if the deleted span is a whole line, also consume the trailing newline
        if (s == 0 or doc[s - 1] == "\n") and e < len(doc) and doc[e] == "\n":
            e += 1
        prev = e
    out.append(doc[prev:])
    return "".join(out)


def frontmatter_stamp(grade: float, n_deleted: int, src_rel: str) -> str:
    return (
        f"<!-- SILVER-ABLATION FIXTURE -- DO NOT INGEST. "
        f"grade={grade} deleted={n_deleted} from={src_rel} "
        f"schema={SCHEMA_VERSION} -->\n"
    )


def detect_kind(page_path: Path, origin: str) -> str:
    """Classify the source kind for stratification."""
    PODCAST_ORIGINS = {
        "lennys-podcast", "prof-g", "acast", "spotify-creators", "iheartmedia-ir",
        "podcastnewsdaily", "the-knowledge-project", "dwarkesh", "siriusxm-media",
    }
    if origin == "papers":
        return "paper"
    if origin in PODCAST_ORIGINS:
        return "podcast"
    return "article"


def read_raw_field(fm: str) -> Optional[str]:
    m = re.search(r'^raw:\s*"?\[\[([^\]]+)\]\]"?', fm, re.MULTILINE)
    return m.group(1) if m else None


def ablate_page(page_path: Path, grades: list[float], out_dir: Path,
                vault_root: Path, classes=DEFAULT_CLASSES) -> list[AblationRecord]:
    doc = page_path.read_text(encoding="utf-8")
    fm, _ = split_frontmatter(doc)
    origin = page_path.parent.name
    kind = detect_kind(page_path, origin)
    raw_field = read_raw_field(fm)
    raw_rel = None
    if raw_field:
        candidate = vault_root / "3-resources" / "knowledge-base" / "raw" / origin / raw_field
        raw_rel = os.path.relpath(candidate, vault_root).replace("\\", "/") if candidate.exists() else f"raw/{origin}/{raw_field}"
    src_sha = hashlib.sha256(doc.encode("utf-8")).hexdigest()
    src_rel = os.path.relpath(page_path, vault_root).replace("\\", "/")

    items = extract_all(doc, classes)
    if not items:
        return []  # nothing ablatable -> caller treats as skip
    seed_key = src_rel

    records: list[AblationRecord] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for grade in grades:
        chosen = select_for_grade(items, grade, seed_key)
        ablated = apply_deletions(doc, chosen)
        gtag = f"g{int(round(grade * 100)):02d}"
        out_name = f"{origin}__{page_path.stem}__{gtag}.md"
        out_path = out_dir / out_name
        stamped = frontmatter_stamp(grade, len(chosen), src_rel) + ablated
        out_path.write_text(stamped, encoding="utf-8")

        # class counts (eligible vs deleted)
        counts: dict[str, dict] = {}
        for it in items:
            counts.setdefault(it.cls, {"eligible": 0, "deleted": 0})
            counts[it.cls]["eligible"] += 1
        for it in chosen:
            counts[it.cls]["deleted"] += 1

        deleted = [
            {"cls": it.cls, "text": it.text, "section": it.section,
             "span": list(it.span), "note": it.note}
            for it in sorted(chosen, key=lambda x: x.span)
        ]
        records.append(AblationRecord(
            schema=SCHEMA_VERSION, kind=kind, origin=origin, source_page=src_rel,
            raw_path=raw_rel, grade=grade,
            ablated_page=os.path.relpath(out_path, vault_root).replace("\\", "/"),
            source_sha256=src_sha, deleted=deleted, class_counts=counts,
        ))
    return records


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _vault_root_from(path: Path) -> Path:
    """Resolve the vault root by walking up to the dir holding sb-os.json."""
    p = path.resolve()
    for anc in [p, *p.parents]:
        if (anc / "sb-os.json").exists():
            return anc
    # fallback: assume <vault>/3-resources/tools/sb-os/wiki/scripts/calibration
    return Path(__file__).resolve().parents[5]


def _parse_grades(s: str) -> list[float]:
    return [float(x) for x in s.split(",") if x.strip()]


def _guard_out_dir(out_dir: Path, vault_root: Path) -> None:
    """Refuse to write fixtures into the live wiki corpus."""
    rp = out_dir.resolve()
    kb = (vault_root / "3-resources" / "knowledge-base").resolve()
    for forbidden in (kb / "wiki", kb / "raw"):
        try:
            rp.relative_to(forbidden)
        except ValueError:
            continue
        print(f"REFUSING: output dir {rp} is inside the live wiki corpus "
              f"({forbidden}). Fixtures must land in a calibration data dir.",
              file=sys.stderr)
        sys.exit(2)


def cmd_ablate(args) -> int:
    page = Path(args.page)
    if not page.exists():
        print(f"page not found: {page}", file=sys.stderr)
        return 2
    vault_root = Path(args.vault_root).resolve() if args.vault_root else _vault_root_from(page)
    out_dir = Path(args.out_dir)
    _guard_out_dir(out_dir, vault_root)
    grades = _parse_grades(args.grades)
    records = ablate_page(page, grades, out_dir, vault_root)
    if not records:
        print(f"NO ELIGIBLE SIGNAL in compare-set of {page} -- not ablatable", file=sys.stderr)
        return 3
    _emit_records(records, args.manifest, vault_root)
    for r in records:
        nd = len(r.deleted)
        print(f"  grade {r.grade}: {nd} items deleted -> {r.ablated_page}")
    return 0


def cmd_ablate_batch(args) -> int:
    batch = Path(args.batch)
    if not batch.exists():
        print(f"batch file not found: {batch}", file=sys.stderr)
        return 2
    vault_root = Path(args.vault_root).resolve() if args.vault_root else _vault_root_from(batch)
    out_dir = Path(args.out_dir)
    _guard_out_dir(out_dir, vault_root)
    grades = _parse_grades(args.grades)
    all_records: list[AblationRecord] = []
    skipped: list[str] = []
    for line in batch.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        page = (vault_root / line) if not os.path.isabs(line) else Path(line)
        if not page.exists():
            skipped.append(f"{line} (not found)")
            continue
        recs = ablate_page(page, grades, out_dir, vault_root)
        if not recs:
            skipped.append(f"{line} (no eligible signal)")
            continue
        all_records.extend(recs)
        print(f"OK  {line}: {len(recs)} grades, "
              f"{len(all_records and all_records[-1].deleted)} items at top grade")
    _emit_records(all_records, args.manifest, vault_root)
    print(f"\nABLATED {len({r.source_page for r in all_records})} pages "
          f"x {len(grades)} grades = {len(all_records)} fixtures")
    if skipped:
        print(f"SKIPPED {len(skipped)}:")
        for s in skipped:
            print(f"  - {s}")
    return 0


def cmd_classes(args) -> int:
    page = Path(args.page)
    if not page.exists():
        print(f"page not found: {page}", file=sys.stderr)
        return 2
    doc = page.read_text(encoding="utf-8")
    items = extract_all(doc)
    grade = float(args.grade) if args.grade else 0.0
    seed_key = page.name
    chosen = set(id(x) for x in select_for_grade(items, grade, seed_key)) if grade else set()
    by_cls: dict[str, list[Item]] = {}
    for it in items:
        by_cls.setdefault(it.cls, []).append(it)
    if args.json:
        out = {cls: {"eligible": len(lst),
                     "would_delete_at_grade": (__import__("math").ceil(grade * len(lst)) if grade else 0),
                     "samples": [i.text for i in lst[:5]]}
               for cls, lst in by_cls.items()}
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(f"{page.name} -- compare-set signal inventory:")
        for cls, lst in sorted(by_cls.items()):
            print(f"  {cls:16s} eligible={len(lst):3d}")
            for i in lst[:3]:
                t = i.text.replace("\n", " ")
                print(f"      e.g. [{i.section}] {t[:80]}")
    return 0


def _emit_records(records: list[AblationRecord], manifest_path: Optional[str], vault_root: Path) -> None:
    if not manifest_path:
        return
    mpath = Path(manifest_path)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    # merge with an existing manifest's ablation list if present (so batch +
    # single runs accrete), keyed on (source_page, grade)
    existing = {"schema": SCHEMA_VERSION, "ablations": [], "gold": []}
    if mpath.exists():
        try:
            existing = json.loads(mpath.read_text(encoding="utf-8"))
            existing.setdefault("ablations", [])
            existing.setdefault("gold", [])
        except json.JSONDecodeError:
            pass
    index = {(a["source_page"], a["grade"]): i for i, a in enumerate(existing["ablations"])}
    for r in records:
        d = asdict(r)
        key = (d["source_page"], d["grade"])
        if key in index:
            existing["ablations"][index[key]] = d
        else:
            existing["ablations"].append(d)
    mpath.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("ablate", help="ablate one page at the given grades")
    a.add_argument("--page", required=True)
    a.add_argument("--grades", default="0.05,0.25,0.50")
    a.add_argument("--out-dir", required=True)
    a.add_argument("--manifest", default=None)
    a.add_argument("--vault-root", default=None)
    a.set_defaults(func=cmd_ablate)

    b = sub.add_parser("ablate-batch", help="ablate every page listed in a batch file")
    b.add_argument("--batch", required=True)
    b.add_argument("--grades", default="0.05,0.25,0.50")
    b.add_argument("--out-dir", required=True)
    b.add_argument("--manifest", default=None)
    b.add_argument("--vault-root", default=None)
    b.set_defaults(func=cmd_ablate_batch)

    c = sub.add_parser("classes", help="show the signal inventory of a page (no writes)")
    c.add_argument("--page", required=True)
    c.add_argument("--grade", default=None)
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_classes)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
