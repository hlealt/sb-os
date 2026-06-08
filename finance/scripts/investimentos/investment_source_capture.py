"""investment_source_capture.py — Save an approved URL to {wiki_root}/raw/{origin}/.

CLI:
    python investment_source_capture.py --url URL --origin ORIGIN
        [--mode markdown|html-archive|both|browser|manual]
        [--title TITLE]
        [--thesis THESIS_SLUG]
        [--vault-root PATH]
        [--user-agent UA]
        [--manual-file PATH]
        [--no-curl-fallback]
        [--ext md|html|json]
        [--pdf-text]
        [--dry-run]

--ext overrides the saved-file extension for markdown mode and manual/browser
saves (default md). Use --ext json to capture XBRL companyfacts JSON data
artifacts (consumed by investment_financials_extract). html-archive/both .html
output is unaffected by --ext.

Manual/browser PDF handling: a --manual-file detected as a PDF (.pdf extension
or %PDF- magic bytes) is BINARY-COPIED to raw/{origin}/{title-slug}.pdf per the
wiki Raw PDF Title-Conformance rule — title-slug filename derived from --title
(REQUIRED for PDF captures), no date prefix, and an existing {title-slug}.pdf
is NEVER overwritten (state=blocked collision error instead). --pdf-text
additionally writes a {title-slug}.md text companion extracted via pypdf
(optional dependency) so a text raw exists for grep-based ingest verification;
an extraction failure or near-empty result is surfaced in the JSON
(transform_error / transform_warning) and never blocks the PDF capture itself.
--ext does not apply to PDF saves.

--manual-file path contract: paths with arbitrary Unicode characters (curly
quotes, accented letters, spaces) MUST be passed as a PowerShell literal
string to avoid shell interpretation. PowerShell: use single quotes around
the path, e.g. --manual-file 'path/to/“Weird Title”.html'. On
Unix/bash: use single quotes the same way. If the path cannot be literal-
quoted (e.g., a shell pipeline), use --manual-file - to read from stdin
(stdin mode: the tool reads the file content from standard input; --title
MUST be supplied when using stdin mode).

Content-validation (A1): before returning captured_to_raw, every fetched
web body is checked. Prose is extracted FIRST and a CONTENT-GATE runs:
  0. Byte floor — body below _BODY_MIN_BYTES fails (0-byte / truncated body).
  1. Rich-prose accept — a body whose extracted prose is at/above _PROSE_OK_CHARS
     is ACCEPTED immediately, before any captcha/density gate. A real bot-wall or
     captcha REPLACES the article with a short challenge page; it never ships
     substantial article prose. So a content-rich body cannot be a wall, and its
     captcha/challenge words are page chrome — e.g. Wikipedia's logged-out signup
     UI carries the word "Captcha". This content-gate is what prevents the
     substring scan from false-blocking legitimate content-rich articles.
  2. CAPTCHA / bot-wall fingerprints — applied ONLY when prose is THIN
     (< _PROSE_OK_CHARS): specific challenge PHRASES ("verify you are human",
     "checking your browser before", Cloudflare/Imperva challenge markers) in a
     200 body. Markers are challenge phrases, not bare words, as defense in depth
     on the thin-prose path.
  3. Article-body density — applied ONLY when prose is THIN: an absolute prose
     floor (_PROSE_MIN_CHARS) catches a shell yielding ~0 prose, and a size-gated
     prose/body RATIO floor (_DENSITY_MIN_RATIO, applied at/above
     _DENSITY_RATIO_BODY_BYTES) catches a large-but-contentless JS shell whose
     stray visible text clears the absolute floor (e.g. emarketer, Next.js
     self.__next_f.push() fragment soup). A genuine multi-MB article carrying a
     large client-hydration payload (real article SSR'd alongside ~2 MB of soup)
     extracts substantial prose, so the rich-prose accept (gate 1) returns it
     before the density gates ever run.
On validation failure: state=blocked, source-queue row written via the
existing blocked path, failure_reason recorded. Manual-file and binary/PDF
paths are EXEMPT from the density check (user already vetted the content);
only a sane byte floor applies to manual paths.

Article-body extraction (A2): fetched HTML bodies are run through a
two-tier extractor. PRIMARY: trafilatura (lazy optional dependency) — a
purpose-built readability library that handles diverse site layouts and
pagination, returning clean plain text. FALLBACK (if trafilatura is
unavailable OR returns empty/near-empty): BeautifulSoup4 (lazy optional
dependency) richest-container logic — scripts, styles, nav, header, footer,
and boilerplate are stripped; EVERY matching content-selector container AND
<body> are rendered to prose and the one with the most text is kept — so an
empty semantic wrapper (a bare <article> shell whose paragraphs live in a
sibling .post-content) can no longer short-circuit a content-rich
server-rendered article to 0 prose (the regression fixed 2026-06-08:
Brazil Journal). The full-page HTML dump is preserved as a .full.html
sidecar for archival/fallback. The primary raw is readable prose, not a
single-line HTML dump. A genuine JS shell still extracts ~0 prose from
either extractor, so the density gate still blocks it.

Date-parse hardening (A2): _parse_published_date is a defensive lenient
date parser — a malformed or implausible value (e.g. 0000-12-31, empty,
garbage) yields None rather than crashing. This tool writes raw article
prose with NO frontmatter and passes any source-supplied frontmatter
through verbatim (it never emits a published: field of its own), so the
function is NOT wired into the capture path here; it is exposed for the
INGEST stage (sb-wiki-ingest), where a source's published: value is read
into wiki frontmatter and the 0000-12-31-class crash actually originates.
A2's date-parse home is therefore ingest-side — see concerns in the task
return.

Returns a metadata summary only — never dumps fetched text into stdout.
Honors the 6-state source lifecycle:
    rejected | approved_for_capture | captured_to_raw | ingested_to_wiki
    | gated_pending_access | blocked

Gated sources (paywall / login required) are NOT fetched — they are registered
as gated_pending_access in {wiki_root}/source-queue.md. Pass --gated to declare
a source gated.

Source-queue registration (§10 source-lifecycle): gated registrations AND
transport-level blocked outcomes (fetch failed after the curl fallback, or
with the fallback disabled, or content-validation failed) append an H2 entry
to {wiki_root}/source-queue.md — the investment source queue that sb-wiki-lint
(finance extension) surfaces and prunes. The file is created with
`type: source-queue` frontmatter when absent. The same (state, url) pair
never registers twice. Usage-error blocked results (missing --manual-file,
unknown mode) and dry-run register NOTHING.

All fetch modes send a declared User-Agent (default: a descriptive tool UA;
override with --user-agent). Fair-access endpoints such as SEC EDGAR 403
undeclared default-library UAs — pass a contact-bearing UA per the endpoint's
policy when required (e.g. "Name contact@example.com").

When the native httpx fetch fails at transport level (403, bot-fingerprint
rejection, connection reset), fetch modes retry once via subprocess curl with
the same User-Agent — curl's HTTP stack and TLS fingerprint pass some bot
walls that reject httpx. The metadata summary records which method fetched
(fetch_method: "httpx" | "curl-fallback") — never a silent fallback. Disable
with --no-curl-fallback. Only after BOTH methods fail does the source return
state=blocked.

Fetch modes:
    markdown      — GET URL, extract article to .md; full HTML sidecar .full.html
    html-archive  — GET URL, save full response body as .html (no extraction)
    both          — article .md + full .html sidecar (same as markdown + html-archive)
    browser       — no fetch; saves the user-fetched file passed via --manual-file
    manual        — no fetch; saves the user-fetched file passed via --manual-file
                    (both: a PDF --manual-file is binary-copied to
                    {title-slug}.pdf — see PDF handling above)

Exit 0 = success (captured or dry-run).
Exit 1 = error (bad args, fetch failed, unknown origin, etc.).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Content-validation constants (A1)
# ---------------------------------------------------------------------------

# Fetched body below this many bytes is immediately blocked (byte floor).
# Catches 0-byte and a-few-junk-bytes responses (truncated/empty body). A real
# HTML response — even a one-paragraph article — is always well above this once
# wrapped in <html>/<head> markup, so this floor never false-fails a genuine
# page. Manual files are exempt from the density/captcha checks but still pass
# this floor (a 0-byte manual file is still a non-capture).
_BODY_MIN_BYTES = 16

# Extracted prose below this many characters is a density failure regardless of
# body size. Catches pure JS shells / Next.js self.__next_f.push() fragment soup
# that yield ~0 prose characters after bs4 strips <script>/<style>/nav/boilerplate
# (measured: a 377 KB Next.js soup extracts 0 chars). A genuine article — even a
# terse one-sentence breaking-news item — clears this floor.
# Manual-file and PDF paths are EXEMPT (user already vetted the content).
_PROSE_MIN_CHARS = 25

# Density-ratio floor (extracted-prose chars / total body bytes), applied ONLY to
# bodies at or above _DENSITY_RATIO_BODY_BYTES. This is the gate that catches a
# LARGE-but-contentless shell whose stray visible text (a "Loading..." splash, a
# cookie banner, nav chrome) survives stripping and clears the absolute prose
# floor: a 100-389 KB JS shell measures ratio ~0.0003-0.0005, while a genuine
# article — even one buried in heavy inline-CSS chrome — measures >=0.04. The
# 0.005 floor sits ~10x above observed shells and ~8x below the lightest genuine
# multi-paragraph article. Small bodies (< _DENSITY_RATIO_BODY_BYTES) skip this
# gate: a tiny real page has few absolute prose chars but cannot be a "large
# contentless shell", and the absolute floor already guards near-empty bodies.
_DENSITY_MIN_RATIO = 0.005
_DENSITY_RATIO_BODY_BYTES = 2048

# Extracted-prose ceiling above which the ratio gate is SKIPPED: a body that
# yields this many characters of clean article prose IS a successful capture,
# however much markup surrounded it. This prevents the ratio gate from
# false-blocking a genuine multi-MB page that server-renders a real article
# alongside a large client-hydration payload (e.g. a Next.js article page
# carrying ~2 MB of self.__next_f.push() soup: the article extracts cleanly to
# ~500 chars, but prose/body ratio is ~0.0002 because the soup dwarfs it).
# Observed shells sit far below this (stray-text shells extract <=140 chars), so
# the ceiling never lets a shell through. After A2 extraction the prose IS the
# captured content, so prose volume — not raw body size — is the right signal
# once it is substantial.
_PROSE_OK_CHARS = 400

# CAPTCHA / bot-wall fingerprint patterns (case-insensitive substring scan).
# Matches interstitial challenges served with HTTP 200 on real article URLs.
# CONTENT-GATED: this scan runs ONLY when extracted prose is thin
# (< _PROSE_OK_CHARS). A content-rich body — even one whose page chrome happens
# to contain a challenge word (e.g. Wikipedia's logged-out signup UI carries the
# word "Captcha") — is accepted before this scan ever runs, because a real
# bot-wall REPLACES the content with a short challenge page; it never ships
# 40 KB of article prose alongside the challenge. Patterns are therefore
# specific challenge PHRASES, not bare interstitial words, as defense in depth on
# the thin-prose path (a bare "captcha" still matched legitimate signup/login
# chrome on thin pages).
_CAPTCHA_PATTERNS = [
    r"verify you are (?:a )?human",
    r"verify that you are (?:a )?human",
    r"are you a robot",
    r"i(?:'| a)m not a robot",
    r"complete the captcha",
    r"solve the captcha",
    r"captcha challenge",
    r"please complete the captcha",
    r"cloudflare-challenge",
    r"cf-challenge",
    r"challenge-form",
    r"checking your browser before",
    r"please wait\.\.\. \|",  # Cloudflare "One moment" splash
    r"<title>access denied</title>",
    r"<title>just a moment\.\.\.</title>",
    r"<title>attention required",
    r"window\._cf_chl",           # Cloudflare JS challenge variable
    r"window\.__aw_",             # Imperva AW challenge
    r"_imperva_",                 # Imperva challenge marker (specific token)
    r"incapsula incident id",     # Imperva/Incapsula block page
]
_CAPTCHA_RE = re.compile(
    "|".join(_CAPTCHA_PATTERNS), re.IGNORECASE | re.DOTALL
)


# ---------------------------------------------------------------------------
# Article-body extraction (A2) — lazy BeautifulSoup4 dependency
# ---------------------------------------------------------------------------

# Tags whose entire subtree is boilerplate; stripped before prose extraction.
_STRIP_TAGS = {
    "script", "style", "noscript", "template",
    "nav", "header", "footer", "aside",
    "form", "button", "iframe", "svg", "canvas",
}

# Candidate main-content container selectors. ALL matching containers are
# evaluated (not just the first) and the one yielding the MOST prose wins —
# `<body>` is always evaluated as an additional candidate. First-match-wins was
# a regression: a page carrying an EMPTY semantic wrapper (e.g. a bare
# `<article>` shell whose paragraphs live in a sibling `.post-content`) matched
# the first selector, short-circuited the loop on a 0-prose container, and the
# body fallback never fired — a content-rich server-rendered article extracted 0
# chars and was false-blocked by the density gate (Brazil Journal, 2026-06-08).
_CONTENT_SELECTORS = [
    "article",
    "main",
    '[role="main"]',
    ".article-body",
    ".post-content",
    ".entry-content",
    ".article__body",
    ".story-body",
    ".content-body",
    "#content",
    "#main-content",
    ".main-content",
]


def _root_to_markdown(root) -> str:
    """Render a bs4 element subtree to clean markdown-flavored prose.

    Preserves paragraph/heading/list/quote breaks. Returns "" when the subtree
    holds no block-level text — the signal a richest-container comparison and the
    density gate both key on (an empty wrapper or a JS shell yields "").
    """
    lines: list[str] = []
    for elem in root.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "td", "th"],
        recursive=True,
    ):
        text = elem.get_text(separator=" ", strip=True)
        if not text:
            continue
        tag_name = elem.name
        if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag_name[1])
            lines.append("#" * level + " " + text)
        elif tag_name in ("li",):
            lines.append("- " + text)
        elif tag_name in ("blockquote",):
            lines.append("> " + text)
        else:
            lines.append(text)
    return "\n\n".join(lines)


def _extract_article_markdown(html_body: str) -> tuple[str, str]:
    """Return (extracted_markdown, extraction_note).

    PRIMARY extractor: trafilatura (lazy optional dependency) — a purpose-built
    readability library that handles diverse site layouts and returns clean plain
    text. If trafilatura is unavailable (ImportError) OR its output is
    empty/near-empty (len < _PROSE_MIN_CHARS), the FALLBACK runs instead.

    FALLBACK extractor: BeautifulSoup4 (lazy optional dependency) richest-
    container selection — strips boilerplate and evaluates EVERY matching
    `_CONTENT_SELECTORS` container AND `<body>`, keeping the result with the
    most characters. This defeats the empty-wrapper short-circuit (a bare
    `<article>` shell no longer hides the real article in a sibling container)
    while preserving the density gate's block on genuine JS shells. If bs4 is
    also unavailable, a regex tag-strip is used as the last resort.

    extraction_note is empty on primary success, "trafilatura-empty — bs4 fallback"
    when the primary returned near-empty, "trafilatura unavailable — bs4 fallback"
    when the primary is not installed, or the regime that ran under the last resort.
    """
    # --- PRIMARY: trafilatura ---
    _trafilatura_note = ""
    try:
        import trafilatura  # type: ignore
        result = trafilatura.extract(html_body, include_comments=False,
                                     include_tables=True, no_fallback=False)
        if result and len(result.strip()) >= _PROSE_MIN_CHARS:
            return result.strip(), ""
        # trafilatura returned empty or near-empty — fall through to bs4.
        _trafilatura_note = "trafilatura-empty — bs4 fallback"
    except ImportError:
        _trafilatura_note = "trafilatura unavailable — bs4 fallback"

    # --- FALLBACK: BeautifulSoup4 richest-container ---
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:
        # Last resort: strip all HTML tags with a regex — crude but dependency-free.
        text = re.sub(r"<[^>]+>", " ", html_body)
        text = re.sub(r"[ \t]+", " ", text)
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        note = (_trafilatura_note + "; bs4 unavailable — regex tag strip used"
                if _trafilatura_note else "bs4 unavailable — regex tag strip used")
        return text, note

    soup = BeautifulSoup(html_body, "html.parser")

    # Remove boilerplate subtrees in-place.
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    # Evaluate ALL candidate containers plus <body>; keep the richest prose.
    # NEVER break on the first match — an empty wrapper would short-circuit the
    # real article (the regression this loop fixes).
    body = soup.find("body")
    candidates = []
    for sel in _CONTENT_SELECTORS:
        candidates.extend(soup.select(sel))
    if body is not None:
        candidates.append(body)

    markdown = ""
    for root in candidates:
        cand = _root_to_markdown(root)
        if len(cand.strip()) > len(markdown.strip()):
            markdown = cand

    if not markdown.strip():
        # Last resort: full text dump from <body> (or whole doc) — a shell still
        # yields ~0 chars here, so the density gate keeps blocking it.
        fallback_root = body if body is not None else soup
        markdown = fallback_root.get_text(separator="\n", strip=True)

    return markdown, _trafilatura_note


# ---------------------------------------------------------------------------
# Content validation (A1)
# ---------------------------------------------------------------------------

def _validate_body(body: str, *, is_manual: bool = False) -> tuple[bool, str]:
    """Validate a fetched or manual body before writing captured_to_raw.

    Returns (ok, failure_reason). ok=True means the body passes all checks.

    Checks applied (fetched bodies):
      - Byte floor: body below _BODY_MIN_BYTES always fails (manual included).
      - Rich-prose accept: a body whose extracted prose is at/above _PROSE_OK_CHARS
        is ACCEPTED before any captcha/density gate runs — a real bot-wall REPLACES
        the article with a short challenge page, so a content-rich body cannot be a
        wall (its captcha/challenge words are page chrome, e.g. Wikipedia's
        logged-out signup UI carries the word "Captcha"). This is the content-gate
        that prevents the substring scan from false-blocking legitimate articles.
      - CAPTCHA / bot-wall fingerprints: applied ONLY when prose is thin
        (< _PROSE_OK_CHARS), for fetched (not manual) bodies.
      - Article-body density: applied ONLY when prose is thin, for fetched bodies.
        Two complementary gates: an absolute prose floor (_PROSE_MIN_CHARS) catches
        near-zero-prose shells regardless of size; a size-gated prose/body RATIO
        floor (_DENSITY_MIN_RATIO, applied only at/above _DENSITY_RATIO_BODY_BYTES)
        catches a large shell whose stray visible text clears the absolute floor.
    Manual bodies are exempt from captcha + density (only the byte floor applies).
    """
    body_bytes = len(body.encode("utf-8"))
    if body_bytes < _BODY_MIN_BYTES:
        return False, (
            f"body_too_small: {body_bytes} bytes < {_BODY_MIN_BYTES} byte floor"
        )

    if is_manual:
        # Manual-file: user already vetted; only byte floor applies.
        return True, ""

    # Extract prose FIRST — it is the signal both the rich-prose accept and the
    # density gates key on, and it gates the captcha scan.
    prose, _ = _extract_article_markdown(body)
    prose_chars = len(prose.strip())

    # Rich-prose accept: a content-rich body IS a genuine capture, regardless of
    # captcha/challenge words or markup volume. A real bot-wall replaces the
    # article with a short challenge; it never ships substantial article prose.
    # This MUST precede the captcha and density gates so a legitimate article
    # whose chrome contains a challenge word (Wikipedia "Captcha" signup UI) is
    # never false-blocked.
    if prose_chars >= _PROSE_OK_CHARS:
        return True, ""

    # Thin prose only — the body is short enough that a challenge page or a
    # contentless shell is plausible. Apply the captcha and density gates here.

    # CAPTCHA / bot-wall fingerprint scan (thin-prose path only).
    m = _CAPTCHA_RE.search(body)
    if m:
        matched = m.group(0)[:60].replace("\n", " ")
        return False, f"captcha_or_bot_wall: interstitial marker detected: {matched!r}"

    # Density Gate 1 — absolute prose floor (any body size): catches pure JS
    # shells / Next.js fragment soup that extract ~0 prose.
    if prose_chars < _PROSE_MIN_CHARS:
        return False, (
            f"low_content_density: extracted prose {prose_chars} chars < "
            f"{_PROSE_MIN_CHARS} minimum; body is likely a JS shell or landing page"
        )

    # Density Gate 2 — prose/body ratio floor for LARGE bodies: catches a big
    # contentless shell whose stray visible text (Loading splash, cookie banner,
    # nav chrome) clears the absolute floor but is dwarfed by markup. Only reached
    # on thin prose (< _PROSE_OK_CHARS), so a real article that extracted
    # substantial prose alongside a large hydration payload already returned above.
    if body_bytes >= _DENSITY_RATIO_BODY_BYTES:
        ratio = prose_chars / body_bytes
        if ratio < _DENSITY_MIN_RATIO:
            return False, (
                f"low_content_density: prose/body ratio {ratio:.5f} < "
                f"{_DENSITY_MIN_RATIO} on a {body_bytes}-byte body "
                f"({prose_chars} prose chars); body is likely a large JS shell "
                "or landing page with negligible article content"
            )

    return True, ""


# ---------------------------------------------------------------------------
# Date-parse hardening (A2)
# ---------------------------------------------------------------------------

# Implausible year sentinels: year 0000, year 9999, pre-1800 dates.
_DATE_MIN_YEAR = 1800
_DATE_MAX_YEAR = 2200


def _parse_published_date(raw: object) -> Optional[str]:
    """Defensive lenient published-date parser. Returns ISO date string or None.

    Accepts: a date object, an ISO 'YYYY-MM-DD' string, or common variants.
    Returns None on malformed, empty, implausible (year outside
    [_DATE_MIN_YEAR, _DATE_MAX_YEAR]), or absent input — never raises.

    NOT called by capture() in this tool: capture writes raw article prose with
    no frontmatter and never emits a published: field, so there is no date to
    parse at this layer. This utility exists for the ingest stage, where a
    source's published: value is read into wiki frontmatter — the place where a
    malformed value such as 0000-12-31 actually crashes. Keep it here as the
    shared, tested implementation; wire it at the ingest date-read site.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, date):
        if _DATE_MIN_YEAR <= raw.year <= _DATE_MAX_YEAR:
            return raw.isoformat()
        return None
    s = str(raw).strip()
    if not s:
        return None
    # Try ISO YYYY-MM-DD first.
    try:
        d = date.fromisoformat(s[:10])
        if _DATE_MIN_YEAR <= d.year <= _DATE_MAX_YEAR:
            return d.isoformat()
        return None
    except (ValueError, IndexError):
        pass
    return None


