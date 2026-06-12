"""Tests for the deterministic source-queue rule-3 prune.

Finance lint extension rule 3 resolves a source-queue entry as "spent" when its
wiki source page now exists. The resolution is DETERMINISTIC (decision
2026-06-10, `source-queue-adjudication-2026-06-10.md` § Rule-3 implementation):

  signal 1 — URL: entry `url:` matched (normalized, prefix-tolerant) against a
             source-page `url:` frontmatter, within the same origin folder.
             AUTHORITATIVE.
  signal 2 — DOI: a DOI extracted from the entry url/title appears in the page.
  signal 3 — exact title: entry title normalizes EQUAL to the page H1 or the
             page filename stem.

It is NEVER a title-token-overlap heuristic — that heuristic produced the IEA
false-negative and the ENGIE false-collapse this suite pins.

Detection runs always (check mode surfaces candidates); the delete is applied
only under the owner-gated `--prune-source-queue` flag.

Run:
    python -m pytest wiki/scripts/tests/test_source_queue_prune.py -v
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).parent.parent / "sb-wiki-lint-deterministic.py"


# ---------------------------------------------------------------------------
# Vault fixture builders
# ---------------------------------------------------------------------------


def make_vault(tmp: Path) -> Path:
    """Minimal vault with sb-os.json and an empty wiki tree. Returns vault root."""
    wiki_root = tmp / "kb"
    for sub in ("raw", "wiki/concepts", "wiki/entities", "wiki/topics", "wiki/sources", "logs"):
        (wiki_root / sub).mkdir(parents=True)
    (tmp / "sb-os.json").write_text(
        json.dumps(
            {
                "wiki_root": "kb",
                "user_context_root": ".user/context/",
                "sb_os_path": str(SCRIPT.parent.parent),
            }
        ),
        encoding="utf-8",
    )
    return tmp


def write_source_page(vault: Path, origin: str, filename: str, *, url: str = "", h1: str = "", body: str = "") -> None:
    page_dir = vault / "kb" / "wiki" / "sources" / origin
    page_dir.mkdir(parents=True, exist_ok=True)
    fm = ["---", "type: source"]
    if url:
        fm.append(f"url: {url}")
    fm.append("---")
    text = "\n".join(fm) + "\n\n"
    if h1:
        text += f"# {h1}\n\n"
    text += body + "\n"
    (page_dir / filename).write_text(text, encoding="utf-8")


QUEUE_HEADER = "---\ntype: source-queue\n---\n\n# Source queue\n\n> Open investment source-lifecycle states.\n"


def write_queue(vault: Path, entries: list[str]) -> Path:
    """entries: list of full H2 blocks (without leading newline)."""
    path = vault / "kb" / "source-queue.md"
    path.write_text(QUEUE_HEADER + "".join("\n" + e.rstrip("\n") + "\n" for e in entries), encoding="utf-8")
    return path


def entry(state: str, date: str, *, title: str, url: str, source: str) -> str:
    return (
        f"## {state} — {date}\n"
        f"- title: {title}\n"
        f"- url: {url}\n"
        f"- source: {source}\n"
        f"- related_thesis: none\n"
    )


def run_helper(vault: Path, extra_args: list[str]) -> dict:
    # Decode stdout as UTF-8 explicitly: the helper prints JSON with
    # ensure_ascii=False, and on Windows the default locale (cp1252) mojibakes
    # the em/en dashes in titles. (Production reads the --report file, written
    # with encoding="utf-8".)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--vault-root", str(vault)] + extra_args,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, f"helper exited {result.returncode}: {result.stderr!r}"
    return json.loads(result.stdout)


def resolved_map(report: dict) -> dict:
    """{queue title -> matched_page} for resolved entries."""
    return {r["title"]: r["matched_page"] for r in report["detected"].get("source_queue_resolved", [])}


def open_titles(report: dict) -> set:
    return {o["title"] for o in report["detected"].get("source_queue_open", [])}


# ---------------------------------------------------------------------------
# Signal 1 — URL match, prefix-tolerant (the IEA failure case)
# ---------------------------------------------------------------------------


def test_url_prefix_match_resolves_iea_case():
    """IEA: queue url has a `/executive-summary` suffix the page url lacks.

    Title-token overlap fell UNDER the old 60% cutoff (false-negative). The
    page url is a prefix of the queue url, so the prefix-tolerant URL match
    resolves it.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = make_vault(Path(tmpdir))
        write_source_page(
            vault,
            "iea",
            "2026-06-06-iea-renewables-2025.md",
            url="https://www.iea.org/reports/renewables-2025",
            h1="Renewables 2025 — IEA Annual Report",
        )
        write_queue(
            vault,
            [
                entry(
                    "blocked",
                    "2026-06-06",
                    title="IEA Renewables 2025 – Executive Summary",
                    url="https://www.iea.org/reports/renewables-2025/executive-summary",
                    source="iea",
                )
            ],
        )
        report = run_helper(vault, [])
        rmap = resolved_map(report)
        assert rmap == {"IEA Renewables 2025 – Executive Summary": "2026-06-06-iea-renewables-2025.md"}
        assert report["detected"]["source_queue_resolved"][0]["signal"] == "url"


