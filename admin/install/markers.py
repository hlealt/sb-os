"""Marker block parser/replacer for sb-os managed files.

Implements the marker block protocol from architecture §6: every managed
CLAUDE.md and the shipped Home.md wraps installer-managed content in HTML
comments::

    <!-- sb:start v=1 -->
    [managed content]
    <!-- sb:end -->

On `--upgrade` the installer replaces content BETWEEN the markers verbatim;
content OUTSIDE the markers is user-owned and preserved.

This module is pure stdlib (re, typing) — no third-party dependencies.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict


CURRENT_VERSION = 1

# Capture the version digit so the parser can detect future-format files.
# Patterns are anchored on FULL LINES (re.MULTILINE) so a marker comment must
# occupy its own line. This prevents accidental matches when the source's
# documentation comment references the literal marker text inline (e.g.
# "Content INSIDE `<!-- sb:start v=1 -->` is overwritten ...").
_START_RE = re.compile(r"^[ \t]*<!--\s*sb:start\s+v=(\d+)\s*-->[ \t]*$", re.MULTILINE)
_END_RE = re.compile(r"^[ \t]*<!--\s*sb:end\s*-->[ \t]*$", re.MULTILINE)


class MissingMarkersError(Exception):
    """Raised when an --upgrade target lacks the expected marker block.

    The message includes the file path and a remediation hint so the CLI
    layer can surface it directly to the user (per architecture §6:
    "If markers are missing on --upgrade ... installer aborts with a clear
    error and instructions").
    """


class MarkerVersionError(Exception):
    """Raised when a managed file uses a marker version this installer cannot
    process. Future migration story lives here."""


class ManagedBlock(TypedDict):
    prefix: str
    managed: str
    suffix: str
    version: int


def parse(file_text: str) -> tuple[str, str, str] | None:
    """Split file text into (prefix, managed, suffix).

    Returns None when either marker is absent. The managed slice excludes
    the marker comment lines themselves; prefix/suffix preserve everything
    outside verbatim, including the markers and their surrounding newlines.
    """
    start_match = _START_RE.search(file_text)
    if start_match is None:
        return None
    end_match = _END_RE.search(file_text, start_match.end())
    if end_match is None:
        return None
    prefix = file_text[: start_match.end()]
    managed = file_text[start_match.end() : end_match.start()]
    suffix = file_text[end_match.start() :]
    return prefix, managed, suffix


def read_managed(path: Path | str) -> ManagedBlock:
    """Read a managed file and return its prefix/managed/suffix/version.

    Raises MissingMarkersError when markers are absent or malformed,
    and MarkerVersionError when the marker version is unsupported.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    start_match = _START_RE.search(text)
    if start_match is None:
        raise MissingMarkersError(
            f"{p}: missing '<!-- sb:start v=N -->' marker. "
            "Re-add the marker pair around the sb-os-managed section, "
            "or delete the file and re-run install to regenerate."
        )
    end_match = _END_RE.search(text, start_match.end())
    if end_match is None:
        raise MissingMarkersError(
            f"{p}: found '<!-- sb:start v=... -->' but no '<!-- sb:end -->'. "
            "Restore the closing marker, then re-run --upgrade."
        )
    version = int(start_match.group(1))
    if version != CURRENT_VERSION:
        raise MarkerVersionError(
            f"{p}: marker version v={version} is not supported by this "
            f"installer (expected v={CURRENT_VERSION}). Migration not yet "
            "implemented — open an issue at the sb-os repo."
        )
    return ManagedBlock(
        prefix=text[: start_match.end()],
        managed=text[start_match.end() : end_match.start()],
        suffix=text[end_match.start() :],
        version=version,
    )


def replace(file_text: str, new_inside: str) -> str:
    """Return file_text with marker-enclosed content replaced.

    Raises MissingMarkersError when either marker is absent.
    Content outside the markers is preserved verbatim.
    """
    parts = parse(file_text)
    if parts is None:
        raise MissingMarkersError(
            "Cannot replace managed block: marker pair is missing or malformed."
        )
    prefix, _, suffix = parts
    return prefix + new_inside + suffix


def replace_managed(
    path: Path | str, new_managed_content: str, version: int = CURRENT_VERSION
) -> None:
    """Replace marker-enclosed content in `path` with new_managed_content.

    Raises MissingMarkersError when markers are absent and
    MarkerVersionError when the file's marker version is unsupported.
    The version arg lets a future migration write a different version
    while still validating the existing file's version on read.
    """
    if version != CURRENT_VERSION:
        raise MarkerVersionError(
            f"replace_managed called with version={version}; only "
            f"v={CURRENT_VERSION} is currently supported."
        )
    p = Path(path)
    block = read_managed(p)  # raises if missing or wrong version
    new_text = block["prefix"] + new_managed_content + block["suffix"]
    p.write_text(new_text, encoding="utf-8")


def validate_markers(path: Path | str) -> None:
    """Raise MissingMarkersError or MarkerVersionError if the file at `path`
    is not a valid managed file. Returns None on success."""
    read_managed(path)


def extract_inside(text: str) -> str:
    """Return the content between markers in ``text``.

    Source files in ``sb-os/claude-mds/`` and ``sb-os/dashboards/`` carry the
    full installable structure — outer documentation comments, the marker
    pair, the managed content, and a trailing user-content placeholder. The
    installer needs the *inside-marker* slice when refreshing a target's
    marker block; this helper extracts it.

    When the text has no marker pair, return the text verbatim — the caller
    decides how to treat marker-less sources (fresh-install wrap-up, abort,
    etc.).
    """
    parts = parse(text)
    if parts is None:
        return text
    _prefix, managed, _suffix = parts
    return managed


def wrap(inside_content: str, version: int = CURRENT_VERSION) -> str:
    """Produce a complete marker block string (for fresh-install writes)."""
    if version != CURRENT_VERSION:
        raise MarkerVersionError(
            f"wrap called with version={version}; only "
            f"v={CURRENT_VERSION} is currently supported."
        )
    # Inside content is sandwiched between newlines so the marker comments
    # always occupy their own line, regardless of inside_content shape.
    inner = inside_content if inside_content.startswith("\n") else "\n" + inside_content
    if not inner.endswith("\n"):
        inner = inner + "\n"
    return f"<!-- sb:start v={version} -->{inner}<!-- sb:end -->"
