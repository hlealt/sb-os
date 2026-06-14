"""Tests for the wiki availability gate — `probe` subcommand + availability-gated
`search --json` (the sb-tutor search-first rewiring).

The unit tests drive `availability_verdict` directly with `api_key=None` for a
deterministic FTS-only mode. The CLI tests run the script as a subprocess with
VOYAGE_API_KEY stripped from the environment, so no Voyage API call is ever made.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "sb-wiki-search.py"
spec = importlib.util.spec_from_file_location("sb_wiki_search", MODULE_PATH)
sws = importlib.util.module_from_spec(spec)
sys.modules["sb_wiki_search"] = sws
spec.loader.exec_module(sws)


# ---------------------------------------------------------------- fixtures

def build_mini_wiki(root: Path) -> Path:
    """4 indexable pages (alpha, ada, post, debate); indexes/CLAUDE.md/raw excluded."""
    wiki_root = root / "kb"
    for rel, body in {
        "wiki/concepts/concepts.md": "| File | Description |\n",  # leaf index (excluded)
        "wiki/concepts/alpha.md": "# Alpha\n\nThe car page.\n",
        "wiki/entities/persons/ada.md": "# Ada\n\nA person.\n",
        "wiki/sources/blog/2026-01-01-post.md": "# Post\n\nA fruit essay.\n",
        "wiki/topics/debate.md": "# Debate\n\nOpinions differ.\n",
        "wiki/CLAUDE.md": "# routing\n",  # excluded
        "raw/blog/2026-01-01-post.md": "raw, never indexed\n",  # outside wiki/
    }.items():
        p = wiki_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return wiki_root


def vault_with_wiki(tmp_path: Path) -> Path:
    build_mini_wiki(tmp_path)
    (tmp_path / "sb-os.json").write_text(json.dumps({"wiki_root": "kb"}), encoding="utf-8")
    return tmp_path


def vault_no_wiki(tmp_path: Path) -> Path:
    (tmp_path / "sb-os.json").write_text(json.dumps({"wiki_root": "kb"}), encoding="utf-8")
    return tmp_path  # sb-os.json present, but no kb/wiki tree on disk


def run_cli(vault_root: Path, *cli_args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("VOYAGE_API_KEY", None)  # force FTS-only — no network from any test
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), "--vault-root", str(vault_root), *cli_args],
        capture_output=True, text=True, encoding="utf-8", env=env)


# ----------------------------------------- availability_verdict (unit)

def test_availability_verdict_present_wiki(tmp_path):
    v = sws.availability_verdict(vault_with_wiki(tmp_path), api_key=None)
    assert v["available"] is True
    assert v["mode"] == "fts-only"     # forced by api_key=None
    assert v["pages"] == 4             # alpha, ada, post, debate
    assert v["ready"] is False         # probe never builds the index
    assert v["reason"] == "ok"


def test_availability_verdict_hybrid_when_key_present(tmp_path):
    v = sws.availability_verdict(vault_with_wiki(tmp_path), api_key="sk-fake")
    assert v["available"] is True and v["mode"] == "hybrid"


def test_availability_verdict_no_wiki_tree(tmp_path):
    v = sws.availability_verdict(vault_no_wiki(tmp_path), api_key=None)
    assert v["available"] is False
    assert v["mode"] == "unavailable" and v["pages"] == 0
    assert "no wiki tree" in v["reason"]


def test_availability_verdict_bad_sb_os_json(tmp_path):
    (tmp_path / "sb-os.json").write_text("{not valid json", encoding="utf-8")
    v = sws.availability_verdict(tmp_path, api_key=None)
    assert v["available"] is False and v["mode"] == "unavailable"


def test_availability_verdict_has_no_side_effect(tmp_path):
    vault = vault_with_wiki(tmp_path)
    sws.availability_verdict(vault, api_key=None)
    assert not (vault / "kb" / ".sb-wiki-search").exists()  # never creates an index


def test_availability_verdict_ready_true_after_index_built(tmp_path):
    vault = vault_with_wiki(tmp_path)
    conn = sws.open_db(sws._default_db(vault / "kb"))
    sws.sync(conn, vault / "kb", embedder=None)  # build FTS index
    conn.close()
    v = sws.availability_verdict(vault, api_key=None)
    assert v["available"] is True and v["ready"] is True


# ------------------------------------------------------- probe CLI

def test_probe_cli_present_wiki_exit0(tmp_path):
    proc = run_cli(vault_with_wiki(tmp_path), "probe")
    assert proc.returncode == 0, proc.stderr
    v = json.loads(proc.stdout)
    assert v["available"] is True and v["pages"] == 4 and v["mode"] == "fts-only"


def test_probe_cli_no_wiki_clean_verdict_exit0(tmp_path):
    proc = run_cli(vault_no_wiki(tmp_path), "probe")
    assert proc.returncode == 0, proc.stderr  # NOT exit 2 — clean verdict
    v = json.loads(proc.stdout)
    assert v["available"] is False and v["mode"] == "unavailable"


# --------------------------------------- search --json availability gate

def test_search_json_present_wiki_available_and_results(tmp_path):
    proc = run_cli(vault_with_wiki(tmp_path), "search", "car", "--json")
    assert proc.returncode == 0, proc.stderr
    env = json.loads(proc.stdout)
    assert env["available"] is True
    assert env["mode"] == "fts-only"
    assert any(h["path"] == "wiki/concepts/alpha.md" for h in env["results"])


def test_search_json_no_wiki_clean_verdict_exit0(tmp_path):
    proc = run_cli(vault_no_wiki(tmp_path), "search", "anything", "--json")
    assert proc.returncode == 0, proc.stderr  # NOT exit 2 — parseable verdict
    env = json.loads(proc.stdout)
    assert env["available"] is False and env["mode"] == "unavailable"
    assert env["results"] == [] and env["query"] == "anything"


# ----------------- compatibility: non-json / other commands keep exit 2

def test_search_nonjson_no_wiki_keeps_exit2(tmp_path):
    proc = run_cli(vault_no_wiki(tmp_path), "search", "anything")
    assert proc.returncode == 2          # historical behavior preserved
    assert proc.stdout.strip() == ""     # verdict only on --json; bare search -> stderr


def test_status_no_wiki_keeps_exit2(tmp_path):
    proc = run_cli(vault_no_wiki(tmp_path), "status")
    assert proc.returncode == 2          # status contract unchanged
