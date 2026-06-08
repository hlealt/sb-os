"""Tests for p3-1: investment_source_capture tool.

Asserts (per the p3-1 task definition, Phase-3 checkpoint: dry-trace, no live fetch):

  (a) An approved open URL → saved to raw/{origin}/<slug>.md; state=captured_to_raw.
  (b) Return is metadata-only — no full fetched text in the summary dict.
  (c) Gated path → gated_pending_access in {wiki_root}/source-queue.md
      WITHOUT fetching — v1.2 retarget (was raw/{origin}/log.md).
  (d) --dry-run → writes nothing (raw dir absent or unchanged).
  (e) Fetch modes send a declared User-Agent (default + override) — 2026-06-04 fix.
  (f) --manual-file: browser/manual modes save user-fetched content without
      any HTTP call; missing/absent file → blocked — 2026-06-04 fix.
  (g) curl fallback: httpx transport failure → subprocess curl retry with the
      same UA; provenance recorded in fetch_method; --no-curl-fallback disables;
      curl-binary-missing and both-fail degrade to state=blocked — 2026-06-04.
  (h) source-queue registration — v1.2 (§10 source-lifecycle): gated AND
      transport-level blocked register an H2 entry in {wiki_root}/source-queue.md
      (file created with type: source-queue frontmatter when absent); same
      (state, url) pair never duplicates; usage-error blocked (missing
      --manual-file, unknown mode) and dry-run register NOTHING.

All HTTP is mocked via unittest.mock. No live network fetch is performed.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import the tool by file path (matches pattern of other investimentos tests)
# ---------------------------------------------------------------------------
_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
_INVESTIMENTOS_DIR = _SCRIPTS_DIR.parent / "investimentos"

for _p in (_SCRIPTS_DIR, _INVESTIMENTOS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_MOD_PATH = _INVESTIMENTOS_DIR / "investment_source_capture.py"
_spec = importlib.util.spec_from_file_location("investment_source_capture", _MOD_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["investment_source_capture"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore

capture = _mod.capture
main = _mod.main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vault(tmp_path: Path) -> Path:
    """Create a minimal vault with sb-os.json pointing wiki_root into tmp."""
    wiki_rel = "knowledge-base"
    cfg = {"wiki_root": wiki_rel}
    (tmp_path / "sb-os.json").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / wiki_rel / "raw").mkdir(parents=True)
    return tmp_path


def _mock_response(body: str, title_tag: str = "") -> MagicMock:
    """Build a mocked httpx response with a REALISTIC article body.

    The caller's ``body`` is preserved verbatim inside an <article> <p> (so
    sentinel assertions still hold) and surrounded by genuine prose so the
    extracted content clears the A1 content-validation gates (absolute prose
    floor + size-gated density ratio). The scaffold stays well under the
    ratio-gate body size so these legit small mocks are never density-blocked.
    For raw JSON data-artifact bodies (--ext json), the body is passed through
    as the whole response with no HTML scaffold — see _mock_json_response.
    """
    article = (
        f"<article><h1>{title_tag or 'Article'}</h1>"
        f"<p>{body}</p>"
        "<p>This article reports on the topic above with supporting analysis, "
        "context, and commentary across several paragraphs of readable prose.</p>"
        "<p>Additional reporting provides background and the broader market "
        "implications for investors following this development.</p>"
        "</article>"
    )
    html_body = (
        f"<html><head><title>{title_tag}</title></head>"
        f"<body><nav>Home About</nav>{article}<footer>(c) 2026</footer></body></html>"
    )
    resp = MagicMock()
    resp.text = html_body
    resp.raise_for_status = MagicMock()
    return resp


def _mock_json_response(body: str) -> MagicMock:
    """Mocked response whose body is a raw JSON data artifact (--ext json path).

    Realistic XBRL companyfacts payloads are large; this builds a body well
    above the byte floor so the capture is not blocked as truncated. The
    density check does not apply to the JSON capture's stored output, but the
    fetched body still passes through _validate_body, so it must be non-trivial.
    """
    resp = MagicMock()
    resp.text = body
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# (a) Approved open URL → saved to raw/{origin}/<slug>.md; state=captured_to_raw
# ---------------------------------------------------------------------------

def test_capture_saves_to_raw_origin(tmp_path):
    vault = _make_vault(tmp_path)
    body = "This is the article body."
    mock_resp = _mock_response(body, title_tag="Test Article")

    with patch("httpx.get", return_value=mock_resp):
        result = capture(
            url="https://example.com/test-article",
            origin="example",
            mode="markdown",
            title="",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "captured_to_raw"
    assert result["origin"] == "example"
    assert "saved_paths" in result
    assert len(result["saved_paths"]) == 1

    saved = Path(result["saved_paths"][0])
    assert saved.exists(), f"Expected {saved} to exist"
    assert saved.suffix == ".md"
    # File must be inside raw/example/
    assert "example" in saved.parts


# ---------------------------------------------------------------------------
# (b) Return is metadata-only — no full fetched text in the summary
# ---------------------------------------------------------------------------

def test_return_is_metadata_only(tmp_path):
    vault = _make_vault(tmp_path)
    article_body = "FULL_ARTICLE_TEXT_MUST_NOT_APPEAR_IN_SUMMARY"
    mock_resp = _mock_response(article_body, title_tag="My Article")

    with patch("httpx.get", return_value=mock_resp):
        result = capture(
            url="https://example.com/my-article",
            origin="example",
            mode="markdown",
            title="",
            thesis="my-thesis",
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    # Serialize the result and assert the raw fetched body is not present
    serialized = json.dumps(result)
    assert "FULL_ARTICLE_TEXT_MUST_NOT_APPEAR_IN_SUMMARY" not in serialized

    # Expected metadata fields are present
    assert "state" in result
    assert "url" in result
    assert "origin" in result
    assert "bytes" in result
    # Full fetched content must not be a key in the result dict
    assert "body" not in result
    assert "content" not in result
    assert "text" not in result


# ---------------------------------------------------------------------------
# (c) Gated path → registers gated_pending_access in {wiki_root}/source-queue.md
#     WITHOUT fetching (v1.2 retarget — was raw/{origin}/log.md)
# ---------------------------------------------------------------------------

def test_gated_registers_without_fetching(tmp_path):
    vault = _make_vault(tmp_path)

    with patch("httpx.get") as mock_get:
        result = capture(
            url="https://paywalled-site.com/report",
            origin="paywalled",
            mode="markdown",
            title="Paywalled Report",
            thesis="some-thesis",
            vault_root=vault,
            dry_run=False,
            gated=True,
            gated_why="Key industry analysis behind paywall",
        )
        # httpx.get must NEVER be called for a gated source
        mock_get.assert_not_called()

    assert result["state"] == "gated_pending_access"
    assert result["url"] == "https://paywalled-site.com/report"
    assert result["queue"] == "registered"

    # source-queue.md must have been written at the wiki root — NOT a per-origin log
    queue_path = Path(result["queue_path"])
    assert queue_path == vault / "knowledge-base" / "source-queue.md"
    assert queue_path.exists(), "source-queue.md must be created for gated sources"
    content = queue_path.read_text(encoding="utf-8")
    # Created with the source-queue frontmatter
    assert content.startswith("---\ntype: source-queue\n---\n")
    # Entry shape: H2 state header + bullet fields
    assert "## gated_pending_access — " in content
    assert "- title: Paywalled Report" in content
    assert "- url: https://paywalled-site.com/report" in content
    assert "- source: paywalled" in content
    assert "- related_thesis: some-thesis" in content
    assert "- why_it_matters: Key industry analysis behind paywall" in content
    assert "- required_user_action: " in content
    # The legacy per-origin log must NOT be written
    assert not (vault / "knowledge-base" / "raw" / "paywalled" / "log.md").exists()


def test_gated_same_url_never_duplicates(tmp_path):
    vault = _make_vault(tmp_path)
    kwargs = dict(
        url="https://paywalled-site.com/report",
        origin="paywalled",
        mode="markdown",
        title="Paywalled Report",
        thesis=None,
        vault_root=vault,
        dry_run=False,
        gated=True,
        gated_why="test",
    )

    first = capture(**kwargs)
    second = capture(**kwargs)

    assert first["queue"] == "registered"
    assert second["queue"] == "already-registered"
    content = (vault / "knowledge-base" / "source-queue.md").read_text(encoding="utf-8")
    assert content.count("## gated_pending_access — ") == 1


# ---------------------------------------------------------------------------
# (d) --dry-run → writes nothing
# ---------------------------------------------------------------------------

def test_dry_run_writes_nothing(tmp_path):
    vault = _make_vault(tmp_path)
    raw_dir = vault / "knowledge-base" / "raw" / "example"

    mock_resp = _mock_response("Some article text", title_tag="Dry Run Article")

    with patch("httpx.get", return_value=mock_resp):
        result = capture(
            url="https://example.com/dry-run-test",
            origin="example",
            mode="markdown",
            title="",
            thesis=None,
            vault_root=vault,
            dry_run=True,
            gated=False,
            gated_why="",
        )

    # State reflects dry-run (not yet captured)
    assert result["state"] == "approved_for_capture"
    assert result["dry_run"] is True

    # The raw/example/ directory must NOT have any .md files written
    if raw_dir.exists():
        md_files = list(raw_dir.glob("*.md"))
        assert md_files == [], f"dry-run must write nothing; found: {md_files}"


# ---------------------------------------------------------------------------
# (d-gated) --dry-run on gated source → writes nothing (no log.md)
# ---------------------------------------------------------------------------

def test_dry_run_gated_writes_nothing(tmp_path):
    vault = _make_vault(tmp_path)

    with patch("httpx.get") as mock_get:
        result = capture(
            url="https://paywalled-site.com/report",
            origin="gated-origin",
            mode="markdown",
            title="Gated",
            thesis=None,
            vault_root=vault,
            dry_run=True,
            gated=True,
            gated_why="test",
        )
        mock_get.assert_not_called()

    assert result["state"] == "gated_pending_access"
    assert result["dry_run"] is True

    # source-queue.md must NOT exist (dry-run writes nothing)
    queue_path = vault / "knowledge-base" / "source-queue.md"
    assert not queue_path.exists(), "dry-run must not write source-queue.md"


# ---------------------------------------------------------------------------
# Additional: CLI --dry-run exits 0 and writes nothing
# ---------------------------------------------------------------------------

def test_cli_dry_run_exits_zero(tmp_path):
    vault = _make_vault(tmp_path)
    mock_resp = _mock_response("Content", title_tag="CLI Test")

    with patch("httpx.get", return_value=mock_resp):
        exit_code = main([
            "--url", "https://example.com/cli-test",
            "--origin", "example",
            "--mode", "markdown",
            "--vault-root", str(vault),
            "--dry-run",
        ])

    assert exit_code == 0

    raw_dir = vault / "knowledge-base" / "raw" / "example"
    if raw_dir.exists():
        assert list(raw_dir.glob("*.md")) == []


# ---------------------------------------------------------------------------
# (e) Fetch modes send a declared User-Agent (SEC EDGAR fair-access fix)
# ---------------------------------------------------------------------------

def test_fetch_sends_default_user_agent(tmp_path):
    vault = _make_vault(tmp_path)
    mock_resp = _mock_response("Body", title_tag="UA Test")

    with patch("httpx.get", return_value=mock_resp) as mock_get:
        capture(
            url="https://example.com/ua-test",
            origin="example",
            mode="markdown",
            title="",
            thesis=None,
            vault_root=vault,
            dry_run=True,
            gated=False,
            gated_why="",
        )

    _, kwargs = mock_get.call_args
    ua = kwargs.get("headers", {}).get("User-Agent", "")
    assert ua == _mod.DEFAULT_USER_AGENT
    assert ua, "fetch must always declare a User-Agent"


def test_fetch_user_agent_override(tmp_path):
    vault = _make_vault(tmp_path)
    mock_resp = _mock_response("Body", title_tag="UA Override")
    contact_ua = "Henri Example contact@example.com"

    with patch("httpx.get", return_value=mock_resp) as mock_get:
        capture(
            url="https://www.sec.gov/some-filing",
            origin="sec",
            mode="markdown",
            title="",
            thesis=None,
            vault_root=vault,
            dry_run=True,
            gated=False,
            gated_why="",
            user_agent=contact_ua,
        )

    _, kwargs = mock_get.call_args
    assert kwargs.get("headers", {}).get("User-Agent") == contact_ua


# ---------------------------------------------------------------------------
# (f) --manual-file: manual/browser modes save user-fetched content, no HTTP
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["manual", "browser"])
def test_manual_file_captures_without_fetching(tmp_path, mode):
    vault = _make_vault(tmp_path)
    fetched = tmp_path / "hand-fetched.md"
    fetched.write_text("HAND FETCHED FILING BODY", encoding="utf-8")

    with patch("httpx.get") as mock_get:
        result = capture(
            url="https://www.sec.gov/exhibit-99-1",
            origin="sec",
            mode=mode,
            title="Some Filing EX-99.1",
            thesis="some-thesis",
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
            manual_file=fetched,
        )
        # No HTTP call in manual/browser modes
        mock_get.assert_not_called()

    assert result["state"] == "captured_to_raw"
    assert result["manual_source"] == str(fetched)
    saved = Path(result["saved_paths"][0])
    assert saved.exists()
    assert saved.suffix == ".md"
    assert "sec" in saved.parts
    assert saved.read_text(encoding="utf-8") == "HAND FETCHED FILING BODY"
    # Metadata-only contract holds
    assert "HAND FETCHED FILING BODY" not in json.dumps(result)


def test_manual_mode_without_file_is_blocked(tmp_path):
    vault = _make_vault(tmp_path)

    result = capture(
        url="https://example.com/x",
        origin="example",
        mode="manual",
        title="",
        thesis=None,
        vault_root=vault,
        dry_run=False,
        gated=False,
        gated_why="",
    )

    assert result["state"] == "blocked"
    assert "--manual-file" in result["error"]


def test_manual_file_missing_is_blocked(tmp_path):
    vault = _make_vault(tmp_path)

    result = capture(
        url="https://example.com/x",
        origin="example",
        mode="manual",
        title="",
        thesis=None,
        vault_root=vault,
        dry_run=False,
        gated=False,
        gated_why="",
        manual_file=tmp_path / "does-not-exist.md",
    )

    assert result["state"] == "blocked"
    assert "not found" in result["error"]


def test_manual_file_dry_run_writes_nothing(tmp_path):
    vault = _make_vault(tmp_path)
    fetched = tmp_path / "hand-fetched.md"
    fetched.write_text(
        "Hand-fetched filing body with enough text to clear the byte floor.",
        encoding="utf-8",
    )

    result = capture(
        url="https://example.com/x",
        origin="example",
        mode="manual",
        title="Dry",
        thesis=None,
        vault_root=vault,
        dry_run=True,
        gated=False,
        gated_why="",
        manual_file=fetched,
    )

    assert result["state"] == "approved_for_capture"
    raw_dir = vault / "knowledge-base" / "raw" / "example"
    if raw_dir.exists():
        assert list(raw_dir.glob("*.md")) == []


def test_cli_manual_file_exits_zero(tmp_path):
    vault = _make_vault(tmp_path)
    fetched = tmp_path / "filing.md"
    fetched.write_text(
        "SEC exhibit filing body with sufficient length for the byte floor.",
        encoding="utf-8",
    )

    exit_code = main([
        "--url", "https://www.sec.gov/exhibit",
        "--origin", "sec",
        "--mode", "manual",
        "--manual-file", str(fetched),
        "--vault-root", str(vault),
    ])

    assert exit_code == 0
    raw_dir = vault / "knowledge-base" / "raw" / "sec"
    assert len(list(raw_dir.glob("*.md"))) == 1


# ---------------------------------------------------------------------------
# (g) curl fallback: httpx transport failure → subprocess curl retry, same UA
# ---------------------------------------------------------------------------

_CURL_BIN = "C:/Windows/System32/curl.exe"


def _mock_curl_success(body: str, title_tag: str = "") -> MagicMock:
    html_body = f"<html><head><title>{title_tag}</title></head><body>{body}</body></html>"
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = html_body.encode("utf-8")
    proc.stderr = b""
    return proc


def _mock_curl_failure(returncode: int = 22, stderr: bytes = b"curl: (22) The requested URL returned error: 403") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = b""
    proc.stderr = stderr
    return proc


def test_httpx_fails_curl_fallback_succeeds(tmp_path):
    vault = _make_vault(tmp_path)
    sentinel = "CURL_FETCHED_BODY_MUST_NOT_APPEAR_IN_SUMMARY"

    with patch("httpx.get", side_effect=Exception("403 Forbidden")), \
         patch("investment_source_capture.shutil.which", return_value=_CURL_BIN), \
         patch("investment_source_capture.subprocess.run",
               return_value=_mock_curl_success(sentinel, title_tag="Curl Rescue")) as mock_run:
        result = capture(
            url="https://bot-walled.example.com/report",
            origin="example",
            mode="markdown",
            title="",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "captured_to_raw"
    assert result["fetch_method"] == "curl-fallback"
    saved = Path(result["saved_paths"][0])
    assert saved.exists()
    assert sentinel in saved.read_text(encoding="utf-8")
    # Metadata-only contract holds on the curl path too
    assert sentinel not in json.dumps(result)
    # curl invoked via the resolved binary path — never a shell alias — same UA
    argv = mock_run.call_args[0][0]
    assert argv[0] == _CURL_BIN
    assert "--user-agent" in argv
    assert argv[argv.index("--user-agent") + 1] == _mod.DEFAULT_USER_AGENT
    assert argv[-1] == "https://bot-walled.example.com/report"


def test_curl_fallback_uses_override_user_agent(tmp_path):
    vault = _make_vault(tmp_path)
    contact_ua = "Henri Example contact@example.com"

    with patch("httpx.get", side_effect=Exception("connection reset")), \
         patch("investment_source_capture.shutil.which", return_value=_CURL_BIN), \
         patch("investment_source_capture.subprocess.run",
               return_value=_mock_curl_success("Body", title_tag="UA Carry")) as mock_run:
        result = capture(
            url="https://www.sec.gov/some-filing",
            origin="sec",
            mode="markdown",
            title="",
            thesis=None,
            vault_root=vault,
            dry_run=True,
            gated=False,
            gated_why="",
            user_agent=contact_ua,
        )

    assert result["fetch_method"] == "curl-fallback"
    argv = mock_run.call_args[0][0]
    assert argv[argv.index("--user-agent") + 1] == contact_ua


def test_httpx_and_curl_both_fail_returns_blocked(tmp_path):
    vault = _make_vault(tmp_path)

    with patch("httpx.get", side_effect=Exception("403 Forbidden")), \
         patch("investment_source_capture.shutil.which", return_value=_CURL_BIN), \
         patch("investment_source_capture.subprocess.run",
               return_value=_mock_curl_failure()):
        result = capture(
            url="https://hard-wall.example.com/report",
            origin="example",
            mode="markdown",
            title="",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "blocked"
    # Error names BOTH failed methods — no silent fallback
    assert "httpx" in result["error"]
    assert "curl" in result["error"]


def test_curl_binary_missing_degrades_to_blocked(tmp_path):
    vault = _make_vault(tmp_path)

    with patch("httpx.get", side_effect=Exception("403 Forbidden")), \
         patch("investment_source_capture.shutil.which", return_value=None), \
         patch("investment_source_capture.subprocess.run") as mock_run:
        result = capture(
            url="https://example.com/x",
            origin="example",
            mode="markdown",
            title="",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )
        mock_run.assert_not_called()

    assert result["state"] == "blocked"
    assert "curl" in result["error"].lower()


def test_curl_fallback_disabled_is_honored(tmp_path):
    vault = _make_vault(tmp_path)

    with patch("httpx.get", side_effect=Exception("403 Forbidden")), \
         patch("investment_source_capture.subprocess.run") as mock_run:
        result = capture(
            url="https://example.com/x",
            origin="example",
            mode="markdown",
            title="",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
            curl_fallback=False,
        )
        mock_run.assert_not_called()

    assert result["state"] == "blocked"
    assert result["error"] == "403 Forbidden"


def test_cli_no_curl_fallback_flag(tmp_path):
    vault = _make_vault(tmp_path)

    with patch("httpx.get", side_effect=Exception("403 Forbidden")), \
         patch("investment_source_capture.subprocess.run") as mock_run:
        exit_code = main([
            "--url", "https://example.com/x",
            "--origin", "example",
            "--vault-root", str(vault),
            "--no-curl-fallback",
        ])
        mock_run.assert_not_called()

    assert exit_code == 1


def test_fetch_method_is_httpx_on_native_success(tmp_path):
    vault = _make_vault(tmp_path)
    mock_resp = _mock_response("Body", title_tag="Native")

    with patch("httpx.get", return_value=mock_resp):
        result = capture(
            url="https://example.com/native",
            origin="example",
            mode="markdown",
            title="",
            thesis=None,
            vault_root=vault,
            dry_run=True,
            gated=False,
            gated_why="",
        )

    assert result["fetch_method"] == "httpx"


# ---------------------------------------------------------------------------
# (h) source-queue registration — blocked transport failures register;
#     usage errors and dry-run do NOT
# ---------------------------------------------------------------------------

def test_blocked_both_fail_registers_in_queue(tmp_path):
    vault = _make_vault(tmp_path)

    with patch("httpx.get", side_effect=Exception("403 Forbidden")), \
         patch("investment_source_capture.shutil.which", return_value=_CURL_BIN), \
         patch("investment_source_capture.subprocess.run",
               return_value=_mock_curl_failure()):
        result = capture(
            url="https://hard-wall.example.com/report",
            origin="example",
            mode="markdown",
            title="Hard Wall Report",
            thesis="some-thesis",
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    assert result["state"] == "blocked"
    assert result["queue"] == "registered"
    queue_path = Path(result["queue_path"])
    assert queue_path == vault / "knowledge-base" / "source-queue.md"
    content = queue_path.read_text(encoding="utf-8")
    assert "## blocked — " in content
    assert "- url: https://hard-wall.example.com/report" in content
    assert "- source: example" in content
    assert "- related_thesis: some-thesis" in content
    # The failure bullet names both failed methods — no silent fallback
    assert "- failure: " in content
    assert "httpx" in content and "curl" in content
    assert "- required_user_action: " in content


def test_blocked_no_fallback_registers_in_queue(tmp_path):
    vault = _make_vault(tmp_path)

    with patch("httpx.get", side_effect=Exception("403 Forbidden")):
        result = capture(
            url="https://example.com/x",
            origin="example",
            mode="markdown",
            title="",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
            curl_fallback=False,
        )

    assert result["state"] == "blocked"
    assert result["queue"] == "registered"
    assert (vault / "knowledge-base" / "source-queue.md").exists()


def test_blocked_same_url_never_duplicates(tmp_path):
    vault = _make_vault(tmp_path)

    for _ in range(2):
        with patch("httpx.get", side_effect=Exception("403 Forbidden")), \
             patch("investment_source_capture.shutil.which", return_value=_CURL_BIN), \
             patch("investment_source_capture.subprocess.run",
                   return_value=_mock_curl_failure()):
            result = capture(
                url="https://hard-wall.example.com/report",
                origin="example",
                mode="markdown",
                title="",
                thesis=None,
                vault_root=vault,
                dry_run=False,
                gated=False,
                gated_why="",
            )

    assert result["queue"] == "already-registered"
    content = (vault / "knowledge-base" / "source-queue.md").read_text(encoding="utf-8")
    assert content.count("## blocked — ") == 1


def test_gated_then_blocked_same_url_both_register(tmp_path):
    # Dedup is per (state, url) — the same url may hold one gated AND one
    # blocked entry (distinct lifecycle facts), never two of the same state.
    vault = _make_vault(tmp_path)
    url = "https://example.com/same-source"

    capture(
        url=url, origin="example", mode="markdown", title="", thesis=None,
        vault_root=vault, dry_run=False, gated=True, gated_why="test",
    )
    with patch("httpx.get", side_effect=Exception("403 Forbidden")), \
         patch("investment_source_capture.shutil.which", return_value=_CURL_BIN), \
         patch("investment_source_capture.subprocess.run",
               return_value=_mock_curl_failure()):
        result = capture(
            url=url, origin="example", mode="markdown", title="", thesis=None,
            vault_root=vault, dry_run=False, gated=False, gated_why="",
        )

    assert result["queue"] == "registered"
    content = (vault / "knowledge-base" / "source-queue.md").read_text(encoding="utf-8")
    assert content.count("## gated_pending_access — ") == 1
    assert content.count("## blocked — ") == 1


def test_blocked_usage_errors_do_not_register(tmp_path):
    vault = _make_vault(tmp_path)
    queue_path = vault / "knowledge-base" / "source-queue.md"

    # Missing --manual-file (usage error, not a source lifecycle state)
    result = capture(
        url="https://example.com/x", origin="example", mode="manual", title="",
        thesis=None, vault_root=vault, dry_run=False, gated=False, gated_why="",
    )
    assert result["state"] == "blocked"

    # Unknown mode (usage error)
    result = capture(
        url="https://example.com/x", origin="example", mode="bogus", title="",
        thesis=None, vault_root=vault, dry_run=False, gated=False, gated_why="",
    )
    assert result["state"] == "blocked"

    assert not queue_path.exists(), "usage-error blocked must register nothing"


def test_blocked_dry_run_does_not_register(tmp_path):
    vault = _make_vault(tmp_path)

    with patch("httpx.get", side_effect=Exception("403 Forbidden")), \
         patch("investment_source_capture.shutil.which", return_value=_CURL_BIN), \
         patch("investment_source_capture.subprocess.run",
               return_value=_mock_curl_failure()):
        result = capture(
            url="https://hard-wall.example.com/report",
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
    assert not (vault / "knowledge-base" / "source-queue.md").exists(), \
        "dry-run must not write source-queue.md"


def test_gated_never_invokes_curl(tmp_path):
    vault = _make_vault(tmp_path)

    with patch("httpx.get") as mock_get, \
         patch("investment_source_capture.subprocess.run") as mock_run:
        result = capture(
            url="https://paywalled-site.com/report",
            origin="paywalled",
            mode="markdown",
            title="Gated",
            thesis=None,
            vault_root=vault,
            dry_run=True,
            gated=True,
            gated_why="test",
        )
        mock_get.assert_not_called()
        mock_run.assert_not_called()

    assert result["state"] == "gated_pending_access"


# ---------------------------------------------------------------------------
# (i) --ext: file-extension override for JSON data artifacts (XBRL companyfacts)
#     Added 2026-06-04 (§10 capture→Financials build).
#     Overrides the saved-file extension for markdown mode and manual/browser
#     saves; default behavior is byte-identical to today when the flag is absent;
#     html-archive/both are unaffected by design.
# ---------------------------------------------------------------------------

def test_ext_json_saves_dot_json_markdown_mode(tmp_path):
    vault = _make_vault(tmp_path)
    # companyfacts-like JSON body fetched over the wire — realistic size so the
    # fetched body clears the A1 byte floor (real companyfacts are 100s of KB).
    body = json.dumps({
        "cik": 1650372,
        "entityName": "Atlassian Corp",
        "facts": {"us-gaap": {f"Metric{i}": {"units": {"USD": [{"val": i}]}}
                              for i in range(200)}},
    })
    mock_resp = _mock_json_response(body)

    with patch("httpx.get", return_value=mock_resp):
        result = capture(
            url="https://data.sec.gov/api/xbrl/companyfacts/CIK0001650372.json",
            origin="sec",
            mode="markdown",
            title="atlassian-xbrl-companyfacts",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
            ext="json",
        )

    assert result["state"] == "captured_to_raw"
    saved = Path(result["saved_paths"][0])
    assert saved.exists()
    assert saved.suffix == ".json", f"expected .json, got {saved.suffix}"
    assert "sec" in saved.parts


def test_ext_json_saves_dot_json_manual_mode(tmp_path):
    vault = _make_vault(tmp_path)
    fetched = tmp_path / "companyfacts.json"
    fetched.write_text('{"cik": 1650372, "facts": {}}', encoding="utf-8")

    with patch("httpx.get") as mock_get:
        result = capture(
            url="https://data.sec.gov/api/xbrl/companyfacts/CIK0001650372.json",
            origin="sec",
            mode="manual",
            title="atlassian-xbrl-companyfacts",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
            manual_file=fetched,
            ext="json",
        )
        mock_get.assert_not_called()

    saved = Path(result["saved_paths"][0])
    assert saved.exists()
    assert saved.suffix == ".json"


def test_ext_default_unchanged_is_md(tmp_path):
    # Absent --ext → behavior byte-identical to today: markdown mode saves .md.
    vault = _make_vault(tmp_path)
    mock_resp = _mock_response("Body", title_tag="Default Ext")

    with patch("httpx.get", return_value=mock_resp):
        result = capture(
            url="https://example.com/default-ext",
            origin="example",
            mode="markdown",
            title="",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
        )

    saved = Path(result["saved_paths"][0])
    assert saved.suffix == ".md"


def test_ext_dry_run_unaffected(tmp_path):
    vault = _make_vault(tmp_path)
    raw_dir = vault / "knowledge-base" / "raw" / "sec"
    mock_resp = _mock_response('{"cik": 1}', title_tag="Dry Ext")

    with patch("httpx.get", return_value=mock_resp):
        result = capture(
            url="https://data.sec.gov/api/xbrl/companyfacts/CIK0001650372.json",
            origin="sec",
            mode="markdown",
            title="xbrl",
            thesis=None,
            vault_root=vault,
            dry_run=True,
            gated=False,
            gated_why="",
            ext="json",
        )

    assert result["state"] == "approved_for_capture"
    # dry-run writes nothing, regardless of ext
    if raw_dir.exists():
        assert list(raw_dir.glob("*.json")) == []
        assert list(raw_dir.glob("*.md")) == []


def test_ext_html_archive_unaffected(tmp_path):
    # html-archive saves .html regardless of --ext (by design — ext only
    # overrides the markdown-mode / manual save extension).
    vault = _make_vault(tmp_path)
    mock_resp = _mock_response("<p>archive</p>", title_tag="Archive")

    with patch("httpx.get", return_value=mock_resp):
        result = capture(
            url="https://example.com/archive",
            origin="example",
            mode="html-archive",
            title="",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
            ext="json",
        )

    saved = Path(result["saved_paths"][0])
    assert saved.suffix == ".html"


def test_cli_ext_json_flag(tmp_path):
    vault = _make_vault(tmp_path)
    fetched = tmp_path / "cf.json"
    # Realistic companyfacts payload — comfortably above the A1 byte floor.
    fetched.write_text(
        json.dumps({"cik": 1, "entityName": "Example Corp",
                    "facts": {"us-gaap": {"Revenue": {"units": {"USD": [{"val": 1}]}}}}}),
        encoding="utf-8",
    )

    exit_code = main([
        "--url", "https://data.sec.gov/api/xbrl/companyfacts/CIK0001650372.json",
        "--origin", "sec",
        "--mode", "manual",
        "--manual-file", str(fetched),
        "--ext", "json",
        "--vault-root", str(vault),
    ])

    assert exit_code == 0
    raw_dir = vault / "knowledge-base" / "raw" / "sec"
    assert len(list(raw_dir.glob("*.json"))) == 1
    assert list(raw_dir.glob("*.md")) == []


# ---------------------------------------------------------------------------
# (j) PDF manual captures — Raw PDF Title-Conformance + optional --pdf-text
#     Added 2026-06-07. A --manual-file detected as PDF (.pdf extension or
#     %PDF- magic bytes) is BINARY-COPIED to raw/{origin}/{title-slug}.pdf
#     (no date prefix, --title required, collision-refused); --pdf-text
#     writes a {title-slug}.md pypdf companion. Destination is the wiki raw
#     file store — the "schema" asserted here is the naming convention
#     (tool_schema_check targets CSV/JSON stores and does not apply).
# ---------------------------------------------------------------------------

# Binary PDF bytes containing a non-UTF-8 sequence (0xE2 — the byte from the
# observed UnicodeDecodeError) so the legacy read_text path would crash on it.
_PDF_BYTES = b"%PDF-1.6\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _make_pdf(tmp_path: Path, name: str = "report.pdf") -> Path:
    pdf = tmp_path / name
    pdf.write_bytes(_PDF_BYTES)
    return pdf


def test_manual_pdf_binary_copy_title_slug(tmp_path):
    vault = _make_vault(tmp_path)
    pdf = _make_pdf(tmp_path)

    with patch("httpx.get") as mock_get:
        result = capture(
            url="https://www.cms.gov/files/highlights.pdf",
            origin="cms",
            mode="manual",
            title="Personal health care spending by age and sex: 2020 highlights",
            thesis="health-longevity-spend",
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
            manual_file=pdf,
        )
        mock_get.assert_not_called()

    assert result["state"] == "captured_to_raw"
    assert result["format"] == "pdf"
    saved = Path(result["saved_paths"][0])
    # Title-slug name, no date prefix, inside raw/cms/
    assert saved.name == "personal-health-care-spending-by-age-and-sex-2020-highlights.pdf"
    assert "cms" in saved.parts
    # Binary copy is byte-identical — read_text would have crashed on 0xE2
    assert saved.read_bytes() == _PDF_BYTES
    assert result["bytes"] == len(_PDF_BYTES)


@pytest.mark.parametrize("mode", ["manual", "browser"])
def test_manual_pdf_magic_bytes_detection(tmp_path, mode):
    # A PDF mislabeled .md is detected by %PDF- magic bytes and routed to the
    # binary path — never through read_text (the UnicodeDecodeError crash).
    vault = _make_vault(tmp_path)
    mislabeled = tmp_path / "actually-a-pdf.md"
    mislabeled.write_bytes(_PDF_BYTES)

    result = capture(
        url="https://example.com/report",
        origin="example",
        mode=mode,
        title="Mislabeled Report",
        thesis=None,
        vault_root=vault,
        dry_run=False,
        gated=False,
        gated_why="",
        manual_file=mislabeled,
    )

    assert result["state"] == "captured_to_raw"
    saved = Path(result["saved_paths"][0])
    assert saved.name == "mislabeled-report.pdf"
    assert saved.read_bytes() == _PDF_BYTES


def test_manual_pdf_requires_title(tmp_path):
    vault = _make_vault(tmp_path)
    pdf = _make_pdf(tmp_path)

    result = capture(
        url="https://example.com/report.pdf",
        origin="example",
        mode="manual",
        title="",
        thesis=None,
        vault_root=vault,
        dry_run=False,
        gated=False,
        gated_why="",
        manual_file=pdf,
    )

    assert result["state"] == "blocked"
    assert "--title" in result["error"]
    # Usage-error blocked: registers nothing, writes nothing
    assert not (vault / "knowledge-base" / "source-queue.md").exists()
    raw_dir = vault / "knowledge-base" / "raw" / "example"
    assert not raw_dir.exists() or list(raw_dir.iterdir()) == []


def test_manual_pdf_collision_refused(tmp_path):
    vault = _make_vault(tmp_path)
    pdf = _make_pdf(tmp_path)
    raw_dir = vault / "knowledge-base" / "raw" / "example"
    raw_dir.mkdir(parents=True)
    existing = raw_dir / "my-report.pdf"
    original = b"%PDF-1.4\nORIGINAL\n%%EOF\n"
    existing.write_bytes(original)

    result = capture(
        url="https://example.com/report.pdf",
        origin="example",
        mode="manual",
        title="My Report",
        thesis=None,
        vault_root=vault,
        dry_run=False,
        gated=False,
        gated_why="",
        manual_file=pdf,
    )

    assert result["state"] == "blocked"
    assert "collision" in result["error"]
    # NEVER overwritten — byte-identical original
    assert existing.read_bytes() == original


def test_manual_pdf_dry_run_writes_nothing(tmp_path):
    vault = _make_vault(tmp_path)
    pdf = _make_pdf(tmp_path)

    result = capture(
        url="https://example.com/report.pdf",
        origin="example",
        mode="manual",
        title="Dry Run Report",
        thesis=None,
        vault_root=vault,
        dry_run=True,
        gated=False,
        gated_why="",
        manual_file=pdf,
        pdf_text=True,
    )

    assert result["state"] == "approved_for_capture"
    assert result["dry_run"] is True
    raw_dir = vault / "knowledge-base" / "raw" / "example"
    assert not raw_dir.exists() or list(raw_dir.iterdir()) == []


def test_manual_pdf_text_companion_written(tmp_path):
    vault = _make_vault(tmp_path)
    pdf = _make_pdf(tmp_path)
    body = "Health spending by age group. " * 20  # > _PDF_TEXT_MIN_CHARS

    with patch("investment_source_capture._extract_pdf_text", return_value=(body, "")):
        result = capture(
            url="https://example.com/report.pdf",
            origin="example",
            mode="manual",
            title="Spending Report",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
            manual_file=pdf,
            pdf_text=True,
        )

    assert result["state"] == "captured_to_raw"
    assert len(result["saved_paths"]) == 2
    companion = Path(result["saved_paths"][1])
    assert companion.name == "spending-report.md"
    content = companion.read_text(encoding="utf-8")
    # Provenance header + extracted text; extracted text never in the JSON
    assert content.startswith("<!-- text extracted from spending-report.pdf")
    assert body in content
    assert body not in json.dumps(result)


def test_manual_pdf_text_near_empty_warns_no_companion(tmp_path):
    vault = _make_vault(tmp_path)
    pdf = _make_pdf(tmp_path)

    with patch("investment_source_capture._extract_pdf_text", return_value=("scan", "")):
        result = capture(
            url="https://example.com/report.pdf",
            origin="example",
            mode="manual",
            title="Scanned Report",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
            manual_file=pdf,
            pdf_text=True,
        )

    assert result["state"] == "captured_to_raw"
    assert "transform_warning" in result
    assert len(result["saved_paths"]) == 1  # PDF only — no husk companion
    raw_dir = vault / "knowledge-base" / "raw" / "example"
    assert list(raw_dir.glob("*.md")) == []


def test_manual_pdf_text_extraction_failure_never_blocks_capture(tmp_path):
    vault = _make_vault(tmp_path)
    pdf = _make_pdf(tmp_path)

    with patch("investment_source_capture._extract_pdf_text",
               return_value=("", "pypdf extraction failed: boom")):
        result = capture(
            url="https://example.com/report.pdf",
            origin="example",
            mode="manual",
            title="Broken Extract",
            thesis=None,
            vault_root=vault,
            dry_run=False,
            gated=False,
            gated_why="",
            manual_file=pdf,
            pdf_text=True,
        )

    assert result["state"] == "captured_to_raw"  # capture itself succeeded
    assert result["transform_error"] == "pypdf extraction failed: boom"
    assert len(result["saved_paths"]) == 1
    assert Path(result["saved_paths"][0]).exists()


def test_manual_pdf_text_real_pypdf_blank_page(tmp_path):
    # Real pypdf round-trip: a generated blank-page PDF extracts near-empty →
    # warning path, no companion. Exercises the real lazy import.
    pypdf = pytest.importorskip("pypdf")
    vault = _make_vault(tmp_path)
    pdf = tmp_path / "blank.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf.open("wb") as fh:
        writer.write(fh)

    result = capture(
        url="https://example.com/blank.pdf",
        origin="example",
        mode="manual",
        title="Blank Page Document",
        thesis=None,
        vault_root=vault,
        dry_run=False,
        gated=False,
        gated_why="",
        manual_file=pdf,
        pdf_text=True,
    )

    assert result["state"] == "captured_to_raw"
    assert "transform_warning" in result
    assert (vault / "knowledge-base" / "raw" / "example" / "blank-page-document.pdf").exists()


def test_manual_pdf_text_flag_ignored_on_non_pdf(tmp_path):
    vault = _make_vault(tmp_path)
    page = tmp_path / "page.md"
    page.write_text("A saved landing page.", encoding="utf-8")

    result = capture(
        url="https://example.com/page",
        origin="example",
        mode="manual",
        title="Landing Page",
        thesis=None,
        vault_root=vault,
        dry_run=False,
        gated=False,
        gated_why="",
        manual_file=page,
        pdf_text=True,
    )

    assert result["state"] == "captured_to_raw"
    assert result["pdf_text"] == "ignored (manual file is not a PDF)"
    saved = Path(result["saved_paths"][0])
    assert saved.suffix == ".md"
    assert saved.name.startswith("20")  # legacy date-prefixed name unchanged


def test_manual_md_legacy_json_shape_unchanged(tmp_path):
    # C4 regression guard: without --pdf-text, a landing-page manual capture
    # returns EXACTLY the legacy key set — no new keys leak in.
    vault = _make_vault(tmp_path)
    page = tmp_path / "page.md"
    page.write_text("A saved landing page.", encoding="utf-8")

    result = capture(
        url="https://example.com/page",
        origin="example",
        mode="manual",
        title="Landing Page",
        thesis=None,
        vault_root=vault,
        dry_run=False,
        gated=False,
        gated_why="",
        manual_file=page,
    )

    assert set(result.keys()) == {
        "state", "url", "title", "origin", "related_thesis",
        "saved_paths", "bytes", "manual_source", "dry_run",
    }


def test_title_slug_conformance_examples():
    # The four documented examples from naming-convention.md § Title-slug algorithm.
    _title_slug = sys.modules["investment_source_capture"]._title_slug
    assert _title_slug("International AI Safety Report 2026") == \
        "international-ai-safety-report-2026"
    assert _title_slug("You Only Look Once: Unified, Real-Time Object Detection") == \
        "you-only-look-once-unified-real-time-object-detection"
    assert _title_slug('Is there "Secret Sauce" in Large Language Model Development?') == \
        "is-there-secret-sauce-in-large-language-model-development"
    assert _title_slug("Machine Learning: The High-Interest Credit Card of Technical Debt") == \
        "machine-learning-the-high-interest-credit-card-of-technical-debt"


def test_cli_pdf_text_flag_end_to_end(tmp_path):
    vault = _make_vault(tmp_path)
    pdf = _make_pdf(tmp_path)
    body = "Extracted body text. " * 20

    with patch("investment_source_capture._extract_pdf_text", return_value=(body, "")):
        exit_code = main([
            "--url", "https://www.cms.gov/files/highlights.pdf",
            "--origin", "cms",
            "--mode", "manual",
            "--manual-file", str(pdf),
            "--title", "CLI PDF Capture",
            "--pdf-text",
            "--vault-root", str(vault),
        ])

    assert exit_code == 0
    raw_dir = vault / "knowledge-base" / "raw" / "cms"
    assert (raw_dir / "cli-pdf-capture.pdf").exists()
    assert (raw_dir / "cli-pdf-capture.md").exists()


def test_cli_pdf_missing_title_exits_one(tmp_path):
    vault = _make_vault(tmp_path)
    pdf = _make_pdf(tmp_path)

    exit_code = main([
        "--url", "https://example.com/report.pdf",
        "--origin", "example",
        "--mode", "manual",
        "--manual-file", str(pdf),
        "--vault-root", str(vault),
    ])

    assert exit_code == 1
