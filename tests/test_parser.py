from pathlib import Path

from svguard.model import Severity
from svguard.parser import (
    SLANG_RULE_ID,
    UVM_MISSING_MESSAGE,
    ParseOptions,
    compile_project,
    compile_sources,
    compile_text,
)
from svguard.project import Project


def _codes(findings):
    return [f.slang_code for f in findings]


def test_clean_file_has_no_findings(fixtures):
    assert compile_sources([fixtures / "rtl" / "clean_counter.sv"]).findings() == []


def test_syntax_error_is_reported_at_the_right_line(fixtures):
    findings = compile_sources([fixtures / "rtl" / "syntax_error.sv"]).findings()
    assert _codes(findings) == ["ExpectedToken"]
    finding = findings[0]
    assert finding.rule_id == SLANG_RULE_ID
    assert finding.severity is Severity.ERROR
    assert finding.origin == "slang"
    assert finding.location.line == 5


def test_latch_comes_from_slang_analysis(fixtures):
    findings = compile_sources([fixtures / "rtl" / "latch.sv"]).findings()
    assert _codes(findings) == ["InferredLatch"]
    assert findings[0].severity is Severity.WARNING
    assert "'q'" in findings[0].message


def test_empty_input_connection():
    text = """
module leaf(input logic a, output logic y); assign y = a; endmodule
module top(output logic y); leaf u(.a(), .y(y)); endmodule
"""
    assert _codes(compile_text(text).findings()) == ["EmptyInputPortConn"]


def test_fsm_case_missing_an_enum_state():
    text = """
module fsm(input logic clk, output logic busy);
    typedef enum logic [1:0] {IDLE, RUN, DONE} state_t;
    state_t state;
    always_ff @(posedge clk) state <= RUN;
    always_comb begin
        busy = 1'b0;
        case (state)
            IDLE: busy = 1'b0;
            RUN:  busy = 1'b1;
        endcase
    end
endmodule
"""
    (finding,) = compile_text(text).findings()
    assert finding.slang_code == "CaseEnum"
    assert "'DONE'" in finding.message


def test_pedantic_warnings_are_off_by_default():
    # Width conversion warnings are not in slang's default set nor in LEARNING_WARNINGS.
    text = "module m(input logic [15:0] a, output logic [7:0] y); assign y = a; endmodule\n"
    assert compile_text(text).findings() == []


def test_cross_file_project_with_include_and_package(fixtures):
    project = Project.discover(fixtures / "projects" / "multi", exclude=["third_party/**"])
    assert compile_project(project).findings() == []


def test_error_in_project_file_points_to_that_file(fixtures):
    project = Project.discover(fixtures / "projects" / "multi")
    findings = compile_project(project).findings()
    assert [(f.location.file.name, f.location.line) for f in findings] == [("vendor.sv", 2)]


def test_defines_reach_the_preprocessor():
    text = "`ifdef SIM\nmodule m(output logic [`W-1:0] o); assign o = '0; endmodule\n`else\nsyntax error\n`endif\n"
    options = ParseOptions(defines={"SIM": None, "W": "4"})
    assert compile_text(text, options=options).findings() == []


def test_columns_are_characters_and_ranges_have_an_end():
    text = "module k(output logic o);\n  /* 가나다 */ assign o = undefined_sig;\nendmodule\n"
    (finding,) = compile_text(text).findings()
    line = text.splitlines()[1]
    loc = finding.location
    assert (loc.line, loc.col) == (2, line.index("undefined_sig") + 1)
    assert loc.end_col == loc.col + len("undefined_sig")


def test_non_ascii_path_and_include_dir(tmp_path: Path):
    folder = tmp_path / "한글 폴더"
    (folder / "inc").mkdir(parents=True)
    (folder / "inc" / "defs.svh").write_text("`define W 4\n", encoding="utf-8")
    src = folder / "k.sv"
    src.write_text('`include "defs.svh"\nmodule k(output logic [`W-1:0] o); assign o = zz; endmodule\n', encoding="utf-8")
    findings = compile_project(Project.discover(folder)).findings()
    assert _codes(findings) == ["UndeclaredIdentifier"]
    assert findings[0].location.file == src.resolve()


def test_cp949_source_is_decoded_before_parsing(tmp_path: Path):
    src = tmp_path / "legacy.sv"
    line2 = "module c(output logic o); /*한글*/ assign o = zz; endmodule"
    src.write_bytes(f"// 한글 주석\n{line2}\n".encode("cp949"))
    findings = compile_sources([src]).findings()
    assert _codes(findings) == ["UndeclaredIdentifier"]  # no InvalidUTF8Seq noise
    assert findings[0].location.col == line2.index("zz") + 1


def test_uvm_files_are_skipped_when_no_library(fixtures):
    project = Project.discover(fixtures / "projects" / "uvm_tb")
    design = compile_project(project, ParseOptions(uvm=None))
    findings = design.findings()
    assert design.uvm is None
    assert {f.location.file.name for f in findings} == {"tb_pkg.sv", "tb_top.sv"}
    assert all(f.severity is Severity.INFO and f.message == UVM_MISSING_MESSAGE for f in findings)


def test_location_helper_for_rules():
    design = compile_text("module m; logic a; endmodule\n")
    tree = design.trees[-1]
    token = tree.root.getFirstToken()
    loc = design.location(token.location)
    assert (loc.line, loc.col) == (1, 1)
