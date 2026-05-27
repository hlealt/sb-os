"""Doc-currency pre-commit HARD BLOCK — layer 3 of the Option D Hybrid mechanism.

Blocks any commit that changes a coupled CODE/CONFIG surface without staging the
DOC that describes it. This is a HARD block, not advisory: an advisory hook lets
documentation drift accumulate exactly when it matters (during a change). The
coupling is declared in `sb-os/finance/CLAUDE.md` § Documentation Currency and
encoded machine-readably in `sb-os/finance/docs/doc-currency-manifest.yaml` (the
SAME manifest the layer-2 `docs_potentially_stale` signal reads).

How it gates (file granularity, per p2-19 Option C):
  For each coupling in the manifest, if ANY staged file matches a `code`
  pattern AND NO staged file matches a coupled `docs` path, the commit is
  BLOCKED. The block message names the stale doc(s) + the fix path. Section-level
  staleness is informational (carried in the manifest/signal) — the commit-time
  gate is "was the coupled doc touched in this commit at all?".

The ONLY legitimate way past this block is to reconcile the doc — run the
`doc-maintainer` companion (layer 4) to bring the doc current, stage it, and
re-commit. There is NO bypass flag in this tool. (Git's own `--no-verify` skips
ALL hooks at the committer's own risk; this tool does not offer or advertise a
per-tool bypass, by design — RC #7 exists because drift was allowed.)

Mechanism source:
  1-projects/finance-system/finance-system-v2-foundation/phase-2/decision-prep/p2-19-documentation-currency.md

Usage (pre-commit):
    python doc_currency_check.py
        # reads `git diff --cached --name-only` (repo-relative paths) and the
        # manifest at the default path; exits non-zero on stale-doc violation.

    python doc_currency_check.py --manifest PATH --repo-root PATH
        # explicit paths (used by the hook wrapper / tests).

Exit codes:
    0   Pass — no coupled code/config change is missing its doc.
    1   Block — a coupled code/config change has no matching staged doc.
    2   Error — manifest unreadable or git unavailable (fail-loud: a broken
        gate must NOT silently allow a commit through).
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# The manifest path repo-relative to the sb-os repo root, and the finance-module
# prefix that segment lives under (so we can match the manifest's
# finance-relative `code`/`docs` patterns against repo-relative staged paths).
_DEFAULT_MANIFEST_REL = "finance/docs/doc-currency-manifest.yaml"
_FINANCE_PREFIX = "finance/"

# A coupling is commit-time HARD-BLOCKED only when its `enforcement` is this
# value AND it has at least one in-repo doc (a doc this commit could stage). A
# coupling whose docs all live OUTSIDE this repo (e.g. the foundation
# data-flow-map under `1-projects/`) cannot be satisfied by an sb-os commit, so
# it is never commit-gated — it is reconciled by the `doc-maintainer` companion
# (layer 4). The default when `enforcement` is absent is hard-block.
_ENFORCE_HARD_BLOCK = "hard-block"

# Doc paths under these prefixes live OUTSIDE the sb-os repo (they are vault
# PARA paths, e.g. the foundation data-flow-map under `1-projects/`). They cannot
# be staged in an sb-os commit, so a coupling whose docs are all out-of-repo is
# never commit-gated — it is a layer-4 (doc-maintainer) surface. Every other doc
# path in the manifest is finance-relative (`docs/...`, `scripts/...`) and is in
# this repo.
_OUT_OF_REPO_DOC_PREFIXES = (
    "0-",
    "1-projects/",
    "2-areas/",
    "3-resources/",
    "4-archives/",
    "5-workbench/",
    ".user/",
)


def _doc_is_in_repo(doc_path: str) -> bool:
    return not any(doc_path.startswith(p) for p in _OUT_OF_REPO_DOC_PREFIXES)


@dataclass
class Violation:
    """One coupling whose code changed but whose doc was not staged."""

    node_id: str
    changed_code: list[str]
    missing_docs: list[str] = field(default_factory=list)


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load the node-doc manifest. Raises on unreadable/invalid (fail-loud —
    a doc-currency gate that cannot read its own coupling must block, not pass)."""
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "couplings" not in data:
        raise ValueError(
            f"doc-currency manifest {manifest_path} has no top-level 'couplings' list"
        )
    return data


