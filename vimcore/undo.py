"""Linear undo/redo built from replace() records.

Each edit stores the text it removed and the text it inserted, so it can be inverted
exactly. Edits are grouped: one Normal-mode change, or one Insert session (including
the command that started it), is one undo step, as in vim.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vimcore.buffer import Pos, TextBuffer, first_nonblank, pos_after


@dataclass(frozen=True)
class Edit:
    start: Pos
    old: str
    new: str


@dataclass
class UndoGroup:
    cursor_before: Pos
    edits: list[Edit] = field(default_factory=list)


class UndoHistory:
    def __init__(self) -> None:
        self._undo: list[UndoGroup] = []
        self._redo: list[UndoGroup] = []
        self._open: UndoGroup | None = None
        self._depth = 0

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def state(self) -> UndoGroup | None:
        """Identity of the current point in history; compare with `is` to detect
        "back at the saved state" after undo/redo."""
        return self._undo[-1] if self._undo else None

    def begin(self, cursor: Pos) -> None:
        """Nested begin()/end() pairs collapse into the outermost group."""
        self._depth += 1
        if self._depth == 1:
            self._open = UndoGroup(cursor)

    def end(self) -> None:
        if self._depth == 0:
            return
        self._depth -= 1
        if self._depth == 0 and self._open is not None:
            if self._open.edits:
                self._undo.append(self._open)
                self._redo.clear()
            self._open = None

    def record(self, edit: Edit) -> None:
        if self._open is None:  # an edit outside any group is a step of its own
            self._undo.append(UndoGroup(edit.start, [edit]))
            self._redo.clear()
        else:
            self._open.edits.append(edit)

    def undo(self, buffer: TextBuffer) -> Pos | None:
        if not self._undo:
            return None
        group = self._undo.pop()
        for edit in reversed(group.edits):
            buffer.replace(edit.start, pos_after(edit.start, edit.new), edit.old)
        self._redo.append(group)
        return _cursor_after(buffer, group)

    def redo(self, buffer: TextBuffer) -> Pos | None:
        if not self._redo:
            return None
        group = self._redo.pop()
        for edit in group.edits:
            buffer.replace(edit.start, pos_after(edit.start, edit.old), edit.new)
        self._undo.append(group)
        return _cursor_after(buffer, group)

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()


def _cursor_after(buffer: TextBuffer, group: UndoGroup) -> Pos:
    """Vim's rule: go to the top changed line; keep the old column if the change started
    on the line the cursor was on, otherwise the first non-blank."""
    top = min(edit.start for edit in group.edits)
    row = min(top.row, buffer.line_count() - 1)
    if row == group.cursor_before.row:
        return Pos(row, group.cursor_before.col)
    return Pos(row, first_nonblank(buffer.line(row)))
