"""Tests for resolve_context.py — the sb-os context-injection resolver — plus the
installer hook wiring (install/hooks.py) and rule orphan-deletion (install/upgrade.py).

Every fixture builds its OWN tmp_path vault with a NON-default `user_context_root`
in `sb-os.json` (proving config-driven resolution, never a hardcoded default) and
points the resolver entirely at the fixture via `--vault-root` — no real-vault
dependency. Each test drives the script the way the hook/CLI will (via main() with
argv, or run_hook() over a fixed stdin), and asserts on exit codes + stdout.

Run from this directory:
    python -m pytest test_resolve_context.py -v
"""

import io
import json
import sys
from pathlib import Path

import pytest

# resolve_context.py lives one level up from tests/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import resolve_context as rc  # noqa: E402

# install/hooks.py + install/upgrade.py live under the sb-os repo root.
# tests/ -> sb-inject-context -> workflows -> para -> sb-os repo root (parents[4]).
_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT))
import install.hooks as hooks  # noqa: E402
import install.upgrade as upgrade  # noqa: E402
import install.loaders as loaders  # noqa: E402


# A non-default context root, written into every fixture's sb-os.json, so a test
# that finds the YAML proves the root came from config and not from
# DEFAULT_CONTEXT_ROOT (".user/context/").
NON_DEFAULT_UCR = "my-context-store/"
NON_DEFAULT_SB_OS = "vendor/sb-os/"


# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #

