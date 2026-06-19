#!/usr/bin/env python3
"""Unit tests for thin_detector_density + the raw-embedding persistence in sb-wiki-search.

Network-free: a deterministic STUB embedder replaces Voyage so the prefilter, the OD-2
model-id invalidation, the windowing, and the recall math are all exercised without a key.
Run:  py -3.12 thin_detector_density_test.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name, filename):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


WS = _load("sb_wiki_search", "sb-wiki-search.py")
DET = _load("thin_detector_density", "thin_detector_density.py")

_failures = []


def check(cond, msg):
    if cond:
        print(f"  PASS  {msg}")
    else:
        print(f"  FAIL  {msg}")
        _failures.append(msg)


# A deterministic embedder: a tiny hash-based 8-dim unit-ish vector. Distinct texts get
# distinct vectors; identical texts get identical vectors. `tag` lets us simulate a DIFFERENT
# model returning DIFFERENT vectors for the same text (so a model change is observable).
def make_stub_embedder(tag: str = "A"):
    def embed(texts, input_type):
        out = []
        for t in texts:
            h = abs(hash((tag, t)))
            vec = [((h >> (i * 5)) & 31) + 1 for i in range(8)]  # 8 positive ints
            out.append([float(x) for x in vec])
        return out
    return embed


def test_window_raw():
    print("test_window_raw")
    text = "---\ntitle: x\n---\n" + ("word " * 4000)  # ~20k chars body
    windows = WS.window_raw(text, "raw/foo/bar.md")
    check(len(windows) >= 2, f"long raw splits into multiple windows (got {len(windows)})")
    check(all(w.text.startswith("bar\n\n") for w in windows),
          "every window is title-prefixed with the filename stem")
    check(windows[0].anchor.count(":") == 1, "anchor records a char span 'start:end'")
    # overlap: window 2 should start before window 1 ends
    s2 = int(windows[1].anchor.split(":")[0])
    e1 = int(windows[0].anchor.split(":")[1])
    check(s2 < e1, f"consecutive windows overlap (w2 start {s2} < w1 end {e1})")
    # short raw -> single window
    short = WS.window_raw("---\nt:1\n---\nshort body here", "raw/x/y.md")
    check(len(short) == 1, "short raw yields exactly one window")


def test_density_priors():
    print("test_density_priors")
    raw = ("---\nt: x\n---\n"
           "The cost grew 2.4x per year, reaching $40M by 2026. "
           "Rule: always validate. The Smith-Jones Effect explains GPT-4 vs Gemini. "
           "| a | b |\n| 1 | 2 |\n"
           "First, measure. Second, verify. 5 principles apply.")
    p = DET.compute_density(raw, "raw/x.md", raw_vectors=None)
    check(p.numeric_count >= 2, f"numeric atoms counted, years excluded (got {p.numeric_count})")
    check(p.table_score >= 5.0, f"table rows weighted heavily (score {p.table_score})")
    check(p.enumeration_score > 0, f"enumeration scored (score {p.enumeration_score})")
    check(p.named_count >= 1, f"named items counted (got {p.named_count})")
    check(p.dispersion is None, "dispersion None when no vectors supplied")
    # 2026 as a bare year should NOT count; 2.4x and $40M should
    bare = DET.compute_density("---\nt:1\n---\nIn 2026 and 2025 nothing happened.",
                               "raw/y.md", None)
    check(bare.numeric_count == 0, f"bare years excluded from numeric (got {bare.numeric_count})")


def test_dispersion():
    print("test_dispersion")
    # identical vectors -> ~0 dispersion; varied -> >0
    same = DET._distance_to_centroid([[1.0, 0, 0], [1.0, 0, 0], [1.0, 0, 0]])
    check(abs(same) < 1e-6, f"identical vectors -> ~0 dispersion (got {same})")
    varied = DET._distance_to_centroid([[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]])
    check(varied > 0.3, f"orthogonal vectors -> high dispersion (got {varied})")


def test_chunked_recall_math():
    print("test_chunked_recall_math")
    # 3 raw windows; page covers window 0 (identical vector), misses 1 & 2 (orthogonal).
    page_text = "## Substance\n\nalpha beta gamma coverage terms here\n\n## My take\n\nignore"
    raw_text = "raw body"
    Chunk = WS.Chunk
    raw_windows = [
        Chunk(anchor="0:10", pos=0, text="alpha beta gamma coverage terms here " * 3),
        Chunk(anchor="10:20", pos=1, text="zzz qqq vvv unrelated passage one " * 3),
        Chunk(anchor="20:30", pos=2, text="mmm nnn ppp unrelated passage two " * 3),
    ]
    page_vectors = [[1.0, 0.0, 0.0]]
    raw_vectors = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    rep = DET.chunked_recall(page_text, raw_text, "wiki/p.md", "raw/r.md",
                             page_vectors, raw_windows, raw_vectors, embeddings_on=True)
    check(rep.status == "ok", "recall status ok with vectors present")
    check(rep.n_uncovered == 2, f"2 of 3 windows uncovered (got {rep.n_uncovered})")
    check(rep.uncovered_mass > 0.5, f"uncovered_mass high (got {rep.uncovered_mass})")
    check(rep.flagged, "page flagged when mass>0")
    # the covered window must NOT be in the uncovered list
    covered_in = any(w["anchor"] == "0:10" for w in rep.uncovered_windows)
    check(not covered_in, "the covered window is not reported uncovered")


def test_recall_no_embeddings():
    print("test_recall_no_embeddings")
    rep = DET.chunked_recall("## Substance\n\nx", "raw", "p.md", "r.md",
                             page_vectors=None, raw_windows=[WS.Chunk("0:1", 0, "t")],
                             raw_vectors=None, embeddings_on=False)
    check(rep.status == "unavailable-no-embeddings",
          "key-absent -> explicit unavailable status, NOT clean")
    check(rep.flagged is False and rep.uncovered_mass == -1.0,
          "no-embeddings sentinel (mass=-1, not a 0 'all-clear')")
    check("NOT an all-clear" in rep.note, "note states this is not an all-clear")


def test_bm25_floor():
    print("test_bm25_floor")
    # a window whose terms are ALL on the page should never be uncovered even at low cosine
    page_set = {"alpha", "beta", "gamma", "delta", "coverage", "terms"}
    high = DET._bm25_overlap("alpha beta gamma delta coverage terms", page_set)
    check(high > 0.9, f"window fully present on page -> high keyword overlap (got {high})")
    low = DET._bm25_overlap("zzzz qqqq vvvv wwww", page_set)
    check(low < 0.1, f"window absent from page -> low keyword overlap (got {low})")


def test_compare_set():
    print("test_compare_set")
    page = ("---\nt: x\n---\n## Substance\n\nSUB body\n\n## My take\n\nMINE\n\n"
            "## Notable quotes\n\nQUOTE body\n\n## Sources\n\nSRC")
    cs = DET.extract_compare_set(page)
    check("SUB body" in cs and "QUOTE body" in cs, "compare-set includes Substance + Notable quotes")
    check("MINE" not in cs and "SRC" not in cs, "compare-set excludes My take + Sources")


def test_raw_sync_prefilter_and_od2():
    print("test_raw_sync_prefilter_and_od2 (stub embedder, no network)")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        wiki_root = Path(td)
        (wiki_root / "raw" / "papers").mkdir(parents=True)
        f = wiki_root / "raw" / "papers" / "sample.md"
        f.write_text("---\nt: x\n---\n" + ("token here " * 1200), encoding="utf-8")
        db = wiki_root / ".sb-wiki-search" / "index.db"
        conn = WS.open_db(db)

        emb_A = make_stub_embedder("A")
        r1 = WS.sync_raw(conn, wiki_root, embedder=emb_A, model="voyage-3.5",
                         glob="raw/papers/*")
        check(r1["raw_added"] == 1, f"first run adds the raw file (got {r1['raw_added']})")
        check(r1["embedded"] > 0, f"first run embeds windows (got {r1['embedded']})")
        n_emb1 = r1["embedded"]

        # second run, SAME model -> prefilter holds, nothing re-embedded
        r2 = WS.sync_raw(conn, wiki_root, embedder=emb_A, model="voyage-3.5",
                         glob="raw/papers/*")
        check(r2["embedded"] == 0, f"second run re-embeds NOTHING (got {r2['embedded']})")
        check(r2["reembedded_model"] == 0, "no model-change invalidation on same model")

        # OD-2: change the model id -> stale vectors invalidated + re-embedded
        r3 = WS.sync_raw(conn, wiki_root, embedder=make_stub_embedder("B"),
                         model="voyage-3-large", glob="raw/papers/*")
        check(r3["reembedded_model"] == n_emb1,
              f"model change invalidates all {n_emb1} vectors (got {r3['reembedded_model']})")
        check(r3["embedded"] == n_emb1, f"all re-embedded under new model (got {r3['embedded']})")

        # the stored model id is now the new one
        models = [r[0] for r in conn.execute(
            "SELECT DISTINCT model FROM raw_chunks WHERE model IS NOT NULL")]
        check(models == ["voyage-3-large"], f"stored model id updated (got {models})")

        # a THIRD run on the new model again re-embeds nothing
        r4 = WS.sync_raw(conn, wiki_root, embedder=make_stub_embedder("B"),
                         model="voyage-3-large", glob="raw/papers/*")
        check(r4["embedded"] == 0 and r4["reembedded_model"] == 0,
              "stable again after the model change settles")
        conn.close()


def test_pages_tables_untouched():
    print("test_pages_tables_untouched")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        wiki_root = Path(td)
        (wiki_root / "wiki" / "concepts").mkdir(parents=True)
        (wiki_root / "wiki" / "concepts" / "alpha.md").write_text(
            "---\nt: x\n---\n# Alpha\n\n## Substance\n\nbody alpha", encoding="utf-8")
        (wiki_root / "raw" / "papers").mkdir(parents=True)
        (wiki_root / "raw" / "papers" / "p.md").write_text(
            "---\nt: x\n---\n" + ("raw token " * 400), encoding="utf-8")
        db = wiki_root / ".sb-wiki-search" / "index.db"
        conn = WS.open_db(db)
        # index pages WITHOUT a key (FTS only) then raw -> pages tables must be unchanged
        WS.sync(conn, wiki_root, embedder=None)
        pages_before = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        fts_before = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
        WS.sync_raw(conn, wiki_root, embedder=make_stub_embedder("A"),
                    model="voyage-3.5", glob="raw/**")
        pages_after = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        fts_after = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
        check(pages_before == pages_after and pages_before > 0,
              f"page chunks untouched by raw sync ({pages_before}=={pages_after})")
        check(fts_before == fts_after, "page FTS untouched by raw sync")
        raw_n = conn.execute("SELECT COUNT(*) FROM raw_chunks").fetchone()[0]
        check(raw_n > 0, f"raw chunks written to the separate table ({raw_n})")
        conn.close()


def main():
    for fn in [test_window_raw, test_density_priors, test_dispersion,
               test_chunked_recall_math, test_recall_no_embeddings, test_bm25_floor,
               test_compare_set, test_raw_sync_prefilter_and_od2,
               test_pages_tables_untouched]:
        fn()
    print()
    if _failures:
        print(f"FAILED: {len(_failures)} check(s)")
        for m in _failures:
            print(f"  - {m}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
