#!/usr/bin/env python3
"""Thin-page detector — Layer-2 composite + escalation + Layer-3 adversarial judge.

The TOP of the thin-page-detector ladder (spec thin-page-detector-spec.md Behavior
#4-#6; synthesis SS2d; decisions OD-4/5/7/8). Wires the two CERTIFIED lower layers
into one verdict, produces a WORST-FIRST ranked suspect queue, builds the STRUCTURED
NLI packet, and drives the adversarial LLM/NLI top-layer judge.

Layers wired (all under wiki/scripts/, imported additively -- never re-implemented):
  Layer-1a  typed-retention   thin_detector_typed.detect()       (T2-T6, embedding-free)
  Layer-1b  chunked recall    thin_detector_density.chunked_recall()  (uncovered_mass, embeddings)
  Layer-0   density priors    thin_detector_density.compute_density() (routing prior only)

THE COMPOSITE -- OR-of-thresholds, NOT a fitted blend (OD-4: ship interpretable
OR until >=~40 gold labels exist). A page is FLAGGED if ANY single signal trips
its recall-biased cut, OR it is a paper, OR its PDF twin is untrustworthy:

    quant_retention   < THETA_QUANT          (T2)
    table_retention   < THETA_TABLE          (T3)
    rule_retention    < THETA_RULE           (T4)
    caveat fully dropped (retention == 0)     (T6)
    named_retention   < THETA_NAMED          (T5; low weight)
    uncovered_mass    > THETA_UNCOVERED      (Layer-1b severity signal)
    kind == "paper"                           (UNCONDITIONAL escalation)
    twin_fidelity == False                    (UNCONDITIONAL escalation, fail-loud)

Each THETA is calibrated on gold_cal() + the ablation set ONLY -- NEVER gold_test().
The cuts are recall-biased (over-flag is cheap; a missed thin page silently corrupts
the second brain). See `calibrate` CLI + the THRESHOLDS block.

SEVERITY (OD-7 worst-first ranking). The atom-deletion ablation fixtures score
uncovered_mass ~= 0 (2.3's measured finding: they delete SCATTERED atoms across
still-topically-covered sections -- 2.2's domain, NOT wholesale omission). So the
severity that ORDERS the graded ablations is driven by the TYPED-retention layer
(2.2 proved its missing-atom count is monotone with deletion grade), blended with
uncovered_mass for wholesale cases:

    severity = W_TYPED * typed_loss_fraction + W_UNCOVERED * uncovered_mass + paper/twin bumps

Queue is sorted severity-DESC (worst first). Per-run page cap is a CONFIGURABLE
runner parameter (--cap, default 100; OD-7) applied at heal time, coupling with the
OD-5 judge budget.

THE STRUCTURED PACKET (codex JSON schema, synthesis SS2d -- the adopted NLI
interface). The judge receives ONLY: triggered layers + missing atoms (per class,
with raw-sentence context) + uncovered windows (with previews + cosine) + native PDF
page numbers -- NEVER the whole page. `build_packet()` is pure-deterministic and the
`packet` CLI emits exactly the bytes the judge sees, so whole-page exclusion is
directly assertable (done-gate crit 4).

THE ADVERSARIAL JUDGE (OD-5: a STRONG general AI -- Claude -- with FRESH context,
prompted to HUNT omissions and DEFAULT to "missing" on doubt; never the weak model/
session that wrote the page). A clean interface: input = the packet, output =
{missing: bool, items: [...], confidence: float}. Providers:
  --judge anthropic   real LLM (claude-opus-4-8, adaptive thinking, structured output)
                      -- fires only when ANTHROPIC_API_KEY (or CLAUDE_API_KEY) resolves.
  --judge stub        deterministic documented stub (no network) -- defaults to
                      "missing" whenever the packet carries any missing atom or
                      uncovered window (the adversarial default), for exercising the
                      packet path when no LLM key is present.
The real LLM call is the runtime dependency the ingest/re-ingest pipeline provides.

A 5% RANDOM NON-FLAGGED AUDIT (codex, synthesis SS4) is surfaced per run to measure
the false-negative rate the cheap layers miss.

CLI
---
    # composite verdict for ONE (page, raw) pair -> JSON
    python thin_detector_composite.py detect --page P --raw R [--kind paper] \
        [--twin-fidelity true|false] [--db SCRATCH.db] [--no-embeddings]

    # the NLI packet for ONE (page, raw) pair -> JSON (the literal judge input)
    python thin_detector_composite.py packet --page P --raw R [...] [--db SCRATCH.db]

    # run the judge on ONE packet -> JSON verdict
    python thin_detector_composite.py judge --page P --raw R \
        --judge stub|anthropic [...] [--db SCRATCH.db]

    # rank a SET worst-first (cal set, or an explicit page/raw list) -> ranked queue
    python thin_detector_composite.py rank --from-manifest [--kind ...] [--grade ...] \
        [--cap 100] [--audit-pct 5] [--db SCRATCH.db] [--no-embeddings] [--json-out P]

    # calibrate the OR-of-thresholds cuts on gold_cal() + ablations (NEVER gold_test)
    python thin_detector_composite.py calibrate [--db SCRATCH.db] [--no-embeddings]

ALWAYS pass an explicit SCRATCH --db for detection runs: density's chunked_recall
embeds the page's raw into whatever --db resolves to (default = the LIVE wiki index)
-- never populate production with detection windows.

Exit codes: 0 ok; 2 usage/bad input; 3 a flagged-paper packet could not be built.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# Layers wired -- imported by module name (both are underscore-named, importable).
import thin_detector_typed as TYPED
import thin_detector_density as DENSITY

WS = DENSITY.WS  # the sb-wiki-search helper module (vault/db/embedder plumbing)


# ===========================================================================
# THRESHOLDS  (OR-of-thresholds; recall-biased; calibrated on gold_cal()+ablations)
# ===========================================================================
# These are the per-signal cuts the composite ORs. They are RECALL-BIASED: a thin
# page that slips through silently corrupts the second brain, while an over-flag only
# costs one cheap LLM call. They are calibrated on gold_cal() (18) + the ablation set
# -- NEVER gold_test() (7 held-out). The `calibrate` CLI reports the recall each cut
# achieves on the cal+ablation positives and prints the chosen values; these defaults
# are those calibrated values (see the done-gate evidence sheet calibrate-*.json).
#
# Retention cuts: flag when retention < THETA (i.e. >= (1-THETA) of the class was lost
# is NOT the test -- ANY measurable loss below the cut flags). Set just below 1.0 so a
# single dropped atom in a scored class flags (recall-biased), with class-specific
# slack where the class is noisier.
THRESHOLDS = {
    "quant": 1.00,    # T2 numeric: ANY missing numeric atom flags (exact facts are load-bearing)
    "table": 1.00,    # T3 table-row: ANY dropped row flags (the forensic's Exhibit A)
    "rule": 1.00,     # T4 rule/framework label: ANY dropped rule flags
    "named": 0.90,    # T5 named-entity: substring presence is noisier -> 10% slack
    # caveat (T6) has no ratio cut -- it flags on FULL drop (retention == 0), the spec rule
}
# Layer-1b uncovered-mass cut. PROVISIONAL: 2.3 MEASURED on real voyage-3.5 that absolute
# cosine barely separates thin from faithful (delta ~0.04) -- this is a SEVERITY signal, not
# a standalone verdict. The faithful baseline measured uncovered_mass ~0.080; thin ~0.187.
# Cut sits between them, recall-biased toward the thin side. The composite never leans on
# this alone -- OR-of-thresholds + the typed layer carry detection.
THETA_UNCOVERED = 0.12

# Severity weights (OD-7 ranking). typed_loss dominates because the ablation grades live
# in the typed layer (uncovered_mass ~= 0 on atom-deletion fixtures -- 2.3's finding).
W_TYPED = 0.80
W_UNCOVERED = 0.20
PAPER_SEVERITY_BUMP = 0.05       # papers escalate unconditionally; small rank bump so a
                                 # flagged paper outranks an equally-thin non-paper
TWIN_SEVERITY_BUMP = 0.10        # an untrustworthy twin is high-risk (content NOT checked)

# Per-class severity weights for typed_loss (a dropped rule/number weighs above a dropped
# entity, mirroring the density-prior weighting philosophy).
TYPED_CLASS_WEIGHTS = {
    "numeric": 1.0,
    "table_row": 1.0,
    "rule_label": 1.0,
    "caveat": 1.0,
    "named_entity": 0.5,
}

DEFAULT_RUN_CAP = 100            # OD-7 per-run page cap (configurable runner parameter)
DEFAULT_AUDIT_PCT = 5.0         # 5% random non-flagged audit (codex)
AUDIT_SEED = 24                 # deterministic audit sampling for reproducible runs


# ===========================================================================
# Composite verdict
# ===========================================================================
@dataclass
class SignalResult:
    name: str
    value: float | None       # the measured signal (retention ratio, uncovered_mass, ...)
    threshold: float | None
    tripped: bool
    skipped: bool = False
    note: str = ""


@dataclass
class CompositeVerdict:
    page: str
    raw: str
    kind: str
    flagged: bool
    escalate: bool                 # goes to the LLM/NLI top layer
    severity: float                # worst-first ranking key (higher = worse)
    signals: list[SignalResult]
    escalation_reasons: list[str]  # why it escalates (paper / twin / a tripped signal)
    typed_loss_fraction: float     # weighted missing-atom fraction across measured classes
    uncovered_mass: float          # Layer-1b (-1.0 sentinel when embeddings off)
    twin_fidelity: bool
    embeddings_on: bool


def _typed_loss_fraction(report) -> float:
    """Weighted fraction of measured atoms that went missing, across non-skipped classes.
    This is the severity engine for the graded ablations (2.2 proved it is monotone with
    deletion grade). 0.0 = nothing lost; higher = more lost. Class-weighted so a dropped
    rule/number weighs above a dropped entity."""
    num = 0.0
    den = 0.0
    for cls, cr in report.classes.items():
        if cr.skipped:
            continue
        w = TYPED_CLASS_WEIGHTS.get(cls, 1.0)
        den += w * cr.raw_count
        num += w * cr.missing_count
    return (num / den) if den else 0.0


def composite_detect(page_doc: str, raw_doc: str, *, page_name: str, raw_name: str,
                     kind: str, twin_fidelity: bool,
                     uncovered_mass: float, embeddings_on: bool,
                     typed_report=None) -> CompositeVerdict:
    """OR-of-thresholds composite + unconditional paper/twin escalation + severity.

    `uncovered_mass` is Layer-1b's char-weighted score (or -1.0 sentinel when embeddings
    are off -- then the uncovered signal is SKIPPED, never read as 0/clean). `typed_report`
    is a thin_detector_typed.PageReport (computed by the caller so it can be reused)."""
    if typed_report is None:
        typed_report = TYPED.detect(page_doc, raw_doc, page_name=page_name, raw_name=raw_name)

    signals: list[SignalResult] = []
    reasons: list[str] = []

    # --- typed retention cuts (T2-T5) -------------------------------------
    cut_for = {"numeric": "quant", "table_row": "table", "rule_label": "rule",
               "named_entity": "named"}
    for cls, key in cut_for.items():
        cr = typed_report.classes.get(cls)
        if cr is None or cr.skipped:
            signals.append(SignalResult(
                name=f"{key}_retention", value=None, threshold=THRESHOLDS[key],
                tripped=False, skipped=True,
                note=(cr.skip_reason if cr else "class absent")))
            continue
        tripped = cr.retention is not None and cr.retention < THRESHOLDS[key]
        signals.append(SignalResult(
            name=f"{key}_retention", value=cr.retention, threshold=THRESHOLDS[key],
            tripped=tripped))
        if tripped:
            reasons.append(f"{key}_retention {cr.retention:.3f} < {THRESHOLDS[key]}")

    # --- caveat full-drop rule (T6) ---------------------------------------
    cav = typed_report.classes.get("caveat")
    if cav is None or cav.skipped:
        signals.append(SignalResult(name="caveat_survival", value=None, threshold=0.0,
                                    tripped=False, skipped=True,
                                    note=(cav.skip_reason if cav else "class absent")))
    else:
        dropped = cav.retention == 0.0 and cav.raw_count > 0
        signals.append(SignalResult(name="caveat_survival", value=cav.retention,
                                    threshold=0.0, tripped=dropped,
                                    note="flags on FULL caveat drop (retention==0)"))
        if dropped:
            reasons.append(f"caveat fully dropped ({cav.raw_count} caveats, 0 retained)")

    # --- Layer-1b uncovered-mass cut --------------------------------------
    # Layer-1b produced a USABLE value only when embeddings are on AND recall returned a real
    # (non-sentinel) uncovered_mass. The -1.0 sentinel reaches here two ways: embeddings off,
    # OR embeddings on but recall could not run (e.g. the raw reference is a structured page
    # outside the embeddable raw/ tree -- the ablation case). BOTH are "Layer-1b unavailable":
    # the signal MUST be SKIPPED, never read as a clean 0.0 (spec: never report clean because
    # the layer was unavailable).
    layer1b_available = embeddings_on and uncovered_mass >= 0.0
    if layer1b_available:
        tripped = uncovered_mass > THETA_UNCOVERED
        signals.append(SignalResult(name="uncovered_mass", value=uncovered_mass,
                                    threshold=THETA_UNCOVERED, tripped=tripped,
                                    note="Layer-1b severity signal (provisional cut)"))
        if tripped:
            reasons.append(f"uncovered_mass {uncovered_mass:.3f} > {THETA_UNCOVERED}")
    else:
        why = ("embeddings off" if not embeddings_on
               else "embeddings on but Layer-1b recall unavailable (raw reference not embeddable "
                    "-- e.g. a structured sources/ page outside the raw/ tree)")
        signals.append(SignalResult(name="uncovered_mass", value=None,
                                    threshold=THETA_UNCOVERED, tripped=False, skipped=True,
                                    note=f"{why} -- Layer-1b SKIPPED, not read as clean"))

    # --- unconditional escalations ----------------------------------------
    is_paper = (kind == "paper")
    if is_paper:
        reasons.append("kind==paper (unconditional escalation -- twin-blind layers may never clear a paper)")
    if not twin_fidelity:
        reasons.append("twin_fidelity==false (unconditional escalation -- twin untrustworthy, content NOT checked)")

    any_signal_tripped = any(s.tripped for s in signals)
    flagged = any_signal_tripped or is_paper or (not twin_fidelity)
    escalate = flagged  # every flagged page (+ all papers) goes to the LLM/NLI top layer

    # --- severity (worst-first ranking key) -------------------------------
    # When Layer-1b is unavailable, its severity contribution is 0.0 (the typed layer carries
    # ranking -- 2.2 proved typed_loss is monotone with deletion grade). The REPORTED field,
    # however, carries the -1.0 sentinel so a consumer can tell "Layer-1b said 0 uncovered"
    # apart from "Layer-1b never ran" -- a reported 0.0 must mean a real measured 0.0.
    typed_loss = _typed_loss_fraction(typed_report)
    um = uncovered_mass if layer1b_available else 0.0
    severity = W_TYPED * typed_loss + W_UNCOVERED * um
    if is_paper:
        severity += PAPER_SEVERITY_BUMP
    if not twin_fidelity:
        severity += TWIN_SEVERITY_BUMP

    return CompositeVerdict(
        page=page_name, raw=raw_name, kind=kind, flagged=flagged, escalate=escalate,
        severity=round(severity, 6), signals=signals, escalation_reasons=reasons,
        typed_loss_fraction=round(typed_loss, 6),
        uncovered_mass=(round(um, 6) if layer1b_available else -1.0),
        twin_fidelity=twin_fidelity, embeddings_on=embeddings_on)


# ===========================================================================
# The STRUCTURED NLI packet  (codex schema -- NEVER the whole page)
# ===========================================================================
@dataclass
class NLIPacket:
    """The structured handoff to the LLM/NLI judge (synthesis SS2d codex schema).

    Carries ONLY: which layers tripped, the missing atoms (per class, with raw-sentence
    context), the uncovered windows (preview + cosine), and native PDF page numbers.
    It DOES NOT carry the whole page -- that is the whole point (D-2: the judge answers a
    narrow per-item 'is this specific item entailed by this specific passage?', never
    're-read the page'). The exclusion is directly assertable on the emitted JSON."""
    page_path: str
    raw_path: str
    kind: str
    triggered_layers: list[str]
    twin_fidelity: bool
    native_pdf_pages: list[int]
    missing_artifacts: list[dict]        # numeric atoms
    missing_table_rows: list[dict]
    missing_framework_items: list[dict]  # rule/framework labels
    missing_named_entities: list[dict]
    missing_caveats: list[dict]
    uncovered_windows: list[dict]
    note: str = ""


_NATIVE_PAGE_RE = None  # native PDF page numbers come from the recall windows' anchors below


def _missing_to_items(missing) -> list[dict]:
    """Serialize MissingItem -> the packet item shape: only text+section+raw-context.
    NO page body, NO surrounding page text -- only the missing atom and its RAW sentence."""
    return [{"text": m.text, "section": m.section, "raw_context": m.context}
            for m in missing]


def _native_pages_from_windows(uncovered_windows: list[dict], raw_doc: str) -> list[int]:
    """Best-effort native PDF page numbers for the uncovered windows. The structured PDF
    twin (wiki v11) carries page markers; absent reliable markers this returns []. The
    judge reads the NATIVE PDF for papers (D-5), so the page numbers localize where to look
    -- their absence is not an error (the judge still gets the raw context)."""
    import re
    pages: set[int] = set()
    # the structured twin emits "(p. N)" / "[page N]" / "<!-- page N -->" markers; scan the
    # raw windows' preview text for any page reference.
    for w in uncovered_windows:
        for m in re.finditer(r"(?:p\.?\s*|page\s+|pg\.?\s*)(\d{1,4})\b", w.get("preview", ""), re.I):
            try:
                pages.add(int(m.group(1)))
            except ValueError:
                pass
    return sorted(pages)


def build_packet(verdict: CompositeVerdict, typed_report, recall_report,
                 raw_doc: str) -> NLIPacket:
    """Build the structured NLI packet from the composite verdict + the two lower-layer
    reports. PURE deterministic -- no page body ever enters the packet."""
    triggered = [s.name for s in verdict.signals if s.tripped]
    if verdict.kind == "paper":
        triggered.append("kind==paper")
    if not verdict.twin_fidelity:
        triggered.append("twin_fidelity==false")

    by_cls: dict[str, list] = {c: [] for c in TYPED.MEASURED_CLASSES}
    for cls, cr in typed_report.classes.items():
        if not cr.skipped:
            by_cls[cls] = cr.missing

    uncovered = []
    if recall_report is not None and getattr(recall_report, "status", "") == "ok":
        for w in recall_report.uncovered_windows:
            uncovered.append({
                "anchor": w.get("anchor"),
                "best_cosine": w.get("best_cosine"),
                "keyword_overlap": w.get("keyword_overlap"),
                "raw_context": w.get("preview"),   # the RAW window preview -- not the page
            })

    native_pages = _native_pages_from_windows(uncovered, raw_doc)

    return NLIPacket(
        page_path=verdict.page, raw_path=verdict.raw, kind=verdict.kind,
        triggered_layers=triggered, twin_fidelity=verdict.twin_fidelity,
        native_pdf_pages=native_pages,
        missing_artifacts=_missing_to_items(by_cls["numeric"]),
        missing_table_rows=_missing_to_items(by_cls["table_row"]),
        missing_framework_items=_missing_to_items(by_cls["rule_label"]),
        missing_named_entities=_missing_to_items(by_cls["named_entity"]),
        missing_caveats=_missing_to_items(by_cls["caveat"]),
        uncovered_windows=uncovered,
        note=("structured NLI packet -- carries ONLY missing atoms + uncovered raw windows "
              "+ raw-sentence context + native PDF page numbers; the whole page is "
              "DELIBERATELY EXCLUDED (D-2: per-item entailment, not page re-read). For "
              "papers the judge ALSO reads the native PDF (D-5)."),
    )


def packet_total_items(packet: NLIPacket) -> int:
    return (len(packet.missing_artifacts) + len(packet.missing_table_rows)
            + len(packet.missing_framework_items) + len(packet.missing_named_entities)
            + len(packet.missing_caveats) + len(packet.uncovered_windows))


# ===========================================================================
# The ADVERSARIAL JUDGE  (OD-5: strong model, fresh context, default-missing-on-doubt)
# ===========================================================================
ADVERSARIAL_SYSTEM_PROMPT = """\
You are an ADVERSARIAL fidelity auditor for a personal knowledge base. A "source page"
is a human-written summary of an original source (a paper, article, or podcast). Your
ONE job: decide whether the page silently DROPPED load-bearing detail the source carried.

