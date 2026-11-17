from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QMimeData, Qt
from PySide6.QtGui import QInputMethodEvent, QKeyEvent, QTextDocument
from PySide6.QtWidgets import QApplication

from app.editor.editor_tabs import EditorTabs
from app.editor.vim_adapter import QtDocumentBuffer, vim_key
from app.settings import EditorSettings, VimSettings
from vimcore import Mode, Pos

NO = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
ALT = Qt.KeyboardModifier.AltModifier


@pytest.mark.parametrize(
    ("key", "text", "mods", "expected"),
    [
        (Qt.Key.Key_J, "j", NO, "j"),
        (Qt.Key.Key_J, "J", SHIFT, "J"),
        (Qt.Key.Key_J, "ㅓ", NO, "j"),  # Hangul IME still on: use the physical key
        (Qt.Key.Key_R, "ㄲ", SHIFT, "R"),
        (Qt.Key.Key_J, "", NO, "j"),  # text swallowed by an IME
        (Qt.Key.Key_Dollar, "$", SHIFT, "$"),
        (Qt.Key.Key_Space, " ", NO, " "),
        (Qt.Key.Key_R, "\x12", CTRL, "<C-r>"),
        (Qt.Key.Key_V, "\x16", CTRL | SHIFT, "<C-S-v>"),
        (Qt.Key.Key_BracketLeft, "\x1b", CTRL, "<Esc>"),
        (Qt.Key.Key_Escape, "\x1b", NO, "<Esc>"),
        (Qt.Key.Key_Return, "\r", NO, "<CR>"),
        (Qt.Key.Key_Backtab, "", SHIFT, "<S-Tab>"),
        (Qt.Key.Key_Shift, "", SHIFT, None),
        (Qt.Key.Key_Hangul, "", NO, None),
        (Qt.Key.Key_F, "f", ALT, None),  # menu mnemonic
        (Qt.Key.Key_F5, "", NO, None),
        (Qt.Key.Key_1, "1", CTRL, None),
    ],
)
def test_vim_key_translation(key, text, mods, expected):
    assert vim_key(key, text, mods) == expected


def test_document_buffer_converts_utf16_positions(qapp):
    doc = QTextDocument()
    doc.setPlainText("a\U0001f600b\n한글")
    buffer = QtDocumentBuffer(doc)
    assert buffer.position(Pos(0, 2)) == 3  # the emoji takes two UTF-16 units
    assert buffer.pos_from(3) == Pos(0, 2)
    buffer.replace(Pos(0, 2), Pos(1, 1), "X")
    assert doc.toPlainText() == "a\U0001f600X글"
    assert buffer.version == 1


@pytest.fixture
def tabs(qtbot):
    widget = EditorTabs(EditorSettings(), VimSettings())
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


@pytest.fixture
def editor(tabs, tmp_path):
    path = tmp_path / "top.sv"
    path.write_bytes(b"module top;\n  logic a;\nendmodule\n")
    return tabs.open_file(path)


def _keys(qtbot, widget, keys: str) -> None:
    for ch in keys:
        qtbot.keyClick(widget, ch)


def _press(widget, key, text="", mods=NO) -> None:
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, key, mods, text))


def test_normal_mode_editing_and_undo(qtbot, editor):
    _keys(qtbot, editor, "jdd")
    assert editor.toPlainText() == "module top;\nendmodule\n"
    assert editor.document().isModified()
    _keys(qtbot, editor, "u")
    assert editor.toPlainText() == "module top;\n  logic a;\nendmodule\n"
    assert not editor.document().isUndoRedoEnabled()  # vimcore owns undo


def test_motions_do_not_mark_the_file_modified(qtbot, editor):
    _keys(qtbot, editor, "jwl")
    assert not editor.document().isModified()


def test_undo_back_to_saved_text_clears_modified(qtbot, tabs, editor):
    _keys(qtbot, editor, "x")
    assert editor.document().isModified()
    _keys(qtbot, editor, "u")
    assert not editor.document().isModified()
    _keys(qtbot, editor, "x")
    tabs.save(editor)
    _keys(qtbot, editor, "u")
    assert editor.document().isModified()  # the saved file has the x applied
    editor.vim._run(lambda: editor.vim.engine.feed("<C-r>"))
    assert not editor.document().isModified()


def test_modes_cursor_shape_ime_and_statusline(qtbot, editor):
    assert editor.vim.engine.mode is Mode.NORMAL
    assert editor.overwriteMode()  # block cursor
    assert not editor.testAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
    assert editor.statusline.isVisible() and editor.statusline.text().startswith("NORMAL")

    _keys(qtbot, editor, "i")
    assert not editor.overwriteMode()
    assert editor.testAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
    assert editor.statusline.text().startswith("INSERT")

    _press(editor, Qt.Key.Key_Escape, "\x1b")
    assert editor.vim.engine.mode is Mode.NORMAL


def test_ime_commit_in_insert_mode_is_one_undo_step(qtbot, editor):
    _keys(qtbot, editor, "i")
    event = QInputMethodEvent("", [])
    event.setCommitString("한글")
    QApplication.sendEvent(editor, event)
    _press(editor, Qt.Key.Key_Escape, "\x1b")
    assert editor.toPlainText().startswith("한글module")
    _keys(qtbot, editor, "u")
    assert editor.toPlainText().startswith("module")


