"""Helpers for vimcore tests: `|` in the text marks the cursor.

    run("foo |bar baz", "dw") == "foo |baz"
"""

from __future__ import annotations

from vimcore import MemoryBuffer, Pos, VimEngine, VimOptions
from vimcore.engine import SharedState
from vimcore.registers import Registers

CURSOR = "|"


class FakeClipboard:
    def __init__(self, text: str = "") -> None:
        self.text = text

    def get(self) -> str:
        return self.text

    def set(self, text: str) -> None:
        self.text = text


def make(text: str, *, clipboard: FakeClipboard | None = None, **options) -> VimEngine:
    lines = text.split("\n")
    row = col = 0
    for r, line in enumerate(lines):
        if CURSOR in line:
            row, col = r, line.index(CURSOR)
            lines[r] = line.replace(CURSOR, "", 1)
            break
    shared = SharedState(registers=Registers(clipboard))
    engine = VimEngine(MemoryBuffer("\n".join(lines)), options=VimOptions(**options), shared=shared)
    engine.move_cursor(Pos(row, col))  # also sets the remembered column for j/k
    return engine


def show(engine: VimEngine) -> str:
    lines = engine.buffer.text.split("\n")
    row, col = engine.cursor
    lines[row] = lines[row][:col] + CURSOR + lines[row][col:]
    return "\n".join(lines)


def run(text: str, keys: str, **options) -> str:
    engine = make(text, **options)
    engine.feed_keys(keys)
    return show(engine)
