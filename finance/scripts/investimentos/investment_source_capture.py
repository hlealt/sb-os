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
        [--dry-run]

Returns a metadata summary only — never dumps fetched text into stdout.
Honors the 6-state source lifecycle:
    rejected | approved_for_capture | captured_to_raw | ingested_to_wiki
    | gated_pending_access | blocked

Gated sources (paywall / login required) are NOT fetched — they are registered
as gated_pending_access in {origin}/log.md. Pass --gated to declare a source
gated.

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
# Gated registration
# ---------------------------------------------------------------------------

def _register_gated(
    log_path: Path,
    *,
    title: str,
    url: str,
    origin: str,
    thesis: Optional[str],
    why: str,
    dry_run: bool,
) -> dict:
    entry = (
        f"\n## gated_pending_access — {date.today().isoformat()}\n"
        f"- title: {title or '(unknown)'}\n"
        f"- url: {url}\n"
        f"- source: {origin}\n"
        f"- related_thesis: {thesis or 'none'}\n"
        f"- why_it_matters: {why}\n"
        f"- required_user_action: Fetch manually and place in raw/{origin}/\n"
    )
    if not dry_run:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(entry)
    return {
        "state": "gated_pending_access",
        "url": url,
        "origin": origin,
        "related_thesis": thesis,
        "log_path": str(log_path),
        "dry_run": dry_run,
    }


# ---------------------------------------------------------------------------
# Fetch (open-web only)
# ---------------------------------------------------------------------------

# Declared default UA — fair-access endpoints (e.g. SEC EDGAR) 403 blank or
# default-library UAs. Override per call with --user-agent when an endpoint
# requires a contact-bearing UA.
DEFAULT_USER_AGENT = (
    "sb-os-investment-source-capture/1.1 (+https://github.com/hlealt/sb-os)"
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
) -> dict:
    """Capture a source and return a metadata summary dict."""
    wiki = _wiki_root(vault_root)
    raw_dir = wiki / "raw" / origin
    log_path = raw_dir / "log.md"

    # Gated path — register only, no fetch
    if gated:
        return _register_gated(
            log_path,
            title=title,
            url=url,
            origin=origin,
            thesis=thesis,
            why=gated_why,
            dry_run=dry_run,
        )

    # Open-web fetch — httpx first; on transport-level failure retry once via
    # subprocess curl with the same UA (unless disabled). state=blocked only
    # after BOTH methods fail.
    if mode in ("markdown", "html-archive", "both"):
        fetch_method = "httpx"
        try:
            body, page_title = _fetch_text(url, user_agent)
        except Exception as exc:
            if not curl_fallback:
                return {
                    "state": "blocked",
                    "url": url,
                    "origin": origin,
                    "error": str(exc),
                }
            try:
                body, page_title = _curl_fetch_text(url, user_agent)
                fetch_method = "curl-fallback"
            except Exception as curl_exc:
                return {
                    "state": "blocked",
                    "url": url,
                    "origin": origin,
                    "error": f"httpx: {exc}; curl-fallback: {curl_exc}",
                }
        resolved_title = title or page_title or url
        saved = []
        total_bytes = 0

        if mode in ("markdown", "both"):
            fname = _filename(resolved_title, url, "md")
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
        body = src.read_text(encoding="utf-8")
        resolved_title = title or _extract_title(body) or url
        fname = _filename(resolved_title, url, "md")
        dest = raw_dir / fname
        n = _save(dest, body, dry_run)
        return {
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
    p.add_argument("--gated", action="store_true", help="Declare source gated (no fetch; register only)")
    p.add_argument("--gated-why", default="(not specified)", help="Why this source matters (for log.md)")
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
    )

    # Print metadata summary only — never the fetched content
    print(json.dumps(result, indent=2))

    state = result.get("state", "blocked")
    return 0 if state in ("captured_to_raw", "approved_for_capture", "gated_pending_access") else 1


if __name__ == "__main__":
    sys.exit(main())
