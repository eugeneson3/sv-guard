"""Step 4: save -> check in the worker -> squiggles, problems panel, stale marks."""

from concurrent.futures import Executor, Future
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCharFormat

from app.editor.code_editor import CodeEditor
from app.main_window import MainWindow
from app.panels.problems_panel import ProblemsPanel
from app.services.analysis_service import AnalysisService, process_executor
from svguard.model import Finding, Location, Severity
from svguard.runner import AnalysisError, AnalysisReport, AnalysisRequest

LATCH = b"module latch_if (\n  input logic en,\n  input logic d,\n  output logic q\n);\n  always_comb begin\n    if (en)\n      q = d;\n  end\nendmodule\n"
PORTS = (
    b"module leaf(input logic a, output logic y); assign y = a; endmodule\n"
    b"module top(output logic y);\n  leaf u (.a(), .y(y));\nendmodule\n"
)


def _finding(path: Path, line: int, col: int, end_col: int | None = None, severity=Severity.WARNING, code="X") -> Finding:
    return Finding("SVG-C000", severity, f"{code} here", Location(path, line, col, line, end_col or col), slang_code=code)


# -- AnalysisService ------------------------------------------------------------------------


class ManualExecutor(Executor):
    """Futures that the test completes by hand, to check queueing."""

    def __init__(self):
        self.submitted: list[tuple[object, Future]] = []

    def submit(self, fn, *args, **kwargs):
        future: Future = Future()
        self.submitted.append((args[0] if args else None, future))
        return future


def test_service_coalesces_requests_while_busy(qtbot):
    executor = ManualExecutor()
    service = AnalysisService(lambda: executor)
    first, second, third = (AnalysisRequest(paths=(Path(name),)) for name in "abc")
    service.request(first)
    service.request(second)
    service.request(third)  # replaces the queued second one
    assert [r for r, _f in executor.submitted] == [first]
    with qtbot.waitSignal(service.finished) as done:
        executor.submitted[0][1].set_result(AnalysisReport(findings=()))
    assert done.args[0].request == first and done.args[0].report is not None
    assert [r for r, _f in executor.submitted] == [first, third]
    assert service.busy


@pytest.mark.parametrize(
    ("exception", "fragment"),
    [
        (AnalysisError("no SystemVerilog sources (.sv/.v) found"), "no SystemVerilog sources"),
        (RuntimeError("parser exploded"), "RuntimeError: parser exploded"),
        (BrokenProcessPool("gone"), "worker crashed"),
    ],
)
def test_service_reports_failures(qtbot, exception, fragment):
    executor = ManualExecutor()
    service = AnalysisService(lambda: executor)
    service.request(AnalysisRequest(paths=(Path("x"),)))
    with qtbot.waitSignal(service.finished) as done:
        executor.submitted[0][1].set_exception(exception)
    outcome = done.args[0]
    assert outcome.report is None and fragment in outcome.error
    assert not service.busy


def test_real_worker_process_checks_a_file(qtbot, tmp_path):
    """The production path: a spawned process imports pyslang and runs svguard."""
    src = tmp_path / "latch.sv"
    src.write_bytes(LATCH)
    service = AnalysisService(process_executor)
    try:
        with qtbot.waitSignal(service.finished, timeout=60_000) as done:
            service.request(AnalysisRequest(paths=(src,)))
        report = done.args[0].report
        assert [f.slang_code for f in report.findings] == ["InferredLatch"]
    finally:
        service.shutdown()


# -- editor diagnostics -----------------------------------------------------------------------


@pytest.fixture
def editor(qtbot, tmp_path):
    widget = CodeEditor()
    qtbot.addWidget(widget)
    widget.setPlainText("module m;\n  logic abc_q;\nendmodule\n")
    widget.path = tmp_path / "m.sv"
    return widget


def test_findings_are_underlined_and_marked_in_the_gutter(editor):
    editor.set_findings([_finding(editor.path, 2, 9, severity=Severity.ERROR)])
    (selection,) = [s for s in editor.extraSelections() if s.format.underlineStyle() != QTextCharFormat.UnderlineStyle.NoUnderline]
    assert selection.cursor.selectedText() == "abc_q"  # a point finding underlines the word
    assert selection.format.underlineStyle() == QTextCharFormat.UnderlineStyle.WaveUnderline
    assert editor.diagnostics.line_severities() == {1: Severity.ERROR}
    assert editor.diagnostics.counts()[Severity.ERROR] == 1


