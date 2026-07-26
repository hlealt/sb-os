# sb-task CLI

Agent CLI for task files (`*-tasks.md`) — the deterministic executor of the task contract in `para/workflows/sb-vault-ops/data/tasks.md`. Source: `para/cli/sb-task/sb_task.py` (Python 3 stdlib, no dependencies). Companion skill: `para/skills/sb-task/SKILL.md` → `para/cli/sb-task/sb-task.md`.

Command inventory lives in the CLI itself — run `sb-task -h` and `sb-task <command> -h`. This doc covers only what `-h` cannot: install, JSON policy, and design invariants.

## Install (per machine)

The vault-side wrapper is per-machine, never synced by git:

- **Windows:** `%USERPROFILE%\.local\bin\sb-task.cmd` containing `@echo off` + `python "<abs path to sb_task.py>" %*`.
- **Linux/macOS:** symlink `~/.local/bin/sb-task` → `sb_task.py` (executable bit set), or an equivalent two-line sh wrapper.

`python <path>/sb_task.py …` always works with no install. The CLI finds the vault by walking up from the current directory, then from its own source path, for `sb-os.json` (`--vault` / `SB_TASK_VAULT` override).

## JSON policy

`--json` is a CLI envelope (never a pass-through of file bytes):

- Success: `{"ok": true, …}` — task objects carry `number, title, status(open|wip|done), moscow, due, done_date, difficulty, batch, wip, subtasks{done,total}, depends[], line`.
- Error: `{"ok": false, "error": {"code", "message", "hint"}}`.
- Exit codes: `0` success · `1` refusal/validation (teaching error text) · `2` reference not found/ambiguous (with closest-match suggestions) · `3` environment/IO (no vault, bad encoding, file changed on disk).

## Design invariants

- **Line-precise writes.** Per-line `\r` and the file's BOM are preserved; untouched lines are never reformatted. Writes are atomic (temp file + replace) and refuse if the file's mtime changed between read and write.
- **Completion gate.** `edit --status done` imports `validate_completion_line` from `para/workflows/sb-archivist/sweep_done_tasks.py` and refuses a non-conforming line — CLI completions can never produce an unsweepable done-task.
- **Structure guarantees.** Task numbers unique per file; `_Depends:_` refs must exist and the same-file graph must stay acyclic; MoSCoW moves relocate the whole block under the target `####` heading; sub-bullet fields insert in canonical order.
- **Selftest.** `sb-task selftest` runs the embedded suite in a temp vault; extend it in the same change as any mechanic.
