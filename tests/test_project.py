from pathlib import Path

import pytest

from svguard.project import PathFilter, Project


@pytest.mark.parametrize(
    ("pattern", "path", "is_dir", "expected"),
    [
        ("third_party/**", "third_party", True, True),
        ("third_party/**", "third_party/x/y.sv", False, True),
        ("third_party/**", "rtl/third_party.sv", False, False),
        ("*.cache", "proj.cache", True, True),
        ("*.cache", "rtl/proj.cache", True, True),  # component pattern matches at any depth
        (".*", ".git", True, True),
        ("*.srcs/*/ip/**", "proj.srcs/sources_1/ip", True, True),
        ("*.srcs/*/ip/**", "proj.srcs/sources_1/new", True, False),
        ("**/gen/*.sv", "a/b/gen/x.sv", False, True),
        ("**/gen/*.sv", "gen/x.sv", False, True),
    ],
)
def test_path_filter(pattern, path, is_dir, expected):
    assert PathFilter([pattern]).excluded(path, is_dir=is_dir) is expected


def _names(paths):
    return sorted(p.name for p in paths)


def test_discover_classifies_sources_and_headers(fixtures):
    project = Project.discover(fixtures / "projects" / "multi")
    assert _names(project.sources) == ["sub.sv", "top.sv", "types_pkg.sv", "vendor.sv"]
    assert _names(project.headers) == ["defs.svh"]
    assert (fixtures / "projects" / "multi" / "include").resolve() in project.include_dirs


def test_discover_skips_vivado_outputs_by_default(fixtures):
    project = Project.discover(fixtures / "projects" / "multi")
    assert "glbl.v" not in _names(project.files)


def test_discover_user_exclude(fixtures):
    project = Project.discover(fixtures / "projects" / "multi", exclude=["third_party/**"])
    assert "vendor.sv" not in _names(project.files)


def test_sv_files_pulled_in_by_include_become_headers(fixtures):
    project = Project.discover(fixtures / "projects" / "uvm_tb")
    assert _names(project.sources) == ["tb_pkg.sv", "tb_top.sv"]
    assert _names(project.headers) == ["my_driver.sv", "my_item.sv"]


def test_from_files_uses_common_parent_as_root(fixtures):
    rtl = fixtures / "projects" / "multi" / "rtl"
    project = Project.from_files([rtl / "top.sv", rtl / "sub.sv"])
    assert project.root == rtl.resolve()
    assert _names(project.sources) == ["sub.sv", "top.sv"]


def test_from_files_requires_files():
    with pytest.raises(ValueError):
        Project.from_files([])


def test_discover_non_ascii_directory(tmp_path: Path):
    folder = tmp_path / "1주차 실습"
    folder.mkdir()
    (folder / "a.sv").write_text("module a; endmodule\n", encoding="utf-8")
    assert _names(Project.discover(tmp_path).sources) == ["a.sv"]
