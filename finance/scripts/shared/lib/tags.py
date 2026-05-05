"""Tag governance — accept / merge / reject + 3-return re-surface (spec T7).

Tags are a CROSS-CUTTING dimension independent of category. A transaction
carries zero-or-more tags stored as a semicolon-separated string in the
`tags` CSV column (data-model.md §1.3). Tag tokens are lowercase
kebab-case ASCII without ';' — see `is_valid_token`.

The rejected-tags log is append-only with a per-token return counter.
Once a rejected token's return_count reaches a non-zero multiple of 3
(3, 6, 9, ...), the caller re-surfaces it: "this came back — reconsider?"

Pure module except for `load_tags` and `save_tags` (the file-I/O boundary).
All other functions accept a `TagIndex` and return a NEW `TagIndex` —
never mutate inputs.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass
class TagIndex:
    """Indexed view of tags.json. Wraps the raw dict; pass through helpers."""

    raw: dict[str, Any]

    @property
    def tags(self) -> dict[str, dict[str, Any]]:
        return self.raw.setdefault("tags", {})

    @property
    def rejected(self) -> list[dict[str, Any]]:
        return self.raw.setdefault("rejected", [])

    def find_rejected(self, token: str) -> dict[str, Any] | None:
        for entry in self.rejected:
            if entry.get("token") == token:
                return entry
        return None


def is_valid_token(token: str) -> bool:
    """True iff token is lowercase kebab-case ASCII (^[a-z0-9][a-z0-9-]*$).

    Rejects empty, uppercase, spaces, semicolons, accents, special chars.
    Pure.
    """
    if not isinstance(token, str) or not token:
        return False
    return bool(_TOKEN_RE.match(token))


def load_tags(tags_json_path: Path) -> TagIndex:
    """Load tags.json into a TagIndex. If the file is empty/missing 'tags' or
    'rejected' keys, they are initialized to empty defaults."""
    with open(tags_json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    raw.setdefault("version", 1)
    raw.setdefault("tags", {})
    raw.setdefault("rejected", [])
    return TagIndex(raw=raw)


def save_tags(index: TagIndex, tags_json_path: Path) -> None:
    """Persist a TagIndex to disk. Side-effecting boundary."""
    tags_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tags_json_path, "w", encoding="utf-8") as f:
        json.dump(index.raw, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")


def _clone(index: TagIndex) -> TagIndex:
    return TagIndex(raw=copy.deepcopy(index.raw))


def accept_tag(
    token: str,
    label: str,
    notes: str,
    today: date,
    index: TagIndex,
) -> TagIndex:
    """Add a new accepted tag. Returns updated index (caller persists).

    If `token` is in `index.rejected`, it is REMOVED from rejected (acceptance
    on re-surface).

    Raises:
      ValueError if token fails is_valid_token.
      ValueError if token already exists in index.tags.

    Pure (input → output).
    """
    if not is_valid_token(token):
        raise ValueError(f"invalid tag token: {token!r}")
    new = _clone(index)
    if token in new.tags:
        raise ValueError(f"tag already accepted: {token!r}")
    entry: dict[str, Any] = {
        "label": label,
        "added": today.isoformat(),
    }
    if notes:
        entry["notes"] = notes
    new.tags[token] = entry
    new.raw["rejected"] = [r for r in new.rejected if r.get("token") != token]
    return new


def merge_tag(
    proposed_token: str,
    existing_token: str,
    today: date,
    index: TagIndex,
) -> TagIndex:
    """Merge proposed_token into existing_token. Returns updated index.

    No new entry is added; the proposed token is implicitly absorbed into
    the existing one. The caller writes existing_token to the transaction's
    tags column. Adds a note to existing tag if not already present.

    Raises:
      ValueError if existing_token not in index.tags.

    Pure.
    """
    if existing_token not in index.tags:
        raise ValueError(f"existing tag not found: {existing_token!r}")
    new = _clone(index)
    entry = new.tags[existing_token]
    note_line = f"merged({proposed_token}@{today.isoformat()})"
    existing_notes = entry.get("notes", "") or ""
    if note_line not in existing_notes:
        entry["notes"] = (existing_notes + "; " + note_line).lstrip("; ")
    return new


def reject_tag(
    token: str,
    reason: str,
    today: date,
    index: TagIndex,
) -> TagIndex:
    """Reject a tag. Returns updated index (caller persists).

    If token already in index.rejected: increment its return_count by 1.
    If token NOT in index.rejected: append entry with return_count=1.

    Raises:
      ValueError if token already in index.tags (must remove acceptance first).
      ValueError if token fails is_valid_token.

    NOTE: the caller MUST check `should_resurface` BEFORE calling reject_tag
    again on a previously-rejected token — re-surface fires when the new
    return_count would cross a multiple of 3.

    Pure.
    """
    if not is_valid_token(token):
        raise ValueError(f"invalid tag token: {token!r}")
    if token in index.tags:
        raise ValueError(
            f"tag is already accepted: {token!r} — remove from tags first"
        )
    new = _clone(index)
    existing = new.find_rejected(token)
    if existing is not None:
        existing["return_count"] = int(existing.get("return_count", 0)) + 1
        # Keep first-rejection date and reason; only update return_count.
    else:
        new.raw["rejected"].append(
            {
                "token": token,
                "date": today.isoformat(),
                "reason": reason,
                "return_count": 1,
            }
        )
    return new


def should_resurface(token: str, index: TagIndex) -> bool:
    """True iff token is in `rejected` AND return_count is a non-zero
    multiple of 3 (3, 6, 9, ...). Caller checks BEFORE calling reject_tag
    again on the same token.

    Pure.
    """
    entry = index.find_rejected(token)
    if entry is None:
        return False
    rc = int(entry.get("return_count", 0) or 0)
    return rc > 0 and rc % 3 == 0


def parse_tag_column(value: str) -> list[str]:
    """Split semicolon-separated tag column into a list of tokens.

    Empty string → []. No trimming is applied (valid tokens never carry
    surrounding whitespace).

    Pure.
    """
    if not value:
        return []
    return [tok for tok in value.split(";") if tok]


def serialize_tag_column(tokens: list[str]) -> str:
    """Join a list of tokens with ';'. Inverse of `parse_tag_column`.

    Validates each token via is_valid_token; raises ValueError on any invalid
    token (prevents storing malformed data).

    Pure.
    """
    for tok in tokens:
        if not is_valid_token(tok):
            raise ValueError(f"invalid tag token in serialize: {tok!r}")
    return ";".join(tokens)
