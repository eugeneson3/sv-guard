from pathlib import Path

import pytest

from app.editor.editor_tabs import EditorTabs
from app.settings import EditorSettings


@pytest.fixture
def tabs(qtbot):
    widget = EditorTabs(EditorSettings())
    qtbot.addWidget(widget)
    return widget


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def test_open_same_file_twice_reuses_the_tab(tabs, tmp_path):
    path = _write(tmp_path / "a.sv", b"module a; endmodule\n")
    first = tabs.open_file(path)
    second = tabs.open_file(tmp_path / "." / "a.sv")
    assert first is second
    assert tabs.count() == 1


def test_dirty_marker_and_save(tabs, tmp_path, qtbot):
    path = _write(tmp_path / "a.sv", b"module a;\nendmodule\n")
    editor = tabs.open_file(path)
    editor.insertPlainText("// edit\n")
    assert tabs.tabText(0) == "a.sv ●"
    with qtbot.waitSignal(tabs.file_saved) as saved:
        assert tabs.save()
    assert saved.args == [path.resolve()]
    assert tabs.tabText(0) == "a.sv"
    assert path.read_text(encoding="utf-8").startswith("// edit\n")


def test_save_preserves_cp949_and_crlf(tabs, tmp_path):
    original = "// 한글 주석\r\nmodule a;\r\nendmodule\r\n".encode("cp949")
    path = _write(tmp_path / "legacy.sv", original)
    editor = tabs.open_file(path)
    assert editor.toPlainText() == "// 한글 주석\nmodule a;\nendmodule\n"
    info = tabs.file_info(editor)
    assert (info.encoding, info.eol) == ("cp949", "\r\n")
    editor.document().setModified(True)
    tabs.save()
    assert path.read_bytes() == original


def test_unencodable_text_falls_back_to_utf8(tabs, tmp_path, qtbot):
    path = _write(tmp_path / "legacy.sv", "// 한글\n".encode("cp949"))
    editor = tabs.open_file(path)
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    editor.insertPlainText("// \U0001f600\n")
    with qtbot.waitSignal(tabs.status_message) as message:
        tabs.save()
    assert "saved as UTF-8" in message.args[0]
    assert tabs.file_info(editor).encoding == "utf-8"
    assert path.read_text(encoding="utf-8") == "// 한글\n// \U0001f600\n"


def test_binary_file_is_refused(tabs, tmp_path):
    path = _write(tmp_path / "blob.bin", b"\x00\x01\x02")
    assert tabs.open_file(path) is None
    assert tabs.count() == 0


@pytest.mark.parametrize(
    ("choice", "closed", "saved"),
    [("cancel", False, False), ("discard", True, False), ("save", True, True)],
)
def test_closing_a_dirty_tab_asks(tabs, tmp_path, choice, closed, saved):
    path = _write(tmp_path / "a.sv", b"x\n")
    editor = tabs.open_file(path)
    editor.insertPlainText("y")
    asked = []
    tabs.ask_close = lambda p: asked.append(p) or choice
    assert tabs.close_current() is closed
    assert asked == [path.resolve()]
    assert tabs.count() == (0 if closed else 1)
    assert (path.read_bytes() == b"yx\n") is saved


def test_close_all_stops_at_cancel(tabs, tmp_path):
    for name in ("a.sv", "b.sv"):
        tabs.open_file(_write(tmp_path / name, b"x\n")).insertPlainText("y")
    tabs.ask_close = lambda p: "cancel"
    assert tabs.close_all() is False
    assert tabs.count() == 2


def test_same_file_names_are_disambiguated(tabs, tmp_path):
    for folder in ("rtl", "tb"):
        (tmp_path / folder).mkdir()
        tabs.open_file(_write(tmp_path / folder / "top.sv", b"\n"))
    assert [tabs.tabText(i) for i in range(2)] == ["top.sv — rtl", "top.sv — tb"]


def test_select_relative_wraps(tabs, tmp_path):
    for name in ("a.sv", "b.sv", "c.sv"):
        tabs.open_file(_write(tmp_path / name, b"\n"))
    tabs.select_relative(1)
    assert tabs.current_file().path.name == "a.sv"
    tabs.select_relative(-1)
    assert tabs.current_file().path.name == "c.sv"


def test_apply_settings_reaches_open_editors(tabs, tmp_path):
    editor = tabs.open_file(_write(tmp_path / "a.sv", b"\n"))
    tabs.apply_settings(EditorSettings(tab_width=2))
    assert editor.indent_unit == "  "


def test_non_sv_files_get_no_highlighter(tabs, tmp_path):
    assert tabs.open_file(_write(tmp_path / "notes.txt", b"module\n")).highlighter is None
    assert tabs.open_file(_write(tmp_path / "a.sv", b"module\n")).highlighter is not None
