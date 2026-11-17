"""Keyboard-only picker shared by the command palette, Go to File and the buffer list.

Type to filter; Up/Down, Ctrl-n/Ctrl-p or Ctrl-j/Ctrl-k move; PageUp/PageDown jump;
Enter picks; Esc or a click anywhere outside closes it.

It is a normal (non-modal) window rather than a Qt::Popup so the Hangul IME works in it;
"click outside" is detected as losing window activation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QEvent, QEventLoop, QObject, Qt
from PySide6.QtGui import QKeyEvent, QPalette
from PySide6.QtWidgets import QDialog, QHeaderView, QLineEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from app.commands.fuzzy import fuzzy_filter

_MOVES = {
    Qt.Key.Key_Down: 1,
    Qt.Key.Key_Up: -1,
    Qt.Key.Key_PageDown: 10,
    Qt.Key.Key_PageUp: -10,
}
_CTRL_MOVES = {Qt.Key.Key_N: 1, Qt.Key.Key_J: 1, Qt.Key.Key_P: -1, Qt.Key.Key_K: -1}


@dataclass(frozen=True)
class FinderItem:
    label: str  # matched and shown on the left
    detail: str = ""  # shown dimmed on the right (key bindings, folder)
    payload: Any = None


class FuzzyFinder(QDialog):
    def __init__(self, items: Sequence[FinderItem], *, placeholder: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(False)  # a modal window would swallow the outside click instead of closing
        self._items = list(items)
        self.selected: FinderItem | None = None

        self.input = QLineEdit(self)
        self.input.setPlaceholderText(placeholder)
        self.input.installEventFilter(self)
        self.input.textChanged.connect(self._refresh)

        self.list = QTreeWidget(self)
        self.list.setColumnCount(2)
        self.list.setHeaderHidden(True)
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # typing always goes to the input line
        header = self.list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # the label gets the free width
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.list.itemActivated.connect(lambda _item, _col: self._accept_current())
        self.list.itemDoubleClicked.connect(lambda _item, _col: self._accept_current())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.input)
        layout.addWidget(self.list)
        self._refresh("")
        self._place(parent)

    @classmethod
    def choose(cls, items: Sequence[FinderItem], *, placeholder: str, parent: QWidget | None = None) -> FinderItem | None:
        finder = cls(items, placeholder=placeholder, parent=parent)
        finder.run()
        return finder.selected

    def run(self) -> None:
        """Like exec(): returns once an item is picked or the finder is dismissed."""
        loop = QEventLoop()
        self.finished.connect(loop.quit)
        self.show()
        self.activateWindow()
        self.input.setFocus()
        loop.exec()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isVisible() and not self.isActiveWindow():
            self.reject()  # the user clicked somewhere else

    def visible_labels(self) -> list[str]:
        return [self.list.topLevelItem(i).text(0) for i in range(self.list.topLevelItemCount())]

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.input and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            key, ctrl = event.key(), bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._accept_current()
                return True
            step = _CTRL_MOVES.get(key) if ctrl else _MOVES.get(key)
            if step is not None:
                self._move(step)
                return True
        return super().eventFilter(watched, event)

    def _refresh(self, query: str) -> None:
        self.list.clear()
        dim = self.palette().color(QPalette.ColorRole.PlaceholderText)
        for item in fuzzy_filter(query, self._items, key=lambda i: i.label):
            row = QTreeWidgetItem([item.label, item.detail])
            row.setData(0, Qt.ItemDataRole.UserRole, item)
            row.setForeground(1, dim)
            row.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.list.addTopLevelItem(row)
        if self.list.topLevelItemCount():
            self.list.setCurrentItem(self.list.topLevelItem(0))

    def _move(self, step: int) -> None:
        count = self.list.topLevelItemCount()
        if not count:
            return
        current = self.list.indexOfTopLevelItem(self.list.currentItem()) if self.list.currentItem() else 0
        self.list.setCurrentItem(self.list.topLevelItem(max(0, min(count - 1, current + step))))

    def _accept_current(self) -> None:
        current = self.list.currentItem()
        if current is not None:
            self.selected = current.data(0, Qt.ItemDataRole.UserRole)
            self.accept()

    def _place(self, parent: QWidget | None) -> None:
        window = parent.window() if parent is not None else None
        if window is None:
            self.resize(640, 420)
            return
        width = min(720, max(420, int(window.width() * 0.6)))
        self.resize(width, min(440, max(240, int(window.height() * 0.6))))
        top_left = window.mapToGlobal(window.rect().topLeft())
        self.move(top_left.x() + (window.width() - width) // 2, top_left.y() + 60)