# ---------------------------------------------------------------------------
# Signal 3 — exact title, no collapse (the ENGIE failure case)
# ---------------------------------------------------------------------------


def test_distinct_titles_do_not_collapse_engie_case():
    """ENGIE: two near-identical quarter titles, two distinct pages, no url.

    Token-overlap collapsed BOTH quarters onto one page (false-collapse).
    Exact-title match resolves each to its OWN page.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = make_vault(Path(tmpdir))
        write_source_page(
            vault,
            "engie-brasil",
            "2026-06-07-engie-brasil-release-de-resultados-4t25-e-2025.md",
            h1="ENGIE Brasil — Release de Resultados 4T25 e 2025",
        )
        write_source_page(
            vault,
            "engie-brasil",
            "2026-06-07-engie-brasil-release-de-resultados-3t25.md",
            h1="ENGIE Brasil — Release de Resultados 3T25",
        )
        write_queue(
            vault,
            [
                entry(
                    "gated_pending_access",
                    "2026-06-07",
                    title="ENGIE Brasil — Release de Resultados 4T25 e 2025",
                    url="https://www.engie.com.br/investidores",
                    source="engie-brasil",
                ),
                entry(
                    "gated_pending_access",
                    "2026-06-07",
                    title="ENGIE Brasil — Release de Resultados 3T25",
                    url="https://www.engie.com.br/investidores",
                    source="engie-brasil",
                ),
            ],
        )
        report = run_helper(vault, [])
        rmap = resolved_map(report)
        assert rmap == {
            "ENGIE Brasil — Release de Resultados 4T25 e 2025": "2026-06-07-engie-brasil-release-de-resultados-4t25-e-2025.md",
            "ENGIE Brasil — Release de Resultados 3T25": "2026-06-07-engie-brasil-release-de-resultados-3t25.md",
        }
        # No collapse: two distinct matched pages.
        assert len(set(rmap.values())) == 2
        for r in report["detected"]["source_queue_resolved"]:
            assert r["signal"] == "title"


# ---------------------------------------------------------------------------
# Signal 2 — DOI match (PDF-sourced paper entries)
# ---------------------------------------------------------------------------


def test_doi_match_resolves_paper_entry():
    """A DOI in the queue entry url appears in the page body -> resolved by doi."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = make_vault(Path(tmpdir))
        write_source_page(
            vault,
            "papers",
            "loneliness-a-scoping-review-of-reviews-from-2001-to-2023.md",
            h1="Loneliness: A Scoping Review of Reviews from 2001 to 2023",
            body="Published in the Journal of Psychology. doi: 10.1080/00223980.2025.2462632",
        )
        write_queue(
            vault,
            [
                entry(
                    "blocked",
                    "2026-06-06",
                    title="Loneliness scoping review 2001-2023",
                    url="https://doi.org/10.1080/00223980.2025.2462632",
                    source="papers",
                )
            ],
        )
        report = run_helper(vault, [])
        rmap = resolved_map(report)
        assert rmap == {"Loneliness scoping review 2001-2023": "loneliness-a-scoping-review-of-reviews-from-2001-to-2023.md"}
        assert report["detected"]["source_queue_resolved"][0]["signal"] == "doi"


# ---------------------------------------------------------------------------
# Negative — title-token overlap alone NEVER resolves
# ---------------------------------------------------------------------------


def test_title_token_overlap_does_not_resolve():
    """A page sharing many title tokens but no url/doi/exact-title stays OPEN."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = make_vault(Path(tmpdir))
        write_source_page(
            vault,
            "papers",
            "loneliness-a-scoping-review-of-reviews-from-2001-to-2023.md",
            url="https://example.org/loneliness-scoping-review",
            h1="Loneliness: A Scoping Review of Reviews from 2001 to 2023",
        )
        write_queue(
            vault,
            [
                entry(
                    "blocked",
                    "2026-06-06",
                    title="Loneliness and Social Isolation Among Young Adults Review 2024",
                    url="https://example.org/loneliness-young-adults",
                    source="papers",
                )
            ],
        )
        report = run_helper(vault, [])
        assert resolved_map(report) == {}
        assert "Loneliness and Social Isolation Among Young Adults Review 2024" in open_titles(report)


def test_no_match_keeps_entry_open():
    """An entry with no matching page stays open and is reported as open."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = make_vault(Path(tmpdir))
        write_source_page(
            vault,
            "iea",
            "2026-06-06-iea-electricity-2026.md",
            url="https://www.iea.org/reports/electricity-2026",
            h1="Electricity 2026",
        )
        write_queue(
            vault,
            [
                entry(
                    "gated_pending_access",
                    "2026-06-07",
                    title="Bloomberg Europe negative power prices 2025",
                    url="https://www.bloomberg.com/europe-negative-prices",
                    source="bloomberg",
                )
            ],
        )
        report = run_helper(vault, [])
        assert resolved_map(report) == {}
        assert open_titles(report) == {"Bloomberg Europe negative power prices 2025"}


