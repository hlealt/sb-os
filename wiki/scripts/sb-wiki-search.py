#!/usr/bin/env python3
"""Hybrid semantic + keyword search over the wiki page tree.

Maintains a local SQLite index (FTS5 keyword table + Voyage embedding
vectors) over `{wiki_root}/wiki/**/*.md` and answers ranked queries for
agents. The semantic tier is availability-gated per the wiki schema:

- key available (`VOYAGE_API_KEY` env var, else `{vault_root}/.user/config/env/.env`)
                            -> hybrid mode (FTS5 BM25 + vector cosine, RRF-fused)
- key absent                -> FTS5-only mode (no API calls, still ranked)
- wiki root unresolvable    -> `probe` and `search --json` return a clean
                               {"available": false, ...} verdict (exit 0) so a
                               mandatory caller always has parseable output; other
                               commands keep exit 2 (callers fall back to grep)

`search` self-heals before answering: changed/added/removed pages are
re-indexed incrementally (mtime+size prefilter, sha256 confirm), so results
never go stale. Embedding spend is incremental — unchanged files are never
re-embedded.

Commands:
    index  [--full]                    build / refresh the page index
    index-raw [--glob G] [--json]      embed raw/** sources into the raw tables
                                       (thin-page detector chunked-recall input;
                                       per-vector model id, OD-2 model invalidation)
    search QUERY [--k N] [--type t,..] [--json] [--no-sync]
    probe                              availability + mode as JSON (no query)
    status                             index freshness + mode as JSON

The index lives at `{wiki_root}/.sb-wiki-search/index.db` (derived data —
keep it out of vault git). This script only reads wiki content; it never
writes a wiki page.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from array import array
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "voyage-3.5"
DEFAULT_RERANK_MODEL = "rerank-2.5"
EMBED_URL = "https://api.voyageai.com/v1/embeddings"
RERANK_URL = "https://api.voyageai.com/v1/rerank"
VOYAGE_TIMEOUT = 30  # explicit per-request socket timeout (s) — bounds a stalled
                     # Voyage call so the caller never hangs; failures degrade to FTS
EMBED_BATCH_TEXTS = 96
EMBED_BATCH_CHARS = 240_000
MAX_CHUNK_CHARS = 6_000
CANDIDATES_PER_ARM = 50
RRF_K = 60
NON_PAGE_FILES = {"CLAUDE.md", "AGENTS.md", "README.md"}

# Raw-source embedding (consumed by the thin-page detector's chunked-recall layer).
# Raw sources are embedded into a SEPARATE table pair (raw_files / raw_chunks) so the
# pages-only index (files / chunks / chunks_fts) and the search CLI are never touched.
# Windows are FIXED-SIZE sliding windows over the raw body (NOT H2-split): pypdf paper
# twins have no clean heading structure, so a heading splitter degrades on the highest-
# stakes sources (synthesis §2b / decisions D-3). ~900 tokens at ~4 chars/token ≈ 3600
# chars, 15% overlap. The model id is stored PER VECTOR so an embedding-model upgrade
# invalidates and re-embeds stale raw vectors (OD-2 guardrail — the hash/mtime prefilter
# covers a content change but NOT a model change).
RAW_WINDOW_CHARS = 3_600          # ~900 tokens at ~4 chars/token
RAW_WINDOW_OVERLAP = 0.15         # 15% overlap between consecutive windows
RAW_CHARS_PER_TOKEN = 4.0         # coarse token estimate for window sizing only
TYPE_PREFIXES = {
    "concept": "wiki/concepts/",
    "entity": "wiki/entities/",
    "topic": "wiki/topics/",
    "source": "wiki/sources/",
    "thesis": "wiki/theses/",
    "decision": "wiki/decisions/",
}
# Rerank type-boost (C1 ruling, 2026-06-12 → tune): rerank-2.5 systematically
# prefers verbose SOURCE pages and can demote a precise concept/topic/thesis page
# out of the visible window. After rerank we multiply each candidate's relevance
# by this factor for the favored KINDS, then re-sort by the boosted key. The boost
# changes ORDER only — the reported score stays the raw rerank relevance. The
# magnitude is conservative: it flips a near-tie demotion without burying a
# source the reranker scored decisively higher.
RERANK_TYPE_BOOST = 1.25
RERANK_BOOST_KINDS = ("concept", "topic", "thesis")


def _kind_for_path(path: str) -> str | None:
    for kind, prefix in TYPE_PREFIXES.items():
        if path.startswith(prefix):
            return kind
    return None


def _type_boost(path: str) -> float:
    return RERANK_TYPE_BOOST if _kind_for_path(path) in RERANK_BOOST_KINDS else 1.0


def _fspath(path: Path) -> str:
    """Return an OS path safe to open on Windows past the 260-char MAX_PATH."""
    raw = os.path.abspath(os.fspath(path))
    if os.name == "nt" and len(raw) >= 260 and not raw.startswith("\\\\?\\"):
        return "\\\\?\\" + raw
    return raw


def read_text(path: Path) -> str:
    with open(_fspath(path), "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _find_vault_root() -> Path | None:
    """Walk up from the script's own directory, then from cwd, to find sb-os.json.

    Returns the directory containing sb-os.json, or None if not found.
    """
    for start in (Path(__file__).resolve().parent, Path.cwd().resolve()):
        candidate = start
        for _ in range(20):  # cap ascent to 20 levels
            if (candidate / "sb-os.json").is_file():
                return candidate
            parent = candidate.parent
            if parent == candidate:
                break
            candidate = parent
    return None


def resolve_wiki_root(vault_root: Path) -> Path:
    manifest = json.loads(read_text(vault_root / "sb-os.json"))
    return vault_root / manifest["wiki_root"]


def resolve_api_key(vault_root: Path) -> str | None:
    """VOYAGE_API_KEY from the environment, else from `.user/config/env/.env`."""
    key = os.environ.get("VOYAGE_API_KEY")
    if key:
        return key
    env_file = vault_root / ".user" / "config" / "env" / ".env"
    if env_file.is_file():
        for line in read_text(env_file).splitlines():
            line = line.strip()
            if line.startswith("VOYAGE_API_KEY="):
                value = line.split("=", 1)[1].strip().strip("'\"")
                if value:
                    return value
    return None


# ---------------------------------------------------------------- chunking

@dataclass
class Chunk:
    anchor: str  # H2 heading text; "" for the preamble
    pos: int     # sequential chunk position within the page
    text: str    # contextualized text actually indexed/embedded


_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.S)
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
_H2_SPLIT_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)


def _split_oversize(content: str, max_chars: int) -> list[str]:
    if len(content) <= max_chars:
        return [content]
    parts: list[str] = []
    buf = ""
    for para in content.split("\n\n"):
        while len(para) > max_chars:  # single paragraph longer than the cap
            parts.append(para[:max_chars])
            para = para[max_chars:]
        if buf and len(buf) + len(para) + 2 > max_chars:
            parts.append(buf)
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf.strip():
        parts.append(buf)
    return parts


def chunk_page(text: str, rel_path: str, max_chars: int = MAX_CHUNK_CHARS) -> list[Chunk]:
    """Split a wiki page into heading-level chunks, each prefixed with the page title."""
    body = _FRONTMATTER_RE.sub("", text, count=1)
    h1 = _H1_RE.search(body)
    title = h1.group(1).strip() if h1 else Path(rel_path).stem
    if h1:
        body = body[:h1.start()] + body[h1.end():]

    sections: list[tuple[str, str]] = []
    matches = list(_H2_SPLIT_RE.finditer(body))
    preamble = body[: matches[0].start()] if matches else body
    sections.append(("", preamble))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections.append((m.group(1).strip(), body[m.end():end]))

    chunks: list[Chunk] = []
    pos = 0
    for anchor, content in sections:
        content = content.strip()
        if not content:
            continue
        for part in _split_oversize(content, max_chars):
            header = f"{title} — {anchor}" if anchor else title
            chunks.append(Chunk(anchor=anchor, pos=pos, text=f"{header}\n\n{part.strip()}"))
            pos += 1
    return chunks


# ---------------------------------------------------------------- walking

def walk_wiki(wiki_root: Path) -> list[str]:
    """Indexable pages under `{wiki_root}/wiki/` as sorted wiki_root-relative posix paths.

    Excludes leaf/origin indexes (`{dir}/{dir}.md`) and non-page files; `raw/`,
    the `logs/` queue folder, and root-level queues (`questions.md`, ...) are
    outside `wiki/`.
    """
    pages_root = wiki_root / "wiki"
    if not pages_root.is_dir():
        return []
    out: list[str] = []
    for path in pages_root.rglob("*.md"):
        if path.name in NON_PAGE_FILES or path.stem == path.parent.name:
            continue
        out.append(path.relative_to(wiki_root).as_posix())
    return sorted(out)


def diff_files(stored: dict[str, str], current: dict[str, str]) -> tuple[set, set, set]:
    """(added, changed, removed) path sets from {path: hash} maps."""
    added = set(current) - set(stored)
    removed = set(stored) - set(current)
    changed = {p for p in set(stored) & set(current) if stored[p] != current[p]}
    return added, changed, removed


# -------------------------------------------------------------- raw walking + windowing

def walk_raw(wiki_root: Path) -> list[str]:
    """Indexable raw sources under `{wiki_root}/raw/` as sorted wiki_root-relative posix
    paths. Excludes origin index files (`{dir}/{dir}.md`) and non-page files, mirroring
    `walk_wiki` so a raw origin's own index (e.g. `raw/a16z/a16z.md`) is not embedded."""
    raw_root = wiki_root / "raw"
    if not raw_root.is_dir():
        return []
    out: list[str] = []
    for path in raw_root.rglob("*.md"):
        if path.name in NON_PAGE_FILES or path.stem == path.parent.name:
            continue
        out.append(path.relative_to(wiki_root).as_posix())
    return sorted(out)


