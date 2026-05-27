"""Regression tests for the atomic safe-write helper (p3-4 / S9).

Contracts tested:
  P3-4-SW-A  atomic_write_json writes a readable, correct JSON file.
  P3-4-SW-B  a failed write (exception in write_fn) leaves the prior content
             intact and leaves NO partial temp file behind — a half-written
             file is never visible.
  P3-4-SW-C  atomic_write_text round-trips a string.
  P3-4-SW-D  atomic_write creates parent directories as needed.
"""
from __future__ import annotations

import json

import pytest

from lib.safe_write import atomic_write, atomic_write_json, atomic_write_text


def test_atomic_write_json_roundtrip(tmp_path):
    path = tmp_path / "out.json"
    atomic_write_json(path, {"a": 1, "b": ["x", "y"]})
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1, "b": ["x", "y"]}


def test_failed_write_leaves_prior_content_and_no_temp(tmp_path):
    path = tmp_path / "out.json"
    atomic_write_text(path, "original")

    def _boom(f):
        f.write("partial-")
        raise RuntimeError("interrupted mid-write")

    with pytest.raises(RuntimeError):
        atomic_write(path, _boom)

    # Destination keeps its prior content — never truncated/partial.
    assert path.read_text(encoding="utf-8") == "original"
    # No leftover atomic-write temp files (.out.json.*.tmp) in the directory.
    leftovers = [p for p in tmp_path.iterdir()
                 if p.name.startswith(".out.json.") and p.name.endswith(".tmp")]
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_atomic_write_text_roundtrip(tmp_path):
    path = tmp_path / "note.txt"
    atomic_write_text(path, "hello world")
    assert path.read_text(encoding="utf-8") == "hello world"


def test_atomic_write_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "deep" / "out.json"
    atomic_write_json(path, {"ok": True})
    assert path.exists()
