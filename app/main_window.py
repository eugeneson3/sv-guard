"""Main window: explorer dock + editor tabs + status bar, driven by named commands.

Every feature is an AppCommand in one registry. Menus, Qt shortcuts, the command palette
(Ctrl+Shift+P), keymap.yaml mappings (<Space>f, <C-w>l, gt) and ex commands (:file.find)
all run the same commands, so anything reachable by mouse is reachable by keyboard.
Qt shortcuts stay off keys vim uses in the editor (Ctrl-W/O/R/V/A/X/B/F/D/U).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import QApplication, QDockWidget, QFileDialog, QLabel, QMainWindow, QMenu, QWidget

from app.commands.keymap import (
    USER_KEYMAP_TEMPLATE,
    Keymap,
    PanelKeyDispatcher,
    default_user_keymap_path,
    load_keymap,
)
from app.commands.registry import AppCommand, CommandRegistry
from app.editor.code_editor import CodeEditor
from app.editor.editor_tabs import SV_SUFFIXES, EditorTabs
from app.editor.qt_buffer import QtDocumentBuffer
from app.panels.fuzzy_finder import FinderItem, FuzzyFinder
from app.panels.problems_panel import ProblemsPanel
from app.panels.project_explorer import EXPLORER_EXCLUDES, ProjectExplorer
from app.services.analysis_service import AnalysisOutcome, AnalysisService, ExecutorFactory
from app.services.session_service import SessionService
from app.settings import Settings, default_settings_path, ensure_settings_file, load_settings
from svguard.model import Finding, Severity
from svguard.project import PathFilter
from svguard.runner import AnalysisReport, AnalysisRequest
from vimcore import Pos, viminfo

_ENCODING_LABELS = {"utf-8": "UTF-8", "utf-8-sig": "UTF-8 with BOM", "cp949": "CP949", "latin-1": "Latin-1"}
_STATUS_TIMEOUT_MS = 6000
_MAX_FINDER_FILES = 20_000
_SESSION_AUTOSAVE_MS = 1500  # also survive crashes, not only clean exits

Chooser = Callable[[Sequence[FinderItem], str], "FinderItem | None"]


def project_files(root: Path, limit: int = _MAX_FINDER_FILES) -> list[Path]:
    """Files under `root` for Go to File, skipping tool output folders like the explorer does."""
    path_filter = PathFilter(EXPLORER_EXCLUDES)
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root).as_posix()
        prefix = "" if rel == "." else f"{rel}/"
        dirnames[:] = sorted(d for d in dirnames if not path_filter.excluded(prefix + d, is_dir=True))
        for name in sorted(filenames):
            if not path_filter.excluded(prefix + name, is_dir=False):
                found.append(Path(dirpath, name))
                if len(found) >= limit:
                    return found
    return found


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings_path: Path | None = None,
        session: SessionService | None = None,
        keymap_path: Path | None = None,
        analysis_executor: ExecutorFactory | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings_path = settings_path or default_settings_path()
        self.keymap_path = keymap_path or default_user_keymap_path()
        self.settings, warnings = load_settings(self.settings_path)
        self.session = session or SessionService()
        self.project_root: Path | None = None
        self._session_frozen = False  # set once the window has closed: nothing may overwrite the saved tabs
        self._session_timer = QTimer(self)
        self._session_timer.setSingleShot(True)
        self._session_timer.setInterval(_SESSION_AUTOSAVE_MS)
        self._session_timer.timeout.connect(self.save_session)
        # Replaceable so tests can pick an item without a modal dialog.
        self.chooser: Chooser = lambda items, placeholder: FuzzyFinder.choose(items, placeholder=placeholder, parent=self)

        self.tabs = EditorTabs(self.settings.editor, self.settings.vim)
        self.setCentralWidget(self.tabs)

        self.explorer = ProjectExplorer()
        self.explorer_dock = QDockWidget("Explorer", self)
        self.explorer_dock.setObjectName("explorer_dock")  # stable name for saveState() in Step 3
        self.explorer_dock.setWidget(self.explorer)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.explorer_dock)

        self.problems = ProblemsPanel()
        self.problems_dock = QDockWidget("Problems", self)
        self.problems_dock.setObjectName("problems_dock")
        self.problems_dock.setWidget(self.problems)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.problems_dock)
        self.resizeDocks([self.problems_dock], [160], Qt.Orientation.Vertical)

        self.analysis = AnalysisService(analysis_executor, self)
        self.last_report: AnalysisReport | None = None

        self._check_label = QLabel()  # "Checking..." or the totals of the last check
        self._check_label.setContentsMargins(8, 0, 8, 0)
        self.statusBar().addPermanentWidget(self._check_label)
        self._position_label = QLabel()
        self._indent_label = QLabel()
        self._encoding_label = QLabel()
        self._eol_label = QLabel()
        for label in (self._position_label, self._indent_label, self._encoding_label, self._eol_label):
            label.setContentsMargins(8, 0, 8, 0)
            self.statusBar().addPermanentWidget(label)

        self.registry = CommandRegistry()
        self.actions: dict[str, QAction] = {}
        self._register_commands()
        self._build_menus()

        self.keymap = Keymap()
        self._panel_keys = PanelKeyDispatcher(self.keymap.panel_trie(), self.keymap.timeoutlen, self)
        self._panel_keys.command.connect(lambda command_id: self.run_command(command_id))
        self.explorer.installEventFilter(self._panel_keys)
        self.problems.installEventFilter(self._panel_keys)
        warnings += self.reload_keymap(announce=False)

        self._connect_signals()
        self._update_title()
        self._update_status()
        self.resize(1200, 800)
        if warnings:
            self._show_message("; ".join(warnings))

    # -- commands ------------------------------------------------------------------------

    def _register_commands(self) -> None:
        def add(command_id, title, category, handler, *shortcuts, planned=None):
            self.registry.add(AppCommand(command_id, title, handler, category, tuple(shortcuts), planned))

        tabs = self.tabs
        add("file.openProject", "Open Folder...", "File", lambda c: self.choose_project(), "Ctrl+Shift+O")
        add("file.openRecent", "Open Recent Folder...", "File", lambda c: self.choose_recent_project())
        add("file.openFile", "Open File...", "File", lambda c: self.choose_file())
        add("file.find", "Go to File...", "File", lambda c: self.find_file(), "Ctrl+P")
        add("file.save", "Save", "File", lambda c: tabs.save(), "Ctrl+S")
        add("file.saveAll", "Save All", "File", lambda c: tabs.save_all(), "Ctrl+Shift+S")
        add("file.close", "Close Tab", "File", lambda c: tabs.close_current(), "Ctrl+F4")
        add("settings.open", "Open Settings", "Preferences", lambda c: self.open_settings(), "Ctrl+,")
        add("keymap.open", "Open User Keymap", "Preferences", lambda c: self.open_keymap())
        add("app.quit", "Exit", "File", lambda c: self.close(), "Ctrl+Q")

        add("palette.show", "Command Palette...", "View", lambda c: self.show_palette(), "Ctrl+Shift+P")
        add("view.toggleExplorer", "Toggle Explorer", "View", lambda c: self.toggle_explorer())
        add("view.focusExplorer", "Focus Explorer", "View", lambda c: self.focus_explorer(), "Ctrl+Shift+E")
        add("view.focusEditor", "Focus Editor", "View", lambda c: self.focus_editor(), "Ctrl+1")

        add("tab.next", "Next Tab", "Go", lambda c: tabs.goto_tab(c) if c else tabs.select_relative(1), "Ctrl+Tab", "Ctrl+PgDown")
        add("tab.previous", "Previous Tab", "Go", lambda c: tabs.select_relative(-(c or 1)), "Ctrl+Shift+Tab", "Ctrl+PgUp")
        add("buffer.alternate", "Alternate Tab", "Go", lambda c: tabs.alternate() or self.notify("No alternate tab"))
        add("buffer.list", "Switch Tab...", "Go", lambda c: self.choose_buffer())
        add("window.focusLeft", "Focus Left", "Go", lambda c: self.focus_direction(-1, 0))
        add("window.focusRight", "Focus Right", "Go", lambda c: self.focus_direction(1, 0))
        add("window.focusUp", "Focus Up", "Go", lambda c: self.focus_direction(0, -1))
        add("window.focusDown", "Focus Down", "Go", lambda c: self.focus_direction(0, 1))
        add("window.focusNext", "Focus Next Panel", "Go", lambda c: self.focus_next())

        add("check.run", "Check Project", "Check", lambda c: self.check())
        add("problems.show", "Show Problems", "Check", lambda c: self.focus_problems())
        add("problems.toggle", "Toggle Problems Panel", "Check", lambda c: self.toggle_problems())
        add("problems.next", "Next Problem", "Check", lambda c: self.goto_problem(1, count=c or 1))
        add("problems.previous", "Previous Problem", "Check", lambda c: self.goto_problem(-1, count=c or 1))
        add("problems.nextError", "Next Error", "Check", lambda c: self.goto_problem(1, count=c or 1, errors_only=True))
        add("problems.previousError", "Previous Error", "Check", lambda c: self.goto_problem(-1, count=c or 1, errors_only=True))

        for command_id, title, step in (
            ("explain.toggle", "Explain Panel", "5"),
            ("sim.run", "Run Simulation", "8"),
            ("synth.run", "Run Synthesis", "11"),
        ):
            add(command_id, title, "Tools", lambda c, t=title, s=step: self.notify(f"{t} arrives in Step {s}"), planned=step)

    def _build_menus(self) -> None:
        layout = {
            "&File": ["file.openProject", "file.openRecent", "file.openFile", "file.find", None, "file.save",
                      "file.saveAll", "file.close", None, "settings.open", "keymap.open", None, "app.quit"],
            "&View": ["palette.show", None, "view.toggleExplorer", "view.focusExplorer", "view.focusEditor"],
            "&Go": ["tab.next", "tab.previous", "buffer.alternate", "buffer.list", None, "window.focusLeft",
                    "window.focusRight", "window.focusUp", "window.focusDown", "window.focusNext"],
            "&Check": ["check.run", None, "problems.show", "problems.toggle", "problems.next", "problems.previous",
                       "problems.nextError", "problems.previousError"],
            "&Tools": ["explain.toggle", "sim.run", "synth.run"],
        }  # fmt: skip
        for title, ids in layout.items():
            menu: QMenu = self.menuBar().addMenu(title)
            for command_id in ids:
                if command_id is None:
                    menu.addSeparator()
                    continue
                command = self.registry.get(command_id)
                action = QAction(command.title + (f"  (Step {command.planned_step})" if command.planned_step else ""), self)
                action.setShortcuts([QKeySequence(s) for s in command.shortcuts])
                action.triggered.connect(lambda _checked=False, cid=command_id: self.run_command(cid))
                menu.addAction(action)
                self.actions[command_id] = action

    def run_command(self, command_id: str, count: int | None = None) -> None:
        if not self.registry.run(command_id, count):
            self.notify(f"Unknown command: {command_id}", error=True)

    def notify(self, text: str, *, error: bool = False) -> None:
        """Status bar, plus the editor's vim status line where the eyes usually are."""
        self._show_message(text)
        self.tabs.show_vim_message(text, error=error)

    # -- keymap ----------------------------------------------------------------------------

    def reload_keymap(self, *, announce: bool = True) -> list[str]:
        keymap, warnings = load_keymap(self.keymap_path)
        unknown = sorted(keymap.command_ids() - self.registry.ids())
        warnings += [f"keymap: unknown command '{command_id}'" for command_id in unknown]
        self.keymap = keymap
        self.tabs.set_vim_mappings(keymap.mappings(), self.registry.ids())
        self._panel_keys.configure(keymap.panel_trie(), keymap.timeoutlen)
        if announce:
            self.notify("Keymap applied" + (": " + "; ".join(warnings) if warnings else ""), error=bool(warnings))
        return warnings

    def open_keymap(self) -> None:
        if not self.keymap_path.exists():
            self.keymap_path.parent.mkdir(parents=True, exist_ok=True)
            self.keymap_path.write_text(USER_KEYMAP_TEMPLATE, encoding="utf-8")
        self.tabs.open_file(self.keymap_path)

    # -- pickers ---------------------------------------------------------------------------

    def show_palette(self) -> None:
        items = []
        for command in self.registry:
            keys = [*command.shortcuts, *self.keymap.bindings_for(command.id)]
            detail = f"Step {command.planned_step}" if command.planned_step else "  ".join(keys)
            items.append(FinderItem(command.label, detail, command.id))
        if (choice := self.chooser(items, "Type a command")) is not None:
            self.run_command(choice.payload)

    def find_file(self) -> None:
        if self.project_root is None:
            self.notify("Open a folder first (Ctrl+Shift+O)")
            return
        root = self.project_root
        items = [FinderItem(p.relative_to(root).as_posix(), payload=p) for p in project_files(root)]
        if (choice := self.chooser(items, "Go to file")) is not None:
            self.open_file(choice.payload)

    def choose_buffer(self) -> None:
        items = []
        for editor in self.tabs.editors():
            path = self.tabs.file_info(editor).path
            folder = path.parent.relative_to(self.project_root).as_posix() if self._in_project(path) else str(path.parent)
            items.append(FinderItem(path.name, folder, editor))
        if not items:
            self.notify("No open tabs")
            return
        if (choice := self.chooser(items, "Switch to tab")) is not None:
            self.tabs.setCurrentWidget(choice.payload)
            choice.payload.setFocus()

    def choose_recent_project(self) -> None:
        items = [FinderItem(p.name, str(p), p) for p in self.session.recent_projects()]
        if not items:
            self.notify("No recent folders yet")
            return
        if (choice := self.chooser(items, "Open recent folder")) is not None:
            self.open_project(choice.payload)

    # -- session ---------------------------------------------------------------------------

    def restore_layout(self) -> None:
        """Window size and dock layout from last time. Call before show() to avoid a flicker."""
        geometry, layout = self.session.window_state()
        if geometry:
            self.restoreGeometry(QByteArray(geometry))
        if layout:
            self.restoreState(QByteArray(layout))

    def restore_workspace(self, path: Path | None = None) -> None:
        """Vim registers/history, then `path` (folder or file) or the last folder with its tabs."""
        if self.settings.session.restore_vim_state:
            viminfo.load(self.tabs.vim_shared, self.session.vim_state())
        if path is None:
            if not self.open_last_project(show_explorer=False) and self.settings.session.restore_tabs:
                self._restore_tabs(None)
            return
        target = Path(path).resolve()
        if target.is_dir():
            self.open_project(target)
        elif target.is_file():
            self.open_project(target.parent)
            self.open_file(target)

    def save_session(self) -> None:
        self._session_timer.stop()
        if self._session_frozen:
            return
        if self.settings.session.restore_tabs:
            self.session.set_project_state(self.project_root, self.tabs.session_state())
        self.session.set_window_state(bytes(self.saveGeometry().data()), bytes(self.saveState().data()))
        if self.settings.session.restore_vim_state:
            self.session.set_vim_state(viminfo.dump(self.tabs.vim_shared))
        self.session.save()

    def _schedule_session_save(self, *_args) -> None:
        if not self._session_frozen:
            self._session_timer.start()

    def _restore_tabs(self, root: Path | None) -> None:
        missing = self.tabs.restore(self.session.project_state(root))
        if missing:
            self.notify(f"{len(missing)} file(s) from the last session no longer exist")
        self.focus_editor()

    # -- project / files -------------------------------------------------------------------

    def open_project(self, root: Path | str, *, show_explorer: bool = True) -> bool:
        """Open a folder. Switching from another folder saves its tabs and closes them first;
        the new folder's tabs from last time come back. False if the user cancelled."""
        root = Path(root).resolve()
        if not root.is_dir():
            self._show_message(f"Not a folder: {root}")
            return False
        if root == self.project_root:
            return True
        if self.project_root is not None and self.tabs.count():
            self.save_session()
            if not self.tabs.close_all():
                return False
        self.project_root = root
        self.session.remember_project(root)
        self.analysis.warm_up()  # start the checker process now so the first save is quick
        self.explorer.set_root(root)
        if show_explorer:
            self.explorer_dock.show()
        self._update_title()
        if self.settings.session.restore_tabs:
            self._restore_tabs(root)
        return True

    def open_last_project(self, *, show_explorer: bool = True) -> bool:
        """Reopen the folder used last time. False if there is none (or it was deleted)."""
        last = self.session.last_project()
        return last is not None and self.open_project(last, show_explorer=show_explorer)

    def choose_project(self) -> None:
        start = str(self.project_root or Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Open Folder", start)
        if folder:
            self.open_project(folder)

    def choose_file(self) -> None:
        start = str(self.project_root or Path.home())
        path, _filter = QFileDialog.getOpenFileName(
            self, "Open File", start, "SystemVerilog (*.sv *.svh *.v *.vh);;All files (*)"
        )
        if path:
            self.open_file(path)

    def open_file(self, path: Path | str) -> None:
        self.tabs.open_file(path)

    def open_settings(self) -> None:
        self.tabs.open_file(ensure_settings_file(self.settings_path))

    def apply_settings(self, settings: Settings) -> None:
        self.settings = settings
        self.tabs.apply_settings(settings.editor, settings.vim)
        self._update_status()

    def _in_project(self, path: Path) -> bool:
        return self.project_root is not None and path.is_relative_to(self.project_root)

    # -- checking --------------------------------------------------------------------------

    def check(self, saved: Path | None = None) -> None:
        """Check the open folder (or, with no folder, the saved/current file) in the worker."""
        if self.project_root is not None:
            target = self.project_root
        elif saved is not None or (saved := self._current_path()) is not None:
            target = saved
        else:
            self.notify("Open a folder or a .sv file to check")
            return
        self.analysis.request(AnalysisRequest(paths=(target,)))

    def _on_check_started(self, _request: AnalysisRequest) -> None:
        self._check_label.setText("Checking...")
        self.problems.set_running()

    def _on_check_finished(self, outcome: AnalysisOutcome) -> None:
        if outcome.report is None:
            self._check_label.setText("Check failed")
            self.problems.set_error(outcome.error or "unknown error")
            self.notify(f"Check failed: {outcome.error}", error=True)
            return
        report = self.last_report = outcome.report
        stale = {e_path for e in self.tabs.editors() if e.document().isModified() and (e_path := self._path_of(e))}
        self.problems.set_findings(list(report.findings), root=self.project_root, stale_files=stale)
        for editor in self.tabs.editors():
            self._apply_findings(editor)
        counts = self.problems.counts()
        self._check_label.setText(
            f"{counts[Severity.ERROR]} error(s), {counts[Severity.WARNING]} warning(s)  ({report.seconds:.2f} s)"
        )
        if self.tabs.current_editor() is not None:  # refresh the vim status line counts
            self.tabs.current_editor().diagnostics.changed.emit()

    def _apply_findings(self, editor: CodeEditor) -> None:
        if self.last_report is None or (path := self._path_of(editor)) is None:
            return
        findings = [f for f in self.last_report.findings if f.location.file == path]
        # A file edited after it was saved for this check: positions may be off, so show it as stale.
        editor.set_findings(findings, stale=editor.document().isModified())

    def _on_file_opened(self, path: Path) -> None:
        editor = self.tabs.editor_for(path)
        if editor is None:
            return
        self._apply_findings(editor)
        editor.diagnostics.changed.connect(lambda e=editor: self._on_editor_diagnostics_changed(e))

    def _on_editor_diagnostics_changed(self, editor: CodeEditor) -> None:
        if editor.diagnostics.stale and (path := self._path_of(editor)) is not None:
            self.problems.mark_stale(path)

    def focus_problems(self) -> None:
        self.problems_dock.show()
        self.problems.setFocus()

    def toggle_problems(self) -> None:
        if self.problems_dock.isVisible():
            self.problems_dock.hide()
            self.focus_editor()
        else:
            self.focus_problems()

    def goto_problem(self, direction: int, *, count: int = 1, errors_only: bool = False) -> None:
        """]d [d ]e [e: the next/previous finding after the cursor, across files, wrapping."""
        entries = self._problem_positions(errors_only)
        if not entries:
            self.notify("No errors" if errors_only else "No problems")
            return
        here = (self._sort_key(self._current_path()), *self._current_line_col())
        keys = [(self._sort_key(path), line, col) for path, line, col, _f in entries]
        index = -1
        for _ in range(count):
            if direction > 0:
                index = next((i for i, k in enumerate(keys) if k > here), 0)
            else:
                index = next((i for i in range(len(keys) - 1, -1, -1) if keys[i] < here), len(keys) - 1)
            here = keys[index]
        self.jump_to_finding(entries[index][3])

    def jump_to_finding(self, finding: Finding) -> None:
        editor = self.tabs.open_file(finding.location.file)
        if editor is None:
            return
        position = editor.diagnostics.position_of(finding)
        buffer = QtDocumentBuffer(editor.document())
        pos = buffer.pos_from(position) if position is not None else Pos(finding.location.line - 1, finding.location.col - 1)
        if editor.vim is not None:
            editor.vim.engine.set_cursor(pos)
            editor.vim.render()
        else:
            cursor = editor.textCursor()
            cursor.setPosition(buffer.position(pos))
            editor.setTextCursor(cursor)
        self.problems.select_finding(finding)
        editor.setFocus()

    def _problem_positions(self, errors_only: bool) -> list[tuple[Path, int, int, Finding]]:
        """(file, line, col, finding) sorted; open files use the anchored (edited) positions."""
        if self.last_report is None:
            return []
        entries = []
        for finding in self.last_report.findings:
            if errors_only and finding.severity is not Severity.ERROR:
                continue
            path, line, col = finding.location.file, finding.location.line, finding.location.col
            editor = self.tabs.editor_for(path)
            if editor is not None and (position := editor.diagnostics.position_of(finding)) is not None:
                pos = QtDocumentBuffer(editor.document()).pos_from(position)
                line, col = pos.row + 1, pos.col + 1
            entries.append((path, line, col, finding))
        return sorted(entries, key=lambda e: (self._sort_key(e[0]), e[1], e[2]))

    def _current_path(self) -> Path | None:
        info = self.tabs.current_file()
        return info.path if info is not None else None

    def _current_line_col(self) -> tuple[int, int]:
        editor = self.tabs.current_editor()
        if editor is None:
            return (0, 0)
        pos = QtDocumentBuffer(editor.document()).pos_from(editor.textCursor().position())
        return pos.row + 1, pos.col + 1

    def _path_of(self, editor: CodeEditor) -> Path | None:
        return self.tabs.file_info(editor).path if self.tabs.indexOf(editor) >= 0 else None

    @staticmethod
    def _sort_key(path: Path | None) -> str:
        return str(path) if path is not None else ""

    # -- focus -----------------------------------------------------------------------------

    def toggle_explorer(self) -> None:
        if self.explorer_dock.isVisible():
            self.explorer_dock.hide()
            self.focus_editor()
        else:
            self.focus_explorer()

    def focus_explorer(self) -> None:
        self.explorer_dock.show()
        self.explorer.setFocus()

    def focus_editor(self) -> None:
        if (editor := self.tabs.current_editor()) is not None:
            editor.setFocus()

    def focus_regions(self) -> list[QWidget]:
        """Panels that can take keyboard focus, in <C-w>w order."""
        regions: list[QWidget] = []
        if self.explorer_dock.isVisible():
            regions.append(self.explorer)
        if (editor := self.tabs.current_editor()) is not None:
            regions.append(editor)
        if self.problems_dock.isVisible():
            regions.append(self.problems)
        return regions

    def focus_direction(self, dx: int, dy: int) -> None:
        """<C-w>h/j/k/l: move focus to the nearest panel in that direction."""
        regions = self.focus_regions()
        current = self._focused_region(regions)
        if current is None:  # focus is in a menu or nowhere: start from the editor
            if (target := self.tabs.current_editor() or (regions[0] if regions else None)) is not None:
                target.setFocus()
            return
        cx, cy = self._center(current)
        best, best_cost = None, None
        for region in regions:
            if region is current:
                continue
            x, y = self._center(region)
            along = (x - cx) * dx + (y - cy) * dy
            if along <= 0:
                continue
            cost = along + 2 * abs((x - cx) * dy + (y - cy) * dx)
            if best_cost is None or cost < best_cost:
                best, best_cost = region, cost
        if best is not None:
            best.setFocus()

    def focus_next(self) -> None:
        regions = self.focus_regions()
        if not regions:
            return
        current = self._focused_region(regions)
        index = regions.index(current) + 1 if current is not None else 0
        regions[index % len(regions)].setFocus()

    def _focused_region(self, regions: list[QWidget]) -> QWidget | None:
        focus = QApplication.focusWidget()
        return next((r for r in regions if focus is not None and (r is focus or r.isAncestorOf(focus))), None)

    def _center(self, widget: QWidget) -> tuple[int, int]:
        point = widget.mapTo(self, widget.rect().center())
        return point.x(), point.y()

    # -- events / status ---------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.explorer.file_activated.connect(self.open_file)
        self.explorer.escape_pressed.connect(self.focus_editor)
        self.explorer.hide_requested.connect(self.toggle_explorer)
        self.tabs.current_file_changed.connect(lambda _path: (self._update_title(), self._update_status()))
        self.tabs.cursor_moved.connect(self._update_position)
        self.tabs.status_message.connect(self._show_message)
        self.tabs.file_saved.connect(self._on_file_saved)
        self.tabs.quit_all_requested.connect(self._quit_all)
        self.tabs.command_requested.connect(self.run_command)
        self.tabs.currentChanged.connect(self._schedule_session_save)
        self.tabs.cursor_moved.connect(self._schedule_session_save)
        self.tabs.file_opened.connect(self._schedule_session_save)
        self.tabs.file_opened.connect(self._on_file_opened)
        self.analysis.started.connect(self._on_check_started)
        self.analysis.finished.connect(self._on_check_finished)
        self.problems.jump_requested.connect(self.jump_to_finding)
        self.problems.escape_pressed.connect(self.focus_editor)
        self.problems.hide_requested.connect(self.toggle_problems)

    def _quit_all(self, force: bool) -> None:
        """vim's :qa (asks about unsaved files) and :qa! (discards them)."""
        if force:
            self.save_session()  # remember the tabs before they are thrown away
            self._session_frozen = True
            self.tabs.close_all(force=True)
        self.close()

    def _on_file_saved(self, path: Path) -> None:
        if path == self.settings_path.resolve():
            settings, warnings = load_settings(self.settings_path)
            self.apply_settings(settings)
            self.notify("Settings applied" + (": " + "; ".join(warnings) if warnings else ""), error=bool(warnings))
        elif path == self.keymap_path.resolve():
            self.reload_keymap()
        elif path.suffix.lower() in SV_SUFFIXES:
            self.check(saved=path)  # checks run on save, never while typing

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.save_session()  # before the tabs are closed
        if self.tabs.close_all():
            self._session_frozen = True
            self.analysis.shutdown()
            event.accept()
        else:
            event.ignore()

    def _show_message(self, text: str) -> None:
        self.statusBar().showMessage(text, _STATUS_TIMEOUT_MS)

    def _update_title(self) -> None:
        parts = []
        if (info := self.tabs.current_file()) is not None:
            parts.append(info.path.name)
        if self.project_root is not None:
            parts.append(self.project_root.name)
        parts.append("SV-Guard")
        self.setWindowTitle(" — ".join(parts))

    def _update_position(self, line: int, col: int) -> None:
        self._position_label.setText(f"Ln {line}, Col {col}")

    def _update_status(self) -> None:
        editor_settings = self.settings.editor
        indent = "Spaces" if editor_settings.insert_spaces else "Tab Size"
        self._indent_label.setText(f"{indent}: {editor_settings.tab_width}")
        info = self.tabs.current_file()
        if info is None:
            for label in (self._position_label, self._encoding_label, self._eol_label):
                label.clear()
            return
        self._encoding_label.setText(_ENCODING_LABELS.get(info.encoding, info.encoding))
        self._eol_label.setText("CRLF" if info.eol == "\r\n" else "LF")
