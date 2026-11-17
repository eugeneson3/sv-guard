"""Vim status line drawn under each editor: mode badge, message or command line, the
finding under the cursor, pending keys and the file's error/warning counts on the right."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette
from PySide6.QtWidgets import QWidget

from vimcore import CmdlineView, Message, Mode

_MODE_COLORS = {
    Mode.NORMAL: "#3b6fd8",
    Mode.INSERT: "#2e9d57",
    Mode.VISUAL: "#c7741b",
    Mode.VISUAL_LINE: "#c7741b",
    Mode.COMMAND: "#8a4fd0",
}
_ERROR_COLOR = "#d03b3b"
_WARNING_COLOR = "#c98a0c"
_STALE_COLOR = "#9a9a9a"


class StatusLine(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.mode = Mode.NORMAL
        self.pending = ""
        self.message: Message | None = None
        self.cmdline: CmdlineView | None = None
        self.preedit = ""  # IME composition while typing on the command line
        self.hint = ""  # the finding under the cursor, shown when there is no message
        self.counts = (0, 0)  # errors, warnings in this file
        self.stale = False

    def set_state(
        self,
        *,
        mode: Mode,
        pending: str,
        message: Message | None,
        cmdline: CmdlineView | None,
        preedit: str = "",
        hint: str = "",
        counts: tuple[int, int] = (0, 0),
        stale: bool = False,
    ) -> None:
        self.mode, self.pending, self.message, self.cmdline, self.preedit = mode, pending, message, cmdline, preedit
        self.hint, self.counts, self.stale = hint, counts, stale
        self.update()

    def counts_text(self) -> str:
        errors, warnings = self.counts
        if not errors and not warnings:
            return ""
        return f"E{errors} W{warnings}" + ("~" if self.stale else "")

    def text(self) -> str:
        """Plain-text rendering, for tests and accessibility."""
        if self.cmdline is not None:
            return self.cmdline.prefix + self.cmdline.text + self.preedit
        parts = [self.mode.label]
        if self.message is not None:
            parts.append(self.message.text)
        elif self.hint:
            parts.append(self.hint)
        parts += [p for p in (self.pending, self.counts_text()) if p]
        return "  ".join(parts)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self.fontMetrics().height() + 6)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.color(QPalette.ColorRole.Window))
        metrics = self.fontMetrics()
        height = self.height()
        x = 6

        if self.cmdline is not None:
            painter.setPen(palette.color(QPalette.ColorRole.Text))
            prefix_and_text = self.cmdline.prefix + self.cmdline.text
            painter.drawText(QRect(x, 0, self.width() - x, height), Qt.AlignmentFlag.AlignVCenter, prefix_and_text + self.preedit)
            cursor_x = x + metrics.horizontalAdvance(self.cmdline.prefix + self.cmdline.text[: self.cmdline.cursor])
            painter.fillRect(QRect(cursor_x, 3, 2, height - 6), palette.color(QPalette.ColorRole.Text))
            painter.end()
            return

        bold = QFont(self.font())
        bold.setBold(True)
        painter.setFont(bold)
        label = f" {self.mode.label} "
        width = painter.fontMetrics().horizontalAdvance(label) + 4
        painter.fillRect(QRect(0, 0, width, height), QColor(_MODE_COLORS[self.mode]))
        painter.setPen(QColor("white"))
        painter.drawText(QRect(0, 0, width, height), Qt.AlignmentFlag.AlignCenter, label)
        painter.setFont(self.font())
        x = width + 8

        right = self.width() - 8
        if counts := self.counts_text():
            errors, _warnings = self.counts
            color = _STALE_COLOR if self.stale else (_ERROR_COLOR if errors else _WARNING_COLOR)
            painter.setPen(QColor(color))
            painter.drawText(QRect(0, 0, right, height), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, counts)
            right -= metrics.horizontalAdvance(counts) + 16
        if self.pending:
            painter.setPen(palette.color(QPalette.ColorRole.Text))
            painter.drawText(QRect(0, 0, right, height), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self.pending)
            right -= metrics.horizontalAdvance(self.pending) + 16
        text, color = None, None
        if self.message is not None:
            text = self.message.text
            color = QColor(_ERROR_COLOR) if self.message.error else palette.color(QPalette.ColorRole.Text)
        elif self.hint:
            text, color = self.hint, palette.color(QPalette.ColorRole.PlaceholderText)
        if text:
            painter.setPen(color)
            elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, max(0, right - x))
            painter.drawText(QRect(x, 0, right - x, height), Qt.AlignmentFlag.AlignVCenter, elided)
        painter.end()
