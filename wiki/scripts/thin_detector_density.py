#!/usr/bin/env python3
"""Thin-page detector — Layer-0 density priors + Layer-1b chunked recall.

Two slices of the thin-page detector (spec Behavior #3, synthesis §2a + §2b):

  Layer-0  density priors  — RAW-ONLY signal (numeric / enumeration / table /
                             named-item density + semantic dispersion), each a
                             per-1k-token number. Feeds routing + per-page
                             thresholds; never a standalone detector (D-1/D-4:
                             density measures the SOURCE, not the loss).
  Layer-1b chunked recall  — flags WHOLESALE-missing raw passages. Splits the raw
                             into FIXED ~900-token / 15%-overlap windows (NOT
                             H2-split — pypdf paper twins have no clean headings),
                             scores each against the page's indexed chunk vectors,
                             and reports char-weighted `uncovered_mass` (primary)
                             + P10 worst-window coverage (secondary). A window is
                             uncovered only if it is low on BOTH cosine AND BM25
                             (codex's keyword floor — kills paraphrase false-flags).

Page vectors are REUSED from the existing `sb-wiki-search.py` SQLite index (pages are
already embedded; never re-embed them). Raw vectors are PERSISTED by `sb-wiki-search.py`'s
`index-raw` (raw_chunks table, per-vector model id, OD-2 invalidation) — this detector
reads them and triggers an incremental embed for the page's own raw if needed.

Key-absent behavior (spec edge case): with no `VOYAGE_API_KEY`, Layer-1b is OFF — the
report carries `chunked_recall.status="unavailable-no-embeddings"`, NOT a false all-clear.
Layer-0 priors are embedding-free EXCEPT dispersion (which needs raw vectors); the four
regex priors always compute, dispersion reports null when embeddings are off.

The compare-set (wiki-schema): page Substance + Counterpoints + Methodology +
Notable quotes. Frontmatter / My take / Sources are excluded.

CLI:
    priors --raw RAWPATH [--json]
        Layer-0 density priors for one raw source (+ routing verdict).
    recall --page PAGEPATH --raw RAWPATH [--json] [--no-embeddings] [--db PATH]
        Layer-1b chunked recall for a (page, raw) pair. Embeds the raw incrementally
        (bounded to that one source) unless --no-embeddings.
    detect --page PAGEPATH --raw RAWPATH [--json] [--no-embeddings]
        Both layers in one report.

Paths are vault-relative (resolved against the wiki_root from sb-os.json) or absolute.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
from array import array
from dataclasses import dataclass, field, asdict
from pathlib import Path


# -------------------------------------------------- import sb-wiki-search.py (hyphenated)

def _load_search_module():
    """Import the sibling sb-wiki-search.py (hyphen → not importable by name).

    The module is registered in sys.modules BEFORE exec_module: its dataclasses use
    `from __future__ import annotations`, and dataclass field resolution looks the module
    up by name in sys.modules — absent that registration the load raises during class
    processing."""
    import sys as _sys
    if "sb_wiki_search" in _sys.modules:
        return _sys.modules["sb_wiki_search"]
    here = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        "sb_wiki_search", here / "sb-wiki-search.py")
    if spec is None or spec.loader is None:
        raise ImportError("cannot locate sb-wiki-search.py next to this script")
    mod = importlib.util.module_from_spec(spec)
    _sys.modules["sb_wiki_search"] = mod
    spec.loader.exec_module(mod)
    return mod


WS = _load_search_module()


# ----------------------------------------------------------------- compare-set extraction

# The page sections compared against the raw (wiki-schema). Counterpoints is included so a
# caveat legitimately parked there is not false-flagged as dropped; My take / Sources are
# excluded (subjective / bibliographic, not source substance).
COMPARE_SECTIONS = ("Substance", "Counterpoints", "Methodology", "Notable quotes")
_H2_ANY_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)


def extract_compare_set(page_text: str,
                        sections: tuple[str, ...] = COMPARE_SECTIONS) -> str:
    """Concatenate the page's compare-set section bodies (case-insensitive heading match).

    Missing sections are silently skipped. Returns the joined text used as the page side
    of the recall comparison — though recall actually scores against the page's INDEXED
    chunk vectors, this text is the fallback / BM25 page side."""
    body = WS._FRONTMATTER_RE.sub("", page_text, count=1)
    matches = list(_H2_ANY_RE.finditer(body))
    wanted = {s.lower() for s in sections}
    out: list[str] = []
    for i, m in enumerate(matches):
        name = m.group(1).strip().lower()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        if name in wanted:
            out.append(body[m.end():end].strip())
    return "\n\n".join(p for p in out if p)


# ============================================================ Layer-0 — density priors

# opus's load-bearing numeric filter: count quantities, but DROP bare years, citation
# markers ([12], [^3]), and figure/table/page refs — those are not droppable substance.
_NUMERIC_TOKEN_RE = re.compile(
    r"""(?<![\w.])            # not mid-identifier
    (?:\$|€|£)?\s?            # optional currency
    \d[\d,]*                  # integer part
    (?:\.\d+)?               # optional decimal
    \s?(?:%|x|×|bp|bps|k|m|bn|b|million|billion|trillion|
        kg|g|mg|km|m|cm|mm|ms|s|hrs?|hours?|days?|years?|x)?  # optional unit
    """,
    re.X | re.I,
)
_BARE_YEAR_RE = re.compile(r"(?<!\$)\b(19|20)\d{2}\b")
_CITATION_RE = re.compile(r"\[\^?\d+\]")
_FIGREF_RE = re.compile(r"\b(?:figure|fig\.?|table|tbl\.?|page|p\.?|eq\.?|equation)\s*\d+",
                        re.I)

# Enumeration markers (D3, qwen weights): named tests/rules weigh far above bullets.
_RULE_LABEL_RE = re.compile(
    r"^\s*(?:[-*]\s+)?(?:[A-Z][\w/ -]{0,40}?)\s*(?:rule|test|law|principle|heuristic|"
    r"criterion|framework|theorem|lemma)\b", re.I | re.M)
_ORDINAL_RE = re.compile(r"\b(?:first|second|third|fourth|fifth|\d+(?:st|nd|rd|th))\b", re.I)
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+", re.M)
_N_PRINCIPLES_RE = re.compile(r"\b\d+\s+(?:principles?|rules?|tests?|laws?|steps?|reasons?|"
                              r"factors?|criteria|ways?)\b", re.I)

# Table / structured-comparison density (D4, glm weights): table rows >> 'vs' >> labeled pair.
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.M)
_VS_RE = re.compile(r"\b(?:vs\.?|versus)\b", re.I)
_ARROW_RE = re.compile(r"(?:->|→|=>|⇒)")

# Named-item / specificity density (D5, opus regex-only — no spaCy):
# acronyms, coined "the X gap/effect/trap", repeated Proper-Noun runs, hyphenated compounds.
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,6}(?:-\d+)?\b")
_COINAGE_RE = re.compile(r"\bthe\s+[a-z]+(?:[- ][a-z]+)?\s+(?:gap|effect|trap|problem|"
                         r"paradox|fallacy|principle|law|economy|shift)\b", re.I)
_PROPER_RUN_RE = re.compile(r"\b(?:[A-Z][a-z]+)(?:\s+[A-Z][a-z]+)+\b")
_HYPHEN_COMPOUND_RE = re.compile(r"\b[a-z]+-[a-z]+(?:-[a-z]+)*\b", re.I)
_WORD_RE = re.compile(r"\b[\w']+\b")


def _count_numeric(text: str) -> int:
    masked = _CITATION_RE.sub(" ", text)
    masked = _FIGREF_RE.sub(" ", masked)
    raw_hits = list(_NUMERIC_TOKEN_RE.finditer(masked))
    n = 0
    for m in raw_hits:
        tok = m.group(0).strip()
        if not re.search(r"\d", tok):
            continue
        # drop a bare year unless it carries a unit/currency (then it is a quantity)
        if _BARE_YEAR_RE.fullmatch(tok) and not re.search(r"[%$€£x×]", tok):
            continue
        n += 1
    return n


def _weighted_enumeration(text: str) -> float:
    score = 0.0
    score += 3.0 * len(_RULE_LABEL_RE.findall(text))
    score += 2.0 * len(_N_PRINCIPLES_RE.findall(text))
    score += 1.5 * len(_ORDINAL_RE.findall(text))
    score += 0.3 * len(_BULLET_RE.findall(text))
    return score


def _weighted_table(text: str) -> float:
    score = 0.0
    score += 5.0 * len(_TABLE_ROW_RE.findall(text))
    score += 2.0 * len(_VS_RE.findall(text))
    score += 1.0 * len(_ARROW_RE.findall(text))
    return score


def _named_items(text: str) -> int:
    n = 0
    n += len(_ACRONYM_RE.findall(text))
    n += len(_COINAGE_RE.findall(text))
    n += len(set(_PROPER_RUN_RE.findall(text)))   # dedup proper-noun runs
    return n


def _token_estimate(text: str) -> int:
    return max(1, len(_WORD_RE.findall(text)))


@dataclass
class DensityPriors:
    raw_path: str
    tokens: int
    numeric_density: float       # numeric atoms per 1k tokens
    enumeration_density: float   # weighted enumeration score per 1k tokens
    table_density: float         # weighted table score per 1k tokens
    named_density: float         # named-item count per 1k tokens
    dispersion: float | None     # mean distance-to-centroid of raw window vectors (0..~1)
    dispersion_note: str
    # raw counts (pre-normalization) for transparency / detector twins
    numeric_count: int
    enumeration_score: float
    table_score: float
    named_count: int


def _per_1k(count: float, tokens: int) -> float:
    return round(count * 1000.0 / tokens, 3)


def compute_density(raw_text: str, raw_path: str,
                    raw_vectors: list[list[float]] | None = None) -> DensityPriors:
    """Layer-0 priors over a raw source body (frontmatter stripped). `raw_vectors`, when
    supplied (the raw's own window embeddings), enable the dispersion prior — distance-to-
    centroid (opus's O(n) form, NOT O(n^2) pairwise)."""
    body = WS._FRONTMATTER_RE.sub("", raw_text, count=1).strip()
    tokens = _token_estimate(body)
    numeric_count = _count_numeric(body)
    enum_score = _weighted_enumeration(body)
    table_score = _weighted_table(body)
    named_count = _named_items(body)

    dispersion: float | None = None
    note = "no embeddings — dispersion not computed"
    if raw_vectors and len(raw_vectors) >= 2:
        dispersion = _distance_to_centroid(raw_vectors)
        note = f"distance-to-centroid over {len(raw_vectors)} raw windows"
    elif raw_vectors is not None and len(raw_vectors) < 2:
        note = f"only {len(raw_vectors)} raw window(s) — dispersion needs >=2"

    return DensityPriors(
        raw_path=raw_path, tokens=tokens,
        numeric_density=_per_1k(numeric_count, tokens),
        enumeration_density=_per_1k(enum_score, tokens),
        table_density=_per_1k(table_score, tokens),
        named_density=_per_1k(named_count, tokens),
        dispersion=dispersion, dispersion_note=note,
        numeric_count=numeric_count, enumeration_score=round(enum_score, 2),
        table_score=round(table_score, 2), named_count=named_count,
    )


def _distance_to_centroid(vectors: list[list[float]]) -> float:
    """Mean cosine distance of each unit vector to the (re-normalized) centroid. 0 = all
    identical direction; larger = more semantically dispersed source. O(n)."""
    try:
        import numpy as np
        mat = np.asarray(vectors, dtype=np.float64)
        centroid = mat.mean(axis=0)
        cn = np.linalg.norm(centroid)
        if cn == 0:
            return 0.0
        centroid = centroid / cn
        sims = mat @ centroid
        return float(round(1.0 - sims.mean(), 4))
    except ImportError:
        n = len(vectors)
        dim = len(vectors[0])
        centroid = [sum(v[i] for v in vectors) / n for i in range(dim)]
        cn = math.sqrt(sum(c * c for c in centroid))
        if cn == 0:
            return 0.0
        centroid = [c / cn for c in centroid]
        sims = [sum(v[i] * centroid[i] for i in range(dim)) for v in vectors]
        return round(1.0 - sum(sims) / n, 4)


# Routing thresholds (PROVISIONAL — synthesis §2a says calibrate on the label set; until
# the OD-1 gold set drives them they are conservative defaults flagged as provisional).
# The routing verdict is a PRIOR (catches "short-but-dense" sources the token-only rule
# misroutes), never a thinness verdict.
ROUTE_TOKENS = 30_000
ROUTE_NUMERIC_DENSITY = 12.0
ROUTE_TABLE_DENSITY = 8.0
ROUTE_DISPERSION = 0.18


def routing_verdict(priors: DensityPriors) -> dict:
    """Replaces token-count-only routing: route to the strong model if long OR dense.
    Provisional thresholds (synthesis §2a) — order/escalation only, not a thinness call."""
    reasons = []
    if priors.tokens > ROUTE_TOKENS:
        reasons.append(f"tokens>{ROUTE_TOKENS}")
    if priors.numeric_density >= ROUTE_NUMERIC_DENSITY:
        reasons.append(f"numeric_density>={ROUTE_NUMERIC_DENSITY}")
    if priors.table_density >= ROUTE_TABLE_DENSITY:
        reasons.append(f"table_density>={ROUTE_TABLE_DENSITY}")
    if priors.dispersion is not None and priors.dispersion >= ROUTE_DISPERSION:
        reasons.append(f"dispersion>={ROUTE_DISPERSION}")
    return {"route_to": "strong" if reasons else "default",
            "reasons": reasons, "thresholds_provisional": True}


# ============================================================ Layer-1b — chunked recall

# Provisional uncovered threshold (synthesis §2b: calibrate on the OD-1 label set — this is
# a recall-biased FLOOR, not a final cut). A raw window is UNCOVERED when its best cosine to
# any page chunk is below this AND its keyword (BM25) floor is also low (both must fail — the
# keyword floor cuts paraphrase false-positives).
#
# CALIBRATION FINDING (measured on real voyage-3.5 vectors, 2026-06-19, evidence p2-3):
# raw-window best-cosine to a page's compare-set sits HIGH even for a wholesale-thin page —
# a 2-sentence abstract vs a 38-window paper gave window cosines 0.66–0.88 (median 0.82),
# vs a faithful page's 0.70–0.92 (median 0.84). This is the D-4 cosine-blindness the design
# warns of, on real data: absolute cosine barely separates thin from faithful (per-window
# delta ~0.04). A threshold BELOW the distribution (the original 0.55) never fires — a silent
# false-negative the spec forbids. 0.76 sits inside the distribution and is recall-biased:
# the thin page surfaced ~2.3x the uncovered_mass of the faithful one (0.187 vs 0.080). It is
# PROVISIONAL — the escalation ladder (task 2.4) calibrates the real cut on the gold set and
# leans on OR-of-thresholds + the typed-retention layer, never on this layer alone.
UNCOVERED_COSINE = 0.76
BM25_FLOOR_FRACTION = 0.30   # window's page-overlap fraction below this = "low on keywords"


@dataclass
class WindowResult:
    anchor: str          # char span in the raw
    chars: int
    best_cosine: float
    keyword_overlap: float
    uncovered: bool
    preview: str


@dataclass
class RecallReport:
    page_path: str
    raw_path: str
    status: str                       # ok | unavailable-no-embeddings | error
    uncovered_mass: float             # char-weighted fraction of raw that is uncovered (0..1)
    p10_coverage: float | None        # 10th-percentile best-cosine (worst-covered passage)
    n_windows: int
    n_uncovered: int
    flagged: bool
    threshold_cosine: float
    uncovered_windows: list[dict] = field(default_factory=list)
    note: str = ""


def _bm25_overlap(window_text: str, page_token_set: set[str]) -> float:
    """Fraction of a raw window's distinct content tokens that also appear in the page
    compare-set — a cheap keyword floor standing in for BM25 presence. 1.0 = every term
    is present on the page; 0.0 = none. (A true BM25 score needs corpus stats; for the
    FLOOR — 'does the page share this window's key terms?' — token presence suffices and
    matches the design's intent: uncovered only if low on cosine AND keywords.)"""
    toks = {t for t in _WORD_RE.findall(window_text.lower()) if len(t) > 3}
    if not toks:
        return 1.0   # nothing contentful to miss
    present = sum(1 for t in toks if t in page_token_set)
    return present / len(toks)


def chunked_recall(page_text: str, raw_text: str, page_path: str, raw_path: str,
                   page_vectors: list[list[float]] | None,
                   raw_windows: list,                       # list[WS.Chunk]
                   raw_vectors: list[list[float]] | None,
                   embeddings_on: bool) -> RecallReport:
    """Compute char-weighted uncovered_mass for a (page, raw) pair.

    `page_vectors`  — the page's INDEXED chunk vectors (reused, never re-embedded).
    `raw_windows`   — fixed-size windows over the raw (WS.window_raw output).
    `raw_vectors`   — each window's embedding, aligned to raw_windows (None when off).
    `embeddings_on` — False when no key: Layer-1b reports unavailable, never 'clean'."""
    compare_text = extract_compare_set(page_text)
    page_token_set = {t for t in _WORD_RE.findall(compare_text.lower()) if len(t) > 3}

    if not embeddings_on or page_vectors is None or raw_vectors is None:
        return RecallReport(
            page_path=page_path, raw_path=raw_path,
            status="unavailable-no-embeddings",
            uncovered_mass=-1.0, p10_coverage=None,
            n_windows=len(raw_windows), n_uncovered=0, flagged=False,
            threshold_cosine=UNCOVERED_COSINE,
            note=("VOYAGE_API_KEY absent or vectors unavailable — chunked-recall layer "
                  "OFF; this is NOT an all-clear. The typed-retention layer (task 2.2) "
                  "carries detection when embeddings are unavailable."),
        )

    try:
        import numpy as np
        pmat = np.asarray(page_vectors, dtype=np.float32)   # already unit-normalized
    except ImportError:
        pmat = None

    results: list[WindowResult] = []
    best_cosines: list[float] = []
    total_chars = 0
    uncovered_chars = 0

    for w, rvec in zip(raw_windows, raw_vectors):
        chars = len(w.text)
        total_chars += chars
        if pmat is not None:
            import numpy as np
            sims = pmat @ np.asarray(rvec, dtype=np.float32)
            best = float(sims.max()) if sims.size else 0.0
        else:
            best = 0.0
            for pv in page_vectors:
                s = sum(a * b for a, b in zip(pv, rvec))
                if s > best:
                    best = s
        kw = _bm25_overlap(w.text, page_token_set)
        uncovered = best < UNCOVERED_COSINE and kw < BM25_FLOOR_FRACTION
        if uncovered:
            uncovered_chars += chars
        best_cosines.append(best)
        results.append(WindowResult(
            anchor=w.anchor, chars=chars, best_cosine=round(best, 4),
            keyword_overlap=round(kw, 3), uncovered=uncovered,
            preview=" ".join(w.text.split())[:200]))

    uncovered_mass = round(uncovered_chars / total_chars, 4) if total_chars else 0.0
    p10 = None
    if best_cosines:
        try:
            import numpy as np
            p10 = float(round(np.percentile(best_cosines, 10), 4))
        except ImportError:
            s = sorted(best_cosines)
            p10 = round(s[max(0, int(0.10 * (len(s) - 1)))], 4)

    uncovered_list = [asdict(r) for r in results if r.uncovered]
    # rank uncovered windows worst (lowest cosine) first
    uncovered_list.sort(key=lambda r: r["best_cosine"])

    return RecallReport(
        page_path=page_path, raw_path=raw_path, status="ok",
        uncovered_mass=uncovered_mass, p10_coverage=p10,
        n_windows=len(raw_windows), n_uncovered=len(uncovered_list),
        flagged=uncovered_mass > 0.0,
        threshold_cosine=UNCOVERED_COSINE,
        uncovered_windows=uncovered_list,
        note=f"char-weighted over {len(raw_windows)} windows; "
             f"uncovered = cosine<{UNCOVERED_COSINE} AND keyword_overlap<{BM25_FLOOR_FRACTION}",
    )


# ----------------------------------------------------------------- path + vector plumbing

def _resolve_paths(arg_path: str, wiki_root: Path, vault_root: Path) -> Path:
    """Resolve a vault-relative or absolute path to an existing file."""
    p = Path(arg_path)
    if p.is_absolute() and p.exists():
        return p
    for base in (vault_root, wiki_root, Path.cwd()):
        cand = base / arg_path
        if cand.exists():
            return cand
    # last resort: relative to wiki_root even if missing (error surfaces on read)
    return vault_root / arg_path


def _rel_to_wiki(path: Path, wiki_root: Path) -> str | None:
    try:
        return path.resolve().relative_to(wiki_root.resolve()).as_posix()
    except ValueError:
        return None


def _load_page_vectors(conn, page_rel: str) -> list[list[float]] | None:
    """Page chunk vectors from the existing index (reused, never re-embedded)."""
    rows = conn.execute(
        "SELECT embedding FROM chunks WHERE path=? AND embedding IS NOT NULL", (page_rel,)
    ).fetchall()
    if not rows:
        return None
    out = []
    for (blob,) in rows:
        a = array("f"); a.frombytes(blob)
        out.append(list(a))
    return out


def _embed_page_compare_set(page_text: str, embedder) -> list[list[float]] | None:
    """Embed the page's compare-set ON THE FLY when the page is not in the index.

    A re-ingest candidate (or a calibration fixture) is not yet indexed, so its chunk
    vectors don't exist. Chunk the compare-set the SAME way the indexer chunks a page
    (heading-level, title-prefixed) and embed those chunks. Returns unit-normalized
    vectors, or None when there is no compare-set content to embed."""
    compare = extract_compare_set(page_text)
    if not compare.strip():
        return None
    chunks = WS.chunk_page("# page\n\n" + compare, "compare.md")
    if not chunks:
        return None
    vecs = embedder([c.text for c in chunks], "document")
    return [WS._normalize(v) for v in vecs]


def _load_raw_vectors(conn, raw_rel: str):
    """(windows-as-Chunks, vectors) for a raw source from raw_chunks, ordered by pos.
    Returns (chunks, vectors) where vectors may contain None for un-embedded windows."""
    rows = conn.execute(
        "SELECT anchor, pos, text, embedding FROM raw_chunks WHERE path=? ORDER BY pos",
        (raw_rel,)
    ).fetchall()
    chunks = []
    vectors = []
    for anchor, pos, text, blob in rows:
        chunks.append(WS.Chunk(anchor=anchor, pos=pos, text=text))
        if blob is None:
            vectors.append(None)
        else:
            a = array("f"); a.frombytes(blob)
            vectors.append(list(a))
    return chunks, vectors


# ----------------------------------------------------------------------------------- CLI

def _setup(args):
    """Resolve vault_root, wiki_root, db, key, embedder. Returns a context dict."""
    vault_root = (args.vault_root.resolve() if args.vault_root
                  else WS._find_vault_root())
    if vault_root is None:
        raise SystemExit("cannot resolve vault root: sb-os.json not found; pass --vault-root")
    wiki_root = WS.resolve_wiki_root(vault_root)
    db_path = args.db or WS._default_db(wiki_root)
    no_emb = getattr(args, "no_embeddings", False)
    api_key = None if no_emb else WS.resolve_api_key(vault_root)
    embedder = WS.make_voyage_embedder(api_key, args.model) if api_key else None
    return {"vault_root": vault_root, "wiki_root": wiki_root, "db_path": db_path,
            "model": args.model, "api_key": api_key, "embedder": embedder,
            "embeddings_on": embedder is not None}


def _ensure_raw_embedded(conn, ctx, raw_rel: str):
    """Incrementally embed THIS raw source (bounded to it) so its windows have vectors.
    Reuses WS.sync_raw with a glob limiter — never embeds the whole corpus. With
    embeddings off the raw is still WINDOWED (so n_windows is reported) but not embedded."""
    WS.sync_raw(conn, ctx["wiki_root"],
                embedder=ctx["embedder"] if ctx["embeddings_on"] else None,
                model=ctx["model"], glob=raw_rel)


def cmd_priors(args) -> int:
    ctx = _setup(args)
    conn = WS.open_db(ctx["db_path"])
    raw_path = _resolve_paths(args.raw, ctx["wiki_root"], ctx["vault_root"])
    raw_text = WS.read_text(raw_path)
    raw_rel = _rel_to_wiki(raw_path, ctx["wiki_root"])

    raw_vectors = None
    if ctx["embeddings_on"] and raw_rel:
        _ensure_raw_embedded(conn, ctx, raw_rel)
        _chunks, vecs = _load_raw_vectors(conn, raw_rel)
        raw_vectors = [v for v in vecs if v is not None] or None

    priors = compute_density(raw_text, raw_rel or str(raw_path), raw_vectors)
    verdict = routing_verdict(priors)
    out = {"priors": asdict(priors), "routing": verdict,
           "embeddings_on": ctx["embeddings_on"]}
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        p = priors
        print(f"raw: {p.raw_path}  ({p.tokens} tokens)")
        print(f"  numeric_density   {p.numeric_density:>7}  ({p.numeric_count} atoms)")
        print(f"  enumeration_dens. {p.enumeration_density:>7}  (score {p.enumeration_score})")
        print(f"  table_density     {p.table_density:>7}  (score {p.table_score})")
        print(f"  named_density     {p.named_density:>7}  ({p.named_count} items)")
        disp = "n/a" if p.dispersion is None else f"{p.dispersion}"
        print(f"  dispersion        {disp:>7}  ({p.dispersion_note})")
        print(f"  routing -> {verdict['route_to']}  reasons={verdict['reasons']}")
    return 0


def cmd_recall(args) -> int:
    ctx = _setup(args)
    conn = WS.open_db(ctx["db_path"])
    page_path = _resolve_paths(args.page, ctx["wiki_root"], ctx["vault_root"])
    raw_path = _resolve_paths(args.raw, ctx["wiki_root"], ctx["vault_root"])
    page_text = WS.read_text(page_path)
    raw_text = WS.read_text(raw_path)
    page_rel = _rel_to_wiki(page_path, ctx["wiki_root"])
    raw_rel = _rel_to_wiki(raw_path, ctx["wiki_root"])

    page_vectors = _load_page_vectors(conn, page_rel) if page_rel else None
    page_vec_source = "index"
    if page_vectors is None and ctx["embeddings_on"]:
        # page not in the index (a re-ingest candidate or a calibration fixture) — embed
        # its compare-set on the fly so recall can still score it.
        page_vectors = _embed_page_compare_set(page_text, ctx["embedder"])
        page_vec_source = "on-the-fly"
    if raw_rel:
        _ensure_raw_embedded(conn, ctx, raw_rel)
        raw_windows, raw_vecs = _load_raw_vectors(conn, raw_rel)
    else:
        raw_windows = WS.window_raw(raw_text, str(raw_path))
        raw_vecs = [None] * len(raw_windows)

    raw_vectors = raw_vecs if all(v is not None for v in raw_vecs) and raw_vecs else None
    report = chunked_recall(
        page_text, raw_text, page_rel or str(page_path), raw_rel or str(raw_path),
        page_vectors, raw_windows, raw_vectors, ctx["embeddings_on"])
    report.note += f" | page_vectors={page_vec_source}"

    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(f"page: {report.page_path}  (page vectors: {page_vec_source})")
        print(f"raw:  {report.raw_path}")
        print(f"status: {report.status}")
        if report.status == "ok":
            print(f"  uncovered_mass {report.uncovered_mass}  "
                  f"(p10_coverage {report.p10_coverage})")
            print(f"  windows {report.n_windows}, uncovered {report.n_uncovered}, "
                  f"flagged={report.flagged}")
            for w in report.uncovered_windows[:5]:
                print(f"    [{w['anchor']}] cos={w['best_cosine']} kw={w['keyword_overlap']}")
                print(f"        {w['preview'][:120]}")
        else:
            print(f"  {report.note}")
    return 0


def cmd_detect(args) -> int:
    """Both layers in one report (priors + chunked recall)."""
    ctx = _setup(args)
    conn = WS.open_db(ctx["db_path"])
    page_path = _resolve_paths(args.page, ctx["wiki_root"], ctx["vault_root"])
    raw_path = _resolve_paths(args.raw, ctx["wiki_root"], ctx["vault_root"])
    page_text = WS.read_text(page_path)
    raw_text = WS.read_text(raw_path)
    page_rel = _rel_to_wiki(page_path, ctx["wiki_root"])
    raw_rel = _rel_to_wiki(raw_path, ctx["wiki_root"])

    page_vectors = _load_page_vectors(conn, page_rel) if page_rel else None
    page_vec_source = "index"
    if page_vectors is None and ctx["embeddings_on"]:
        page_vectors = _embed_page_compare_set(page_text, ctx["embedder"])
        page_vec_source = "on-the-fly"
    raw_vectors_for_disp = None
    if raw_rel:
        _ensure_raw_embedded(conn, ctx, raw_rel)
        raw_windows, raw_vecs = _load_raw_vectors(conn, raw_rel)
        if ctx["embeddings_on"]:
            raw_vectors_for_disp = [v for v in raw_vecs if v is not None] or None
    else:
        raw_windows = WS.window_raw(raw_text, str(raw_path))
        raw_vecs = [None] * len(raw_windows)

    priors = compute_density(raw_text, raw_rel or str(raw_path), raw_vectors_for_disp)
    verdict = routing_verdict(priors)
    raw_vectors = raw_vecs if (raw_vecs and all(v is not None for v in raw_vecs)) else None
    report = chunked_recall(
        page_text, raw_text, page_rel or str(page_path), raw_rel or str(raw_path),
        page_vectors, raw_windows, raw_vectors, ctx["embeddings_on"])
    report.note += f" | page_vectors={page_vec_source}"

    out = {"priors": asdict(priors), "routing": verdict,
           "chunked_recall": asdict(report), "embeddings_on": ctx["embeddings_on"]}
    print(json.dumps(out, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--vault-root", type=Path, default=None)
    parser.add_argument("--db", type=Path, default=None,
                        help="index db (default {wiki_root}/.sb-wiki-search/index.db)")
    parser.add_argument("--model", default=WS.DEFAULT_MODEL)
    parser.add_argument("--no-embeddings", action="store_true",
                        help="force the key-absent path (Layer-1b OFF) for testing")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pri = sub.add_parser("priors", help="Layer-0 density priors for a raw source")
    p_pri.add_argument("--raw", required=True)
    p_pri.add_argument("--json", action="store_true")
    p_pri.set_defaults(func=cmd_priors)

    p_rec = sub.add_parser("recall", help="Layer-1b chunked recall for a (page, raw) pair")
    p_rec.add_argument("--page", required=True)
    p_rec.add_argument("--raw", required=True)
    p_rec.add_argument("--json", action="store_true")
    p_rec.set_defaults(func=cmd_recall)

    p_det = sub.add_parser("detect", help="both layers in one JSON report")
    p_det.add_argument("--page", required=True)
    p_det.add_argument("--raw", required=True)
    p_det.set_defaults(func=cmd_detect)
    return parser


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