# ---------------------------------------------------------------------------
# Vault-root resolution
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
    raise FileNotFoundError(
        "sb-os.json not found in any ancestor of: " + str(start)
    )


def _wiki_root(vault_root: Path) -> Path:
    cfg = json.loads((vault_root / "sb-os.json").read_text(encoding="utf-8"))
    rel = cfg.get("wiki_root", "3-resources/knowledge-base")
    return vault_root / rel


# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower().strip()).strip("-")[:80]


def _filename(title: str, url: str, ext: str) -> str:
    today = date.today().isoformat()
    slug = _slugify(title) if title else _slugify(url.split("//")[-1])
    return f"{today}-{slug}.{ext}"


# ---------------------------------------------------------------------------
# Manual PDF capture (Raw PDF Title-Conformance)
# ---------------------------------------------------------------------------

# wiki/workflows/shared/naming-convention.md § Title-slug algorithm: lowercase;
# each run of whitespace and + / : – — becomes a single "-"; remaining
# punctuation is removed; consecutive "-" collapse. The canonical PDF filename
# is {title-slug}.pdf — NO date prefix (unlike the date-prefixed fetch-mode
# saves produced by _filename above).
_TITLE_HYPHEN_RE = re.compile(r"[\s+/:–—]+")
_TITLE_DROP_RE = re.compile(r"[^a-z0-9-]")

