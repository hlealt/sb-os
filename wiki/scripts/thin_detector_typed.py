#!/usr/bin/env python3
"""Typed-retention detector (T2-T6) -- the embedding-free floor of the thin-page
detector (synthesis.md SS2b; spec thin-page-detector-spec.md Behavior #2).

PURE regex + set arithmetic. NO embeddings, NO LLM, NO network. Runs in
milliseconds/page and works when `VOYAGE_API_KEY` is absent -- that property is
the whole point: it is the detection floor that still fires when the embedding
layer (Layer-1b, task 2.3) is off.

Given a (page, raw) pair it reports, per signal class, whether the specific
quantities survived from raw into page, and -- for whatever is missing -- the
missing items WITH their raw-sentence context. That missing-item packet is the
input the NLI layer (task 2.4) consumes (it resolves paraphrase, e.g. "a third"
vs "33%", which this layer deliberately does NOT).

Classes (mirroring the calibration ground-truth classes so recall is measurable
against `calibration/data/ground-truth-manifest.json`):

    T2 numeric      numeric atoms (magnitude-normalized; 1% tol, 5% for >1000 rounded)
    T3 table_row    markdown table rows (row-shingle + token-set fallback)
    T4 rule_label   bold rule/framework labels + "Rule N:"-style labels
    T5 named_entity wikilink targets [[slug.md]] (substring presence)
    T6 caveat       author-flagged-uncertainty sentences (survival)

`reasoning_chain` is INTENTIONALLY NOT a class here -- it is the OD-6
unmeasured-class bait carried by the calibration set so task 2.2/2.4 can
demonstrate "a re-do can be worse on an unmeasured class and still pass the
mechanical gate". Do not add a T-class for it.

Per-class MIN-COUNT GUARDS: a class whose raw has fewer than its atom floor is
SKIPPED (its retention ratio would be noise) and the skip is reported with its
reason. Floors: numeric 5, rule_label 3, table_row 1, named_entity 1, caveat 1.

Output (a `PageReport`): per-class `retention` ratio in [0,1] + the `missing`
items (each with verbatim text, section, and raw-sentence context) + the
`skipped` classes with reasons.

CLI
---
    # single (page, raw) pair -> JSON packet on stdout
    python thin_detector_typed.py report --page <page>.md --raw <raw>.md [--json]

    # ablation-set validation (recall over the MEASURED classes), key-independent
    python thin_detector_typed.py validate \
        [--manifest <calibration>/data/ground-truth-manifest.json] \
        [--json-out <path>] [--kind paper|article|podcast] [--grade 0.05|0.25|0.50]

The `validate` command reads the keystone manifest through `load_manifest.py`
(the cal/test discipline holds -- it touches ablations only, never gold_test()).
For each ablation it runs `detect(ablated_page, original_source_page)` and counts
a ground-truth deleted item as CAUGHT when the detector reports a missing item
that matches it (numeric: magnitude-normalized within tolerance; other classes:
case-insensitive containment either direction -- same semantics as the keystone's
`recall_of`). Recall is reported over the measured classes (reasoning_chain is
excluded and reported separately as the OD-6 bait).

Exit codes: 0 ok (validate: recall >= floor); 2 usage/bad input; 4 validate ran
but recall < the configured floor (default 0.90).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# Compare-set sections (wiki-schema.md): only these participate. Frontmatter,
# the lead paragraph, `My take`, and `Sources` are EXCLUDED.
COMPARE_SECTIONS = ("Substance", "Counterpoints", "Methodology", "Notable quotes")

# Per-class minimum atom counts in the RAW below which the class is skipped
# (the retention ratio would be noise). spec Edge Cases: <5 numeric -> skip T2,
# <3 rule -> skip T4.
MIN_COUNT_FLOORS = {
    "numeric": 5,
    "rule_label": 3,
    "table_row": 1,
    "named_entity": 1,
    "caveat": 1,
}

# Measured classes (the recall denominator). reasoning_chain is deliberately NOT
# here -- it is the OD-6 unmeasured bait.
MEASURED_CLASSES = ("numeric", "table_row", "rule_label", "named_entity", "caveat")

# Numeric match tolerances.
NUM_TOL = 0.01          # 1% for exact facts
NUM_TOL_ROUNDED = 0.05  # 5% for >1000-magnitude rounded figures
ROUNDED_MAGNITUDE = 1000.0

# Table-row token-set fallback threshold (codex L3): a raw row is retained if a
# page row shares >= this fraction of its tokens (Jaccard-on-the-raw-side).
TABLE_TOKENSET_THRESHOLD = 0.72


# ===========================================================================
# Markdown structure parsing  (compare-set extraction)
# ===========================================================================
@dataclass
class Section:
    name: str
    level: int
    body_start: int
    end: int

    def body(self, doc: str) -> str:
        return doc[self.body_start:self.end]


def _strip_frontmatter_offset(doc: str) -> int:
    """Char offset where content after a leading YAML frontmatter block begins.
    A silver-ablation fixture prepends an HTML-comment stamp line BEFORE the
    frontmatter; tolerate any leading lines until the first `---` fence."""
    # find the first frontmatter fence at a line start
    m = re.search(r"(?m)^---[ \t]*\r?\n", doc)
    if not m:
        return 0
    open_close = re.search(r"(?m)^---[ \t]*\r?\n", doc[m.end():])
    if open_close:
        return m.end() + open_close.end()
    return 0


def parse_sections(doc: str) -> list[Section]:
    headings = []
    for m in re.finditer(r"(?m)^(#{1,6})[ \t]+(.+?)[ \t]*\r?$", doc):
        level = len(m.group(1))
        name = m.group(2).strip()
        line_start = m.start()
        nl = doc.find("\n", m.end())
        body_start = (nl + 1) if nl != -1 else len(doc)
        headings.append((level, name, line_start, body_start))
    out: list[Section] = []
    for i, (level, name, line_start, body_start) in enumerate(headings):
        end = headings[i + 1][2] if i + 1 < len(headings) else len(doc)
        out.append(Section(name, level, body_start, end))
    return out


def compare_sections(doc: str) -> list[Section]:
    """The compare-set H2 sections present, in document order. The user-half
    separator `---` does not create a heading; `My take`/`Sources` are excluded by
    name regardless of where the separator lands."""
    return [s for s in parse_sections(doc) if s.level == 2 and s.name in COMPARE_SECTIONS]


def compare_text(doc: str) -> str:
    """Concatenated compare-set section bodies (used for substring presence checks)."""
    return "\n".join(s.body(doc) for s in compare_sections(doc))


# ===========================================================================
# Sentence helpers (raw-sentence context for the missing-item packet)
# ===========================================================================
def _sentence_span(text: str, pos: int) -> tuple[int, int]:
    """(start, end) of the sentence/bullet containing `pos`. Bullets bounded by
    their line; prose by `. ! ?` and blank lines."""
    line_start = text.rfind("\n", 0, pos) + 1
    line_end = text.find("\n", pos)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    if re.match(r"^[ \t]*[-*+]\s", line) or re.match(r"^[ \t]*\d+\.\s", line):
        return line_start, line_end
    s = pos
    while s > 0:
        if text[s - 1] in ".!?" and (s >= len(text) or text[s:s + 1] in (" ", "\n", "")):
            break
        if text[s - 1] == "\n" and s >= 2 and text[s - 2] == "\n":
            break
        s -= 1
    e = pos
    while e < len(text):
        if text[e] in ".!?":
            e += 1
            break
        if text[e] == "\n" and e + 1 < len(text) and text[e + 1] == "\n":
            break
        e += 1
    return s, (min(e, len(text)) if e > pos else line_end)


def _enclosing_sentence(text: str, pos: int) -> str:
    s, e = _sentence_span(text, pos)
    return " ".join(text[s:e].strip().split())[:300]


# ===========================================================================
# Signal-class extraction  (from a compare-set body)
# ===========================================================================
@dataclass
class Atom:
    cls: str
    text: str            # verbatim signal text
    section: str
    context: str         # enclosing raw sentence (the NLI-packet context)
    norm: str = ""       # normalized key for matching (numeric magnitude, lowered text)


# --- T2 numeric ------------------------------------------------------------
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
_NUM_TOKEN_RE = re.compile(
    r"""
    (?<![\w.])
    (?:[\$€£]\s?)?
    \d{1,3}(?:,\d{3})+(?:\.\d+)?
    | (?<![\w.])(?:[\$€£]\s?)?\d+(?:\.\d+)?
    """,
    re.VERBOSE,
)
_SUFFIX_RE = re.compile(
    r"\s*(?:x|×|%|MW|GW|kW|TW|billion|million|trillion|bn|M|B|K|OOMs?|"
    r"orders? of magnitude|per year|/year|FTE|TPUs?|GPUs?)\b",
    re.IGNORECASE,
)
_MAGNITUDE = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mw": 1e6, "million": 1e6, "mn": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9, "gw": 1e9,
    "t": 1e12, "tw": 1e12, "trillion": 1e12,
}


def _is_citation_or_ref(doc: str, start: int, end: int) -> bool:
    pre = doc[max(0, start - 2):start]
    if pre.endswith("[^") or pre.endswith("["):
        if doc[end:end + 1] == "]":
            return True
    window = doc[max(0, start - 14):start].lower()
    if re.search(r"\b(figure|fig|table|tbl|page|pg|section|sec|chapter|eq|equation|v)\.?\s*$", window):
        return True
    return False


def _numeric_value(token: str) -> float | None:
    """Magnitude-normalized numeric value of a numeric atom. `2.4x` -> 2.4;
    `$40M` -> 40e6; `$1 billion` -> 1e9; `300MW` -> 300e6; `$5,000` -> 5000.
    Returns None when no number is present."""
    t = token.strip()
    mnum = re.search(r"\d[\d,]*(?:\.\d+)?", t)
    if not mnum:
        return None
    base = float(mnum.group(0).replace(",", ""))
    tail = t[mnum.end():].strip().lower()
    # magnitude word/letter immediately following the number
    mmag = re.match(r"(k|m|b|t|mw|gw|tw|bn|mn|thousand|million|billion|trillion)\b", tail)
    if mmag:
        base *= _MAGNITUDE[mmag.group(1)]
    elif "billion" in tail:
        base *= 1e9
    elif "million" in tail:
        base *= 1e6
    elif "trillion" in tail:
        base *= 1e12
    return base


def extract_numeric(body: str, section: str) -> list[Atom]:
    atoms: list[Atom] = []
    for m in _NUM_TOKEN_RE.finditer(body):
        s, e = m.start(), m.end()
        token = m.group(0)
        raw_num = re.sub(r"[\$€£,\s]", "", token)
        if _YEAR_RE.match(raw_num) and "." not in raw_num and not token.strip().startswith(("$", "€", "£")):
            if not _SUFFIX_RE.match(body[e:]):
                continue
        if _is_citation_or_ref(body, s, e):
            continue
        suff = _SUFFIX_RE.match(body[e:])
        if suff:
            e = e + suff.end()
            token = body[m.start():e]
        val = _numeric_value(token)
        atoms.append(Atom(
            cls="numeric", text=token.strip(), section=section,
            context=_enclosing_sentence(body, m.start()),
            norm=("" if val is None else f"{val:.6g}"),
        ))
    return atoms


# --- T3 table rows ---------------------------------------------------------
def _row_cells(line: str) -> list[str]:
    inner = line.strip().strip("|")
    return [c.strip() for c in inner.split("|")]


def _norm_cell(cell: str) -> str:
    """Normalize a table cell for shingle matching: lowercase, strip markdown
    emphasis + wikilink syntax, collapse whitespace."""
    c = cell.lower()
    c = re.sub(r"\[\[([^\]\|]+?)(?:\|[^\]]+)?\]\]", r"\1", c)  # wikilink -> target
    c = re.sub(r"[*_`]", "", c)
    c = re.sub(r"\s+", " ", c).strip()
    return c


def _row_shingle(line: str) -> str:
    return "|".join(_norm_cell(c) for c in _row_cells(line))


def _row_tokens(line: str) -> set[str]:
    toks = re.findall(r"[a-z0-9]+", _row_shingle(line).replace("|", " "))
    return set(toks)


def extract_table_rows(body: str, section: str) -> list[Atom]:
    atoms: list[Atom] = []
    for m in re.finditer(r"(?m)^[ \t]*\|.+\|[ \t]*\r?$", body):
        line = m.group(0)
        if re.match(r"^[ \t]*\|[\s:\-|]+\|[ \t]*$", line):  # separator row
            continue
        atoms.append(Atom(
            cls="table_row", text=line.strip(), section=section,
            context=_enclosing_sentence(body, m.start()),
            norm=_row_shingle(line),
        ))
    return atoms


# --- T4 rule / framework labels --------------------------------------------
_RULE_LABEL_RE = re.compile(
    r"\*\*([^*\n]{2,80}?)\*\*"
    r"|(?<![\w])(Rule|Test|Law|Principle|Theorem|Criterion|Step)\s+\d+\s*[:.]"
)


def extract_rule_labels(body: str, section: str) -> list[Atom]:
    atoms: list[Atom] = []
    for m in _RULE_LABEL_RE.finditer(body):
        label = (m.group(1) or m.group(0)).strip()
        if re.search(r"limitation|caveat|threat|uncertain|confidence|neglect", label, re.IGNORECASE):
            continue  # caveat-class handles these
        atoms.append(Atom(
            cls="rule_label", text=label, section=section,
            context=_enclosing_sentence(body, m.start()),
            norm=_norm_text(label),
        ))
    return atoms


# --- T5 named entities -----------------------------------------------------
_WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+?\.md)(?:#[^\]\|]+)?(?:\|[^\]]+)?\]\]")


def extract_named_entities(body: str, section: str) -> list[Atom]:
    atoms: list[Atom] = []
    for m in _WIKILINK_RE.finditer(body):
        atoms.append(Atom(
            cls="named_entity", text=m.group(0), section=section,
            context=_enclosing_sentence(body, m.start()),
            norm=m.group(1).lower(),   # the slug target -- substring presence key
        ))
    return atoms


# --- T6 caveats ------------------------------------------------------------
_CAVEAT_MARKERS = re.compile(
    r"\b(limitation|limitations|caveat|threats? to validity|needs? validation|"
    r"unvalidated|unproven|uncertain(?:ty)?|low[- ]confidence|"
    r"the authors? (?:state|note|acknowledge|flag|caution)|neglected|"
    r"may be conservative|understates?|robustness)\b",
    re.IGNORECASE,
)


def extract_caveats(body: str, section: str) -> list[Atom]:
    atoms: list[Atom] = []
    seen: set[tuple[int, int]] = set()
    for m in _CAVEAT_MARKERS.finditer(body):
        s, e = _sentence_span(body, m.start())
        if (s, e) in seen:
            continue
        seen.add((s, e))
        text = body[s:e].strip()
        if len(text) < 8:
            continue
        atoms.append(Atom(
            cls="caveat", text=text, section=section,
            context=" ".join(text.split())[:300],
            norm=_norm_text(text),
        ))
    return atoms


def _norm_text(t: str) -> str:
    """Normalize prose/label text for containment matching: drop markdown
    emphasis + wikilink brackets, lowercase, collapse whitespace."""
    c = t.lower()
    c = re.sub(r"\[\[([^\]\|]+?)(?:\|[^\]]+)?\]\]", r"\1", c)
    c = re.sub(r"[*_`>]", "", c)
    c = re.sub(r"\s+", " ", c).strip()
    return c


EXTRACTORS = {
    "numeric": extract_numeric,
    "table_row": extract_table_rows,
    "rule_label": extract_rule_labels,
    "named_entity": extract_named_entities,
    "caveat": extract_caveats,
}


def extract_atoms(doc: str, classes=MEASURED_CLASSES) -> dict[str, list[Atom]]:
    """All atoms of each class across the compare-set sections of `doc`."""
    out: dict[str, list[Atom]] = {c: [] for c in classes}
    for sec in compare_sections(doc):
        body = sec.body(doc)
        for cls in classes:
            out[cls].extend(EXTRACTORS[cls](body, sec.name))
    return out


# ===========================================================================
# Matching  (is a RAW atom present in the PAGE?)
# ===========================================================================
def _numeric_missing(raw_atoms: list[Atom], page_atoms: list[Atom]) -> list[Atom]:
    """MULTISET retention for numeric atoms. A magnitude `V` that appears N times
    in the raw is fully retained only if at least N magnitude-matching atoms
    survive on the page; if only M<N survive, the (N-M) excess raw occurrences are
    MISSING. This is the correct retention semantics for the calibration set, whose
    numeric extraction is intentionally INCLUSIVE (bare integers like `4`, `1`,
    `5`): a deleted `2.4x` is NOT "retained" just because another `2.4x` survives
    elsewhere -- set-membership would wrongly clear every common/duplicated value.

    Page values are consumed greedily (one page atom matches at most one raw atom).
    Matching is magnitude-normalized within tolerance (1%, or 5% above magnitude
    1000). Raw atoms are processed tightest-tolerance-first (small magnitudes
    before large) so a tight raw value cannot be stolen by a loose large one."""
    page_vals: list[float | None] = [_numeric_value(p.text) for p in page_atoms]
    remaining: list[float] = [v for v in page_vals if v is not None]
    missing: list[Atom] = []
    # process by ascending |value| so 1%-tolerance small atoms claim their match
    # before a 5%-tolerance large atom could absorb a nearby page value
    order = sorted(range(len(raw_atoms)),
                   key=lambda i: (abs(_numeric_value(raw_atoms[i].text) or 0.0)))
    consumed: set[int] = set()
    for i in order:
        ra = raw_atoms[i]
        rv = _numeric_value(ra.text)
        if rv is None:
            missing.append(ra)
            continue
        tol = NUM_TOL_ROUNDED if abs(rv) > ROUNDED_MAGNITUDE else NUM_TOL
        hit = -1
        for j, pv in enumerate(remaining):
            if j in consumed:
                continue
            if rv == 0:
                if pv == 0:
                    hit = j
                    break
                continue
            if abs(pv - rv) <= tol * abs(rv):
                hit = j
                break
        if hit >= 0:
            consumed.add(hit)
        else:
            missing.append(ra)
    # preserve raw document order in the returned missing list
    missing_ids = {id(m) for m in missing}
    return [ra for ra in raw_atoms if id(ra) in missing_ids]


def _table_row_present(raw_atom: Atom, page_atoms: list[Atom], page_text_norm: str) -> bool:
    rshingle = raw_atom.norm
    rtokens = set(re.findall(r"[a-z0-9]+", rshingle.replace("|", " ")))
    for p in page_atoms:
        if p.norm == rshingle:               # exact row-shingle
            return True
    if not rtokens:
        return False
    for p in page_atoms:                     # token-set fallback (>=0.72 of raw row)
        ptokens = set(re.findall(r"[a-z0-9]+", p.norm.replace("|", " ")))
        if not ptokens:
            continue
        overlap = len(rtokens & ptokens) / len(rtokens)
        if overlap >= TABLE_TOKENSET_THRESHOLD:
            return True
    return False


def _text_present(raw_atom: Atom, page_text_norm: str) -> bool:
    """Containment of a normalized rule/caveat label/sentence in the normalized
    page compare-text (case-insensitive, markdown-stripped)."""
    key = raw_atom.norm
    if not key:
        return False
    return key in page_text_norm


def _entity_present(raw_atom: Atom, page_text_norm: str) -> bool:
    return raw_atom.norm in page_text_norm   # slug target substring


# ===========================================================================
# Detector core
# ===========================================================================
@dataclass
class MissingItem:
    cls: str
    text: str
    section: str
    context: str          # raw-sentence context (the NLI-packet input)


@dataclass
class ClassResult:
    cls: str
    raw_count: int
    page_count: int
    missing_count: int
    retention: float | None        # None when skipped
    skipped: bool
    skip_reason: str = ""
    missing: list[MissingItem] = field(default_factory=list)


@dataclass
class PageReport:
    page: str
    raw: str
    classes: dict[str, ClassResult]
    flagged: bool                  # any measured class retention below a hard-flag (full drop) OR <1.0
    measured_missing: int
    measured_raw: int

    def all_missing(self) -> list[MissingItem]:
        out: list[MissingItem] = []
        for cr in self.classes.values():
            out.extend(cr.missing)
        return out


def detect(page_doc: str, raw_doc: str, page_name: str = "", raw_name: str = "",
           floors: dict[str, int] = MIN_COUNT_FLOORS) -> PageReport:
    """Compare RAW (the faithful / source text) against PAGE (the possibly-thin
    text). Reports, per measured class, the retention ratio and the raw atoms
    absent from the page (with raw-sentence context). Pure regex + set math; no
    embeddings, no LLM, no network.

    For the calibration ablation set, `raw_doc` is the ORIGINAL faithful page and
    `page_doc` is the ablated copy -- ablation deleted from the page's own
    compare-set, so the original page IS the retention reference."""
    raw_atoms = extract_atoms(raw_doc)
    page_atoms = extract_atoms(page_doc)
    page_text_norm = _norm_text(compare_text(page_doc))

    classes: dict[str, ClassResult] = {}
    for cls in MEASURED_CLASSES:
        r_atoms = raw_atoms[cls]
        p_atoms = page_atoms[cls]
        floor = floors.get(cls, 1)
        if len(r_atoms) < floor:
            classes[cls] = ClassResult(
                cls=cls, raw_count=len(r_atoms), page_count=len(p_atoms),
                missing_count=0, retention=None, skipped=True,
                skip_reason=f"raw has {len(r_atoms)} {cls} atoms < floor {floor}",
            )
            continue
        missing: list[MissingItem] = []
        if cls == "numeric":
            # multiset retention (count-aware) -- see _numeric_missing
            for ra in _numeric_missing(r_atoms, p_atoms):
                missing.append(MissingItem(cls=cls, text=ra.text, section=ra.section, context=ra.context))
        else:
            for ra in r_atoms:
                if cls == "table_row":
                    present = _table_row_present(ra, p_atoms, page_text_norm)
                elif cls == "named_entity":
                    present = _entity_present(ra, page_text_norm)
                else:  # rule_label, caveat
                    present = _text_present(ra, page_text_norm)
                if not present:
                    missing.append(MissingItem(cls=cls, text=ra.text, section=ra.section, context=ra.context))
        retention = 1.0 - (len(missing) / len(r_atoms)) if r_atoms else 1.0
        classes[cls] = ClassResult(
            cls=cls, raw_count=len(r_atoms), page_count=len(p_atoms),
            missing_count=len(missing), retention=retention, skipped=False,
            missing=missing,
        )

    measured_raw = sum(cr.raw_count for cr in classes.values() if not cr.skipped)
    measured_missing = sum(cr.missing_count for cr in classes.values() if not cr.skipped)
    # flagged if any non-skipped class lost any atom (recall-biased; final
    # thresholds are task 2.4's escalation ladder -- this is the floor signal).
    flagged = any((not cr.skipped) and cr.missing_count > 0 for cr in classes.values())
    return PageReport(page=page_name, raw=raw_name, classes=classes,
                      flagged=flagged, measured_missing=measured_missing,
                      measured_raw=measured_raw)


# ===========================================================================
# Validation against the calibration ablation set
# ===========================================================================
def _ground_truth_caught(deleted_item, report: PageReport) -> bool:
    """Did the detector report the ground-truth deleted item as missing?
    Numeric: magnitude-normalized within tolerance against any reported-missing
    numeric. Other classes: case-insensitive containment either direction (same
    semantics as the keystone's `recall_of`)."""
    cls = deleted_item.cls
    text = deleted_item.text
    cr = report.classes.get(cls)
    if cr is None or cr.skipped:
        return False
    if cls == "numeric":
        gv = _numeric_value(text)
        if gv is None:
            tl = text.lower()
            return any(tl in m.text.lower() or m.text.lower() in tl for m in cr.missing)
        tol = NUM_TOL_ROUNDED if abs(gv) > ROUNDED_MAGNITUDE else NUM_TOL
        for m in cr.missing:
            mv = _numeric_value(m.text)
            if mv is None:
                continue
            if gv == 0:
                if mv == 0:
                    return True
                continue
            if abs(mv - gv) <= tol * abs(gv):
                return True
        return False
    tl = text.lower()
    return any(tl in m.text.lower() or m.text.lower() in tl for m in cr.missing)


def run_validation(manifest_path: Path, vault_root: Path,
                   kind: str | None = None, grade: float | None = None,
                   floor: float = 0.90) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "calibration"))
    from load_manifest import Manifest  # noqa: E402

    M = Manifest.load(manifest_path)
    ablations = M.ablations(kind=kind, grade=grade)

    # SCORED denominator = GT items whose class was NOT skipped on that fixture
    # (a class skipped by the min-count guard is declared too sparse to score, so
    # scoring its GT items would be the inverse of the skip -- "don't score
    # noise", spec Edge Cases). We ALSO report a CONSERVATIVE recall that counts
    # skipped-class GT items as misses, so the cold verifier sees both framings.
    scored_total = 0          # primary: non-skipped-class GT items
    scored_hit = 0
    skipped_class_gt = 0      # GT items dropped from the scored denominator (class skipped)
    reasoning_total = 0
    reasoning_hit = 0
    per_class_total: dict[str, int] = {c: 0 for c in MEASURED_CLASSES}
    per_class_hit: dict[str, int] = {c: 0 for c in MEASURED_CLASSES}
    skipped_class_gt_by_class: dict[str, int] = {c: 0 for c in MEASURED_CLASSES}
    per_fixture = []
    skip_log: dict[str, int] = {}

    for a in ablations:
        page_path = vault_root / a.ablated_page
        src_path = vault_root / a.source_page
        if not page_path.exists() or not src_path.exists():
            per_fixture.append({"fixture": a.ablated_page, "error": "page/source missing"})
            continue
        page_doc = page_path.read_text(encoding="utf-8")
        raw_doc = src_path.read_text(encoding="utf-8")
        report = detect(page_doc, raw_doc, page_name=a.ablated_page, raw_name=a.source_page)

        for cr in report.classes.values():
            if cr.skipped:
                skip_log[cr.skip_reason] = skip_log.get(cr.skip_reason, 0) + 1

        f_total = 0
        f_hit = 0
        f_skipped = 0
        for d in a.deleted:
            if d.cls == "reasoning_chain":
                reasoning_total += 1
                # reasoning_chain has no class -> always a miss (the OD-6 bait)
                continue
            if d.cls not in MEASURED_CLASSES:
                continue
            cr = report.classes.get(d.cls)
            if cr is not None and cr.skipped:
                # class skipped by the min-count guard -> excluded from scoring
                skipped_class_gt += 1
                skipped_class_gt_by_class[d.cls] += 1
                f_skipped += 1
                continue
            scored_total += 1
            per_class_total[d.cls] += 1
            f_total += 1
            if _ground_truth_caught(d, report):
                scored_hit += 1
                per_class_hit[d.cls] += 1
                f_hit += 1
        per_fixture.append({
            "fixture": a.ablated_page, "kind": a.kind, "grade": a.grade,
            "scored_deleted": f_total, "scored_caught": f_hit,
            "skipped_class_deleted": f_skipped,
            "recall": (f_hit / f_total if f_total else None),
            "flagged": report.flagged,
        })

    recall = (scored_hit / scored_total) if scored_total else None
    # conservative: skipped-class GT items counted as misses
    conservative_total = scored_total + skipped_class_gt
    conservative_recall = (scored_hit / conservative_total) if conservative_total else None
    per_class_recall = {
        c: (per_class_hit[c] / per_class_total[c] if per_class_total[c] else None)
        for c in MEASURED_CLASSES
    }
    return {
        "manifest": str(manifest_path),
        "voyage_key_set": "VOYAGE_API_KEY" in __import__("os").environ,
        "n_fixtures": len([p for p in per_fixture if "error" not in p]),
        "measured_classes": list(MEASURED_CLASSES),
        "scored_deleted_total": scored_total,
        "scored_caught_total": scored_hit,
        "recall_measured": recall,
        "recall_floor": floor,
        "passes_floor": (recall is not None and recall >= floor),
        "conservative_recall": conservative_recall,
        "conservative_deleted_total": conservative_total,
        "conservative_passes_floor": (conservative_recall is not None and conservative_recall >= floor),
        "skipped_class_gt_excluded": skipped_class_gt,
        "skipped_class_gt_by_class": {c: n for c, n in skipped_class_gt_by_class.items() if n},
        "skipped_class_gt_note": "GT items whose class fell below its min-count floor on that fixture -- excluded from the PRIMARY recall denominator (the class was declared too sparse to score). conservative_recall counts them as misses.",
        "per_class_recall": per_class_recall,
        "per_class_counts": {c: {"caught": per_class_hit[c], "total": per_class_total[c]} for c in MEASURED_CLASSES},
        "reasoning_chain_deleted_total": reasoning_total,
        "reasoning_chain_caught_total": reasoning_hit,
        "reasoning_chain_note": "UNMEASURED class (OD-6 bait) -- excluded from the recall denominator by design; 0 caught is expected and demonstrates the unmeasured-class gap for task 2.4.",
        "skip_log": skip_log,
        "per_fixture": per_fixture,
    }


