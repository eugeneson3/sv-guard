"""Operators (d c y > <) and put, applied to a TextRange.

Ranges are charwise with an exclusive end, or linewise covering start.row..end.row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vimcore.buffer import Pos, TextBuffer, first_nonblank, get_text, leading_whitespace
from vimcore.motions import Motion
from vimcore.registers import RegisterValue

if TYPE_CHECKING:
    from vimcore.engine import VimEngine

REPORT_THRESHOLD = 2  # vim's 'report': mention line counts above this


@dataclass(frozen=True)
class TextRange:
    start: Pos
    end: Pos  # charwise: exclusive end; linewise: last row (column ignored)
    linewise: bool

    @property
    def rows(self) -> range:
        return range(self.start.row, self.end.row + 1)


def motion_range(buffer: TextBuffer, cursor: Pos, motion: Motion) -> TextRange:
    a, b = sorted((cursor, motion.target))
    if motion.linewise:
        return TextRange(Pos(a.row, 0), Pos(b.row, 0), True)
    if motion.inclusive:
        b = Pos(b.row, min(b.col + 1, len(buffer.line(b.row))))
    elif b.col == 0 and b.row > a.row:
        # :help exclusive -- an exclusive motion ending in column 0 stops at the end of the
        # previous line, and becomes linewise if it started at or before the first non-blank.
        prev = b.row - 1
        if a.col <= first_nonblank(buffer.line(a.row)):
            return TextRange(Pos(a.row, 0), Pos(prev, 0), True)
        b = Pos(prev, len(buffer.line(prev)))
    return TextRange(a, b, False)


def range_text(buffer: TextBuffer, rng: TextRange) -> RegisterValue:
    if rng.linewise:
        return RegisterValue("\n".join(buffer.line(r) for r in rng.rows), linewise=True)
    return RegisterValue(get_text(buffer, rng.start, rng.end))


def yank(eng: VimEngine, rng: TextRange, register: str | None) -> None:
    eng.registers.put(register, range_text(eng.buffer, rng), yank=True)
    if rng.linewise:
        if eng.cursor.row != rng.start.row:
            eng.move_cursor(Pos(rng.start.row, eng.cursor.col))
        _report(eng, len(rng.rows), "yanked")
    else:
        eng.move_cursor(rng.start)


def delete(eng: VimEngine, rng: TextRange, register: str | None) -> None:
    buf = eng.buffer
    value = range_text(buf, rng)
    if not rng.linewise and not value.text:
        return
    eng.registers.put(register, value, yank=False)
    if not rng.linewise:
        eng.edit(rng.start, rng.end, "")
        eng.move_cursor(rng.start)
        return
    first, last = rng.start.row, rng.end.row
    final = buf.line_count() - 1
    if last < final:
        eng.edit(Pos(first, 0), Pos(last + 1, 0), "")
    elif first > 0:
        eng.edit(Pos(first - 1, len(buf.line(first - 1))), Pos(last, len(buf.line(last))), "")
    else:
        eng.edit(Pos(0, 0), Pos(last, len(buf.line(last))), "")
    row = min(first, buf.line_count() - 1)
    eng.move_cursor(Pos(row, first_nonblank(buf.line(row))))
    _report(eng, last - first + 1, "fewer lines", plain=True)


def change(eng: VimEngine, rng: TextRange, register: str | None) -> None:
    buf = eng.buffer
    if rng.linewise:
        eng.registers.put(register, range_text(buf, rng), yank=False)
        first, last = rng.start.row, rng.end.row
        indent = leading_whitespace(buf.line(first)) if eng.options.autoindent else ""
        eng.edit(Pos(first, 0), Pos(last, len(buf.line(last))), indent)
        eng.move_cursor(Pos(first, len(indent)), clamp=False)
    else:
        value = range_text(buf, rng)
        if value.text:
            eng.registers.put(register, value, yank=False)
            eng.edit(rng.start, rng.end, "")
        eng.move_cursor(rng.start, clamp=False)
    eng.start_insert("c")


def shift(eng: VimEngine, rng: TextRange, direction: int, times: int = 1) -> None:
    buf, opts = eng.buffer, eng.options
    rows = rng.rows
    for row in rows:
        line = buf.line(row)
        if not line.strip():
            continue  # never create indentation on blank lines
        indent = leading_whitespace(line)
        width = max(0, indent_width(indent, opts.tabstop) + direction * opts.sw * times)
        eng.edit(Pos(row, 0), Pos(row, len(indent)), make_indent(width, opts.expandtab, opts.tabstop))
    first = rows[0]
    eng.move_cursor(Pos(first, first_nonblank(buf.line(first))))
    if len(rows) > REPORT_THRESHOLD:
        eng.set_message(f"{len(rows)} lines {'>' if direction > 0 else '<'}ed {times} time{'s' if times > 1 else ''}")


def put(eng: VimEngine, value: RegisterValue, count: int, *, after: bool) -> None:
    buf = eng.buffer
    row = eng.cursor.row
    if value.linewise:
        block = "\n".join([value.text] * count)
        if after:
            eng.edit(Pos(row, len(buf.line(row))), Pos(row, len(buf.line(row))), "\n" + block)
            first = row + 1
        else:
            eng.edit(Pos(row, 0), Pos(row, 0), block + "\n")
            first = row
        eng.move_cursor(Pos(first, first_nonblank(buf.line(first))))
        _report(eng, (value.text.count("\n") + 1) * count, "more lines", plain=True)
        return
    text = value.text * count
    line = buf.line(row)
    col = min(eng.cursor.col + 1 if after and line else eng.cursor.col, len(line))
    eng.edit(Pos(row, col), Pos(row, col), text)
    if "\n" in text:
        eng.move_cursor(Pos(row, col))  # vim: multi-line text leaves the cursor at its start
    else:
        eng.move_cursor(Pos(row, col + len(text) - 1))


def indent_width(indent: str, tabstop: int) -> int:
    width = 0
    for ch in indent:
        width = width + tabstop - width % tabstop if ch == "\t" else width + 1
    return width


def make_indent(width: int, expandtab: bool, tabstop: int) -> str:
    if expandtab:
        return " " * width
    return "\t" * (width // tabstop) + " " * (width % tabstop)


def _report(eng: VimEngine, lines: int, what: str, *, plain: bool = False) -> None:
    if lines > REPORT_THRESHOLD:
        eng.set_message(f"{lines} {what}" if plain else f"{lines} lines {what}")
