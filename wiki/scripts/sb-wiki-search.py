#!/usr/bin/env python3
"""Hybrid semantic + keyword search over the wiki page tree.

Maintains a local SQLite index (FTS5 keyword table + Voyage embedding
vectors) over `{wiki_root}/wiki/**/*.md` and answers ranked queries for
agents. The semantic tier is availability-gated per the wiki schema:

- `VOYAGE_API_KEY` set      -> hybrid mode (FTS5 BM25 + vector cosine, RRF-fused)
- key absent                -> FTS5-only mode (no API calls, still ranked)
- wiki root unresolvable    -> exit 2 (callers fall back to grep)

`search` self-heals before answering: changed/added/removed pages are
re-indexed incrementally (mtime+size prefilter, sha256 confirm), so results
never go stale. Embedding spend is incremental — unchanged files are never
re-embedded.

Commands:
    index  [--full]                    build / refresh the index
    search QUERY [--k N] [--type t,..] [--json] [--no-sync]
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
EMBED_URL = "https://api.voyageai.com/v1/embeddings"
EMBED_BATCH_TEXTS = 96
EMBED_BATCH_CHARS = 240_000
MAX_CHUNK_CHARS = 6_000
CANDIDATES_PER_ARM = 50
RRF_K = 60
NON_PAGE_FILES = {"CLAUDE.md", "AGENTS.md", "README.md"}
TYPE_PREFIXES = {
    "concept": "wiki/concepts/",
    "entity": "wiki/entities/",
    "topic": "wiki/topics/",
    "source": "wiki/sources/",
    "thesis": "wiki/theses/",
    "decision": "wiki/decisions/",
}


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


def resolve_wiki_root(vault_root: Path) -> Path:
    manifest = json.loads(read_text(vault_root / "sb-os.json"))
    return vault_root / manifest["wiki_root"]


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

    Excludes leaf/origin indexes (`{dir}/{dir}.md`) and non-page files; `raw/`
    and root-level queues (`log.md`, `questions.md`, ...) are outside `wiki/`.
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


def search_index(conn: sqlite3.Connection, query: str, embedder=None,
                 k: int = 8, type_filter: list | None = None) -> list[dict]:
    rankings = []
    fts = _fts_candidates(conn, query, CANDIDATES_PER_ARM)
    if fts:
        rankings.append(fts)
    if embedder is not None:
        qvec = embedder([query], "query")[0]
        vec = _vector_candidates(conn, qvec, CANDIDATES_PER_ARM)
        if vec:
            rankings.append(vec)
    if not rankings:
        return []

    prefixes = None
    if type_filter:
        prefixes = tuple(TYPE_PREFIXES[t] for t in type_filter)

    results: list[dict] = []
    for chunk_id, score in rrf_fuse(rankings):
        row = conn.execute(
            "SELECT path, anchor, text FROM chunks WHERE id=?", (chunk_id,)
        ).fetchone()
        if row is None:
            continue
        path, anchor, text = row
        if prefixes and not path.startswith(prefixes):
            continue
        snippet = " ".join(text.split())[:240]
        results.append({"path": path, "anchor": anchor,
                        "score": round(score, 6), "snippet": snippet})
        if len(results) >= k:
            break
    return results


# ---------------------------------------------------------------- voyage

def make_voyage_embedder(api_key: str, model: str = DEFAULT_MODEL):
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
                with urllib.request.urlopen(request, timeout=120) as resp:
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


# ---------------------------------------------------------------- CLI

def _default_db(wiki_root: Path) -> Path:
    return wiki_root / ".sb-wiki-search" / "index.db"


def _check_model(conn: sqlite3.Connection, model: str) -> None:
    row = conn.execute("SELECT value FROM meta WHERE key='model'").fetchone()
    if row and row[0] != model:
        sys.exit(f"index was built with model '{row[0]}' but '{model}' requested — "
                 f"run `index --full` to rebuild, or pass --model {row[0]}")
    if not row:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('model', ?)", (model,))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--vault-root", type=Path, default=Path.cwd())
    parser.add_argument("--db", type=Path, help="index db path (default {wiki_root}/.sb-wiki-search/index.db)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="build or refresh the index")
    p_index.add_argument("--full", action="store_true", help="wipe and rebuild from scratch")

    p_search = sub.add_parser("search", help="query the index")
    p_search.add_argument("query")
    p_search.add_argument("--k", type=int, default=8)
    p_search.add_argument("--type", help="comma-separated: concept,entity,topic,source,thesis,decision")
    p_search.add_argument("--json", action="store_true")
    p_search.add_argument("--no-sync", action="store_true", help="skip the freshness sync")

    sub.add_parser("status", help="index freshness + mode as JSON")

    args = parser.parse_args()

    try:
        wiki_root = resolve_wiki_root(args.vault_root.resolve())
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as err:
        print(f"cannot resolve wiki_root from sb-os.json: {err}", file=sys.stderr)
        return 2
    if not (wiki_root / "wiki").is_dir():
        print(f"no wiki tree at {wiki_root / 'wiki'}", file=sys.stderr)
        return 2

    api_key = os.environ.get("VOYAGE_API_KEY")
    embedder = make_voyage_embedder(api_key, args.model) if api_key else None
    mode = "hybrid" if embedder else "fts-only"
    db_path = args.db or _default_db(wiki_root)
    conn = open_db(db_path)
    if embedder:
        _check_model(conn, args.model)

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
            print("VOYAGE_API_KEY not set — vector tier off, keyword (FTS5) tier active",
                  file=sys.stderr)
        return 0

    if args.command == "search":
        if not args.no_sync:
            counts = sync(conn, wiki_root, embedder=embedder)
            if any(counts.values()):
                print(f"synced: +{counts['added']} ~{counts['changed']} -{counts['removed']} "
                      f"files, {counts['embedded']} chunks embedded", file=sys.stderr)
        type_filter = [t.strip() for t in args.type.split(",")] if args.type else None
        try:
            hits = search_index(conn, args.query, embedder=embedder, k=args.k,
                                type_filter=type_filter)
        except KeyError as err:
            print(f"unknown --type {err}; valid: {', '.join(TYPE_PREFIXES)}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"mode": mode, "query": args.query, "results": hits},
                             ensure_ascii=False, indent=2))
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
        meta = dict(conn.execute("SELECT key, value FROM meta"))
        print(json.dumps({
            "ready": files > 0, "mode": mode, "db": str(db_path),
            "files": files, "chunks": chunks, "embedded_chunks": embedded,
            "model": meta.get("model"), "last_sync": meta.get("last_sync"),
        }, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
