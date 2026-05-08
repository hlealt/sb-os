"""Zero-dependency terminal UI for interactive installer selection.

Works on Windows (msvcrt), macOS, and Linux. Uses ANSI escape codes for
rendering and degrades to plain terminal output when ANSI support is limited.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Any, Callable


KEY_UP = "UP"
KEY_DOWN = "DOWN"
KEY_SPACE = "SPACE"
KEY_ENTER = "ENTER"
KEY_ESCAPE = "ESC"
KEY_UNKNOWN = "UNKNOWN"

HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR_TO_END = "\033[J"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
RESET = "\033[0m"

_ANSI_RE = re.compile(r"\033\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _term_cols() -> int:
    try:
        return os.get_terminal_size().columns
    except (AttributeError, ValueError, OSError):
        return 80


def _visual_line_count(text: str, cols: int) -> int:
    total = 0
    for line in text.split("\n"):
        width = len(_strip_ansi(line))
        if width == 0:
            total += 1
        else:
            total += (width + cols - 1) // cols
    return total


def _enable_ansi_windows() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


_ansi_initialized = False


def _ensure_ansi() -> None:
    global _ansi_initialized
    if not _ansi_initialized:
        _enable_ansi_windows()
        _ansi_initialized = True


def _read_key() -> str:
    if os.name == "nt":
        import msvcrt

        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            return {"H": KEY_UP, "P": KEY_DOWN}.get(ch2, KEY_UNKNOWN)
        if ch == "\r":
            return KEY_ENTER
        if ch == " ":
            return KEY_SPACE
        if ch == "\x1b":
            return KEY_ESCAPE
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch

    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                ch3 = sys.stdin.read(1)
                return {"A": KEY_UP, "B": KEY_DOWN}.get(ch3, KEY_UNKNOWN)
            return KEY_ESCAPE
        if ch in ("\r", "\n"):
            return KEY_ENTER
        if ch == " ":
            return KEY_SPACE
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def checkbox(
    title: str,
    items: list[dict[str, Any]],
    *,
    min_selected: int = 0,
    detail_callback: Callable[[int], str] | None = None,
) -> list[int]:
    """Render a keyboard-navigable checkbox list and return selected indices."""
    if not items:
        return []

    _ensure_ansi()
    cursor = 0
    selected = [item.get("selected", False) for item in items]
    disabled = [item.get("disabled", False) for item in items]
    prev_visual_rows = 0

    def write(text: str) -> None:
        sys.stdout.write(text)

    def build_output() -> str:
        keys = "up/down move | space toggle | enter confirm"
        if detail_callback:
            keys += " | i info"
        keys += " | a all"

        lines = [f"{BOLD}{title}{RESET}", f"{DIM}  {keys}{RESET}"]
        for i, item in enumerate(items):
            prefix = f"{CYAN}>{RESET} " if i == cursor else "  "
            if disabled[i]:
                box = f"{DIM}[x]{RESET}"
                label = f"{DIM}{item['label']} (always installed){RESET}"
            elif selected[i]:
                box = f"{GREEN}[x]{RESET}"
                label = item["label"]
            else:
                box = "[ ]"
                label = item["label"]
            hint = f"  {DIM}{item['hint']}{RESET}" if item.get("hint") else ""
            lines.append(f"{prefix}{box} {label}{hint}")
        return "\n".join(lines)

    def render(first_draw: bool = False) -> None:
        nonlocal prev_visual_rows
        cols = _term_cols()
        if not first_draw and prev_visual_rows > 0:
            write(f"\033[{prev_visual_rows - 1}A\r")
        write(CLEAR_TO_END)
        output = build_output()
        write(output)
        sys.stdout.flush()
        prev_visual_rows = _visual_line_count(output, cols)

    def show_detail() -> None:
        nonlocal prev_visual_rows
        if not detail_callback:
            return
        cols = _term_cols()
        detail_text = detail_callback(cursor)
        if prev_visual_rows > 0:
            write(f"\033[{prev_visual_rows - 1}A\r")
        write(CLEAR_TO_END)
        write(detail_text)
        write(f"\n{DIM}  Press any key to return...{RESET}")
        sys.stdout.flush()
        prev_visual_rows = _visual_line_count(
            detail_text + "\n  Press any key to return...",
            cols,
        )
        _read_key()
        render()

    write(HIDE_CURSOR)
    try:
        render(first_draw=True)
        while True:
            key = _read_key()
            if key == KEY_UP:
                cursor = (cursor - 1) % len(items)
            elif key == KEY_DOWN:
                cursor = (cursor + 1) % len(items)
            elif key == KEY_SPACE:
                if not disabled[cursor]:
                    selected[cursor] = not selected[cursor]
            elif key in ("i", "?"):
                show_detail()
                continue
            elif key == "a":
                all_selected = all(
                    selected[i] for i in range(len(items)) if not disabled[i]
                )
                for i in range(len(items)):
                    if not disabled[i]:
                        selected[i] = not all_selected
            elif key == KEY_ENTER:
                if sum(1 for item in selected if item) >= min_selected:
                    break
            render()
    except KeyboardInterrupt:
        write(SHOW_CURSOR)
        sys.stdout.flush()
        raise SystemExit(1)
    finally:
        write(f"\n{SHOW_CURSOR}")
        sys.stdout.flush()

    return [i for i, item in enumerate(selected) if item]