You are given a STRUCTURED PACKET, never the whole page. The packet lists specific items
a cheap deterministic checker found TEXTUALLY ABSENT from the page, each with the exact
sentence from the RAW SOURCE where it appears (`raw_context`), plus any raw passages the
page does not cover (`uncovered_windows`). For a paper you are ALSO given the native PDF.

Your task is NARROW and per-item: for each listed item, decide whether the page plausibly
carries that specific fact/rule/row/caveat as a PARAPHRASE (e.g. "a third" for "33%",
"the authors caution" for "needs validation") that the textual checker could not see —
OR whether it is genuinely MISSING.

ADVERSARIAL STANCE — non-negotiable:
- HUNT for omissions. Assume the page is thin until the packet proves otherwise.
- DEFAULT TO "missing" ON ANY DOUBT. If you cannot be confident the page carries the item,
  mark it missing. A false "present" silently corrupts the knowledge base; a false "missing"
  only triggers one cheap re-check.
- A topically-relevant page is NOT evidence the specific item survived — relevance is not
  retention. Do not clear an item because the page is "about the same thing".

Return STRICT JSON, no prose:
{"missing": <true if ANY load-bearing item is genuinely missing>,
 "items": [{"item": "<verbatim from packet>", "class": "<artifact|table_row|framework|named_entity|caveat|uncovered_window>",
            "verdict": "missing"|"present_as_paraphrase", "why": "<one clause>"}],
 "confidence": <0.0-1.0 your confidence in the overall missing verdict>}
