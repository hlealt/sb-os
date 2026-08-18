"""Tests for sweep_done_tasks.py — sb-archivist day-rollover + Done-Task Sweep.

Each test builds a temp vault fixture and drives the script the way the workflow
will (via main() with --vault-path / --today), then asserts on the resulting
files. Covers: day-rollover (stale / noop / missing / archive-exists),
date-routing, nested-checked-skip, group-append-under, dedup, missing-archive
creation, CRLF/LF preservation, and byte-for-byte block fidelity.
"""

import sys
import json
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


# --------------------------------------------------------------------------- #
# Targeted sweep: --only filter + per-file breakdown
# --------------------------------------------------------------------------- #

def _two_source_vault(tmp_path):
    """A vault with two task files, each holding one today-done task."""
    vault, state, archive = make_vault(tmp_path)
    fresh_today_worklog(state)
    foo = vault / "1-projects" / "foo" / "foo-tasks.md"
    write_bytes(foo, "# foo\n\n- [x] Foo task ✅ 2026-06-18\n", crlf=False)
    bar = vault / "2-areas" / "bar" / "bar-tasks.md"
    write_bytes(bar, "# bar\n\n- [x] Bar task ✅ 2026-06-18\n", crlf=False)
    return vault, state, archive, foo, bar


def test_only_sweeps_just_the_named_file(tmp_path):
    """--only NAMED sweeps only that file; every other task file is untouched."""
    vault, state, archive, foo, bar = _two_source_vault(tmp_path)
    bar_before = bar.read_text(encoding="utf-8")

    rc = run(vault, "--only", "1-projects/foo/foo-tasks.md")
    assert rc == 0

    # foo swept, bar byte-for-byte untouched
    assert "Foo task" not in foo.read_text(encoding="utf-8")
    assert bar.read_text(encoding="utf-8") == bar_before
    today_log = (state / "work-log.md").read_text(encoding="utf-8")
    assert "Foo task" in today_log
    assert "Bar task" not in today_log


def test_only_accepts_multiple_comma_separated_paths(tmp_path):
    vault, state, archive, foo, bar = _two_source_vault(tmp_path)
    rc = run(vault, "--only",
             "1-projects/foo/foo-tasks.md,2-areas/bar/bar-tasks.md")
    assert rc == 0
    today_log = (state / "work-log.md").read_text(encoding="utf-8")
    assert "Foo task" in today_log
    assert "Bar task" in today_log


def test_only_normalizes_backslashes_and_dot_slash(tmp_path):
    vault, state, archive, foo, bar = _two_source_vault(tmp_path)
    rc = run(vault, "--only", r"./1-projects\foo\foo-tasks.md")
    assert rc == 0
    assert "Foo task" not in foo.read_text(encoding="utf-8")
    assert bar.read_text(encoding="utf-8").count("Bar task") == 1


def test_only_unmatched_path_fails_loud(tmp_path):
    """An --only path matching no task file exits 2 and sweeps nothing."""
    vault, state, archive, foo, bar = _two_source_vault(tmp_path)
    foo_before = foo.read_text(encoding="utf-8")
    bar_before = bar.read_text(encoding="utf-8")

    rc = run(vault, "--only", "1-projects/nope/nope-tasks.md")
    assert rc == 2
    # nothing swept from either real source
    assert foo.read_text(encoding="utf-8") == foo_before
    assert bar.read_text(encoding="utf-8") == bar_before


def test_only_valid_file_with_no_done_tasks_is_not_an_error(tmp_path):
    """A real task file that simply holds no done tasks resolves and sweeps 0."""
    vault, state, archive = make_vault(tmp_path)
    fresh_today_worklog(state)
    foo = vault / "1-projects" / "foo" / "foo-tasks.md"
    src = "# foo\n\n- [ ] only open here\n"
    write_bytes(foo, src, crlf=False)

    rc = run(vault, "--only", "1-projects/foo/foo-tasks.md")
    assert rc == 0
    assert foo.read_text(encoding="utf-8") == src


def test_per_source_breakdown_in_report(tmp_path):
    vault, state, archive, foo, bar = _two_source_vault(tmp_path)
    report = run_sweep(vault, dry_run=True)
    ps = report["per_source"]
    assert ps["1-projects/foo/foo-tasks.md"]["swept"] == 1
    assert ps["1-projects/foo/foo-tasks.md"]["targets"] == ["work-log.md"]
    assert ps["2-areas/bar/bar-tasks.md"]["swept"] == 1