# Below this many extracted characters the PDF is treated as scanned/image-only
# and the --pdf-text companion is NOT written (a husk would let grep-based
# ingest verification pass on nothing).
_PDF_TEXT_MIN_CHARS = 200


def _title_slug(title: str) -> str:
    """Kebab-slug of a document title per the Raw PDF Title-Conformance rule."""
    s = _TITLE_HYPHEN_RE.sub("-", title.lower())
    s = _TITLE_DROP_RE.sub("", s)
    return re.sub(r"-{2,}", "-", s).strip("-")


def _is_pdf(path: Path) -> bool:
    """Detect a PDF by .pdf extension OR %PDF- magic bytes (mislabeled files)."""
    if path.suffix.lower() == ".pdf":
        return True
    try:
        with path.open("rb") as fh:
            return fh.read(5) == b"%PDF-"
    except OSError:
        return False


def _extract_pdf_text(src: Path) -> tuple[str, str]:
    """Return (extracted_text, error). pypdf is a lazy optional dependency."""
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return "", "pypdf is required for --pdf-text. Install it: pip install pypdf"
    try:
        reader = PdfReader(str(src))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages), ""
    except Exception as exc:
        return "", f"pypdf extraction failed: {exc}"


def _capture_manual_pdf(
    *,
    src: Path,
    url: str,
    origin: str,
    title: str,
    thesis: Optional[str],
    raw_dir: Path,
    dry_run: bool,
    pdf_text: bool,
) -> dict:
    """Binary-copy a user-fetched PDF into raw/{origin}/{title-slug}.pdf.

    Raw PDF Title-Conformance: the filename is the kebab-slug of the document's
    printed title (--title REQUIRED), no date prefix, and an existing
    {title-slug}.pdf is NEVER overwritten (duplicate raw — merge/delete via
    lint). --pdf-text writes a {title-slug}.md text companion (pypdf) so a text
    raw exists for grep-based ingest verification; transform problems are
    surfaced in the result, never fatal to the PDF capture.
    """
    if not title:
        return {
            "state": "blocked",
            "url": url,
            "origin": origin,
            "error": (
                "PDF manual capture requires --title: the raw filename MUST be "
                "the kebab-slug of the document's printed title (Raw PDF "
                'Title-Conformance). Re-run with --title "<document title>".'
            ),
        }
    slug = _title_slug(title)
    if not slug:
        return {
            "state": "blocked",
            "url": url,
            "origin": origin,
            "error": f"--title {title!r} yields an empty title-slug; pass the document's printed title.",
        }
    dest = raw_dir / f"{slug}.pdf"
    if dest.exists():
        return {
            "state": "blocked",
            "url": url,
            "origin": origin,
            "error": (
                f"collision: {dest} already exists — raw PDFs are never "
                "overwritten (duplicate raw; ingest halts, lint flags for merge/delete)."
            ),
        }
    size = src.stat().st_size
    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    result = {
        "state": "captured_to_raw" if not dry_run else "approved_for_capture",
        "url": url,
        "title": title,
        "origin": origin,
        "related_thesis": thesis,
        "saved_paths": [str(dest)],
        "bytes": size,
        "format": "pdf",
        "manual_source": str(src),
        "dry_run": dry_run,
    }
    if pdf_text:
        companion = raw_dir / f"{slug}.md"
        if companion.exists():
            result["transform_error"] = (
                f"companion exists, not overwritten: {companion}"
            )
            return result
        text, transform_error = _extract_pdf_text(src)
        if transform_error:
            result["transform_error"] = transform_error
            return result
        stripped = text.strip()
        if len(stripped) < _PDF_TEXT_MIN_CHARS:
            result["transform_warning"] = (
                f"extracted text is near-empty ({len(stripped)} chars < "
                f"{_PDF_TEXT_MIN_CHARS}) — likely a scanned/image PDF; "
                "companion NOT written"
            )
            return result
        header = (
            f"<!-- text extracted from {slug}.pdf by pypdf for grep-based "
            f"ingest verification; captured {date.today().isoformat()} "
            f"from {url} -->\n\n"
        )
        n = _save(companion, header + text, dry_run)
        result["saved_paths"].append(str(companion))
        result["bytes"] += n
    return result


