#!/usr/bin/env python3
"""Network-free unit suite for thin_detector_composite + thin_detector_reingest_gate.

Exercises the deterministic parts with NO embeddings and NO LLM:
  - composite OR-of-thresholds (each signal trips correctly; paper/twin escalation)
  - severity ordering (more loss -> higher severity)
  - the structured packet (whole-page EXCLUSION; only missing atoms + raw context)
  - the stub judge (adversarial default-missing-on-doubt; never fabricates an LLM verdict)
  - the OD-6 no-worse gate (accept >= old; reject a regression; min-delta; uncovered arm)
  - the OD-6 unmeasured-class guardrail (reasoning_chain -> surfaced + added, not passed)

Run: python -m pytest thin_detector_composite_test.py -q
"""
from __future__ import annotations

import thin_detector_composite as C
import thin_detector_reingest_gate as G
import thin_detector_typed as TYPED


# --- fixtures: tiny structured (page, raw) pairs -----------------------------
# Enough atoms per class to clear the min-count floors (numeric>=5, rule>=3) so the
# composite's quant/rule cuts actually score rather than being noise-skipped.
FAITHFUL = """\
---
type: source
---

## Substance

- The growth rate is **2.4x** per year, validated at $40M amortized cost, with a 90% CI of 2.0x to 2.9x.
- A second run reached 3.0x per year and $30M amortized over 12 months.
- The **Chinchilla Rule** governs scaling: 20 tokens per parameter is optimal.
- The **Compute-Optimal Test** caps the run at 1e25 FLOPs.
- The **Amortization Principle** spreads hardware cost across 5 runs.
- See [[gpt-4.md]] and [[gemini-models.md]] for the frontier runs.

## Counterpoints

- The authors caution this needs validation on TPU-priced runs.

## My take

This is my own page-only commentary that is NOT in the raw.
"""

# A THIN copy: drops several numbers (2.4x, 2.9x, 3.0x), two rule labels (Compute-Optimal
# Test, Amortization Principle), one entity ([[gemini-models.md]]), and the caveat.
THIN = """\
---
type: source
---

## Substance

- The growth rate increases per year, validated at $40M amortized cost.
- A second run reached a higher rate and $30M amortized over 12 months.
- The **Chinchilla Rule** governs scaling: 20 tokens per parameter is optimal.
- The run is capped at 1e25 FLOPs.
- Hardware cost is spread across 5 runs.
- See [[gpt-4.md]] for the frontier runs.

## My take

This is my own page-only commentary that is NOT in the raw.
"""


def _verdict(page, raw, kind="article", twin=True, uncovered=-1.0, emb=False):
    rep = TYPED.detect(page, raw, page_name="p", raw_name="r")
    return C.composite_detect(page, raw, page_name="p", raw_name="r", kind=kind,
                              twin_fidelity=twin, uncovered_mass=uncovered,
                              embeddings_on=emb, typed_report=rep)


# ===========================================================================
# Composite OR-of-thresholds
# ===========================================================================
def test_faithful_self_compare_not_flagged():
    v = _verdict(FAITHFUL, FAITHFUL, kind="article")
    assert not v.flagged
    assert not v.escalate
    assert v.typed_loss_fraction == 0.0


def test_thin_page_flagged_multiple_signals():
    v = _verdict(THIN, FAITHFUL, kind="article")
    assert v.flagged
    assert v.escalate
    tripped = {s.name for s in v.signals if s.tripped}
    # the dropped number trips quant; the dropped rule trips rule; the dropped caveat trips caveat
    assert "quant_retention" in tripped
    assert "rule_retention" in tripped
    assert "caveat_survival" in tripped


def test_paper_escalates_unconditionally_even_when_faithful():
    # a FAITHFUL paper (no signal tripped) STILL escalates -- twin-blind layers may never clear it
    v = _verdict(FAITHFUL, FAITHFUL, kind="paper")
    assert v.flagged
    assert v.escalate
    assert any("kind==paper" in r for r in v.escalation_reasons)


def test_twin_fidelity_false_escalates_unconditionally():
    v = _verdict(FAITHFUL, FAITHFUL, kind="article", twin=False)
    assert v.flagged
    assert any("twin_fidelity==false" in r for r in v.escalation_reasons)


