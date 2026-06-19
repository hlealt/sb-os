"""Tests for sweep_done_tasks.py — sb-archivist day-rollover + Done-Task Sweep.

Each test builds a temp vault fixture and drives the script the way the workflow
will (via main() with --vault-path / --today), then asserts on the resulting
files. Covers: day-rollover (stale / noop / missing / archive-exists),
date-routing, nested-checked-skip, group-append-under, dedup, missing-archive
creation, CRLF/LF preservation, and byte-for-byte block fidelity.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sweep_done_tasks as sw  # noqa: E402

TODAY = "2026-06-18"


# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #

def make_vault(tmp_path):
    state = tmp_path / ".user" / "runtime" / "state"
    archive = state / "work-log-archive"
    archive.mkdir(parents=True)
    return tmp_path, state, archive


def write_bytes(path, text, crlf=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.replace("\n", "\r\n") if crlf else text
    path.write_bytes(data.encode("utf-8"))


def fresh_today_worklog(state, extra_completed=""):
    """A today-dated work-log.md with an optional pre-seeded ## Completed body."""
    content = (
        f"---\ndate: {TODAY}\nlast_updated: {TODAY}T08:00\n---\n\n"
        f"# Work Log — {TODAY}\n\n## Completed\n{extra_completed}\n"
        "## New Tasks Created\n\n## Updates\n"
    )
    (state / "work-log.md").write_text(content, encoding="utf-8", newline="")


def run(vault, *flags):
    argv = ["--vault-path", str(vault), "--today", TODAY, *flags]
    return sw.main(argv)


def run_sweep(vault, dry_run=False):
    """Call sweep() the way main() does and return its report dict."""
    state = vault / ".user" / "runtime" / "state"
    archive = state / "work-log-archive"
    return sw.sweep(vault, state, archive, TODAY, "09:00", dry_run)


# --------------------------------------------------------------------------- #
# Day-rollover
# --------------------------------------------------------------------------- #

def test_rollover_stale_archives_and_creates_fresh(tmp_path):
    vault, state, archive = make_vault(tmp_path)
    stale = "---\ndate: 2026-06-17\nlast_updated: 2026-06-17T23:00\n---\n\n# Work Log — 2026-06-17\n\n## Completed\n\n- [x] yesterday thing ✅ 2026-06-17\n"
    (state / "work-log.md").write_text(stale, encoding="utf-8", newline="")

    rc = run(vault, "--rollover-only")
    assert rc == 0

    archived = archive / "2026-06-17-work-log.md"
    assert archived.exists()
    # old content moved byte-for-byte (no normalization, no overwrite)
    assert archived.read_text(encoding="utf-8") == stale

    fresh = (state / "work-log.md").read_text(encoding="utf-8")
    assert f"date: {TODAY}" in fresh
    assert f"# Work Log — {TODAY}" in fresh
    assert "## Completed" in fresh
    assert "| Decision | Choice | Rationale |" in fresh   # table header retained
    assert "{Action description}" not in fresh            # placeholder dropped
    assert "{decision}" not in fresh


def test_rollover_noop_when_already_today(tmp_path):
    vault, state, archive = make_vault(tmp_path)
    fresh_today_worklog(state)
    before = (state / "work-log.md").read_text(encoding="utf-8")

    rc = run(vault, "--rollover-only")
    assert rc == 0
    assert (state / "work-log.md").read_text(encoding="utf-8") == before
    assert list(archive.iterdir()) == []   # nothing archived


def test_rollover_creates_fresh_when_missing(tmp_path):
    vault, state, archive = make_vault(tmp_path)
    assert not (state / "work-log.md").exists()

    rc = run(vault, "--rollover-only")
    assert rc == 0
    fresh = (state / "work-log.md").read_text(encoding="utf-8")
    assert f"date: {TODAY}" in fresh
    assert "## Completed" in fresh


def test_rollover_refuses_to_overwrite_existing_archive(tmp_path):
    vault, state, archive = make_vault(tmp_path)
    stale = "---\ndate: 2026-06-17\n---\n\n# Work Log — 2026-06-17\n\n## Completed\n"
    (state / "work-log.md").write_text(stale, encoding="utf-8", newline="")
    # archive target already present
    (archive / "2026-06-17-work-log.md").write_text("PRE-EXISTING", encoding="utf-8")

    rc = run(vault, "--rollover-only")
    assert rc == 0
    # archive untouched; stale work-log left as-is (fail-loud, no data loss)
    assert (archive / "2026-06-17-work-log.md").read_text(encoding="utf-8") == "PRE-EXISTING"
    assert (state / "work-log.md").read_text(encoding="utf-8") == stale


