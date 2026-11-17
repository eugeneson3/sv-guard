from pathlib import Path

import pytest

from svguard.runner import AnalysisError, AnalysisRequest, analyze


def test_analyze_project_folder(fixtures):
    report = analyze(AnalysisRequest(paths=(fixtures / "projects" / "multi",), exclude=("third_party/**",)))
    assert report.findings == ()
    assert [p.name for p in report.files] == ["defs.svh", "sub.sv", "top.sv", "types_pkg.sv"]
    assert report.seconds >= 0


def test_analyze_single_file(fixtures):
    report = analyze(AnalysisRequest(paths=(fixtures / "rtl" / "latch.sv",)))
    assert [f.slang_code for f in report.findings] == ["InferredLatch"]


def test_defines_are_passed(tmp_path: Path):
    src = tmp_path / "d.sv"
    src.write_text("`ifndef SIM\nsyntax error\n`endif\nmodule d; endmodule\n", encoding="utf-8")
    assert analyze(AnalysisRequest(paths=(src,), defines=(("SIM", None),))).findings == ()


@pytest.mark.parametrize(
    ("make_request", "message"),
    [
        (lambda tmp: AnalysisRequest(paths=(tmp / "missing.sv",)), "path not found"),
        (lambda tmp: AnalysisRequest(paths=(tmp,)), "no SystemVerilog sources"),
        (lambda tmp: AnalysisRequest(paths=(tmp,), include_dirs=(tmp / "nope",)), "include directory not found"),
    ],
)
def test_request_problems_raise_analysis_error(tmp_path: Path, make_request, message):
    with pytest.raises(AnalysisError, match=message):
        analyze(make_request(tmp_path))
