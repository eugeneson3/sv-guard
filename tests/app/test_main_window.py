from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow, project_files
from app.services.session_service import SessionService
from app.settings import default_settings_path

CTRL = Qt.KeyboardModifier.ControlModifier


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win.activateWindow()
    win.picked = []  # (placeholder, labels) of every picker that was opened

    def chooser(items, placeholder):
        win.picked.append((placeholder, [i.label for i in items]))
        return win.pick(items) if hasattr(win, "pick") else None

    win.chooser = chooser
    return win


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "rtl").mkdir(parents=True)
    (root / ".venv").mkdir()
    (root / "top.sv").write_bytes(b"module top;\nendmodule\n")  # write_text would emit CRLF on Windows
    (root / "rtl" / "alu.sv").write_bytes(b"module alu;\nendmodule\n")
    (root / ".venv" / "junk.py").write_bytes(b"")
    return root


def _keys(qtbot, widget, keys: str) -> None:
    for ch in keys:
        qtbot.keyClick(widget, ch)


def _ctrl_w(qtbot, widget, key) -> None:
    qtbot.keyClick(widget, Qt.Key.Key_W, CTRL)
    qtbot.keyClick(widget, key)


def test_keyboard_shortcuts_are_registered(window):
    expected = {
        "file.openProject": "Ctrl+Shift+O",
        "file.find": "Ctrl+P",
        "file.save": "Ctrl+S",
        "file.saveAll": "Ctrl+Shift+S",
        "file.close": "Ctrl+F4",
        "settings.open": "Ctrl+,",
        "app.quit": "Ctrl+Q",
        "palette.show": "Ctrl+Shift+P",
        "view.focusExplorer": "Ctrl+Shift+E",
        "view.focusEditor": "Ctrl+1",
        "tab.next": "Ctrl+Tab",
        "tab.previous": "Ctrl+Shift+Tab",
    }
    actual = {name: window.actions[name].shortcut().toString() for name in expected}
    assert actual == expected


def test_every_menu_command_is_in_the_registry(window):
    assert set(window.actions) <= window.registry.ids()


def test_open_project_and_file_updates_title_and_status(window, project):
    window.open_project(project)
    window.open_file(project / "top.sv")
    assert window.windowTitle() == f"top.sv — {project.name} — SV-Guard"
    assert window._indent_label.text() == "Spaces: 4"
    assert window._encoding_label.text() == "UTF-8"
    assert window._eol_label.text() == "LF"
    assert window._position_label.text() == "Ln 1, Col 1"


def test_ctrl_s_saves_the_current_file(qtbot, window, project):
    window.open_project(project)
    window.open_file(project / "top.sv")
    editor = window.tabs.current_editor()
    qtbot.keyClicks(editor, "O// hi")  # vim: open a line above, type; never put "\n" in keyClicks
    qtbot.keyClick(editor, Qt.Key.Key_Escape)
    qtbot.keyClick(editor, Qt.Key.Key_S, CTRL)
    assert (project / "top.sv").read_text(encoding="utf-8").startswith("// hi\n")


def test_focus_explorer_and_escape_back(qtbot, window, project):
    window.open_project(project)
    window.open_file(project / "top.sv")
    window.run_command("view.focusExplorer")
    assert window.explorer.hasFocus()
    qtbot.keyClick(window.explorer, Qt.Key.Key_Escape)
    assert window.tabs.current_editor().hasFocus()


def test_settings_file_opens_and_applies_on_save(window, project):
    window.open_file(project / "top.sv")
    window.run_command("settings.open")
    settings_editor = window.tabs.current_editor()
    assert window.tabs.current_file().path == default_settings_path().resolve()

    settings_editor.setPlainText("editor:\n  tab_width: 2\n  insert_spaces: false\n")
    window.run_command("file.save")

    assert window.settings.editor.tab_width == 2
    assert window._indent_label.text() == "Tab Size: 2"
    sv_editor = window.tabs.editor_for(project / "top.sv")
    assert sv_editor.indent_unit == "\t"


def test_close_is_cancelled_when_user_cancels(window, project):
    window.open_file(project / "top.sv")
    window.tabs.current_editor().insertPlainText("x")
    window.tabs.ask_close = lambda path: "cancel"
    assert window.close() is False
    assert window.isVisible()
    window.tabs.ask_close = lambda path: "discard"  # let teardown close cleanly


# -- Step 2.6: commands, pickers, mappings, focus ------------------------------------------


def test_palette_lists_commands_with_their_keys_and_runs_the_choice(window, project):
    window.open_project(project)
    window.pick = lambda items: next(i for i in items if i.payload == "view.focusExplorer")
    window.run_command("palette.show")
    placeholder, labels = window.picked[0]
    assert placeholder == "Type a command"
    assert "View: Focus Explorer" in labels
    assert window.explorer.hasFocus()


def test_palette_shows_leader_bindings(window):
    items = []
    window.chooser = lambda found, placeholder: items.extend(found)
    window.run_command("palette.show")
    detail = {i.payload: i.detail for i in items}
    assert detail["file.find"] == "Ctrl+P  <Space>f"
    assert detail["check.run"] == "<Space>r"
    assert detail["explain.toggle"] == "Step 5"


def test_go_to_file_lists_project_files_and_opens_the_choice(window, project):
    window.open_project(project)
    window.pick = lambda items: next(i for i in items if i.label == "rtl/alu.sv")
    window.run_command("file.find")
    assert window.picked[0][1] == ["top.sv", "rtl/alu.sv"]  # root files first; .venv is skipped
    assert window.tabs.current_file().path == (project / "rtl" / "alu.sv").resolve()


