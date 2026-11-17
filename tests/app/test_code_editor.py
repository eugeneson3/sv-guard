import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor

from app.editor.code_editor import CodeEditor
from app.settings import EditorSettings


@pytest.fixture
def make_editor(qtbot):
    def make(text: str = "", **settings) -> CodeEditor:
        editor = CodeEditor(EditorSettings(**settings))
        qtbot.addWidget(editor)
        editor.setPlainText(text)
        return editor

    return make


def _move(editor: CodeEditor, line: int, col: int) -> None:
    block = editor.document().findBlockByNumber(line)
    cursor = editor.textCursor()
    cursor.setPosition(block.position() + col)
    editor.setTextCursor(cursor)


def _select_lines(editor: CodeEditor, first: int, last: int) -> None:
    doc = editor.document()
    cursor = editor.textCursor()
    cursor.setPosition(doc.findBlockByNumber(first).position())
    cursor.setPosition(doc.findBlockByNumber(last).position() + 1, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)


def test_tab_inserts_spaces_to_next_tab_stop(qtbot, make_editor):
    editor = make_editor("ab")
    _move(editor, 0, 2)
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.toPlainText() == "ab  "
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.toPlainText() == "ab      "


def test_tab_width_setting(qtbot, make_editor):
    editor = make_editor("", tab_width=2)
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.toPlainText() == "  "


def test_tab_character_when_insert_spaces_is_off(qtbot, make_editor):
    editor = make_editor("", insert_spaces=False)
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.toPlainText() == "\t"


def test_tab_and_shift_tab_on_selection_shift_lines(qtbot, make_editor):
    editor = make_editor("a\n\nb\nc")
    _select_lines(editor, 0, 2)  # lines a, (empty), b
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.toPlainText() == "    a\n\n    b\nc"  # empty line stays empty
    qtbot.keyClick(editor, Qt.Key.Key_Backtab)
    assert editor.toPlainText() == "a\n\nb\nc"


def test_selection_ending_at_column_zero_excludes_that_line(qtbot, make_editor):
    editor = make_editor("a\nb\nc")
    cursor = editor.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(editor.document().findBlockByNumber(1).position(), QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.toPlainText() == "    a\nb\nc"


def test_shift_lines_is_one_undo_step(qtbot, make_editor):
    editor = make_editor("a\nb\nc")
    _select_lines(editor, 0, 2)
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    editor.undo()
    assert editor.toPlainText() == "a\nb\nc"


def test_backspace_removes_one_indent_level(qtbot, make_editor):
    editor = make_editor("      x")  # 6 spaces
    _move(editor, 0, 6)
    qtbot.keyClick(editor, Qt.Key.Key_Backspace)
    assert editor.toPlainText() == "    x"  # back to the tab stop at 4
    qtbot.keyClick(editor, Qt.Key.Key_Backspace)
    assert editor.toPlainText() == "x"


def test_backspace_after_text_is_normal(qtbot, make_editor):
    editor = make_editor("    ab")
    _move(editor, 0, 6)
    qtbot.keyClick(editor, Qt.Key.Key_Backspace)
    assert editor.toPlainText() == "    a"


def test_enter_keeps_indentation(qtbot, make_editor):
    editor = make_editor("    always_ff begin")
    _move(editor, 0, len("    always_ff begin"))
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    qtbot.keyClicks(editor, "x")
    assert editor.toPlainText() == "    always_ff begin\n    x"


def test_shift_enter_inserts_a_real_newline(qtbot, make_editor):
    editor = make_editor("a")
    _move(editor, 0, 1)
    qtbot.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert editor.blockCount() == 2


def test_auto_indent_off(qtbot, make_editor):
    editor = make_editor("    a", auto_indent=False)
    _move(editor, 0, 5)
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert editor.toPlainText() == "    a\n"


def test_key_handler_can_consume_keys(qtbot, make_editor):
    editor = make_editor("")
    seen = []
    editor.key_handler = lambda event: seen.append(event.text()) or event.text() == "j"
    qtbot.keyClicks(editor, "jk")
    assert seen == ["j", "k"]
    assert editor.toPlainText() == "k"


def test_cursor_line_col_is_one_based(make_editor):
    editor = make_editor("ab\n한글x")
    _move(editor, 1, 2)
    assert editor.cursor_line_col() == (2, 3)


def test_line_number_area_grows_with_digits(make_editor):
    editor = make_editor("x")
    narrow = editor.line_number_area_width()
    editor.setPlainText("\n" * 12000)
    assert editor.line_number_area_width() > narrow


def test_apply_settings_updates_tab_stop(make_editor):
    editor = make_editor("")
    before = editor.tabStopDistance()
    editor.apply_settings(EditorSettings(tab_width=8))
    assert editor.tabStopDistance() == pytest.approx(before * 2)
    assert editor.indent_unit == " " * 8
