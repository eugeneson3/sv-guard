"""File tree for the open project, driven like a vim buffer.

Keys: j/k down/up, h collapse or go to parent, l expand or open, Enter/o open or toggle,
gg/G first/last, / search visible names (n/N repeat), q hide the panel, Esc back to editor.
Leader and <C-w> sequences are handled by the window's PanelKeyDispatcher before these.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, QPersistentModelIndex, QRect, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QKeyEvent, QPainter, QPalette
from PySide6.QtWidgets import QFileSystemModel, QLineEdit, QTreeView, QWidget

from svguard.project import PathFilter

# Unlike the checker's DEFAULT_EXCLUDES this keeps dotfiles such as .svguard.yaml visible.
EXPLORER_EXCLUDES = (
    ".git",
    ".svn",
    ".hg",
    ".venv",
    "venv",
    ".svguard",
    ".Xil",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "*.egg-info",
    "xsim.dir",
    "*.cache",
    "*.runs",
    "*.sim",
    "*.gen",
    "*.hw",
    "*.ip_user_files",
)
EMPTY_HINT = "No folder open\n\nCtrl+Shift+O  open a folder\nCtrl+Shift+P  all commands"


class _ExcludeProxy(QSortFilterProxyModel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._root: Path | None = None
        self._filter = PathFilter(EXPLORER_EXCLUDES)

    def set_root(self, root: Path) -> None:
        self.beginFilterChange()  # Qt 6.10+ replacement for the deprecated invalidateFilter()
        self._root = root
        self.endFilterChange()

    def filterAcceptsRow(self, row: int, parent: QModelIndex | QPersistentModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        index = model.index(row, 0, parent)
        if self._root is None:
            return True
        try:
            rel = Path(model.filePath(index)).relative_to(self._root).as_posix()
        except ValueError:
            return True  # ancestors of the root (needed for the root index itself)
        return rel == "." or not self._filter.excluded(rel, is_dir=model.isDir(index))


class ProjectExplorer(QTreeView):
    file_activated = Signal(Path)
    escape_pressed = Signal()
    hide_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.root: Path | None = None
        self._model = QFileSystemModel(self)
        self._model.setReadOnly(True)
        self._model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden)
        self._proxy = _ExcludeProxy(self)
        self._proxy.setSourceModel(self._model)
        self._pending_g = False
        self._last_search = ""

        self.setHeaderHidden(True)
        self.setUniformRowHeights(True)
        self.doubleClicked.connect(self._activate)

        self._search = QLineEdit(self)
        self._search.setPlaceholderText("/ search")
        self._search.hide()
        self._search.returnPressed.connect(self._finish_search)
        self._search.installEventFilter(self)

    @property
    def source_model(self) -> QFileSystemModel:
        return self._model

    def set_root(self, root: Path) -> None:
        self.root = Path(root).resolve()
        if self.model() is not self._proxy:  # no model until a folder is open: the view shows a hint instead
            self.setModel(self._proxy)
            for column in range(1, self._model.columnCount()):
                self.hideColumn(column)  # size / type / date
        source_root = self._model.setRootPath(str(self.root))
        self._proxy.set_root(self.root)
        self._model.sort(0, Qt.SortOrder.AscendingOrder)  # folders first, then files
        self.setRootIndex(self._proxy.mapFromSource(source_root))

    def path_at(self, index: QModelIndex) -> Path | None:
        return Path(self._model.filePath(self._proxy.mapToSource(index))) if index.isValid() else None

    def index_of(self, path: Path) -> QModelIndex:
        """Fresh view index for `path`. QFileSystemModel re-sorts asynchronously, so plain
        QModelIndex values go stale across event-loop turns; look them up again by path."""
        return self._proxy.mapFromSource(self._model.index(str(path)))

    def select_path(self, path: Path) -> None:
        index = self.index_of(path)
        if index.isValid():
            self.setCurrentIndex(index)

    # -- keys ------------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key, text = event.key(), event.text()
        if self.model() is None:
            if key == Qt.Key.Key_Escape:
                self.escape_pressed.emit()
            return
        pending_g, self._pending_g = self._pending_g, False
        current = self.currentIndex()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) or text == "o":
            self._activate(current)
        elif key == Qt.Key.Key_Escape:
            self.escape_pressed.emit()
        elif text == "j":
            self._move(self.indexBelow(current))
        elif text == "k":
            self._move(self.indexAbove(current))
        elif text == "h":
            if current.isValid() and self.isExpanded(current):
                self.collapse(current)
            elif current.parent().isValid() and current.parent() != self.rootIndex():
                self._move(current.parent())
        elif text == "l":
            path = self.path_at(current)
            if path is not None and path.is_dir():
                if self.isExpanded(current) and self._proxy.rowCount(current):
                    self._move(self._proxy.index(0, 0, current))
                else:
                    self.expand(current)
            else:
                self._activate(current)
        elif text == "g":
            if pending_g:
                self._move(self._proxy.index(0, 0, self.rootIndex()))
            else:
                self._pending_g = True
        elif text == "G":
            self._move(self._last_visible())
        elif text == "q":
            self.hide_requested.emit()
        elif text == "/":
            self._start_search()
        elif text in ("n", "N") and self._last_search:
            self._search_next(forward=text == "n")
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        if self.model() is not None and not self.currentIndex().isValid() and self._proxy.rowCount(self.rootIndex()):
            self.setCurrentIndex(self._proxy.index(0, 0, self.rootIndex()))  # so j/k work immediately

    def paintEvent(self, event) -> None:  # noqa: N802
        if self.model() is not None:
            super().paintEvent(event)
            return
        painter = QPainter(self.viewport())
        painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
        painter.drawText(self.viewport().rect().adjusted(8, 16, -8, -8), Qt.AlignmentFlag.AlignHCenter, EMPTY_HINT)
        painter.end()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self._search and event.type() == event.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self._search.hide()
            self.setFocus()
            return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        height = self._search.sizeHint().height()
        self._search.setGeometry(QRect(0, self.height() - height, self.width(), height))

    # -- helpers ---------------------------------------------------------------------

    def _move(self, index: QModelIndex) -> None:
        if index.isValid():
            self.setCurrentIndex(index)
            self.scrollTo(index)

    def _last_visible(self) -> QModelIndex:
        index = self._proxy.index(0, 0, self.rootIndex())
        while (below := self.indexBelow(index)).isValid():
            index = below
        return index

    def _start_search(self) -> None:
        self._search.clear()
        self._search.show()
        self._search.raise_()
        self._search.setFocus()

    def _finish_search(self) -> None:
        self._last_search = self._search.text().strip().lower()
        self._search.hide()
        self.setFocus()
        if self._last_search:
            self._search_next(forward=True)

    def _search_next(self, *, forward: bool) -> None:
        """Next visible (expanded) item whose name contains the search text, wrapping around."""
        start = self.currentIndex()
        if not start.isValid():
            start = self._proxy.index(0, 0, self.rootIndex())
        step = self.indexBelow if forward else self.indexAbove
        index = step(start)
        wrapped = False
        while True:
            if not index.isValid():
                if wrapped:
                    return
                wrapped = True
                index = self._proxy.index(0, 0, self.rootIndex()) if forward else self._last_visible()
            if index == start and wrapped:
                return
            if self._last_search in (index.data() or "").lower():
                self._move(index)
                return
            index = step(index)

    def _activate(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        source = self._proxy.mapToSource(index)
        if self._model.isDir(source):
            self.setExpanded(index, not self.isExpanded(index))
        else:
            self.file_activated.emit(Path(self._model.filePath(source)))
