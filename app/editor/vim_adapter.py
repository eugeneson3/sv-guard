"""Connects a CodeEditor to a vimcore.VimEngine.

Qt side of the design agreed in Step 0:
  * QTextDocument stays the single source of truth; the engine edits it through
    QtDocumentBuffer, and the document's own undo stack is switched off (vimcore owns undo).
  * Keys, IME commits, pastes and mouse moves go to the engine; the adapter then renders
    the result: Qt cursor, block/thin cursor shape, Visual selection, status line.
  * The IME is enabled only in Insert and command-line mode, so Normal-mode keys arrive as
    Latin letters even while a Hangul layout is active. Hangul that still slips through is
    mapped back to QWERTY keys (vimcore.hangul).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QInputMethodEvent, QKeyEvent, QPalette, QTextCursor, QTextFormat
from PySide6.QtWidgets import QTextEdit

from app.editor.code_editor import CodeEditor
from app.editor.qt_buffer import QtDocumentBuffer
from vimcore import HostRequest, Message, Mode, Pos, SharedState, VimEngine, VimOptions
from svguard.model import Severity
from vimcore.hangul import is_hangul, to_qwerty

_SPECIAL_KEYS = {
    Qt.Key.Key_Escape: "<Esc>",
    Qt.Key.Key_Return: "<CR>",
    Qt.Key.Key_Enter: "<CR>",
    Qt.Key.Key_Backspace: "<BS>",
    Qt.Key.Key_Delete: "<Del>",
    Qt.Key.Key_Tab: "<Tab>",
    Qt.Key.Key_Backtab: "<S-Tab>",
    Qt.Key.Key_Left: "<Left>",
    Qt.Key.Key_Right: "<Right>",
    Qt.Key.Key_Up: "<Up>",
    Qt.Key.Key_Down: "<Down>",
    Qt.Key.Key_Home: "<Home>",
    Qt.Key.Key_End: "<End>",
    Qt.Key.Key_PageUp: "<PageUp>",
    Qt.Key.Key_PageDown: "<PageDown>",
    Qt.Key.Key_Insert: "<Insert>",
}
_MODIFIER_ONLY = {
    Qt.Key.Key_Shift,
    Qt.Key.Key_Control,
    Qt.Key.Key_Alt,
    Qt.Key.Key_Meta,
    Qt.Key.Key_AltGr,
    Qt.Key.Key_CapsLock,
    Qt.Key.Key_NumLock,
    Qt.Key.Key_ScrollLock,
    Qt.Key.Key_Hangul,
    Qt.Key.Key_Hangul_Hanja,
}
_LETTERS = range(Qt.Key.Key_A.value, Qt.Key.Key_Z.value + 1)


def vim_key(key: int, text: str, modifiers: Qt.KeyboardModifier) -> str | None:
    """Translate a Qt key press into a vim key token, or None if vim has no use for it."""
    key = Qt.Key(key) if not isinstance(key, Qt.Key) else key
    if key in _MODIFIER_ONLY:
        return None
    ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
    alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
    shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
    if key in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[key]
    if ctrl and not alt:
        if key.value in _LETTERS:
            return f"<C-{'S-' if shift else ''}{chr(key.value).lower()}>"
        if key == Qt.Key.Key_BracketLeft:
            return "<Esc>"
        if key in (Qt.Key.Key_AsciiCircum, Qt.Key.Key_6):
            return "<C-^>"
        return None
    if alt and not ctrl:
        return None  # Alt+letter belongs to menu mnemonics
    if text and text.isprintable():
        if is_hangul(text) and key.value in _LETTERS:
            # A Hangul IME is still active: the physical key is what vim wants.
            return chr(key.value) if shift else chr(key.value).lower()
        return text
    if key.value in _LETTERS:  # the IME swallowed the text; fall back to the physical key
        return chr(key.value) if shift else chr(key.value).lower()
    return None


class QtClipboard:
    def get(self) -> str:
        return QGuiApplication.clipboard().text()

    def set(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)


class VimAdapter(QObject):
    request = Signal(object)  # HostRequest the editor cannot handle itself (write, quit, edit...)

    def __init__(self, editor: CodeEditor, shared: SharedState, options: VimOptions) -> None:
        super().__init__(editor)
        self.editor = editor
        self.buffer = QtDocumentBuffer(editor.document())
        self.engine = VimEngine(self.buffer, options=options, shared=shared)
        self._message: Message | None = None
        self._preedit = ""
        self._busy = False  # the engine is editing or rendering: ignore Qt cursor signals
        self._attached = False
        self._clean_state = self.engine.undo_state  # undo position that matches the file on disk
        self._discarded_preedit = ""
        self._timeout = QTimer(self)  # 'timeoutlen' for keys that may grow into a longer mapping
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(lambda: self._run(self.engine.timeout))

    # -- lifecycle ---------------------------------------------------------------------

    def attach(self) -> None:
        editor = self.editor
        editor.document().setUndoRedoEnabled(False)  # vimcore owns undo
        editor.key_handler = self.handle_key
        editor.vim = self
        editor.setAcceptDrops(False)  # a drag-move would edit the document behind vimcore's back
        editor.cursorPositionChanged.connect(self._on_cursor_changed)
        editor.diagnostics.changed.connect(self._render_status)
        editor.viewport().installEventFilter(self)
        editor.set_statusline_visible(True)
        editor.set_tab_width(self.engine.options.tabstop)
        self.engine.set_cursor(self.buffer.pos_from(editor.textCursor().position()))
        self._attached = True
        self.render()

    def detach(self) -> None:
        if not self._attached:
            return
        editor = self.editor
        editor.cursorPositionChanged.disconnect(self._on_cursor_changed)
        editor.diagnostics.changed.disconnect(self._render_status)
        editor.viewport().removeEventFilter(self)
        editor.key_handler = None
        editor.vim = None
        editor.setAcceptDrops(True)
        editor.document().setUndoRedoEnabled(True)
        editor.setOverwriteMode(False)
        editor.setCursorWidth(1)
        editor.set_extra_layer("visual", [])
        editor.set_statusline_visible(False)
        editor.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self._attached = False

    # -- input ---------------------------------------------------------------------------

    def handle_key(self, event: QKeyEvent) -> bool:
        mode = self.engine.mode
        key = vim_key(event.key(), event.text(), event.modifiers())
        if key is None:
            # Never let Qt edit text behind the engine's back in Normal/Visual mode.
            return not mode.accepts_text
        if key == "<Esc>" and mode.accepts_text:
            QGuiApplication.inputMethod().commit()  # keep a half-composed syllable, as vim does
        self._run(lambda: self.engine.feed(key))
        return True

    def handle_input_method(self, event: QInputMethodEvent) -> QInputMethodEvent | None:
        """Returns the event Qt should still process (preedit display only), or None."""
        mode = self.engine.mode
        commit = event.commitString()
        if mode is Mode.INSERT:
            if commit:
                self._run(lambda: self.engine.insert_text(commit))
            return QInputMethodEvent(event.preeditString(), event.attributes())
        if mode is Mode.COMMAND:
            if commit:
                self._run(lambda: self.engine.insert_text(commit))
            self._preedit = event.preeditString()
            self.render()
            return None
        # Normal/Visual: the IME should be off, but some input methods compose anyway.
        # Act on the key as soon as composition starts instead of waiting for the next
        # key to commit the syllable (which made every command lag one key behind).
        preedit = event.preeditString()
        if commit and commit == self._discarded_preedit:
            commit = ""  # the composition we already handled and cancelled
        self._discarded_preedit = ""
        text = commit + preedit
        if preedit:
            self._discarded_preedit = preedit
            QGuiApplication.inputMethod().reset()
        keys = to_qwerty(text) if text else None
        for key in keys or "":
            self._run(lambda k=key: self.engine.feed(k))
        return None

    def handle_paste(self, text: str) -> None:
        self._run(lambda: self.engine.paste_text(text))

    def copy_selection(self) -> None:
        self._run(lambda: self.engine.feed("<C-c>"))  # Visual <C-c>: yank to "+

    def paste_clipboard(self) -> None:
        self.handle_paste(QtClipboard().get())

    def show_message(self, text: str, *, error: bool = False) -> None:
        self._message = Message(text, error)
        self.render()

    def apply_options(self) -> None:
        self.editor.set_tab_width(self.engine.options.tabstop)

    def mark_clean(self) -> None:
        """The file was saved or reloaded: undoing back to here means "unmodified"."""
        self._clean_state = self.engine.undo_state

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.MouseButtonRelease:
            self.render()  # a drag selection is rendered once the button is released
        return False

    # -- engine round trip -----------------------------------------------------------------

    def _run(self, action) -> None:
        engine = self.engine
        engine.options.page = max(1, self.editor.viewport().height() // max(1, self.editor.fontMetrics().height()))
        mode_before = engine.mode
        self._timeout.stop()
        doc = self.editor.document()
        was_modified, version = doc.isModified(), self.buffer.version
        batch = QTextCursor(doc)
        busy, self._busy = self._busy, True  # edits shift Qt's cursor; that is not a mouse move
        batch.beginEditBlock()  # one relayout/rehighlight per key
        try:
            result = action()
        finally:
            batch.endEditBlock()
            self._busy = busy
        if engine.undo_state is self._clean_state and not engine.change_in_progress:
            doc.setModified(False)  # undone back to the saved text, as in vim
        elif self.buffer.version == version:
            doc.setModified(was_modified)  # with undo off, Qt flags even an empty edit block as a change
        if result.message is not None:
            self._message = result.message
        elif result.mode is not mode_before:
            self._message = None
        if result.mode is not Mode.COMMAND:
            self._preedit = ""
        if engine.awaiting_timeout:
            self._timeout.start(engine.shared.mappings.timeoutlen)
        for req in result.requests:
            self._handle_request(req)
            if not self._attached:
                return  # :q closed this editor
        self.render()

    def _handle_request(self, req: HostRequest) -> None:
        if req.name == "scroll":
            bar = self.editor.verticalScrollBar()
            bar.setValue(bar.value() + int(req.arg or 0))
        elif req.name == "options":
            self.apply_options()
        else:
            self.request.emit(req)

    def _on_cursor_changed(self) -> None:
        """The cursor moved without the engine: a mouse click or drag."""
        if self._busy:
            return
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            anchor = self.buffer.pos_from(cursor.anchor())
            pos = self.buffer.pos_from(cursor.position())
            if pos > anchor and pos.col > 0:
                pos = Pos(pos.row, pos.col - 1)  # Qt's selection end is exclusive; vim's cursor is on the last char
            self.engine.set_visual(anchor, pos)
        else:
            self.engine.set_cursor(self.buffer.pos_from(cursor.position()))
        if QGuiApplication.mouseButtons() == Qt.MouseButton.NoButton:
            self.render()
        else:
            self._render_status()  # keep Qt's drag anchor intact until the button is released

    # -- rendering ---------------------------------------------------------------------------

    def render(self) -> None:
        engine, editor = self.engine, self.editor
        busy, self._busy = self._busy, True
        try:
            cursor = editor.textCursor()
            cursor.setPosition(self.buffer.position(engine.cursor))
            editor.setTextCursor(cursor)
            block = engine.mode.block_cursor
            editor.setOverwriteMode(block)  # QPlainTextEdit draws a block cursor in overwrite mode
            editor.setCursorWidth(max(2, editor.fontMetrics().horizontalAdvance(" ")) if block else 2)
            editor.set_extra_layer("visual", self._visual_selections())
            self._sync_input_method()
            editor.ensureCursorVisible()
        finally:
            self._busy = busy
        self._render_status()

    def _render_status(self) -> None:
        engine, editor = self.engine, self.editor
        counts = editor.diagnostics.counts()
        finding = editor.finding_at_cursor()
        hint = f"{finding.severity.value}: {finding.message}" if finding is not None else ""
        editor.statusline.set_state(
            mode=engine.mode,
            pending=engine.pending,
            message=self._message,
            cmdline=engine.cmdline,
            preedit=self._preedit,
            hint=hint,
            counts=(counts[Severity.ERROR], counts[Severity.WARNING]),
            stale=editor.diagnostics.stale,
        )

    def _visual_selections(self) -> list[QTextEdit.ExtraSelection]:
        selection = self.engine.selection
        if selection is None:
            return []
        extra = QTextEdit.ExtraSelection()
        color = QColor(self.editor.palette().color(QPalette.ColorRole.Highlight))
        color.setAlpha(110)
        extra.format.setBackground(color)
        extra.cursor = QTextCursor(self.editor.document())
        extra.cursor.setPosition(self.buffer.position(selection.start))
        end = selection.end
        if end.row >= self.buffer.line_count():
            end = Pos(self.buffer.line_count() - 1, len(self.buffer.line(self.buffer.line_count() - 1)))
        extra.cursor.setPosition(self.buffer.position(end), QTextCursor.MoveMode.KeepAnchor)
        if selection.linewise:
            extra.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        return [extra]

    def _sync_input_method(self) -> None:
        enabled = self.engine.mode.accepts_text
        if self.editor.testAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled) != enabled:
            self.editor.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, enabled)
            QGuiApplication.inputMethod().update(Qt.InputMethodQuery.ImEnabled)
