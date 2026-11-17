"""Text buffer abstraction used by the vim engine.

The engine never touches Qt. It edits through `TextBuffer.replace()`, the single
mutation primitive, which keeps undo recording trivial (old text + new text).
MemoryBuffer backs the unit tests; app/editor/vim_adapter.QtDocumentBuffer backs the IDE.
"""

from __future__ import annotations

from typing import NamedTuple, Protocol


class Pos(NamedTuple):
    """0-based row and column; the column counts Python characters (code points)."""

    row: int
    col: int


class TextBuffer(Protocol):
    def line_count(self) -> int: ...

    def line(self, row: int) -> str:
        """Line text without the newline."""
        ...

    def replace(self, start: Pos, end: Pos, text: str) -> None:
        """Replace [start, end) with `text`; both may span lines, `text` may contain newlines."""
        ...

    @property
    def version(self) -> int:
        """Incremented on every replace()."""
        ...


class MemoryBuffer:
    def __init__(self, text: str = "") -> None:
        self._lines = text.split("\n")
        self._version = 0

    @property
    def text(self) -> str:
        return "\n".join(self._lines)

    @property
    def version(self) -> int:
        return self._version

    def line_count(self) -> int:
        return len(self._lines)

    def line(self, row: int) -> str:
        return self._lines[row]

    def replace(self, start: Pos, end: Pos, text: str) -> None:
        prefix = self._lines[start.row][: start.col]
        suffix = self._lines[end.row][end.col :]
        self._lines[start.row : end.row + 1] = (prefix + text + suffix).split("\n")
        self._version += 1


def get_text(buffer: TextBuffer, start: Pos, end: Pos) -> str:
    if start.row == end.row:
        return buffer.line(start.row)[start.col : end.col]
    parts = [buffer.line(start.row)[start.col :]]
    parts.extend(buffer.line(row) for row in range(start.row + 1, end.row))
    parts.append(buffer.line(end.row)[: end.col])
    return "\n".join(parts)


def pos_after(start: Pos, text: str) -> Pos:
    """Position just after `text` once it is inserted at `start`."""
    newlines = text.count("\n")
    if not newlines:
        return Pos(start.row, start.col + len(text))
    return Pos(start.row + newlines, len(text) - text.rfind("\n") - 1)


def last_row(buffer: TextBuffer) -> int:
    return buffer.line_count() - 1


def first_nonblank(line: str) -> int:
    """Column of the first non-blank; len(line) for blank lines (Normal mode clamps it)."""
    return len(line) - len(line.lstrip(" \t"))


def leading_whitespace(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]
