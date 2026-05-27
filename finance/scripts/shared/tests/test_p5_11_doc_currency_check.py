"""Tests for the doc-currency pre-commit HARD BLOCK (p5-11) — layer 3.

The hook BLOCKS a commit that changes a coupled code/config surface without
staging the doc that describes it; PASSES when the doc is staged alongside the
code; the block message names the stale doc + the doc-maintainer fix path; and
it fails LOUD (never silently passes) when its manifest cannot be read.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import doc_currency_check as dcc


_MANIFEST = {
    "version": "1.0",
    "couplings": [
        {
            "node_id": "expenses_schema_and_classifier",
            "code": [
                "scripts/shared/categorize.py",
                ".user/finance/bookkeeper/config/categories.json",
            ],
            "docs": [
                {"path": "docs/expenses-data.md", "sections": ["Schema"]},
            ],
        },
        {
            "node_id": "tool_registry",
            "code": ["scripts/shared/gate_*.py"],
            "docs": [
                {"path": "scripts/tools-index.md", "sections": ["Registered Tools"]},
            ],
        },
        {
            # signal-only — mirrors the real manifest: pipeline-shape staleness is
            # a judgment, so it is NOT commit-gated.
            "node_id": "pipeline_shape",
            "enforcement": "signal-only",
            "code": ["scripts/shared/normalize.py"],
            "docs": [
                {"path": "docs/architecture.md", "sections": ["pipelines"]},
                {
                    "path": "1-projects/finance-system/finance-system-v2-foundation/phase-2/data-flow-map-target.md",
                    "sections": ["Gastos Pipeline — TARGET"],
                },
            ],
        },
        {
            # A HARD-BLOCK coupling with TWO in-repo docs — staging EITHER satisfies it.
            "node_id": "investimentos_schema",
            "code": ["scripts/investimentos/calculate.py"],
            "docs": [
                {"path": "docs/investimentos.md", "sections": ["schemas"]},
                {"path": "docs/financial-dashboard.md", "sections": ["views"]},
            ],
        },
    ],
}


@pytest.fixture
def manifest_file(tmp_path) -> Path:
    p = tmp_path / "doc-currency-manifest.yaml"
    p.write_text(yaml.safe_dump(_MANIFEST), encoding="utf-8")
    return p


# --- find_violations (pure, injected staged-file lists) ---------------------


def test_block_when_coupled_code_changes_without_doc():
    staged = ["finance/scripts/shared/categorize.py"]
    violations = dcc.find_violations(staged, _MANIFEST)
    assert len(violations) == 1
    assert violations[0].node_id == "expenses_schema_and_classifier"
    assert "docs/expenses-data.md" in violations[0].missing_docs


def test_pass_when_code_and_doc_both_staged():
    staged = [
        "finance/scripts/shared/categorize.py",
        "finance/docs/expenses-data.md",
    ]
    assert dcc.find_violations(staged, _MANIFEST) == []


def test_pass_when_no_coupled_code_changed():
    # A doc-only commit, or a change to an uncoupled file, never blocks.
    staged = ["finance/docs/expenses-data.md", "README.md"]
    assert dcc.find_violations(staged, _MANIFEST) == []


def test_config_surface_also_triggers_block():
    # Config files live outside the repo at runtime; the manifest keys them by
    # their vault path (`.user/...`). They match when staged under that path.
    staged = [".user/finance/bookkeeper/config/categories.json"]
    violations = dcc.find_violations(staged, _MANIFEST)
    assert len(violations) == 1
    assert violations[0].node_id == "expenses_schema_and_classifier"


def test_glob_code_pattern_blocks():
    staged = ["finance/scripts/shared/gate_coverage.py"]
    violations = dcc.find_violations(staged, _MANIFEST)
    assert len(violations) == 1
    assert violations[0].node_id == "tool_registry"


def test_either_in_repo_doc_satisfies_multi_doc_coupling():
    # investimentos_schema (hard-block) couples to TWO in-repo docs; staging
    # EITHER satisfies the gate (file-granularity, per p2-19 Option C).
    staged_a = [
        "finance/scripts/investimentos/calculate.py",
        "finance/docs/investimentos.md",
    ]
    assert dcc.find_violations(staged_a, _MANIFEST) == []

    staged_b = [
        "finance/scripts/investimentos/calculate.py",
        "finance/docs/financial-dashboard.md",
    ]
    assert dcc.find_violations(staged_b, _MANIFEST) == []


def test_pipeline_shape_signal_only_does_not_block_in_full_manifest():
    # normalize.py is coupled only to the signal-only pipeline_shape row →
    # changing it without any doc must NOT block.
    assert dcc.find_violations(["finance/scripts/shared/normalize.py"], _MANIFEST) == []


def test_multiple_violations_reported_together():
    staged = [
        "finance/scripts/shared/categorize.py",
        "finance/scripts/shared/gate_coverage.py",
    ]
    violations = dcc.find_violations(staged, _MANIFEST)
    assert {v.node_id for v in violations} == {
        "expenses_schema_and_classifier",
        "tool_registry",
    }


def test_signal_only_coupling_never_blocks():
    """A `signal-only` coupling (judgment surface) emits the layer-2 signal but
    is NOT commit-gated — changing its code without its doc must NOT block."""
    manifest = {
        "couplings": [
            {
                "node_id": "pipeline_shape",
                "enforcement": "signal-only",
                "code": ["scripts/investimentos/update_ledgers.py"],
                "docs": [{"path": "docs/architecture.md"}],
            }
        ]
    }
    staged = ["finance/scripts/investimentos/update_ledgers.py"]
    assert dcc.find_violations(staged, manifest) == []


def test_hard_block_is_the_default_when_enforcement_absent():
    """Omitting `enforcement` defaults to hard-block (fail-closed)."""
    manifest = {
        "couplings": [
            {
                "node_id": "x",
                "code": ["scripts/shared/categorize.py"],
                "docs": [{"path": "docs/expenses-data.md"}],
            }
        ]
    }
    assert len(dcc.find_violations(["finance/scripts/shared/categorize.py"], manifest)) == 1


def test_coupling_with_only_out_of_repo_docs_never_blocks():
    """A coupling whose docs all live outside the sb-os repo cannot be satisfied
    by an sb-os commit, so it must NEVER hard-block (it is layer-4 territory)."""
    manifest = {
        "couplings": [
            {
                "node_id": "foundation_only",
                "code": ["scripts/investimentos/calculate.py"],
                "docs": [
                    {
                        "path": "1-projects/finance-system/finance-system-v2-foundation/phase-2/data-flow-map-target.md"
                    }
                ],
            }
        ]
    }
    staged = ["finance/scripts/investimentos/calculate.py"]
    assert dcc.find_violations(staged, manifest) == []


def test_mixed_docs_block_keys_on_in_repo_doc_only():
    """When a hard-block coupling has both in-repo and out-of-repo docs, staging
    the in-repo doc satisfies it; the out-of-repo doc is ignored by the gate."""
    manifest = {
        "couplings": [
            {
                "node_id": "mixed",
                "code": ["scripts/investimentos/calculate.py"],
                "docs": [
                    {"path": "docs/investimentos.md"},
                    {
                        "path": "1-projects/finance-system/finance-system-v2-foundation/phase-2/data-flow-map-target.md"
                    },
                ],
            }
        ]
    }
    # code changed, in-repo doc NOT staged → block, and the missing-doc list
    # names only the in-repo doc (the stage-able one).
    v = dcc.find_violations(["finance/scripts/investimentos/calculate.py"], manifest)
    assert len(v) == 1
    assert v[0].missing_docs == ["docs/investimentos.md"]
    # code changed, in-repo doc staged → pass.
    assert (
        dcc.find_violations(
            [
                "finance/scripts/investimentos/calculate.py",
                "finance/docs/investimentos.md",
            ],
            manifest,
        )
        == []
    )


# --- block message is actionable -------------------------------------------


def test_block_message_names_stale_doc_and_fix_path(manifest_file, capsys):
    rc = dcc.run(
        manifest_path=manifest_file,
        repo_root=Path("."),
        staged_files=["finance/scripts/shared/categorize.py"],
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "COMMIT BLOCKED" in err
    assert "docs/expenses-data.md" in err  # names the stale doc
    assert "doc-maintainer" in err  # names the legitimate fix path
    assert "bypass" in err.lower()  # explicitly states no bypass flag


def test_pass_returns_zero_and_no_message(manifest_file, capsys):
    rc = dcc.run(
        manifest_path=manifest_file,
        repo_root=Path("."),
        staged_files=[
            "finance/scripts/shared/categorize.py",
            "finance/docs/expenses-data.md",
        ],
    )
    assert rc == 0
    assert "BLOCKED" not in capsys.readouterr().err


# --- fail-loud on broken manifest (a broken gate must NOT pass) -------------


def test_missing_manifest_fails_loud_exit_2(tmp_path, capsys):
    rc = dcc.run(
        manifest_path=tmp_path / "nope.yaml",
        repo_root=Path("."),
        staged_files=["finance/scripts/shared/categorize.py"],
    )
    assert rc == 2  # NOT 0 — a missing manifest blocks, never silently allows
    assert "ERROR" in capsys.readouterr().err


def test_malformed_manifest_fails_loud_exit_2(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("not: a: valid: mapping: [", encoding="utf-8")
    rc = dcc.run(
        manifest_path=bad,
        repo_root=Path("."),
        staged_files=["finance/scripts/shared/categorize.py"],
    )
    assert rc == 2


def test_manifest_without_couplings_key_fails_loud(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(yaml.safe_dump({"version": "1.0"}), encoding="utf-8")
    rc = dcc.run(
        manifest_path=p,
        repo_root=Path("."),
        staged_files=["finance/scripts/shared/categorize.py"],
    )
    assert rc == 2


# --- real-git integration smoke (proves the staged-diff read path) ----------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def tmp_git_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "finance" / "scripts" / "shared").mkdir(parents=True)
    (repo / "finance" / "docs").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.test")
    _git(repo, "config", "user.name", "t")
    # seed a committed baseline so `--cached` has a HEAD to diff against
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def test_real_git_staged_code_without_doc_blocks(tmp_git_repo, manifest_file):
    code = tmp_git_repo / "finance" / "scripts" / "shared" / "categorize.py"
    code.write_text("# changed\n", encoding="utf-8")
    _git(tmp_git_repo, "add", "finance/scripts/shared/categorize.py")

    rc = dcc.run(manifest_path=manifest_file, repo_root=tmp_git_repo, staged_files=None)
    assert rc == 1  # blocked via the real `git diff --cached` read


def test_real_git_staged_code_with_doc_passes(tmp_git_repo, manifest_file):
    (tmp_git_repo / "finance" / "scripts" / "shared" / "categorize.py").write_text(
        "# changed\n", encoding="utf-8"
    )
    (tmp_git_repo / "finance" / "docs" / "expenses-data.md").write_text(
        "updated\n", encoding="utf-8"
    )
    _git(tmp_git_repo, "add", "finance/scripts/shared/categorize.py")
    _git(tmp_git_repo, "add", "finance/docs/expenses-data.md")

    rc = dcc.run(manifest_path=manifest_file, repo_root=tmp_git_repo, staged_files=None)
    assert rc == 0


def test_real_git_doc_only_commit_passes(tmp_git_repo, manifest_file):
    (tmp_git_repo / "finance" / "docs" / "expenses-data.md").write_text(
        "doc tweak\n", encoding="utf-8"
    )
    _git(tmp_git_repo, "add", "finance/docs/expenses-data.md")
    rc = dcc.run(manifest_path=manifest_file, repo_root=tmp_git_repo, staged_files=None)
    assert rc == 0


def test_cli_main_infers_paths(tmp_git_repo, manifest_file, monkeypatch):
    # Exercise main()'s arg parsing + path inference against the real tmp repo.
    code = tmp_git_repo / "finance" / "scripts" / "shared" / "categorize.py"
    code.write_text("# changed\n", encoding="utf-8")
    _git(tmp_git_repo, "add", "finance/scripts/shared/categorize.py")
    rc = dcc.main(
        ["--manifest", str(manifest_file), "--repo-root", str(tmp_git_repo)]
    )
    assert rc == 1
