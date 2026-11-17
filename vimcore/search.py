"""Plain-string search for / ? n N (regex support is not part of V1)."""

from __future__ import annotations

from vimcore.buffer import Pos, TextBuffer


def search(
    buffer: TextBuffer,
    pattern: str,
    start: Pos,
    *,
    forward: bool,
    wrapscan: bool = True,
    ignorecase: bool = False,
) -> tuple[Pos, bool] | None:
    """Next match strictly after (or before) `start`. Returns (position, wrapped)."""
    if not pattern:
        return None
    needle = pattern.lower() if ignorecase else pattern
    count = buffer.line_count()

    def text(row: int) -> str:
        line = buffer.line(row)
        return line.lower() if ignorecase else line

    if forward:
        idx = text(start.row).find(needle, start.col + 1)
        if idx >= 0:
            return Pos(start.row, idx), False
        for step in range(1, count + 1):
            wrapped = start.row + step >= count
            if wrapped and not wrapscan:
                return None
            row = (start.row + step) % count
            idx = text(row).find(needle)
            if idx >= 0 and (row != start.row or idx <= start.col):
                return Pos(row, idx), wrapped
        return None

    idx = text(start.row).rfind(needle, 0, max(0, start.col - 1 + len(needle)))
    if idx >= 0:
        return Pos(start.row, idx), False
    for step in range(1, count + 1):
        wrapped = start.row - step < 0
        if wrapped and not wrapscan:
            return None
        row = (start.row - step) % count
        idx = text(row).rfind(needle)
        if idx >= 0 and (row != start.row or idx >= start.col):
            return Pos(row, idx), wrapped
    return None