# --------------------------------------------------------------------------- #
# Sweep
# --------------------------------------------------------------------------- #

def test_sweep_routes_today_and_past_and_skips_nested(tmp_path):
    vault, state, archive = make_vault(tmp_path)
    fresh_today_worklog(state)

    foo = vault / "1-projects" / "foo" / "foo-tasks.md"
    foo_body = (
        "---\ntype: tasks\n---\n\n# foo — Tasks\n\n#### Should\n\n"
        "- [x] Task A done today ✅ 2026-06-18\n"
        "  - _Note:_ a sub-bullet that must travel with the block\n"
        "  - _Ref:_ keep me verbatim\n"
        "- [ ] An open task\n"
        "  - [x] nested checked under open — MUST NOT be swept\n"
        "- [x] Task B done past ✅ 2026-06-15\n"
        "  - _detail:_ past block body\n"
    )
    write_bytes(foo, foo_body, crlf=False)

    bar = vault / "2-areas" / "bar" / "bar-tasks.md"
    bar_body = (
        "# bar — Tasks\n\n- [ ] open bar task\n"
        "- [x] Task C done today ✅ 2026-06-18\n"
    )
    write_bytes(bar, bar_body, crlf=True)   # CRLF source

    rc = run(vault)
    assert rc == 0

    today_log = (state / "work-log.md").read_text(encoding="utf-8")
    assert "Task A done today" in today_log
    assert "a sub-bullet that must travel with the block" in today_log
    assert "Task C done today" in today_log
    # grouped under per-source headers
    assert "### Swept from [[foo-tasks]] (1-projects/foo/foo-tasks.md)" in today_log
    assert "### Swept from [[bar-tasks]] (2-areas/bar/bar-tasks.md)" in today_log

    past_log = (archive / "2026-06-15-work-log.md").read_text(encoding="utf-8")
    assert "Task B done past" in past_log
    assert "## Completed" in past_log               # missing archive auto-created
    assert "Task A done today" not in past_log

    # nested checked + open tasks remain in source, untouched
    foo_after = foo.read_bytes().decode("utf-8")
    assert "nested checked under open — MUST NOT be swept" in foo_after
    assert "- [ ] An open task" in foo_after
    assert "Task A done today" not in foo_after
    assert "Task B done past" not in foo_after

    # CRLF source preserved
    bar_after = bar.read_bytes()
    assert b"\r\n" in bar_after
    assert b"Task C done today" not in bar_after
    assert b"open bar task" in bar_after


def test_sweep_block_preserved_byte_for_byte(tmp_path):
    vault, state, archive = make_vault(tmp_path)
    fresh_today_worklog(state)

    block = (
        "- [x] Exact block ✅ 2026-06-18\n"
        "  - _Goal:_ preserve every character — accents: café, em-dash —, pipe |\n"
        "  - nested:\n"
        "    - deep bullet\n"
    )
    foo = vault / "1-projects" / "p" / "p-tasks.md"
    write_bytes(foo, f"# p\n\n## Should\n\n{block}\n## Done\n", crlf=False)

    rc = run(vault)
    assert rc == 0
    today_log = (state / "work-log.md").read_text(encoding="utf-8")
    assert block.rstrip("\n") in today_log   # block text byte-identical (LF)


def test_sweep_appends_under_existing_group_and_dedups(tmp_path):
    vault, state, archive = make_vault(tmp_path)
    # Pre-seed today's log: foo group already holds Task Z.
    pre = (
        "\n### Swept from [[foo-tasks]] (1-projects/foo/foo-tasks.md)\n\n"
        "- [x] Task Z already logged ✅ 2026-06-18\n  - _body:_ prior block\n"
    )
    fresh_today_worklog(state, extra_completed=pre)

    foo = vault / "1-projects" / "foo" / "foo-tasks.md"
    foo_body = (
        "# foo\n\n## Should\n\n"
        "- [x] Task A new ✅ 2026-06-18\n  - _body:_ new block\n"
        "- [x] Task Z already logged ✅ 2026-06-18\n  - _body:_ dup attempt\n"
    )
    write_bytes(foo, foo_body, crlf=False)

    rc = run(vault)
    assert rc == 0
    today_log = (state / "work-log.md").read_text(encoding="utf-8")

    # group header appears exactly once (appended under, not duplicated)
    assert today_log.count("### Swept from [[foo-tasks]] (1-projects/foo/foo-tasks.md)") == 1
    # Task Z logged once (dedup), Task A added
    assert today_log.count("- [x] Task Z already logged ✅ 2026-06-18") == 1
    assert "- [x] Task A new ✅ 2026-06-18" in today_log

    # both swept from source, even the deduped one
    foo_after = foo.read_text(encoding="utf-8")
    assert "Task A new" not in foo_after
    assert "Task Z already logged" not in foo_after


