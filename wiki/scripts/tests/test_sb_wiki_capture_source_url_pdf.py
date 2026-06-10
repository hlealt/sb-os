"""Tests for the URL-fetched PDF path (2026-06-09 false-success capture fix).

Defect (filed 2026-06-09, F30 §10 re-run): a PDF fetched via ``--url`` was
decoded as text, dumped through the HTML extractor (whose ``get_text`` returns
the raw PDF stream as "prose"), passed the content-validation rich-prose-accept
gate, and was written verbatim into a ``.md`` marked ``captured_to_raw`` with
zero real prose — a FALSE SUCCESS. ``--pdf-text`` was silently ignored on the
URL branch (only the manual path honored it).

Contracted behavior (mirrors the manual PDF path): a PDF detected on the URL
fetch (``application/pdf`` content-type OR ``%PDF-`` magic bytes) is BINARY-saved
to ``raw/{origin}/{title-slug}.pdf`` (NEVER a ``.md``); ``--pdf-text`` writes a
``{title-slug}.md`` pypdf companion; ``--title`` is REQUIRED (missing → clean
``blocked``); never a binary-in-``.md`` false success.

HTTP is mocked via unittest.mock. No live network fetch is performed here — the
live fidelity-floor exercise on real PDF URLs lives in the done-gate evidence.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import the tool by file path. Reuse the module if a sibling test already
# loaded it (shared sys.modules key — re-loading would break sibling patches).
# ---------------------------------------------------------------------------
_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_MOD_KEY = "sb_wiki_capture_source"
if _MOD_KEY in sys.modules:
    _mod = sys.modules[_MOD_KEY]
else:
    _MOD_PATH = _SCRIPTS_DIR / "sb-wiki-capture-source.py"
    _spec = importlib.util.spec_from_file_location(_MOD_KEY, _MOD_PATH)
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_MOD_KEY] = _mod
    _spec.loader.exec_module(_mod)  # type: ignore

capture = _mod.capture
main = _mod.main


# ---------------------------------------------------------------------------
# Ligature normalization: pypdf extracts academic-font ligatures (ﬀ ﬁ ﬂ ﬃ ﬄ)
# as their single Unicode codepoint. They are the "garble" in the 2026-06-09
# F30 Fed/Wharton PDFs (e.g. "Staﬀ", "Aﬀairs"). Normalize them to ASCII so the
# text raw is clean and grep-able.
# ---------------------------------------------------------------------------

def test_normalize_pdf_text_expands_latin_ligatures():
    norm = _mod._normalize_pdf_text
    assert norm("Staﬀ working papers and Monetary Aﬀairs") == \
        "Staff working papers and Monetary Affairs"
    assert norm("the ﬁle and the ﬂow") == "the file and the flow"
    assert norm("eﬃcient and shuﬄe") == "efficient and shuffle"


def test_normalize_pdf_text_leaves_clean_text_unchanged():
    norm = _mod._normalize_pdf_text
    clean = "When Benchmarks Fail: Negative Oil Prices in 2020."
    assert norm(clean) == clean


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vault(tmp_path: Path) -> Path:
    wiki_rel = "knowledge-base"
    cfg = {"wiki_root": wiki_rel}
    (tmp_path / "sb-os.json").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / wiki_rel / "raw").mkdir(parents=True)
    return tmp_path


# A realistic PDF body: a real %PDF- header + binary marker bytes + enough
# readable ASCII that the LEGACY HTML extractor would dump >= _PROSE_OK_CHARS
# "prose" and false-accept it as captured_to_raw .md. This is the exact
# fingerprint the gate missed — large binary PDF whose stray text clears the
# rich-prose floor.
_PDF_BODY_TEXT = ("Flights to safety in sovereign debt markets. " * 24).encode("latin-1")
_PDF_BYTES = b"%PDF-1.6\n%\xe2\xe3\xcf\xd3\n" + _PDF_BODY_TEXT + b"\n%%EOF\n"


def _mock_pdf_response(pdf_bytes: bytes = _PDF_BYTES,
                       content_type: str = "application/pdf") -> MagicMock:
    """A mocked httpx response carrying a PDF body (bytes + decoded text + ctype)."""
    resp = MagicMock()
    resp.content = pdf_bytes
    resp.text = pdf_bytes.decode("latin-1")
    resp.headers = {"content-type": content_type}
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# Core defect guard: URL PDF + --pdf-text saves .pdf + .md companion,
# NEVER the binary dumped into a .md.
# ---------------------------------------------------------------------------

def test_url_pdf_with_pdf_text_saves_pdf_and_text_companion(tmp_path):
    vault = _make_vault(tmp_path)
    extracted = "Flights to safety and the credit ratings of sovereign debt. " * 8
    resp = _mock_pdf_response()

    with patch("httpx.get", return_value=resp), \
         patch("sb_wiki_capture_source._extract_pdf_text", return_value=(extracted, "")):
        result = capture(
            url="https://www.federalreserve.gov/econres/feds/files/2014046pap.pdf",
            origin="federal-reserve",
            mode="markdown",
            title="Flights to Safety FEDS 2014-46",
            thesis="quality-crisis-resilience",
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
            pdf_text=True,
        )

    assert result["state"] == "captured_to_raw", f"URL PDF must capture; got {result}"
    assert result.get("format") == "pdf", "URL PDF must be marked format=pdf"

    saved = [Path(p) for p in result["saved_paths"]]
    pdfs = [p for p in saved if p.suffix == ".pdf"]
    mds = [p for p in saved if p.suffix == ".md"]
    assert len(pdfs) == 1, f"exactly one .pdf must be saved; got {saved}"
    assert len(mds) == 1, f"--pdf-text must write one .md companion; got {saved}"

    pdf_path, md_path = pdfs[0], mds[0]
    # The .pdf is byte-identical to the fetched bytes (real binary saved, not text).
    assert pdf_path.read_bytes() == _PDF_BYTES
    assert pdf_path.name == "flights-to-safety-feds-2014-46.pdf"
    # The .md companion is the EXTRACTED TEXT — never the raw PDF binary dump.
    md_text = md_path.read_text(encoding="utf-8")
    assert extracted.strip()[:40] in md_text
    assert "%PDF-" not in md_text, "the .md companion must not hold the raw PDF binary"


def test_url_pdf_never_dumps_binary_into_md(tmp_path):
    """The defect guard: NO .md anywhere in the origin holds the PDF binary."""
    vault = _make_vault(tmp_path)
    extracted = "Sovereign debt flight-to-safety analysis across crisis episodes. " * 8
    resp = _mock_pdf_response()

    with patch("httpx.get", return_value=resp), \
         patch("sb_wiki_capture_source._extract_pdf_text", return_value=(extracted, "")):
        result = capture(
            url="https://example.com/paper.pdf",
            origin="papers",
            mode="markdown",
            title="A Sovereign Debt Paper",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
            pdf_text=True,
        )

    assert result["state"] == "captured_to_raw"
    raw_dir = vault / "knowledge-base" / "raw" / "papers"
    for md in raw_dir.glob("*.md"):
        assert "%PDF-" not in md.read_text(encoding="utf-8"), \
            f"{md} contains raw PDF binary — the false-success defect"
    # No date-prefixed HTML-path artifact (the legacy false-success .md).
    assert not list(raw_dir.glob("20*-*.md")), "must not write the legacy date-prefixed .md"


def test_url_pdf_without_pdf_text_saves_pdf_only(tmp_path):
    """Parity with manual mode: a URL PDF without --pdf-text still saves the
    .pdf binary (a valid raw record), no .md companion, never a binary .md."""
    vault = _make_vault(tmp_path)
    resp = _mock_pdf_response()

    with patch("httpx.get", return_value=resp):
        result = capture(
            url="https://example.com/report.pdf",
            origin="example",
            mode="markdown",
            title="Quarterly Report",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "captured_to_raw"
    assert result.get("format") == "pdf"
    saved = [Path(p) for p in result["saved_paths"]]
    assert [p.suffix for p in saved] == [".pdf"], f"only the .pdf saved; got {saved}"
    assert saved[0].read_bytes() == _PDF_BYTES


def test_url_pdf_detected_by_magic_bytes_without_content_type(tmp_path):
    """A server that mislabels the content-type (octet-stream / missing) is still
    detected as a PDF by the %PDF- magic bytes — never false-succeeds as .md."""
    vault = _make_vault(tmp_path)
    resp = _mock_pdf_response(content_type="application/octet-stream")

    with patch("httpx.get", return_value=resp):
        result = capture(
            url="https://example.com/mislabeled-binary",
            origin="example",
            mode="markdown",
            title="Mislabeled PDF",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "captured_to_raw"
    assert result.get("format") == "pdf"
    saved = Path(result["saved_paths"][0])
    assert saved.suffix == ".pdf"
    assert saved.read_bytes() == _PDF_BYTES


def test_url_pdf_missing_title_is_blocked(tmp_path):
    """Raw PDF Title-Conformance on the URL path: no --title → clean blocked,
    NEVER a binary-in-.md false success."""
    vault = _make_vault(tmp_path)
    resp = _mock_pdf_response()

    with patch("httpx.get", return_value=resp):
        result = capture(
            url="https://example.com/untitled.pdf",
            origin="example",
            mode="markdown",
            title="",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "blocked", f"missing title must block; got {result}"
    assert "--title" in result["error"]
    raw_dir = vault / "knowledge-base" / "raw" / "example"
    assert not raw_dir.exists() or list(raw_dir.iterdir()) == [], \
        "blocked URL PDF must write nothing"


def test_url_pdf_dry_run_writes_nothing(tmp_path):
    vault = _make_vault(tmp_path)
    extracted = "Extractable sovereign debt prose for the dry run. " * 8
    resp = _mock_pdf_response()

    with patch("httpx.get", return_value=resp), \
         patch("sb_wiki_capture_source._extract_pdf_text", return_value=(extracted, "")):
        result = capture(
            url="https://example.com/dry.pdf",
            origin="example",
            mode="markdown",
            title="Dry Run PDF",
            thesis=None,
            vault_root=vault,
            dry_run=True,
            gated=False,
            gated_why="",
            pdf_text=True,
        )

    assert result["state"] == "approved_for_capture"
    raw_dir = vault / "knowledge-base" / "raw" / "example"
    assert not raw_dir.exists() or list(raw_dir.iterdir()) == [], \
        "dry-run must write neither the .pdf nor the .md companion"


def test_cli_url_pdf_with_pdf_text_end_to_end(tmp_path):
    """CLI path: --pdf-text --url <pdf> writes a .pdf + .md companion, exit 0.
    This is the research.md Step 5 worked example, now honored on the URL branch."""
    vault = _make_vault(tmp_path)
    extracted = "IMF Article IV staff report narrative content. " * 8
    resp = _mock_pdf_response()

    with patch("httpx.get", return_value=resp), \
         patch("sb_wiki_capture_source._extract_pdf_text", return_value=(extracted, "")):
        exit_code = main([
            "--url", "https://example.com/doc.pdf",
            "--origin", "imf",
            "--title", "IMF Article IV 2025",
            "--pdf-text",
            "--vault-root", str(vault),
        ])

    assert exit_code == 0
    raw_dir = vault / "knowledge-base" / "raw" / "imf"
    assert (raw_dir / "imf-article-iv-2025.pdf").exists()
    assert (raw_dir / "imf-article-iv-2025.md").exists()