def test_uncovered_mass_skipped_not_clean_when_embeddings_off():
    v = _verdict(THIN, FAITHFUL, kind="article", emb=False, uncovered=-1.0)
    um = next(s for s in v.signals if s.name == "uncovered_mass")
    assert um.skipped
    assert not um.tripped  # skipped, NOT read as a clean pass


def test_uncovered_mass_trips_when_high():
    v = _verdict(FAITHFUL, FAITHFUL, kind="article", emb=True, uncovered=0.20)
    um = next(s for s in v.signals if s.name == "uncovered_mass")
    assert um.tripped
    assert v.flagged  # tripped via the uncovered arm alone


def test_uncovered_mass_sentinel_not_reported_as_clean_when_embeddings_on():
    # embeddings ON but Layer-1b recall could NOT run (raw reference not embeddable -> sentinel
    # -1.0 reaches the composite). The signal must be SKIPPED and the REPORTED field must carry
    # the sentinel (-1.0), NEVER a misleading measured 0.0 (spec: never read clean because the
    # layer was unavailable). Regression guard for the embeddings-on + ablation-raw path.
    v = _verdict(THIN, FAITHFUL, kind="article", emb=True, uncovered=-1.0)
    um = next(s for s in v.signals if s.name == "uncovered_mass")
    assert um.skipped
    assert not um.tripped
    assert "Layer-1b recall unavailable" in um.note   # note distinguishes from "embeddings off"
    assert v.uncovered_mass == -1.0                    # field is the sentinel, not a clean 0.0


# ===========================================================================
# Severity ordering (OD-7)
# ===========================================================================
def test_severity_more_loss_ranks_worse():
    v_thin = _verdict(THIN, FAITHFUL, kind="article")
    v_faithful = _verdict(FAITHFUL, FAITHFUL, kind="article")
    assert v_thin.severity > v_faithful.severity


def test_paper_severity_bump_breaks_ties():
    v_paper = _verdict(FAITHFUL, FAITHFUL, kind="paper")
    v_article = _verdict(FAITHFUL, FAITHFUL, kind="article")
    # the article is not flagged (sev contributions ~0); the paper carries the paper bump
    assert v_paper.severity > v_article.severity


# ===========================================================================
# The structured packet -- whole-page EXCLUSION
# ===========================================================================
def test_packet_excludes_whole_page():
    import json
    rep = TYPED.detect(THIN, FAITHFUL, page_name="p", raw_name="r")
    v = C.composite_detect(THIN, FAITHFUL, page_name="p", raw_name="r", kind="article",
                           twin_fidelity=True, uncovered_mass=-1.0, embeddings_on=False,
                           typed_report=rep)
    packet = C.build_packet(v, rep, None, FAITHFUL)
    packet_str = json.dumps(C_asdict(packet), ensure_ascii=False)
    # the page's MY TAKE line is page-only content -> MUST be absent from the packet
    assert "page-only commentary" not in packet_str
    # the whole THIN page body is NOT embedded
    assert THIN.strip() not in packet_str
    # but the missing atoms ARE present, each with a RAW sentence (not a page sentence)
    assert C.packet_total_items(packet) > 0
    # the raw context of a missing artifact is a RAW sentence
    if packet.missing_artifacts:
        assert "raw_context" in packet.missing_artifacts[0]


def test_packet_carries_only_missing_atoms_and_context():
    rep = TYPED.detect(THIN, FAITHFUL, page_name="p", raw_name="r")
    v = C.composite_detect(THIN, FAITHFUL, page_name="p", raw_name="r", kind="article",
                           twin_fidelity=True, uncovered_mass=-1.0, embeddings_on=False,
                           typed_report=rep)
    packet = C.build_packet(v, rep, None, FAITHFUL)
    # each packet item has EXACTLY text+section+raw_context -- no page body field
    for it in (packet.missing_artifacts + packet.missing_framework_items
               + packet.missing_caveats):
        assert set(it.keys()) == {"text", "section", "raw_context"}