def _staged_files_from_git(repo_root: Path) -> list[str]:
    """Return repo-relative paths of files staged for commit (added/copied/
    modified/renamed — never deleted, a deletion cannot make a doc stale).

    Raises CalledProcessError / FileNotFoundError on git failure; the caller
    converts that to exit 2 (fail-loud)."""
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def _to_finance_relative(path: str) -> str:
    """A repo-relative path under `finance/` → finance-relative; else unchanged.
    The manifest's `code`/`docs` patterns are finance-relative."""
    if path.startswith(_FINANCE_PREFIX):
        return path[len(_FINANCE_PREFIX):]
    return path


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def find_violations(
    staged_files: list[str], manifest: dict[str, Any]
) -> list[Violation]:
    """Return the couplings whose code/config changed without a staged doc.

    `staged_files` are repo-relative (e.g. `finance/scripts/shared/categorize.py`,
    `1-projects/.../data-flow-map-target.md`). Both `code` and `docs` manifest
    patterns are matched finance-relative for finance-module paths; doc paths
    rooted outside `finance/` (e.g. `1-projects/...`) are matched as-is.
    """
    staged_finance = [_to_finance_relative(p) for p in staged_files]
    violations: list[Violation] = []

    for coupling in manifest.get("couplings") or []:
        if not isinstance(coupling, dict):
            continue

        # Only `hard-block` couplings are commit-gated. `signal-only` couplings
        # (architecture/pipeline-shape — a judgment the companion makes, per
        # p2-19's "hook is coarse, companion judges") are declared in the
        # manifest and emit the layer-2 signal, but never block a commit.
        enforcement = str(coupling.get("enforcement", _ENFORCE_HARD_BLOCK))
        if enforcement != _ENFORCE_HARD_BLOCK:
            continue

        code_patterns = coupling.get("code") or []
        changed_code = [
            staged_files[i]
            for i, rel in enumerate(staged_finance)
            if _matches_any(rel, code_patterns)
        ]
        if not changed_code:
            continue  # this coupling's code/config was not touched

        doc_paths = [
            d.get("path")
            for d in (coupling.get("docs") or [])
            if isinstance(d, dict) and d.get("path")
        ]
        # Only docs that live IN this repo can be staged in this commit. A
        # coupling whose docs all live outside the repo cannot be satisfied here
        # and is left to the companion — so it is never a commit-time block.
        in_repo_docs = [d for d in doc_paths if _doc_is_in_repo(d)]
        if not in_repo_docs:
            continue

        # The coupling's code changed — was at least ONE of its in-repo docs staged?
        doc_staged = any(
            _matches_any(_to_finance_relative(staged), [_to_finance_relative(doc)])
            or staged == doc
            for staged in staged_files
            for doc in in_repo_docs
        )
        if doc_staged:
            continue  # doc was updated in the same commit — coupling satisfied

        violations.append(
            Violation(
                node_id=str(coupling.get("node_id", "<unnamed>")),
                changed_code=changed_code,
                missing_docs=[str(d) for d in in_repo_docs],
            )
        )
    return violations


def _format_block_message(violations: list[Violation]) -> str:
    lines = [
        "COMMIT BLOCKED — documentation is stale relative to your code/config changes.",
        "",
        "The doc-currency hard block (p2-19 layer 3) stops a commit that changes a",
        "coupled code/config surface without updating the doc that describes it.",
        "",
    ]
    for v in violations:
        lines.append(f"  • Coupling '{v.node_id}':")
        lines.append("      You staged this code/config change:")
        for c in v.changed_code:
            lines.append(f"        - {c}")
        lines.append("      …but did NOT stage its coupled doc(s):")
        for d in v.missing_docs:
            lines.append(f"        - {d}   <-- update this, then `git add` it")
        lines.append("")
    lines += [
        "How to pass (the ONLY legitimate path — there is no bypass flag):",
        "  1. Reconcile the doc so it describes what the code/config now does.",
        "     Run the `doc-maintainer` companion",
        "     (finance/workflows/doc-maintainer/doc-maintainer.md) to bring the",
        "     listed doc(s) current with your change.",
        "  2. `git add` the updated doc(s).",
        "  3. Re-commit.",
        "",
        "Coupling source: finance/CLAUDE.md § Documentation Currency",
        "Manifest:        finance/docs/doc-currency-manifest.yaml",
    ]
    return "\n".join(lines)


def run(
    *,
    manifest_path: Path,
    repo_root: Path,
    staged_files: list[str] | None = None,
) -> int:
    """Core entry. `staged_files` injectable for tests; None → read from git.

    Returns the process exit code (0 pass / 1 block / 2 error)."""
    try:
        manifest = _load_manifest(manifest_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(
            f"ERROR: doc-currency gate could not read its manifest: {exc}\n"
            "The gate blocks (exit 2) rather than allow a commit through with a "
            "broken coupling check.",
            file=sys.stderr,
        )
        return 2

    if staged_files is None:
        try:
            staged_files = _staged_files_from_git(repo_root)
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
            print(
                f"ERROR: doc-currency gate could not read the staged diff: {exc}\n"
                "The gate blocks (exit 2) rather than allow a commit through "
                "without checking.",
                file=sys.stderr,
            )
            return 2

    violations = find_violations(staged_files, manifest)
    if violations:
        print(_format_block_message(violations), file=sys.stderr)
        return 1
    return 0


def _default_repo_root() -> Path:
    """The sb-os repo root = three levels up from this file
    (finance/scripts/shared/doc_currency_check.py → repo root)."""
    return Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Doc-currency pre-commit HARD BLOCK — refuse a commit that "
        "changes a coupled code/config surface without updating its doc."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to doc-currency-manifest.yaml (default: finance/docs/ in the repo).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repo root for the staged-diff read (default: inferred from this file).",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root or _default_repo_root()
    manifest_path = args.manifest or (repo_root / _DEFAULT_MANIFEST_REL)
    return run(manifest_path=manifest_path, repo_root=repo_root)


if __name__ == "__main__":
    sys.exit(main())