# ===========================================================================
# CLI
# ===========================================================================
def _vault_root_from(path: Path) -> Path:
    p = path.resolve()
    for anc in [p, *p.parents]:
        if (anc / "sb-os.json").exists():
            return anc
    return Path(__file__).resolve().parents[4]


def _report_to_dict(r: PageReport) -> dict:
    return {
        "page": r.page, "raw": r.raw, "flagged": r.flagged,
        "measured_raw_atoms": r.measured_raw, "measured_missing": r.measured_missing,
        "classes": {
            cls: {
                "raw_count": cr.raw_count, "page_count": cr.page_count,
                "missing_count": cr.missing_count,
                "retention": cr.retention, "skipped": cr.skipped,
                "skip_reason": cr.skip_reason,
                "missing": [asdict(m) for m in cr.missing],
            } for cls, cr in r.classes.items()
        },
    }


def cmd_report(args) -> int:
    page = Path(args.page)
    raw = Path(args.raw)
    if not page.exists():
        print(f"page not found: {page}", file=sys.stderr)
        return 2
    if not raw.exists():
        print(f"raw not found: {raw}", file=sys.stderr)
        return 2
    report = detect(page.read_text(encoding="utf-8"), raw.read_text(encoding="utf-8"),
                    page_name=str(page), raw_name=str(raw))
    if args.json:
        print(json.dumps(_report_to_dict(report), indent=2, ensure_ascii=False))
        return 0
    print(f"page: {page.name}")
    print(f"raw:  {raw.name}")
    print(f"flagged: {report.flagged}  (measured missing {report.measured_missing}/{report.measured_raw})")
    for cls, cr in report.classes.items():
        if cr.skipped:
            print(f"  {cls:13s} SKIPPED ({cr.skip_reason})")
            continue
        print(f"  {cls:13s} retention={cr.retention:.3f}  raw={cr.raw_count} page={cr.page_count} missing={cr.missing_count}")
        for m in cr.missing[:5]:
            print(f"       MISSING [{m.section}] {m.text[:70]!r}")
            print(f"            ctx: {m.context[:90]}")
    return 0


