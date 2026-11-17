from pathlib import Path

from svguard.model import Severity
from svguard.parser import ParseOptions, compile_project, compile_text
from svguard.project import Project
from svguard.uvm import find_uvm, library_from_path


def _fake_vivado(root: Path) -> Path:
    uvm_dir = root / "Vivado" / "2099.1" / "data" / "system_verilog" / "uvm_1.2"
    uvm_dir.mkdir(parents=True)
    (uvm_dir / "xlnx_uvm_package.sv").write_text("package uvm_pkg; endpackage\n")
    (uvm_dir / "uvm_macros.svh").write_text("")
    return root / "Vivado" / "2099.1"


def _fake_accellera(root: Path) -> Path:
    (root / "src").mkdir(parents=True)
    (root / "src" / "uvm_pkg.sv").write_text("package uvm_pkg; endpackage\n")
    (root / "src" / "uvm_macros.svh").write_text("")
    return root


def test_library_from_vivado_install_root(tmp_path):
    lib = library_from_path(_fake_vivado(tmp_path))
    assert lib is not None
    assert lib.package_file.name == "xlnx_uvm_package.sv"
    assert lib.description == "Vivado 2099.1 (UVM 1.2)"


def test_library_from_accellera_home(tmp_path):
    lib = library_from_path(_fake_accellera(tmp_path / "uvm-1.2"))
    assert lib is not None
    assert lib.package_file.name == "uvm_pkg.sv"
    assert lib.include_dir.name == "src"


def test_library_from_unrelated_dir(tmp_path):
    assert library_from_path(tmp_path) is None


def test_find_uvm_prefers_uvm_home(tmp_path):
    home = _fake_accellera(tmp_path / "uvm")
    lib = find_uvm(env={"UVM_HOME": str(home)})
    assert lib is not None and lib.package_file.name == "uvm_pkg.sv"


def test_library_only_loaded_when_a_file_uses_uvm(tmp_path):
    lib = library_from_path(_fake_accellera(tmp_path / "uvm"))
    design = compile_text("module m; endmodule\n", options=ParseOptions(uvm=lib))
    assert design.uvm is None


# --- tests against a real installed UVM (skipped when none is found) -----------


def test_real_uvm_testbench_is_clean(fixtures, uvm_library):
    project = Project.discover(fixtures / "projects" / "uvm_tb")
    design = compile_project(project, ParseOptions(uvm=uvm_library))
    assert design.uvm == uvm_library
    assert design.findings() == []  # nothing leaks from the UVM library itself


def test_real_uvm_reports_user_errors_in_included_files(fixtures, uvm_library, tmp_path):
    for src in (fixtures / "projects" / "uvm_tb").glob("*.sv"):
        (tmp_path / src.name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    driver = tmp_path / "my_driver.sv"
    driver.write_text(
        driver.read_text(encoding="utf-8").replace(
            "seq_item_port.item_done();",
            'seq_item_port.item_done();\n            `uvm_info("DRV", 42, UVM_LOW)',
        ),
        encoding="utf-8",
    )
    findings = compile_project(Project.discover(tmp_path), ParseOptions(uvm=uvm_library)).findings()
    assert [(f.location.file.name, f.slang_code, f.severity) for f in findings] == [
        ("my_driver.sv", "NoImplicitConversion", Severity.ERROR)
    ]
    assert findings[0].location.line == 13
