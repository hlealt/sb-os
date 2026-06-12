"""pytest suite for `investimentos/scribe_transition.py`.

Covers every Behavior row and Edge Case from the scribe-transition spec.
All fixtures are tmp-dir based — no real vault data is touched.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# scribe_transition lives under investimentos/, three levels above tests/
_SCRIPTS = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_SCRIPTS))

from investimentos.scribe_transition import (
    _append_index_row,
    _delete_log_entry,
    _delete_source_queue_entry,
    _ensure_related_link,
    _has_index_row,
    _normalize_url,
    _parse_frontmatter,
    _set_frontmatter_field,
    _update_index_description,
    run,
)


# A realistic two-entry source-queue.md (mirrors production shape).
_SOURCE_QUEUE = """---
type: source-queue
---

# Source queue

> Open investment source-lifecycle states.

## gated_pending_access — 2026-06-07
- title: Retail Media Ad Spending Forecast and Trends H2 2025
- url: https://www.emarketer.com/content/retail-media-ad-spending-forecast-trends-h2-2025
- source: emarketer
- related_thesis: representativity-niche-brands
- why_it_matters: eMarketer paywall
- required_user_action: Fetch manually

## blocked — 2026-06-06
- title: DHL Global Connectedness Tracker
- url: https://www.dhl.com/global-en/delivered/globalization/global-connectedness-tracker.html
- source: dhl
- related_thesis: new-world-order-deglobalization
- failure: read timeout
- required_user_action: Retry later
"""


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_vault(tmp_path: Path, wiki_root_rel: str = "wiki") -> Path:
    """Create a minimal vault tree under tmp_path and return vault_root."""
    vault = tmp_path / "vault"
    vault.mkdir()
    sb_os = {"wiki_root": str(vault / wiki_root_rel)}
    (vault / "sb-os.json").write_text(json.dumps(sb_os), encoding="utf-8")

    wiki = vault / wiki_root_rel
    (wiki / "wiki" / "theses").mkdir(parents=True)
    (wiki / "wiki" / "decisions").mkdir(parents=True)
    (wiki / "wiki" / "entities" / "organizations").mkdir(parents=True)
    (wiki / "wiki" / "entities" / "assets").mkdir(parents=True)
    (wiki / "wiki" / "entities" / "countries").mkdir(parents=True)
    (wiki / "wiki" / "entities" / "sectors").mkdir(parents=True)
    (wiki / "logs").mkdir(parents=True)
    return vault


def _write_page(path: Path, frontmatter: dict | None = None, body: str = "") -> None:
    if frontmatter:
        fm_lines = "\n".join(f"{k}: {v}" for k, v in frontmatter.items())
        text = f"---\n{fm_lines}\n---\n\n{body}"
    else:
        text = body
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

class TestFrontmatterHelpers:
    def test_parse_frontmatter_present(self):
        text = "---\ntype: entity\nlast-touched: 2026-01-01\n---\n\nBody"
        fm, body = _parse_frontmatter(text)
        assert fm == {"type": "entity", "last-touched": "2026-01-01"}
        assert body == "Body"

    def test_parse_frontmatter_absent(self):
        text = "No frontmatter here."
        fm, body = _parse_frontmatter(text)
        assert fm == {}
        assert body == text

    def test_set_frontmatter_field_adds(self):
        text = "---\ntype: entity\n---\n\nBody"
        result = _set_frontmatter_field(text, "last-touched", "2026-06-10")
        assert "last-touched: 2026-06-10" in result
        assert "type: entity" in result

    def test_set_frontmatter_field_updates(self):
        text = "---\ntype: entity\nlast-touched: 2026-01-01\n---\n\nBody"
        result = _set_frontmatter_field(text, "last-touched", "2026-06-10")
        assert "last-touched: 2026-06-10" in result
        assert "last-touched: 2026-01-01" not in result

    def test_set_frontmatter_field_creates_block(self):
        text = "Body only"
        result = _set_frontmatter_field(text, "last-touched", "2026-06-10")
        assert result.startswith("---\nlast-touched: 2026-06-10\n---\n\nBody only")


class TestRelatedLinkHelper:
    def test_creates_section(self):
        text = "# Page\n\nBody"
        new_text, status = _ensure_related_link(text, "- [[x.md]]")
        assert status == "created-section"
        assert "## Related" in new_text
        assert "- [[x.md]]" in new_text

    def test_adds_to_existing_section(self):
        text = "# Page\n\n## Related\n\n- [[a.md]]\n"
        new_text, status = _ensure_related_link(text, "- [[x.md]]")
        assert status == "added"
        assert "- [[a.md]]" in new_text
        assert "- [[x.md]]" in new_text

    def test_already_linked(self):
        text = "# Page\n\n## Related\n\n- [[x.md]]\n"
        new_text, status = _ensure_related_link(text, "- [[x.md]]")
        assert status == "already-linked"
        assert new_text == text


class TestLogDeletionHelper:
    def test_delete_proposed_new_thesis(self):
        text = (
            "## 2026-06-10T10:00:00 — proposed-new-thesis: petrobras\n\nBody one\n"
            "## 2026-06-11T11:00:00 — proposed-new-thesis: vale\n\nBody two\n"
        )
        new_text, found = _delete_log_entry(text, "proposed-new-thesis", {"timestamp": "2026-06-10T10:00:00", "slug": "petrobras"})
        assert found
        assert "petrobras" not in new_text
        assert "vale" in new_text

    def test_delete_speculative_thesis_update(self):
        text = (
            "## 2026-06-10T10:00:00 — speculative-thesis-update\n\n- target thesis: [[petrobras.md]]\n\nBody one\n"
            "## 2026-06-11T11:00:00 — speculative-thesis-update\n\n- target thesis: [[vale.md]]\n\nBody two\n"
        )
        new_text, found = _delete_log_entry(text, "speculative-thesis-update", {"target_thesis": "petrobras"})
        assert found
        assert "petrobras" not in new_text
        assert "vale" in new_text

    def test_not_found(self):
        text = "## 2026-06-10T10:00:00 — proposed-new-thesis: petrobras\n\nBody\n"
        new_text, found = _delete_log_entry(text, "proposed-new-thesis", {"timestamp": "nope", "slug": "nope"})
        assert not found
        assert new_text == text


class TestSourceQueueHelpers:
    def test_normalize_url_strips_scheme_www_trailing_slash(self):
        assert _normalize_url("https://www.Example.com/path/") == "example.com/path"
        assert _normalize_url("http://example.com/x") == "example.com/x"
        assert _normalize_url('"https://example.com"') == "example.com"
        assert _normalize_url("") == ""

    def test_delete_by_url(self):
        new_text, found = _delete_source_queue_entry(
            _SOURCE_QUEUE,
            {"url": "https://www.emarketer.com/content/retail-media-ad-spending-forecast-trends-h2-2025"},
        )
        assert found
        assert "emarketer" not in new_text
        assert "dhl.com" in new_text  # other entry intact
        assert "# Source queue" in new_text  # preamble preserved

    def test_delete_by_url_normalized_variant_matches(self):
        # A trailing slash + http scheme variant still matches the stored https/no-slash url.
        new_text, found = _delete_source_queue_entry(
            _SOURCE_QUEUE,
            {"url": "http://emarketer.com/content/retail-media-ad-spending-forecast-trends-h2-2025/"},
        )
        assert found
        assert "emarketer" not in new_text

    def test_delete_by_title(self):
        new_text, found = _delete_source_queue_entry(
            _SOURCE_QUEUE, {"title": "DHL Global Connectedness Tracker"}
        )
        assert found
        assert "dhl.com" not in new_text
        assert "emarketer" in new_text  # other entry intact

    def test_not_found_by_url(self):
        new_text, found = _delete_source_queue_entry(_SOURCE_QUEUE, {"url": "https://nope.example/x"})
        assert not found
        assert new_text == _SOURCE_QUEUE

    def test_not_found_by_title(self):
        new_text, found = _delete_source_queue_entry(_SOURCE_QUEUE, {"title": "Nonexistent"})
        assert not found
        assert new_text == _SOURCE_QUEUE


class TestIndexHelpers:
    def test_has_index_row_true(self):
        text = "| [[a.md]] | desc |"
        assert _has_index_row(text, "[[a.md]]")

    def test_has_index_row_false(self):
        text = "| [[b.md]] | desc |"
        assert not _has_index_row(text, "[[a.md]]")

    def test_append_index_row_creates(self):
        result = _append_index_row("", "[[a.md]]", "Description")
        assert "type: index" in result
        assert "| File | Description |" in result
        assert "| [[a.md]] | Description |" in result

    def test_append_index_row_appends(self):
        text = "---\ntype: index\n---\n\n| File | Description |\n|------|-------------|\n| [[b.md]] | Existing |\n"
        result = _append_index_row(text, "[[a.md]]", "New")
        assert result.count("| [[a.md]] | New |") == 1
        assert "| [[b.md]] | Existing |" in result

    def test_update_index_description(self):
        text = "| [[a.md]] | Old |\n"
        result, updated = _update_index_description(text, "[[a.md]]", "New")
        assert updated
        assert "| [[a.md]] | New |" in result

    def test_update_index_description_not_found(self):
        text = "| [[b.md]] | Old |\n"
        result, updated = _update_index_description(text, "[[a.md]]", "New")
        assert not updated
        assert result == text


# ---------------------------------------------------------------------------
# Integration / behavior tests
# ---------------------------------------------------------------------------

class TestThesisNew:
    def test_full_transition(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"

        # Pre-existing entity pages
        _write_page(wiki_root / "wiki" / "entities" / "organizations" / "petrobras.md", {"type": "entity"}, "# Petrobras")
        _write_page(wiki_root / "wiki" / "entities" / "assets" / "petr4.md", {"type": "entity"}, "# PETR4")

        # Thesis page (agent already wrote it)
        (wiki_root / "wiki" / "theses" / "petrobras-dividend.md").write_text("# Claim\n", encoding="utf-8")

        # Log with a candidate entry
        log_text = (
            "## 2026-06-10T08:00:00 — proposed-new-thesis: petrobras-dividend\n\nDetails\n"
            "## 2026-06-09T07:00:00 — proposed-new-thesis: other\n\nOther details\n"
        )
        (wiki_root / "logs" / "theses.md").write_text(log_text, encoding="utf-8")

        payload = {
            "mode": "thesis-new",
            "slug": "petrobras-dividend",
            "entities": [
                {"kind": "organizations", "slug": "petrobras"},
                {"kind": "assets", "slug": "petr4"},
            ],
            "log_ref": {"timestamp": "2026-06-10T08:00:00", "slug": "petrobras-dividend"},
            "description": "Petrobras dividend thesis",
        }

        report = run(payload, vault, dry_run=False)
        assert not report["errors"]
        assert not report["skipped"]

        # Entity pages cross-linked
        org_text = (wiki_root / "wiki" / "entities" / "organizations" / "petrobras.md").read_text(encoding="utf-8")
        assert "- [[petrobras-dividend.md]]" in org_text
        assert "last-touched:" in org_text

        asset_text = (wiki_root / "wiki" / "entities" / "assets" / "petr4.md").read_text(encoding="utf-8")
        assert "- [[petrobras-dividend.md]]" in asset_text

        # Log entry removed
        new_log = (wiki_root / "logs" / "theses.md").read_text(encoding="utf-8")
        assert "petrobras-dividend" not in new_log
        assert "other" in new_log  # other entry intact

        # Index row appended
        index_text = (wiki_root / "wiki" / "theses" / "theses.md").read_text(encoding="utf-8")
        assert "| [[petrobras-dividend.md]] | Petrobras dividend thesis |" in index_text

    def test_no_log_ref_ok(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "theses" / "x.md").write_text("# X", encoding="utf-8")
        _write_page(wiki_root / "wiki" / "entities" / "organizations" / "co.md", {}, "# Co")

        payload = {
            "mode": "thesis-new",
            "slug": "x",
            "entities": [{"kind": "organizations", "slug": "co"}],
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)
        assert not report["errors"]

    def test_missing_page_aborts(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        payload = {
            "mode": "thesis-new",
            "slug": "missing",
            "entities": [],
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)
        assert report["errors"]
        assert any("does not exist" in e for e in report["errors"])

    def test_missing_entity_skipped(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "theses" / "x.md").write_text("# X", encoding="utf-8")
        # entity page intentionally missing

        payload = {
            "mode": "thesis-new",
            "slug": "x",
            "entities": [{"kind": "organizations", "slug": "missing-co"}],
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)
        assert not report["errors"]
        assert len(report["skipped"]) == 1
        assert report["skipped"][0]["reason"] == "page-not-found"

    def test_already_linked_not_duplicated(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "theses" / "x.md").write_text("# X", encoding="utf-8")
        _write_page(
            wiki_root / "wiki" / "entities" / "organizations" / "co.md",
            {},
            "# Co\n\n## Related\n\n- [[x.md]]\n",
        )

        payload = {
            "mode": "thesis-new",
            "slug": "x",
            "entities": [{"kind": "organizations", "slug": "co"}],
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)
        assert not report["errors"]
        edits = [e for e in report["edits"] if e["action"] == "cross-link already-linked"]
        assert len(edits) == 1
        # File should remain unchanged
        text = (wiki_root / "wiki" / "entities" / "organizations" / "co.md").read_text(encoding="utf-8")
        assert text.count("- [[x.md]]") == 1

    def test_missing_last_touched_added(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "theses" / "x.md").write_text("# X", encoding="utf-8")
        (wiki_root / "wiki" / "entities" / "organizations" / "co.md").write_text("# Co\n", encoding="utf-8")

        payload = {
            "mode": "thesis-new",
            "slug": "x",
            "entities": [{"kind": "organizations", "slug": "co"}],
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)
        assert not report["errors"]
        text = (wiki_root / "wiki" / "entities" / "organizations" / "co.md").read_text(encoding="utf-8")
        assert "last-touched:" in text

    def test_missing_log_entry_aborts(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "theses" / "x.md").write_text("# X", encoding="utf-8")
        _write_page(wiki_root / "wiki" / "entities" / "organizations" / "co.md", {}, "# Co")
        (wiki_root / "logs" / "theses.md").write_text("## Other\n\nBody\n", encoding="utf-8")

        payload = {
            "mode": "thesis-new",
            "slug": "x",
            "entities": [{"kind": "organizations", "slug": "co"}],
            "log_ref": {"timestamp": "nope", "slug": "nope"},
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)
        assert report["errors"]
        assert any("not found" in e for e in report["errors"])

    def test_duplicate_index_row_aborts(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "theses" / "x.md").write_text("# X", encoding="utf-8")
        _write_page(wiki_root / "wiki" / "entities" / "organizations" / "co.md", {}, "# Co")
        (wiki_root / "wiki" / "theses" / "theses.md").write_text(
            "---\ntype: index\n---\n\n| File | Description |\n|------|-------------|\n| [[x.md]] | Old |\n",
            encoding="utf-8",
        )

        payload = {
            "mode": "thesis-new",
            "slug": "x",
            "entities": [{"kind": "organizations", "slug": "co"}],
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)
        assert report["errors"]
        assert any("Duplicate index row" in e for e in report["errors"])

    def test_dry_run(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "theses" / "x.md").write_text("# X", encoding="utf-8")
        _write_page(wiki_root / "wiki" / "entities" / "organizations" / "co.md", {}, "# Co")

        payload = {
            "mode": "thesis-new",
            "slug": "x",
            "entities": [{"kind": "organizations", "slug": "co"}],
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=True)
        assert not report["errors"]
        assert report["dry_run"]
        # Verify no writes occurred
        text = (wiki_root / "wiki" / "entities" / "organizations" / "co.md").read_text(encoding="utf-8")
        assert "- [[x.md]]" not in text

    def test_index_created_when_absent(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "theses" / "x.md").write_text("# X", encoding="utf-8")

        payload = {
            "mode": "thesis-new",
            "slug": "x",
            "entities": [],
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)
        assert not report["errors"]
        index_path = wiki_root / "wiki" / "theses" / "theses.md"
        assert index_path.exists()
        text = index_path.read_text(encoding="utf-8")
        assert "type: index" in text
        assert "| File | Description |" in text


class TestThesisExtend:
    def test_extend_only_new_entities(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"

        (wiki_root / "wiki" / "theses" / "petrobras-dividend.md").write_text("# Claim\n", encoding="utf-8")
        # Pre-existing entity already linked
        _write_page(
            wiki_root / "wiki" / "entities" / "organizations" / "petrobras.md",
            {},
            "# Petrobras\n\n## Related\n\n- [[petrobras-dividend.md]]\n",
        )
        # New entity not yet linked
        (wiki_root / "wiki" / "entities" / "sectors" / "oil-gas.md").write_text("# Oil & Gas\n", encoding="utf-8")

        payload = {
            "mode": "thesis-extend",
            "slug": "petrobras-dividend",
            "new_entities": [
                {"kind": "organizations", "slug": "petrobras"},
                {"kind": "sectors", "slug": "oil-gas"},
            ],
            "description": "Updated claim",
        }
        report = run(payload, vault, dry_run=False)
        assert not report["errors"]

        # petrobras should report already-linked
        org_edits = [e for e in report["edits"] if e["slug"] == "petrobras"]
        assert org_edits[0]["action"] == "cross-link already-linked"

        # oil-gas should be newly linked
        sector_text = (wiki_root / "wiki" / "entities" / "sectors" / "oil-gas.md").read_text(encoding="utf-8")
        assert "- [[petrobras-dividend.md]]" in sector_text

    def test_extend_updates_description(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "theses" / "x.md").write_text("# X", encoding="utf-8")
        (wiki_root / "wiki" / "theses" / "theses.md").write_text(
            "---\ntype: index\n---\n\n| File | Description |\n|------|-------------|\n| [[x.md]] | Old |\n",
            encoding="utf-8",
        )

        payload = {
            "mode": "thesis-extend",
            "slug": "x",
            "new_entities": [],
            "updated_description": "Sharpened",
        }
        report = run(payload, vault, dry_run=False)
        assert not report["errors"]
        text = (wiki_root / "wiki" / "theses" / "theses.md").read_text(encoding="utf-8")
        assert "| [[x.md]] | Sharpened |" in text

    def test_extend_resolves_speculative_update(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "theses" / "x.md").write_text("# X", encoding="utf-8")
        log_text = (
            "## 2026-06-10T08:00:00 — speculative-thesis-update\n\n- target thesis: [[x.md]]\n\nDetails\n"
            "## 2026-06-09T07:00:00 — speculative-thesis-update\n\n- target thesis: [[y.md]]\n\nOther\n"
        )
        (wiki_root / "logs" / "theses.md").write_text(log_text, encoding="utf-8")

        payload = {
            "mode": "thesis-extend",
            "slug": "x",
            "new_entities": [],
            "log_ref": {"target_thesis": "x"},
        }
        report = run(payload, vault, dry_run=False)
        assert not report["errors"]
        new_log = (wiki_root / "logs" / "theses.md").read_text(encoding="utf-8")
        assert "x.md" not in new_log
        assert "y.md" in new_log


class TestDecision:
    def test_full_transition(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"

        (wiki_root / "wiki" / "decisions" / "2026-06-10-sell-petrobras.md").write_text("# Decision\n", encoding="utf-8")
        _write_page(wiki_root / "wiki" / "theses" / "petrobras-dividend.md", {}, "# Thesis")
        _write_page(wiki_root / "wiki" / "entities" / "assets" / "petr4.md", {}, "# PETR4")

        payload = {
            "mode": "decision",
            "filename": "2026-06-10-sell-petrobras.md",
            "links": [
                {"kind": "theses", "slug": "petrobras-dividend"},
                {"kind": "assets", "slug": "petr4"},
            ],
            "description": "Sell Petrobras",
        }
        report = run(payload, vault, dry_run=False)
        assert not report["errors"]

        thesis_text = (wiki_root / "wiki" / "theses" / "petrobras-dividend.md").read_text(encoding="utf-8")
        assert "- [[2026-06-10-sell-petrobras.md]]" in thesis_text

        index_text = (wiki_root / "wiki" / "decisions" / "decisions.md").read_text(encoding="utf-8")
        assert "| [[2026-06-10-sell-petrobras.md]] | Sell Petrobras |" in index_text

    def test_missing_decision_page_aborts(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        payload = {
            "mode": "decision",
            "filename": "2026-06-10-sell-x.md",
            "links": [],
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)
        assert report["errors"]
        assert any("does not exist" in e for e in report["errors"])

    def test_queue_ref_resolves(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "decisions" / "d.md").write_text("# D", encoding="utf-8")
        (wiki_root / "logs" / "theses.md").write_text(
            "## 2026-06-10T08:00:00 — proposed-new-thesis: x\n\nDetails\n",
            encoding="utf-8",
        )

        payload = {
            "mode": "decision",
            "filename": "d.md",
            "links": [],
            "queue_ref": {"timestamp": "2026-06-10T08:00:00", "slug": "x"},
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)
        assert not report["errors"]
        new_log = (wiki_root / "logs" / "theses.md").read_text(encoding="utf-8")
        assert "x" not in new_log


class TestDecisionSourceQueue:
    """source_queue_ref: a decision-mode payload retires a {wiki_root}/source-queue.md entry."""

    def _setup(self, tmp_path: Path) -> Path:
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "decisions" / "d.md").write_text("# D", encoding="utf-8")
        (wiki_root / "source-queue.md").write_text(_SOURCE_QUEUE, encoding="utf-8")
        return vault

    def test_resolves_by_url(self, tmp_path: Path):
        vault = self._setup(tmp_path)
        wiki_root = vault / "wiki"
        payload = {
            "mode": "decision",
            "filename": "d.md",
            "links": [],
            "source_queue_ref": {"url": "https://www.emarketer.com/content/retail-media-ad-spending-forecast-trends-h2-2025"},
            "description": "Act on the eMarketer source",
        }
        report = run(payload, vault, dry_run=False)
        assert not report["errors"], report["errors"]
        sq = (wiki_root / "source-queue.md").read_text(encoding="utf-8")
        assert "emarketer" not in sq
        assert "dhl.com" in sq  # other entry untouched
        assert any(e["action"] == "resolve-source-queue-entry" for e in report["edits"])

    def test_resolves_by_title(self, tmp_path: Path):
        vault = self._setup(tmp_path)
        wiki_root = vault / "wiki"
        payload = {
            "mode": "decision",
            "filename": "d.md",
            "links": [],
            "source_queue_ref": {"title": "DHL Global Connectedness Tracker"},
            "description": "Act on the DHL source",
        }
        report = run(payload, vault, dry_run=False)
        assert not report["errors"], report["errors"]
        sq = (wiki_root / "source-queue.md").read_text(encoding="utf-8")
        assert "dhl.com" not in sq
        assert "emarketer" in sq

    def test_log_ref_and_source_queue_ref_both_resolve(self, tmp_path: Path):
        vault = self._setup(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "logs" / "theses.md").write_text(
            "## 2026-06-10T08:00:00 — proposed-new-thesis: t\n\nDetails\n", encoding="utf-8"
        )
        payload = {
            "mode": "decision",
            "filename": "d.md",
            "links": [],
            "log_ref": {"timestamp": "2026-06-10T08:00:00", "slug": "t"},
            "source_queue_ref": {"url": "https://www.emarketer.com/content/retail-media-ad-spending-forecast-trends-h2-2025"},
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)
        assert not report["errors"], report["errors"]
        assert "emarketer" not in (wiki_root / "source-queue.md").read_text(encoding="utf-8")
        assert "proposed-new-thesis" not in (wiki_root / "logs" / "theses.md").read_text(encoding="utf-8")

    def test_not_found_aborts_with_no_writes(self, tmp_path: Path):
        vault = self._setup(tmp_path)
        before = _hash_tree(vault)
        payload = {
            "mode": "decision",
            "filename": "d.md",
            "links": [],
            "source_queue_ref": {"url": "https://nope.example/missing"},
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)
        assert report["errors"]
        assert any("source-queue entry not found" in e for e in report["errors"])
        assert _hash_tree(vault) == before  # validate-first: zero writes

    def test_source_queue_ref_rejected_in_thesis_mode(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "theses" / "x.md").write_text("# X", encoding="utf-8")
        (wiki_root / "source-queue.md").write_text(_SOURCE_QUEUE, encoding="utf-8")
        before = _hash_tree(vault)
        payload = {
            "mode": "thesis-new",
            "slug": "x",
            "entities": [],
            "source_queue_ref": {"title": "DHL Global Connectedness Tracker"},
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)
        assert report["errors"]
        assert any("only valid in decision mode" in e for e in report["errors"])
        assert _hash_tree(vault) == before

    def test_missing_source_queue_file_aborts(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "decisions" / "d.md").write_text("# D", encoding="utf-8")
        # source-queue.md intentionally absent
        payload = {
            "mode": "decision",
            "filename": "d.md",
            "links": [],
            "source_queue_ref": {"title": "Anything"},
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)
        assert report["errors"]
        assert any("Source queue file not found" in e for e in report["errors"])

    def test_ref_without_url_or_title_aborts(self, tmp_path: Path):
        vault = self._setup(tmp_path)
        payload = {
            "mode": "decision",
            "filename": "d.md",
            "links": [],
            "source_queue_ref": {"source": "emarketer"},
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)
        assert report["errors"]
        assert any("must contain" in e for e in report["errors"])

    def test_dry_run_leaves_source_queue_untouched(self, tmp_path: Path):
        vault = self._setup(tmp_path)
        before = _hash_tree(vault)
        payload = {
            "mode": "decision",
            "filename": "d.md",
            "links": [],
            "source_queue_ref": {"url": "https://www.emarketer.com/content/retail-media-ad-spending-forecast-trends-h2-2025"},
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=True)
        assert not report["errors"], report["errors"]
        assert report["dry_run"]
        assert _hash_tree(vault) == before
        assert any(e["action"] == "resolve-source-queue-entry" for e in report["edits"])


class TestEdgeCases:
    def test_missing_sb_os_json(self, tmp_path: Path):
        vault = tmp_path / "vault"
        vault.mkdir()
        payload = {"mode": "thesis-new", "slug": "x", "entities": [], "description": "Desc"}
        report = run(payload, vault, dry_run=False)
        assert report["errors"]
        assert any("sb-os.json not found" in e for e in report["errors"])

    def test_malformed_payload_unknown_mode(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        payload = {"mode": "invalid-mode", "slug": "x"}
        report = run(payload, vault, dry_run=False)
        assert report["errors"]
        assert any("Unknown mode" in e for e in report["errors"])

    def test_malformed_payload_missing_slug(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        payload = {"mode": "thesis-new", "entities": [], "description": "Desc"}
        report = run(payload, vault, dry_run=False)
        assert report["errors"]
        assert any("Missing required field: slug" in e for e in report["errors"])


def _hash_tree(root: Path) -> dict[str, str]:
    """SHA-256 every file under *root* keyed by relative posix path."""
    import hashlib

    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


class TestVaultRootSeam:
    """The --vault-root isolation seam: every path derives from vault_root.

    The production sb-os.json stores wiki_root VAULT-RELATIVE
    (e.g. "3-resources/knowledge-base/"). A relative wiki_root MUST resolve
    UNDER vault_root, never against the process CWD — otherwise an exercise
    on a scratch vault silently reaches (or misses) the wrong tree.
    """

    def test_relative_wiki_root_resolves_under_vault_root(self, tmp_path: Path, monkeypatch):
        # Mirror production: relative wiki_root string in sb-os.json.
        vault = tmp_path / "vault"
        wiki = vault / "3-resources" / "knowledge-base"
        (wiki / "wiki" / "theses").mkdir(parents=True)
        (wiki / "wiki" / "entities" / "organizations").mkdir(parents=True)
        (wiki / "logs").mkdir(parents=True)
        (vault / "sb-os.json").write_text(
            json.dumps({"wiki_root": "3-resources/knowledge-base/"}), encoding="utf-8"
        )
        (wiki / "wiki" / "theses" / "x.md").write_text("# X\n", encoding="utf-8")
        _write_page(wiki / "wiki" / "entities" / "organizations" / "co.md", {"type": "entity"}, "# Co")

        # Run from a CWD that is NOT the vault root — the seam must ignore CWD.
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        monkeypatch.chdir(outside)

        payload = {
            "mode": "thesis-new",
            "slug": "x",
            "entities": [{"kind": "organizations", "slug": "co"}],
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)
        assert not report["errors"], report["errors"]
        # The page WAS found under vault_root (not reported missing).
        co_text = (wiki / "wiki" / "entities" / "organizations" / "co.md").read_text(encoding="utf-8")
        assert "- [[x.md]]" in co_text
        assert (wiki / "wiki" / "theses" / "theses.md").exists()
        # Nothing leaked to a CWD-relative tree outside the vault.
        assert not (outside / "3-resources").exists()

    def test_dry_run_leaves_tree_byte_identical(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "theses" / "x.md").write_text("# X", encoding="utf-8")
        _write_page(wiki_root / "wiki" / "entities" / "organizations" / "co.md", {"type": "entity"}, "# Co")
        (wiki_root / "logs" / "theses.md").write_text(
            "## 2026-06-10T08:00:00 — proposed-new-thesis: x\n\nDetails\n", encoding="utf-8"
        )

        before = _hash_tree(vault)
        payload = {
            "mode": "thesis-new",
            "slug": "x",
            "entities": [{"kind": "organizations", "slug": "co"}],
            "log_ref": {"timestamp": "2026-06-10T08:00:00", "slug": "x"},
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=True)
        assert not report["errors"]
        assert _hash_tree(vault) == before

    def test_validation_failure_leaves_tree_unchanged(self, tmp_path: Path):
        # A referenced-but-absent log entry must abort with ZERO writes.
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "theses" / "x.md").write_text("# X", encoding="utf-8")
        _write_page(wiki_root / "wiki" / "entities" / "organizations" / "co.md", {"type": "entity"}, "# Co")
        (wiki_root / "logs" / "theses.md").write_text("## Other\n\nBody\n", encoding="utf-8")

        before = _hash_tree(vault)
        payload = {
            "mode": "thesis-new",
            "slug": "x",
            "entities": [{"kind": "organizations", "slug": "co"}],
            "log_ref": {"timestamp": "nope", "slug": "nope"},
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)
        assert report["errors"]
        # No entity cross-link, no index, no log edit — tree byte-identical.
        assert _hash_tree(vault) == before


# ---------------------------------------------------------------------------
# ADX-5: failure-path report labeling
# ---------------------------------------------------------------------------

class TestFailurePathReportLabeling:
    """ADX-5: on pre-write validation failure, edits must NOT appear as performed.

    The failure path (errors present, partial=False) must label any listed
    operations as planned-and-not-applied — never as `edits:`.
    The partial-write path (errors present, partial=True) retains `edits:` so
    the caller can distinguish landed vs not-landed operations.
    """

    def test_pre_write_failure_labels_edits_as_planned(self, tmp_path: Path):
        """A nonexistent log ref aborts before writes; report must say planned-not-applied."""
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        # Thesis page exists so we pass the page-existence gate
        (wiki_root / "wiki" / "theses" / "x.md").write_text("# X", encoding="utf-8")
        # Entity page exists so a cross-link op is queued (making the edits list non-empty)
        _write_page(wiki_root / "wiki" / "entities" / "organizations" / "co.md", {}, "# Co")
        # Log file exists but does NOT contain the referenced entry
        (wiki_root / "logs" / "theses.md").write_text("## Unrelated entry\n\nBody\n", encoding="utf-8")

        payload = {
            "mode": "thesis-new",
            "slug": "x",
            "entities": [{"kind": "organizations", "slug": "co"}],
            "log_ref": {"timestamp": "nope", "slug": "nope"},
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)

        # Must have error, must not be partial (no writes occurred)
        assert report["errors"]
        assert not report["partial"]
        assert report["edits"]  # cross-link op was queued before the failure

        from investimentos.scribe_transition import _build_report_text
        text = _build_report_text(report)

        # Failure label must be present
        assert "planned (NOT applied — validation failed):" in text
        # Plain "edits:" label must NOT appear as a section heading
        assert "edits:\n" not in text and not text.startswith("edits:\n")
        # Error must still be the headline (present in report)
        assert "errors:" in text

    def test_success_path_uses_edits_label(self, tmp_path: Path):
        """On success, report uses the plain `edits:` label (not the failure label)."""
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "theses" / "x.md").write_text("# X", encoding="utf-8")
        _write_page(wiki_root / "wiki" / "entities" / "organizations" / "co.md", {}, "# Co")

        payload = {
            "mode": "thesis-new",
            "slug": "x",
            "entities": [{"kind": "organizations", "slug": "co"}],
            "description": "Desc",
        }
        report = run(payload, vault, dry_run=False)
        assert not report["errors"]

        from investimentos.scribe_transition import _build_report_text
        text = _build_report_text(report)

        assert "edits:" in text
        assert "planned (NOT applied" not in text


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------

class TestCLI:
    def test_cli_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "investimentos.scribe_transition", "--help"],
            capture_output=True,
            text=True,
            cwd=str(_SCRIPTS),
        )
        assert result.returncode == 0
        assert "--payload" in result.stdout

    def test_cli_stdin(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "theses" / "x.md").write_text("# X", encoding="utf-8")

        payload = json.dumps({
            "mode": "thesis-new",
            "slug": "x",
            "entities": [],
            "description": "Desc",
        })
        result = subprocess.run(
            [sys.executable, "-m", "investimentos.scribe_transition", "--payload", "-", "--vault-root", str(vault)],
            input=payload,
            capture_output=True,
            text=True,
            cwd=str(_SCRIPTS),
        )
        assert result.returncode == 0
        assert "append-index-row" in result.stdout

    def test_cli_dry_run(self, tmp_path: Path):
        vault = _make_vault(tmp_path)
        wiki_root = vault / "wiki"
        (wiki_root / "wiki" / "theses" / "x.md").write_text("# X", encoding="utf-8")

        payload_path = tmp_path / "payload.json"
        payload_path.write_text(json.dumps({
            "mode": "thesis-new",
            "slug": "x",
            "entities": [],
            "description": "Desc",
        }), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, "-m", "investimentos.scribe_transition", "--payload", str(payload_path), "--vault-root", str(vault), "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(_SCRIPTS),
        )
        assert result.returncode == 0
        assert "dry_run: True" in result.stdout
        # No index file should have been created
        assert not (wiki_root / "wiki" / "theses" / "theses.md").exists()
