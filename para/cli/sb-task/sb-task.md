# sb-task — task-file operations

Deterministic executor for every operation on `*-tasks.md` files. NEVER hand-edit a task's main line or structured sub-bullets when this CLI is available — it enforces the task contract (`{sb_os_path}/para/workflows/sb-vault-ops/data/tasks.md`) mechanically.

## Order of use

1. **Verify + orient:** `sb-task doctor` (fallback if not on PATH: `python {sb_os_path}/para/cli/sb-task/sb_task.py doctor`; resolve `{sb_os_path}` from `sb-os.json`). A failing probe means: apply the task contract by hand instead.
2. **Find the file:** `sb-task files` — every task file with tag + open/done counts. Any `<file>` argument accepts a vault-relative path OR a unique name substring (`tecer` → `2-areas/tecer/tecer-tasks.md`). WHICH file a new task belongs in is a routing decision — `sb-vault-ops` owns it, not this CLI.
3. **Read before write:** `sb-task list <file>` (digest; filters: `--status --moscow --due --batch --difficulty`), then `sb-task read <file> <ref>` for one task's full block. `<ref>` = task number (`4.1b`), exact title, or unique title substring.
4. **Write:** one named command per action — `create`, `edit`, `delete`. Add `--dry-run` to preview any write. Use `--json` whenever output will be parsed.

## Rules

- Starting work on a task → `sb-task edit <file> <ref> --status wip`; ending → `--status done` (validates the sweep contract + stamps ✅ today) or back via `--status open`.
- `create` refuses without `--context` + `--criteria` (cold-start sufficiency). Override with `--force` only when the owner explicitly waives it.
- `delete` requires `--yes`, refuses while other tasks depend on the target (`--force` overrides), and prints the removed block — surface that block in your reply (never lose information).
- Dependencies: `--add-depends`/`--remove-depends` reference task NUMBERS; the CLI refuses unknown refs and dependency cycles. Do not start a task whose depends are not all done.
- Free text with quotes/backticks/newlines: pass `@<path>` or `@-` (stdin) to any text flag.
- There is no raw escape hatch: an operation the CLI lacks (e.g. a `_Review:_` entry) is a hand edit under the task contract — keep it line-precise.

## Examples

```
sb-task list tecer --status open --moscow must
sb-task create sb-os --title "Wire the ignite VPS wrapper" --number 12 --due 2026-08-01 --context "..." --criteria "..."
sb-task edit tecer 4.1b --status done
```

Full inventory and per-command examples: `sb-task -h` and `sb-task <command> -h`.