def _ime_query(widget) -> bool:
    from PySide6.QtGui import QInputMethodQueryEvent

    event = QInputMethodQueryEvent(Qt.InputMethodQuery.ImEnabled)
    QApplication.sendEvent(widget, event)
    return event.value(Qt.InputMethodQuery.ImEnabled)


def test_platform_ime_is_told_to_switch_off_in_normal_mode(qtbot, editor):
    # The OS input method asks this query; QPlainTextEdit alone always answers True.
    assert _ime_query(editor) is False
    _keys(qtbot, editor, "i")
    assert _ime_query(editor) is True
    _press(editor, Qt.Key.Key_Escape, "\x1b")
    assert _ime_query(editor) is False
    _keys(qtbot, editor, ":")
    assert _ime_query(editor) is True


def test_composition_in_normal_mode_acts_immediately(editor):
    """An IME that composes anyway: 'dd' must not wait for a third key to commit."""
    for _ in range(2):
        QApplication.sendEvent(editor, QInputMethodEvent("ㅇ", []))  # 'd' starts a syllable
    assert editor.toPlainText() == "  logic a;\nendmodule\n"
    late_commit = QInputMethodEvent("", [])
    late_commit.setCommitString("ㅇ")  # the IME commits what we already cancelled
    QApplication.sendEvent(editor, late_commit)
    assert editor.vim.engine.pending == ""


def test_hangul_in_normal_mode_still_works_as_vim_keys(editor):
    _press(editor, Qt.Key.Key_J, "ㅓ")  # j typed with the Korean layout
    assert editor.vim.engine.cursor.row == 1
    event = QInputMethodEvent("", [])
    event.setCommitString("ㅏ")  # k committed by an IME that ignored the disabled state
    QApplication.sendEvent(editor, event)
    assert editor.vim.engine.cursor.row == 0


def test_pending_keys_and_unsupported_keys_on_statusline(qtbot, editor):
    _keys(qtbot, editor, '"a2')
    assert editor.statusline.text().endswith('"a2')
    _press(editor, Qt.Key.Key_Escape, "\x1b")
    _keys(qtbot, editor, "q")
    assert "Unsupported key: q" in editor.statusline.text()


def test_colon_w_saves_and_reports(qtbot, tabs, editor, tmp_path):
    _keys(qtbot, editor, "x:w")
    _press(editor, Qt.Key.Key_Return, "\r")
    assert (tmp_path / "top.sv").read_bytes().startswith(b"odule top;")
    assert '"top.sv" 4L' in editor.statusline.text()


def test_colon_q_refuses_unsaved_and_q_bang_discards(qtbot, tabs, editor):
    _keys(qtbot, editor, "x:q")
    _press(editor, Qt.Key.Key_Return, "\r")
    assert tabs.count() == 1
    assert "E37" in editor.statusline.text()
    _keys(qtbot, editor, ":q!")
    _press(editor, Qt.Key.Key_Return, "\r")
    assert tabs.count() == 0


def test_visual_selection_is_drawn(qtbot, editor):
    _keys(qtbot, editor, "vl")
    selections = [s for s in editor.extraSelections() if s.cursor.hasSelection()]
    assert [s.cursor.selectedText() for s in selections] == ["mo"]
    _press(editor, Qt.Key.Key_Escape, "\x1b")
    assert not [s for s in editor.extraSelections() if s.cursor.hasSelection()]


def test_mouse_click_moves_the_engine_cursor(editor):
    cursor = editor.textCursor()
    cursor.setPosition(editor.document().findBlockByNumber(1).position() + 4)
    editor.setTextCursor(cursor)  # what a click does
    assert editor.vim.engine.cursor == Pos(1, 4)


def test_paste_goes_through_the_engine(qtbot, editor):
    data = QMimeData()
    data.setText("XY")
    editor.insertFromMimeData(data)
    assert editor.toPlainText().startswith("XYmodule")
    _keys(qtbot, editor, "u")
    assert editor.toPlainText().startswith("module")


def test_set_tabstop_changes_tab_drawing(qtbot, editor):
    before = editor.tabStopDistance()
    _keys(qtbot, editor, ":set ts=8")
    _press(editor, Qt.Key.Key_Return, "\r")
    assert editor.tabStopDistance() == pytest.approx(before * 2)


def test_disabling_vim_restores_a_plain_editor(qtbot, tabs, editor):
    tabs.apply_settings(EditorSettings(), VimSettings(enabled=False))
    assert editor.vim is None and editor.key_handler is None
    assert not editor.statusline.isVisible()
    assert editor.document().isUndoRedoEnabled()
    _keys(qtbot, editor, "dd")
    assert editor.toPlainText().startswith("ddmodule")
    tabs.apply_settings(EditorSettings(), VimSettings(enabled=True))
    assert editor.vim is not None


def test_registers_are_shared_between_tabs(qtbot, tabs, editor, tmp_path):
    _keys(qtbot, editor, "yy")
    other_path = tmp_path / "other.sv"
    other_path.write_bytes(b"x\n")
    other = tabs.open_file(other_path)
    _keys(qtbot, other, "p")
    assert other.toPlainText() == "x\nmodule top;\n"


def test_ctrl_z_is_reported_not_silently_ignored(editor):
    _press(editor, Qt.Key.Key_Z, "\x1a", CTRL)
    assert "Unsupported key: <C-z>" in editor.statusline.text()


def test_settings_file_without_vim_section_keeps_vim_on(tmp_path: Path):
    from app.settings import parse_settings

    settings, warnings = parse_settings("editor:\n  tab_width: 2\n")
    assert settings.vim.enabled and warnings == []
