"""Tests for sb-wiki-shared-append.py — collision-safe shared-file appends.

Covers:
- plan_append_block / plan_append_row pure-function shaping (incl. byte-identity
  to a direct append, the "single-source unchanged" guarantee)
- create-if-absent, dry-run, dedupe-skip, insert-before-next-section
- the lock: timeout when held, age-based stale-lock steal
- --vault-root containment guard
- REAL concurrency: N OS processes appending to ONE file at once, all preserved
  (the done-gate C1 exercise — block surface AND queue-row surface)

Run from the sb-os repo root:
    python -m pytest wiki/scripts/tests/test_sb_wiki_shared_append.py -v
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "sb-wiki-shared-append.py"
_spec = importlib.util.spec_from_file_location("sb_wiki_shared_append", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["sb_wiki_shared_append"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore

plan_append_block = _mod.plan_append_block
plan_append_row = _mod.plan_append_row
acquire_lock = _mod.acquire_lock
release_lock = _mod.release_lock
write_text_verified = _mod.write_text_verified
_lock_path = _mod._lock_path
LockTimeout = _mod.LockTimeout
AppendError = _mod.AppendError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_vault(tmp_path: Path) -> Path:
    wiki_root = tmp_path / "kb"
    (wiki_root / "logs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sb-os.json").write_text(json.dumps({
        "wiki_root": "kb",
        "user_context_root": ".user/context/",
        "sb_os_path": str(_SCRIPT.parent.parent),
    }), encoding="utf-8")
    return tmp_path


def run_cmd(vault_root: Path, subcommand: str, *args: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(_SCRIPT), subcommand,
           "--vault-root", str(vault_root), *args]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")


QUEUE_FIXTURE = (
    "# Pending topic updates\n\n"
    "## Pending topic updates\n\n"
    "| source page | target topic | signal | proposed section | proposed bullet + citation | Decision |\n"
    "|---|---|---|---|---|---|\n"
    "| wiki/sources/x/seed.md | seed-topic.md | semantic:0.5 | Timeline | seed bullet. — [[seed.md]] |  |\n\n"
    "## Rejected ledger\n\n"
    "| source page | target topic | reason |\n"
    "|---|---|---|\n"
    "| wiki/sources/x/declined.md | declined-topic.md | reject N |\n"
)


# ---------------------------------------------------------------------------
# plan_append_block — pure shaping
# ---------------------------------------------------------------------------

def test_block_appends_blank_line_separated():
    before = "# Log\n\n## [2026-06-14] candidate-mention | a\n- name: a\n"
    entry = "## [2026-06-14] candidate-mention | b\n- name: b"
    after = plan_append_block(before, entry, None, exists=True)
    assert after == "# Log\n\n## [2026-06-14] candidate-mention | a\n- name: a\n\n## [2026-06-14] candidate-mention | b\n- name: b\n"


def test_block_output_is_identical_to_a_direct_append():
    # The "single-source ingest unchanged" guarantee: the helper's bytes equal a
    # plain direct append (rstrip existing, one blank line, entry, trailing nl).
    before = "# Mentions candidate log\n\n> note\n"
    entry = "## [2026-06-14] candidate-mention | x\n- name: x\n- classification: concept"
    direct = before.rstrip("\n") + "\n\n" + entry.strip("\n") + "\n"
    assert plan_append_block(before, entry, None, exists=True) == direct


def test_block_create_if_absent_uses_init_header():
    after = plan_append_block("", "## entry\n- body", "# New Log", exists=False)
    assert after == "# New Log\n\n## entry\n- body\n"


def test_block_create_without_header():
    after = plan_append_block("", "## entry\n- body", None, exists=False)
    assert after == "## entry\n- body\n"


def test_block_refuses_empty_entry():
    with pytest.raises(AppendError):
        plan_append_block("# Log\n", "   \n  ", None, exists=True)


# ---------------------------------------------------------------------------
# plan_append_row — pure shaping
# ---------------------------------------------------------------------------

def test_row_inserts_at_end_of_section_table_before_next_section():
    new_row = "| wiki/sources/y/new.md | new-topic.md | semantic:0.7 | Timeline | new bullet. — [[new.md]] |  |"
    after, skipped = plan_append_row(
        QUEUE_FIXTURE, "Pending topic updates", new_row, [0, 1], None, exists=True
    )
    assert skipped is False
    lines = after.split("\n")
    pending_hdr = lines.index("## Pending topic updates")
    ledger_hdr = lines.index("## Rejected ledger")
    new_idx = next(i for i, ln in enumerate(lines) if "new-topic.md" in ln)
    # the new row lands inside the pending section, before the rejected ledger
    assert pending_hdr < new_idx < ledger_hdr
    # the seed row and the ledger row are both untouched
    assert any("seed-topic.md" in ln for ln in lines)
    assert any("declined-topic.md" in ln for ln in lines[ledger_hdr:])


def test_row_dedupe_skips_existing_pair():
    dup = "| wiki/sources/x/seed.md | seed-topic.md | semantic:0.9 | Timeline | different text — [[seed.md]] |  |"
    after, skipped = plan_append_row(
        QUEUE_FIXTURE, "Pending topic updates", dup, [0, 1], None, exists=True
    )
    assert skipped is True
    assert after == QUEUE_FIXTURE  # no-op


def test_row_no_dedupe_allows_second_pair():
    again = "| wiki/sources/x/seed.md | seed-topic.md | semantic:0.9 | Timeline | second — [[seed.md]] |  |"
    after, skipped = plan_append_row(
        QUEUE_FIXTURE, "Pending topic updates", again, [], None, exists=True
    )
    assert skipped is False
    assert after.count("seed-topic.md") == 2


def test_row_missing_section_raises():
    with pytest.raises(AppendError):
        plan_append_row(QUEUE_FIXTURE, "No Such Section", "| a | b |", [], None, exists=True)


def test_row_create_if_absent():
    header = ("# Pending topic updates\n\n## Pending topic updates\n\n"
              "| source page | target topic |\n|---|---|")
    row = "| s.md | t.md |"
    after, skipped = plan_append_row("", "Pending topic updates", row, [], header, exists=False)
    assert skipped is False
    assert after.endswith("| s.md | t.md |\n")


# ---------------------------------------------------------------------------
# Lock behavior
# ---------------------------------------------------------------------------

def test_lock_timeout_when_held(tmp_path: Path):
    target = tmp_path / "f.md"
    lock = _lock_path(target)
    lock.write_text("99999 0", encoding="utf-8")  # simulate a fresh held lock
    try:
        with pytest.raises(LockTimeout):
            acquire_lock(lock, timeout=0.3, stale=9999, poll=0.02)
    finally:
        release_lock(lock)


def test_stale_lock_is_stolen(tmp_path: Path):
    import os
    target = tmp_path / "f.md"
    lock = _lock_path(target)
    lock.write_text("99999 0", encoding="utf-8")
    old = time.time() - 120
    os.utime(lock, (old, old))  # age the lock past the stale threshold
    acquire_lock(lock, timeout=1.0, stale=30, poll=0.02)  # must steal, not raise
    assert lock.is_file()  # now held by us
    release_lock(lock)


def test_acquire_retries_through_windows_delete_pending(tmp_path: Path, monkeypatch):
    # Regression: on Windows a releasing worker leaves the lockfile in
    # 'delete pending', so a concurrent O_EXCL create raises PermissionError
    # (EACCES), NOT FileExistsError. acquire_lock must WAIT through it, not error.
    import os as _os
    real_open = _os.open
    lock = _lock_path(tmp_path / "f.md")
    calls = {"n": 0}

    def flaky_open(path, flags, *a, **k):
        if str(path) == str(lock) and calls["n"] < 3:
            calls["n"] += 1
            raise PermissionError(13, "delete pending")
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(_os, "open", flaky_open)
    acquire_lock(lock, timeout=2.0, stale=999, poll=0.01)  # retries, does not raise
    assert lock.is_file()
    assert calls["n"] == 3
    release_lock(lock)


def test_acquire_permission_error_times_out_bounded(tmp_path: Path, monkeypatch):
    # A genuinely stuck PermissionError must time out (bounded), never hang.
    import os as _os
    lock = _lock_path(tmp_path / "f.md")
    monkeypatch.setattr(_os, "open",
                        lambda *a, **k: (_ for _ in ()).throw(PermissionError(13, "stuck")))
    with pytest.raises(LockTimeout):
        acquire_lock(lock, timeout=0.2, stale=999, poll=0.02)


def test_release_tolerates_transient_permission_error(tmp_path: Path, monkeypatch):
    lock = _lock_path(tmp_path / "f.md")
    lock.write_text("x", encoding="utf-8")
    real_unlink = Path.unlink
    calls = {"n": 0}

    def flaky_unlink(self, *a, **k):
        if calls["n"] < 2:
            calls["n"] += 1
            raise PermissionError(13, "transient")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    release_lock(lock)  # must not raise (it runs in a finally)
    assert calls["n"] == 2
    assert not lock.exists()


def test_write_verified_retries_transient_oserror(tmp_path: Path, monkeypatch):
    target = tmp_path / "t.md"
    real_wt = Path.write_text
    calls = {"n": 0}

    def flaky_wt(self, *a, **k):
        if calls["n"] < 2:
            calls["n"] += 1
            raise PermissionError(13, "transient")
        return real_wt(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", flaky_wt)
    write_text_verified(target, "hello\n")
    assert calls["n"] == 2
    assert target.read_text(encoding="utf-8") == "hello\n"


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

def test_cli_append_block_writes(tmp_path: Path):
    vault = make_vault(tmp_path)
    log = vault / "kb" / "logs" / "mentions.md"
    log.write_text("# Mentions candidate log\n", encoding="utf-8")
    r = run_cmd(vault, "append-block", "--file", "logs/mentions.md",
                "--entry", "## [2026-06-14] candidate-mention | foo\n- name: foo")
    assert r.returncode == 0, r.stderr
    assert "candidate-mention | foo" in log.read_text(encoding="utf-8")


def test_cli_dry_run_writes_nothing(tmp_path: Path):
    vault = make_vault(tmp_path)
    log = vault / "kb" / "logs" / "mentions.md"
    log.write_text("# Mentions candidate log\n", encoding="utf-8")
    before = log.read_text(encoding="utf-8")
    r = run_cmd(vault, "append-block", "--file", "logs/mentions.md",
                "--entry", "## entry\n- body", "--dry-run")
    assert r.returncode == 0
    assert log.read_text(encoding="utf-8") == before


def test_cli_consume_deletes_entry_file(tmp_path: Path):
    vault = make_vault(tmp_path)
    log = vault / "kb" / "logs" / "mentions.md"
    log.write_text("# Mentions candidate log\n", encoding="utf-8")
    entry_file = tmp_path / "entry.txt"
    entry_file.write_text("## [2026-06-14] candidate-mention | z\n- name: z", encoding="utf-8")
    r = run_cmd(vault, "append-block", "--file", "logs/mentions.md",
                "--entry-file", str(entry_file), "--consume")
    assert r.returncode == 0
    assert not entry_file.exists()
    assert "candidate-mention | z" in log.read_text(encoding="utf-8")


def test_cli_containment_guard_rejects_escape(tmp_path: Path):
    vault = make_vault(tmp_path)
    r = run_cmd(vault, "append-block", "--file", "../../escape.md", "--entry", "x")
    assert r.returncode == 1
    assert "escapes wiki_root" in r.stderr


# ---------------------------------------------------------------------------
# REAL concurrency — the done-gate C1 exercise
# ---------------------------------------------------------------------------

def _spawn_concurrent(vault: Path, payloads, build_args):
    """Launch len(payloads) CLI subprocesses simultaneously (barrier-synced)."""
    n = len(payloads)
    barrier = threading.Barrier(n)
    results: list[int | None] = [None] * n

    def worker(i: int):
        args = build_args(payloads[i])
        barrier.wait()  # release all at once → maximal lock contention
        proc = run_cmd(vault, *args)
        results[i] = proc.returncode

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_concurrent_block_appends_all_preserved(tmp_path: Path):
    vault = make_vault(tmp_path)
    log = vault / "kb" / "logs" / "mentions.md"
    log.write_text("# Mentions candidate log\n", encoding="utf-8")
    n = 12
    payloads = [
        f"## [2026-06-14 00:00] candidate-mention | name-{i:02d}\n- name: name-{i:02d}\n- classification: concept"
        for i in range(n)
    ]
    results = _spawn_concurrent(
        vault, payloads,
        lambda p: ("append-block", "--file", "logs/mentions.md", "--entry", p),
    )
    assert all(rc == 0 for rc in results), results
    content = log.read_text(encoding="utf-8")
    # every concurrent append survived — none clobbered
    for i in range(n):
        assert f"name-{i:02d}" in content, f"lost append name-{i:02d}"
    assert content.count("candidate-mention | name-") == n


def test_concurrent_row_appends_all_preserved(tmp_path: Path):
    vault = make_vault(tmp_path)
    queue = vault / "kb" / "pending-topic-updates.md"
    queue.write_text(QUEUE_FIXTURE, encoding="utf-8")
    n = 12
    payloads = [
        f"| wiki/sources/o/src-{i:02d}.md | topic-{i:02d}.md | semantic:0.{i:02d} | Timeline | bullet {i:02d}. — [[src-{i:02d}.md]] |  |"
        for i in range(n)
    ]
    results = _spawn_concurrent(
        vault, payloads,
        lambda p: ("append-row", "--file", "pending-topic-updates.md",
                   "--section", "Pending topic updates", "--row", p,
                   "--dedupe-cols", "0,1"),
    )
    assert all(rc == 0 for rc in results), results
    content = queue.read_text(encoding="utf-8")
    lines = content.split("\n")
    ledger_hdr = lines.index("## Rejected ledger")
    for i in range(n):
        # every row survived AND landed in the pending section (before the ledger)
        idx = next((j for j, ln in enumerate(lines) if f"topic-{i:02d}.md" in ln), None)
        assert idx is not None, f"lost row topic-{i:02d}.md"
        assert idx < ledger_hdr, f"row topic-{i:02d}.md landed in the wrong section"
    # the pre-existing ledger row is untouched
    assert any("declined-topic.md" in ln for ln in lines[ledger_hdr:])