# ---------------------------------------------------------------------------
# Domain-clean guard — absent queue is a silent no-op
# ---------------------------------------------------------------------------


def test_absent_queue_is_silent_noop():
    """No source-queue.md -> no resolved/open detection, clean exit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = make_vault(Path(tmpdir))
        report = run_helper(vault, [])
        assert not report["detected"].get("source_queue_resolved")
        assert not report["detected"].get("source_queue_open")


# ---------------------------------------------------------------------------
# Gating — check mode never writes; --prune-source-queue applies the delete
# ---------------------------------------------------------------------------


def test_check_mode_does_not_write_but_surfaces_candidates():
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = make_vault(Path(tmpdir))
        write_source_page(
            vault,
            "iea",
            "2026-06-06-iea-renewables-2025.md",
            url="https://www.iea.org/reports/renewables-2025",
            h1="Renewables 2025",
        )
        queue_path = write_queue(
            vault,
            [
                entry(
                    "blocked",
                    "2026-06-06",
                    title="IEA Renewables 2025 Executive Summary",
                    url="https://www.iea.org/reports/renewables-2025/executive-summary",
                    source="iea",
                )
            ],
        )
        before = queue_path.read_text(encoding="utf-8")
        report = run_helper(vault, [])
        assert queue_path.read_text(encoding="utf-8") == before, "check mode must not write"
        assert len(report["detected"]["source_queue_resolved"]) == 1
        assert "source_queue_pruned" not in report["detected"]


def test_prune_flag_removes_resolved_keeps_open_verbatim():
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = make_vault(Path(tmpdir))
        write_source_page(
            vault,
            "iea",
            "2026-06-06-iea-renewables-2025.md",
            url="https://www.iea.org/reports/renewables-2025",
            h1="Renewables 2025",
        )
        queue_path = write_queue(
            vault,
            [
                entry(
                    "blocked",
                    "2026-06-06",
                    title="IEA Renewables 2025 Executive Summary",
                    url="https://www.iea.org/reports/renewables-2025/executive-summary",
                    source="iea",
                ),
                entry(
                    "gated_pending_access",
                    "2026-06-07",
                    title="Bloomberg Europe negative power prices 2025",
                    url="https://www.bloomberg.com/europe-negative-prices",
                    source="bloomberg",
                ),
            ],
        )
        report = run_helper(vault, ["--prune-source-queue"])
        assert report["detected"]["source_queue_pruned"] == 1
        after = queue_path.read_text(encoding="utf-8")
        assert "IEA Renewables 2025 Executive Summary" not in after, "resolved entry must be pruned"
        assert "Bloomberg Europe negative power prices 2025" in after, "open entry must survive"
        assert "# Source queue" in after, "preamble must survive"


def test_prune_flag_noop_when_nothing_resolved_leaves_file_intact():
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = make_vault(Path(tmpdir))
        queue_path = write_queue(
            vault,
            [
                entry(
                    "gated_pending_access",
                    "2026-06-07",
                    title="Bloomberg Europe negative power prices 2025",
                    url="https://www.bloomberg.com/europe-negative-prices",
                    source="bloomberg",
                )
            ],
        )
        before = queue_path.read_text(encoding="utf-8")
        report = run_helper(vault, ["--prune-source-queue"])
        assert queue_path.read_text(encoding="utf-8") == before
        assert "source_queue_pruned" not in report["detected"]


# ---------------------------------------------------------------------------
# State-file guard — prune flag + canonical --report is forbidden
# ---------------------------------------------------------------------------


def test_prune_source_queue_with_canonical_report_exits_nonzero():
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = make_vault(Path(tmpdir))
        canonical = vault / "kb" / "lint-deterministic-report.json"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--vault-root", str(vault),
             "--prune-source-queue", "--report", str(canonical)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1, f"expected exit 1, got {result.returncode}: {result.stderr!r}"
        assert "ERROR" in result.stderr
