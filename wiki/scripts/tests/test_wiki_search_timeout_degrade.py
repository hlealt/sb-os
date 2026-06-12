"""Tests for sb-wiki-search.py Voyage network-timeout + clean tier-degrade.

A stalled or unreachable Voyage endpoint must fail within an explicit socket
timeout and degrade exactly like the no-key path (EXIT 0, FTS-only results,
stderr note) instead of hanging the caller. Network calls are mocked; the live
Voyage endpoint is never contacted.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "sb-wiki-search.py"
spec = importlib.util.spec_from_file_location("sb_wiki_search_timeout", MODULE_PATH)
sws = importlib.util.module_from_spec(spec)
sys.modules["sb_wiki_search_timeout"] = sws
spec.loader.exec_module(sws)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def build_index(tmp_path: Path):
    """Index with three chunks present in BOTH the chunks table and the FTS
    index, so the real keyword tier returns candidates with no monkeypatching."""
    conn = sws.open_db(tmp_path / "index.db")
    rows = [
        (1, "wiki/concepts/alpha.md", "", 0, "Alpha needle\n\nfirst candidate"),
        (2, "wiki/concepts/beta.md", "", 0, "Beta needle\n\nsecond candidate"),
        (3, "wiki/concepts/gamma.md", "", 0, "Gamma needle\n\nthird candidate"),
    ]
    conn.executemany(
        "INSERT INTO chunks (id, path, anchor, pos, text) VALUES (?,?,?,?,?)", rows
    )
    conn.executemany(
        "INSERT INTO chunks_fts (rowid, text) VALUES (?,?)",
        [(r[0], r[4]) for r in rows],
    )
    conn.commit()
    return conn


# ---------------------------------------------------- explicit socket timeout

def test_make_voyage_embedder_uses_explicit_timeout(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["timeout"] = timeout
        return FakeResponse({"data": [{"index": 0, "embedding": [0.1, 0.2]}]})

    monkeypatch.setattr(sws.urllib.request, "urlopen", fake_urlopen)
    embed = sws.make_voyage_embedder("test-key")
    embed(["hello"], "document")

    assert seen["timeout"] == sws.VOYAGE_TIMEOUT


def test_make_voyage_reranker_uses_explicit_timeout(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["timeout"] = timeout
        return FakeResponse({"data": [{"index": 0, "relevance_score": 0.9}]})

    monkeypatch.setattr(sws.urllib.request, "urlopen", fake_urlopen)
    rerank = sws.make_voyage_reranker("test-key")
    rerank("needle", ["a"], 1)

    assert seen["timeout"] == sws.VOYAGE_TIMEOUT


def test_stalled_socket_times_out_each_attempt_then_raises(monkeypatch):
    """A socket that never answers raises TimeoutError every attempt; the call
    gives up (RuntimeError) instead of hanging, using the explicit timeout."""
    timeouts = []
    sleeps = []

    def fake_urlopen(request, timeout):
        timeouts.append(timeout)
        raise TimeoutError("timed out")

    monkeypatch.setattr(sws.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(sws.time, "sleep", lambda seconds: sleeps.append(seconds))

    embed = sws.make_voyage_embedder("test-key")
    with pytest.raises(RuntimeError, match="unreachable"):
        embed(["hello"], "query")

    assert timeouts and all(t == sws.VOYAGE_TIMEOUT for t in timeouts)
    assert sleeps  # backed off between attempts, bounded by the retry cap


# ------------------------------------------------------- search-level degrade

def test_search_index_degrades_to_fts_when_query_embed_fails(tmp_path, capsys):
    """A failing embedder at query time degrades to FTS-only ranking (mirrors the
    reranker degrade) — results still return, with a stderr note."""
    conn = build_index(tmp_path)

    def failing_embedder(texts, input_type):
        raise RuntimeError("Voyage API unreachable after 6 attempts")

    hits = sws.search_index(conn, "needle", embedder=failing_embedder, k=3, reranker=None)

    assert [h["path"] for h in hits] == [
        "wiki/concepts/alpha.md",
        "wiki/concepts/beta.md",
        "wiki/concepts/gamma.md",
    ]
    err = capsys.readouterr().err
    assert "embedding" in err.lower()


def test_search_index_with_failing_embedder_matches_no_embedder(tmp_path):
    """Degraded (failing-embedder) results are identical to the genuine no-key
    (embedder=None) path — the no-key fallback semantics, exactly."""
    conn = build_index(tmp_path)

    def failing_embedder(texts, input_type):
        raise RuntimeError("stalled")

    degraded = sws.search_index(conn, "needle", embedder=failing_embedder, k=3, reranker=None)
    no_key = sws.search_index(conn, "needle", embedder=None, k=3, reranker=None)

    assert degraded == no_key


# ------------------------------------------------------- command-level degrade

def _make_vault(tmp_path: Path) -> Path:
    wiki_root = tmp_path / "kb"
    for rel, body in {
        "wiki/concepts/concepts.md": "| File | Description |\n",
        "wiki/concepts/alpha.md": "# Alpha\n\nThe needle page about cars.\n",
        "wiki/topics/debate.md": "# Debate\n\nA needle of opinions.\n",
    }.items():
        p = wiki_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    (tmp_path / "sb-os.json").write_text(json.dumps({"wiki_root": "kb"}), encoding="utf-8")
    return wiki_root


def test_search_command_exits_zero_when_voyage_stalls_during_self_sync(
    tmp_path, monkeypatch, capsys
):
    """The `search` command with a stalled Voyage endpoint must NOT hang or crash:
    the in-call self-sync degrades, the query answers from the FTS tier, and the
    command exits 0 with results — exactly the no-key path's observable outcome."""
    _make_vault(tmp_path)
    monkeypatch.setenv("VOYAGE_API_KEY", "test-key")

    def stalled_embedder(texts, input_type):
        raise RuntimeError("Voyage API unreachable after 6 attempts")

    # key resolves -> hybrid mode is selected, but every Voyage call stalls
    monkeypatch.setattr(sws, "make_voyage_embedder", lambda key, model=None, **kw: stalled_embedder)
    monkeypatch.setattr(
        sws, "make_voyage_reranker",
        lambda key, model=None, **kw: (lambda q, d, t: (_ for _ in ()).throw(RuntimeError("stalled"))),
    )
    monkeypatch.setattr(
        sys, "argv",
        ["sb-wiki-search", "--vault-root", str(tmp_path), "search", "needle", "--json"],
    )

    rc = sws.main()

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["results"], "FTS tier must still return results when Voyage stalls"
    assert all("needle" in h["snippet"].lower() or h["path"] for h in out["results"])
