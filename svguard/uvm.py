"""Locate a UVM library: an Accellera source tree or the copy bundled with Vivado.

Vivado layout (checked on 2020.2):
    <vivado>/data/system_verilog/uvm_1.2/xlnx_uvm_package.sv   (single flattened package)
    <vivado>/data/system_verilog/uvm_1.2/uvm_macros.svh
Accellera layout:
    <uvm_home>/src/uvm_pkg.sv, <uvm_home>/src/uvm_macros.svh
"""

from __future__ import annotations

import glob
import os
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

VIVADO_UVM_SUBDIR = Path("data/system_verilog/uvm_1.2")

# Searched after UVM_HOME / XILINX_VIVADO / `vivado` on PATH. Newest version wins.
_VIVADO_INSTALL_GLOBS = (
    "C:/Xilinx/Vivado/*",
    "C:/AMD/Vivado/*",
    "C:/AMDDesignTools/*/Vivado",
    "/tools/Xilinx/Vivado/*",
    "/opt/Xilinx/Vivado/*",
    "/tools/AMD/Vivado/*",
)
_VERSION_RE = re.compile(r"(\d{4})\.(\d+)")


@dataclass(frozen=True)
class UvmLibrary:
    package_file: Path  # compiled as an extra compilation unit
    include_dir: Path  # holds uvm_macros.svh; findings inside it are dropped
    description: str  # e.g. "Vivado 2020.2 (UVM 1.2)"


def library_from_path(path: Path | str) -> UvmLibrary | None:
    """Accepts a UVM home, its src/ dir, a Vivado install root, or Vivado's uvm_1.2 dir."""
    path = Path(path)
    candidates = (
        (path / "src" / "uvm_pkg.sv", path / "src"),
        (path / "uvm_pkg.sv", path),
        (path / "xlnx_uvm_package.sv", path),
        (path / VIVADO_UVM_SUBDIR / "xlnx_uvm_package.sv", path / VIVADO_UVM_SUBDIR),
    )
    for package, include_dir in candidates:
        if package.is_file() and (include_dir / "uvm_macros.svh").is_file():
            package = package.resolve()
            return UvmLibrary(package, include_dir.resolve(), _describe(package))
    return None


def find_uvm(env: Mapping[str, str] | None = None) -> UvmLibrary | None:
    """Auto-detect a UVM library. Returns None when nothing is installed."""
    env = os.environ if env is None else env
    for var in ("UVM_HOME", "XILINX_VIVADO"):
        if env.get(var) and (lib := library_from_path(env[var])):
            return lib
    vivado = shutil.which("vivado")
    if vivado and (lib := library_from_path(Path(vivado).resolve().parent.parent)):
        return lib
    for install in _vivado_installs():
        if lib := library_from_path(install):
            return lib
    return None


def _vivado_installs() -> list[Path]:
    found = [Path(p) for pattern in _VIVADO_INSTALL_GLOBS for p in glob.glob(pattern) if os.path.isdir(p)]
    return sorted(found, key=_version_key, reverse=True)


def _version_key(path: Path) -> tuple[int, int]:
    match = _VERSION_RE.search(str(path))
    return (int(match[1]), int(match[2])) if match else (0, 0)


def _describe(package: Path) -> str:
    if package.name == "xlnx_uvm_package.sv":
        match = _VERSION_RE.search(str(package))
        version = f" {match[0]}" if match else ""
        return f"Vivado{version} (UVM 1.2)"
    return f"UVM ({package.parent})"
