"""Tests for sb-wiki-search.py rerank second stage.

Network calls are mocked; the live Voyage endpoint is never contacted.
"""

from __future__ import annotations

import importlib.util
import inspect
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "sb-wiki-search.py"
spec = importlib.util.spec_from_file_location("sb_wiki_search_rerank", MODULE_PATH)
sws = importlib.util.module_from_spec(spec)
sys.modules["sb_wiki_search_rerank"] = sws
spec.loader.exec_module(sws)


def build_index(tmp_path: Path):
    conn = sws.open_db(tmp_path / "index.db")
    rows = [
        (1, "wiki/concepts/alpha.md", "", 0, "Alpha\n\nweak candidate"),
        (2, "wiki/concepts/beta.md", "", 0, "Beta\n\nbest candidate"),
        (3, "wiki/concepts/gamma.md", "", 0, "Gamma\n\nmiddle candidate"),
    ]
    conn.executemany(
        "INSERT INTO chunks (id, path, anchor, pos, text) VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()
    return conn


def force_candidate_order(monkeypatch, fts, vector):
    monkeypatch.setattr(sws, "_fts_candidates", lambda conn, query, limit: fts)
    monkeypatch.setattr(sws, "_vector_candidates", lambda conn, query_vec, limit: vector)


def fake_embedder(texts, input_type):
    return [[1.0]]


def test_rerank_order_replaces_rrf_order_and_score(tmp_path, monkeypatch):
    conn = build_index(tmp_path)
    force_candidate_order(monkeypatch, [1, 2, 3], [])

    def reranker(query, documents, top_k):
        assert query == "needle"
        assert top_k == 3
        return [{"index": 1, "relevance_score": 0.91}, {"index": 0, "relevance_score": 0.42}]

    hits = sws.search_index(conn, "needle", embedder=None, k=2, reranker=reranker)

    assert [h["path"] for h in hits] == [
        "wiki/concepts/beta.md",
        "wiki/concepts/alpha.md",
    ]
    assert [h["score"] for h in hits] == [0.91, 0.42]


def test_rerank_window_is_wider_than_requested_k(tmp_path, monkeypatch):
    conn = build_index(tmp_path)
    force_candidate_order(monkeypatch, [1, 2, 3], [])

    def reranker(query, documents, top_k):
        assert top_k == 3
        assert len(documents) == 3
        return [{"index": 2, "relevance_score": 0.99}]

    hits = sws.search_index(conn, "needle", embedder=None, k=1, reranker=reranker)

    assert [h["path"] for h in hits] == ["wiki/concepts/gamma.md"]


def test_no_reranker_path_matches_rrf_order(tmp_path, monkeypatch):
    conn = build_index(tmp_path)
    force_candidate_order(monkeypatch, [1, 2, 3], [3, 2, 1])

    no_key_hits = sws.search_index(conn, "needle", embedder=fake_embedder, k=3, reranker=None)
    no_rerank_hits = sws.search_index(
        conn, "needle", embedder=fake_embedder, k=3, reranker=None
    )

    assert no_key_hits == no_rerank_hits
    assert [h["path"] for h in no_key_hits] == [
        "wiki/concepts/alpha.md",
        "wiki/concepts/gamma.md",
        "wiki/concepts/beta.md",
    ]


def test_rerank_failure_falls_back_to_rrf_order(tmp_path, monkeypatch, capsys):
    conn = build_index(tmp_path)
    force_candidate_order(monkeypatch, [1, 2, 3], [])

    def failing_reranker(query, documents, top_k):
        raise RuntimeError("rerank unavailable")

    hits = sws.search_index(conn, "needle", embedder=None, k=2, reranker=failing_reranker)

    assert [h["path"] for h in hits] == ["wiki/concepts/alpha.md", "wiki/concepts/beta.md"]
    assert "rerank unavailable" in capsys.readouterr().err


def test_rerank_returns_zero_rows_fills_from_rrf(tmp_path, monkeypatch):
    """A reranker that returns an empty list must still yield k RRF-ordered hits
    (the never-empty-a-search invariant), carrying RRF scores, not rerank scores."""
    conn = build_index(tmp_path)
    force_candidate_order(monkeypatch, [1, 2, 3], [])

    hits = sws.search_index(
        conn, "needle", embedder=None, k=2, reranker=lambda q, d, t: []
    )

    assert [h["path"] for h in hits] == [
        "wiki/concepts/alpha.md",
        "wiki/concepts/beta.md",
    ]
    # RRF scores are the rounded 1/(k+rank) fusion scores, not rerank relevance scores
    assert all(0.0 < h["score"] < 1.0 for h in hits)


def test_rerank_dedups_and_guards_out_of_range_indices(tmp_path, monkeypatch):
    """Duplicate indices are collapsed and out-of-range indices skipped; the RRF
    tail fills any shortfall so exactly k results are returned without raising."""
    conn = build_index(tmp_path)
    force_candidate_order(monkeypatch, [1, 2, 3], [])

    def reranker(query, documents, top_k):
        return [
            {"index": 99, "relevance_score": 0.95},   # out of range -> skipped
            {"index": 0, "relevance_score": 0.90},    # alpha
            {"index": 0, "relevance_score": 0.50},    # duplicate -> skipped
            {"index": -1, "relevance_score": 0.40},   # negative -> skipped
        ]

    hits = sws.search_index(conn, "needle", embedder=None, k=3, reranker=reranker)

    # alpha first (only valid rerank row), then beta+gamma from the RRF fill tail
    assert [h["path"] for h in hits] == [
        "wiki/concepts/alpha.md",
        "wiki/concepts/beta.md",
        "wiki/concepts/gamma.md",
    ]
    assert hits[0]["score"] == 0.90
    assert len(hits) == 3


def test_partial_rerank_fills_remainder_in_rrf_order(tmp_path, monkeypatch):
    """A reranker returning fewer rows than k places its row(s) first by rerank
    score, then appends the unseen candidates in their original RRF order."""
    conn = build_index(tmp_path)
    force_candidate_order(monkeypatch, [1, 2, 3], [])

    def reranker(query, documents, top_k):
        return [{"index": 2, "relevance_score": 0.99}]  # gamma only

    hits = sws.search_index(conn, "needle", embedder=None, k=3, reranker=reranker)

    assert [h["path"] for h in hits] == [
        "wiki/concepts/gamma.md",   # reranked to top
        "wiki/concepts/alpha.md",   # RRF-order fill
        "wiki/concepts/beta.md",
    ]
    assert hits[0]["score"] == 0.99
    # filled rows carry their RRF scores, not the rerank score
    assert hits[1]["score"] < 1.0 and hits[2]["score"] < 1.0


def build_typed_index(tmp_path: Path):
    """An index spanning a verbose SOURCE page and a precise CONCEPT page —
    the shape of the C1 demotion case the type-boost must correct."""
    conn = sws.open_db(tmp_path / "index.db")
    rows = [
        (1, "wiki/sources/verbose.md", "", 0, "Verbose source\n\nlong rambling source page"),
        (2, "wiki/concepts/precise.md", "", 0, "Precise concept\n\ntight concept page"),
    ]
    conn.executemany(
        "INSERT INTO chunks (id, path, anchor, pos, text) VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()
    return conn


def test_type_boost_lifts_concept_above_verbose_source(tmp_path, monkeypatch):
    """C1 reproduction: the reranker scores the SOURCE page above the CONCEPT
    page; the type-boost must reorder the concept above the source. The reported
    score stays the raw rerank relevance — the boost changes ORDER only."""
    conn = build_typed_index(tmp_path)
    force_candidate_order(monkeypatch, [1, 2], [])  # candidates: [verbose(0), precise(1)]

    def reranker(query, documents, top_k):
        return [
            {"index": 0, "relevance_score": 0.80},   # verbose source — reranker's top
            {"index": 1, "relevance_score": 0.70},   # precise concept — demoted by reranker
        ]

    hits = sws.search_index(conn, "needle", embedder=None, k=2, reranker=reranker)

    assert [h["path"] for h in hits] == [
        "wiki/concepts/precise.md",   # boosted above the source
        "wiki/sources/verbose.md",
    ]
    # reported scores are the raw rerank relevance, not the boosted ordering key
    assert [h["score"] for h in hits] == [0.70, 0.80]


def test_type_boost_does_not_bury_genuinely_best_source(tmp_path, monkeypatch):
    """A source page the reranker scores far above the concept must stay on top —
    the boost is bounded and must not flip a genuinely-best source."""
    conn = build_typed_index(tmp_path)
    force_candidate_order(monkeypatch, [1, 2], [])

    def reranker(query, documents, top_k):
        return [
            {"index": 0, "relevance_score": 0.95},   # clearly-best source
            {"index": 1, "relevance_score": 0.50},   # weaker concept
        ]

    hits = sws.search_index(conn, "needle", embedder=None, k=2, reranker=reranker)

    assert [h["path"] for h in hits] == [
        "wiki/sources/verbose.md",
        "wiki/concepts/precise.md",
    ]


def test_search_index_default_k_is_25():
    assert inspect.signature(sws.search_index).parameters["k"].default == 25


def test_cli_search_k_default_is_25():
    parser = sws.build_parser()
    args = parser.parse_args(["search", "needle"])
    assert args.k == 25


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_make_voyage_reranker_retries_retryable_http_errors(monkeypatch):
    calls = {"count": 0}
    sleeps = []

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        body = json.loads(request.data.decode("utf-8"))
        assert body == {
            "query": "needle",
            "documents": ["a", "b"],
            "model": "rerank-2.5",
            "top_k": 2,
        }
        if calls["count"] == 1:
            raise urllib.error.HTTPError(
                url="https://api.voyageai.com/v1/rerank",
                code=429,
                msg="rate limit",
                hdrs={},
                fp=io.BytesIO(b"rate limited"),
            )
        return FakeResponse(
            {"data": [{"index": 1, "relevance_score": 0.8}, {"index": 0, "relevance_score": 0.2}]}
        )

    monkeypatch.setattr(sws.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(sws.time, "sleep", lambda seconds: sleeps.append(seconds))

    reranker = sws.make_voyage_reranker("test-key")
    rows = reranker("needle", ["a", "b"], 2)

    assert rows == [{"index": 1, "relevance_score": 0.8}, {"index": 0, "relevance_score": 0.2}]
    assert calls["count"] == 2
    assert sleeps


def test_make_voyage_reranker_raises_on_non_retryable_http_error(monkeypatch):
    """A non-retryable status (e.g. 400) raises immediately without retrying —
    the error surfaces to search_index, which downgrades it to RRF order."""
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        raise urllib.error.HTTPError(
            url="https://api.voyageai.com/v1/rerank",
            code=400,
            msg="bad request",
            hdrs={},
            fp=io.BytesIO(b"malformed body"),
        )

    monkeypatch.setattr(sws.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(sws.time, "sleep", lambda seconds: None)

    reranker = sws.make_voyage_reranker("test-key")
    with pytest.raises(RuntimeError, match="Voyage rerank API error 400"):
        reranker("needle", ["a"], 1)
    assert calls["count"] == 1  # raised on the first attempt, no retry loop
