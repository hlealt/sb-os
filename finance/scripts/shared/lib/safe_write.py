"""Atomic file writes — write-to-temp-then-rename.

A half-written file is never visible to a reader: content is written to a
temp file in the same directory, flushed + fsync'd, then atomically renamed
over the destination via os.replace (atomic on the same filesystem on both
POSIX and Windows). If the writer is interrupted mid-write, the destination
either keeps its prior content or does not exist — it is never truncated or
partial.

This is the safe-write half of the S9 snapshot-triplet decision (p3-4).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable


def atomic_write(path: Path, write_fn: Callable[[Any], None], *,
                 encoding: str = "utf-8", newline: str | None = "") -> None:
    """Write to `path` atomically by writing to a temp file then renaming.

    `write_fn` receives an open text file handle and writes the full content.
    The temp file is created in the destination's directory so the final
    os.replace is a same-filesystem rename (atomic).

    On any exception during the write, the temp file is removed and the
    destination is left untouched.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline=newline) as f:
            write_fn(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Atomically write a string to `path`."""
    atomic_write(path, lambda f: f.write(text), encoding=encoding, newline="")


def atomic_write_json(path: Path, obj: Any, *, indent: int = 2,
                      ensure_ascii: bool = False) -> None:
    """Atomically write `obj` as JSON to `path`."""
    atomic_write(
        path,
        lambda f: json.dump(obj, f, indent=indent, ensure_ascii=ensure_ascii),
        newline="",
    )