def test_go_to_file_without_a_project(window):
    window.run_command("file.find")
    assert window.picked == []
    assert "Open a folder first" in window.statusBar().currentMessage()


def test_leader_mapping_in_the_editor_opens_go_to_file(qtbot, window, project):
    window.open_project(project)
    editor = window.tabs.open_file(project / "top.sv")
    qtbot.keyClick(editor, Qt.Key.Key_Space)
    _keys(qtbot, editor, "f")
    assert window.picked and window.picked[0][0] == "Go to file"


def test_leader_alone_falls_back_to_l_after_the_timeout(qtbot, window, project):
    window.keymap_path.write_text("timeoutlen: 50\n", encoding="utf-8")
    window.reload_keymap()
    editor = window.tabs.open_file(project / "top.sv")
    qtbot.keyClick(editor, Qt.Key.Key_Space)
    assert editor.vim.engine.cursor.col == 0
    qtbot.waitUntil(lambda: editor.vim.engine.cursor.col == 1, timeout=2000)


def test_ex_command_runs_a_registry_command(qtbot, window, project):
    window.open_project(project)
    editor = window.tabs.open_file(project / "top.sv")
    _keys(qtbot, editor, ":file.find")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert window.picked and window.picked[0][0] == "Go to file"


def test_planned_commands_say_when_they_arrive(window, project):
    editor = window.tabs.open_file(project / "top.sv")
    window.run_command("explain.toggle")
    assert "arrives in Step 5" in editor.statusline.text()


def test_ctrl_w_moves_focus_between_explorer_and_editor(qtbot, window, project):
    window.open_project(project)
    editor = window.tabs.open_file(project / "top.sv")
    editor.setFocus()
    _ctrl_w(qtbot, editor, "h")
    assert window.explorer.hasFocus()
    _ctrl_w(qtbot, window.explorer, "l")
    assert editor.hasFocus()
    _ctrl_w(qtbot, editor, "j")  # down to the problems panel
    assert window.problems.hasFocus()
    _ctrl_w(qtbot, window.problems, "k")
    assert editor.hasFocus()
    _ctrl_w(qtbot, editor, "w")  # explorer -> editor -> problems -> explorer
    assert window.problems.hasFocus()
    _ctrl_w(qtbot, window.problems, "w")
    assert window.explorer.hasFocus()


def test_leader_works_inside_the_explorer(qtbot, window, project):
    window.open_project(project)
    window.run_command("view.focusExplorer")
    qtbot.keyClick(window.explorer, Qt.Key.Key_Space)
    _keys(qtbot, window.explorer, "e")  # <Space>e toggles the explorer away
    assert not window.explorer_dock.isVisible()


def test_tab_navigation_gt_gT_and_alternate(qtbot, window, project):
    first = window.tabs.open_file(project / "top.sv")
    second = window.tabs.open_file(project / "rtl" / "alu.sv")
    _keys(qtbot, second, "gt")
    assert window.tabs.current_editor() is first
    _keys(qtbot, first, "2gt")
    assert window.tabs.current_editor() is second
    qtbot.keyClick(second, Qt.Key.Key_6, CTRL)  # <C-^>
    assert window.tabs.current_editor() is first
    _keys(qtbot, first, ":bn")
    qtbot.keyClick(first, Qt.Key.Key_Return)
    assert window.tabs.current_editor() is second


def test_buffer_list_switches_tabs(window, project):
    window.open_project(project)
    first = window.tabs.open_file(project / "top.sv")
    window.tabs.open_file(project / "rtl" / "alu.sv")
    window.pick = lambda items: next(i for i in items if i.label == "top.sv")
    window.run_command("buffer.list")
    assert window.tabs.current_editor() is first


def test_user_keymap_changes_leader_and_reloads_on_save(qtbot, window, project):
    window.open_project(project)
    window.run_command("keymap.open")
    keymap_editor = window.tabs.current_editor()
    assert window.tabs.current_file().path == window.keymap_path.resolve()
    keymap_editor.setPlainText('leader: ","\nnormal:\n  "<leader>z": buffer.list\n  "<leader>y": no.such.command\n')
    window.run_command("file.save")
    assert "unknown command 'no.such.command'" in window.statusBar().currentMessage()
    sv = window.tabs.open_file(project / "top.sv")
    _keys(qtbot, sv, ",z")
    assert window.picked and window.picked[-1][0] == "Switch to tab"


def test_recent_project_is_reopened_by_a_new_window(qtbot, window, project):
    window.open_project(project)
    other = MainWindow()
    qtbot.addWidget(other)
    assert other.open_last_project()
    assert other.project_root == project.resolve()


def test_explorer_shows_a_hint_until_a_folder_is_open(window, project):
    assert window.explorer.model() is None
    window.open_project(project)
    assert window.explorer.model() is not None


def test_project_files_skips_tool_folders(project):
    assert [p.name for p in project_files(project)] == ["top.sv", "alu.sv"]


def test_session_service_round_trip(tmp_path):
    path = tmp_path / "state.json"
    session = SessionService(path)
    for name in ("a", "b", "a"):
        (tmp_path / name).mkdir(exist_ok=True)
        session.remember_project(tmp_path / name)
    reloaded = SessionService(path)
    assert [p.name for p in reloaded.recent_projects()] == ["a", "b"]
    (tmp_path / "a").rmdir()
    assert reloaded.last_project().name == "b"  # deleted folders are skipped


def test_corrupt_session_file_is_ignored(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    assert SessionService(path).last_project() is None


def test_focus_direction_without_focus_picks_the_editor(window, project):
    window.open_project(project)
    editor = window.tabs.open_file(project / "top.sv")
    window.menuBar().setFocus()
    window.focus_direction(1, 0)
    assert QApplication.focusWidget() is editor