def cmd_validate(args) -> int:
    manifest = Path(args.manifest) if args.manifest else (
        Path(__file__).resolve().parent / "calibration" / "data" / "ground-truth-manifest.json")
    if not manifest.exists():
        print(f"manifest not found: {manifest}", file=sys.stderr)
        return 2
    vault_root = Path(args.vault_root).resolve() if args.vault_root else _vault_root_from(manifest)
    grade = float(args.grade) if args.grade else None
    result = run_validation(manifest, vault_root, kind=args.kind, grade=grade, floor=args.floor)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    # human summary always to stdout
    print(f"VOYAGE_API_KEY set: {result['voyage_key_set']}")
    print(f"fixtures: {result['n_fixtures']}  (kind={args.kind or 'all'}, grade={args.grade or 'all'})")
    print(f"measured classes: {', '.join(result['measured_classes'])}")
    print(f"RECALL (primary, scored classes) = {result['recall_measured']:.4f}"
          f"  [{result['scored_caught_total']}/{result['scored_deleted_total']}]"
          f"  floor={result['recall_floor']}  PASS={result['passes_floor']}")
    print(f"RECALL (conservative, skipped-class GT counted as misses) = "
          f"{result['conservative_recall']:.4f}  [{result['scored_caught_total']}/{result['conservative_deleted_total']}]"
          f"  PASS={result['conservative_passes_floor']}")
    print("per-class recall:")
    for c, r in result["per_class_recall"].items():
        cnt = result["per_class_counts"][c]
        rv = "n/a" if r is None else f"{r:.4f}"
        print(f"  {c:13s} {rv:>7s}  [{cnt['caught']}/{cnt['total']}]")
    print(f"reasoning_chain (UNMEASURED/OD-6 bait): {result['reasoning_chain_caught_total']}/{result['reasoning_chain_deleted_total']} caught (0 expected)")
    if result["skipped_class_gt_excluded"]:
        print(f"skipped-class GT excluded from primary denominator: {result['skipped_class_gt_excluded']} "
              f"({result['skipped_class_gt_by_class']})")
    if result["skip_log"]:
        print("min-count guard skips:")
        for reason, n in sorted(result["skip_log"].items()):
            print(f"  x{n}: {reason}")
    if args.json_out:
        print(f"(full per-fixture JSON -> {args.json_out})")
    return 0 if result["passes_floor"] else 4


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("report", help="run on one (page, raw) pair -> packet")
    r.add_argument("--page", required=True)
    r.add_argument("--raw", required=True)
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_report)

    v = sub.add_parser("validate", help="recall over the calibration ablation set (key-independent)")
    v.add_argument("--manifest", default=None)
    v.add_argument("--vault-root", default=None)
    v.add_argument("--kind", default=None, choices=["paper", "article", "podcast"])
    v.add_argument("--grade", default=None)
    v.add_argument("--floor", type=float, default=0.90)
    v.add_argument("--json-out", default=None)
    v.set_defaults(func=cmd_validate)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