# ---------------------------------------------------------------------------
# Source-queue registration (gated + blocked lifecycle states)
# ---------------------------------------------------------------------------

QUEUE_FILENAME = "source-queue.md"

_QUEUE_HEADER = """---
type: source-queue
---

# Source queue

> Open investment source-lifecycle states (`gated_pending_access`, `blocked`).
> Written by `investment_source_capture` only; surfaced and pruned by
> `sb-wiki-lint` (finance extension) — an entry is spent once its wiki source
> page exists. Delete an entry to retire the source.
"""


def _queue_has_open_entry(text: str, state: str, url: str) -> bool:
    """True if an entry with this (state, url) pair already exists."""
    for block in text.split("\n## ")[1:]:
        if block.startswith(f"{state} — ") and f"\n- url: {url}\n" in f"\n{block}\n":
            return True
    return False


def _register_queue_entry(
    queue_path: Path,
    *,
    state: str,
    title: str,
    url: str,
    origin: str,
    thesis: Optional[str],
    why: str = "",
    failure: str = "",
    dry_run: bool,
) -> dict:
    """Append a lifecycle entry to {wiki_root}/source-queue.md (dedup by state+url)."""
    manual_hint = (
        f"fetch manually and re-run the tool with "
        f"--mode manual --manual-file <path> --origin {origin}"
        f' (PDFs: add --title "<printed title>"; optional --pdf-text text companion)'
    )
    lines = [
        f"\n## {state} — {date.today().isoformat()}\n",
        f"- title: {title or '(unknown)'}\n",
        f"- url: {url}\n",
        f"- source: {origin}\n",
        f"- related_thesis: {thesis or 'none'}\n",
    ]
    if why:
        lines.append(f"- why_it_matters: {why}\n")
    if failure:
        lines.append(f"- failure: {failure}\n")
        lines.append(f"- required_user_action: Retry later, or {manual_hint}\n")
    else:
        lines.append(f"- required_user_action: {manual_hint[0].upper() + manual_hint[1:]}\n")

    queue_status = "dry-run"
    if not dry_run:
        existing = queue_path.read_text(encoding="utf-8") if queue_path.exists() else ""
        if _queue_has_open_entry(existing, state, url):
            queue_status = "already-registered"
        else:
            queue_path.parent.mkdir(parents=True, exist_ok=True)
            with queue_path.open("a", encoding="utf-8") as fh:
                if not existing:
                    fh.write(_QUEUE_HEADER)
                fh.write("".join(lines))
            queue_status = "registered"
    return {
        "queue": queue_status,
        "queue_path": str(queue_path),
    }


