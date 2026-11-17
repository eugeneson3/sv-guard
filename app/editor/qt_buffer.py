"""vimcore.TextBuffer over a QTextDocument, plus the position conversions between them.

Qt positions count UTF-16 units; vimcore and svguard count Python characters. They only
differ for characters outside the BMP (an emoji in a comment), so the conversion is a
no-op for almost every line.
"""

from __future__ import annotations

import re

from PySide6.QtGui import QTextCursor, QTextDocument

from vimcore import Pos

_ASTRAL = re.compile("[\U00010000-\U0010ffff]")  # 2 UTF-16 units in Qt, 1 character in Python


def utf16_length(text: str) -> int:
    return len(text) + len(_ASTRAL.findall(text))


def chars_for_utf16(text: str, units: int) -> int:
    if not _ASTRAL.search(text):
        return units
    count = used = 0
    for ch in text:
        if used >= units:
            break
        used += 2 if ord(ch) > 0xFFFF else 1
        count += 1
    return count


class QtDocumentBuffer:
    def __init__(self, document: QTextDocument) -> None:
        self._doc = document
        self._version = 0

    @property
    def version(self) -> int:
        return self._version

    def line_count(self) -> int:
        return self._doc.blockCount()

    def line(self, row: int) -> str:
        return self._doc.findBlockByNumber(row).text()

    def replace(self, start: Pos, end: Pos, text: str) -> None:
        cursor = QTextCursor(self._doc)
        cursor.setPosition(self.position(start))
        cursor.setPosition(self.position(end), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        self._version += 1

    def position(self, pos: Pos) -> int:
        """Qt document position (UTF-16 units) of a vimcore position."""
        block = self._doc.findBlockByNumber(pos.row)
        return block.position() + utf16_length(block.text()[: pos.col])

    def pos_from(self, position: int) -> Pos:
        block = self._doc.findBlock(position)
        return Pos(block.blockNumber(), chars_for_utf16(block.text(), position - block.position()))
