"""investment_financials_extract.py — SOLE writer of entity `## Financials`
table sections (§10 capture→Financials extraction integration).

Models LOCATE; this tool READS, VALIDATES, WRITES. A model never transcribes a
number into the table — it points at one (an anchor in a captured raw file) and
this tool re-reads and re-parses it. Fully OFFLINE — no network access, ever.

Three lanes:
    lane 1  us-gaap -> vocab map over a captured EDGAR companyfacts JSON   -> method: xbrl
    lane 2  verify a target's anchor in the cited raw, re-parse verbatim   -> method: structured
    lane 3  unverifiable target (no anchor) — exception, not norm          -> method: llm

CLI:
    python investment_financials_extract.py
        --entity <wiki entity page path>           (required)
        [--xbrl <captured companyfacts json path>] (lane 1)
        [--targets <targets json path>]            (lanes 2/3)
        [--cik N]                                  (overrides entity frontmatter cik:)
        [--since YYYY-MM-DD]                        (lane-1 open extraction window)
        [--vault-root PATH]
        [--vocab PATH]                             (override metric-vocab.md location)
        [--dry-run]

At least one of --xbrl / --targets is required.

Targets JSON schema (lanes 2/3, path-transported — never inline in a prompt):
    {"entity": "<slug>", "source": "<raw filename>.md",
     "targets": [
        {"metric", "period_type", "period_end", "value_as_printed",
         "unit_as_printed", "anchor", "unverifiable": bool, "reason": ""}
     ]}
A per-target `source` override is allowed. `source` MUST resolve to an existing
file under {wiki_root}/raw/**/<filename> or the row is rejected.

Vocabulary hard-gate: metric/unit/period_type/method are validated against
metric-vocab.md EXACTLY. A valid metric = a base identifier from the entity
kind's list, OR base + exactly ONE suffix from {_growth_yoy, _guidance,
_non_gaap} (no stacking). Off-vocab rows are REJECTED, never written. A target
whose metric starts with `PROPOSAL:` is never written and is surfaced under
vocab_proposals.

Upsert key = (metric, period_type, period_end, source-filename):
    same key + same (value, unit) + same method      -> no-op (skipped)
    same key + same (value, unit) + different method  -> method precedence
        xbrl > structured > llm > manual: stronger incoming UPDATES in place
        (upgraded); weaker/equal -> no-op
    same key + different value or unit                -> CONFLICT (surfaced, not written)
    new key                                           -> INSERT
Different sources for the same (metric, period_type, period_end) COEXIST.

Writes are surgical — ONLY the `## Financials` block (header + table). The
section is created (when absent) AFTER the last content section and BEFORE
`## Related` (or before `## Sources` when no Related; appended at end when
neither). Frontmatter, other sections, and footnotes are never touched.

Output: metadata JSON only to stdout — never page or raw content.
Exit 0 = success (even with rejects/conflicts — surfaced state).
Exit 1 = usage/validation ERROR (missing entity, bad kind, cik mismatch,
unreadable inputs).
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Vault-root / wiki-root resolution (mirrors sb-wiki-capture-source.py)
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
# Constants
# ---------------------------------------------------------------------------

CANONICAL_COLUMNS = ["metric", "period_type", "period_end", "value", "unit", "source", "method"]
_PERIOD_TYPE_ORDER = ["annual", "quarterly", "monthly", "ttm", "point"]
_METHOD_PRECEDENCE = {"manual": 0, "llm": 1, "structured": 2, "xbrl": 3}
_SUFFIXES = ("_growth_yoy", "_guidance", "_non_gaap")

# Kinds that carry a ## Financials section (per page-types.ext.md).
_FINANCIALS_KINDS = {"company", "asset", "country", "sector"}

# us-gaap -> vocab map ships beside this script.
_MAP_PATH = Path(__file__).resolve().parent / "us_gaap_vocab_map.json"
# metric-vocab.md resolves relative to this script (overridable via --vocab).
_DEFAULT_VOCAB_PATH = Path(__file__).resolve().parent.parent.parent / "wiki-ext" / "metric-vocab.md"


# ---------------------------------------------------------------------------
# Vocabulary parsing (the hard gate)
# ---------------------------------------------------------------------------

_KIND_HEADINGS = {
    "company": "company / equity",
    "asset": "asset",          # "### asset — fixed income"
    "country": "country / macro",
    "sector": "sector",
}

_CODESPAN_RE = re.compile(r"`([^`]+)`")
_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _codespan_idents(block: str) -> set[str]:
    """All snake_case identifiers in every comma-bearing code-span in a block."""
    out: set[str] = set()
    for span in _CODESPAN_RE.findall(block):
        parts = [p.strip() for p in span.split(",")]
        for p in parts:
            if _IDENT_RE.match(p):
                out.add(p)
    return out


def _section_block(text: str, heading_substr: str, levels=("###", "##")) -> str:
    """Return the text under the first heading whose title contains heading_substr,
    up to the next heading of same-or-higher level."""
    lines = text.splitlines()
    start = None
    start_level = None
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        for lvl in ("####", "###", "##", "#"):
            if stripped.startswith(lvl + " "):
                title = stripped[len(lvl):].strip()
                if start is None and heading_substr.lower() in title.lower() and lvl in levels:
                    start = i
                    start_level = len(lvl)
                elif start is not None and i > start and len(lvl) <= start_level:
                    return "\n".join(lines[start + 1:i])
                break
    if start is not None:
        return "\n".join(lines[start + 1:])
    return ""


class Vocab:
    """Parsed metric-vocab.md gate."""

    def __init__(self, *, bases_by_kind: dict[str, set[str]], units: set[str],
                 period_types: set[str], methods: set[str], suffixes: set[str]):
        self.bases_by_kind = bases_by_kind
        self.units = units
        self.period_types = period_types
        self.methods = methods
        self.suffixes = suffixes

    def metric_valid(self, metric: str, kind: str) -> bool:
        bases = self.bases_by_kind.get(kind, set())
        if metric in bases:
            return True
        for suf in self.suffixes:
            if metric.endswith(suf):
                base = metric[: -len(suf)]
                # no stacking: the base itself must not carry another suffix
                if base in bases and not any(base.endswith(s) for s in self.suffixes):
                    return True
        return False


def parse_vocab(vocab_path: Path) -> Vocab:
    text = vocab_path.read_text(encoding="utf-8")

    bases_by_kind: dict[str, set[str]] = {}
    for kind, heading in _KIND_HEADINGS.items():
        block = _section_block(text, heading, levels=("###",))
        bases_by_kind[kind] = _codespan_idents(block)

    allowed = _section_block(text, "Allowed Sets", levels=("##",))

    def _named_set(label: str) -> set[str]:
        # find "**label:** `...`" within the Allowed Sets block
        m = re.search(r"\*\*" + re.escape(label) + r":\*\*\s*`([^`]+)`", allowed)
        if not m:
            return set()
        return {p.strip() for p in m.group(1).split(",") if p.strip()}

    units = _named_set("units")
    period_types = _named_set("period_type")
    methods = _named_set("method")

    suffix_block = _section_block(text, "Suffix Families", levels=("##",))
    suffixes = {s.strip() for s in _codespan_idents_raw(suffix_block)}
    if not suffixes:
        suffixes = set(_SUFFIXES)

    return Vocab(bases_by_kind=bases_by_kind, units=units,
                 period_types=period_types, methods=methods, suffixes=suffixes)


def _codespan_idents_raw(block: str) -> set[str]:
    """Identifiers (allowing leading underscore — suffix families) in code-spans."""
    out: set[str] = set()
    for span in _CODESPAN_RE.findall(block):
        for p in span.split(","):
            p = p.strip()
            if re.match(r"^_[a-z][a-z0-9_]*$", p):
                out.add(p)
    return out


# ---------------------------------------------------------------------------
# Raw normalization + anchor verification + number re-parse (lane 2)
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """HTML-strip + entity-unescape + whitespace-collapse + casefold."""
    notags = _TAG_RE.sub(" ", text)
    unesc = html.unescape(notags)
    collapsed = _WS_RE.sub(" ", unesc).strip()
    return collapsed.casefold()


# A numeric token: optional ($ R$ -), digits with thousands separators, optional
# decimals, optional trailing % and scale word.
_NUMBER_RE = re.compile(
    r"\(?\s*[-+]?\s*(?:US)?\$?\s*R?\$?\s*\d[\d,]*(?:\.\d+)?\s*\)?",
    re.IGNORECASE,
)


def _parse_number_token(token: str) -> Optional[float]:
    """Parse the numeric magnitude+sign from a matched token (no unit scaling)."""
    t = token.strip()
    negative = t.startswith("(") and t.endswith(")")
    t = t.strip("()").strip()
    t = re.sub(r"(?i)us\$", "$", t)
    t = t.replace("$", "").replace("R", "").replace("r", "").replace(" ", "")
    if t.startswith("-"):
        negative = True
        t = t[1:]
    if t.startswith("+"):
        t = t[1:]
    t = t.replace(",", "")
    if not t:
        return None
    try:
        val = float(t)
    except ValueError:
        return None
    return -val if negative else val


def _find_number_candidates(segment: str) -> list[tuple[float, int, int]]:
    """All numeric candidates in a segment: (value, start, end)."""
    out = []
    for m in _NUMBER_RE.finditer(segment):
        v = _parse_number_token(m.group(0))
        if v is not None:
            out.append((v, m.start(), m.end()))
    return out


# Scale words → multiplier on a millions base (USD_mn / BRL_mn). Bare words are
# valid printed units when a currency is detectable (see _resolve_unit_and_scale).
# Word-boundary matched so "b"/"m"/"k" never trip on a substring of another word.
_SCALE_WORDS = (
    (r"billions?|bn|b", 1000.0),
    (r"millions?|mn|m", 1.0),
    (r"thousands?|k", 0.001),
)
_SCALE_RES = [(re.compile(r"(?<![a-z])(?:" + pat + r")(?![a-z0-9])", re.IGNORECASE), mult)
              for pat, mult in _SCALE_WORDS]


def _scale_from_text(text: str) -> Optional[float]:
    """First scale-word multiplier found in `text` (already lowercase or not),
    in billion→million→thousand precedence; None if no scale word present."""
    for rgx, mult in _SCALE_RES:
        if rgx.search(text):
            return mult
    return None


def _detect_currency(text: str) -> Optional[str]:
    """Return 'BRL' / 'USD' for a currency symbol or code in `text`, else None.
    R$ / BRL is checked BEFORE $ / USD so 'R$' never reads as bare '$'."""
    low = text.lower()
    if "r$" in low or re.search(r"(?<![a-z])brl(?![a-z])", low):
        return "BRL"
    if "$" in low or re.search(r"(?<![a-z])us\$|(?<![a-z])usd(?![a-z])", low):
        return "USD"
    return None


# Printed-unit -> (vocab_unit, scale-resolver). Deterministic; unmapped -> None.
def _resolve_unit_and_scale(unit_as_printed: str, context_norm: str, raw_value: float,
                            value_as_printed: str = "") -> Optional[tuple[float, str]]:
    """Return (scaled_value, vocab_unit) or None if the printed unit is unmapped.

    Currency: explicit currency in unit_as_printed wins; else currency detected
    in value_as_printed; none found ⇒ reject (None).
    Scale: a scale word in unit_as_printed wins; else a scale word in context_norm
    (the normalized anchor for lane 2, the normalized value for lane 3); else
    default ×1 (filings tabulate "in millions"). Scale is resolved ONCE — a scale
    word in both the unit and the value does not double-apply.
    """
    u = unit_as_printed.strip().lower()

    # percent family
    if u in ("%", "percent", "pct", "pct_yoy", "pct_mom"):
        return raw_value, "pct"

    # multiple (x)
    if u in ("x", "×"):
        return raw_value, "x"

    # basis points
    if u in ("bps",):
        return raw_value, "bps"

    # tonnes (commodity mass) — unscaled
    if u in ("t", "tonne", "tonnes"):
        return raw_value, "tonnes"

    # per-ounce price ("USD/oz") — plain currency unit, unscaled
    if "/oz" in u:
        currency = _detect_currency(u) or _detect_currency(value_as_printed)
        if currency is None:
            return None
        return raw_value, currency

    # already-vocab units pass through unscaled
    if u in ("usd_mn",):
        return raw_value, "USD_mn"
    if u in ("brl_mn",):
        return raw_value, "BRL_mn"

    # currency: explicit in the unit wins, else detect in value_as_printed.
    currency = _detect_currency(u) or _detect_currency(value_as_printed)
    if currency is None:
        return None

    # scale: a scale word in the unit wins; else in the context (anchor/value);
    # else default million (×1). Resolved exactly once.
    mult = _scale_from_text(u)
    if mult is None:
        mult = _scale_from_text(context_norm)
    if mult is None:
        mult = 1.0
    scaled = raw_value * mult
    return (scaled, "BRL_mn") if currency == "BRL" else (scaled, "USD_mn")


def _round_half_up(value: float, places: int) -> float:
    """Round half AWAY from zero (financial convention) to `places` decimals.
    Python's built-in round() uses banker's rounding (168.5 -> 168); filings and
    the existing hand tables round half-up (168.5 -> 169)."""
    q = Decimal(1).scaleb(-places)  # 10**-places
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def _round_value(value: float, vocab_unit: str, value_as_printed: str) -> str:
    """Match existing tables: integer-millions style; pct keeps 1 decimal when
    printed with one. Round to int when |value| >= 10 else 1 decimal.
    Half-values round up (financial convention), not banker's."""
    if vocab_unit == "pct":
        # keep one decimal if printed with a decimal, else int
        if "." in (value_as_printed or ""):
            return _fmt(_round_half_up(value, 1))
        return _fmt(_round_half_up(value, 0))
    if abs(value) >= 10:
        return _fmt(_round_half_up(value, 0))
    return _fmt(_round_half_up(value, 1))