def test_ranges_follow_edits_and_become_stale(editor):
    finding = _finding(editor.path, 2, 9, end_col=14)
    editor.set_findings([finding])
    assert not editor.diagnostics.stale
    cursor = editor.textCursor()
    cursor.setPosition(0)
    cursor.insertText("// new line\n")
    assert editor.diagnostics.stale
    assert editor.diagnostics.line_severities() == {2: Severity.WARNING}  # moved down with the text
    position = editor.diagnostics.position_of(finding)
    assert editor.document().findBlock(position).text() == "  logic abc_q;"
    (selection,) = [s for s in editor.extraSelections() if s.format.underlineStyle() == QTextCharFormat.UnderlineStyle.DotLine]
    assert selection.cursor.selectedText() == "abc_q"


def test_finding_under_the_cursor(editor):
    finding = _finding(editor.path, 2, 9, end_col=14)
    editor.set_findings([finding])
    cursor = editor.textCursor()
    cursor.setPosition(editor.document().findBlockByNumber(1).position())
    editor.setTextCursor(cursor)
    assert editor.finding_at_cursor() == finding  # same line counts too
    cursor.setPosition(0)
    editor.setTextCursor(cursor)
    assert editor.finding_at_cursor() is None


def test_point_at_line_end_and_empty_line(editor):
    editor.set_findings([_finding(editor.path, 1, 10), _finding(editor.path, 4, 1)])
    texts = sorted(m.cursor.selectedText() for m in editor.diagnostics.marks)
    assert texts == ["", ";"]  # line end: the last character; empty last line: just the gutter mark


# -- problems panel ---------------------------------------------------------------------------


def test_problems_panel_groups_and_jumps_with_keys(qtbot, tmp_path):
    panel = ProblemsPanel()
    qtbot.addWidget(panel)
    a, b = tmp_path / "a.sv", tmp_path / "rtl" / "b.sv"
    findings = [_finding(b, 3, 1, code="B1"), _finding(a, 9, 1, severity=Severity.ERROR, code="A2"), _finding(a, 2, 1, code="A1")]
    panel.set_findings(findings, root=tmp_path)
    assert panel.visible_rows() == ["a.sv", "A1 here", "A2 here", "rtl/b.sv", "B1 here"]
    assert panel.summary() == "1 error(s), 2 warning(s)"
    assert panel.current_finding().slang_code == "A1"
    qtbot.keyClick(panel, "j")
    with qtbot.waitSignal(panel.jump_requested) as jumped:
        qtbot.keyClick(panel, Qt.Key.Key_Return)
    assert jumped.args[0].slang_code == "A2"
    qtbot.keyClick(panel, "G")
    assert panel.current_finding().slang_code == "B1"


def test_problems_panel_filter_and_stale(qtbot, tmp_path):
    panel = ProblemsPanel()
    qtbot.addWidget(panel)
    a = tmp_path / "a.sv"
    panel.set_findings([_finding(a, 1, 1, code="InferredLatch"), _finding(a, 2, 1, code="PortWidthExpand")], root=tmp_path)
    qtbot.keyClick(panel, "/")
    qtbot.keyClicks(panel._filter_edit, "latch")
    qtbot.keyClick(panel._filter_edit, Qt.Key.Key_Return)
    assert panel.visible_rows() == ["a.sv", "InferredLatch here"]
    panel.mark_stale(a)
    assert panel.topLevelItem(0).text(1).endswith("(edited since check)")


def test_problems_panel_q_hides(qtbot):
    panel = ProblemsPanel()
    qtbot.addWidget(panel)
    with qtbot.waitSignal(panel.hide_requested):
        qtbot.keyClick(panel, "q")


# -- the whole loop in the IDE -----------------------------------------------------------------


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "latch.sv").write_bytes(LATCH)
    (root / "ports.sv").write_bytes(PORTS)
    return root


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win.activateWindow()
    return win


def _save_and_wait(qtbot, window: MainWindow, editor: CodeEditor) -> None:
    with qtbot.waitSignal(window.analysis.finished, timeout=20_000):
        qtbot.keyClick(editor, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)


def test_saving_checks_the_project_and_shows_the_results(qtbot, window, project):
    window.open_project(project)
    editor = window.tabs.open_file(project / "latch.sv")
    _save_and_wait(qtbot, window, editor)

    assert sorted(f.slang_code for f in window.last_report.findings) == ["EmptyInputPortConn", "InferredLatch"]
    assert window.problems.visible_rows()[0] == "latch.sv"
    assert editor.diagnostics.counts()[Severity.WARNING] == 1
    assert editor.statusline.counts_text() == "E0 W1"
    assert "1 warning" in window._check_label.text() or "2 warning" in window._check_label.text()