def test_dry_run_writes_nothing(tmp_path):
    vault, state, archive = make_vault(tmp_path)
    fresh_today_worklog(state)
    foo = vault / "1-projects" / "foo" / "foo-tasks.md"
    src = "# foo\n\n- [x] Task A ✅ 2026-06-18\n"
    write_bytes(foo, src, crlf=False)
    log_before = (state / "work-log.md").read_text(encoding="utf-8")

    rc = run(vault, "--dry-run")
    assert rc == 0
    assert foo.read_text(encoding="utf-8") == src                       # source untouched
    assert (state / "work-log.md").read_text(encoding="utf-8") == log_before  # log untouched


def test_no_done_tasks_is_clean_noop(tmp_path):
    vault, state, archive = make_vault(tmp_path)
    fresh_today_worklog(state)
    foo = vault / "1-projects" / "foo" / "foo-tasks.md"
    src = "# foo\n\n- [ ] only open tasks here\n  - [x] nested checked, skipped\n"
    write_bytes(foo, src, crlf=False)

    rc = run(vault)
    assert rc == 0
    assert foo.read_text(encoding="utf-8") == src   # nothing removed


# --------------------------------------------------------------------------- #
# Fail-safe: skip-not-delete on blocks that cannot be routed with confidence
# --------------------------------------------------------------------------- #

def _reasons(report):
    return " | ".join(s["reason"] for s in report["skipped"])


def test_failsafe_skips_done_task_with_no_date(tmp_path):
    """A column-0 `- [x]` with NO ✅ date stays in source, is not logged, is reported.

    This is the real `pagamentos-recorrentes.md` shape (`- [x] Tiago — 930`) that
    the OLD code would have swept to today's log and deleted.
    """
    vault, state, archive = make_vault(tmp_path)
    fresh_today_worklog(state)
    foo = vault / "2-areas" / "pay" / "pay-tasks.md"
    src = (
        "# pay\n\n#### Should\n\n"
        "- [x] Tiago — 930\n"
        "- [x] Internet — 120 (débito automático — confirmar que caiu)\n"
    )
    write_bytes(foo, src, crlf=False)

    report = run_sweep(vault)
    # nothing swept, both blocks skipped
    assert report["tasks_swept"] == 0
    assert report["tasks_skipped"] == 2
    assert all("no valid" in s["reason"] for s in report["skipped"])
    assert report["skipped"][0]["source"] == "2-areas/pay/pay-tasks.md"
    # source untouched byte-for-byte; nothing in the work-log
    assert foo.read_text(encoding="utf-8") == src
    today_log = (state / "work-log.md").read_text(encoding="utf-8")
    assert "Tiago" not in today_log
    assert "Internet" not in today_log


def test_failsafe_skips_invalid_calendar_and_unpadded_dates(tmp_path):
    vault, state, archive = make_vault(tmp_path)
    fresh_today_worklog(state)
    foo = vault / "1-projects" / "p" / "p-tasks.md"
    src = (
        "# p\n\n"
        "- [x] impossible month ✅ 2026-13-40\n"
        "- [x] unpadded date ✅ 2026-6-1\n"
        "- [x] no space before date ✅2026-06-18\n"
    )
    write_bytes(foo, src, crlf=False)

    report = run_sweep(vault)
    assert report["tasks_swept"] == 0
    assert report["tasks_skipped"] == 3
    # all three left in source untouched
    assert foo.read_text(encoding="utf-8") == src
    today_log = (state / "work-log.md").read_text(encoding="utf-8")
    assert "impossible month" not in today_log
    assert "unpadded date" not in today_log
    assert "no space before date" not in today_log


def test_failsafe_skips_multiple_distinct_dates(tmp_path):
    vault, state, archive = make_vault(tmp_path)
    fresh_today_worklog(state)
    foo = vault / "1-projects" / "p" / "p-tasks.md"
    src = "# p\n\n- [x] did, then redid ✅ 2026-06-18 then again ✅ 2026-06-15\n"
    write_bytes(foo, src, crlf=False)

    report = run_sweep(vault)
    assert report["tasks_swept"] == 0
    assert report["tasks_skipped"] == 1
    assert "multiple distinct" in _reasons(report)
    assert foo.read_text(encoding="utf-8") == src
    assert "did, then redid" not in (state / "work-log.md").read_text(encoding="utf-8")


