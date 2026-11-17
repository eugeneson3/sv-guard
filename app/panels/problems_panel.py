"""Problems panel: the last check's findings grouped by file.

Keys: j/k move, l/h expand/collapse a file, Enter/o jump to the problem, gg/G,
/ filter (Esc in the filter clears it), q hide the panel, Esc back to the editor.
Leader and <C-w> sequences are handled by the window's PanelKeyDispatcher first.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPalette
from PySide6.QtWidgets import QHeaderView, QLineEdit, QStyle, QTreeWidget, QTreeWidgetItem, QWidget

from svguard.model import Finding, Severity

_ICONS = {
    Severity.ERROR: QStyle.StandardPixmap.SP_MessageBoxCritical,
    Severity.WARNING: QStyle.StandardPixmap.SP_MessageBoxWarning,
    Severity.INFO: QStyle.StandardPixmap.SP_MessageBoxInformation,
    Severity.HINT: QStyle.StandardPixmap.SP_MessageBoxInformation,
}
_FINDING_ROLE = Qt.ItemDataRole.UserRole
_STALE_COLOR = "#9a9a9a"


class ProblemsPanel(QTreeWidget):
    jump_requested = Signal(object)  # Finding
    escape_pressed = Signal()
    hide_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        self.setUniformRowHeights(True)
        self.setRootIsDecorated(True)
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # the message gets the free width
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.itemActivated.connect(self._on_activated)
        self._findings: list[Finding] = []
        self._root: Path | None = None
        self._stale_files: set[Path] = set()
        self._filter = ""
        self._pending_g = False
        self.state = "idle"  # idle | running | done | error
        self.error = ""

        self._filter_edit = QLineEdit(self)
        self._filter_edit.setPlaceholderText("/ filter problems")
        self._filter_edit.hide()
        self._filter_edit.textChanged.connect(self._set_filter)
        self._filter_edit.returnPressed.connect(self._close_filter)
        self._filter_edit.installEventFilter(self)

    # -- content ---------------------------------------------------------------------

    def set_running(self) -> None:
        self.state = "running"
        self.viewport().update()

    def set_error(self, message: str) -> None:
        self.state, self.error = "error", message
        self.clear()
        self.viewport().update()

    def set_findings(self, findings: list[Finding], *, root: Path | None, stale_files: set[Path] = frozenset()) -> None:
        self.state, self.error = "done", ""
        self._findings = list(findings)
        self._root = root
        self._stale_files = set(stale_files)
        self._rebuild()

    def mark_stale(self, path: Path) -> None:
        if path not in self._stale_files and any(f.location.file == path for f in self._findings):
            self._stale_files.add(path)
            self._rebuild()

    def counts(self) -> Counter[Severity]:
        return Counter(f.severity for f in self._findings)

    def summary(self) -> str:
        counts = self.counts()
        return f"{counts[Severity.ERROR]} error(s), {counts[Severity.WARNING]} warning(s)"

    def visible_rows(self) -> list[str]:
        """Text of the rows in display order (expanded children included), for tests."""
        rows, item = [], self.topLevelItem(0)
        while item is not None:
            rows.append(item.text(0))
            item = self.itemBelow(item)
        return rows

    def current_finding(self) -> Finding | None:
        item = self.currentItem()
        return item.data(0, _FINDING_ROLE) if item is not None else None

    def select_finding(self, finding: Finding) -> None:
        for i in range(self.topLevelItemCount()):
            group = self.topLevelItem(i)
            for j in range(group.childCount()):
                if group.child(j).data(0, _FINDING_ROLE) == finding:
                    self.setCurrentItem(group.child(j))
                    return

    def _rebuild(self) -> None:
        self.clear()
        style = self.style()
        needle = self._filter.lower()
        by_file: dict[Path, list[Finding]] = {}
        for finding in sorted(self._findings, key=lambda f: f.sort_key):
            text = f"{finding.message} {finding.rule_id} {finding.slang_code or ''} {finding.location.file.name}"
            if needle and needle not in text.lower():
                continue
            by_file.setdefault(finding.location.file, []).append(finding)
        dim = QColor(_STALE_COLOR)
        bold = QFont(self.font())
        bold.setBold(True)
        for path, findings in by_file.items():
            stale = path in self._stale_files
            group = QTreeWidgetItem([self._display(path), f"{len(findings)}" + ("  (edited since check)" if stale else "")])
            group.setFont(0, bold)
            group.setToolTip(0, str(path))
            for finding in findings:
                loc = finding.location
                code = f"{finding.rule_id} {finding.slang_code}" if finding.slang_code else finding.rule_id
                child = QTreeWidgetItem([finding.message, f"{code}  [{loc.line}:{loc.col}]"])
                child.setIcon(0, style.standardIcon(_ICONS[finding.severity]))
                child.setData(0, _FINDING_ROLE, finding)
                child.setToolTip(0, f"{finding.severity.value}: {finding.message}")
                if stale:
                    child.setForeground(0, dim)
                    child.setForeground(1, dim)
                group.addChild(child)
            self.addTopLevelItem(group)
            group.setExpanded(True)
        if self.topLevelItemCount():
            first = self.topLevelItem(0)
            self.setCurrentItem(first.child(0) if first.childCount() else first)
        self.viewport().update()

    def _display(self, path: Path) -> str:
        if self._root is not None and path.is_relative_to(self._root):
            return path.relative_to(self._root).as_posix()
        return str(path)

    # -- keys ------------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key, text = event.key(), event.text()
        pending_g, self._pending_g = self._pending_g, False
        current = self.currentItem()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) or text == "o":
            if current is not None:
                self._on_activated(current, 0)
        elif key == Qt.Key.Key_Escape:
            self.escape_pressed.emit()
        elif text == "j" and current is not None:
            self._move(self.itemBelow(current))
        elif text == "k" and current is not None:
            self._move(self.itemAbove(current))
        elif text == "l" and current is not None:
            if current.childCount() and not current.isExpanded():
                current.setExpanded(True)
            elif current.childCount():
                self._move(current.child(0))
        elif text == "h" and current is not None:
            parent = current.parent()
            if parent is not None:
                self._move(parent)
            elif current.isExpanded():
                current.setExpanded(False)
        elif text == "g":
            if pending_g:
                self._move(self.topLevelItem(0))
            else:
                self._pending_g = True
        elif text == "G":
            last = self.topLevelItem(self.topLevelItemCount() - 1)
            while last is not None and last.isExpanded() and last.childCount():
                last = last.child(last.childCount() - 1)
            self._move(last)
        elif text == "/":
            self._filter_edit.setText(self._filter)
            self._filter_edit.show()
            self._filter_edit.raise_()
            self._filter_edit.setFocus()
        elif text == "q":
            self.hide_requested.emit()
        else:
            super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self._filter_edit and event.type() == event.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self._filter_edit.clear()  # Esc in the filter clears it
            self._close_filter()
            return True
        return super().eventFilter(watched, event)

    def _set_filter(self, text: str) -> None:
        self._filter = text.strip()
        self._rebuild()

    def _close_filter(self) -> None:
        self._filter_edit.hide()
        self.setFocus()

    def _move(self, item: QTreeWidgetItem | None) -> None:
        if item is not None:
            self.setCurrentItem(item)
            self.scrollToItem(item)

    def _on_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        finding = item.data(0, _FINDING_ROLE)
        if finding is not None:
            self.jump_requested.emit(finding)
        else:
            item.setExpanded(not item.isExpanded())

    # -- painting ----------------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        height = self._filter_edit.sizeHint().height()
        self._filter_edit.setGeometry(QRect(0, self.height() - height, self.width(), height))

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.topLevelItemCount():
            return
        hint = {
            "idle": "Save a .sv file (Ctrl+S, :w) or press <Space>r to check the project",
            "running": "Checking...",
            "error": f"Check failed: {self.error}",
        }.get(self.state, "No problems found" if not self._filter else f"No problems match '{self._filter}'")
        painter = QPainter(self.viewport())
        painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
        painter.drawText(self.viewport().rect().adjusted(8, 8, -8, -8), Qt.AlignmentFlag.AlignLeft, hint)
        painter.end()
