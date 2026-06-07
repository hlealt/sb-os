"""Tests for sb-wiki-search.py — hybrid semantic + keyword wiki search.

Pure-logic units run with no network; index/search integration uses a fake
embedder over a temp mini-wiki. Voyage API calls are never made from tests.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "sb-wiki-search.py"
spec = importlib.util.spec_from_file_location("sb_wiki_search", MODULE_PATH)
sws = importlib.util.module_from_spec(spec)
sys.modules["sb_wiki_search"] = sws
spec.loader.exec_module(sws)


# ---------------------------------------------------------------- chunking

PAGE = """---
type: concept
created: 2026-01-01
---
# Agentic Engineering

Intro paragraph about the practice.

## Definition

A practice of building software where agents do the work.

## Sources

[^1]: [[2026-01-01-some-source.md]]
"""


def test_chunk_page_splits_on_h2():
    chunks = sws.chunk_page(PAGE, "wiki/concepts/agentic-engineering.md")
    assert [c.anchor for c in chunks] == ["", "Definition", "Sources"]
    # every chunk is contextualized with the page title
    assert all(c.text.startswith("Agentic Engineering") for c in chunks)
    assert "A practice of building software" in chunks[1].text
    # frontmatter is not embedded
    assert "type: concept" not in chunks[0].text


def test_chunk_page_without_headings_is_single_chunk():
    text = "---\ntype: entity\n---\n# Voyage AI\n\nAn embeddings company.\n"
    chunks = sws.chunk_page(text, "wiki/entities/voyage-ai.md")
    assert len(chunks) == 1
    assert chunks[0].anchor == ""
    assert "An embeddings company." in chunks[0].text


def test_chunk_page_title_falls_back_to_stem():
    text = "Just prose, no H1.\n"
    chunks = sws.chunk_page(text, "wiki/concepts/some-idea.md")
    assert chunks[0].text.startswith("some-idea")


def test_chunk_page_splits_oversize_sections():
    para = "word " * 200  # ~1000 chars
    text = "# Big\n\n## Long\n\n" + "\n\n".join([para] * 5)
    chunks = sws.chunk_page(text, "wiki/topics/big.md", max_chars=1500)
    assert len(chunks) > 1
    assert all(c.anchor == "Long" for c in chunks)
    assert [c.pos for c in chunks] == list(range(len(chunks)))


# ---------------------------------------------------------------- walking

def build_mini_wiki(root: Path) -> Path:
    wiki_root = root / "kb"
    for rel, body in {
        "wiki/concepts/concepts.md": "| File | Description |\n",  # leaf index
        "wiki/concepts/alpha.md": "# Alpha\n\nThe car page. sem-car.\n",
        "wiki/entities/persons/persons.md": "| File | Description |\n",  # subfolder leaf index
        "wiki/entities/persons/ada.md": "# Ada\n\nA person.\n",
        "wiki/sources/blog/blog.md": "| File | What it says | My take |\n",  # origin index
        "wiki/sources/blog/2026-01-01-post.md": "# Post\n\nA fruit essay.\n",
        "wiki/CLAUDE.md": "# routing\n",
        "wiki/topics/debate.md": "# Debate\n\nOpinions differ.\n",
        "raw/blog/2026-01-01-post.md": "raw text, never indexed\n",
        "log.md": "# log\n",
    }.items():
        p = wiki_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return wiki_root


def test_walk_wiki_excludes_indexes_claude_md_raw_and_log(tmp_path):
    wiki_root = build_mini_wiki(tmp_path)
    files = sws.walk_wiki(wiki_root)
    assert files == [
        "wiki/concepts/alpha.md",
        "wiki/entities/persons/ada.md",
        "wiki/sources/blog/2026-01-01-post.md",
        "wiki/topics/debate.md",
    ]


# ---------------------------------------------------------------- diffing

def test_diff_files_detects_added_changed_removed():
    stored = {"a.md": "h1", "b.md": "h2", "c.md": "h3"}
    current = {"b.md": "h2", "c.md": "CHANGED", "d.md": "h4"}
    added, changed, removed = sws.diff_files(stored, current)
    assert added == {"d.md"}
    assert changed == {"c.md"}
    assert removed == {"a.md"}


# ---------------------------------------------------------------- fusion

def test_rrf_fuse_rewards_presence_in_both_rankings():
    fused = sws.rrf_fuse([[1, 2, 3], [2, 9]])
    ids = [i for i, _ in fused]
    assert ids[0] == 2  # appears in both lists
    assert set(ids) == {1, 2, 3, 9}
    scores = dict(fused)
    assert scores[2] == pytest.approx(1 / 61 + 1 / 62)


# ------------------------------------------------------- fake embedder

VOCAB = {
    # synonyms share a direction — semantic match without shared tokens
    "car": 0, "vehicle": 0,
    "fruit": 1, "banana": 1,
    "debate": 2,
}


def fake_embedder_factory(calls):
    def fake_embedder(texts, input_type):
        calls.append((len(texts), input_type))
        out = []
        for t in texts:
            v = [0.0] * 4
            for word in t.lower().replace("-", " ").split():
                if word in VOCAB:
                    v[VOCAB[word]] += 1.0
            n = math.sqrt(sum(x * x for x in v))
            out.append([x / n for x in v] if n else v)
        return out
    return fake_embedder


# ------------------------------------------------- index + search (sqlite)

@pytest.fixture()
def indexed(tmp_path):
    wiki_root = build_mini_wiki(tmp_path)
    calls = []
    embedder = fake_embedder_factory(calls)
    conn = sws.open_db(tmp_path / "index.db")
    counts = sws.sync(conn, wiki_root, embedder=embedder)
    return wiki_root, conn, embedder, calls, counts


def test_sync_indexes_all_pages_once(indexed):
    _, conn, _, calls, counts = indexed
    assert counts["added"] == 4
    assert counts["embedded"] > 0
    assert all(it == "document" for _, it in calls)


def test_sync_rerun_is_incremental_no_embedding_calls(indexed):
    wiki_root, conn, embedder, calls, _ = indexed
    calls.clear()
    counts = sws.sync(conn, wiki_root, embedder=embedder)
    assert counts == {"added": 0, "changed": 0, "removed": 0, "embedded": 0}
    assert calls == []  # zero API calls on a no-change rerun


def test_search_semantic_match_without_shared_keyword(indexed):
    _, conn, embedder, _, _ = indexed
    # alpha.md says "car"; the query says "vehicle" — no token overlap
    hits = sws.search_index(conn, "vehicle", embedder=embedder, k=3)
    assert hits[0]["path"] == "wiki/concepts/alpha.md"


def test_search_fts_exact_token(indexed):
    _, conn, embedder, _, _ = indexed
    # "sem-car" appears verbatim only in alpha.md; embedder knows nothing of it
    hits = sws.search_index(conn, "sem-car", embedder=embedder, k=3)
    assert hits and hits[0]["path"] == "wiki/concepts/alpha.md"


def test_search_type_filter(indexed):
    _, conn, embedder, _, _ = indexed
    hits = sws.search_index(conn, "fruit", embedder=embedder, k=5,
                            type_filter=["concept"])
    assert all(h["path"].startswith("wiki/concepts/") for h in hits)


def test_sync_picks_up_changed_file_and_removals(indexed):
    wiki_root, conn, embedder, calls, _ = indexed
    (wiki_root / "wiki/topics/debate.md").write_text(
        "# Debate\n\nNow about banana economics.\n", encoding="utf-8")
    (wiki_root / "wiki/concepts/alpha.md").unlink()
    calls.clear()
    counts = sws.sync(conn, wiki_root, embedder=embedder)
    assert counts["changed"] == 1 and counts["removed"] == 1
    hits = sws.search_index(conn, "banana", embedder=embedder, k=3)
    assert hits[0]["path"] == "wiki/topics/debate.md"
    assert not any(h["path"] == "wiki/concepts/alpha.md"
                   for h in sws.search_index(conn, "vehicle", embedder=embedder, k=5))


def test_sync_persists_progress_when_embedder_fails_midway(tmp_path, monkeypatch):
    """Rate-limit abort mid-embedding must not roll back structural state or
    already-embedded batches; the next sync resumes from where it stopped."""
    monkeypatch.setattr(sws, "EMBED_BATCH_TEXTS", 1)  # force one flush per chunk
    wiki_root = build_mini_wiki(tmp_path)
    conn = sws.open_db(tmp_path / "index.db")
    good = fake_embedder_factory([])
    state = {"calls": 0}

    def flaky(texts, input_type):
        state["calls"] += 1
        if state["calls"] > 1:
            raise RuntimeError("429 rate limited")
        return good(texts, input_type)

    with pytest.raises(RuntimeError):
        sws.sync(conn, wiki_root, embedder=flaky)
    conn.close()  # simulate the process dying after the abort

    conn2 = sws.open_db(tmp_path / "index.db")
    assert conn2.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 4
    first_pass = conn2.execute(
        "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0]
    assert first_pass >= 1  # the successful batch survived

    counts = sws.sync(conn2, wiki_root, embedder=good)
    assert counts["added"] == 0 and counts["embedded"] > 0  # resumed, not rebuilt
    total = conn2.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    embedded = conn2.execute(
        "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0]
    assert embedded == total


def test_fts_only_mode_without_embedder(tmp_path):
    wiki_root = build_mini_wiki(tmp_path)
    conn = sws.open_db(tmp_path / "index.db")
    counts = sws.sync(conn, wiki_root, embedder=None)
    assert counts["added"] == 4 and counts["embedded"] == 0
    hits = sws.search_index(conn, "sem-car", embedder=None, k=3)
    assert hits and hits[0]["path"] == "wiki/concepts/alpha.md"
