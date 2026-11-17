from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from app.panels.project_explorer import ProjectExplorer


@pytest.fixture
def project(tmp_path: Path) -> Path:
    for folder in ("rtl", ".venv", ".git", "proj.runs"):
        (tmp_path / folder).mkdir()
    (tmp_path / "rtl" / "top.sv").write_text("module top; endmodule\n")
    (tmp_path / ".svguard.yaml").write_text("preset: default\n")
    (tmp_path / "README.md").write_text("hi\n")
    return tmp_path


@pytest.fixture
def explorer(qtbot, project):
    widget = ProjectExplorer()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    widget.set_root(project)
    model = widget.model()
    qtbot.waitUntil(lambda: model.rowCount(widget.rootIndex()) == 3, timeout=5000)
    return widget


def _top_level_names(explorer: ProjectExplorer) -> list[str]:
    model = explorer.model()
    root = explorer.rootIndex()
    return [explorer.path_at(model.index(row, 0, root)).name for row in range(model.rowCount(root))]


def test_tool_folders_are_hidden_but_dotfiles_are_not(explorer):
    assert sorted(_top_level_names(explorer)) == [".svguard.yaml", "README.md", "rtl"]


def test_folders_come_first(explorer):
    assert _top_level_names(explorer)[0] == "rtl"


def test_enter_expands_folder_then_opens_file(qtbot, explorer, project):
    rtl = project.resolve() / "rtl"
    top = rtl / "top.sv"
    explorer.setCurrentIndex(explorer.index_of(rtl))
    qtbot.keyClick(explorer, Qt.Key.Key_Return)
    # Indexes are looked up by path every time: the model re-sorts in the background.
    qtbot.waitUntil(lambda: explorer.index_of(top).isValid(), timeout=5000)
    assert explorer.isExpanded(explorer.index_of(rtl))

    explorer.setCurrentIndex(explorer.index_of(top))
    with qtbot.waitSignal(explorer.file_activated) as activated:
        qtbot.keyClick(explorer, Qt.Key.Key_Return)
    assert activated.args == [top]


def test_escape_signals_return_to_editor(qtbot, explorer):
    with qtbot.waitSignal(explorer.escape_pressed):
        qtbot.keyClick(explorer, Qt.Key.Key_Escape)


def _current_name(explorer) -> str:
    return explorer.path_at(explorer.currentIndex()).name


def test_vim_keys_move_expand_and_open(qtbot, explorer, project):
    rtl = project.resolve() / "rtl"
    explorer.setCurrentIndex(explorer.index_of(rtl))
    qtbot.keyClick(explorer, "j")
    assert _current_name(explorer) == ".svguard.yaml"
    qtbot.keyClick(explorer, "G")
    assert _current_name(explorer) == "README.md"
    qtbot.keyClicks(explorer, "gg")
    assert _current_name(explorer) == "rtl"

    qtbot.keyClick(explorer, "l")  # expand
    qtbot.waitUntil(lambda: explorer.index_of(rtl / "top.sv").isValid(), timeout=5000)
    assert explorer.isExpanded(explorer.index_of(rtl))
    qtbot.keyClick(explorer, "l")  # into the folder
    assert _current_name(explorer) == "top.sv"
    with qtbot.waitSignal(explorer.file_activated) as opened:
        qtbot.keyClick(explorer, "l")  # open the file
    assert opened.args == [rtl / "top.sv"]
    qtbot.keyClick(explorer, "h")  # back to the parent folder
    assert _current_name(explorer) == "rtl"
    qtbot.keyClick(explorer, "h")  # collapse
    assert not explorer.isExpanded(explorer.index_of(rtl))


def test_search_and_repeat(qtbot, explorer):
    explorer.setCurrentIndex(explorer.model().index(0, 0, explorer.rootIndex()))
    qtbot.keyClick(explorer, "/")
    qtbot.keyClicks(explorer._search, "read")
    qtbot.keyClick(explorer._search, Qt.Key.Key_Return)
    assert _current_name(explorer) == "README.md"
    assert explorer.hasFocus()
    qtbot.keyClick(explorer, "n")  # wraps around to the same single match
    assert _current_name(explorer) == "README.md"


def test_q_asks_to_hide(qtbot, explorer):
    with qtbot.waitSignal(explorer.hide_requested):
        qtbot.keyClick(explorer, "q")


def test_no_model_until_a_folder_is_set(qtbot):
    widget = ProjectExplorer()
    qtbot.addWidget(widget)
    assert widget.model() is None
    with qtbot.waitSignal(widget.escape_pressed):
        qtbot.keyClick(widget, Qt.Key.Key_Escape)
