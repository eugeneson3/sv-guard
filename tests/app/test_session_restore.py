"""Step 3: close the IDE, start it again, and find everything where it was."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from app.main_window import MainWindow
from vimcore import Pos


@pytest.fixture
def new_window(qtbot):
    """Start an IDE the way main.py does (each call is a new 'launch')."""

    def launch(path=None, *, show=True) -> MainWindow:
        window = MainWindow()
        qtbot.addWidget(window)
        window.restore_layout()
        if show:
            window.show()
            qtbot.waitExposed(window)
            window.activateWindow()
        window.restore_workspace(path)
        return window

    return launch


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "rtl").mkdir(parents=True)
    (root / "top.sv").write_bytes(b"module top;\n  logic a;\nendmodule\n")
    (root / "rtl" / "alu.sv").write_bytes(b"module alu;\nendmodule\n")
    (root / "long.sv").write_bytes("".join(f"// line {i}\n" for i in range(300)).encode())
    return root


def _keys(qtbot, widget, keys: str) -> None:
    for ch in keys:
        qtbot.keyClick(widget, ch)


def _open_paths(window: MainWindow) -> list[str]:
    return [p.name for p in window.tabs.open_paths()]


def test_folder_tabs_active_tab_and_cursors_come_back(qtbot, new_window, project):
    first = new_window()
    first.open_project(project)
    top = first.tabs.open_file(project / "top.sv")
    alu = first.tabs.open_file(project / "rtl" / "alu.sv")
    _keys(qtbot, alu, "j")
    first.tabs.setCurrentWidget(top)
    _keys(qtbot, top, "jw")  # line 2, on "logic"
    first.close()

    second = new_window()
    assert second.project_root == project.resolve()
    assert _open_paths(second) == ["top.sv", "alu.sv"]
    assert second.tabs.current_file().path.name == "top.sv"
    assert second.tabs.current_editor().vim.engine.cursor == Pos(1, 2)
    assert second.tabs.editor_for(project / "rtl" / "alu.sv").vim.engine.cursor == Pos(1, 0)
    assert second.focusWidget() is second.tabs.current_editor()  # typing goes straight to it


def test_scroll_position_comes_back(qtbot, new_window, project):
    first = new_window()
    first.open_project(project)
    editor = first.tabs.open_file(project / "long.sv")
    _keys(qtbot, editor, "200G")
    scroll = editor.verticalScrollBar().value()
    assert scroll > 100
    first.close()

    second = new_window()
    restored = second.tabs.current_editor()
    qtbot.waitUntil(lambda: restored.verticalScrollBar().value() == scroll, timeout=2000)
    assert restored.vim.engine.cursor.row == 199


def test_deleted_files_are_skipped_with_a_message(new_window, project):
    first = new_window()
    first.open_project(project)
    first.tabs.open_file(project / "top.sv")
    first.tabs.open_file(project / "rtl" / "alu.sv")
    first.close()
    (project / "rtl" / "alu.sv").unlink()

    second = new_window()
    assert _open_paths(second) == ["top.sv"]
    assert "1 file(s) from the last session no longer exist" in second.statusBar().currentMessage()


def test_each_folder_keeps_its_own_tabs(new_window, project, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "tb.sv").write_bytes(b"module tb;\nendmodule\n")

    window = new_window()
    window.open_project(project)
    window.tabs.open_file(project / "top.sv")
    window.open_project(other)  # saves proj's tabs, closes them
    assert _open_paths(window) == []
    window.tabs.open_file(other / "tb.sv")
    window.open_project(project)
    assert _open_paths(window) == ["top.sv"]
    window.open_project(other)
    assert _open_paths(window) == ["tb.sv"]


def test_switching_folders_can_be_cancelled_on_unsaved_changes(new_window, project, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    window = new_window()
    window.open_project(project)
    window.tabs.open_file(project / "top.sv").insertPlainText("x")
    window.tabs.ask_close = lambda path: "cancel"
    assert window.open_project(other) is False
    assert window.project_root == project.resolve()
    window.tabs.ask_close = lambda path: "discard"


def test_window_size_and_hidden_explorer_come_back(qtbot, new_window, project):
    first = new_window()
    first.open_project(project)
    first.resize(760, 520)  # must fit the 800x600 offscreen screen, or Qt shrinks it on restore
    first.run_command("view.toggleExplorer")
    assert not first.explorer_dock.isVisible()
    first.close()

    second = new_window()
    assert (second.width(), second.height()) == (760, 520)
    assert not second.explorer_dock.isVisible()  # reopening the folder must not force it back


def test_vim_registers_and_history_survive_a_restart(qtbot, new_window, project):
    first = new_window()
    first.open_project(project)
    editor = first.tabs.open_file(project / "top.sv")
    _keys(qtbot, editor, '"ayy')
    _keys(qtbot, editor, "/endmodule")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    first.close()

    second = new_window()
    restored = second.tabs.current_editor()
    _keys(qtbot, restored, 'gg"ap')
    assert restored.toPlainText().startswith("module top;\nmodule top;\n")
    _keys(qtbot, restored, "n")  # the last search came back too
    assert restored.vim.engine.cursor.row == 3


def test_settings_can_turn_restoring_off(new_window, project):
    first = new_window()
    first.open_project(project)
    first.tabs.open_file(project / "top.sv")
    first.close()
    first.settings_path.write_text("session:\n  restore_tabs: false\n", encoding="utf-8")

    second = new_window()
    assert second.project_root == project.resolve()  # the folder still comes back
    assert _open_paths(second) == []


def test_qa_bang_remembers_tabs_before_discarding(qtbot, new_window, project):
    first = new_window()
    first.open_project(project)
    editor = first.tabs.open_file(project / "top.sv")
    _keys(qtbot, editor, "x:qa!")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert not first.isVisible()
    assert (project / "top.sv").read_bytes().startswith(b"module")  # change discarded

    second = new_window()
    assert _open_paths(second) == ["top.sv"]


def test_session_is_autosaved_while_working(qtbot, new_window, project):
    first = new_window()
    first.open_project(project)
    first.tabs.open_file(project / "top.sv")
    qtbot.waitUntil(lambda: first.session.path.exists() and "top.sv" in first.session.path.read_text("utf-8"), timeout=4000)


def test_command_line_path_wins_over_the_last_folder(new_window, project, tmp_path):
    first = new_window()
    first.open_project(project)
    first.close()
    other = tmp_path / "other"
    other.mkdir()
    (other / "tb.sv").write_bytes(b"module tb;\nendmodule\n")

    second = new_window(other / "tb.sv")
    assert second.project_root == other.resolve()
    assert _open_paths(second) == ["tb.sv"]
