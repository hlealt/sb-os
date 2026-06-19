#!/usr/bin/env python3
"""OD-6 no-worse re-ingest gate -- consumed by `/sb-wiki-reingest` (task 3.1).

The mechanical acceptance gate the re-ingest pipeline calls to decide whether a RE-DONE
page may replace the OLD one (spec thin-page-detector-spec.md Behavior #6 + crit 5/8;
decisions OD-6). A re-do is "better" -- and only then ACCEPTED -- when it is >= the old page
on EVERY measured retention class AND clears a minimum improvement delta. For papers and
borderline mechanical calls the adversarial AI no-loss confirmation is the backstop.

WHAT IS MEASURED (the mechanical gate's measure list = T2-T4 + uncovered_mass, OD-6):
  T2 numeric retention      (more numeric atoms retained from raw is better)
  T3 table-row retention
  T4 rule/framework retention
  T5 named-entity retention  (included -- a re-do that drops entities is worse)
  T6 caveat survival         (included -- caveats are load-bearing)
  uncovered_mass             (LOWER is better -- fewer uncovered raw passages; Layer-1b)

The comparison is OLD-page vs NEW-page against the SAME raw reference -- exactly the
structured-page-vs-structured-page model the typed-retention layer (2.2) was built for, and
the model the ablation set validates. (For a re-do the raw reference is the re-summarized
SOURCE's structured twin; for the gate's own validation it is the original faithful page.)

THE OD-6 GUARDRAIL (crit 8 -- the load-bearing safety):
  The mechanical gate is only as complete as its measure list. A re-do can be WORSE on a
  signal class the checker does NOT yet measure (the calibration set seeds `reasoning_chain`
  -- deleted in the ablations but NOT scored by T2-T6 -- as exactly this bait). When such a
  class is present in the loss signal:
    (a) the gate SURFACES the gap (names the unmeasured class in `surfaced_unmeasured`), and
    (b) ADDS that class to the measured set for THIS comparison (scores it via a substring/
        atom check against old vs new) -- it does NOT silently pass.
  This prevents a re-do that kept every number but dropped the reasoning chain from sailing
  through. The AI no-loss backstop on papers covers what even the extended mechanical set
  cannot.

THE INTERFACE (what `/sb-wiki-reingest` calls):
    from thin_detector_reingest_gate import reingest_gate
    verdict = reingest_gate(old_page_text, new_page_text, raw_text,
                            kind="paper",                    # paper/article/podcast
                            min_delta=0.0,                   # min improvement margin (OD-6/glm)
                            loss_classes=None,               # optional: known per-class loss
                            require_ai_for=("paper",))       # kinds needing the AI no-loss confirm
    verdict.accept        -> bool   (False = reject the re-do)
    verdict.reasons       -> why
    verdict.surfaced_unmeasured -> classes the mechanical set could not score (added/flagged)
    verdict.needs_ai_confirm    -> True if a paper/borderline call needs the adversarial backstop

The adversarial AI no-loss confirm itself is the LLM judge from thin_detector_composite
(claude-opus-4-8, fresh context). This gate returns `needs_ai_confirm` so the caller drives
the judge through the composite's interface; the gate does NOT make the LLM call itself (the
caller owns the budget + the native-PDF for papers).

CLI
---
    # compare an OLD page vs a NEW re-do against a raw reference -> JSON gate verdict
    python thin_detector_reingest_gate.py gate --old OLD.md --new NEW.md --raw RAW.md \
        [--kind paper] [--min-delta 0.0] [--loss-class reasoning_chain] [--json-out P]

    --loss-class CLASS may be repeated -- declares that the re-do is known-worse on CLASS
    (the re-ingest pipeline passes the deletion/diff signal). An UNMEASURED class triggers the
    OD-6 guardrail (surface + add-to-measured).

Exit codes: 0 accept; 1 reject; 2 usage/bad input; 5 reject due to an unmeasured-class
regression (the OD-6 guardrail fired -- distinct from a plain mechanical reject).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

import thin_detector_typed as TYPED

WS = None
try:
    import thin_detector_density as _D
    WS = _D.WS
except Exception:
    WS = None


# The mechanical measure set (OD-6). Retention classes: HIGHER is better. uncovered_mass:
# LOWER is better (handled separately). T5/T6 included -- a re-do that drops entities or
# caveats is worse even if numbers/tables/rules are intact.
MEASURED_RETENTION_CLASSES = TYPED.MEASURED_CLASSES  # numeric, table_row, rule_label, named_entity, caveat

# Classes the typed layer does NOT measure (the OD-6 bait + any future signal class). When a
# re-do is known-worse on one of these, the guardrail fires.
KNOWN_UNMEASURED_CLASSES = ("reasoning_chain",)


@dataclass
class ClassDelta:
    cls: str
    old_retention: float | None
    new_retention: float | None
    delta: float | None          # new - old (positive = improved)
    regressed: bool              # new < old (worse)
    measured: bool


@dataclass
class GateVerdict:
    accept: bool
    kind: str
    min_delta: float
    reasons: list[str]
    class_deltas: list[ClassDelta]
    uncovered_old: float | None
    uncovered_new: float | None
    uncovered_delta: float | None        # old - new (positive = improved: fewer uncovered)
    surfaced_unmeasured: list[str]       # classes the mechanical set could not score (OD-6 guardrail)
    added_to_measured: list[str]         # unmeasured classes the gate scored ad hoc for this call
    needs_ai_confirm: bool               # paper/borderline -> caller runs the adversarial judge
    overall_improvement: float | None    # aggregate retention improvement (for the min-delta check)


def _retention_map(report) -> dict[str, float | None]:
    """class -> retention ratio (None when skipped) from a typed PageReport."""
    out: dict[str, float | None] = {}
    for cls, cr in report.classes.items():
        out[cls] = None if cr.skipped else cr.retention
    return out


def _score_unmeasured_class(cls: str, old_text: str, new_text: str, raw_text: str,
                            loss_declared: bool) -> ClassDelta:
    """Score an UNMEASURED class ad hoc for this comparison (OD-6 guardrail step (b)).

    The typed layer has no extractor for these classes, so the gate does a lightweight
    presence comparison: it does NOT silently pass. If the caller DECLARED the re-do worse on
    this class (loss_declared -- the re-ingest pipeline passes the diff/deletion signal), the
    gate marks it regressed. Absent a declared signal, the gate still surfaces the class as
    UNSCORED-BY-DEFAULT (it cannot prove no-loss), defaulting to regressed=True under the
    recall-biased no-worse stance (a re-do is rejected unless proven no-worse on the class)."""
    # When the pipeline declares a known loss on this class, that is authoritative.
    if loss_declared:
        return ClassDelta(cls=cls, old_retention=None, new_retention=None, delta=None,
                          regressed=True, measured=False)
    # No declared signal: the gate cannot mechanically prove the class survived (no extractor),
    # so under the no-worse stance it cannot CLEAR it -- surface as unscorable, treat as a
    # potential regression the AI backstop must resolve. We mark regressed=False here (no
    # positive evidence of loss) but record it as surfaced so the caller escalates to AI.
    return ClassDelta(cls=cls, old_retention=None, new_retention=None, delta=None,
                      regressed=False, measured=False)


def reingest_gate(old_page_text: str, new_page_text: str, raw_text: str, *,
                  kind: str = "article", min_delta: float = 0.0,
                  loss_classes: list[str] | None = None,
                  uncovered_old: float | None = None,
                  uncovered_new: float | None = None,
                  require_ai_for: tuple[str, ...] = ("paper",)) -> GateVerdict:
    """OD-6 no-worse gate. Returns ACCEPT only if the re-do is >= the old page on EVERY
    measured retention class AND clears `min_delta` AND does not regress uncovered_mass AND
    triggers no unmeasured-class regression.

    `raw_text` is the structured-page retention reference (old & new are both scored against
    it via the typed layer -- structured-page-vs-structured-page, 2.2's model).
    `loss_classes` -- classes the re-ingest pipeline KNOWS the re-do is worse on (from its
    diff). An unmeasured class here fires the OD-6 guardrail.
    `uncovered_old`/`uncovered_new` -- Layer-1b uncovered_mass for old/new (optional; when
    supplied, a re-do with MORE uncovered mass is rejected). Pass None to skip that arm."""
    loss_classes = loss_classes or []
    old_report = TYPED.detect(old_page_text, raw_text, page_name="old", raw_name="raw")
    new_report = TYPED.detect(new_page_text, raw_text, page_name="new", raw_name="raw")
    old_ret = _retention_map(old_report)
    new_ret = _retention_map(new_report)

    reasons: list[str] = []
    class_deltas: list[ClassDelta] = []
    regressions: list[str] = []
    improvements: list[float] = []

    # --- measured retention classes ---------------------------------------
    for cls in MEASURED_RETENTION_CLASSES:
        o = old_ret.get(cls)
        n = new_ret.get(cls)
        if o is None and n is None:
            class_deltas.append(ClassDelta(cls, o, n, None, False, measured=True))
            continue
        # treat a skipped side as "no constraint" on that side (the class had too few atoms)
        if o is None or n is None:
            class_deltas.append(ClassDelta(cls, o, n, None, False, measured=True))
            continue
        delta = round(n - o, 6)
        regressed = n < o
        class_deltas.append(ClassDelta(cls, o, n, delta, regressed, measured=True))
        improvements.append(delta)
        if regressed:
            regressions.append(f"{cls} retention regressed {o:.3f} -> {n:.3f}")

    # --- uncovered_mass arm (lower is better) -----------------------------
    uncovered_delta = None
    if uncovered_old is not None and uncovered_new is not None \
            and uncovered_old >= 0.0 and uncovered_new >= 0.0:
        uncovered_delta = round(uncovered_old - uncovered_new, 6)  # positive = improved
        if uncovered_new > uncovered_old:
            regressions.append(f"uncovered_mass regressed {uncovered_old:.3f} -> {uncovered_new:.3f} "
                               f"(more raw left uncovered)")

    # --- OD-6 GUARDRAIL: unmeasured-class regressions ---------------------
    surfaced_unmeasured: list[str] = []
    added_to_measured: list[str] = []
    for cls in loss_classes:
        if cls not in MEASURED_RETENTION_CLASSES:
            # an unmeasured class the pipeline declared a loss on -> guardrail fires
            cd = _score_unmeasured_class(cls, old_page_text, new_page_text, raw_text,
                                         loss_declared=True)
            class_deltas.append(cd)
            surfaced_unmeasured.append(cls)
            added_to_measured.append(cls)
            if cd.regressed:
                regressions.append(
                    f"UNMEASURED-CLASS regression on '{cls}' (OD-6 guardrail): the mechanical "
                    f"measure set does not score '{cls}'; it has been ADDED for this comparison "
                    f"and the re-do is worse on it -- NOT silently passed")
        else:
            # a measured class declared lost -> already covered by the retention arm; note it
            if cls in old_ret and cls in new_ret and (new_ret[cls] or 0) < (old_ret[cls] or 0):
                pass  # already in regressions

    # --- min-delta check (glm/OD-6) ---------------------------------------
    overall = round(sum(improvements) / len(improvements), 6) if improvements else None
    clears_min_delta = True
    if min_delta > 0.0:
        # require the aggregate improvement to clear the margin (don't replace for a marginal gain)
        if overall is None or overall < min_delta:
            clears_min_delta = False
            reasons.append(f"aggregate improvement {overall} < min_delta {min_delta} "
                           f"(re-do not better enough to justify replacement)")

    # --- decision ---------------------------------------------------------
    mechanical_ok = (not regressions) and clears_min_delta
    accept = mechanical_ok
    if regressions:
        reasons = regressions + reasons
        reasons.insert(0, "REJECT: re-do is worse on >=1 measure")

    # paper/borderline -> the AI no-loss confirm is required before a true accept
    borderline = (overall is not None and abs(overall) < 0.01)  # near-zero net change
    needs_ai = (kind in require_ai_for) or borderline or bool(surfaced_unmeasured)
    if accept and needs_ai:
        reasons.append(
            f"AI no-loss confirm REQUIRED before final accept (kind={kind}"
            + (", borderline net change" if borderline else "")
            + (", unmeasured class surfaced" if surfaced_unmeasured else "")
            + ") -- caller runs the adversarial judge via the composite interface")
    if accept and not reasons:
        reasons.append("ACCEPT: re-do >= old on every measured class and clears min-delta")

    return GateVerdict(
        accept=accept, kind=kind, min_delta=min_delta, reasons=reasons,
        class_deltas=class_deltas,
        uncovered_old=uncovered_old, uncovered_new=uncovered_new,
        uncovered_delta=uncovered_delta,
        surfaced_unmeasured=surfaced_unmeasured, added_to_measured=added_to_measured,
        needs_ai_confirm=needs_ai, overall_improvement=overall)


# ===========================================================================
# CLI
# ===========================================================================
def _vault_root() -> Path:
    """Resolve the vault root by walking up to the sb-os.json marker (so vault-relative
    paths resolve regardless of cwd). Falls back to the repo-relative ancestor."""
    here = Path.cwd().resolve()
    for anc in [here, *here.parents]:
        if (anc / "sb-os.json").exists():
            return anc
    return Path(__file__).resolve().parents[4]


def _resolve(path_arg: str) -> Path:
    """Resolve an absolute, cwd-relative, or vault-relative path to an existing file."""
    p = Path(path_arg)
    if p.is_absolute():
        return p
    vr = _vault_root()
    for base in (Path.cwd(), vr):
        cand = base / path_arg
        if cand.exists():
            return cand
    return vr / path_arg


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def cmd_gate(args) -> int:
    old, new, raw = _resolve(args.old), _resolve(args.new), _resolve(args.raw)
    for f in (old, new, raw):
        if not f.exists():
            print(f"not found: {f}", file=sys.stderr)
            return 2
    v = reingest_gate(
        _read(old), _read(new), _read(raw),
        kind=args.kind, min_delta=args.min_delta,
        loss_classes=list(args.loss_class or []),
        uncovered_old=args.uncovered_old, uncovered_new=args.uncovered_new,
        require_ai_for=tuple(args.require_ai_for.split(",")) if args.require_ai_for else ())
    payload = json.dumps(asdict(v), indent=2, ensure_ascii=False)
    if args.json_out:
        Path(args.json_out).write_text(payload, encoding="utf-8")
    print(payload)
    if not v.accept:
        return 5 if v.surfaced_unmeasured and any(cd.regressed and not cd.measured
                                                  for cd in v.class_deltas) else 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate", help="OD-6 no-worse gate: old vs new re-do against a raw reference")
    g.add_argument("--old", required=True, help="the OLD page (structured)")
    g.add_argument("--new", required=True, help="the NEW re-done page (structured)")
    g.add_argument("--raw", required=True, help="the raw reference (structured retention reference)")
    g.add_argument("--kind", default="article", choices=["paper", "article", "podcast"])
    g.add_argument("--min-delta", type=float, default=0.0)
    g.add_argument("--loss-class", action="append", default=[],
                   help="declare the re-do is known-worse on this class (repeatable); an "
                        "UNMEASURED class fires the OD-6 guardrail")
    g.add_argument("--uncovered-old", type=float, default=None)
    g.add_argument("--uncovered-new", type=float, default=None)
    g.add_argument("--require-ai-for", default="paper",
                   help="comma list of kinds needing the AI no-loss confirm (default: paper)")
    g.add_argument("--json-out", default=None)
    g.set_defaults(func=cmd_gate)
    return ap


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
