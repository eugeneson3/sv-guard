"""Findings drawn into one editor: squiggles, gutter marks, the message under the cursor.

Each finding is anchored with a QTextCursor selection, so Qt moves it along as the user
edits above it. Any edit after a check marks all of them stale: they are drawn grey and
dotted until the next save brings fresh results (checks never run while typing).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit

from app.editor.qt_buffer import QtDocumentBuffer
from svguard.model import Finding, Severity
from vimcore import Pos

if TYPE_CHECKING:
    from app.editor.code_editor import CodeEditor

SEVERITY_COLORS = {
    Severity.ERROR: "#e5484d",
    Severity.WARNING: "#d9900f",
    Severity.INFO: "#3b82f6",
    Severity.HINT: "#8b8b8b",
}
STALE_COLOR = "#9a9a9a"
_WORD_CHARS = "_$"


@dataclass
class Mark:
    finding: Finding
    cursor: QTextCursor  # selection anchored in the document

    @property
    def start(self) -> int:
        return self.cursor.selectionStart()

    @property
    def end(self) -> int:
        return self.cursor.selectionEnd()


class EditorDiagnostics(QObject):
    changed = Signal()

    def __init__(self, editor: CodeEditor) -> None:
        super().__init__(editor)
        self._editor = editor
        self._marks: list[Mark] = []
        self.stale = False
        editor.document().contentsChange.connect(self._on_contents_change)

    # -- state -----------------------------------------------------------------------

    @property
    def marks(self) -> list[Mark]:
        return sorted(self._marks, key=lambda m: (m.start, m.finding.severity.rank))

    def set(self, findings: list[Finding], *, stale: bool = False) -> None:
        buffer = QtDocumentBuffer(self._editor.document())
        self._marks = [Mark(f, self._anchor(buffer, f)) for f in findings]
        self.stale = stale
        self.changed.emit()

    def clear(self) -> None:
        if self._marks or self.stale:
            self._marks = []
            self.stale = False
            self.changed.emit()

    def counts(self) -> Counter[Severity]:
        return Counter(m.finding.severity for m in self._marks)

    def at(self, position: int) -> Finding | None:
        """The most severe finding covering `position`, else the first one on its line."""
        covering = [m for m in self._marks if m.start <= position <= max(m.end, m.start)]
        if covering:
            return min(covering, key=lambda m: m.finding.severity.rank).finding
        block = self._editor.document().findBlock(position).blockNumber()
        on_line = [m for m in self._marks if m.cursor.document().findBlock(m.start).blockNumber() == block]
        return min(on_line, key=lambda m: (m.finding.severity.rank, m.start)).finding if on_line else None

    def position_of(self, finding: Finding) -> int | None:
        """Where `finding` is now (after edits), if it belongs to this editor."""
        return next((m.start for m in self._marks if m.finding == finding), None)

    def line_severities(self) -> dict[int, Severity]:
        """Most severe finding per block number, for the gutter."""
        result: dict[int, Severity] = {}
        doc = self._editor.document()
        for mark in self._marks:
            block = doc.findBlock(mark.start).blockNumber()
            if block not in result or mark.finding.severity.rank < result[block].rank:
                result[block] = mark.finding.severity
        return result

    # -- drawing ---------------------------------------------------------------------

    def selections(self) -> list[QTextEdit.ExtraSelection]:
        selections = []
        for mark in self._marks:
            fmt = QTextCharFormat()
            if self.stale:
                fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.DotLine)
                fmt.setUnderlineColor(QColor(STALE_COLOR))
            else:
                color = QColor(SEVERITY_COLORS[mark.finding.severity])
                fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
                fmt.setUnderlineColor(color)
                color.setAlpha(45)  # a light tint too: a squiggle under one letter is easy to miss
                fmt.setBackground(color)
            selection = QTextEdit.ExtraSelection()
            selection.cursor = mark.cursor
            selection.format = fmt
            selections.append(selection)
        return selections

    # -- internals -------------------------------------------------------------------

    def _on_contents_change(self, _position: int, removed: int, added: int) -> None:
        if self._marks and (removed or added) and not self.stale:
            self.stale = True
            self.changed.emit()

    def _anchor(self, buffer: QtDocumentBuffer, finding: Finding) -> QTextCursor:
        doc = self._editor.document()
        loc = finding.location
        last = doc.blockCount() - 1
        row = min(max(loc.line - 1, 0), last)
        line = doc.findBlockByNumber(row).text()
        start = min(max(loc.col - 1, 0), len(line))
        end_row = min(max(loc.end_line - 1, row), last)
        end = loc.end_col - 1
        if (end_row, end) <= (row, start):
            # slang gave only a point: underline the word there (or at least one character)
            end_row, end = row, start
            while end < len(line) and (line[end].isalnum() or line[end] in _WORD_CHARS):
                end += 1
            if end == start:
                if start < len(line):
                    end = start + 1
                elif start > 0:
                    start -= 1
        end = min(end, len(doc.findBlockByNumber(end_row).text()))
        cursor = QTextCursor(doc)
        cursor.setPosition(buffer.position(Pos(row, start)))
        cursor.setPosition(buffer.position(Pos(end_row, end)), QTextCursor.MoveMode.KeepAnchor)
        return cursor