# ===========================================================================
# The stub judge -- adversarial default-missing-on-doubt, never fabricates
# ===========================================================================
def test_stub_judge_defaults_missing_on_nonempty_packet():
    rep = TYPED.detect(THIN, FAITHFUL, page_name="p", raw_name="r")
    v = C.composite_detect(THIN, FAITHFUL, page_name="p", raw_name="r", kind="article",
                           twin_fidelity=True, uncovered_mass=-1.0, embeddings_on=False,
                           typed_report=rep)
    packet = C.build_packet(v, rep, None, FAITHFUL)
    jv = C.judge_stub(packet)
    assert jv.missing is True            # packet has missing atoms -> default missing
    assert jv.provider == "stub"
    assert all(it["verdict"] == "missing" for it in jv.items)  # never clears an item


def test_stub_judge_empty_packet_not_missing():
    rep = TYPED.detect(FAITHFUL, FAITHFUL, page_name="p", raw_name="r")
    v = C.composite_detect(FAITHFUL, FAITHFUL, page_name="p", raw_name="r", kind="article",
                           twin_fidelity=True, uncovered_mass=-1.0, embeddings_on=False,
                           typed_report=rep)
    packet = C.build_packet(v, rep, None, FAITHFUL)
    jv = C.judge_stub(packet)
    assert jv.missing is False           # nothing missing -> not flagged
    assert jv.provider == "stub"


# ===========================================================================
# OD-6 no-worse gate
# ===========================================================================
def test_gate_accepts_strict_improvement():
    # NEW restores everything the OLD (thin) dropped -> >= old on every class -> accept
    v = G.reingest_gate(THIN, FAITHFUL, FAITHFUL, kind="article", min_delta=0.0)
    assert v.accept
    assert not any(cd.regressed for cd in v.class_deltas if cd.measured)


def test_gate_rejects_a_worse_redo():
    # NEW (thin) is worse than OLD (faithful) on numbers/rules/caveats -> reject
    v = G.reingest_gate(FAITHFUL, THIN, FAITHFUL, kind="article", min_delta=0.0)
    assert not v.accept
    assert any("regressed" in r for r in v.reasons)


def test_gate_min_delta_blocks_marginal_gain():
    # equal pages -> overall improvement 0 -> below a positive min-delta -> reject
    v = G.reingest_gate(FAITHFUL, FAITHFUL, FAITHFUL, kind="article", min_delta=0.2)
    assert not v.accept
    assert any("min_delta" in r for r in v.reasons)


def test_gate_uncovered_regression_rejects():
    # mechanically equal pages but NEW leaves MORE raw uncovered -> reject
    v = G.reingest_gate(FAITHFUL, FAITHFUL, FAITHFUL, kind="article", min_delta=0.0,
                        uncovered_old=0.05, uncovered_new=0.20)
    assert not v.accept
    assert any("uncovered_mass regressed" in r for r in v.reasons)


def test_gate_paper_requires_ai_confirm():
    v = G.reingest_gate(THIN, FAITHFUL, FAITHFUL, kind="paper", min_delta=0.0)
    assert v.needs_ai_confirm
    assert any("AI no-loss confirm" in r for r in v.reasons)


# ===========================================================================
# OD-6 UNMEASURED-CLASS guardrail (crit 8)
# ===========================================================================
def test_gate_unmeasured_class_regression_surfaced_not_passed():
    # NEW is mechanically >= OLD on every MEASURED class, but the pipeline declares the re-do
    # is worse on `reasoning_chain` (a class T2-T6 does NOT measure). The gate must SURFACE
    # the gap, ADD the class, and REJECT -- not silently pass.
    v = G.reingest_gate(THIN, FAITHFUL, FAITHFUL, kind="article", min_delta=0.0,
                        loss_classes=["reasoning_chain"])
    assert "reasoning_chain" in v.surfaced_unmeasured
    assert "reasoning_chain" in v.added_to_measured
    assert not v.accept  # the unmeasured-class regression blocks acceptance
    assert any("UNMEASURED-CLASS regression on 'reasoning_chain'" in r for r in v.reasons)


def test_gate_measured_class_not_misrouted_to_unmeasured():
    # declaring a MEASURED class as lost does not route it through the guardrail
    v = G.reingest_gate(FAITHFUL, THIN, FAITHFUL, kind="article", loss_classes=["numeric"])
    assert "numeric" not in v.surfaced_unmeasured


# helper: asdict for the packet dataclass (avoid importing dataclasses in-test)
def C_asdict(obj):
    from dataclasses import asdict
    return asdict(obj)