def _strip_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub("", text, count=1)


def window_raw(text: str, rel_path: str,
               window_chars: int = RAW_WINDOW_CHARS,
               overlap: float = RAW_WINDOW_OVERLAP) -> list[Chunk]:
    """Split a raw source into FIXED-SIZE sliding character windows (NOT H2-split).

    Frontmatter is dropped; the remaining body is sliced into ~`window_chars` windows
    with `overlap` fractional overlap, each title-prefixed (filename stem, raw sources
    rarely carry a clean H1). `anchor` records the window's char span; `pos` is the
    sequential window index. Heading-independent by design so headingless pypdf paper
    twins window cleanly (synthesis §2b)."""
    body = _strip_frontmatter(text).strip()
    title = Path(rel_path).stem
    if not body:
        return []
    step = max(1, int(window_chars * (1.0 - overlap)))
    windows: list[Chunk] = []
    pos = 0
    start = 0
    n = len(body)
    while start < n:
        end = min(start + window_chars, n)
        segment = body[start:end].strip()
        if segment:
            windows.append(Chunk(anchor=f"{start}:{end}", pos=pos,
                                 text=f"{title}\n\n{segment}"))
            pos += 1
        if end >= n:
            break
        start += step
    return windows


# ---------------------------------------------------------------- fusion

