"""Code editor widget: line numbers, current-line highlight, indentation handling.

Pattern follows Qt's "Code Editor Example". Extension points:
  * key_handler:       called first for every key press; return True to consume it.
  * vim:               the attached VimAdapter (app/editor/vim_adapter.py), which also
                       receives IME commits, pastes and the context menu.
  * set_extra_layer(): named layers of ExtraSelections (current line, Visual selection,
                       diagnostic underlines later) merged into one list.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEvent, QMimeData, QRect, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QHelpEvent,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QInputMethodEvent,
    QKeyEvent,
    QPainter,
    QPalette,
    QSyntaxHighlighter,
    QTextCursor,
    QTextFormat,
    QTextOption,
)
from PySide6.QtWidgets import QMenu, QPlainTextEdit, QTextEdit, QToolTip, QWidget

from app.editor.diagnostics import SEVERITY_COLORS, STALE_COLOR, EditorDiagnostics
from app.editor.statusline import StatusLine
from app.settings import EditorSettings
from svguard.model import Finding

KeyHandler = Callable[[QKeyEvent], bool]

# First installed family wins; D2Coding is popular with Korean developers.
_PREFERRED_FONTS = ("D2Coding", "Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono", "Ubuntu Mono")
_NO_MODIFIERS = Qt.KeyboardModifier.NoModifier | Qt.KeyboardModifier.KeypadModifier


def editor_font(settings: EditorSettings) -> QFont:
    families = set(QFontDatabase.families())
    family = settings.font_family or next((f for f in _PREFERRED_FONTS if f in families), "")
    font = QFont(family) if family else QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(settings.font_size)
    return font


class _LineNumberArea(QWidget):
    def __init__(self, editor: CodeEditor) -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        self._editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, settings: EditorSettings | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key_handler: KeyHandler | None = None
        self.vim: Any = None  # VimAdapter when vim mode is on
        self.highlighter: QSyntaxHighlighter | None = None  # set by EditorTabs for SV files
        self._settings = settings or EditorSettings()
        self._layers: dict[str, list[QTextEdit.ExtraSelection]] = {}
        self._line_numbers = _LineNumberArea(self)
        self.statusline = StatusLine(self)
        self.statusline.hide()
        self.diagnostics = EditorDiagnostics(self)
        self.diagnostics.changed.connect(self._on_diagnostics_changed)

        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.blockCountChanged.connect(self._update_margins)
        self.updateRequest.connect(self._on_update_request)
        self.cursorPositionChanged.connect(self._on_cursor_moved)
        self.apply_settings(self._settings)

    # -- settings ------------------------------------------------------------

    @property
    def settings(self) -> EditorSettings:
        return self._settings

    @property
    def indent_unit(self) -> str:
        return " " * self._settings.tab_width if self._settings.insert_spaces else "\t"

    def apply_settings(self, settings: EditorSettings) -> None:
        self._settings = settings
        font = editor_font(settings)
        self.setFont(font)
        self.statusline.setFont(font)
        self.set_tab_width(settings.tab_width)
        option = self.document().defaultTextOption()
        flags = option.flags()
        if settings.show_whitespace:
            flags |= QTextOption.Flag.ShowTabsAndSpaces
        else:
            flags &= ~QTextOption.Flag.ShowTabsAndSpaces
        option.setFlags(flags)
        self.document().setDefaultTextOption(option)
        self._update_margins()
        self._on_cursor_moved()

    def set_tab_width(self, columns: int) -> None:
        """How wide a tab character is drawn (vim's :set tabstop changes it per editor)."""
        self.setTabStopDistance(QFontMetricsF(self.font()).horizontalAdvance(" ") * columns)

    def set_statusline_visible(self, visible: bool) -> None:
        self.statusline.setVisible(visible)
        self._update_margins()
        self._layout_children()

    def is_dark(self) -> bool:
        return self.palette().color(QPalette.ColorRole.Base).lightness() < 128

    # -- extra selections ----------------------------------------------------

    def set_extra_layer(self, name: str, selections: list[QTextEdit.ExtraSelection]) -> None:
        self._layers[name] = selections
        self.setExtraSelections([s for layer in self._layers.values() for s in layer])

    # -- cursor info ---------------------------------------------------------

    def cursor_line_col(self) -> tuple[int, int]:
        """1-based line and character column of the cursor (same convention as svguard Location)."""
        cursor = self.textCursor()
        return cursor.blockNumber() + 1, cursor.positionInBlock() + 1

    # -- diagnostics ---------------------------------------------------------------

    def set_findings(self, findings: list[Finding], *, stale: bool = False) -> None:
        self.diagnostics.set(findings, stale=stale)

    def finding_at_cursor(self) -> Finding | None:
        return self.diagnostics.at(self.textCursor().position())

    def _on_diagnostics_changed(self) -> None:
        self.set_extra_layer("diagnostics", self.diagnostics.selections())
        self._line_numbers.update()

    def viewportEvent(self, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.ToolTip:
            assert isinstance(event, QHelpEvent)
            finding = self.diagnostics.at(self.cursorForPosition(event.pos()).position())
            if finding is not None:
                stale = " (outdated: save to re-check)" if self.diagnostics.stale else ""
                QToolTip.showText(event.globalPos(), f"{finding.severity.value}: {finding.message} [{finding.rule_id}]{stale}")
            else:
                QToolTip.hideText()
            return True
        return super().viewportEvent(event)

    # -- keys ----------------------------------------------------------------

    def inputMethodQuery(self, query: Qt.InputMethodQuery):  # noqa: N802
        # QPlainTextEdit answers ImEnabled=True whenever it is editable, ignoring
        # WA_InputMethodEnabled, and the platform IME (Windows IMM, ibus, fcitx) asks this
        # query. Report the vim mode instead so a Hangul IME stays off in Normal mode.
        if query == Qt.InputMethodQuery.ImEnabled and self.vim is not None:
            return self.vim.engine.mode.accepts_text
        return super().inputMethodQuery(query)

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:  # noqa: N802
        if self.vim is not None:
            forwarded = self.vim.handle_input_method(event)
            if forwarded is None:
                return
            event = forwarded
        super().inputMethodEvent(event)

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        if self.vim is not None:
            if source.hasText():
                self.vim.handle_paste(source.text())
            return
        super().insertFromMimeData(source)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        if self.vim is None:
            super().contextMenuEvent(event)
            return
        # Qt's default menu (Cut, Delete, Undo...) would edit the text behind vimcore's back.
        menu = QMenu(self)
        copy = menu.addAction('Copy  ("+y)')
        copy.setEnabled(self.vim.engine.selection is not None)
        copy.triggered.connect(self.vim.copy_selection)
        menu.addAction("Paste", self.vim.paste_clipboard)
        menu.exec(event.globalPos())

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self.key_handler is not None and self.key_handler(event):
            return
        key = event.key()
        mods = event.modifiers() & ~_NO_MODIFIERS
        plain = mods == Qt.KeyboardModifier.NoModifier
        if key == Qt.Key.Key_Tab and plain:
            self._tab()
        elif key == Qt.Key.Key_Backtab:
            self._shift_lines(indent=False)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and mods in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier):
            # Shift+Enter would insert a U+2028 soft break inside the line; code files need a real newline.
            self._newline()
        elif key == Qt.Key.Key_Backspace and plain and self._backspace_indent():
            pass
        else:
            super().keyPressEvent(event)

    def _tab(self) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection() and self._selection_spans_lines(cursor):
            self._shift_lines(indent=True)
            return
        if self._settings.insert_spaces:
            column = self._visual_column(cursor)
            width = self._settings.tab_width
            cursor.insertText(" " * (width - column % width))
        else:
            cursor.insertText("\t")

    def _shift_lines(self, *, indent: bool) -> None:
        cursor = self.textCursor()
        doc = self.document()
        first = doc.findBlock(cursor.selectionStart())
        last = doc.findBlock(cursor.selectionEnd())
        # A selection ending at column 0 does not include that line.
        if cursor.hasSelection() and last.position() == cursor.selectionEnd() and last != first:
            last = last.previous()

        edit = QTextCursor(doc)
        edit.beginEditBlock()
        block = first
        while block.isValid():
            line = QTextCursor(block)
            if indent:
                if block.text().strip():  # don't create trailing whitespace on empty lines
                    line.insertText(self.indent_unit)
            else:
                text = block.text()
                remove = 1 if text.startswith("\t") else len(text) - len(text.lstrip(" "))
                remove = min(remove, self._settings.tab_width)
                if remove:
                    line.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, remove)
                    line.removeSelectedText()
            if block == last:
                break
            block = block.next()
        edit.endEditBlock()

    def _newline(self) -> None:
        cursor = self.textCursor()
        before = cursor.block().text()[: cursor.positionInBlock()]
        indent = before[: len(before) - len(before.lstrip(" \t"))] if self._settings.auto_indent else ""
        cursor.beginEditBlock()
        cursor.insertText("\n" + indent)
        cursor.endEditBlock()
        self.ensureCursorVisible()

    def _backspace_indent(self) -> bool:
        """In leading spaces, delete back to the previous tab stop. Returns True if handled."""
        cursor = self.textCursor()
        if cursor.hasSelection() or not self._settings.insert_spaces:
            return False
        col = cursor.positionInBlock()
        before = cursor.block().text()[:col]
        if col == 0 or before.strip(" "):
            return False
        width = self._settings.tab_width
        cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, (col - 1) % width + 1)
        cursor.removeSelectedText()
        return True

    def _selection_spans_lines(self, cursor: QTextCursor) -> bool:
        doc = self.document()
        return doc.findBlock(cursor.selectionStart()) != doc.findBlock(cursor.selectionEnd())

    def _visual_column(self, cursor: QTextCursor) -> int:
        column = 0
        for ch in cursor.block().text()[: cursor.positionInBlock()]:
            column = column + self._settings.tab_width - column % self._settings.tab_width if ch == "\t" else column + 1
        return column

    # -- line numbers / current line ------------------------------------------

    def line_number_area_width(self) -> int:
        digits = max(3, len(str(self.blockCount())))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margins(self, *_args) -> None:
        bottom = self.statusline.sizeHint().height() if self.statusline.isVisibleTo(self) else 0
        self.setViewportMargins(self.line_number_area_width(), 0, 0, bottom)
        self._layout_children()

    def _on_update_request(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_numbers.scroll(0, dy)
        else:
            self._line_numbers.update(0, rect.y(), self._line_numbers.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margins()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_children()

    def _layout_children(self) -> None:
        cr = self.contentsRect()
        viewport = self.viewport().geometry()
        self._line_numbers.setGeometry(QRect(cr.left(), viewport.top(), self.line_number_area_width(), viewport.height()))
        height = self.statusline.sizeHint().height()
        self.statusline.setGeometry(QRect(cr.left(), viewport.bottom() + 1, cr.width(), height))

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._line_numbers)
        palette = self.palette()
        painter.fillRect(event.rect(), palette.color(QPalette.ColorRole.Window))
        current = self.textCursor().blockNumber()
        dim = palette.color(QPalette.ColorRole.PlaceholderText)
        bright = palette.color(QPalette.ColorRole.Text)
        height = self.fontMetrics().height()
        width = self._line_numbers.width() - 8
        marked = self.diagnostics.line_severities()
        stale = self.diagnostics.stale

        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            bottom = top + round(self.blockBoundingRect(block).height())
            if block.isVisible() and bottom >= event.rect().top():
                if (severity := marked.get(block.blockNumber())) is not None:
                    color = QColor(STALE_COLOR if stale else SEVERITY_COLORS[severity])
                    painter.fillRect(QRect(1, top + 1, 4, bottom - top - 2), color)
                painter.setPen(bright if block.blockNumber() == current else dim)
                painter.drawText(0, top, width, height, Qt.AlignmentFlag.AlignRight, str(block.blockNumber() + 1))
            block = block.next()
            top = bottom
        painter.end()

    def _on_cursor_moved(self) -> None:
        selections = []
        if self._settings.highlight_current_line and not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            color = QColor(self.palette().color(QPalette.ColorRole.Highlight))
            color.setAlpha(30)
            selection.format.setBackground(color)
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            selections.append(selection)
        self.set_extra_layer("current_line", selections)
        self._line_numbers.update()