def test_failsafe_same_date_twice_is_not_ambiguous(tmp_path):
    """Two ✅ of the SAME date is one distinct date -> still sweeps (not a skip)."""
    vault, state, archive = make_vault(tmp_path)
    fresh_today_worklog(state)
    foo = vault / "1-projects" / "p" / "p-tasks.md"
    src = "# p\n\n- [x] belt and braces ✅ 2026-06-18 (done ✅ 2026-06-18)\n"
    write_bytes(foo, src, crlf=False)

    report = run_sweep(vault)
    assert report["tasks_swept"] == 1
    assert report["tasks_skipped"] == 0
    assert "belt and braces" in (state / "work-log.md").read_text(encoding="utf-8")


def test_failsafe_mixed_valid_and_malformed_in_one_file(tmp_path):
    """Valid blocks sweep; malformed blocks in the SAME file skip + stay. No
    cross-contamination: a skipped block between two valid ones is preserved and
    the valid ones still move with correct boundaries."""
    vault, state, archive = make_vault(tmp_path)
    fresh_today_worklog(state)
    foo = vault / "1-projects" / "foo" / "foo-tasks.md"
    src = (
        "# foo\n\n#### Should\n\n"
        "- [x] Valid one ✅ 2026-06-18\n"
        "  - _Ref:_ travels with valid one\n"
        "- [x] Malformed no date — KEEP ME\n"
        "  - _Ref:_ this body must also stay\n"
        "- [x] Valid two ✅ 2026-06-18\n"
        "- [ ] still open\n"
    )
    write_bytes(foo, src, crlf=False)

    report = run_sweep(vault)
    assert report["tasks_swept"] == 2
    assert report["tasks_skipped"] == 1

    foo_after = foo.read_text(encoding="utf-8")
    # malformed block (line + its body) preserved verbatim in source
    assert "- [x] Malformed no date — KEEP ME" in foo_after
    assert "this body must also stay" in foo_after
    assert "- [ ] still open" in foo_after
    # valid blocks removed from source, present in log with their bodies
    assert "Valid one" not in foo_after
    assert "Valid two" not in foo_after
    today_log = (state / "work-log.md").read_text(encoding="utf-8")
    assert "Valid one" in today_log
    assert "travels with valid one" in today_log
    assert "Valid two" in today_log
    # malformed block never reached the log
    assert "KEEP ME" not in today_log


def test_failsafe_skips_reported_in_dry_run(tmp_path):
    vault, state, archive = make_vault(tmp_path)
    fresh_today_worklog(state)
    foo = vault / "1-projects" / "p" / "p-tasks.md"
    src = "# p\n\n- [x] no date here\n- [x] good ✅ 2026-06-18\n"
    write_bytes(foo, src, crlf=False)

    report = run_sweep(vault, dry_run=True)
    assert report["tasks_skipped"] == 1
    assert "no valid" in _reasons(report)
    # dry-run writes nothing
    assert foo.read_text(encoding="utf-8") == src


def test_failsafe_text_report_surfaces_skips(tmp_path):
    vault, state, archive = make_vault(tmp_path)
    fresh_today_worklog(state)
    foo = vault / "1-projects" / "p" / "p-tasks.md"
    write_bytes(foo, "# p\n\n- [x] no date here\n", crlf=False)

    report = run_sweep(vault, dry_run=True)
    text = sw.format_text_report(("noop", {"date": TODAY}), report)
    assert "SKIPPED" in text
    assert "no date here" in text
    assert "1-projects/p/p-tasks.md" in text


def test_failsafe_skips_undecodable_source_whole(tmp_path):
    """A source that is not valid UTF-8 is skipped whole and left untouched."""
    vault, state, archive = make_vault(tmp_path)
    fresh_today_worklog(state)
    foo = vault / "1-projects" / "bad" / "bad-tasks.md"
    foo.parent.mkdir(parents=True, exist_ok=True)
    raw = b"# bad\n\n- [x] looks done \xff\xfe not utf-8 \x80\n"
    foo.write_bytes(raw)

    report = run_sweep(vault)
    assert report["tasks_swept"] == 0
    assert report["tasks_skipped"] == 1
    assert "unreadable source" in _reasons(report)
    # bytes untouched
    assert foo.read_bytes() == raw