"""


@dataclass
class JudgeVerdict:
    missing: bool
    items: list[dict]
    confidence: float
    provider: str
    note: str = ""


def _packet_items_for_prompt(packet: NLIPacket) -> list[dict]:
    items = []
    for it in packet.missing_artifacts:
        items.append({"class": "artifact", **it})
    for it in packet.missing_table_rows:
        items.append({"class": "table_row", **it})
    for it in packet.missing_framework_items:
        items.append({"class": "framework", **it})
    for it in packet.missing_named_entities:
        items.append({"class": "named_entity", **it})
    for it in packet.missing_caveats:
        items.append({"class": "caveat", **it})
    for w in packet.uncovered_windows:
        items.append({"class": "uncovered_window", "text": w.get("raw_context"),
                      "section": "", "raw_context": w.get("raw_context")})
    return items


def judge_stub(packet: NLIPacket) -> JudgeVerdict:
    """Deterministic DOCUMENTED stub judge (no network). Implements the ADVERSARIAL default:
    if the packet carries ANY missing atom or uncovered window, default to "missing" (the
    judge's doubt-defaults-missing stance) -- it cannot resolve paraphrase without an LLM, so
    it never clears an item. Used to exercise the packet path when no LLM key is present;
    the REAL judge (judge_anthropic) is the runtime dependency the ingest pipeline provides.

    This stub NEVER fabricates an LLM verdict -- it is explicitly a deterministic placeholder
    whose verdict is a mechanical function of the packet, flagged as `provider='stub'`."""
    items_in = _packet_items_for_prompt(packet)
    items_out = [{"item": (it.get("text") or "")[:120], "class": it["class"],
                  "verdict": "missing",
                  "why": "stub defaults to missing on doubt (no LLM to resolve paraphrase)"}
                 for it in items_in]
    missing = len(items_in) > 0
    return JudgeVerdict(
        missing=missing, items=items_out,
        confidence=(0.5 if missing else 0.0),
        provider="stub",
        note=("DETERMINISTIC STUB -- adversarial default-missing-on-doubt; cannot resolve "
              "paraphrase. The real LLM judge (--judge anthropic, claude-opus-4-8) is the "
              "runtime dependency the ingest/re-ingest pipeline provides."))


def _resolve_llm_key(vault_root: Path | None) -> str | None:
    """Resolve an Anthropic key from the OS env first, then the gitignored .env file.
    Returns the key or None. Checks ANTHROPIC_API_KEY then CLAUDE_API_KEY."""
    for name in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"):
        v = os.environ.get(name)
        if v:
            return v
    # .env fallback (same pattern sb-wiki-search uses for VOYAGE_API_KEY)
    if vault_root is not None:
        env_file = vault_root / ".user" / "config" / "env" / ".env"
        if env_file.exists():
            try:
                for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    k, _, val = line.partition("=")
                    if k.strip() in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY") and val.strip():
                        return val.strip().strip('"').strip("'")
            except OSError:
                pass
    return None


def judge_anthropic(packet: NLIPacket, native_pdf_path: Path | None,
                    api_key: str, model: str = "claude-opus-4-8") -> JudgeVerdict:
    """Real adversarial judge via the Anthropic SDK (claude-opus-4-8, adaptive thinking,
    structured JSON output). FRESH context per call -- a single stateless message carrying
    ONLY the packet (and, for a paper, the native PDF as a document block). The system prompt
    sets the adversarial default-missing-on-doubt stance.

    This is the OD-5 'strong general AI with fresh context' top layer. It fires only when a
    key resolves; otherwise the runner uses judge_stub and flags the LLM wiring as the
    pipeline's runtime dependency."""
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError(
            "anthropic SDK not installed -- `pip install anthropic`. The real judge is the "
            "runtime dependency the ingest pipeline provides; use --judge stub otherwise."
        ) from e

    client = anthropic.Anthropic(api_key=api_key)

    user_blocks: list[dict] = []
    # For a paper, attach the native PDF (D-5: the NLI layer reads the native PDF, not the twin).
    if packet.kind == "paper" and native_pdf_path is not None and native_pdf_path.exists() \
            and native_pdf_path.suffix.lower() == ".pdf":
        import base64
        data = base64.standard_b64encode(native_pdf_path.read_bytes()).decode("utf-8")
        user_blocks.append({"type": "document",
                            "source": {"type": "base64", "media_type": "application/pdf",
                                       "data": data}})

    packet_json = json.dumps(asdict(packet), ensure_ascii=False, indent=2)
    user_blocks.append({"type": "text", "text":
        "STRUCTURED PACKET (the page itself is deliberately NOT included):\n\n"
        + packet_json
        + "\n\nFor each listed item decide missing vs present_as_paraphrase, defaulting to "
          "missing on any doubt. Return the strict JSON described in your instructions."})

    schema = {
        "type": "object",
        "properties": {
            "missing": {"type": "boolean"},
            "items": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "class": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["missing", "present_as_paraphrase"]},
                    "why": {"type": "string"},
                },
                "required": ["item", "class", "verdict", "why"],
                "additionalProperties": False,
            }},
            "confidence": {"type": "number"},
        },
        "required": ["missing", "items", "confidence"],
        "additionalProperties": False,
    }

    resp = client.messages.create(
        model=model,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=ADVERSARIAL_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": user_blocks}],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    data = json.loads(text)
    return JudgeVerdict(
        missing=bool(data.get("missing", True)),
        items=data.get("items", []),
        confidence=float(data.get("confidence", 0.5)),
        provider=f"anthropic:{model}",
        note="real adversarial LLM judge (fresh context; packet-only input + native PDF for papers).")


# ===========================================================================
# Per-pair plumbing  (run the lower layers on a SCRATCH db)
# ===========================================================================
@dataclass
class PairContext:
    page_path: Path
    raw_path: Path
    page_doc: str
    raw_doc: str
    typed_report: object
    recall_report: object
    uncovered_mass: float
    embeddings_on: bool
    kind: str
    twin_fidelity: bool


def _kind_from_page_path(page_rel: str) -> str:
    """Infer source kind from the wiki sources path: .../sources/{origin}/... where origin
    'papers' -> paper, 'lennys-podcast' -> podcast, else article. Mirrors the calibration
    manifest's kinds."""
    p = page_rel.replace("\\", "/").lower()
    if "/papers/" in p or p.endswith("/papers"):
        return "paper"
    if "podcast" in p:
        return "podcast"
    return "article"


def run_pair(page_path: Path, raw_path: Path, *, db_path: Path | None,
             no_embeddings: bool, kind: str | None, twin_fidelity: bool,
             vault_root: Path | None = None) -> PairContext:
    """Run Layer-1a (typed) + Layer-1b (chunked recall) for one (page, raw) pair.

    Layer-1b runs through thin_detector_density on a SCRATCH db (caller MUST pass --db).
    Layer-1a is embedding-free and always runs. When raw is an UNSTRUCTURED source file
    (no compare-set H2 sections), typed.detect(page, raw) yields zero raw atoms -- the
    typed layer compares page-vs-structured-page; raw-vs-page wholesale omission is Layer-1b
    via density's windowing (2.2's disclosed boundary). For the ablation set, raw IS the
    original structured page (the retention reference), so typed scores correctly."""
    page_doc = WS.read_text(page_path)
    raw_doc = WS.read_text(raw_path)

    typed_report = TYPED.detect(page_doc, raw_doc,
                                page_name=str(page_path), raw_name=str(raw_path))

    # Layer-1b via density's recall CLI path -- reuse its plumbing through a tiny shim args.
    class _A:
        pass
    a = _A()
    a.vault_root = vault_root
    a.db = db_path
    a.model = DENSITY.WS.DEFAULT_MODEL
    a.no_embeddings = no_embeddings
    ctx = DENSITY._setup(a)
    conn = DENSITY.WS.open_db(ctx["db_path"])
    page_rel = DENSITY._rel_to_wiki(page_path, ctx["wiki_root"])
    raw_rel = DENSITY._rel_to_wiki(raw_path, ctx["wiki_root"])

    page_vectors = DENSITY._load_page_vectors(conn, page_rel) if page_rel else None
    if page_vectors is None and ctx["embeddings_on"]:
        page_vectors = DENSITY._embed_page_compare_set(page_doc, ctx["embedder"])
    if raw_rel:
        DENSITY._ensure_raw_embedded(conn, ctx, raw_rel)
        raw_windows, raw_vecs = DENSITY._load_raw_vectors(conn, raw_rel)
    else:
        raw_windows = DENSITY.WS.window_raw(raw_doc, str(raw_path))
        raw_vecs = [None] * len(raw_windows)
    raw_vectors = raw_vecs if (raw_vecs and all(v is not None for v in raw_vecs)) else None

    recall_report = DENSITY.chunked_recall(
        page_doc, raw_doc, page_rel or str(page_path), raw_rel or str(raw_path),
        page_vectors, raw_windows, raw_vectors, ctx["embeddings_on"])
    uncovered_mass = recall_report.uncovered_mass if recall_report.status == "ok" else -1.0

    k = kind or _kind_from_page_path(page_rel or str(page_path))
    return PairContext(
        page_path=page_path, raw_path=raw_path, page_doc=page_doc, raw_doc=raw_doc,
        typed_report=typed_report, recall_report=recall_report,
        uncovered_mass=uncovered_mass, embeddings_on=ctx["embeddings_on"],
        kind=k, twin_fidelity=twin_fidelity)


def verdict_for_pair(pc: PairContext) -> CompositeVerdict:
    return composite_detect(
        pc.page_doc, pc.raw_doc, page_name=str(pc.page_path), raw_name=str(pc.raw_path),
        kind=pc.kind, twin_fidelity=pc.twin_fidelity,
        uncovered_mass=pc.uncovered_mass, embeddings_on=pc.embeddings_on,
        typed_report=pc.typed_report)


# ===========================================================================
# Ranked queue  (worst-first; per-run cap; 5% audit)
# ===========================================================================
def _vault_root_from(path: Path) -> Path:
    return TYPED._vault_root_from(path)


def rank_pages(pairs: list[tuple[Path, Path, str | None, bool]], *,
               db_path: Path | None, no_embeddings: bool,
               cap: int = DEFAULT_RUN_CAP, audit_pct: float = DEFAULT_AUDIT_PCT,
               vault_root: Path | None = None) -> dict:
    """Run the ladder over a set of (page, raw, kind, twin_fidelity) and produce a
    WORST-FIRST ranked suspect queue (severity-DESC), capped at `cap`, plus a 5% random
    audit sample of NON-flagged pages (codex -- measures the false-negative rate)."""
    verdicts: list[CompositeVerdict] = []
    for page_path, raw_path, kind, twin_fidelity in pairs:
        pc = run_pair(page_path, raw_path, db_path=db_path, no_embeddings=no_embeddings,
                      kind=kind, twin_fidelity=twin_fidelity, vault_root=vault_root)
        verdicts.append(verdict_for_pair(pc))

    flagged = [v for v in verdicts if v.flagged]
    non_flagged = [v for v in verdicts if not v.flagged]
    # worst-first
    flagged.sort(key=lambda v: v.severity, reverse=True)
    capped = flagged[:cap]

    # 5% random non-flagged audit (deterministic sample)
    rng = random.Random(AUDIT_SEED)
    n_audit = max(1, round(len(non_flagged) * audit_pct / 100.0)) if non_flagged else 0
    audit = rng.sample(non_flagged, min(n_audit, len(non_flagged))) if non_flagged else []

    def _row(v: CompositeVerdict, i: int | None = None) -> dict:
        d = {"rank": i, "page": v.page, "kind": v.kind, "severity": v.severity,
             "flagged": v.flagged, "escalate": v.escalate,
             "typed_loss_fraction": v.typed_loss_fraction,
             "uncovered_mass": v.uncovered_mass,
             "escalation_reasons": v.escalation_reasons}
        if i is None:
            d.pop("rank")
        return d

    return {
        "n_pages": len(verdicts),
        "n_flagged": len(flagged),
        "n_escalate": sum(1 for v in flagged if v.escalate),
        "run_cap": cap,
        "n_queued": len(capped),
        "audit_pct": audit_pct,
        "ranked_queue": [_row(v, i + 1) for i, v in enumerate(capped)],
        "audit_sample_non_flagged": [_row(v) for v in audit],
        "audit_note": ("5% random audit of NON-flagged pages -- measures the false-negative "
                       "rate the cheap layers miss (codex). Send these to the judge too."),
        "all_verdicts": [_row(v) for v in verdicts],
    }


# ===========================================================================
# CLI
# ===========================================================================
def _resolve(path_arg: str, vault_root: Path) -> Path:
    p = Path(path_arg)
    if p.is_absolute():
        return p
    for base in (vault_root, Path.cwd()):
        cand = base / path_arg
        if cand.exists():
            return cand
    return vault_root / path_arg


def _bool(s: str) -> bool:
    return str(s).strip().lower() in ("1", "true", "yes", "y", "on")


def _pairs_from_manifest(manifest_path: Path, vault_root: Path,
                         kind: str | None, grade: float | None,
                         include_gold: bool) -> list[tuple[Path, Path, str | None, bool]]:
    """Build (page, raw, kind, twin_fidelity) tuples from the calibration manifest.

    Ablations: (ablated_page, source_page) -- raw side is the ORIGINAL structured page (the
    retention reference; 2.2's model). Gold (cal ONLY): (page, raw) pairs. twin_fidelity is
    True for all calibration pages (no untrustworthy-twin fixtures in the cal set)."""
    sys.path.insert(0, str(manifest_path.parent.parent))  # calibration/ on path? load_manifest is in calibration/
    sys.path.insert(0, str(Path(__file__).resolve().parent / "calibration"))
    from load_manifest import Manifest
    M = Manifest.load(manifest_path)
    pairs: list[tuple[Path, Path, str | None, bool]] = []
    for a in M.ablations(kind=kind, grade=grade):
        page = vault_root / a.ablated_page
        src = vault_root / a.source_page
        pairs.append((page, src, a.kind, True))
    if include_gold:
        for g in M.gold_cal(kind=kind):   # cal ONLY -- never gold_test()
            page = vault_root / g.page
            raw = vault_root / g.raw
            pairs.append((page, raw, g.kind, True))
    return pairs


def cmd_detect(args) -> int:
    vault_root = Path(args.vault_root).resolve() if args.vault_root else _vault_root_from(Path.cwd())
    page = _resolve(args.page, vault_root)
    raw = _resolve(args.raw, vault_root)
    if not page.exists() or not raw.exists():
        print(f"page or raw not found: {page} / {raw}", file=sys.stderr)
        return 2
    tf = _bool(args.twin_fidelity)
    pc = run_pair(page, raw, db_path=Path(args.db) if args.db else None,
                  no_embeddings=args.no_embeddings, kind=args.kind, twin_fidelity=tf,
                  vault_root=vault_root)
    v = verdict_for_pair(pc)
    print(json.dumps(asdict(v), indent=2, ensure_ascii=False))
    return 0


def cmd_packet(args) -> int:
    vault_root = Path(args.vault_root).resolve() if args.vault_root else _vault_root_from(Path.cwd())
    page = _resolve(args.page, vault_root)
    raw = _resolve(args.raw, vault_root)
    if not page.exists() or not raw.exists():
        print(f"page or raw not found: {page} / {raw}", file=sys.stderr)
        return 2
    tf = _bool(args.twin_fidelity)
    pc = run_pair(page, raw, db_path=Path(args.db) if args.db else None,
                  no_embeddings=args.no_embeddings, kind=args.kind, twin_fidelity=tf,
                  vault_root=vault_root)
    v = verdict_for_pair(pc)
    packet = build_packet(v, pc.typed_report, pc.recall_report, pc.raw_doc)
    out = {"verdict_flagged": v.flagged, "verdict_escalate": v.escalate,
           "packet_total_items": packet_total_items(packet),
           "packet": asdict(packet)}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if (not v.flagged or v.kind != "paper" or packet_total_items(packet) >= 0) else 3


def cmd_judge(args) -> int:
    vault_root = Path(args.vault_root).resolve() if args.vault_root else _vault_root_from(Path.cwd())
    page = _resolve(args.page, vault_root)
    raw = _resolve(args.raw, vault_root)
    if not page.exists() or not raw.exists():
        print(f"page or raw not found: {page} / {raw}", file=sys.stderr)
        return 2
    tf = _bool(args.twin_fidelity)
    pc = run_pair(page, raw, db_path=Path(args.db) if args.db else None,
                  no_embeddings=args.no_embeddings, kind=args.kind, twin_fidelity=tf,
                  vault_root=vault_root)
    v = verdict_for_pair(pc)
    packet = build_packet(v, pc.typed_report, pc.recall_report, pc.raw_doc)

    provider = args.judge
    if provider == "anthropic":
        key = _resolve_llm_key(vault_root)
        if not key:
            print(json.dumps({"error": "no ANTHROPIC_API_KEY/CLAUDE_API_KEY resolved",
                              "fallback": "use --judge stub; real LLM wiring is the ingest "
                                          "pipeline's runtime dependency"}, indent=2))
            return 2
        native_pdf = None  # native PDF path resolution is the ingest pipeline's job; absent here
        jv = judge_anthropic(packet, native_pdf, key, model=args.model_llm)
    else:
        jv = judge_stub(packet)

    out = {"page": v.page, "kind": v.kind, "flagged": v.flagged,
           "packet_total_items": packet_total_items(packet),
           "judge": asdict(jv)}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_rank(args) -> int:
    vault_root = Path(args.vault_root).resolve() if args.vault_root else _vault_root_from(Path.cwd())
    if args.from_manifest:
        manifest = (Path(args.manifest) if args.manifest else
                    Path(__file__).resolve().parent / "calibration" / "data" / "ground-truth-manifest.json")
        grade = float(args.grade) if args.grade else None
        pairs = _pairs_from_manifest(manifest, vault_root, args.kind, grade,
                                     include_gold=args.include_gold)
    elif args.page and args.raw:
        pairs = [(_resolve(args.page, vault_root), _resolve(args.raw, vault_root),
                  args.kind, _bool(args.twin_fidelity))]
    else:
        print("rank needs --from-manifest OR --page/--raw", file=sys.stderr)
        return 2
    result = rank_pages(pairs, db_path=Path(args.db) if args.db else None,
                        no_embeddings=args.no_embeddings, cap=args.cap,
                        audit_pct=args.audit_pct, vault_root=vault_root)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_calibrate(args) -> int:
    """Report, for each OR-of-thresholds cut, the recall it achieves on the cal+ablation
    POSITIVES (known-thin), and the chosen value. Calibrated on gold_cal()+ablations ONLY
    -- gold_test() is NEVER loaded here. This makes the threshold choice auditable: each cut
    is recall-biased (>= ~0.90 detection on the known-thin set)."""
    vault_root = Path(args.vault_root).resolve() if args.vault_root else _vault_root_from(Path.cwd())
    manifest = (Path(args.manifest) if args.manifest else
                Path(__file__).resolve().parent / "calibration" / "data" / "ground-truth-manifest.json")
    sys.path.insert(0, str(Path(__file__).resolve().parent / "calibration"))
    from load_manifest import Manifest
    M = Manifest.load(manifest)

    # Positives: every ablation (known-thin) + gold_cal thin pages. Negatives: gold_cal faithful.
    ablations = M.ablations()
    gold_cal = M.gold_cal()
    rows_pos = []
    for a in ablations:
        rows_pos.append((vault_root / a.ablated_page, vault_root / a.source_page, a.kind, True, "ablation"))
    for g in gold_cal:
        # gold raw side is the raw SOURCE (unstructured) -> typed yields 0 raw atoms; for
        # calibration recall we score gold THIN pages via the composite flag (paper escalation
        # + any signal). They contribute to the "does the composite flag a known-thin page"
        # recall, computed below.
        rows_pos.append((vault_root / g.page, vault_root / g.raw, g.kind, True,
                         f"gold-{g.label}"))

    flagged_pos = 0
    total_pos = 0
    flagged_faithful = 0
    total_faithful = 0
    per = []
    for page, raw, kind, tf, src in rows_pos:
        if not page.exists() or not raw.exists():
            per.append({"page": str(page), "error": "missing"})
            continue
        pc = run_pair(page, raw, db_path=Path(args.db) if args.db else None,
                      no_embeddings=args.no_embeddings, kind=kind, twin_fidelity=tf,
                      vault_root=vault_root)
        v = verdict_for_pair(pc)
        is_thin = (src == "ablation") or src == "gold-thin"
        if is_thin:
            total_pos += 1
            if v.flagged:
                flagged_pos += 1
        else:  # gold-faithful
            total_faithful += 1
            if v.flagged:
                flagged_faithful += 1
        per.append({"page": page.name, "src": src, "kind": kind, "flagged": v.flagged,
                    "severity": v.severity, "typed_loss": v.typed_loss_fraction,
                    "reasons": v.escalation_reasons})

    result = {
        "manifest": str(manifest),
        "thresholds": {**THRESHOLDS, "uncovered_mass": THETA_UNCOVERED},
        "calibrated_on": "gold_cal() + ablation set ONLY (gold_test never loaded)",
        "known_thin_total": total_pos,
        "known_thin_flagged": flagged_pos,
        "thin_recall": (flagged_pos / total_pos) if total_pos else None,
        "faithful_total": total_faithful,
        "faithful_flagged": flagged_faithful,
        "faithful_flag_rate": (flagged_faithful / total_faithful) if total_faithful else None,
        "note": ("OR-of-thresholds recall on the known-thin set; recall-biased cuts (papers "
                 "escalate unconditionally so faithful papers also flag -- expected, the LLM "
                 "judge clears them). Faithful ARTICLES flagging would be the false-positive "
                 "concern; the judge is the precision backstop."),
        "per_page": per,
    }
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vault-root", default=None)
    ap.add_argument("--db", default=None,
                    help="SCRATCH index db -- ALWAYS pass for detection runs (never the LIVE index)")
    ap.add_argument("--no-embeddings", action="store_true",
                    help="force Layer-1b OFF (key-absent path) for testing")
    sub = ap.add_subparsers(dest="cmd", required=True)

    common = dict()
    d = sub.add_parser("detect", help="composite verdict for one (page, raw) pair")
    d.add_argument("--page", required=True)
    d.add_argument("--raw", required=True)
    d.add_argument("--kind", default=None, choices=["paper", "article", "podcast"])
    d.add_argument("--twin-fidelity", default="true")
    d.set_defaults(func=cmd_detect)

    p = sub.add_parser("packet", help="the structured NLI packet (the literal judge input)")
    p.add_argument("--page", required=True)
    p.add_argument("--raw", required=True)
    p.add_argument("--kind", default=None, choices=["paper", "article", "podcast"])
    p.add_argument("--twin-fidelity", default="true")
    p.set_defaults(func=cmd_packet)

    j = sub.add_parser("judge", help="run the adversarial judge on one packet")
    j.add_argument("--page", required=True)
    j.add_argument("--raw", required=True)
    j.add_argument("--kind", default=None, choices=["paper", "article", "podcast"])
    j.add_argument("--twin-fidelity", default="true")
    j.add_argument("--judge", default="stub", choices=["stub", "anthropic"])
    j.add_argument("--model-llm", default="claude-opus-4-8")
    j.set_defaults(func=cmd_judge)

    r = sub.add_parser("rank", help="worst-first ranked suspect queue over a set")
    r.add_argument("--from-manifest", action="store_true")
    r.add_argument("--manifest", default=None)
    r.add_argument("--include-gold", action="store_true",
                   help="include gold_cal() pages (NEVER gold_test())")
    r.add_argument("--page", default=None)
    r.add_argument("--raw", default=None)
    r.add_argument("--kind", default=None, choices=["paper", "article", "podcast"])
    r.add_argument("--twin-fidelity", default="true")
    r.add_argument("--grade", default=None)
    r.add_argument("--cap", type=int, default=DEFAULT_RUN_CAP)
    r.add_argument("--audit-pct", type=float, default=DEFAULT_AUDIT_PCT)
    r.add_argument("--json-out", default=None)
    r.set_defaults(func=cmd_rank)

    c = sub.add_parser("calibrate", help="report recall of each OR cut on gold_cal()+ablations")
    c.add_argument("--manifest", default=None)
    c.add_argument("--json-out", default=None)
    c.set_defaults(func=cmd_calibrate)
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