def test_per_source_breakdown_in_text_report(tmp_path):
    vault, state, archive, foo, bar = _two_source_vault(tmp_path)
    report = run_sweep(vault, dry_run=True)
    text = sw.format_text_report(("noop", {"date": TODAY}), report)
    assert "per-file breakdown" in text
    assert "1-projects/foo/foo-tasks.md: 1 sweepable → work-log.md" in text


def test_only_full_sweep_unchanged_when_absent(tmp_path):
    """No --only -> both files swept (no regression)."""
    vault, state, archive, foo, bar = _two_source_vault(tmp_path)
    rc = run(vault)
    assert rc == 0
    assert "Foo task" not in foo.read_text(encoding="utf-8")
    assert "Bar task" not in bar.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Author-side write-time validation: validate_completion_line / --validate-line
# Reuses routed_date / valid_iso_date, so an author-side CONFORMING is exactly a
# sweepable block — author-side and sweep-side enforcement can never drift.
# --------------------------------------------------------------------------- #

def test_validate_conforming_line():
    r = sw.validate_completion_line("- [x] Do thing ✅ 2026-06-18", TODAY)
    assert r["status"] == "conforming"
    assert r["date"] == "2026-06-18"
    assert r["reason"] is None


def test_validate_no_date_is_violation():
    r = sw.validate_completion_line("- [x] Do thing", TODAY)
    assert r["status"] == "violation"
    assert "no valid" in r["reason"]


def test_validate_no_space_before_date_is_violation():
    r = sw.validate_completion_line("- [x] Do thing ✅2026-06-18", TODAY)
    assert r["status"] == "violation"


def test_validate_unpadded_date_is_violation():
    r = sw.validate_completion_line("- [x] Do thing ✅ 2026-6-1", TODAY)
    assert r["status"] == "violation"


def test_validate_impossible_calendar_date_is_violation():
    r = sw.validate_completion_line("- [x] Do thing ✅ 2026-13-40", TODAY)
    assert r["status"] == "violation"


def test_validate_multiple_distinct_dates_is_violation():
    r = sw.validate_completion_line(
        "- [x] did then redid ✅ 2026-06-18 again ✅ 2026-06-15", TODAY)
    assert r["status"] == "violation"
    assert "multiple distinct" in r["reason"]


def test_validate_same_date_twice_is_conforming():
    r = sw.validate_completion_line(
        "- [x] belt and braces ✅ 2026-06-18 (done ✅ 2026-06-18)", TODAY)
    assert r["status"] == "conforming"
    assert r["date"] == "2026-06-18"


def test_validate_indented_subtask_is_not_a_task():
    r = sw.validate_completion_line("  - [x] nested done ✅ 2026-06-18", TODAY)
    assert r["status"] == "not-a-task"


def test_validate_open_checkbox_is_not_a_task():
    r = sw.validate_completion_line("- [ ] still open", TODAY)
    assert r["status"] == "not-a-task"


def test_validate_non_checkbox_bullet_is_not_a_task():
    r = sw.validate_completion_line("- _Ref:_ a continuation bullet", TODAY)
    assert r["status"] == "not-a-task"


def test_validate_column0_strikethrough_crossref_no_date_is_violation():
    """The dumb-validator boundary: a column-0 `- [x]` strikethrough relocation
    cross-ref (no ✅ date) is reported VIOLATION — the checker cannot tell it from
    a forgotten-date completion. The workflow protects such lines by NOT
    validating them (it fires only on a genuine completion)."""
    line = "- [x] ~~Build the thing~~ — **MOVED 2026-06-18 → Phase 1**"
    r = sw.validate_completion_line(line, TODAY)
    assert r["status"] == "violation"
    assert "no valid" in r["reason"]


def test_validate_trailing_newline_ignored():
    r = sw.validate_completion_line("- [x] Do thing ✅ 2026-06-18\n", TODAY)
    assert r["status"] == "conforming"


def test_validate_line_cli_exit_codes():
    """main() returns 0 / 1 / 2 for conforming / violation / not-a-task. The `=`
    form is required so a value beginning with `-` is not parsed as a flag."""
    assert sw.main(["--validate-line=- [x] Good ✅ 2026-06-18"]) == 0
    assert sw.main(["--validate-line=- [x] Bad, no date"]) == 1
    assert sw.main(["--validate-line=  - [x] indented ✅ 2026-06-18"]) == 2