def _fmt(num: float) -> str:
    """Format a number without a trailing .0 for integers."""
    if isinstance(num, float) and num.is_integer():
        return str(int(num))
    return str(num)


def verify_and_reparse(target: dict, raw_text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Lane-2 verification.

    Returns (value_str, vocab_unit, error). On success error is None. On failure
    value_str/vocab_unit are None and error names the reason.
    """
    anchor = target.get("anchor", "") or ""
    anchor_norm = normalize(anchor)
    if not anchor_norm:
        return None, None, "anchor missing"

    raw_norm = normalize(raw_text)
    idx = raw_norm.find(anchor_norm)
    if idx < 0:
        return None, None, "anchor not found in cited raw"

    matched = raw_norm[idx: idx + len(anchor_norm)]
    candidates = _find_number_candidates(matched)

    if not candidates:
        return None, None, "anchor has no number"

    chosen: Optional[float] = None
    if len(candidates) == 1:
        chosen = candidates[0][0]
    else:
        # disambiguate via value_as_printed (normalized numeric equality)
        vap = target.get("value_as_printed", "") or ""
        vap_num = None
        vap_cands = _find_number_candidates(normalize(vap))
        if vap_cands:
            vap_num = vap_cands[0][0]
        if vap_num is not None:
            matches = [c for c in candidates if abs(c[0] - vap_num) < 1e-9]
            if len(matches) == 1:
                chosen = matches[0][0]
        if chosen is None:
            return None, None, "anchor ambiguous (multiple numbers)"

    resolved = _resolve_unit_and_scale(target.get("unit_as_printed", ""), anchor_norm, chosen,
                                       target.get("value_as_printed", ""))
    if resolved is None:
        return None, None, f"unmapped printed unit: {target.get('unit_as_printed', '')!r}"
    scaled, vocab_unit = resolved
    value_str = _round_value(scaled, vocab_unit, target.get("value_as_printed", ""))
    return value_str, vocab_unit, None


# ---------------------------------------------------------------------------
# Entity page parsing + ## Financials table
# ---------------------------------------------------------------------------

def _split_frontmatter(text: str) -> tuple[dict, str, str]:
    """Return (frontmatter_dict, frontmatter_block_with_delims, body)."""
    if not text.startswith("---\n"):
        return {}, "", text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, "", text
    fm_block = text[: end + len("\n---\n")]
    body = text[end + len("\n---\n"):]
    fm: dict = {}
    for ln in text[4:end].splitlines():
        m = re.match(r"^([a-zA-Z0-9_-]+):\s*(.*)$", ln)
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return fm, fm_block, body


class Row:
    __slots__ = ("metric", "period_type", "period_end", "value", "unit", "source", "method")

    def __init__(self, metric, period_type, period_end, value, unit, source, method):
        self.metric = metric
        self.period_type = period_type
        self.period_end = period_end
        self.value = value
        self.unit = unit
        self.source = source       # the [[wikilink]] cell, verbatim
        self.method = method

    def key(self) -> tuple:
        return (self.metric, self.period_type, self.period_end, _source_filename(self.source))

    def cells(self) -> list[str]:
        return [self.metric, self.period_type, self.period_end, self.value,
                self.unit, self.source, self.method]


def _source_filename(source_cell: str) -> str:
    """Extract the filename from a [[wikilink]] or bare string source cell."""
    s = source_cell.strip()
    m = re.match(r"\[\[([^\]|#]+)", s)
    if m:
        return m.group(1).strip()
    return s


def _source_wikilink(filename: str) -> str:
    return f"[[{filename}]]"


def parse_financials_table(body: str) -> tuple[list[Row], Optional[int], Optional[int]]:
    """Return (rows, section_start_line, section_end_line) for the ## Financials
    block. start/end are line indices into body.splitlines() bounding the section
    (header line through the line before the next ## or EOF). None if absent."""
    lines = body.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == "## Financials":
            start = i
            break
    if start is None:
        return [], None, None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    rows: list[Row] = []
    for k in range(start + 1, end):
        ln = lines[k]
        if not ln.strip().startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if cells[:1] == ["metric"]:
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue  # separator
        if len(cells) == 7:
            rows.append(Row(*cells))
    return rows, start, end


def _render_table(rows: list[Row]) -> str:
    out = ["| " + " | ".join(CANONICAL_COLUMNS) + " |",
           "|" + "|".join(["--------"] * 7) + "|"]
    for r in rows:
        out.append("| " + " | ".join(r.cells()) + " |")
    return "\n".join(out)


def _canonical_sort(rows: list[Row]) -> list[Row]:
    def ptidx(pt: str) -> int:
        return _PERIOD_TYPE_ORDER.index(pt) if pt in _PERIOD_TYPE_ORDER else len(_PERIOD_TYPE_ORDER)
    return sorted(rows, key=lambda r: (r.metric, r.period_end, ptidx(r.period_type),
                                       _source_filename(r.source)))


# ---------------------------------------------------------------------------
# Section write (surgical)
# ---------------------------------------------------------------------------

def _write_financials(body: str, rows: list[Row]) -> str:
    """Return a new body with the ## Financials block replaced/created.
    rows must already be canonically sorted."""
    lines = body.splitlines(keepends=False)
    table = _render_table(rows)
    block = "## Financials\n\n" + table + "\n"

    existing_rows, start, end = parse_financials_table(body)
    if start is not None:
        new_lines = lines[:start] + block.splitlines() + [""] + lines[end:]
        result = "\n".join(new_lines)
        # collapse any accidental triple blank from the join
        result = re.sub(r"\n{3,}", "\n\n", result)
        if body.endswith("\n") and not result.endswith("\n"):
            result += "\n"
        return result

    # Section absent — insert before ## Related, else before ## Sources, else append.
    insert_at = None
    for i, ln in enumerate(lines):
        if ln.strip() == "## Related":
            insert_at = i
            break
    if insert_at is None:
        for i, ln in enumerate(lines):
            if ln.strip() == "## Sources":
                insert_at = i
                break

    if insert_at is not None:
        head = lines[:insert_at]
        # ensure exactly one blank line before the new section
        while head and head[-1].strip() == "":
            head.pop()
        new_lines = head + ["", block.rstrip("\n"), ""] + lines[insert_at:]
    else:
        body_stripped = body.rstrip("\n")
        new_lines = body_stripped.splitlines() + ["", block.rstrip("\n"), ""]

    result = "\n".join(new_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    if not result.endswith("\n"):
        result += "\n"
    return result


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

def _upsert(existing: list[Row], incoming: Row, counters: dict, conflicts: list, lane_count_key: str):
    """Apply one incoming row against the existing list. Mutates existing/counters/conflicts.
    Sets counters['changed'] = True on any insert or in-place method upgrade."""
    for r in existing:
        if r.key() == incoming.key():
            same_value_unit = (r.value == incoming.value and r.unit == incoming.unit)
            if same_value_unit:
                if r.method == incoming.method:
                    counters["skipped"] += 1
                    return
                if _METHOD_PRECEDENCE.get(incoming.method, -1) > _METHOD_PRECEDENCE.get(r.method, -1):
                    r.method = incoming.method
                    counters["upgraded"] += 1
                    counters["changed"] = True
                    return
                counters["skipped"] += 1
                return
            # same key, different value/unit -> conflict, not written
            conflicts.append({
                "metric": incoming.metric,
                "period_type": incoming.period_type,
                "period_end": incoming.period_end,
                "source": _source_filename(incoming.source),
                "existing_value": r.value,
                "incoming_value": incoming.value,
            })
            return
    # new key -> insert
    existing.append(incoming)
    counters["written"][lane_count_key] += 1
    counters["changed"] = True


# ---------------------------------------------------------------------------
# Lane 1 — XBRL companyfacts
# ---------------------------------------------------------------------------

def _classify_duration(start: str, end: str) -> Optional[str]:
    try:
        d0 = datetime.fromisoformat(start).date()
        d1 = datetime.fromisoformat(end).date()
    except ValueError:
        return None
    days = (d1 - d0).days
    if 80 <= days <= 100:
        return "quarterly"
    if 350 <= days <= 380:
        return "annual"
    return None  # YTD 9-mo etc. -> skip


def _lane1_rows(companyfacts: dict, concept_map: dict, source_filename: str,
                since: Optional[str]) -> list[Row]:
    facts = companyfacts.get("facts", {}).get("us-gaap", {})
    # collect mapped duration facts; dedup by (metric, period_type, period_end)
    # keeping the latest `filed`.
    best: dict[tuple, tuple] = {}  # key -> (filed, value_usd, period_end, period_type, metric)
    for concept, payload in facts.items():
        metric = concept_map.get(concept)
        if not metric:
            continue
        usd_list = payload.get("units", {}).get("USD", [])
        for fact in usd_list:
            start = fact.get("start")
            end = fact.get("end")
            if not start or not end:
                continue  # duration facts only
            ptype = _classify_duration(start, end)
            if ptype is None:
                continue
            if since is not None and end < since:
                continue
            key = (metric, ptype, end)
            filed = fact.get("filed", "")
            if key not in best or filed > best[key][0]:
                best[key] = (filed, fact.get("val"), end, ptype, metric)

    rows: list[Row] = []
    for (metric, ptype, end), (_filed, val, period_end, period_type, m) in best.items():
        if val is None:
            continue
        value_mn = val / 1e6
        value_str = _round_value(value_mn, "USD_mn", str(val))
        rows.append(Row(metric, period_type, period_end, value_str, "USD_mn",
                        _source_wikilink(source_filename), "xbrl"))
    return rows


# ---------------------------------------------------------------------------
# Core extract
# ---------------------------------------------------------------------------

class ExtractError(Exception):
    pass


def _resolve_raw(wiki: Path, filename: str) -> Optional[Path]:
    """Find <filename> anywhere under {wiki_root}/raw/. Return path or None."""
    raw_root = wiki / "raw"
    if not raw_root.exists():
        return None
    direct = None
    for p in raw_root.rglob(filename):
        if p.is_file():
            direct = p
            break
    return direct


def extract(*, entity_path: Path, xbrl_path: Optional[Path], targets_path: Optional[Path],
            vault_root: Path, vocab_path: Optional[Path] = None, cik: Optional[str] = None,
            since: Optional[str] = None, dry_run: bool = False,
            map_path: Optional[Path] = None) -> dict:
    """Extract financials into the entity's ## Financials table. Returns the
    metadata report dict. Raises ExtractError on a validation ERROR."""
    wiki = _wiki_root(vault_root)
    vocab_path = vocab_path or _DEFAULT_VOCAB_PATH
    map_path = map_path or _MAP_PATH

    # --- entity validation ---
    if not entity_path.is_file():
        raise ExtractError(f"entity page not found: {entity_path}")
    page_text = entity_path.read_text(encoding="utf-8")
    fm, _fm_block, body = _split_frontmatter(page_text)
    if fm.get("type") != "entity":
        raise ExtractError(f"not an entity page (type={fm.get('type')!r}): {entity_path}")
    kind = fm.get("kind", "")
    if kind not in _FINANCIALS_KINDS:
        raise ExtractError(
            f"entity kind {kind!r} does not carry ## Financials "
            f"(allowed: {sorted(_FINANCIALS_KINDS)})"
        )

    entity_cik = cik if cik is not None else fm.get("cik")

    # --- vocab gate ---
    if not vocab_path.is_file():
        raise ExtractError(f"metric-vocab.md not found: {vocab_path}")
    vocab = parse_vocab(vocab_path)
    for s in ("metric", "period_type", "method"):
        pass  # presence asserted implicitly by use below

    report = {
        "entity": entity_path.stem,
        "kind": kind,
        "dry_run": dry_run,
        "written": {"xbrl": 0, "structured": 0, "llm": 0},
        "upgraded": 0,
        "skipped": 0,
        "rejected": [],
        "conflicts": [],
        "vocab_proposals": [],
        "lane1_mode": None,
        "changed": False,   # internal — stripped before return; gates the write
    }

    existing_rows, _start, _end = parse_financials_table(body)

    # --- lane 1: XBRL ---
    if xbrl_path is not None:
        if not xbrl_path.is_file():
            raise ExtractError(f"companyfacts JSON not found: {xbrl_path}")
        try:
            companyfacts = json.loads(xbrl_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ExtractError(f"unreadable companyfacts JSON: {exc}")
        cf_cik = companyfacts.get("cik")
        if entity_cik and cf_cik is not None:
            if str(int(str(entity_cik))) != str(int(cf_cik)):
                raise ExtractError(
                    f"CIK mismatch: entity cik={entity_cik}, companyfacts cik={cf_cik}"
                )
        concept_map = {k: v for k, v in json.loads(map_path.read_text(encoding="utf-8")).items()
                       if not k.startswith("_")}
        cf_filename = xbrl_path.name
        report["lane1_mode"] = f"since:{since}" if since else "corroborate-only"

        # existing keys (metric, period_type, period_end) across ANY source — the
        # corroboration set.
        existing_mpp = {(r.metric, r.period_type, r.period_end) for r in existing_rows}

        for row in _lane1_rows(companyfacts, concept_map, cf_filename, since):
            if since is None:
                # corroborate-only: skip facts whose (metric, ptype, period_end)
                # is not already present.
                if (row.metric, row.period_type, row.period_end) not in existing_mpp:
                    report["skipped"] += 1
                    continue
            # vocab gate (xbrl rows are mapped to vocab, but assert anyway)
            if not vocab.metric_valid(row.metric, kind):
                report["rejected"].append({"metric": row.metric, "period_end": row.period_end,
                                           "reason": "off-vocab metric"})
                continue
            _upsert(existing_rows, row, report, report["conflicts"], "xbrl")

    # --- lanes 2/3: targets ---
    if targets_path is not None:
        if not targets_path.is_file():
            raise ExtractError(f"targets JSON not found: {targets_path}")
        try:
            tspec = json.loads(targets_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ExtractError(f"unreadable targets JSON: {exc}")
        default_source = tspec.get("source", "")
        raw_cache: dict[str, Optional[str]] = {}

        for t in tspec.get("targets", []):
            metric = (t.get("metric") or "").strip()
            period_type = (t.get("period_type") or "").strip()
            period_end = (t.get("period_end") or "").strip()

            # PROPOSAL rows: never written, surfaced.
            if metric.startswith("PROPOSAL:"):
                report["vocab_proposals"].append(metric[len("PROPOSAL:"):].strip())
                continue

            # vocab gate: metric
            if not vocab.metric_valid(metric, kind):
                report["rejected"].append({"metric": metric, "period_end": period_end,
                                           "reason": "off-vocab metric"})
                continue
            # vocab gate: period_type
            if period_type not in vocab.period_types:
                report["rejected"].append({"metric": metric, "period_end": period_end,
                                           "reason": f"off-vocab period_type: {period_type!r}"})
                continue
            # ISO date
            try:
                datetime.fromisoformat(period_end)
            except ValueError:
                report["rejected"].append({"metric": metric, "period_end": period_end,
                                           "reason": "period_end not an ISO date"})
                continue

            # source resolution
            source_name = (t.get("source") or default_source or "").strip()
            if not source_name:
                report["rejected"].append({"metric": metric, "period_end": period_end,
                                           "reason": "no source specified"})
                continue
            if source_name not in raw_cache:
                rp = _resolve_raw(wiki, source_name)
                raw_cache[source_name] = rp.read_text(encoding="utf-8") if rp else None
            raw_text = raw_cache[source_name]
            if raw_text is None:
                report["rejected"].append({"metric": metric, "period_end": period_end,
                                           "reason": f"source not found under raw/: {source_name}"})
                continue

            unverifiable = bool(t.get("unverifiable", False))
            if unverifiable or not (t.get("anchor") or "").strip():
                # lane 3 — llm: model-supplied value, no tool verification.
                value_str, unit_str, err = _lane3_value(t, vocab)
                if err:
                    report["rejected"].append({"metric": metric, "period_end": period_end,
                                               "reason": err})
                    continue
                method = "llm"
                lane_key = "llm"
            else:
                # lane 2 — structured: verify anchor, re-parse.
                value_str, unit_str, err = verify_and_reparse(t, raw_text)
                if err:
                    report["rejected"].append({"metric": metric, "period_end": period_end,
                                               "reason": err})
                    continue
                method = "structured"
                lane_key = "structured"

            # vocab gate: unit (resolved)
            if unit_str not in vocab.units:
                report["rejected"].append({"metric": metric, "period_end": period_end,
                                           "reason": f"off-vocab unit: {unit_str!r}"})
                continue
            # vocab gate: method
            if method not in vocab.methods:
                report["rejected"].append({"metric": metric, "period_end": period_end,
                                           "reason": f"off-vocab method: {method!r}"})
                continue

            row = Row(metric, period_type, period_end, value_str, unit_str,
                      _source_wikilink(source_name), method)
            _upsert(existing_rows, row, report, report["conflicts"], lane_key)

    # --- write (surgical) ---
    # Only re-render the table when a row was actually inserted or upgraded.
    # A run that only rejects / conflicts / no-ops leaves the page byte-identical
    # (the contract's "after any change: rewrite" — no change ⇒ no rewrite).
    if report["changed"]:
        new_rows = _canonical_sort(existing_rows)
        new_body = _write_financials(body, new_rows)
        new_page = _fm_block + new_body if _fm_block else new_body
        if not dry_run and new_page != page_text:
            entity_path.write_text(new_page, encoding="utf-8")

    report.pop("changed", None)
    return report


def _lane3_value(t: dict, vocab: Vocab) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Lane-3 (llm) value: model-supplied value_as_printed + unit_as_printed.
    Parsed/scaled the same way as lane 2 but WITHOUT anchor verification.
    The unit_as_printed must map (or already be vocab) — bare vocab unit allowed."""
    vap = t.get("value_as_printed", "") or ""
    cands = _find_number_candidates(normalize(vap))
    if not cands:
        return None, None, "llm row: no parseable value"
    raw_value = cands[0][0]
    # use value_as_printed text as the scale-context (it may carry billion/million)
    resolved = _resolve_unit_and_scale(t.get("unit_as_printed", ""), normalize(vap), raw_value, vap)
    if resolved is None:
        return None, None, f"unmapped printed unit: {t.get('unit_as_printed', '')!r}"
    scaled, vocab_unit = resolved
    return _round_value(scaled, vocab_unit, vap), vocab_unit, None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Write entity ## Financials rows from a captured XBRL companyfacts "
                    "JSON (lane 1) and/or agent-pointed targets (lanes 2/3). OFFLINE."
    )
    p.add_argument("--entity", required=True, help="Path to the wiki entity page")
    p.add_argument("--xbrl", default=None, help="Path to a captured companyfacts JSON (lane 1)")
    p.add_argument("--targets", default=None, help="Path to a targets JSON (lanes 2/3)")
    p.add_argument("--cik", default=None, help="CIK override (else read from entity frontmatter)")
    p.add_argument("--since", default=None, help="Lane-1 open-extraction window start (YYYY-MM-DD)")
    p.add_argument("--vault-root", default=None, help="Path to vault root (auto-detected if omitted)")
    p.add_argument("--vocab", default=None, help="Override metric-vocab.md location (tests)")
    p.add_argument("--dry-run", action="store_true", help="Compute + report; write nothing")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if not args.xbrl and not args.targets:
        print("ERROR: at least one of --xbrl / --targets is required", file=sys.stderr)
        return 1

    try:
        if args.vault_root:
            vault_root = Path(args.vault_root).resolve()
        else:
            vault_root = _find_vault_root(Path(args.entity).resolve())
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        report = extract(
            entity_path=Path(args.entity).resolve(),
            xbrl_path=Path(args.xbrl).resolve() if args.xbrl else None,
            targets_path=Path(args.targets).resolve() if args.targets else None,
            vault_root=vault_root,
            vocab_path=Path(args.vocab).resolve() if args.vocab else None,
            cik=args.cik,
            since=args.since,
            dry_run=args.dry_run,
        )
    except ExtractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
