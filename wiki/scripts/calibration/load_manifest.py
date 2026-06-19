#!/usr/bin/env python3
"""Consumer-side loader for the thin-page detector ground-truth manifest.

Tasks p2-2 / p2-3 / p2-4 import this instead of parsing the JSON by hand — it
enforces the cal/test discipline (a `gold_test()` call is the ONLY way to reach
the held-out split, so a calibration loop physically cannot pull test pages by
accident) and exposes the records as light dataclasses.

    from load_manifest import Manifest
    M = Manifest.load()                     # default manifest path
    for a in M.ablations():                 # synthetic thin pages + exact ground truth
        report = my_detector(a.ablated_page)
        recall = a.recall_of(report.missing_texts)
    for g in M.gold_cal():                  # calibration gold ONLY (tune here)
        ...
    # final measurement, run ONCE, never in a tuning loop:
    for g in M.gold_test():                 # HELD-OUT gold (never tune on these)
        ...

CLI (sanity view):
    python load_manifest.py                 # prints a summary + the cal/test split
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MANIFEST = Path(__file__).resolve().parent / "data" / "ground-truth-manifest.json"


@dataclass
class DeletedItem:
    cls: str
    text: str
    section: str
    span: tuple[int, int]
    note: str = ""


@dataclass
class Ablation:
    kind: str
    origin: str
    source_page: str
    raw_path: str | None
    grade: float
    ablated_page: str
    source_sha256: str
    deleted: list[DeletedItem]
    class_counts: dict
    label: str = "thin"

    def missing_texts(self) -> list[str]:
        return [d.text for d in self.deleted]

    def recall_of(self, reported_missing: list[str]) -> float:
        """Fraction of the ground-truth deleted items present (substring-insensitive)
        in a detector's reported-missing list. A convenience for the detector tasks;
        each task may use a stricter matcher."""
        if not self.deleted:
            return 1.0
        rep = [r.lower() for r in reported_missing]
        hit = sum(1 for d in self.deleted if any(d.text.lower() in r or r in d.text.lower() for r in rep))
        return hit / len(self.deleted)


@dataclass
class Gold:
    page: str
    raw: str
    kind: str
    label: str          # thin | faithful
    split: str          # cal | test
    check: str          # deep | signal
    missing: list[str] = field(default_factory=list)
    retained: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def is_thin(self) -> bool:
        return self.label == "thin"


class Manifest:
    def __init__(self, raw: dict):
        self.schema = raw.get("schema", "")
        self._ablations = [
            Ablation(
                kind=a["kind"], origin=a["origin"], source_page=a["source_page"],
                raw_path=a.get("raw_path"), grade=a["grade"], ablated_page=a["ablated_page"],
                source_sha256=a["source_sha256"],
                deleted=[DeletedItem(d["cls"], d["text"], d["section"], tuple(d["span"]), d.get("note", ""))
                         for d in a["deleted"]],
                class_counts=a.get("class_counts", {}), label=a.get("label", "thin"),
            )
            for a in raw.get("ablations", [])
        ]
        self._gold = [
            Gold(page=g["page"], raw=g["raw"], kind=g["kind"], label=g["label"],
                 split=g["split"], check=g.get("check", ""), missing=g.get("missing", []),
                 retained=g.get("retained", []), note=g.get("note", ""))
            for g in raw.get("gold", [])
        ]

    @classmethod
    def load(cls, path: str | Path = DEFAULT_MANIFEST) -> "Manifest":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    # --- ablations -----------------------------------------------------
    def ablations(self, kind: str | None = None, grade: float | None = None) -> list[Ablation]:
        out = self._ablations
        if kind is not None:
            out = [a for a in out if a.kind == kind]
        if grade is not None:
            out = [a for a in out if a.grade == grade]
        return out

    # --- gold, split-disciplined --------------------------------------
    def gold_cal(self, kind: str | None = None) -> list[Gold]:
        """Calibration gold — the ONLY gold you may tune thresholds on."""
        return [g for g in self._gold if g.split == "cal" and (kind is None or g.kind == kind)]

    def gold_test(self, kind: str | None = None) -> list[Gold]:
        """HELD-OUT gold — final precision/recall only. NEVER tune on these."""
        return [g for g in self._gold if g.split == "test" and (kind is None or g.kind == kind)]

    def gold_all(self) -> list[Gold]:
        return list(self._gold)


def _summary() -> str:
    from collections import Counter
    M = Manifest.load()
    ak = Counter(a.kind for a in M.ablations())
    gc = Counter((g.kind, g.label) for g in M.gold_all())
    lines = [
        f"manifest schema: {M.schema}",
        f"ablations: {len(M.ablations())} fixtures "
        f"({len({a.source_page for a in M.ablations()})} pages x grades) by kind={dict(ak)}",
        f"gold: {len(M.gold_all())} pairs | cal={len(M.gold_cal())} test={len(M.gold_test())}",
        f"  gold kind x label: " + ", ".join(f"{k}/{l}={v}" for (k, l), v in sorted(gc.items())),
        "  (test split is held out — load via gold_test(), never in a tuning loop)",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(_summary())
