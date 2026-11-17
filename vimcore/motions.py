"""Motion primitives. Word motions are ports of vim's fwd_word / bck_word / end_word
(search.c / textobject.c) so edge cases match vim: empty lines count as words, `dw` on
the last word of a line stops at the line end, `w` on the last word of the file fails.
"""

from __future__ import annotations

from dataclasses import dataclass

from vimcore.buffer import Pos, TextBuffer

MAXCOL = 1 << 30  # curswant after `$`: stick to the end of every line


@dataclass(frozen=True)
class Motion:
    target: Pos
    linewise: bool = False
    inclusive: bool = False
    keep_column: bool = False  # j/k: the column comes from curswant
    curswant: int | None = None  # MAXCOL after `$`


class _Walker:
    """A cursor that, like vim's, may sit on the end-of-line position (col == len)."""

    def __init__(self, buffer: TextBuffer, pos: Pos) -> None:
        self.buffer = buffer
        self.row, self.col = pos

    @property
    def pos(self) -> Pos:
        return Pos(self.row, self.col)

    def char(self) -> str:
        line = self.buffer.line(self.row)
        return line[self.col] if self.col < len(line) else ""

    def at_empty_line(self) -> bool:
        return self.col == 0 and self.buffer.line(self.row) == ""

    def inc(self) -> int:
        """0: moved within the line, 2: moved onto the line end, 1: moved to the next line, -1: end of file."""
        line = self.buffer.line(self.row)
        if self.col < len(line):
            self.col += 1
            return 0 if self.col < len(line) else 2
        if self.row + 1 < self.buffer.line_count():
            self.row += 1
            self.col = 0
            return 1
        return -1

    def dec(self) -> int:
        """0: moved within the line, 1: moved to the previous line's end, -1: start of file."""
        if self.col > 0:
            self.col -= 1
            return 0
        if self.row > 0:
            self.row -= 1
            self.col = len(self.buffer.line(self.row))
            return 1
        return -1


def char_class(ch: str, bigword: bool = False) -> int:
    """0 blank/end of line, 1 punctuation, 2 keyword, 3 Hangul (a separate word class, as in vim)."""
    if ch in ("", " ", "\t"):
        return 0
    if bigword:
        return 1
    if "가" <= ch <= "힣" or "ㄱ" <= ch <= "ㆎ":
        return 3
    if ch.isalnum() or ch == "_":
        return 2
    return 1


def _skip_class(w: _Walker, cls: int, bigword: bool, forward: bool) -> bool:
    """Move while the class stays `cls`. True if the file edge was hit."""
    while char_class(w.char(), bigword) == cls:
        if (w.inc() if forward else w.dec()) == -1:
            return True
    return False


def forward_word(buffer: TextBuffer, pos: Pos, count: int, bigword: bool, *, stop_at_eol: bool) -> tuple[Pos, bool]:
    """`w`/`W`. stop_at_eol: with an operator the last word stops at the line end (dw, yw)."""
    w = _Walker(buffer, pos)
    last_row = buffer.line_count() - 1
    for i in range(count):
        last = i == count - 1
        cls = char_class(w.char(), bigword)
        on_last_line = w.row == last_row
        moved = w.inc()
        if moved == -1 or (moved >= 1 and on_last_line):
            return w.pos, False  # started at the last character of the file
        if moved >= 1 and stop_at_eol and last:
            return w.pos, True
        if cls != 0:
            while char_class(w.char(), bigword) == cls:
                moved = w.inc()
                if moved == -1 or (moved >= 1 and stop_at_eol and last):
                    return w.pos, True
        while char_class(w.char(), bigword) == 0:
            if w.at_empty_line():
                break
            moved = w.inc()
            if moved == -1 or (moved >= 1 and stop_at_eol and last):
                return w.pos, True
    return w.pos, True


def backward_word(buffer: TextBuffer, pos: Pos, count: int, bigword: bool) -> tuple[Pos, bool]:
    """`b`/`B`."""
    w = _Walker(buffer, pos)
    for _ in range(count):
        if w.dec() == -1:
            return w.pos, False
        finished = False
        while char_class(w.char(), bigword) == 0:  # skip blanks before the word, stop on an empty line
            if w.at_empty_line():
                finished = True
                break
            if w.dec() == -1:
                return w.pos, True
        if finished:
            continue
        if _skip_class(w, char_class(w.char(), bigword), bigword, forward=False):
            return w.pos, True
        w.inc()  # overshot by one
    return w.pos, True


def end_word(buffer: TextBuffer, pos: Pos, count: int, bigword: bool, *, stop: bool = False) -> tuple[Pos, bool]:
    """`e`/`E`. stop=True keeps the cursor if it already is at the end of a word (cw = ce)."""
    w = _Walker(buffer, pos)
    for _ in range(count):
        cls = char_class(w.char(), bigword)
        if w.inc() == -1:
            return pos, False
        if char_class(w.char(), bigword) == cls and cls != 0:
            if _skip_class(w, cls, bigword, forward=True):
                return pos, False
        elif not stop or cls == 0:
            while char_class(w.char(), bigword) == 0:
                if w.inc() == -1:
                    return pos, False
            if _skip_class(w, char_class(w.char(), bigword), bigword, forward=True):
                return pos, False
        w.dec()  # overshot by one
        stop = False
    return w.pos, True


def find_char(line: str, col: int, char: str, count: int, *, forward: bool, till: bool, repeat: bool = False) -> int | None:
    """f/F/t/T within one line. `repeat` (; ,) skips an adjacent match for t/T so it doesn't stick."""
    c = col
    for i in range(count):
        if forward:
            start = c + 1
            if till and repeat and i == 0 and start < len(line) and line[start] == char:
                start += 1
            c = line.find(char, start)
        else:
            end = c
            if till and repeat and i == 0 and c - 1 >= 0 and line[c - 1] == char:
                end = c - 1
            c = line.rfind(char, 0, max(0, end))
        if c < 0:
            return None
    if till:
        c = c - 1 if forward else c + 1
    return c


_OPEN = {"(": ")", "[": "]", "{": "}"}
_CLOSE = {v: k for k, v in _OPEN.items()}


def match_pair(buffer: TextBuffer, pos: Pos) -> Pos | None:
    """`%`: jump from the first bracket at or after the cursor to its partner."""
    line = buffer.line(pos.row)
    col = next((c for c in range(pos.col, len(line)) if line[c] in "()[]{}"), None)
    if col is None:
        return None
    ch = line[col]
    forward = ch in _OPEN
    partner = _OPEN[ch] if forward else _CLOSE[ch]
    depth = 0
    w = _Walker(buffer, Pos(pos.row, col))
    while True:
        here = w.char()
        if here == ch:
            depth += 1
        elif here == partner:
            depth -= 1
            if depth == 0:
                return w.pos
        if (w.inc() if forward else w.dec()) == -1:
            return None
