"""One analysis run, shared by the CLI and the IDE.

The IDE calls analyze() in a separate worker process: pyslang holds the GIL while it
compiles, so a worker *thread* would still freeze the UI. Requests and reports are plain
picklable dataclasses for that reason.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from svguard.model import Finding
from svguard.parser import ParseOptions, compile_project
from svguard.project import Project
from svguard.uvm import UvmLibrary, find_uvm, library_from_path


class AnalysisError(Exception):
    """A problem with the request itself (missing path, no sources, bad UVM path)."""


@dataclass(frozen=True)
class AnalysisRequest:
    paths: tuple[Path, ...]  # one project folder, or files and folders
    exclude: tuple[str, ...] = ()
    include_dirs: tuple[Path, ...] = ()
    defines: tuple[tuple[str, str | None], ...] = ()
    uvm_home: Path | None = None
    find_uvm: bool = True
    check_unused: bool = False


@dataclass(frozen=True)
class AnalysisReport:
    findings: tuple[Finding, ...]
    files: tuple[Path, ...] = field(default_factory=tuple)
    uvm: str | None = None  # description of the UVM library used, if any
    seconds: float = 0.0


def analyze(request: AnalysisRequest) -> AnalysisReport:
    started = time.perf_counter()
    for directory in request.include_dirs:
        if not Path(directory).is_dir():
            raise AnalysisError(f"include directory not found: {directory}")
    project = load_project(request.paths, request.exclude, request.include_dirs)
    if not project.sources:
        raise AnalysisError("no SystemVerilog sources (.sv/.v) found")
    options = ParseOptions(defines=dict(request.defines), uvm=_uvm_for(request), check_unused=request.check_unused)
    design = compile_project(project, options)
    findings = tuple(design.findings())
    return AnalysisReport(
        findings=findings,
        files=project.files,
        uvm=design.uvm.description if design.uvm else None,
        seconds=time.perf_counter() - started,
    )


def load_project(paths: Sequence[Path], exclude: Sequence[str] = (), include_dirs: Sequence[Path] = ()) -> Project:
    paths = [Path(p) for p in paths]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise AnalysisError(f"path not found: {', '.join(missing)}")
    if len(paths) == 1 and paths[0].is_dir():
        return Project.discover(paths[0], exclude=exclude, include_dirs=include_dirs)
    files: list[Path] = []
    for path in paths:
        files.extend(Project.discover(path, exclude=exclude).files if path.is_dir() else [path])
    if not files:
        raise AnalysisError("no SystemVerilog files found")
    return Project.from_files(files, include_dirs=include_dirs)


def _uvm_for(request: AnalysisRequest) -> UvmLibrary | None:
    if request.uvm_home is not None:
        library = library_from_path(request.uvm_home)
        if library is None:
            raise AnalysisError(f"no UVM library found under {request.uvm_home}")
        return library
    return _detected_uvm() if request.find_uvm else None


@lru_cache(maxsize=1)
def _detected_uvm() -> UvmLibrary | None:
    """Looked up once per process; the IDE's worker process lives for the whole session."""
    return find_uvm()


def warm_up() -> bool:
    """Import pyslang and find UVM ahead of the first real request (run in the worker)."""
    _detected_uvm()
    return True
