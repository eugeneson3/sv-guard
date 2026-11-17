import json

import pytest

from svguard.cli import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, main


def test_clean_exits_zero(fixtures, capsys):
    assert main(["check", str(fixtures / "rtl" / "clean_counter.sv"), "--no-uvm"]) == EXIT_OK
    assert "0 error(s)" in capsys.readouterr().out


def test_error_exits_one_with_gcc_style_line(fixtures, capsys):
    assert main(["check", str(fixtures / "rtl" / "syntax_error.sv"), "--no-uvm"]) == EXIT_FINDINGS
    first_line = capsys.readouterr().out.splitlines()[0]
    assert first_line.endswith("syntax_error.sv:5:17: error: expected ';' [SVG-C000 ExpectedToken]")


def test_warnings_pass_unless_fail_on_warning(fixtures):
    latch = str(fixtures / "rtl" / "latch.sv")
    assert main(["check", latch, "--no-uvm"]) == EXIT_OK
    assert main(["check", latch, "--no-uvm", "--fail-on", "warning"]) == EXIT_FINDINGS


def test_fail_on_never(fixtures):
    assert main(["check", str(fixtures / "rtl" / "syntax_error.sv"), "--no-uvm", "--fail-on", "never"]) == EXIT_OK


def test_json_output(fixtures, capsys):
    main(["check", str(fixtures / "rtl" / "latch.sv"), "--no-uvm", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["warning"] == 1
    (finding,) = payload["findings"]
    assert finding["slang_code"] == "InferredLatch"
    assert finding["line"] == 8


def test_exclude_and_directory_input(fixtures, capsys):
    project = str(fixtures / "projects" / "multi")
    assert main(["check", project, "--no-uvm"]) == EXIT_FINDINGS
    assert main(["check", project, "--no-uvm", "--exclude", "third_party/**"]) == EXIT_OK


def test_defines(tmp_path):
    src = tmp_path / "d.sv"
    src.write_text("`ifndef SIM\nsyntax error\n`endif\nmodule d; endmodule\n", encoding="utf-8")
    assert main(["check", str(src), "--no-uvm"]) == EXIT_FINDINGS
    assert main(["check", str(src), "--no-uvm", "-D", "SIM"]) == EXIT_OK


@pytest.mark.parametrize(
    "argv",
    [
        ["check", "does/not/exist.sv"],
        ["check", ".", "-I", "no_such_dir"],
        ["check", ".", "--uvm-home", "."],
    ],
)
def test_usage_errors_exit_two(argv, capsys, fixtures, monkeypatch):
    monkeypatch.chdir(fixtures / "rtl")
    assert main(argv) == EXIT_USAGE
    assert "svguard: error:" in capsys.readouterr().err


def test_directory_without_sources_is_a_usage_error(tmp_path, capsys):
    assert main(["check", str(tmp_path)]) == EXIT_USAGE
