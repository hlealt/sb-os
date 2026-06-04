"""Tests for p3-1: investment_source_capture tool.

Asserts (per the p3-1 task definition, Phase-3 checkpoint: dry-trace, no live fetch):

  (a) An approved open URL → saved to raw/{origin}/<slug>.md; state=captured_to_raw.
  (b) Return is metadata-only — no full fetched text in the summary dict.
  (c) Gated path → gated_pending_access in log.md WITHOUT fetching.
  (d) --dry-run → writes nothing (raw dir absent or unchanged).
  (e) Fetch modes send a declared User-Agent (default + override) — 2026-06-04 fix.
  (f) --manual-file: browser/manual modes save user-fetched content without
      any HTTP call; missing/absent file → blocked — 2026-06-04 fix.

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
    html_body = f"<html><head><title>{title_tag}</title></head><body>{body}</body></html>"
    resp = MagicMock()
    resp.text = html_body
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
# (c) Gated path → registers gated_pending_access in log.md WITHOUT fetching
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

    # log.md must have been written
    log_path = Path(result["log_path"])
    assert log_path.exists(), "log.md must be created for gated sources"
    log_content = log_path.read_text(encoding="utf-8")
    assert "gated_pending_access" in log_content
    assert "https://paywalled-site.com/report" in log_content
    assert "paywalled" in log_content


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

    # log.md must NOT exist (dry-run writes nothing)
    log_path = vault / "knowledge-base" / "raw" / "gated-origin" / "log.md"
    assert not log_path.exists(), "dry-run must not write log.md"


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
    fetched.write_text("BODY", encoding="utf-8")

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
    fetched.write_text("FILING", encoding="utf-8")

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
