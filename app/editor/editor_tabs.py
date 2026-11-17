"""Tabbed editors: one CodeEditor per open file.

Files keep their original encoding (utf-8 / utf-8 with BOM / cp949) and line endings
on save. `file_saved` is the hook Step 4 uses to run the checker.
With vim enabled every editor gets a VimAdapter; all of them share registers, the last
search and `.` (vim keeps those per session, not per buffer).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QMessageBox, QTabWidget, QWidget

from app.editor.code_editor import CodeEditor
from app.editor.sv_highlighter import SvHighlighter
from app.editor.qt_buffer import QtDocumentBuffer
from app.editor.vim_adapter import QtClipboard, VimAdapter
from app.services.session_service import ProjectState, TabState
from app.settings import EditorSettings, VimSettings
from svguard.textio import decode_source, detect_eol, normalize_eol, read_source, write_source
from vimcore import HostRequest, Pos, Registers, SharedState, VimOptions
from vimcore.mapping import Mappings

SV_SUFFIXES = frozenset({".sv", ".svh", ".v", ".vh"})
_BINARY_SNIFF_BYTES = 8192

CloseChoice = Literal["save", "discard", "cancel"]


@dataclass
class OpenFile:
    path: Path
    encoding: str
    eol: str


class EditorTabs(QTabWidget):
    file_opened = Signal(Path)
    file_saved = Signal(Path)
    current_file_changed = Signal(object)  # Path | None
    cursor_moved = Signal(int, int)  # line, column of the current editor (1-based)
    status_message = Signal(str)
    quit_all_requested = Signal(bool)  # :qa / :qa! (force)
    command_requested = Signal(str, object)  # host command id from a vim mapping or :id, count | None

    def __init__(self, settings: EditorSettings, vim: VimSettings | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._vim_settings = vim or VimSettings()
        self._vim_shared = SharedState(Registers(QtClipboard(), unnamedplus=self._vim_settings.clipboard_unnamedplus))
        self._files: dict[CodeEditor, OpenFile] = {}
        self._current: CodeEditor | None = None
        self._previous: CodeEditor | None = None  # for <C-^> (alternate buffer)
        # Replaceable so tests (and later a keyboard-first prompt) can answer without a dialog.
        self.ask_close: Callable[[Path], CloseChoice] = self._ask_close_dialog

        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)
        self.tabCloseRequested.connect(self.close_tab)
        self.currentChanged.connect(self._on_current_changed)

    # -- queries ---------------------------------------------------------------

    def current_editor(self) -> CodeEditor | None:
        widget = self.currentWidget()
        return widget if isinstance(widget, CodeEditor) else None

    def current_file(self) -> OpenFile | None:
        editor = self.current_editor()
        return self._files.get(editor) if editor else None

    def file_info(self, editor: CodeEditor) -> OpenFile:
        return self._files[editor]

    def editors(self) -> list[CodeEditor]:
        return [w for i in range(self.count()) if isinstance(w := self.widget(i), CodeEditor)]

    def editor_for(self, path: Path) -> CodeEditor | None:
        path = Path(path).resolve()
        return next((e for e, f in self._files.items() if f.path == path), None)

    def open_paths(self) -> list[Path]:
        return [self._files[e].path for e in self.editors()]

    # -- open / save / close -----------------------------------------------------

    def open_file(self, path: Path | str) -> CodeEditor | None:
        path = Path(path).resolve()
        if (existing := self.editor_for(path)) is not None:
            self.setCurrentWidget(existing)
            return existing
        try:
            data = path.read_bytes()
        except OSError as exc:
            self.status_message.emit(f"Cannot open {path.name}: {exc.strerror or exc}")
            return None
        if b"\0" in data[:_BINARY_SNIFF_BYTES]:
            self.status_message.emit(f"{path.name} looks like a binary file; not opened")
            return None

        source = decode_source(data)
        editor = CodeEditor(self._settings)
        if path.suffix.lower() in SV_SUFFIXES:
            # Attach before setting text: a highlighter added later only runs on the next event loop pass.
            editor.highlighter = SvHighlighter(editor.document(), dark=editor.is_dark())
        editor.setPlainText(normalize_eol(source.text))
        editor.document().setModified(False)
        editor.document().modificationChanged.connect(lambda _modified: self._refresh_titles())
        editor.cursorPositionChanged.connect(lambda e=editor: self._emit_cursor(e))

        self._files[editor] = OpenFile(path, source.encoding, detect_eol(source.text))
        index = self.addTab(editor, path.name)
        self.setTabToolTip(index, str(path))
        if self._vim_settings.enabled:
            self._attach_vim(editor)
        self._refresh_titles()
        self.setCurrentIndex(index)
        editor.setFocus()
        self.file_opened.emit(path)
        return editor

    def reload(self, editor: CodeEditor) -> bool:
        """Discard unsaved changes and read the file again (vim's :e!)."""
        info = self._files[editor]
        try:
            source = read_source(info.path)
        except OSError as exc:
            self.status_message.emit(f"Cannot reload {info.path.name}: {exc.strerror or exc}")
            return False
        editor.setPlainText(normalize_eol(source.text))
        editor.document().setModified(False)
        info.encoding, info.eol = source.encoding, detect_eol(source.text)
        if editor.vim is not None:
            editor.vim.engine.reset_undo()
            editor.vim.mark_clean()
            editor.vim.engine.set_cursor(editor.vim.engine.cursor)
            editor.vim.render()
        return True

    def save(self, editor: CodeEditor | None = None) -> bool:
        editor = editor or self.current_editor()
        if editor is None:
            return False
        info = self._files[editor]
        text = editor.toPlainText()
        try:
            write_source(info.path, text, info.encoding, info.eol)
        except UnicodeEncodeError:
            write_source(info.path, text, "utf-8", info.eol)
            self.status_message.emit(f"{info.path.name}: some characters do not fit {info.encoding}; saved as UTF-8")
            info.encoding = "utf-8"
        except OSError as exc:
            self.status_message.emit(f"Save failed for {info.path.name}: {exc.strerror or exc}")
            return False
        editor.document().setModified(False)
        if editor.vim is not None:
            editor.vim.mark_clean()
        self.status_message.emit(f"Saved {info.path.name}")
        self.file_saved.emit(info.path)
        return True

    def save_all(self) -> bool:
        return all([self.save(e) for e in self.editors() if e.document().isModified()])

    def close_tab(self, index: int, *, force: bool = False) -> bool:
        """force=True discards unsaved changes without asking (vim's :q!)."""
        editor = self.widget(index)
        if not isinstance(editor, CodeEditor):
            return False
        info = self._files[editor]
        if editor.document().isModified() and not force:
            choice = self.ask_close(info.path)
            if choice == "cancel" or (choice == "save" and not self.save(editor)):
                return False
        if editor.vim is not None:
            editor.vim.detach()
        self.removeTab(index)
        del self._files[editor]
        editor.deleteLater()
        self._refresh_titles()
        if (current := self.current_editor()) is not None:
            current.setFocus()
        return True

    def close_current(self) -> bool:
        return self.count() > 0 and self.close_tab(self.currentIndex())

    def close_all(self, *, force: bool = False) -> bool:
        """Close every tab, asking about unsaved ones. False if the user cancelled."""
        for index in reversed(range(self.count())):
            if not self.close_tab(index, force=force):
                return False
        return True

    def select_relative(self, delta: int) -> None:
        if self.count():
            self.setCurrentIndex((self.currentIndex() + delta) % self.count())
            self._focus_current()

    def goto_tab(self, number: int) -> None:
        """1-based, like vim's {N}gt."""
        if 1 <= number <= self.count():
            self.setCurrentIndex(number - 1)
            self._focus_current()

    def alternate(self) -> bool:
        """Switch to the previously active tab (vim's <C-^>)."""
        if self._previous is None or self.indexOf(self._previous) < 0:
            return False
        self.setCurrentWidget(self._previous)
        self._focus_current()
        return True

    # -- session -----------------------------------------------------------------

    @property
    def vim_shared(self) -> SharedState:
        return self._vim_shared

    def session_state(self) -> ProjectState:
        tabs = []
        for editor in self.editors():
            pos = QtDocumentBuffer(editor.document()).pos_from(editor.textCursor().position())
            tabs.append(TabState(str(self._files[editor].path), pos.row, pos.col, editor.verticalScrollBar().value()))
        return ProjectState(tuple(tabs), self.currentIndex() if tabs else -1)

    def restore(self, state: ProjectState) -> list[str]:
        """Reopen saved tabs with their cursor and scroll positions. Returns paths that are gone."""
        missing, restored = [], []
        for tab in state.tabs:
            editor = self.open_file(tab.path) if Path(tab.path).is_file() else None
            if editor is None:
                missing.append(tab.path)
                continue
            self._place_cursor(editor, tab)
            restored.append((editor, tab.scroll))
        if state.active_path and (active := self.editor_for(Path(state.active_path))) is not None:
            self.setCurrentWidget(active)
        # Scroll once Qt has laid the documents out; setting it now would be clamped or undone.
        QTimer.singleShot(0, lambda: self._restore_scroll(restored))
        return missing

    def _place_cursor(self, editor: CodeEditor, tab: TabState) -> None:
        row = min(tab.line, editor.blockCount() - 1)
        pos = Pos(row, min(tab.col, len(editor.document().findBlockByNumber(row).text())))
        if editor.vim is not None:
            editor.vim.engine.set_cursor(pos)
            editor.vim.render()
        else:
            cursor = editor.textCursor()
            cursor.setPosition(QtDocumentBuffer(editor.document()).position(pos))
            editor.setTextCursor(cursor)

    def _restore_scroll(self, restored: list[tuple[CodeEditor, int]]) -> None:
        for editor, scroll in restored:
            if self.indexOf(editor) >= 0:
                editor.verticalScrollBar().setValue(scroll)

    def set_vim_mappings(self, mappings: Mappings, host_commands: frozenset[str]) -> None:
        self._vim_shared.mappings = mappings
        self._vim_shared.host_commands = host_commands

    def show_vim_message(self, text: str, *, error: bool = False) -> bool:
        """Show a message on the current editor's vim status line. False if there is none."""
        editor = self.current_editor()
        if editor is None or editor.vim is None:
            return False
        editor.vim.show_message(text, error=error)
        return True

    def _focus_current(self) -> None:
        if (editor := self.current_editor()) is not None:
            editor.setFocus()

    def apply_settings(self, settings: EditorSettings, vim: VimSettings | None = None) -> None:
        self._settings = settings
        vim = vim or self._vim_settings
        self._vim_settings = vim
        self._vim_shared.registers.unnamedplus = vim.clipboard_unnamedplus
        for editor in self.editors():
            editor.apply_settings(settings)
            if vim.enabled and editor.vim is None:
                self._attach_vim(editor)
            elif not vim.enabled and editor.vim is not None:
                editor.vim.detach()
            elif editor.vim is not None:
                options = editor.vim.engine.options
                options.tabstop, options.expandtab, options.autoindent = (
                    settings.tab_width,
                    settings.insert_spaces,
                    settings.auto_indent,
                )
                editor.vim.apply_options()

    # -- vim ---------------------------------------------------------------------

    def _attach_vim(self, editor: CodeEditor) -> None:
        s = self._settings
        options = VimOptions(tabstop=s.tab_width, expandtab=s.insert_spaces, autoindent=s.auto_indent)
        adapter = VimAdapter(editor, self._vim_shared, options)
        adapter.request.connect(lambda req, e=editor: self._on_vim_request(e, req))
        adapter.attach()

    def _on_vim_request(self, editor: CodeEditor, req: HostRequest) -> None:
        info = self._files.get(editor)
        if info is None:
            return
        vim = editor.vim
        modified = editor.document().isModified()
        if req.name == "write" or (req.name == "write_if_modified" and modified):
            if req.arg:
                vim.show_message("E: :w with a file name (save as) is not supported yet", error=True)
            elif self.save(editor):
                data_size = info.path.stat().st_size
                vim.show_message(f'"{info.path.name}" {editor.blockCount()}L, {data_size}B written')
        elif req.name == "write_all":
            self.save_all()
        elif req.name == "quit":
            if editor.document().isModified() and not req.force:
                vim.show_message("E37: No write since last change (add ! to override)", error=True)
            else:
                self.close_tab(self.indexOf(editor), force=True)
        elif req.name == "quit_all":
            self.quit_all_requested.emit(req.force)
        elif req.name == "command":
            self.command_requested.emit(req.arg, req.count)
        elif req.name == "reload":
            self.reload(editor)
        elif req.name == "edit":
            target = Path(req.arg or "")
            if not target.is_absolute():
                target = info.path.parent / target
            if target.is_file():
                self.open_file(target)
            else:
                vim.show_message(f'E: cannot open "{req.arg}": file not found', error=True)

    # -- internals ---------------------------------------------------------------

    def _refresh_titles(self) -> None:
        editors = self.editors()
        names = [self._files[e].path.name for e in editors]
        for index, editor in enumerate(editors):
            path = self._files[editor].path
            title = path.name
            if names.count(path.name) > 1:  # two top.sv files: show the parent folder too
                title = f"{path.name} — {path.parent.name}"
            if editor.document().isModified():
                title += " ●"
            self.setTabText(index, title)

    def _on_current_changed(self, _index: int) -> None:
        editor = self.current_editor()
        if editor is not self._current:
            self._previous, self._current = self._current, editor
        info = self.current_file()
        self.current_file_changed.emit(info.path if info else None)
        if (editor := self.current_editor()) is not None:
            self._emit_cursor(editor)

    def _emit_cursor(self, editor: CodeEditor) -> None:
        if editor is self.current_editor():
            self.cursor_moved.emit(*editor.cursor_line_col())

    def _ask_close_dialog(self, path: Path) -> CloseChoice:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Unsaved changes")
        box.setText(f"Save changes to {path.name}?")
        box.setStandardButtons(
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QMessageBox.StandardButton.Save)  # Enter
        box.setEscapeButton(QMessageBox.StandardButton.Cancel)  # Esc
        result = box.exec()
        if result == QMessageBox.StandardButton.Save:
            return "save"
        if result == QMessageBox.StandardButton.Discard:
            return "discard"
        return "cancel"