def rrf_fuse(rankings: list[list], k: int = RRF_K) -> list[tuple]:
    """Reciprocal-rank fusion: score(id) = sum over rankings of 1/(k + rank)."""
    scores: dict = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


# ---------------------------------------------------------------- storage

def open_db(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_fspath(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY, hash TEXT NOT NULL,
            mtime REAL NOT NULL, size INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY, path TEXT NOT NULL,
            anchor TEXT NOT NULL, pos INTEGER NOT NULL,
            text TEXT NOT NULL, embedding BLOB
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text);
        -- Raw-source embeddings (thin-page detector chunked-recall layer). SEPARATE
        -- from the pages tables above so the existing index + search CLI are untouched.
        -- raw_chunks.model carries the embedding model id PER VECTOR so a model upgrade
        -- invalidates stale raw vectors (OD-2). No FTS table for raw: the detector's
        -- BM25 floor is computed in-process over the raw windows, not via SQLite FTS.
        CREATE TABLE IF NOT EXISTS raw_files (
            path TEXT PRIMARY KEY, hash TEXT NOT NULL,
            mtime REAL NOT NULL, size INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS raw_chunks (
            id INTEGER PRIMARY KEY, path TEXT NOT NULL,
            anchor TEXT NOT NULL, pos INTEGER NOT NULL,
            text TEXT NOT NULL, embedding BLOB, model TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_raw_chunks_path ON raw_chunks(path);
        """
    )
    return conn


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm > 0 else vec


def _delete_paths(conn: sqlite3.Connection, paths: set) -> None:
    for path in paths:
        ids = [r[0] for r in conn.execute("SELECT id FROM chunks WHERE path=?", (path,))]
        conn.executemany("DELETE FROM chunks_fts WHERE rowid=?", [(i,) for i in ids])
        conn.execute("DELETE FROM chunks WHERE path=?", (path,))
        conn.execute("DELETE FROM files WHERE path=?", (path,))


def sync(conn: sqlite3.Connection, wiki_root: Path, embedder=None) -> dict:
    """Bring the index up to date with the wiki tree. Returns change counts.

    Embedding is incremental: only chunks without a stored vector are sent to
    the embedder (changed files have their chunks rewritten, so they qualify).
    """
    stored = {
        path: (h, mtime, size)
        for path, h, mtime, size in conn.execute("SELECT path, hash, mtime, size FROM files")
    }
    current_hashes: dict[str, str] = {}
    texts: dict[str, str] = {}
    stats: dict[str, tuple[float, int]] = {}
    for rel in walk_wiki(wiki_root):
        stat = (wiki_root / rel).stat()
        stats[rel] = (stat.st_mtime, stat.st_size)
        prior = stored.get(rel)
        if prior and prior[1] == stat.st_mtime and prior[2] == stat.st_size:
            current_hashes[rel] = prior[0]  # mtime+size unchanged -> trust stored hash
            continue
        text = read_text(wiki_root / rel)
        texts[rel] = text
        current_hashes[rel] = sha256_text(text)

    added, changed, removed = diff_files({p: v[0] for p, v in stored.items()}, current_hashes)

    _delete_paths(conn, removed | changed)
    for rel in sorted(added | changed):
        text = texts.get(rel)
        if text is None:
            text = read_text(wiki_root / rel)
        for chunk in chunk_page(text, rel):
            cur = conn.execute(
                "INSERT INTO chunks (path, anchor, pos, text) VALUES (?,?,?,?)",
                (rel, chunk.anchor, chunk.pos, chunk.text),
            )
            conn.execute(
                "INSERT INTO chunks_fts (rowid, text) VALUES (?,?)",
                (cur.lastrowid, chunk.text),
            )
        mtime, size = stats[rel]
        conn.execute(
            "INSERT OR REPLACE INTO files (path, hash, mtime, size) VALUES (?,?,?,?)",
            (rel, current_hashes[rel], mtime, size),
        )
    # refresh mtime/size for touched-but-identical files so the prefilter stays warm
    for rel, (mtime, size) in stats.items():
        if rel in current_hashes and rel not in (added | changed):
            conn.execute("UPDATE files SET mtime=?, size=? WHERE path=?", (mtime, size, rel))
    conn.commit()  # structural state survives an embedding-phase abort

    embedded = 0
    if embedder is not None:
        pending = conn.execute(
            "SELECT id, text FROM chunks WHERE embedding IS NULL ORDER BY id"
        ).fetchall()
        if pending:
            print(f"embedding {len(pending)} chunks...", file=sys.stderr)
        batch: list[tuple[int, str]] = []
        batch_chars = 0
        def flush() -> int:
            nonlocal batch, batch_chars
            if not batch:
                return 0
            vectors = embedder([t for _, t in batch], "document")
            for (chunk_id, _), vec in zip(batch, vectors):
                blob = array("f", _normalize(vec)).tobytes()
                conn.execute("UPDATE chunks SET embedding=? WHERE id=?", (blob, chunk_id))
            conn.commit()  # each embedded batch survives a later abort (resumable)
            n = len(batch)
            batch, batch_chars = [], 0
            return n
        for chunk_id, text in pending:
            if batch and (len(batch) >= EMBED_BATCH_TEXTS
                          or batch_chars + len(text) > EMBED_BATCH_CHARS):
                embedded += flush()
            batch.append((chunk_id, text))
            batch_chars += len(text)
        embedded += flush()

    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_sync', ?)",
        (time.strftime("%Y-%m-%dT%H:%M:%S"),),
    )
    conn.commit()
    return {"added": len(added), "changed": len(changed),
            "removed": len(removed), "embedded": embedded}


# ---------------------------------------------------------------- raw sync (detector)

def _delete_raw_paths(conn: sqlite3.Connection, paths: set) -> None:
    for path in paths:
        conn.execute("DELETE FROM raw_chunks WHERE path=?", (path,))
        conn.execute("DELETE FROM raw_files WHERE path=?", (path,))


def sync_raw(conn: sqlite3.Connection, wiki_root: Path, embedder=None,
             model: str = DEFAULT_MODEL, glob: str | None = None) -> dict:
    """Embed raw sources under `{wiki_root}/raw/` into raw_files / raw_chunks, incrementally.

    Mirrors `sync` (mtime+size prefilter, sha256 confirm) but writes the SEPARATE raw
    tables, so the pages index and search CLI are untouched. Two invalidation paths:

      1. content change — hash/mtime/size differs → re-window + re-embed (same as pages);
      2. model change (OD-2) — any raw chunk whose stored `model` != the requested `model`
         is dropped and re-embedded, so a model upgrade never leaves stale raw vectors.

    `glob` (a wiki_root-relative fnmatch pattern, e.g. `raw/papers/*frontier*`) bounds the
    walked set so a caller can embed a SMALL subset (cost/time bound) without touching the
    rest. `embedder=None` (no key) still maintains structure (windows/files) but embeds
    nothing — the detector then reports chunked-recall OFF rather than a false all-clear.
    Returns change counts including `reembedded_model` (OD-2 invalidations)."""
    import fnmatch

    raw_rels = walk_raw(wiki_root)
    if glob:
        raw_rels = [r for r in raw_rels if fnmatch.fnmatch(r, glob)]

    stored = {
        path: (h, mtime, size)
        for path, h, mtime, size in conn.execute(
            "SELECT path, hash, mtime, size FROM raw_files")
    }
    current_hashes: dict[str, str] = {}
    texts: dict[str, str] = {}
    stats: dict[str, tuple[float, int]] = {}
    for rel in raw_rels:
        stat = (wiki_root / rel).stat()
        stats[rel] = (stat.st_mtime, stat.st_size)
        prior = stored.get(rel)
        if prior and prior[1] == stat.st_mtime and prior[2] == stat.st_size:
            current_hashes[rel] = prior[0]
            continue
        text = read_text(wiki_root / rel)
        texts[rel] = text
        current_hashes[rel] = sha256_text(text)

    # content-change diff (only over the walked subset — never touches rows outside `glob`)
    stored_sub = {p: stored[p][0] for p in stored if p in set(raw_rels)}
    added, changed, _ = diff_files(stored_sub, current_hashes)

    _delete_raw_paths(conn, changed)
    for rel in sorted(added | changed):
        text = texts.get(rel)
        if text is None:
            text = read_text(wiki_root / rel)
        for w in window_raw(text, rel):
            conn.execute(
                "INSERT INTO raw_chunks (path, anchor, pos, text, embedding, model) "
                "VALUES (?,?,?,?,NULL,NULL)",
                (rel, w.anchor, w.pos, w.text),
            )
        mtime, size = stats[rel]
        conn.execute(
            "INSERT OR REPLACE INTO raw_files (path, hash, mtime, size) VALUES (?,?,?,?)",
            (rel, current_hashes[rel], mtime, size),
        )
    for rel, (mtime, size) in stats.items():
        if rel in current_hashes and rel not in (added | changed):
            conn.execute("UPDATE raw_files SET mtime=?, size=? WHERE path=?",
                         (mtime, size, rel))

    # OD-2: invalidate raw vectors embedded under a DIFFERENT model id, within the walked
    # subset. Null the embedding so the incremental embed pass below re-embeds them.
    reembedded_model = 0
    if embedder is not None and raw_rels:
        placeholders = ",".join("?" for _ in raw_rels)
        stale = conn.execute(
            f"SELECT id FROM raw_chunks WHERE embedding IS NOT NULL "
            f"AND (model IS NULL OR model != ?) AND path IN ({placeholders})",
            (model, *raw_rels),
        ).fetchall()
        reembedded_model = len(stale)
        for (cid,) in stale:
            conn.execute(
                "UPDATE raw_chunks SET embedding=NULL, model=NULL WHERE id=?", (cid,))
    conn.commit()  # structural + invalidation state survives an embedding-phase abort

    embedded = 0
    if embedder is not None:
        if raw_rels:
            placeholders = ",".join("?" for _ in raw_rels)
            pending = conn.execute(
                f"SELECT id, text FROM raw_chunks WHERE embedding IS NULL "
                f"AND path IN ({placeholders}) ORDER BY id",
                tuple(raw_rels),
            ).fetchall()
        else:
            pending = []
        if pending:
            print(f"embedding {len(pending)} raw chunks...", file=sys.stderr)
        batch: list[tuple[int, str]] = []
        batch_chars = 0

        def flush() -> int:
            nonlocal batch, batch_chars
            if not batch:
                return 0
            vectors = embedder([t for _, t in batch], "document")
            for (chunk_id, _), vec in zip(batch, vectors):
                blob = array("f", _normalize(vec)).tobytes()
                conn.execute("UPDATE raw_chunks SET embedding=?, model=? WHERE id=?",
                             (blob, model, chunk_id))
            conn.commit()
            n = len(batch)
            batch, batch_chars = [], 0
            return n

        for chunk_id, text in pending:
            if batch and (len(batch) >= EMBED_BATCH_TEXTS
                          or batch_chars + len(text) > EMBED_BATCH_CHARS):
                embedded += flush()
            batch.append((chunk_id, text))
            batch_chars += len(text)
        embedded += flush()

    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('raw_last_sync', ?)",
        (time.strftime("%Y-%m-%dT%H:%M:%S"),),
    )
    conn.commit()
    return {"raw_added": len(added), "raw_changed": len(changed),
            "embedded": embedded, "reembedded_model": reembedded_model,
            "raw_files_scanned": len(raw_rels)}


# ---------------------------------------------------------------- search

def _fts_candidates(conn: sqlite3.Connection, query: str, limit: int) -> list[int]:
    tokens = re.findall(r"[\w\-]+", query.lower())
    if not tokens:
        return []
    match = " OR ".join(f'"{t}"' for t in tokens)
    try:
        rows = conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? "
            "ORDER BY bm25(chunks_fts) LIMIT ?",
            (match, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r[0] for r in rows]


def _vector_candidates(conn: sqlite3.Connection, query_vec: list[float], limit: int) -> list[int]:
    qv = _normalize(query_vec)
    if not any(qv):
        return []
    rows = conn.execute(
        "SELECT id, embedding FROM chunks WHERE embedding IS NOT NULL"
    ).fetchall()
    if not rows:
        return []
    try:
        import numpy as np
        ids = [r[0] for r in rows]
        mat = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32)
        mat = mat.reshape(len(rows), -1)
        sims = mat @ np.asarray(qv, dtype=np.float32)
        order = np.argsort(-sims)[:limit]
        return [ids[i] for i in order]
    except ImportError:
        scored = []
        for chunk_id, blob in rows:
            vec = array("f")
            vec.frombytes(blob)
            scored.append((sum(a * b for a, b in zip(vec, qv)), chunk_id))
        scored.sort(key=lambda s: (-s[0], s[1]))
        return [chunk_id for _, chunk_id in scored[:limit]]


def _hit(path: str, anchor: str, text: str, score: float) -> dict:
    snippet = " ".join(text.split())[:240]
    return {"path": path, "anchor": anchor, "score": round(score, 6), "snippet": snippet}


def search_index(conn: sqlite3.Connection, query: str, embedder=None,
                 k: int = 25, type_filter: list | None = None,
                 reranker=None) -> list[dict]:
    rankings = []
    fts = _fts_candidates(conn, query, CANDIDATES_PER_ARM)
    if fts:
        rankings.append(fts)
    if embedder is not None:
        try:
            qvec = embedder([query], "query")[0]
            vec = _vector_candidates(conn, qvec, CANDIDATES_PER_ARM)
            if vec:
                rankings.append(vec)
        except Exception as err:
            # mirror the no-key fallback: drop the vector tier, answer from FTS
            print(f"voyage embedding unavailable; using keyword (FTS5) tier ({err})",
                  file=sys.stderr)
    if not rankings:
        return []

    prefixes = None
    if type_filter:
        prefixes = tuple(TYPE_PREFIXES[t] for t in type_filter)

    candidates: list[dict] = []
    for chunk_id, score in rrf_fuse(rankings):
        row = conn.execute(
            "SELECT path, anchor, text FROM chunks WHERE id=?", (chunk_id,)
        ).fetchone()
        if row is None:
            continue
        path, anchor, text = row
        if prefixes and not path.startswith(prefixes):
            continue
        candidates.append({"path": path, "anchor": anchor, "text": text, "score": score})

    if reranker is not None and candidates:
        try:
            rows = reranker(query, [c["text"] for c in candidates], len(candidates))
            reranked: list[tuple[float, dict]] = []  # (boosted_sort_key, hit)
            seen: set[int] = set()
            for row in rows:
                index = int(row["index"])
                if index < 0 or index >= len(candidates) or index in seen:
                    continue
                seen.add(index)
                candidate = candidates[index]
                score = float(row["relevance_score"])
                boosted = score * _type_boost(candidate["path"])
                reranked.append(
                    (boosted,
                     _hit(candidate["path"], candidate["anchor"], candidate["text"], score))
                )
            # Type-boost reorders the reranked rows; sort is stable, so rows sharing
            # a boosted key keep the reranker's original order. The reported score
            # stays the raw relevance — only the ORDER reflects the boost.
            reranked.sort(key=lambda r: r[0], reverse=True)
            results: list[dict] = [hit for _, hit in reranked]
            # RRF-fill tail: candidates the reranker did not return, in RRF order,
            # carrying their RRF scores (never a rerank relevance score).
            for index, candidate in enumerate(candidates):
                if index in seen:
                    continue
                results.append(_hit(candidate["path"], candidate["anchor"],
                                    candidate["text"], candidate["score"]))
            return results[:k]
        except Exception as err:
            print(f"voyage rerank unavailable; using RRF order ({err})", file=sys.stderr)

    return [_hit(c["path"], c["anchor"], c["text"], c["score"]) for c in candidates[:k]]


# ---------------------------------------------------------------- voyage

def make_voyage_embedder(api_key: str, model: str = DEFAULT_MODEL,
                         timeout: float = VOYAGE_TIMEOUT):
    def embed(texts: list[str], input_type: str) -> list[list[float]]:
        payload = json.dumps(
            {"input": texts, "model": model, "input_type": input_type}
        ).encode("utf-8")
        request = urllib.request.Request(
            EMBED_URL, data=payload,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
        )
        last_error: Exception | None = None
        for attempt in range(1, 7):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                rows = sorted(data["data"], key=lambda d: d["index"])
                return [r["embedding"] for r in rows]
            except urllib.error.HTTPError as err:
                last_error = err
                if err.code not in (429, 500, 502, 503, 529):
                    raise RuntimeError(
                        f"Voyage API error {err.code}: "
                        f"{err.read().decode(errors='replace')[:300]}")
                if err.code == 429 and attempt >= 2 and len(texts) > 8:
                    # likely a tokens-per-minute cap — halve the batch
                    mid = len(texts) // 2
                    print(f"429: splitting batch of {len(texts)}", file=sys.stderr)
                    return embed(texts[:mid], input_type) + embed(texts[mid:], input_type)
                retry_after = err.headers.get("Retry-After") if err.headers else None
                wait = min(float(retry_after) if retry_after else 2 ** attempt, 65.0)
            except (urllib.error.URLError, TimeoutError) as err:
                last_error = err
                wait = min(2 ** attempt, 65.0)
            print(f"voyage retry {attempt}/6 in {wait:.0f}s ({last_error})", file=sys.stderr)
            time.sleep(wait)
        raise RuntimeError(f"Voyage API unreachable after 6 attempts: {last_error}")
    return embed


def make_voyage_reranker(api_key: str, model: str = DEFAULT_RERANK_MODEL,
                         timeout: float = VOYAGE_TIMEOUT):
    def rerank(query: str, documents: list[str], top_k: int) -> list[dict]:
        payload = json.dumps(
            {"query": query, "documents": documents, "model": model, "top_k": top_k}
        ).encode("utf-8")
        request = urllib.request.Request(
            RERANK_URL, data=payload,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
        )
        last_error: Exception | None = None
        for attempt in range(1, 7):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                return data["data"]
            except urllib.error.HTTPError as err:
                last_error = err
                if err.code not in (429, 500, 502, 503, 529):
                    raise RuntimeError(
                        f"Voyage rerank API error {err.code}: "
                        f"{err.read().decode(errors='replace')[:300]}")
                retry_after = err.headers.get("Retry-After") if err.headers else None
                wait = min(float(retry_after) if retry_after else 2 ** attempt, 65.0)
            except (urllib.error.URLError, TimeoutError) as err:
                last_error = err
                wait = min(2 ** attempt, 65.0)
            time.sleep(wait)
        raise RuntimeError(f"Voyage rerank API unreachable after 6 attempts: {last_error}")
    return rerank


# ---------------------------------------------------------------- CLI

def _default_db(wiki_root: Path) -> Path:
    return wiki_root / ".sb-wiki-search" / "index.db"


def _index_file_count(db_path: Path) -> int:
    """Indexed-file count WITHOUT creating the db. 0 when no index exists yet."""
    db_path = Path(db_path)
    if not db_path.is_file():
        return 0
    try:
        conn = sqlite3.connect(_fspath(db_path))
        try:
            return conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def availability_verdict(vault_root: Path, *, db_path: Path | None = None,
                         api_key="__auto__") -> dict:
    """Wiki availability + mode as a verdict dict — never builds or writes an index.

    The reusable "is-wiki-available" capability behind the `probe` command. Shape:
    {available, ready, mode, pages, reason}. `available` = the wiki tree is present;
    `ready` = an index is already built; `mode` = hybrid/fts-only/unavailable; `pages`
    = indexable pages on disk. The not-installed shape is identical with available=false
    so callers branch on one stable schema. `api_key="__auto__"` resolves the key from
    env/.env (production); pass an explicit key or None to force the mode in tests.
    """
    try:
        wiki_root = resolve_wiki_root(vault_root)
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as err:
        return {"available": False, "ready": False, "mode": "unavailable",
                "pages": 0, "reason": f"cannot resolve wiki_root from sb-os.json: {err}"}
    if not (wiki_root / "wiki").is_dir():
        return {"available": False, "ready": False, "mode": "unavailable",
                "pages": 0, "reason": f"no wiki tree at {wiki_root / 'wiki'}"}
    if api_key == "__auto__":
        api_key = resolve_api_key(vault_root)
    db = db_path or _default_db(wiki_root)
    return {"available": True, "ready": _index_file_count(db) > 0,
            "mode": "hybrid" if api_key else "fts-only",
            "pages": len(walk_wiki(wiki_root)), "reason": "ok"}


def _emit_unavailable(args: argparse.Namespace, reason: str) -> int:
    """Not-installed exit path. `probe` and `search --json` get a clean JSON verdict
    (exit 0) so a mandatory caller always has parseable output; every other command
    keeps the historical stderr message + exit 2 (callers fall back to grep)."""
    if args.command == "probe":
        print(json.dumps({"available": False, "ready": False, "mode": "unavailable",
                          "pages": 0, "reason": reason}, indent=2))
        return 0
    if args.command == "search" and getattr(args, "json", False):
        print(json.dumps({"available": False, "mode": "unavailable",
                          "query": args.query, "results": [], "reason": reason},
                         ensure_ascii=False, indent=2))
        return 0
    print(reason, file=sys.stderr)
    return 2


def _check_model(conn: sqlite3.Connection, model: str) -> None:
    row = conn.execute("SELECT value FROM meta WHERE key='model'").fetchone()
    if row and row[0] != model:
        sys.exit(f"index was built with model '{row[0]}' but '{model}' requested — "
                 f"run `index --full` to rebuild, or pass --model {row[0]}")
    if not row:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('model', ?)", (model,))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--vault-root", type=Path, default=None,
                        help="vault root (directory containing sb-os.json); "
                             "auto-detected by walking up from the script location when omitted")
    parser.add_argument("--db", type=Path, help="index db path (default {wiki_root}/.sb-wiki-search/index.db)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="build or refresh the index")
    p_index.add_argument("--full", action="store_true", help="wipe and rebuild from scratch")

    p_index_raw = sub.add_parser(
        "index-raw",
        help="embed raw/** sources into the raw tables (thin-page detector input)")
    p_index_raw.add_argument(
        "--glob", default=None,
        help="wiki_root-relative fnmatch to bound the embedded subset "
             "(e.g. 'raw/papers/*frontier*') — embeds only matching raw sources")
    p_index_raw.add_argument(
        "--json", action="store_true", help="emit change counts as JSON")

    p_search = sub.add_parser("search", help="query the index")
    p_search.add_argument("query")
    p_search.add_argument("--k", type=int, default=25)
    p_search.add_argument("--type", help="comma-separated: concept,entity,topic,source,thesis,decision")
    p_search.add_argument("--json", action="store_true")
    p_search.add_argument("--no-sync", action="store_true", help="skip the freshness sync")
    p_search.add_argument("--no-rerank", action="store_true",
                          help="skip Voyage rerank and return RRF-fused order")
    p_search.add_argument("--rerank-model", default=DEFAULT_RERANK_MODEL)

    sub.add_parser("probe", help="availability + mode as JSON (no query) — is the wiki installed/ready?")
    sub.add_parser("status", help="index freshness + mode as JSON")
    return parser


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    parser = build_parser()
    args = parser.parse_args()

    if args.vault_root is not None:
        vault_root = args.vault_root.resolve()
    else:
        vault_root = _find_vault_root()
        if vault_root is None:
            return _emit_unavailable(
                args, "cannot resolve vault root: sb-os.json not found in script directory "
                "ancestors or cwd ancestors; pass --vault-root explicitly")

    if args.command == "probe":
        print(json.dumps(availability_verdict(vault_root, db_path=args.db), indent=2))
        return 0

    try:
        wiki_root = resolve_wiki_root(vault_root)
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as err:
        return _emit_unavailable(args, f"cannot resolve wiki_root from sb-os.json: {err}")
    if not (wiki_root / "wiki").is_dir():
        return _emit_unavailable(args, f"no wiki tree at {wiki_root / 'wiki'}")

    api_key = resolve_api_key(vault_root)
    embedder = make_voyage_embedder(api_key, args.model) if api_key else None
    mode = "hybrid" if embedder else "fts-only"
    db_path = args.db or _default_db(wiki_root)
    conn = open_db(db_path)
    # index-raw owns its own per-vector model id (raw_chunks.model, OD-2) and is
    # intentionally decoupled from the pages-index model guard — running it with a
    # different --model must NOT abort (that is how a raw model upgrade is exercised).
    if embedder and args.command != "index-raw":
        _check_model(conn, args.model)

    if args.command == "index-raw":
        counts = sync_raw(conn, wiki_root, embedder=embedder,
                          model=args.model, glob=args.glob)
        if args.json:
            print(json.dumps({"mode": mode, "model": args.model,
                              "glob": args.glob, **counts}, indent=2))
        else:
            print(f"raw-indexed: +{counts['raw_added']} ~{counts['raw_changed']} "
                  f"({counts['raw_files_scanned']} scanned), "
                  f"{counts['embedded']} chunks embedded, "
                  f"{counts['reembedded_model']} re-embedded (model change), mode={mode}")
        if mode == "fts-only":
            print("VOYAGE_API_KEY unavailable — raw windows recorded but NOT embedded; "
                  "chunked-recall layer OFF (typed-retention layer still detects)",
                  file=sys.stderr)
        return 0

    if args.command == "index":
        if args.full:
            conn.executescript(
                "DELETE FROM chunks_fts; DELETE FROM chunks; DELETE FROM files; DELETE FROM meta;")
            conn.commit()
            if embedder:
                _check_model(conn, args.model)
        counts = sync(conn, wiki_root, embedder=embedder)
        total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        print(f"indexed: +{counts['added']} ~{counts['changed']} -{counts['removed']} files "
              f"({total} total), {counts['embedded']} chunks embedded, mode={mode}")
        if mode == "fts-only":
            print("VOYAGE_API_KEY unavailable (env var or .user/config/env/.env) — "
                  "vector tier off, keyword (FTS5) tier active",
                  file=sys.stderr)
        return 0

    if args.command == "search":
        if not args.no_sync:
            try:
                counts = sync(conn, wiki_root, embedder=embedder)
                if any(counts.values()):
                    print(f"synced: +{counts['added']} ~{counts['changed']} -{counts['removed']} "
                          f"files, {counts['embedded']} chunks embedded", file=sys.stderr)
            except Exception as err:
                # a stalled/failed Voyage embedding must not hang or crash the query;
                # structural state is already committed, so answer from the current index
                print(f"self-sync incomplete ({err}); answering from the current index",
                      file=sys.stderr)
        type_filter = [t.strip() for t in args.type.split(",")] if args.type else None
        try:
            reranker = None
            if api_key and not args.no_rerank:
                reranker = make_voyage_reranker(api_key, args.rerank_model)
            hits = search_index(conn, args.query, embedder=embedder, k=args.k,
                                type_filter=type_filter, reranker=reranker)
        except KeyError as err:
            print(f"unknown --type {err}; valid: {', '.join(TYPE_PREFIXES)}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"available": True, "mode": mode, "query": args.query,
                              "results": hits}, ensure_ascii=False, indent=2))
        else:
            if not hits:
                print("no results", file=sys.stderr)
            for h in hits:
                location = f"{h['path']}#{h['anchor']}" if h["anchor"] else h["path"]
                print(f"{h['score']:.4f}  {location}\n        {h['snippet']}")
        return 0

    if args.command == "status":
        files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        embedded = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0]
        raw_files = conn.execute("SELECT COUNT(*) FROM raw_files").fetchone()[0]
        raw_chunks = conn.execute("SELECT COUNT(*) FROM raw_chunks").fetchone()[0]
        raw_embedded = conn.execute(
            "SELECT COUNT(*) FROM raw_chunks WHERE embedding IS NOT NULL").fetchone()[0]
        raw_models = [r[0] for r in conn.execute(
            "SELECT DISTINCT model FROM raw_chunks WHERE model IS NOT NULL")]
        meta = dict(conn.execute("SELECT key, value FROM meta"))
        print(json.dumps({
            "ready": files > 0, "mode": mode, "db": str(db_path),
            "files": files, "chunks": chunks, "embedded_chunks": embedded,
            "raw_files": raw_files, "raw_chunks": raw_chunks,
            "raw_embedded_chunks": raw_embedded, "raw_models": raw_models,
            "model": meta.get("model"), "last_sync": meta.get("last_sync"),
            "raw_last_sync": meta.get("raw_last_sync"),
        }, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