def test_no_check_while_typing_and_stale_after_edits(qtbot, window, project):
    window.open_project(project)
    editor = window.tabs.open_file(project / "latch.sv")
    _save_and_wait(qtbot, window, editor)
    finished = []
    window.analysis.finished.connect(finished.append)
    qtbot.keyClicks(editor, "O// note")
    qtbot.keyClick(editor, Qt.Key.Key_Escape)
    qtbot.wait(100)
    assert finished == []  # typing never starts a check
    assert editor.diagnostics.stale
    assert editor.statusline.counts_text() == "E0 W1~"
    assert window.problems.topLevelItem(0).text(1).endswith("(edited since check)")
    _save_and_wait(qtbot, window, editor)
    assert not editor.diagnostics.stale


def test_files_opened_after_a_check_get_their_findings(qtbot, window, project):
    window.open_project(project)
    _save_and_wait(qtbot, window, window.tabs.open_file(project / "latch.sv"))
    other = window.tabs.open_file(project / "ports.sv")
    assert [m.finding.slang_code for m in other.diagnostics.marks] == ["EmptyInputPortConn"]


def test_bracket_d_walks_problems_across_files(qtbot, window, project):
    window.open_project(project)
    editor = window.tabs.open_file(project / "latch.sv")
    _save_and_wait(qtbot, window, editor)
    qtbot.keyClicks(editor, "gg]d")
    assert window.tabs.current_file().path.name == "latch.sv"
    assert editor.vim.engine.cursor.row == 7  # q = d;
    qtbot.keyClicks(editor, "]d")
    current = window.tabs.current_editor()
    assert window.tabs.current_file().path.name == "ports.sv"
    assert current.vim.engine.cursor.row == 2
    qtbot.keyClicks(current, "]d")  # wraps around
    assert window.tabs.current_file().path.name == "latch.sv"
    qtbot.keyClicks(window.tabs.current_editor(), "[d")
    assert window.tabs.current_file().path.name == "ports.sv"
    qtbot.keyClicks(window.tabs.current_editor(), "]e")
    assert "No errors" in window.tabs.current_editor().statusline.text()


def test_problems_panel_keys_jump_into_the_file(qtbot, window, project):
    window.open_project(project)
    _save_and_wait(qtbot, window, window.tabs.open_file(project / "latch.sv"))
    window.run_command("problems.show")
    assert window.problems.hasFocus()
    qtbot.keyClicks(window.problems, "G")
    qtbot.keyClick(window.problems, Qt.Key.Key_Return)
    editor = window.tabs.current_editor()
    assert window.tabs.current_file().path.name == "ports.sv"
    assert editor.hasFocus() and editor.vim.engine.cursor.row == 2


def test_space_r_checks_and_space_p_focuses_problems(qtbot, window, project):
    window.open_project(project)
    editor = window.tabs.open_file(project / "latch.sv")
    with qtbot.waitSignal(window.analysis.finished, timeout=20_000):
        qtbot.keyClick(editor, Qt.Key.Key_Space)
        qtbot.keyClick(editor, "r")
    qtbot.keyClick(editor, Qt.Key.Key_Space)
    qtbot.keyClick(editor, "p")
    assert window.problems.hasFocus()
    qtbot.keyClick(window.problems, "q")
    assert not window.problems_dock.isVisible()


def test_loose_file_without_a_folder_is_checked_alone(qtbot, window, tmp_path):
    src = tmp_path / "solo.sv"
    src.write_bytes(LATCH)
    editor = window.tabs.open_file(src)
    _save_and_wait(qtbot, window, editor)
    assert [f.slang_code for f in window.last_report.findings] == ["InferredLatch"]


def test_saving_settings_does_not_start_a_check(qtbot, window):
    started = []
    window.analysis.started.connect(started.append)
    window.run_command("settings.open")
    window.run_command("file.save")
    qtbot.wait(50)
    assert started == []


def test_a_failed_check_is_reported(qtbot, window, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "notes.txt").write_text("x", encoding="utf-8")
    window.open_project(empty)
    with qtbot.waitSignal(window.analysis.finished, timeout=20_000):
        window.run_command("check.run")
    assert window.problems.state == "error"
    assert "no SystemVerilog sources" in window.statusBar().currentMessage()
