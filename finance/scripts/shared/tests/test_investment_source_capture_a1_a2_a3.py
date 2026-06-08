"""Tests for A1/A2/A3 hardening of investment_source_capture (2026-06-08).

Items covered:
  A1 — content-validation before returning captured_to_raw:
       CAPTCHA/bot-wall bodies, 0-byte bodies, large-but-contentless JS-shell
       bodies return state=blocked + source-queue row with failure_reason.
       A normal article body still returns captured_to_raw.

  A2 — article-body markdown extraction at capture + date-parse hardening:
       A multi-paragraph HTML fixture yields readable prose in the raw .md
       (not a raw dump); full HTML is preserved as .full.html sidecar.
       A 'published: 0000-12-31' date parses to None without raising.

  A3 — --manual-file Unicode path handling:
       A manual-mode capture of a file whose name contains Unicode characters
       (curly quotes) succeeds — no arg-parse error; exit 0.

All HTTP is mocked via unittest.mock. No live network fetch is performed.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import the tool by file path (matches pattern of existing tests).
# Guard against re-loading if already loaded by the sibling test module
# (both files register under the same sys.modules key; re-loading overwrites
# the reference and breaks patches in the sibling).
# ---------------------------------------------------------------------------
_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
_INVESTIMENTOS_DIR = _SCRIPTS_DIR.parent / "investimentos"

for _p in (_SCRIPTS_DIR, _INVESTIMENTOS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_MOD_KEY = "investment_source_capture"
if _MOD_KEY in sys.modules:
    _mod = sys.modules[_MOD_KEY]
else:
    _MOD_PATH = _INVESTIMENTOS_DIR / "investment_source_capture.py"
    _spec = importlib.util.spec_from_file_location(_MOD_KEY, _MOD_PATH)
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_MOD_KEY] = _mod
    _spec.loader.exec_module(_mod)  # type: ignore

capture = _mod.capture
main = _mod.main
_validate_body = _mod._validate_body
_parse_published_date = _mod._parse_published_date
_extract_article_markdown = _mod._extract_article_markdown


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vault(tmp_path: Path) -> Path:
    """Minimal vault with sb-os.json."""
    wiki_rel = "knowledge-base"
    cfg = {"wiki_root": wiki_rel}
    (tmp_path / "sb-os.json").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / wiki_rel / "raw").mkdir(parents=True)
    return tmp_path


def _mock_response(body: str, title_tag: str = "") -> MagicMock:
    html = f"<html><head><title>{title_tag}</title></head><body>{body}</body></html>"
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status = MagicMock()
    return resp


def _mock_article_html(*, title: str, paragraphs: list[str]) -> str:
    """Produce a realistic multi-paragraph article HTML."""
    ps = "\n".join(f"<p>{p}</p>" for p in paragraphs)
    return textwrap.dedent(f"""
        <html>
        <head><title>{title}</title></head>
        <body>
          <nav><a href="/">Home</a></nav>
          <article>
            <h1>{title}</h1>
            {ps}
          </article>
          <footer>Copyright 2026</footer>
        </body>
        </html>
    """).strip()


# ---------------------------------------------------------------------------
# A1 — content-validation: CAPTCHA / bot-wall returns state=blocked
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("captcha_body, label", [
    (
        "<html><head><title>Just a moment...</title></head>"
        "<body><p>Please wait while we verify your browser.</p></body></html>",
        "cloudflare_title",
    ),
    (
        "<html><body><p>Please complete the captcha to continue.</p></body></html>",
        "captcha_word",
    ),
    (
        "<html><body><p>Verify you are human before proceeding.</p></body></html>",
        "verify_human",
    ),
    (
        "<html><head></head><body><script>window._cf_chl_opt={cType:'managed'};</script>"
        "<p>Checking your browser before accessing the site.</p></body></html>",
        "cf_challenge_var",
    ),
])
def test_a1_captcha_body_returns_blocked(tmp_path, captcha_body, label):
    """A 200 response with CAPTCHA / bot-wall markers returns state=blocked."""
    vault = _make_vault(tmp_path)
    resp = MagicMock()
    resp.text = captcha_body
    resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=resp):
        result = capture(
            url="https://example.com/article",
            origin="example",
            mode="markdown",
            title="Article",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "blocked", f"[{label}] expected blocked, got {result}"
    assert "failure_reason" in result
    assert "captcha" in result["failure_reason"].lower() or \
           "bot_wall" in result["failure_reason"].lower() or \
           "interstitial" in result["failure_reason"].lower(), \
        f"failure_reason should name the captcha check: {result['failure_reason']!r}"
    # Must NOT write raw .md
    raw_dir = vault / "knowledge-base" / "raw" / "example"
    assert not raw_dir.exists() or list(raw_dir.glob("*.md")) == [], \
        "blocked capture must not write .md"


def test_a1_zero_byte_body_returns_blocked(tmp_path):
    """A 0-byte fetched body returns state=blocked."""
    vault = _make_vault(tmp_path)
    resp = MagicMock()
    resp.text = ""
    resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=resp):
        result = capture(
            url="https://example.com/empty",
            origin="example",
            mode="markdown",
            title="Empty Page",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "blocked"
    assert "failure_reason" in result
    assert "body_too_small" in result["failure_reason"] or \
           "captcha" in result["failure_reason"].lower() or \
           "density" in result["failure_reason"].lower()


def _nextjs_fragment_soup(*, title: str, approx_bytes: int = 380_000) -> str:
    """Build a realistic, large Next.js self.__next_f.push() fragment-soup body.

    All content lives inside <script> as escaped fragment arrays — there is no
    real article DOM. After bs4 strips <script>, near-zero prose remains. Sized
    to the ~389 KB emarketer-class shell from the A1 evidence so the test
    exercises the gate on a realistically large body, not a toy fixture.
    """
    frag = ""
    i = 0
    while len(frag) < approx_bytes:
        chunk = {"$": "L" + str(i),
                 "children": ["$", "div", None, {"className": "c" + str(i),
                                                  "data": "a" * 200}]}
        frag += "self.__next_f.push([1," + json.dumps([str(i), chunk]) + "\n])"
        i += 1
    return (
        f"<!DOCTYPE html><html><head><title>{title}</title></head>"
        f'<body><div id="__next"></div><script>{frag}</script></body></html>'
    )


def test_a1_js_shell_returns_blocked(tmp_path):
    """A large (~380 KB) Next.js fragment-soup shell returns state=blocked.

    Realistic emarketer/Next.js self.__next_f.push() page: all content inside
    <script>, body yields ~0 prose chars after extraction → absolute prose floor
    fires. This is the contracted large-but-contentless JS-shell case.
    """
    vault = _make_vault(tmp_path)
    js_shell = _nextjs_fragment_soup(title="emarketer Report")
    assert len(js_shell.encode("utf-8")) > 300_000, "fixture must be realistically large"
    resp = MagicMock()
    resp.text = js_shell
    resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=resp):
        result = capture(
            url="https://emarketer.com/report",
            origin="emarketer",
            mode="markdown",
            title="Emarketer Report",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "blocked", \
        f"JS shell should return blocked; got {result}"
    assert "low_content_density" in result["failure_reason"], \
        f"failure must name the density check: {result['failure_reason']!r}"
    # Must write a source-queue row (same path as transport-level blocked).
    assert result.get("queue") in ("registered", "already-registered"), \
        "blocked content-validation must register in source-queue"


def test_a1_large_stray_text_shell_blocked_by_ratio(tmp_path):
    """A large shell whose STRAY visible text clears the absolute prose floor is
    still blocked — by the prose/body density-ratio gate.

    This is the regression the A1 evidence named: a ~389 KB JS shell with a
    "Loading..."/cookie-banner/nav splash (a few dozen visible chars) evaded
    both the byte floor AND a too-low absolute prose floor. The ratio gate is
    what catches it.
    """
    vault = _make_vault(tmp_path)
    big_payload = json.dumps({"data": "x" * 380_000})
    stray_shell = (
        "<html><head><title>eMarketer Report</title></head><body>"
        "<header><nav>Home About Contact Subscribe Login</nav></header>"
        "<div>Loading report, please wait. Enable JavaScript to view this "
        "content. We use cookies and similar technologies to provide the best "
        "experience.</div>"
        f"<script>self.__next_f.push([1,{big_payload}])</script>"
        '<div id="__next"></div></body></html>'
    )
    body_bytes = len(stray_shell.encode("utf-8"))
    assert body_bytes > 300_000, "fixture must be realistically large"
    resp = MagicMock()
    resp.text = stray_shell
    resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=resp):
        result = capture(
            url="https://emarketer.com/stray-report",
            origin="emarketer",
            mode="markdown",
            title="Emarketer Stray Report",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "blocked", \
        f"large stray-text shell must be blocked; got {result}"
    # Specifically the RATIO gate, not the absolute floor (stray text > floor).
    assert "ratio" in result["failure_reason"], \
        f"must be caught by the density-ratio gate: {result['failure_reason']!r}"
    assert result.get("queue") in ("registered", "already-registered")


def test_a1_rich_article_with_captcha_word_in_chrome_passes(tmp_path):
    """REGRESSION (2026-06-08 owner smoke gate): a content-rich legitimate article
    whose page CHROME contains the word "captcha" must CAPTURE — not be blocked.

    Real case: Wikipedia's logged-out HTML chrome (signup/account UI) carries the
    word "Captcha"; the live ETF article (40 KB of extractable prose) was
    FALSE-BLOCKED by the bare-substring captcha scan running before extraction.
    The fix content-gates the captcha/density blocks behind the rich-prose accept:
    a body with prose >= _PROSE_OK_CHARS is a genuine capture regardless of any
    captcha word in chrome, because a real bot-wall REPLACES the article with a
    short challenge — it never ships substantial article prose. This pins that
    behavior so a future marker/ordering change cannot reintroduce the false block.
    """
    vault = _make_vault(tmp_path)
    # Wikipedia-style logged-out chrome containing the word "Captcha".
    chrome = (
        "<header><nav>Main page Contents Current events</nav>"
        "<div id='p-personal'>Create account Log in</div>"
        "<div id='wpCaptcha' class='captcha'>Captcha: please enter the "
        "characters you see (anti-spam check for account creation).</div>"
        "</header>"
    )
    paras = [
        "An exchange-traded fund is a type of investment fund and exchange-traded "
        "product, that is, it is traded on stock exchanges throughout the day.",
        "ETFs hold assets such as stocks, bonds, currencies, debts, futures "
        "contracts, and commodities, and generally track an underlying index.",
        "Unlike mutual funds, ETF shares trade at market price, which may differ "
        "from net asset value, and can be bought and sold like ordinary shares.",
        "The first ETF was created in 1990 in Canada, and the structure has since "
        "grown into one of the largest categories of pooled investment products.",
    ]
    article = "<article><h1>Exchange-traded fund</h1>" + \
        "".join(f"<p>{p}</p>" for p in paras) + "</article>"
    body = (
        "<!DOCTYPE html><html><head><title>Exchange-traded fund - Wikipedia</title>"
        "</head><body>" + chrome + article +
        "<footer>This page was last edited recently.</footer></body></html>"
    )
    # Sanity: chrome carries the captcha word; article carries rich prose.
    assert "Captcha" in body
    resp = MagicMock()
    resp.text = body
    resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=resp):
        result = capture(
            url="https://en.wikipedia.org/wiki/Exchange-traded_fund",
            origin="wikipedia",
            mode="markdown",
            title="Exchange-traded fund",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "captured_to_raw", \
        f"rich article with 'captcha' in chrome must capture, not block; got {result}"
    raw_md = Path(result["saved_paths"][0])
    content = raw_md.read_text(encoding="utf-8")
    # Saved raw is clean article prose, not the raw HTML dump.
    assert "An exchange-traded fund is a type of investment fund" in content
    assert "<html>" not in content and "<script>" not in content


def test_a1_realistic_wrapped_short_article_passes(tmp_path):
    """A genuine short article wrapped in realistic page chrome (head/meta/CSS,
    nav, footer) still captures — the density gates must NOT false-block it.

    Guards the A1 contract's "WITHOUT false-blocking a genuine short article":
    even a terse multi-sentence news item buried in heavy inline-CSS chrome
    sits far above the ratio floor once it has real paragraphs.
    """
    vault = _make_vault(tmp_path)
    style = "<style>" + (".cls{color:#fff;background:#000;padding:4px} " * 250) + "</style>"
    nav = "<nav>" + ("Section link " * 60) + "</nav>"
    footer = "<footer>" + ("footer link " * 80) + "</footer>"
    para = (
        "<p>U.S. equities fell sharply on Thursday as investors weighed the "
        "prospect of higher interest rates for longer, with technology shares "
        "leading the decline amid renewed inflation concerns.</p>"
    )
    wrapped = (
        f"<!DOCTYPE html><html><head><title>Markets tumble</title>{style}</head>"
        f"<body><header>{nav}</header>"
        f"<article><h1>Markets tumble on rate fears</h1>{para * 3}</article>"
        f"{footer}</body></html>"
    )
    assert len(wrapped.encode("utf-8")) > 5000, "fixture must carry heavy chrome"
    resp = MagicMock()
    resp.text = wrapped
    resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=resp):
        result = capture(
            url="https://news.example.com/markets-tumble",
            origin="news",
            mode="markdown",
            title="Markets tumble on rate fears",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "captured_to_raw", \
        f"realistic wrapped short article must NOT be density-blocked; got {result}"
    raw_md = Path(result["saved_paths"][0])
    content = raw_md.read_text(encoding="utf-8")
    assert "U.S. equities fell sharply" in content


def test_a1_genuine_multi_mb_article_with_hydration_soup_passes(tmp_path):
    """A genuine ~2 MB page that server-renders a real article alongside a large
    Next.js client-hydration payload must CAPTURE — not be density-blocked.

    This pins the interaction between A1 (density ratio gate) and A2 (extraction):
    the prose/body ratio is tiny (~0.0002, the soup dwarfs the article), but bs4
    extracts the real article cleanly, so the substantial-prose ceiling skips the
    ratio gate. Regression guard: a future ratio tweak must not re-block real
    multi-MB articles. The .md is clean prose; the soup is discarded.
    """
    vault = _make_vault(tmp_path)
    paras = [
        "Healthcare spending in the United States reached a new high in 2025, "
        "driven by an aging population and rising prescription drug costs.",
        "Adults aged 55 and over now account for the largest share of total "
        "expenditures, according to the latest federal data.",
        "Analysts expect the trend to accelerate as the baby-boomer cohort "
        "moves further into retirement age.",
        "Policymakers are weighing reforms to Medicare reimbursement to contain "
        "the growth in outlays.",
    ]
    article_dom = ("<article><h1>U.S. Health Spending Hits Record in 2025</h1>"
                   + "".join(f"<p>{p}</p>" for p in paras) + "</article>")
    soup = ""
    i = 0
    while len(soup) < 2_000_000:
        soup += ("self.__next_f.push([1,"
                 + json.dumps([str(i), {"$": "L" + str(i), "data": "z" * 300}]) + "])")
        i += 1
    body = (
        "<!DOCTYPE html><html><head><title>Health Spending</title>"
        "<style>" + (".a{b:c} " * 500) + "</style></head>"
        "<body><nav>" + ("Menu " * 100) + "</nav>"
        + article_dom + "<script>" + soup + "</script>"
        "<footer>" + ("foot " * 200) + "</footer></body></html>"
    ).replace("\n", "")
    assert len(body.encode("utf-8")) > 1_500_000, "fixture must be multi-MB"
    resp = MagicMock()
    resp.text = body
    resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=resp):
        result = capture(
            url="https://news.example.com/health-spending-2025",
            origin="news",
            mode="markdown",
            title="U.S. Health Spending Hits Record in 2025",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "captured_to_raw", \
        f"genuine multi-MB article must capture (not be density-blocked); got {result}"
    raw_md = Path(result["saved_paths"][0])
    content = raw_md.read_text(encoding="utf-8")
    # Clean prose: every paragraph present, none of the soup/markup leaked.
    assert all(p[:40] in content for p in paras)
    assert "__next_f" not in content
    assert "<script>" not in content
    assert "<html>" not in content


def test_a1_blocked_writes_source_queue_row(tmp_path):
    """A1 blocked capture writes a source-queue entry with failure_reason."""
    vault = _make_vault(tmp_path)
    resp = MagicMock()
    resp.text = ""   # 0-byte body
    resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=resp):
        result = capture(
            url="https://example.com/captcha-page",
            origin="example",
            mode="markdown",
            title="Captcha Page",
            thesis="my-thesis",
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "blocked"
    assert result.get("queue") == "registered"
    queue_path = Path(result["queue_path"])
    assert queue_path.exists()
    content = queue_path.read_text(encoding="utf-8")
    assert "## blocked — " in content
    assert "- url: https://example.com/captcha-page" in content
    # Failure reason recorded.
    assert "- failure: " in content


def test_a1_normal_article_still_captured(tmp_path):
    """A normal article body returns captured_to_raw (not blocked)."""
    vault = _make_vault(tmp_path)
    article = _mock_article_html(
        title="Global Economy Outlook 2026",
        paragraphs=[
            "The global economy is projected to grow at 3.2% in 2026.",
            "Emerging markets continue to drive growth despite headwinds.",
            "Inflation has moderated but remains above central bank targets.",
        ],
    )
    resp = MagicMock()
    resp.text = article
    resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=resp):
        result = capture(
            url="https://news.example.com/economy-2026",
            origin="news",
            mode="markdown",
            title="Global Economy Outlook 2026",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "captured_to_raw", \
        f"Normal article should succeed; got {result}"
    assert result["saved_paths"]


def test_a1_dry_run_blocked_registers_nothing(tmp_path):
    """A dry-run blocked capture does not write source-queue.md."""
    vault = _make_vault(tmp_path)
    resp = MagicMock()
    resp.text = ""
    resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=resp):
        result = capture(
            url="https://example.com/empty",
            origin="example",
            mode="markdown",
            title="",
            thesis=None,
            vault_root=vault,
            dry_run=True,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "blocked"
    assert result.get("queue") == "dry-run"
    assert not (vault / "knowledge-base" / "source-queue.md").exists()


# ---------------------------------------------------------------------------
# A1 — manual-file paths: only byte floor applies (density exempt)
# ---------------------------------------------------------------------------

def test_a1_manual_file_large_body_not_density_blocked(tmp_path):
    """A manual file with JS-only content is NOT density-blocked (user vetted)."""
    vault = _make_vault(tmp_path)
    js_content = "<script>" + "window.__DATA__=" + json.dumps({"k": "x" * 500}) + ";</script>"
    src = tmp_path / "clip.html"
    src.write_text(js_content, encoding="utf-8")

    result = capture(
        url="https://example.com/clip",
        origin="example",
        mode="manual",
        title="JS Clip",
        thesis=None,
        vault_root=vault,
        dry_run=False,
        gated=False,
        gated_why="",
        manual_file=src,
    )

    # Manual path: density check does NOT apply — should succeed.
    assert result["state"] == "captured_to_raw", \
        f"Manual JS-only clip must not be density-blocked; got {result}"


# ---------------------------------------------------------------------------
# A2 — article extraction: multi-MB HTML → readable prose .md + .full.html
# ---------------------------------------------------------------------------

def test_a2_extraction_produces_readable_prose(tmp_path):
    """A multi-paragraph HTML fetch yields clean prose in the raw .md."""
    vault = _make_vault(tmp_path)
    paragraphs = [
        "Healthcare spending continues to rise across all age groups.",
        "Adults aged 55 and over account for the largest share of expenses.",
        "Prescription drug costs are the fastest-growing category.",
    ]
    article = _mock_article_html(
        title="Health Spending 2026",
        paragraphs=paragraphs,
    )
    resp = MagicMock()
    resp.text = article
    resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=resp):
        result = capture(
            url="https://cms.gov/health-2026",
            origin="cms",
            mode="markdown",
            title="Health Spending 2026",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "captured_to_raw"
    assert result["saved_paths"]
    raw_md = Path(result["saved_paths"][0])
    assert raw_md.exists()
    content = raw_md.read_text(encoding="utf-8")
    # Primary .md must be prose — at least one paragraph text present.
    assert any(p[:30] in content for p in paragraphs), \
        f"Extracted .md should contain article prose; got: {content[:300]!r}"
    # Must NOT be a raw single-line HTML dump.
    assert "<html>" not in content, "Primary .md must not contain raw HTML tags"
    assert "<script>" not in content


def test_a2_full_html_sidecar_written(tmp_path):
    """Full HTML body is preserved as a .full.html sidecar beside the .md."""
    vault = _make_vault(tmp_path)
    article = _mock_article_html(
        title="AI Safety Report",
        paragraphs=["AI safety research is advancing rapidly."],
    )
    resp = MagicMock()
    resp.text = article
    resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=resp):
        result = capture(
            url="https://example.com/ai-safety",
            origin="example",
            mode="markdown",
            title="AI Safety Report",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "captured_to_raw"
    # sidecar_paths must list the .full.html file.
    assert "sidecar_paths" in result, "Result must include sidecar_paths for .full.html"
    sidecar = Path(result["sidecar_paths"][0])
    assert sidecar.exists()
    assert sidecar.name.endswith(".full.html"), \
        f"Sidecar must be .full.html; got {sidecar.name!r}"
    # Full HTML sidecar retains the original HTML.
    sidecar_text = sidecar.read_text(encoding="utf-8")
    assert "<html>" in sidecar_text or "html" in sidecar_text.lower()


def test_a2_both_mode_has_sidecar_and_html_archive(tmp_path):
    """mode=both: extracted .md + .full.html sidecar + .html archive."""
    vault = _make_vault(tmp_path)
    article = _mock_article_html(
        title="Both Mode Test",
        paragraphs=["Content for both mode test."],
    )
    resp = MagicMock()
    resp.text = article
    resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=resp):
        result = capture(
            url="https://example.com/both",
            origin="example",
            mode="both",
            title="Both Mode Test",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "captured_to_raw"
    # saved_paths: article .md + html-archive .html
    saved = result["saved_paths"]
    assert any(p.endswith(".md") for p in saved), "both mode must have .md"
    assert any(p.endswith(".html") for p in saved), "both mode must have .html"
    # sidecar_paths: .full.html
    assert "sidecar_paths" in result
    assert any(p.endswith(".full.html") for p in result["sidecar_paths"])


def test_a2_dry_run_writes_nothing_including_sidecar(tmp_path):
    """dry-run: neither the .md nor the .full.html sidecar is written."""
    vault = _make_vault(tmp_path)
    article = _mock_article_html(
        title="Dry Run Article",
        paragraphs=["Some prose content here."],
    )
    resp = MagicMock()
    resp.text = article
    resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=resp):
        result = capture(
            url="https://example.com/dry",
            origin="example",
            mode="markdown",
            title="Dry Run Article",
            thesis=None,
            vault_root=vault,
            dry_run=True,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "approved_for_capture"
    raw_dir = vault / "knowledge-base" / "raw" / "example"
    assert not raw_dir.exists() or list(raw_dir.iterdir()) == [], \
        "dry-run must write nothing (no .md or .full.html)"


# ---------------------------------------------------------------------------
# A2 — date-parse hardening: implausible / malformed published: dates
# ---------------------------------------------------------------------------

def test_a2_parse_published_date_implausible_year_returns_none():
    """published: 0000-12-31 returns None — does not raise."""
    assert _parse_published_date("0000-12-31") is None


def test_a2_parse_published_date_empty_returns_none():
    """published: '' or None returns None."""
    assert _parse_published_date("") is None
    assert _parse_published_date(None) is None


def test_a2_parse_published_date_garbage_returns_none():
    """published: 'not-a-date' returns None without raising."""
    assert _parse_published_date("not-a-date") is None
    assert _parse_published_date("99999-01-01") is None


def test_a2_parse_published_date_valid_iso_passes():
    """published: '2024-03-15' parses correctly."""
    assert _parse_published_date("2024-03-15") == "2024-03-15"


def test_a2_parse_published_date_future_reasonable_year_passes():
    """published: '2026-06-08' (today-ish) parses correctly."""
    assert _parse_published_date("2026-06-08") == "2026-06-08"


# ---------------------------------------------------------------------------
# A2 — _extract_article_markdown: prose extraction unit tests
# ---------------------------------------------------------------------------

def test_a2_extract_strips_scripts_and_nav():
    """Scripts, nav, and footer are removed; article text is preserved."""
    html = (
        "<html><body>"
        "<nav>Home | About</nav>"
        "<article><h1>Title</h1><p>Article body text here.</p></article>"
        "<script>window.__DATA__={}</script>"
        "<footer>Copyright</footer>"
        "</body></html>"
    )
    prose, note = _extract_article_markdown(html)
    assert "Article body text here." in prose
    assert "window.__DATA__" not in prose
    assert "Home | About" not in prose or "Article body text here." in prose


def test_a2_extract_js_shell_yields_minimal_prose():
    """A pure JS shell with no text nodes yields near-zero prose."""
    js_shell = (
        "<html><head></head><body>"
        "<script>window.__NEXT_DATA__=" + json.dumps({"key": "x" * 2000}) + ";</script>"
        "</body></html>"
    )
    prose, _ = _extract_article_markdown(js_shell)
    assert len(prose.strip()) < _mod._PROSE_MIN_CHARS + 50, \
        f"JS shell should extract near-zero prose; got {len(prose)} chars"


def test_a2_extract_empty_wrapper_does_not_shadow_article():
    """REGRESSION (2026-06-08 owner smoke gate, r1c): a server-rendered article
    whose page carries an EMPTY higher-priority content wrapper must still extract
    the real article prose — the empty wrapper must NOT shadow it to 0 chars.

    Real case: Brazil Journal ships a bare <article> shell (0 <p>) while the
    article body lives in a sibling .post-content (28 <p>). The old first-match
    loop broke on the empty <article>, the <body> fallback never fired, and a
    168 KB content-rich article extracted 0 prose -> FALSE-BLOCKED by the density
    gate. The fix evaluates EVERY matching container plus <body> and keeps the
    richest. This pins that behavior so a future change cannot reintroduce the
    empty-wrapper short-circuit.
    """
    paras = [
        "The national grid operator faced an unprecedented and risky situation "
        "last Sunday during the continuation of the holiday weekend.",
        "With demand falling and a surplus of generation driven by rooftop solar "
        "panels, the operator had to curtail output across several regions.",
        "Analysts warned that the mismatch between supply and demand exposes a "
        "structural fragility in how distributed generation is integrated.",
        "Officials are weighing new rules to give the operator more flexibility to "
        "manage these swings without compromising grid stability.",
    ]
    # Empty <article> (higher priority) precedes the real .post-content sibling.
    body_inner = (
        "<article></article>"
        "<div class='post-content'><h1>Grid Surplus</h1>"
        + "".join(f"<p>{p}</p>" for p in paras)
        + "</div>"
    )
    html = (
        "<!DOCTYPE html><html><head><title>Grid Surplus - News</title></head>"
        "<body><nav>Home About</nav>" + body_inner
        + "<footer>Copyright</footer></body></html>"
    )
    prose, _ = _extract_article_markdown(html)
    # Real article prose extracted, not 0 — every paragraph present.
    assert all(p[:40] in prose for p in paras), \
        f"empty <article> wrapper must not shadow the real article; got: {prose[:200]!r}"
    assert len(prose.strip()) >= _mod._PROSE_OK_CHARS, \
        f"extracted prose must clear the rich-prose accept floor; got {len(prose)} chars"
    # No markup leaked.
    assert "<html>" not in prose and "<script>" not in prose


def test_a1_empty_wrapper_server_rendered_article_captures(tmp_path):
    """End-to-end (r1c): the empty-wrapper server-rendered article CAPTURES via
    capture() — state captured_to_raw, raw .md is clean article prose, not blocked.

    The full-path twin of the extraction unit test above: drives capture() with a
    mocked 200 response carrying the empty <article> + real .post-content body and
    asserts the content-validation gate ACCEPTS it (rich prose) and the saved raw
    is prose. Guards the exact owner-observed outcome: capturing such a page now
    succeeds instead of returning low_content_density.
    """
    vault = _make_vault(tmp_path)
    paras = [
        "The national grid operator faced an unprecedented situation last Sunday.",
        "A surplus of generation driven by rooftop solar forced output curtailment.",
        "Analysts warned the supply-demand mismatch exposes structural fragility.",
        "Officials are weighing new rules to manage these swings on the grid.",
    ]
    body = (
        "<!DOCTYPE html><html><head><title>Grid Surplus - News</title></head>"
        "<body><nav>Home</nav><article></article>"
        "<div class='post-content'><h1>Grid Surplus</h1>"
        + "".join(f"<p>{p}</p>" for p in paras)
        + "</div><footer>Copyright</footer></body></html>"
    )
    resp = MagicMock()
    resp.text = body
    resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=resp):
        result = capture(
            url="https://braziljournal.com/example-article",
            origin="news",
            mode="markdown",
            title="Grid Surplus",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "captured_to_raw", \
        f"empty-wrapper server-rendered article must capture, not block; got {result}"
    raw_md = Path(result["saved_paths"][0])
    content = raw_md.read_text(encoding="utf-8")
    assert all(p[:40] in content for p in paras), \
        f"raw .md must contain the real article prose; got: {content[:200]!r}"
    assert "<html>" not in content and "<script>" not in content


# ---------------------------------------------------------------------------
# A3 — --manual-file Unicode path: curly-quote filename captured without error
# ---------------------------------------------------------------------------

def test_a3_curly_quote_filename_captures_successfully(tmp_path):
    """A --manual-file path with Unicode curly-quote characters captures ok."""
    vault = _make_vault(tmp_path)
    # Filename with curly quotes — the kind Obsidian clipper produces.
    unicode_name = "“Weird Title”.html"   # "Weird Title".html
    src = tmp_path / unicode_name
    content = (
        "<html><head><title>Weird Title</title></head>"
        "<body><p>This is the clipped article content.</p></body></html>"
    )
    src.write_text(content, encoding="utf-8")

    result = capture(
        url="https://example.com/weird",
        origin="example",
        mode="manual",
        title="Weird Title",
        thesis=None,
        vault_root=vault,
        dry_run=False,
        gated=False,
        gated_why="",
        manual_file=src,
    )

    assert result["state"] == "captured_to_raw", \
        f"Unicode filename capture must succeed; got {result}"
    saved = Path(result["saved_paths"][0])
    assert saved.exists()


def test_a3_cli_curly_quote_path_via_path_object(tmp_path):
    """CLI main() with a Unicode path (passed as Path object) exits 0."""
    vault = _make_vault(tmp_path)
    unicode_name = "“Report 2026”.html"
    src = tmp_path / unicode_name
    content = (
        "<html><head><title>Report 2026</title></head>"
        "<body><p>Investment thesis overview and market analysis.</p></body></html>"
    )
    src.write_text(content, encoding="utf-8")

    exit_code = main([
        "--url", "https://example.com/report-2026",
        "--origin", "example",
        "--mode", "manual",
        "--manual-file", str(src),
        "--title", "Report 2026",
        "--vault-root", str(vault),
    ])

    assert exit_code == 0, f"CLI with Unicode path must exit 0"
    raw_dir = vault / "knowledge-base" / "raw" / "example"
    # Manual non-PDF mode saves as .md by default.
    assert len(list(raw_dir.glob("*.md"))) == 1


def test_a3_ascii_filename_still_works(tmp_path):
    """Regression: plain ASCII filename continues to capture normally."""
    vault = _make_vault(tmp_path)
    src = tmp_path / "plain-article.html"
    src.write_text(
        "<html><body><p>Plain article content for regression.</p></body></html>",
        encoding="utf-8",
    )

    result = capture(
        url="https://example.com/plain",
        origin="example",
        mode="manual",
        title="Plain Article",
        thesis=None,
        vault_root=vault,
        dry_run=False,
        gated=False,
        gated_why="",
        manual_file=src,
    )

    assert result["state"] == "captured_to_raw"
