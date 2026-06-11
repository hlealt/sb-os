"""Tests for the p4-8 backfill drafting hardening — coverage gate + native
firm-match relevance (Match/Rel columns).

Two surfaces under test, both on `sb-wiki-lint-deterministic.py`:

1. `update-backfill-gather` now emits a `relevance` field per firm candidate
   (overlap concept(s) scored by SOURCE document frequency; `weak` flag at
   `--weak-threshold`). ADVISORY — never drops a firm row (total-coverage
   invariant). Adopted per the p3-checkpoint2 ADX-8 ruling (Match = rarest
   shared concept + its source-frequency; Rel = hub-concept weak flag).

2. `update-backfill-reconcile` is the deterministic COVERAGE GATE: every firm
   pair the gather emitted must be DRAFTED in the artifact or ACCOUNTED as
   already-cited (citation staleness). An unexplained firm gap exits 1 — the
   silent-drop defect class (2026-06-10: ~107/351 firm rows dropped) this gate
   catches without depending on the drafting agent's memory.

All tests use `--skip-semantic` so they are deterministic and Voyage-free.

Run from the sb-os repo root or vault root:
    python -m pytest wiki/scripts/tests/test_backfill_drafting_harden.py -v
"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "sb-wiki-lint-deterministic.py"


# ---------------------------------------------------------------------------
# Synthetic-vault builder
# ---------------------------------------------------------------------------

def make_vault(tmp: Path) -> Path:
    """Build a minimal vault skeleton; return the vault root."""
    wiki_root = tmp / "kb"
    for sub in ("wiki/concepts", "wiki/entities", "wiki/topics",
                "wiki/sources", "logs", "raw"):
        (wiki_root / sub).mkdir(parents=True, exist_ok=True)
    (tmp / "sb-os.json").write_text(json.dumps({
        "wiki_root": "kb",
        "user_context_root": ".user/context/",
        "sb_os_path": str(SCRIPT.parent.parent),
    }), encoding="utf-8")
    return tmp


def write_source(wiki_root: Path, origin: str, slug: str, title: str,
                 substance_links: list[str]) -> None:
    d = wiki_root / "wiki" / "sources" / origin
    d.mkdir(parents=True, exist_ok=True)
    bullets = "\n".join(f"- A claim about [[{l}]]." for l in substance_links)
    (d / f"{slug}.md").write_text(
        f"---\ntitle: {title}\n---\n\n## Substance\n\n{bullets}\n",
        encoding="utf-8",
    )


def write_topic(wiki_root: Path, slug: str, key_concepts: list[str],
                sources_cited: list[str] | None = None) -> None:
    kc = "\n".join(f"- [[{l}]]" for l in key_concepts)
    cite_block = ""
    if sources_cited:
        defs = "\n".join(f"[^{i+1}]: [[{s}]]" for i, s in enumerate(sources_cited))
        cite_block = f"\n## Sources\n\n{defs}\n"
    (wiki_root / "wiki" / "topics" / f"{slug}.md").write_text(
        f"---\ntype: topic\n---\n\n## Scope\n\nScope text.\n\n"
        f"## Key concepts\n\n{kc}\n{cite_block}",
        encoding="utf-8",
    )


def run_gather(vault_root: Path, out: Path, weak_threshold: int | None = None) -> dict:
    cmd = [sys.executable, str(SCRIPT), "update-backfill-gather",
           "--vault-root", str(vault_root), "--output", str(out),
           "--skip-semantic"]
    if weak_threshold is not None:
        cmd += ["--weak-threshold", str(weak_threshold)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, f"gather exited {r.returncode}: {r.stderr}"
    return json.loads(out.read_text(encoding="utf-8"))


def run_reconcile(vault_root: Path, gather: Path, artifact: Path,
                  out: Path) -> tuple[int, dict]:
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "update-backfill-reconcile",
         "--vault-root", str(vault_root), "--gather", str(gather),
         "--artifact", str(artifact), "--output", str(out)],
        capture_output=True, text=True, encoding="utf-8",
    )
    return r.returncode, json.loads(out.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Relevance — Match / Rel / weak
# ---------------------------------------------------------------------------

def test_relevance_rare_concept_is_specific(tmp_path):
    """A firm match on a RARE concept (low source DF) is NOT weak; Match names it."""
    vault = make_vault(tmp_path)
    wiki = vault / "kb"
    # `rare-concept` appears in exactly ONE source; `hub-concept` in many.
    write_topic(wiki, "topic-a", ["rare-concept.md"])
    write_source(wiki, "o", "2026-01-01-s1", "Source One", ["rare-concept.md"])
    gather = run_gather(vault, tmp_path / "g.json", weak_threshold=25)

    firm = gather["firm_candidates"]
    assert len(firm) == 1
    rel = firm[0]["relevance"]
    assert rel["match_concept"] == "rare-concept"
    assert rel["match_df"] == 1
    assert rel["weak"] is False
    assert gather["firm_weak_count"] == 0


def test_relevance_hub_concept_is_weak(tmp_path):
    """A firm match whose rarest shared concept is a HUB (DF >= threshold) is weak."""
    vault = make_vault(tmp_path)
    wiki = vault / "kb"
    write_topic(wiki, "topic-hub", ["hub-concept.md"])
    # 5 sources all link hub-concept; threshold 3 -> DF 5 >= 3 -> weak.
    for i in range(5):
        write_source(wiki, "o", f"2026-01-0{i+1}-h{i}", f"Hub {i}", ["hub-concept.md"])
    gather = run_gather(vault, tmp_path / "g.json", weak_threshold=3)

    firm = [c for c in gather["firm_candidates"] if c["topic"] == "topic-hub.md"]
    assert firm, "expected firm rows against topic-hub"
    for c in firm:
        assert c["relevance"]["match_concept"] == "hub-concept"
        assert c["relevance"]["match_df"] == 5
        assert c["relevance"]["weak"] is True
    assert gather["firm_weak_count"] == len(firm)


def test_relevance_min_df_picks_rarest_shared(tmp_path):
    """When a row shares multiple concepts, Match = the RAREST (min DF) one."""
    vault = make_vault(tmp_path)
    wiki = vault / "kb"
    write_topic(wiki, "topic-multi", ["rare-one.md", "common-one.md"])
    # common-one in 4 sources, rare-one in 1 (this source). Rarest = rare-one.
    write_source(wiki, "o", "2026-02-01-multi", "Multi", ["rare-one.md", "common-one.md"])
    for i in range(3):
        write_source(wiki, "o", f"2026-02-1{i}-c{i}", f"C{i}", ["common-one.md"])
    gather = run_gather(vault, tmp_path / "g.json", weak_threshold=25)

    firm = [c for c in gather["firm_candidates"] if c["topic"] == "topic-multi.md"]
    target = next(c for c in firm if "multi" in c["source"])
    assert target["relevance"]["match_concept"] == "rare-one"
    assert target["relevance"]["match_df"] == 1
    assert sorted(target["relevance"]["overlap"]) == ["common-one", "rare-one"]


def test_slug_only_row_has_no_recomputed_overlap(tmp_path):
    """A pure slug-match row (no key-concept overlap) gets weak=False, min_df=None."""
    vault = make_vault(tmp_path)
    wiki = vault / "kb"
    # Topic 'foo' has a key concept the source does NOT link; the source TITLE
    # contains the slug 'foo' -> slug-match fires, key-concept-overlap does not.
    write_topic(wiki, "foo", ["unrelated-concept.md"])
    write_source(wiki, "o", "2026-03-01-about-foo", "All about foo", ["other.md"])
    gather = run_gather(vault, tmp_path / "g.json", weak_threshold=25)

    firm = [c for c in gather["firm_candidates"] if c["topic"] == "foo.md"]
    assert firm, "expected a slug-match firm row"
    row = firm[0]
    assert "slug-match" in row["match_types"]
    assert row["relevance"]["overlap"] == []
    assert row["relevance"]["match_concept"] is None
    assert row["relevance"]["min_df"] is None
    assert row["relevance"]["weak"] is False  # unscored is NEVER auto-weak


def test_weak_rows_are_never_dropped(tmp_path):
    """Total-coverage invariant: weak (advisory) firm rows stay in the set."""
    vault = make_vault(tmp_path)
    wiki = vault / "kb"
    write_topic(wiki, "t-weak", ["hub.md"])
    write_topic(wiki, "t-strong", ["rare.md"])
    for i in range(4):
        write_source(wiki, "o", f"2026-04-0{i+1}-w{i}", f"W{i}", ["hub.md"])
    write_source(wiki, "o", "2026-04-09-strong", "Strong", ["rare.md"])
    gather = run_gather(vault, tmp_path / "g.json", weak_threshold=3)

    weak = [c for c in gather["firm_candidates"] if c["relevance"]["weak"]]
    strong = [c for c in gather["firm_candidates"] if not c["relevance"]["weak"]]
    assert weak, "weak rows must be present, not dropped"
    assert strong, "strong rows must be present"
    # firm_count includes weak rows
    assert gather["firm_count"] == len(gather["firm_candidates"])
    assert gather["firm_count"] == len(weak) + len(strong)


# ---------------------------------------------------------------------------
# Coverage gate — reconcile
# ---------------------------------------------------------------------------

PENDING_HEADER = (
    "# Pending topic updates\n\n## Pending topic updates\n\n"
    "| source page | target topic | signal | proposed section | "
    "proposed bullet + citation | Match | Rel | Decision |\n"
    "|---|---|---|---|---|---|---|---|\n"
)


def artifact_from_pairs(pairs: list[tuple[str, str]]) -> str:
    rows = "".join(
        f"| {src} | {top} | firm:key-concept-overlap | Key concepts | "
        f"bullet — [[x.md]] | concept | specific | |\n"
        for src, top in pairs
    )
    return PENDING_HEADER + rows + "\n## Rejected ledger\n\n"


def build_two_firm_pairs(tmp_path):
    vault = make_vault(tmp_path)
    wiki = vault / "kb"
    write_topic(wiki, "topic-x", ["shared.md"])
    write_topic(wiki, "topic-y", ["shared.md"])
    write_source(wiki, "o", "2026-05-01-src", "Src", ["shared.md"])
    gather = run_gather(vault, tmp_path / "g.json", weak_threshold=25)
    pairs = [(c["source"], c["topic"]) for c in gather["firm_candidates"]]
    return vault, gather, pairs


def test_reconcile_passes_when_all_drafted(tmp_path):
    vault, gather, pairs = build_two_firm_pairs(tmp_path)
    art = tmp_path / "pending.md"
    art.write_text(artifact_from_pairs(pairs), encoding="utf-8")
    rc, report = run_reconcile(vault, tmp_path / "g.json", art, tmp_path / "rec.json")
    assert rc == 0
    assert report["coverage_total"] is True
    assert report["unexplained_gaps"] == 0
    assert report["firm_drafted"] == len(pairs)


def test_reconcile_fails_on_unexplained_gap(tmp_path):
    """Dropping a firm pair from the draft (not cited) is an unexplained gap -> exit 1."""
    vault, gather, pairs = build_two_firm_pairs(tmp_path)
    assert len(pairs) >= 2
    art = tmp_path / "pending.md"
    art.write_text(artifact_from_pairs(pairs[:-1]), encoding="utf-8")  # drop one
    rc, report = run_reconcile(vault, tmp_path / "g.json", art, tmp_path / "rec.json")
    assert rc == 1
    assert report["coverage_total"] is False
    assert report["unexplained_gaps"] == 1
    dropped = pairs[-1]
    assert [dropped[0], dropped[1]] in report["gap_pairs"]


def test_reconcile_accounts_staleness(tmp_path):
    """A firm pair absent from the draft but now CITED by the topic is accounted, not a gap."""
    vault = make_vault(tmp_path)
    wiki = vault / "kb"
    src_slug = "2026-06-01-cited"
    # topic-cited already cites the source in its Sources section.
    write_topic(wiki, "topic-cited", ["shared.md"],
                sources_cited=[f"{src_slug}.md"])
    write_topic(wiki, "topic-open", ["shared.md"])
    write_source(wiki, "o", src_slug, "Cited", ["shared.md"])
    gather = run_gather(vault, tmp_path / "g.json", weak_threshold=25)

    # The gather already citation-dedupes topic-cited, so only topic-open fires.
    firm_topics = {c["topic"] for c in gather["firm_candidates"]}
    assert "topic-cited.md" not in firm_topics  # citation-dedupe at gather time

    # Construct a gather JSON that INCLUDES the cited pair (simulating staleness:
    # the topic cited the source AFTER the gather ran). The reconcile must
    # account it via the live citation map, not flag a gap.
    stale_gather = json.loads((tmp_path / "g.json").read_text(encoding="utf-8"))
    stale_gather["firm_candidates"].append({
        "source": f"wiki/sources/o/{src_slug}.md",
        "source_title": "Cited",
        "topic": "topic-cited.md",
        "signal": "firm:key-concept-overlap",
        "match_types": ["key-concept-overlap"],
        "relevance": {"overlap": ["shared"], "match_concept": "shared",
                      "match_df": 1, "min_df": 1, "weak": False},
    })
    stale_path = tmp_path / "g-stale.json"
    stale_path.write_text(json.dumps(stale_gather), encoding="utf-8")

    # Artifact drafts ONLY topic-open (the cited pair is correctly omitted).
    open_pairs = [(c["source"], c["topic"]) for c in gather["firm_candidates"]]
    art = tmp_path / "pending.md"
    art.write_text(artifact_from_pairs(open_pairs), encoding="utf-8")

    rc, report = run_reconcile(vault, stale_path, art, tmp_path / "rec.json")
    assert rc == 0, f"staleness must be accounted, got gaps {report['gap_pairs']}"
    assert report["staleness_accounted"] == 1
    assert report["unexplained_gaps"] == 0
    assert report["coverage_total"] is True


# ---------------------------------------------------------------------------
# Artifact-shape compatibility (suspect areas #2 / #3 — ADX-8 review)
#
# The owner's pending 446-row artifact is the OLD 6-column shape
# (`source | topic | signal | section | bullet | Decision`). A future
# `scan` reconciles against an artifact in EITHER shape; the reconcile pair
# parser MUST read (source, topic) by their stable leading position
# regardless of how many trailing columns the artifact carries. And a drafting
# agent that retypes a curly-quote source path as straight quotes (the
# documented worker hazard) must still reconcile — the pair normalization folds
# both quote forms to one space. Direct-import the module so the parser is
# exercised without a subprocess round-trip.
# ---------------------------------------------------------------------------

import importlib.util as _ilu


def _load_module():
    spec = _ilu.spec_from_file_location("lintmod_test", SCRIPT)
    m = _ilu.module_from_spec(spec)
    sys.modules["lintmod_test"] = m
    spec.loader.exec_module(m)
    return m


OLD_6COL_ARTIFACT = (
    "# Pending topic updates\n\n## Pending topic updates\n\n"
    "| source page | target topic | signal | proposed section | "
    "proposed bullet + citation | Decision |\n"
    "|---|---|---|---|---|---|\n"
    "| wiki/sources/o/a.md | t1.md | firm:key-concept-overlap | "
    "Key concepts | bullet — [[a.md]] | |\n"
    "| wiki/sources/o/b.md | t2.md | semantic:0.5 | Timeline | "
    "bullet — [[b.md]] | accept |\n"
    "\n## Rejected ledger\n\n"
    "| source page | target topic | rejected by | reason |\n"
    "|---|---|---|---|\n"
    "| wiki/sources/o/z.md | t9.md | backfill:review | not relevant |\n"
)


def test_pending_parse_reads_old_6col_shape():
    """The reconcile pair parser reads (source, topic) from the OLD 6-column
    artifact (the owner-pending shape) by leading position — column count is
    irrelevant. APPLY-mode compatibility with the owner's 446-row artifact rests
    on this: source/topic are always the first two cells in both shapes."""
    m = _load_module()
    pairs = m._parse_artifact_pending_pairs(OLD_6COL_ARTIFACT)
    assert ("wiki/sources/o/a.md", "t1.md") in pairs
    assert ("wiki/sources/o/b.md", "t2.md") in pairs
    # the rejected-ledger section is a DIFFERENT section — its pairs must not
    # leak into the pending set (the parser stops at the next `##` heading).
    assert ("wiki/sources/o/z.md", "t9.md") not in pairs
    # header / separator rows are never emitted as pairs
    assert ("source page", "target topic") not in pairs
    assert len(pairs) == 2


def test_pending_parse_reads_new_8col_shape():
    """The same parser reads the NEW 8-column (Match/Rel) shape identically —
    the two trailing triage columns do not shift the leading source/topic cells."""
    m = _load_module()
    new_8col = (
        PENDING_HEADER
        + "| wiki/sources/o/a.md | t1.md | firm:key-concept-overlap | "
          "Key concepts | bullet — [[a.md]] | rare (1) | specific | |\n"
        + "\n## Rejected ledger\n\n"
    )
    pairs = m._parse_artifact_pending_pairs(new_8col)
    assert pairs == {("wiki/sources/o/a.md", "t1.md")}


def test_pending_parse_folds_curly_vs_straight_quotes():
    """A drafted row whose source path retyped a curly quote as straight (the
    documented worker hazard) normalizes to the SAME pair as the curly-quote
    gather expectation — so the coverage gate sees a MATCH, not a false gap.
    `_norm_pair_cell` folds both quote forms (and en/em dashes) to one space."""
    m = _load_module()
    curly = "wiki/sources/o/2026-01-01-burry’s-call.md"
    straight = "wiki/sources/o/2026-01-01-burry's-call.md"
    assert curly != straight
    assert m._norm_pair_cell(curly) == m._norm_pair_cell(straight)
    # and through the table parser end-to-end
    art = (
        PENDING_HEADER
        + f"| {straight} | t1.md | firm | Key concepts | b | c | specific | |\n"
        + "\n## Rejected ledger\n\n"
    )
    parsed = m._parse_artifact_pending_pairs(art)
    assert (m._norm_pair_cell(curly), "t1.md") in parsed


def test_gather_probe_passes_no_rerank(tmp_path, monkeypatch):
    """The gather's semantic probe must opt out of the search rerank stage.

    p4-11 pilot (2026-06-11): the gather harvests by top-k MEMBERSHIP (cap
    2/source) and the LLM confirmation bar supplies precision - under rerank,
    confirmed-class candidates inside the cap-2 window fell 81/95 -> 75/95.
    Owner-ruled tune: `--no-rerank` on the gather probe ONLY; rerank stays
    default-on for every other search consumer.
    """
    m = _load_module()
    # 2-level wiki root: _call_search_helper resolves vault root as
    # wiki_root.parent.parent (the production shape, e.g. 3-resources/kb).
    wiki_root = tmp_path / "3-resources" / "kb"
    wiki_root.mkdir(parents=True)
    (tmp_path / "sb-os.json").write_text(json.dumps({
        "wiki_root": "3-resources/kb",
        # absolute path wins the pathlib join; points at the REAL repo root
        # so the search script existence check passes
        "sb_os_path": str(SCRIPT.parents[2]),
    }), encoding="utf-8")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class R:
            returncode = 0
            stdout = '{"results": []}'
            stderr = ""

        return R()

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    result = m._call_search_helper(wiki_root, "probe query", k=5, topic_only=True)
    assert result == {"results": []}
    cmd = captured["cmd"]
    assert "--no-rerank" in cmd
    assert "--no-sync" in cmd
    assert cmd[cmd.index("--type") + 1] == "topic"