# ---------------------------------------------------------------------------
# Fetch (open-web only)
# ---------------------------------------------------------------------------

# Declared default UA — fair-access endpoints (e.g. SEC EDGAR) 403 blank or
# default-library UAs. Override per call with --user-agent when an endpoint
# requires a contact-bearing UA.
DEFAULT_USER_AGENT = (
    "sb-os-investment-source-capture/1.2 (+https://github.com/hlealt/sb-os)"
)


def _extract_title(body: str) -> str:
    """Return the <title> text if present, else empty string."""
    m = re.search(r"<title[^>]*>([^<]+)</title>", body, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _fetch_text(url: str, user_agent: str = DEFAULT_USER_AGENT) -> tuple[str, str]:
    """Return (body_text, page_title). Raises on HTTP error."""
    try:
        import httpx  # type: ignore
    except ImportError:
        raise ImportError(
            "httpx is required for fetch modes. "
            "Install it: pip install httpx"
        )
    resp = httpx.get(
        url,
        headers={"User-Agent": user_agent},
        follow_redirects=True,
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.text
    return body, _extract_title(body)


def _curl_fetch_text(url: str, user_agent: str = DEFAULT_USER_AGENT) -> tuple[str, str]:
    """Fetch URL via subprocess curl with the same User-Agent.

    Fallback for transport-level blocks that reject httpx's fingerprint.
    Resolves the curl binary explicitly via shutil.which — never a shell
    alias (PowerShell aliases `curl` to Invoke-WebRequest).
    Returns (body_text, page_title). Raises RuntimeError on any failure.
    """
    curl_bin = shutil.which("curl")
    if curl_bin is None:
        raise RuntimeError("curl binary not found on PATH")
    cmd = [
        curl_bin,
        "--silent",
        "--show-error",
        "--fail",
        "--location",
        "--max-time", "30",
        "--user-agent", user_agent,
        url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"curl invocation failed: {exc}")
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"curl exit {proc.returncode}: {stderr or 'no stderr'}")
    body = proc.stdout.decode("utf-8", errors="replace")
    return body, _extract_title(body)


def _save(dest: Path, content: str, dry_run: bool) -> int:
    """Write content to dest. Return byte length."""
    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    return len(content.encode("utf-8"))


# ---------------------------------------------------------------------------
# Core capture
# ---------------------------------------------------------------------------

def capture(
    *,
    url: str,
    origin: str,
    mode: str,
    title: str,
    thesis: Optional[str],
    vault_root: Path,
    dry_run: bool,
    gated: bool,
    gated_why: str,
    user_agent: str = DEFAULT_USER_AGENT,
    manual_file: Optional[Path] = None,
    curl_fallback: bool = True,
    ext: str = "md",
    pdf_text: bool = False,
) -> dict:
    """Capture a source and return a metadata summary dict.

    ``ext`` overrides the saved-file extension for the markdown-mode save and the
    manual/browser save (default "md" — byte-identical to legacy behavior).
    Used to capture XBRL companyfacts JSON data artifacts as ``.json``.
    The html-archive ``.html`` save is unaffected by ``ext`` (by design)."""
    wiki = _wiki_root(vault_root)
    raw_dir = wiki / "raw" / origin
    queue_path = wiki / QUEUE_FILENAME

    # Gated path — register only, no fetch
    if gated:
        queue = _register_queue_entry(
            queue_path,
            state="gated_pending_access",
            title=title,
            url=url,
            origin=origin,
            thesis=thesis,
            why=gated_why,
            dry_run=dry_run,
        )
        return {
            "state": "gated_pending_access",
            "url": url,
            "origin": origin,
            "related_thesis": thesis,
            "dry_run": dry_run,
            **queue,
        }

    # Open-web fetch — httpx first; on transport-level failure retry once via
    # subprocess curl with the same UA (unless disabled). state=blocked only
    # after BOTH methods fail.
    if mode in ("markdown", "html-archive", "both"):
        fetch_method = "httpx"
        try:
            body, page_title = _fetch_text(url, user_agent)
        except Exception as exc:
            if not curl_fallback:
                queue = _register_queue_entry(
                    queue_path,
                    state="blocked",
                    title=title,
                    url=url,
                    origin=origin,
                    thesis=thesis,
                    failure=str(exc),
                    dry_run=dry_run,
                )
                return {
                    "state": "blocked",
                    "url": url,
                    "origin": origin,
                    "error": str(exc),
                    **queue,
                }
            try:
                body, page_title = _curl_fetch_text(url, user_agent)
                fetch_method = "curl-fallback"
            except Exception as curl_exc:
                error = f"httpx: {exc}; curl-fallback: {curl_exc}"
                queue = _register_queue_entry(
                    queue_path,
                    state="blocked",
                    title=title,
                    url=url,
                    origin=origin,
                    thesis=thesis,
                    failure=error,
                    dry_run=dry_run,
                )
                return {
                    "state": "blocked",
                    "url": url,
                    "origin": origin,
                    "error": error,
                    **queue,
                }
        resolved_title = title or page_title or url
        saved = []
        total_bytes = 0

        # A1 — content-validation before writing captured_to_raw.
        ok, failure_reason = _validate_body(body, is_manual=False)
        if not ok:
            queue = _register_queue_entry(
                queue_path,
                state="blocked",
                title=resolved_title,
                url=url,
                origin=origin,
                thesis=thesis,
                failure=failure_reason,
                dry_run=dry_run,
            )
            return {
                "state": "blocked",
                "url": url,
                "title": resolved_title,
                "origin": origin,
                "error": failure_reason,
                "failure_reason": failure_reason,
                "fetch_method": fetch_method,
                **queue,
            }

        extraction_note: str = ""
        sidecars: list[str] = []
        if mode in ("markdown", "both"):
            # A2 — extract article body; full HTML preserved as sidecar.
            article_md, extraction_note = _extract_article_markdown(body)
            fname = _filename(resolved_title, url, ext)
            dest = raw_dir / fname
            n = _save(dest, article_md, dry_run)
            saved.append(str(dest))
            total_bytes += n
            # Full-page sidecar (archival/fallback); keyed separately so
            # saved_paths retains the same length as before A2.
            sidecar_path = raw_dir / _filename(resolved_title, url, "full.html")
            ns = _save(sidecar_path, body, dry_run)
            sidecars.append(str(sidecar_path))
            total_bytes += ns

        if mode in ("html-archive", "both"):
            fname = _filename(resolved_title, url, "html")
            dest = raw_dir / fname
            n = _save(dest, body, dry_run)
            saved.append(str(dest))
            total_bytes += n

        result: dict = {
            "state": "captured_to_raw" if not dry_run else "approved_for_capture",
            "url": url,
            "title": resolved_title,
            "origin": origin,
            "related_thesis": thesis,
            "saved_paths": saved,
            "bytes": total_bytes,
            "fetch_method": fetch_method,
            "dry_run": dry_run,
        }
        if sidecars:
            result["sidecar_paths"] = sidecars
        if extraction_note:
            result["extraction_note"] = extraction_note
        return result

    # Manual path — no fetch; the user already retrieved the content
    if mode in ("browser", "manual"):
        if manual_file is None:
            return {
                "state": "blocked",
                "url": url,
                "origin": origin,
                "error": (
                    f"mode={mode!r} requires --manual-file. "
                    "Fetch the page manually and re-run with "
                    f"--mode {mode} --manual-file <path>."
                ),
            }
        src = Path(manual_file)
        if not src.is_file():
            return {
                "state": "blocked",
                "url": url,
                "origin": origin,
                "error": f"--manual-file not found: {src}",
            }
        if _is_pdf(src):
            return _capture_manual_pdf(
                src=src,
                url=url,
                origin=origin,
                title=title,
                thesis=thesis,
                raw_dir=raw_dir,
                dry_run=dry_run,
                pdf_text=pdf_text,
            )
        body = src.read_text(encoding="utf-8")
        resolved_title = title or _extract_title(body) or url
        # A1 — byte floor only for manual paths (user already vetted content).
        ok, failure_reason = _validate_body(body, is_manual=True)
        if not ok:
            return {
                "state": "blocked",
                "url": url,
                "title": resolved_title,
                "origin": origin,
                "error": failure_reason,
                "failure_reason": failure_reason,
                "manual_source": str(src),
            }
        fname = _filename(resolved_title, url, ext)
        dest = raw_dir / fname
        n = _save(dest, body, dry_run)
        result = {
            "state": "captured_to_raw" if not dry_run else "approved_for_capture",
            "url": url,
            "title": resolved_title,
            "origin": origin,
            "related_thesis": thesis,
            "saved_paths": [str(dest)],
            "bytes": n,
            "manual_source": str(src),
            "dry_run": dry_run,
        }
        if pdf_text:
            result["pdf_text"] = "ignored (manual file is not a PDF)"
        return result

    return {
        "state": "blocked",
        "url": url,
        "origin": origin,
        "error": f"Unknown mode: {mode!r}",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Capture an approved URL into {wiki_root}/raw/{origin}/."
    )
    p.add_argument("--url", required=True, help="URL to capture")
    p.add_argument("--origin", required=True, help="Destination origin folder name")
    p.add_argument(
        "--mode",
        default="markdown",
        choices=["markdown", "html-archive", "both", "browser", "manual"],
    )
    p.add_argument("--title", default="", help="Override page title for filename slug")
    p.add_argument("--thesis", default=None, help="Related thesis slug (optional)")
    p.add_argument("--vault-root", default=None, help="Path to vault root (auto-detected if omitted)")
    p.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="User-Agent header for fetch modes (use a contact-bearing UA for fair-access endpoints like SEC EDGAR)",
    )
    p.add_argument(
        "--manual-file",
        default=None,
        help=(
            "Path to user-fetched content (required by --mode browser|manual; no fetch performed). "
            "Paths with Unicode characters (curly quotes, spaces, accented letters) MUST be "
            "literal-quoted: PowerShell single-quote: --manual-file '“Weird Title”.html'; "
            "bash single-quote: --manual-file '‘Weird’.html'. "
            "Pass '-' to read content from stdin (--title MUST be supplied)."
        ),
    )
    p.add_argument(
        "--no-curl-fallback",
        action="store_true",
        help="Disable the subprocess-curl retry on transport-level fetch failure (fallback is ON by default)",
    )
    p.add_argument("--dry-run", action="store_true", help="Report what would be saved; write nothing")
    p.add_argument(
        "--ext",
        default="md",
        choices=["md", "html", "json"],
        help="Saved-file extension override for markdown/manual/browser saves "
             "(default md; use json for XBRL companyfacts data artifacts). "
             "Does not affect html-archive/both .html output.",
    )
    p.add_argument(
        "--pdf-text",
        action="store_true",
        help="For a PDF --manual-file: also write a {title-slug}.md text companion "
             "extracted via pypdf (optional dependency) beside the PDF, for "
             "grep-based ingest verification. Ignored for non-PDF captures.",
    )
    p.add_argument("--gated", action="store_true", help="Declare source gated (no fetch; register only)")
    p.add_argument("--gated-why", default="(not specified)", help="Why this source matters (for source-queue.md)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        if args.vault_root:
            vault_root = Path(args.vault_root).resolve()
        else:
            vault_root = _find_vault_root(Path(__file__))
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # A3 — stdin mode: --manual-file - reads content from stdin, writes to a
    # temp file, then proceeds as a normal manual capture. Allows piping content
    # from tools that cannot produce a literal-path argument.
    manual_file_path: Optional[Path] = None
    _stdin_tmp: Optional[Path] = None
    if args.manual_file:
        if args.manual_file == "-":
            if not args.title:
                print(
                    "ERROR: --manual-file - (stdin) requires --title to derive the filename.",
                    file=sys.stderr,
                )
                return 1
            import tempfile
            content = sys.stdin.read()
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8"
            )
            tmp.write(content)
            tmp.close()
            _stdin_tmp = Path(tmp.name)
            manual_file_path = _stdin_tmp
        else:
            manual_file_path = Path(args.manual_file)

    result = capture(
        url=args.url,
        origin=args.origin,
        mode=args.mode,
        title=args.title,
        thesis=args.thesis,
        vault_root=vault_root,
        dry_run=args.dry_run,
        gated=args.gated,
        gated_why=args.gated_why,
        user_agent=args.user_agent,
        manual_file=manual_file_path,
        curl_fallback=not args.no_curl_fallback,
        ext=args.ext,
        pdf_text=args.pdf_text,
    )

    # Clean up stdin temp file if used.
    if _stdin_tmp and _stdin_tmp.exists():
        try:
            _stdin_tmp.unlink()
        except OSError:
            pass

    # Print metadata summary only — never the fetched content
    print(json.dumps(result, indent=2))

    state = result.get("state", "blocked")
    return 0 if state in ("captured_to_raw", "approved_for_capture", "gated_pending_access") else 1


if __name__ == "__main__":
    sys.exit(main())
