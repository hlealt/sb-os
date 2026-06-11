"""Tests for the configurable candidate-topic age floor (CANDIDATE-TOPIC PROMOTION).

Covers `scan_log`'s `candidate_age_floor` parameter and the enriched
`detected.log_aging_candidate_topics` rows:

  (a) default floor (7): entries aged >=7 days surface; younger do not.
  (b) floor 0: every pending candidate surfaces, including one logged today.
  (c) floor 14: only entries aged >=14 days surface.
  (d) spent candidates (topic page exists) are NEVER in aging, at any floor.
  (e) both header timestamp forms parse: `[YYYY-MM-DD]` and `[YYYY-MM-DD HH:MM]`.
  (f) a candidate-topic header with no parseable date is kept, never crashes,
      and surfaces in `detected.log_unparseable_timestamps`.
  (g) aging rows carry the entry's `trigger:` field (None when absent).
  (h) the stub age floor (STUB_AGE_FLOOR_DAYS = 30) is untouched by this change.
"""
from __future__ import annotations

import datetime
import importlib.util
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_MOD_PATH = _SCRIPTS_DIR / "sb-wiki-lint-deterministic.py"
_spec = importlib.util.spec_from_file_location("sb_wiki_lint_deterministic", _MOD_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["sb_wiki_lint_deterministic"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore

scan_log = _mod.scan_log
Report = _mod.Report

TODAY = _mod.today()


def _days_ago(n: int) -> str:
    return (TODAY - datetime.timedelta(days=n)).isoformat()


def _entry(timestamp: str, slug: str, trigger: str | None = "evolution") -> str:
    lines = [f"## [{timestamp}] candidate-topic | {slug}"]
    if trigger is not None:
        lines.append(f"- trigger: {trigger}")
    lines.append("- between: [[a.md]] and [[b.md]]")
    lines.append("- promote via: sb-wiki-create-topic skill")
    return "\n".join(lines) + "\n\n"


def _wiki_root(tmp_path: Path, topics_md: str, topic_pages: list[str] | None = None) -> Path:
    wiki_root = tmp_path / "kb"
    (wiki_root / "logs").mkdir(parents=True)
    (wiki_root / "logs" / "topics.md").write_text(
        "# Topics candidate log\n\n" + topics_md, encoding="utf-8"
    )
    topics_dir = wiki_root / "wiki" / "topics"
    topics_dir.mkdir(parents=True)
    for page in topic_pages or []:
        (topics_dir / page).write_text("---\ntype: topic\n---\nbody\n", encoding="utf-8")
    return wiki_root


def _aging_slugs(report: Report) -> list[str]:
    return [row["slug"] for row in report.detected["log_aging_candidate_topics"]]


def test_default_floor_surfaces_seven_days_and_older(tmp_path: Path) -> None:
    topics = (
        _entry(_days_ago(14), "old-candidate")
        + _entry(_days_ago(7), "boundary-candidate")
        + _entry(_days_ago(3), "young-candidate")
    )
    report = Report(mode="check")
    scan_log(_wiki_root(tmp_path, topics), report, prune=False)
    assert _aging_slugs(report) == ["old-candidate", "boundary-candidate"]


def test_floor_zero_surfaces_every_pending_candidate(tmp_path: Path) -> None:
    topics = _entry(_days_ago(14), "old-candidate") + _entry(_days_ago(0), "today-candidate")
    report = Report(mode="check")
    scan_log(_wiki_root(tmp_path, topics), report, prune=False, candidate_age_floor=0)
    assert _aging_slugs(report) == ["old-candidate", "today-candidate"]


def test_floor_fourteen_surfaces_only_two_week_old(tmp_path: Path) -> None:
    topics = (
        _entry(_days_ago(14), "old-candidate")
        + _entry(_days_ago(13), "almost-candidate")
        + _entry(_days_ago(7), "week-candidate")
    )
    report = Report(mode="check")
    scan_log(_wiki_root(tmp_path, topics), report, prune=False, candidate_age_floor=14)
    assert _aging_slugs(report) == ["old-candidate"]


def test_spent_candidate_never_ages(tmp_path: Path) -> None:
    topics = _entry(_days_ago(20), "promoted-candidate") + _entry(_days_ago(20), "pending-candidate")
    wiki_root = _wiki_root(tmp_path, topics, topic_pages=["promoted-candidate.md"])
    report = Report(mode="check")
    scan_log(wiki_root, report, prune=False, candidate_age_floor=0)
    assert _aging_slugs(report) == ["pending-candidate"]
    spent_headers = [row["header"] for row in report.detected["log_spent_entries"]]
    assert any("promoted-candidate" in h for h in spent_headers)


def test_both_timestamp_forms_parse(tmp_path: Path) -> None:
    topics = (
        _entry(_days_ago(10), "date-only-candidate")
        + _entry(f"{_days_ago(10)} 14:30", "date-time-candidate")
    )
    report = Report(mode="check")
    scan_log(_wiki_root(tmp_path, topics), report, prune=False)
    assert _aging_slugs(report) == ["date-only-candidate", "date-time-candidate"]
    assert all(row["age_days"] == 10 for row in report.detected["log_aging_candidate_topics"])


def test_unparseable_timestamp_kept_and_reported(tmp_path: Path) -> None:
    topics = _entry("sometime last week", "undated-candidate") + _entry(
        _days_ago(10), "dated-candidate"
    )
    wiki_root = _wiki_root(tmp_path, topics)
    report = Report(mode="check")
    scan_log(wiki_root, report, prune=True)
    assert _aging_slugs(report) == ["dated-candidate"]
    unparseable = report.detected["log_unparseable_timestamps"]
    assert len(unparseable) == 1 and "undated-candidate" in unparseable[0]
    # the undated entry survives the prune pass untouched
    remaining = (wiki_root / "logs" / "topics.md").read_text(encoding="utf-8")
    assert "undated-candidate" in remaining


def test_aging_rows_carry_trigger_field(tmp_path: Path) -> None:
    topics = (
        _entry(_days_ago(10), "with-trigger", trigger="contradiction (same-scope-opposing)")
        + _entry(_days_ago(10), "without-trigger", trigger=None)
    )
    report = Report(mode="check")
    scan_log(_wiki_root(tmp_path, topics), report, prune=False)
    rows = {row["slug"]: row["trigger"] for row in report.detected["log_aging_candidate_topics"]}
    assert rows["with-trigger"] == "contradiction (same-scope-opposing)"
    assert rows["without-trigger"] is None


def test_stub_age_floor_constant_untouched() -> None:
    assert _mod.STUB_AGE_FLOOR_DAYS == 30
    assert _mod.CANDIDATE_AGE_FLOOR_DAYS == 7