def make_vault(tmp_path, ucr=NON_DEFAULT_UCR, sb_os_path=NON_DEFAULT_SB_OS):
    """Create a tmp vault with a config-driven sb-os.json. Returns the root."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "sb-os.json").write_text(
        json.dumps({"user_context_root": ucr, "sb_os_path": sb_os_path}),
        encoding="utf-8",
    )
    return tmp_path


def write_yaml(vault, rel, text):
    """Write a context YAML at vault/rel (rel is relative to the vault root)."""
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def run_cli(vault, *flags, capsys):
    """Run main() with --vault-root pinned to the fixture; return (rc, stdout)."""
    argv = ["--vault-root", str(vault), *flags]
    rc_code = rc.main(argv)
    out = capsys.readouterr().out
    return rc_code, out


def run_hook_event(vault, event, monkeypatch, capsys):
    """Drive run_hook() with a fixed stdin event JSON; return (rc, stdout).

    The hook mode auto-detects the vault root (no --vault-root), so we cd into
    the fixture so find_vault_root walks up to its sb-os.json.
    """
    monkeypatch.chdir(vault)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
    rc_code = rc.run_hook()
    out = capsys.readouterr().out
    return rc_code, out


# =========================================================================== #
# Criterion 1 — skill path -> {ucr}/skills/{name}.yaml
# =========================================================================== #

def test_skill_path_resolves_under_ucr_skills(tmp_path, capsys):
    vault = make_vault(tmp_path)
    write_yaml(
        vault, f"{NON_DEFAULT_UCR}skills/my-skill.yaml",
        "context:\n  - name: n\n    type: text\n    content: HELLO-SKILL\n",
    )
    code, out = run_cli(vault, "--surface", "skill", "--name", "my-skill", capsys=capsys)
    assert code == 0
    assert "HELLO-SKILL" in out
    # path-only proves the exact resolved location is {ucr}/skills/{name}.yaml
    code2, out2 = run_cli(vault, "--surface", "skill", "--name", "my-skill",
                          "--path-only", capsys=capsys)
    assert code2 == 0
    assert out2.strip() == f"{NON_DEFAULT_UCR}skills/my-skill.yaml"


# =========================================================================== #
# Criterion 2 — step path mirrors workflow-relative path (.md->.yaml) across
#   BOTH .user/workflows/ and {sb_os_path}/{module}/workflows/; unknown root -> exit 2
# =========================================================================== #

def test_step_path_under_user_workflows(tmp_path, capsys):
    vault = make_vault(tmp_path)
    step = vault / ".user" / "workflows" / "wf" / "steps" / "s1.md"
    step.parent.mkdir(parents=True, exist_ok=True)
    step.write_text("# step", encoding="utf-8")
    code, out = run_cli(vault, "--surface", "step", "--file", str(step),
                        "--path-only", capsys=capsys)
    assert code == 0
    assert out.strip() == f"{NON_DEFAULT_UCR}wf/steps/s1.yaml"


def test_step_path_under_sb_os_module_workflows(tmp_path, capsys):
    vault = make_vault(tmp_path)
    # {sb_os_path}/<module>/workflows/<wf>/<step>.md
    step = vault / NON_DEFAULT_SB_OS.rstrip("/") / "para" / "workflows" / "wf" / "deep" / "s2.md"
    step.parent.mkdir(parents=True, exist_ok=True)
    step.write_text("# step", encoding="utf-8")
    code, out = run_cli(vault, "--surface", "step", "--file", str(step),
                        "--path-only", capsys=capsys)
    assert code == 0
    # relative-to the module workflows root is wf/deep/s2 -> mirrored under ucr
    assert out.strip() == f"{NON_DEFAULT_UCR}wf/deep/s2.yaml"


def test_step_under_no_known_root_errors_exit_2(tmp_path, capsys):
    vault = make_vault(tmp_path)
    stray = vault / "somewhere" / "else" / "step.md"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text("# step", encoding="utf-8")
    code, out = run_cli(vault, "--surface", "step", "--file", str(stray), capsys=capsys)
    assert code == 2
    assert "not under a known workflow root" in out


# =========================================================================== #
# Criterion 3 — NO CONTEXT (exit 0) for missing YAML AND for empty context list
# =========================================================================== #

def test_no_context_missing_yaml(tmp_path, capsys):
    vault = make_vault(tmp_path)
    code, out = run_cli(vault, "--surface", "skill", "--name", "absent", capsys=capsys)
    assert code == 0
    assert out.strip() == "NO CONTEXT"


def test_no_context_empty_list(tmp_path, capsys):
    vault = make_vault(tmp_path)
    write_yaml(vault, f"{NON_DEFAULT_UCR}skills/empty.yaml", "context: []\n")
    code, out = run_cli(vault, "--surface", "skill", "--name", "empty", capsys=capsys)
    assert code == 0
    assert out.strip() == "NO CONTEXT"


# =========================================================================== #
# Criterion 4 — text + file(read) content loaded inline
# =========================================================================== #

def test_text_and_file_read_loaded_inline(tmp_path, capsys):
    vault = make_vault(tmp_path)
    (vault / "data").mkdir()
    (vault / "data" / "doc.md").write_text("FILE-BODY-CONTENT", encoding="utf-8")
    write_yaml(
        vault, f"{NON_DEFAULT_UCR}skills/mix.yaml",
        "context:\n"
        "  - name: t\n    type: text\n    content: INLINE-TEXT-CONTENT\n"
        "  - name: f\n    type: file\n    mode: read\n    path: data/doc.md\n",
    )
    code, out = run_cli(vault, "--surface", "skill", "--name", "mix", capsys=capsys)
    assert code == 0
    assert "INLINE-TEXT-CONTENT" in out
    assert "FILE-BODY-CONTENT" in out


# =========================================================================== #
# Criterion 5 — sections extraction prints only named headings, excludes others
# =========================================================================== #

def test_sections_extraction_includes_only_named(tmp_path, capsys):
    vault = make_vault(tmp_path)
    (vault / "data").mkdir()
    (vault / "data" / "sec.md").write_text(
        "# Alpha\nalpha-body\n# Beta\nbeta-body\n# Gamma\ngamma-body\n",
        encoding="utf-8",
    )
    write_yaml(
        vault, f"{NON_DEFAULT_UCR}skills/secs.yaml",
        "context:\n  - name: s\n    type: file\n    mode: read\n"
        "    path: data/sec.md\n    sections: [Beta]\n",
    )
    code, out = run_cli(vault, "--surface", "skill", "--name", "secs", capsys=capsys)
    assert code == 0
    assert "beta-body" in out
    assert "alpha-body" not in out
    assert "gamma-body" not in out


# =========================================================================== #
# Criterion 6 — glob/select/count selection
# =========================================================================== #

def test_glob_select_latest_count(tmp_path, capsys):
    vault = make_vault(tmp_path)
    d = vault / "logs"
    d.mkdir()
    for i in range(1, 5):
        (d / f"log-{i}.md").write_text(f"BODY-{i}", encoding="utf-8")
    write_yaml(
        vault, f"{NON_DEFAULT_UCR}skills/g.yaml",
        "context:\n  - name: g\n    type: file\n    mode: read\n"
        "    path: logs\n    glob: 'log-*.md'\n    select: latest\n    count: 2\n",
    )
    code, out = run_cli(vault, "--surface", "skill", "--name", "g", capsys=capsys)
    assert code == 0
    # latest 2 of a sorted list = log-3, log-4
    assert "BODY-3" in out
    assert "BODY-4" in out
    assert "BODY-1" not in out
    assert "BODY-2" not in out


# =========================================================================== #
# Criterion 7 — script/url/mcp/write-mode/unresolved-placeholder -> AGENT ACTION,
#   never executed
# =========================================================================== #

def test_agent_action_surfaces_never_executes(tmp_path, capsys):
    vault = make_vault(tmp_path)
    write_yaml(
        vault, f"{NON_DEFAULT_UCR}skills/actions.yaml",
        "context:\n"
        "  - name: sc\n    type: script\n    command: echo\n    args: [DANGER]\n"
        "  - name: u\n    type: url\n    url: https://example.test/x\n"
        "  - name: m\n    type: mcp\n    server: srv\n    tool: tl\n    params: {a: 1}\n"
        "  - name: w\n    type: file\n    mode: write\n    path: out/result.md\n"
        "  - name: ph\n    type: file\n    mode: read\n    path: data/{week}/file.md\n",
    )
    code, out = run_cli(vault, "--surface", "skill", "--name", "actions", capsys=capsys)
    assert code == 0
    # All five surfaced as AGENT ACTION; exactly five action blocks expected.
    assert out.count("AGENT ACTION") == 5
    assert "run command" in out
    assert "fetch URL" in out
    assert "call MCP tool" in out
    assert "write output to this destination" in out
    assert "did not resolve to an existing file as-is" in out
    # Proof of non-execution: the write-mode destination file was never created.
    assert not (vault / "out" / "result.md").exists()


# =========================================================================== #
# Criterion 8 — malformed YAML -> CANNOT PARSE, exit 3, no traceback
# =========================================================================== #

def test_malformed_yaml_cannot_parse_exit_3(tmp_path, capsys):
    vault = make_vault(tmp_path)
    # Unbalanced bracket -> a YAMLError, not a dict.
    write_yaml(vault, f"{NON_DEFAULT_UCR}skills/bad.yaml",
               "context: [this is : : not valid yaml\n  - broken\n")
    code, out = run_cli(vault, "--surface", "skill", "--name", "bad", capsys=capsys)
    assert code == 3
    assert "CANNOT PARSE" in out
    assert "Traceback" not in out


# =========================================================================== #
# Criterion 9 — --path-only for an existing AND a not-yet-existing surface
# =========================================================================== #

def test_path_only_existing_and_absent(tmp_path, capsys):
    vault = make_vault(tmp_path)
    write_yaml(vault, f"{NON_DEFAULT_UCR}skills/here.yaml",
               "context:\n  - name: n\n    type: text\n    content: x\n")
    code, out = run_cli(vault, "--surface", "skill", "--name", "here",
                        "--path-only", "--json", capsys=capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload["exists"] is True
    assert payload["path"] == f"{NON_DEFAULT_UCR}skills/here.yaml"

    code2, out2 = run_cli(vault, "--surface", "skill", "--name", "nope",
                          "--path-only", "--json", capsys=capsys)
    assert code2 == 0
    payload2 = json.loads(out2)
    assert payload2["exists"] is False
    assert payload2["path"] == f"{NON_DEFAULT_UCR}skills/nope.yaml"


# =========================================================================== #
# Criterion 10 — --vault-root override proves user_context_root comes from
#   sb-os.json, not a hardcoded default
# =========================================================================== #

def test_ucr_read_from_config_not_default(tmp_path, capsys):
    # Two vaults: one with the non-default ucr, one with the DEFAULT ucr. The
    # SAME YAML relative path resolves differently per-config — proving the root
    # is read from sb-os.json, never baked in.
    vault_custom = make_vault(tmp_path / "custom", ucr=NON_DEFAULT_UCR)
    write_yaml(vault_custom, f"{NON_DEFAULT_UCR}skills/s.yaml",
               "context:\n  - name: n\n    type: text\n    content: CUSTOM-HIT\n")
    code, out = run_cli(vault_custom, "--surface", "skill", "--name", "s", capsys=capsys)
    assert code == 0
    assert "CUSTOM-HIT" in out

    # A vault whose config uses the DEFAULT root does NOT find the file at the
    # custom path (it would only find it under .user/context/).
    vault_default = make_vault(tmp_path / "deflt", ucr=rc.DEFAULT_CONTEXT_ROOT)
    write_yaml(vault_default, f"{NON_DEFAULT_UCR}skills/s.yaml",
               "context:\n  - name: n\n    type: text\n    content: SHOULD-NOT-LOAD\n")
    code2, out2 = run_cli(vault_default, "--surface", "skill", "--name", "s", capsys=capsys)
    assert code2 == 0
    assert out2.strip() == "NO CONTEXT"  # config points elsewhere -> not found


# =========================================================================== #
# Criterion 11 — --hook mode: PreToolUse/Skill surface AND PostToolUse/Read
#   step-file detection
# =========================================================================== #

def test_hook_pretooluse_skill(tmp_path, monkeypatch, capsys):
    vault = make_vault(tmp_path)
    write_yaml(vault, f"{NON_DEFAULT_UCR}skills/hooked.yaml",
               "context:\n  - name: n\n    type: text\n    content: HOOK-SKILL-BODY\n")
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Skill",
        "tool_input": {"skill_name": "hooked"},
    }
    code, out = run_hook_event(vault, event, monkeypatch, capsys)
    assert code == 0
    envelope = json.loads(out)
    assert envelope["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "HOOK-SKILL-BODY" in envelope["hookSpecificOutput"]["additionalContext"]


def test_hook_posttooluse_read_step(tmp_path, monkeypatch, capsys):
    vault = make_vault(tmp_path)
    step = vault / ".user" / "workflows" / "wf" / "s.md"
    step.parent.mkdir(parents=True, exist_ok=True)
    step.write_text("# step", encoding="utf-8")
    write_yaml(vault, f"{NON_DEFAULT_UCR}wf/s.yaml",
               "context:\n  - name: n\n    type: text\n    content: HOOK-STEP-BODY\n")
    event = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": str(step)},
    }
    code, out = run_hook_event(vault, event, monkeypatch, capsys)
    assert code == 0
    envelope = json.loads(out)
    assert envelope["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "HOOK-STEP-BODY" in envelope["hookSpecificOutput"]["additionalContext"]


def test_hook_non_surface_read_is_silent(tmp_path, monkeypatch, capsys):
    vault = make_vault(tmp_path)
    other = vault / "notes" / "random.md"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("# not a surface", encoding="utf-8")
    event = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": str(other)},
    }
    code, out = run_hook_event(vault, event, monkeypatch, capsys)
    assert code == 0
    assert out.strip() == ""  # fail-soft silent: no stdout for a non-surface read


# =========================================================================== #
# Criterion 12 — sync_context_hook writes the sentinel + two hook entries
# =========================================================================== #

def test_sync_context_hook_writes_sentinel_and_two_entries(tmp_path):
    target = tmp_path
    changed, msg = hooks.sync_context_hook(target, "vendor/sb-os")
    assert changed is True
    settings_path = target / ".claude" / "settings.local.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    pre = settings["hooks"]["PreToolUse"]
    post = settings["hooks"]["PostToolUse"]
    assert len(pre) == 1 and len(post) == 1
    assert pre[0]["__sb__"] == "sb:context-injection"
    assert post[0]["__sb__"] == "sb:context-injection"
    assert pre[0]["matcher"] == "Skill"
    assert post[0]["matcher"] == "Read"
    assert "resolve_context.py" in pre[0]["hooks"][0]["command"]
    assert "--hook" in post[0]["hooks"][0]["command"]
    # Idempotent: a second identical call reports unchanged.
    changed2, _ = hooks.sync_context_hook(target, "vendor/sb-os")
    assert changed2 is False


# =========================================================================== #
# Criterion 13 — remove_context_hook strips ONLY sentinel entries, leaves the rest
# =========================================================================== #

def test_remove_context_hook_preserves_foreign_entries(tmp_path):
    target = tmp_path
    settings_path = target / ".claude" / "settings.local.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    # Pre-seed a foreign hook entry + a foreign top-level key.
    foreign = {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "echo keep-me"}],
    }
    settings_path.write_text(json.dumps({
        "permissions": {"allow": ["Read"]},
        "hooks": {"PreToolUse": [foreign]},
    }), encoding="utf-8")

    hooks.sync_context_hook(target, "vendor/sb-os")
    changed, _ = hooks.remove_context_hook(target)
    assert changed is True

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    # Foreign top-level key intact.
    assert settings["permissions"] == {"allow": ["Read"]}
    # Foreign hook entry intact; no sb entries remain anywhere.
    pre = settings["hooks"]["PreToolUse"]
    assert foreign in pre
    assert all(e.get("__sb__") != "sb:context-injection" for e in pre)
    post = settings["hooks"].get("PostToolUse", [])
    assert all(e.get("__sb__") != "sb:context-injection" for e in post)


# =========================================================================== #
# Criterion 14 — upgrade orphan-deletes an installed sb rule that is no longer
#   selected; a foreign / kept rule is preserved.
#
# NOTE: the literal wording "no longer in the module manifest" is NOT how the
# code deletes a RULE orphan. find_orphaned_loaders() scans ONLY
# .claude/commands + .claude/skills (not rules). Rule orphan-deletion is done by
# upgrade._clear_orphans(), which removes an installed rule whose manifest
# `target` is no longer in the SELECTED modules. This test exercises that real
# mechanism: an installed sb rule from a now-deselected module is deleted, while
# a kept rule and a non-manifest foreign rule survive. See the flag in the return.
# =========================================================================== #

def test_clear_orphans_deletes_deselected_rule_keeps_others(tmp_path):
    target = tmp_path
    rules_dir = target / ".claude" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    # Discover a real (module, rule-target) pair from the live manifest so the
    # test stays valid as the manifest evolves: pick a rule in a NON-core module
    # so we can deselect that module.
    modules = loaders.manifest_modules()
    deselected_rule = None
    deselected_module = None
    kept_rule = None
    for mod_name, mod in modules.items():
        if mod.get("always_installed"):
            for e in mod.get("rules", []):
                kept_rule = kept_rule or e["target"].replace("\\", "/")
        else:
            for e in mod.get("rules", []):
                deselected_rule = e["target"].replace("\\", "/")
                deselected_module = mod_name
                break
        if deselected_rule and kept_rule:
            break

    if deselected_rule is None:
        pytest.skip("manifest has no non-core module rule to deselect")

    # Lay down the installed rule files on disk.
    installed_deselected = target / deselected_rule
    installed_deselected.parent.mkdir(parents=True, exist_ok=True)
    installed_deselected.write_text("sb rule body", encoding="utf-8")

    foreign = rules_dir / "user-custom-rule.md"
    foreign.write_text("user owns this", encoding="utf-8")

    kept_file = None
    if kept_rule:
        kept_file = target / kept_rule
        kept_file.parent.mkdir(parents=True, exist_ok=True)
        kept_file.write_text("kept sb rule", encoding="utf-8")

    # Select ONLY the always-installed (core) modules -> the non-core module's
    # rule becomes an orphan and must be deleted.
    upgrade._clear_orphans(target, selected_modules=(), excluded_components=set())

    assert not installed_deselected.exists(), (
        "deselected sb rule should be orphan-deleted"
    )
    assert foreign.exists(), "foreign (non-manifest) rule must be preserved"
    if kept_file is not None:
        assert kept_file.exists(), "kept (selected) sb rule must be preserved"


# =========================================================================== #
# Criterion 15 — upgrade orphan-deletes an installed sb rule REMOVED from the
#   manifest ENTIRELY while its owning module stays selected — the gap that
#   _clear_orphans (de-selection only) and find_orphaned_loaders (commands +
#   skills only, never rules) both miss. find_orphaned_rules + the upgrade
#   wiring close it. A kept manifest rule, a foreign rbtv rule, and an excluded
#   sb rule all survive (bounded blast radius: .claude/rules/sb-*.md only).
# =========================================================================== #

def test_find_orphaned_rules_deletes_manifest_removed_rule_keeps_others(tmp_path):
    target = tmp_path
    rules_dir = target / ".claude" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    # The "known" universe = every rule target the live manifest declares (all
    # modules, stale included). Read from the real helper so the test stays
    # valid as the manifest evolves.
    known = upgrade._all_manifest_rule_targets()
    assert known, "manifest must declare at least one rule for this test"

    # A real manifest rule laid down on disk must be PRESERVED — still declared.
    kept_rel = sorted(known)[0]
    kept_file = target / kept_rel
    kept_file.parent.mkdir(parents=True, exist_ok=True)
    kept_file.write_text("kept sb rule", encoding="utf-8")

    # An sb rule whose manifest entry was removed ENTIRELY (module still
    # selected) — the gap this closes. Name guaranteed absent from the manifest.
    removed = rules_dir / "sb-removed-from-manifest.md"
    removed.write_text("orphaned sb rule body", encoding="utf-8")
    removed_rel = removed.relative_to(target).as_posix()
    assert removed_rel not in known

    # A foreign rule (no sb- prefix) is never sb-owned -> never flagged.
    foreign = rules_dir / "rbtv-some-rule.md"
    foreign.write_text("rbtv owns this", encoding="utf-8")

    # An sb rule the user explicitly excluded -> protected, never deleted.
    excluded_sb = rules_dir / "sb-user-excluded.md"
    excluded_sb.write_text("excluded by user signal", encoding="utf-8")
    excluded_rel = excluded_sb.relative_to(target).as_posix()

    orphans = loaders.find_orphaned_rules(
        target,
        known_rule_targets=known,
        excluded={excluded_rel},
    )

    assert removed_rel in orphans, "manifest-removed sb rule must be flagged"
    assert kept_rel not in orphans, "kept (declared) sb rule must NOT be flagged"
    assert foreign.relative_to(target).as_posix() not in orphans, (
        "foreign rbtv rule must NOT be flagged"
    )
    assert excluded_rel not in orphans, "excluded sb rule must NOT be flagged"

    # Pruning deletes ONLY the orphan; everything else survives (bounded blast).
    upgrade._prune_orphaned_rules(target, orphans)
    assert not removed.exists(), "orphaned sb rule should be deleted"
    assert kept_file.exists(), "kept sb rule must be preserved"
    assert foreign.exists(), "foreign rbtv rule must be preserved"
    assert excluded_sb.exists(), "excluded sb rule must be preserved"


# =========================================================================== #
# Criterion 16 — the planned deletion of a manifest-removed rule is surfaced in
#   the upgrade plan (owner sees every deletion before the confirm prompt).
# =========================================================================== #

def test_build_upgrade_plan_surfaces_orphaned_rule_deletion(tmp_path):
    plan = upgrade.build_upgrade_plan(
        wiki_root="3-resources/knowledge-base/wiki",
        user_context_root=".user/context/",
        selected_modules=(),
        excluded_components=set(),
        install_wiki=False,
        orphaned_rules=[".claude/rules/sb-removed-from-manifest.md"],
    )
    deletions = [
        a for a in plan.actions
        if a.category == "delete"
        and a.target == ".claude/rules/sb-removed-from-manifest.md"
    ]
    assert len(deletions) == 1, "orphaned rule deletion must appear once in the plan"
    assert "rule removed while module stays selected" in deletions[0].detail