def test_validate_line_cli_json_output(capsys):
    rc = sw.main(["--validate-line=- [x] Good ✅ 2026-06-18", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "conforming"
    assert out["date"] == "2026-06-18"
    assert out["line"] == "- [x] Good ✅ 2026-06-18"


def test_validate_line_mode_does_not_touch_vault(tmp_path):
    """--validate-line is side-effect-free: a stale work-log is NOT rolled over,
    no archive is created, no source is swept."""
    vault, state, archive = make_vault(tmp_path)
    stale = "---\ndate: 2026-06-17\n---\n\n# Work Log — 2026-06-17\n\n## Completed\n"
    (state / "work-log.md").write_text(stale, encoding="utf-8", newline="")
    foo = vault / "1-projects" / "p" / "p-tasks.md"
    write_bytes(foo, "# p\n\n- [x] Task ✅ 2026-06-18\n", crlf=False)

    rc = sw.main(["--vault-path", str(vault), "--today", TODAY,
                  "--validate-line=- [x] Task ✅ 2026-06-18"])
    assert rc == 0
    # vault untouched: stale work-log not rolled over, no archive, source intact
    assert (state / "work-log.md").read_text(encoding="utf-8") == stale
    assert list(archive.iterdir()) == []
    assert "- [x] Task ✅ 2026-06-18" in foo.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Ref integrity: refs pointing at swept tasks are scrubbed, never left dangling
# --------------------------------------------------------------------------- #

def _ref_fixture(tmp_path):
    vault, state, archive = make_vault(tmp_path)
    fresh_today_worklog(state)
    foo = vault / "1-projects" / "foo" / "foo-tasks.md"
    write_bytes(foo, (
        "# foo\n\n"
        f"- [x] 1.1 archived ✅ {TODAY}\n\n"
        f"- [x] 1.2 also archived ✅ {TODAY}\n"
        "  - _Depends:_ 1.1\n\n"
        "- [ ] 2.1 still open\n"
        "  - _Depends:_ 1.1, 1.2, 3.1\n"
        "  - _Done-after:_ 1.1\n\n"
        "- [ ] 3.1 also open\n"
        "  - _Depends:_ 1.2\n"
        "  - _Ref:_ keep me\n"
    ), crlf=False)
    return vault, foo


def test_refs_to_swept_tasks_are_scrubbed(tmp_path):
    vault, foo = _ref_fixture(tmp_path)
    rc = run(vault)
    assert rc == 0
    out = foo.read_text(encoding="utf-8")
    assert "  - _Depends:_ 3.1\n" in out        # 1.1/1.2 dropped, 3.1 kept
    assert "_Done-after:_" not in out           # emptied field line removed
    assert "1.1" not in out and "1.2" not in out
    assert "  - _Ref:_ keep me\n" in out        # unrelated fields untouched


def test_scrubbed_refs_are_reported_and_deps_resolvable(tmp_path):
    vault, foo = _ref_fixture(tmp_path)
    report = run_sweep(vault)
    scrubbed = {(s["task"], s["field"]): s["removed"] for s in report["refs_scrubbed"]}
    assert scrubbed == {("2.1", "_Depends:_"): ["1.1", "1.2"],
                        ("2.1", "_Done-after:_"): ["1.1"],
                        ("3.1", "_Depends:_"): ["1.2"]}
    # every same-file ref left in the file now resolves to a task in it
    sb = sw.load_sb_task()
    tf = sb.TaskFile(foo)
    numbers = {t.number for t in tf.tasks if t.number}
    for t in tf.tasks:
        for ref in t.depends()[1] + t.done_after()[1]:
            path, num = sb.parse_depend_ref(ref)
            assert path is not None or num in numbers


def test_dry_run_reports_ref_scrub_without_writing(tmp_path):
    vault, foo = _ref_fixture(tmp_path)
    before = foo.read_text(encoding="utf-8")
    report = run_sweep(vault, dry_run=True)
    assert len(report["refs_scrubbed"]) == 3
    assert foo.read_text(encoding="utf-8") == before


def test_cross_file_refs_are_left_alone(tmp_path):
    vault, state, archive = make_vault(tmp_path)
    fresh_today_worklog(state)
    foo = vault / "1-projects" / "foo" / "foo-tasks.md"
    write_bytes(foo, (
        "# foo\n\n"
        f"- [x] 1.1 archived ✅ {TODAY}\n\n"
        "- [ ] 2.1 open\n"
        "  - _Depends:_ 1-projects/bar/bar-tasks.md#1.1\n"
    ), crlf=False)
    assert run(vault) == 0
    assert "_Depends:_ 1-projects/bar/bar-tasks.md#1.1" in foo.read_text(encoding="utf-8")
