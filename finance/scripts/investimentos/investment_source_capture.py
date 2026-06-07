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

Returns a metadata summary only — never dumps fetched text into stdout.
Honors the 6-state source lifecycle:
    rejected | approved_for_capture | captured_to_raw | ingested_to_wiki
    | gated_pending_access | blocked

Gated sources (paywall / login required) are NOT fetched — they are registered
as gated_pending_access in {wiki_root}/source-queue.md. Pass --gated to declare
a source gated.

Source-queue registration (§10 source-lifecycle): gated registrations AND
transport-level blocked outcomes (fetch failed after the curl fallback, or
with the fallback disabled) append an H2 entry to {wiki_root}/source-queue.md
— the investment source queue that sb-wiki-lint (finance extension) surfaces
and prunes. The file is created with `type: source-queue` frontmatter when
absent. The same (state, url) pair never registers twice. Usage-error blocked
results (missing --manual-file, unknown mode) and dry-run register NOTHING.

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
    markdown      — GET URL, save response body as .md  (default)
    html-archive  — GET URL, save response body as .html
    both          — save as .md AND .html
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

        if mode in ("markdown", "both"):
            fname = _filename(resolved_title, url, ext)
            dest = raw_dir / fname
            n = _save(dest, body, dry_run)
            saved.append(str(dest))
            total_bytes += n

        if mode in ("html-archive", "both"):
            fname = _filename(resolved_title, url, "html")
            dest = raw_dir / fname
            n = _save(dest, body, dry_run)
            saved.append(str(dest))
            total_bytes += n

        return {
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
        help="Path to user-fetched content (required by --mode browser|manual; no fetch performed)",
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
        manual_file=Path(args.manual_file) if args.manual_file else None,
        curl_fallback=not args.no_curl_fallback,
        ext=args.ext,
        pdf_text=args.pdf_text,
    )

    # Print metadata summary only — never the fetched content
    print(json.dumps(result, indent=2))

    state = result.get("state", "blocked")
    return 0 if state in ("captured_to_raw", "approved_for_capture", "gated_pending_access") else 1


if __name__ == "__main__":
    sys.exit(main())
