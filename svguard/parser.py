"""pyslang wrapper: compile sources into a frozen slang Compilation and report
slang's own diagnostics as SVG-C000 findings.

Every call used here was verified against pyslang 12 (scripts/step0/explore_pyslang.py):
    syntax.SyntaxTree.fromText(text, source_manager, name, path, bag)
    ast.Compilation.addSyntaxTree / getAllDiagnostics / freeze
    analysis.AnalysisManager(options).analyze(compilation) / getDiagnostics
Diagnostics come from three stages: parse, semantic (elaboration) and analysis
(data-flow: InferredLatch etc.). Analysis requires a frozen compilation.

Importing this module on Windows switches the C runtime LC_CTYPE to UTF-8; see
_enable_utf8_paths().
"""

from __future__ import annotations

import locale
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import pyslang
from pyslang import analysis, ast, parsing, syntax

from svguard.model import Finding, Location, Severity
from svguard.project import Project
from svguard.textio import LineIndex, decode_source, read_source
from svguard.uvm import UvmLibrary

SLANG_RULE_ID = "SVG-C000"

UVM_MISSING_MESSAGE = (
    "UVM library not found, so slang checks are skipped for this file. "
    "Install Vivado, set UVM_HOME, or pass --uvm-home."
)

_UVM_USE_RE = re.compile(r'\bimport\s+uvm_pkg\s*::|`include\s+"uvm_macros\.svh"')
_MAX_INCLUDE_DEPTH = 64

# slang's "default" warning group is conservative and leaves out classic beginner bugs
# (latches, empty port connections). These come from its "extra"/"conversion" groups.
LEARNING_WARNINGS = (
    "InferredLatch",
    "InferredComb",
    "EmptyInputPortConn",
    "CaseIncomplete",
    "CaseEnum",  # an FSM case that forgets a state (and has no default)
    "CaseDup",
    "CaseOverlap",
    "DanglingElse",
    "PortWidthTruncate",
    "PortWidthExpand",
    "IncompleteReturn",
    "MissingReturn",
    "DivisionByZero",
    "LogicalNotParentheses",
    "BitwiseRelPrecedence",
)

_SEVERITY = {
    pyslang.DiagnosticSeverity.Note: Severity.INFO,
    pyslang.DiagnosticSeverity.Warning: Severity.WARNING,
    pyslang.DiagnosticSeverity.Error: Severity.ERROR,
    pyslang.DiagnosticSeverity.Fatal: Severity.ERROR,
}


def _enable_utf8_paths() -> None:
    """pyslang on Windows converts path strings with the C runtime code page.

    With the default ANSI page (cp949 on Korean Windows) every non-ASCII path fails
    with "No mapping for the Unicode character exists in the target multi-byte code
    page". A UTF-8 LC_CTYPE makes the conversion lossless. Python's own encodings
    (open(), console) do not depend on LC_CTYPE, so this is safe process-wide.
    """
    if sys.platform != "win32":
        return
    try:
        locale.setlocale(locale.LC_CTYPE, ".UTF-8")
    except locale.Error:
        pass  # Windows older than 10 1803: non-ASCII paths stay unsupported


_enable_utf8_paths()


@dataclass(frozen=True)
class ParseOptions:
    include_dirs: Sequence[Path] = ()
    defines: Mapping[str, str | None] = field(default_factory=dict)
    uvm: UvmLibrary | None = None  # loaded only if some source uses UVM
    check_unused: bool = False  # slang -Wunused-*: noisy for UVM (run_phase looks "unused")


def compile_project(project: Project, options: ParseOptions | None = None) -> ParsedDesign:
    options = options or ParseOptions()
    options = replace(options, include_dirs=(*project.include_dirs, *options.include_dirs))
    return compile_sources(project.sources, options)


def compile_sources(paths: Sequence[Path | str], options: ParseOptions | None = None) -> ParsedDesign:
    units = []
    for path in paths:
        resolved = Path(path).resolve()
        units.append((resolved, read_source(resolved).text))
    return _compile(units, options or ParseOptions())


def compile_text(text: str, name: str = "input.sv", options: ParseOptions | None = None) -> ParsedDesign:
    """Compile in-memory text. `name` is resolved against the cwd and need not exist."""
    return _compile([(Path(name).resolve(), text)], options or ParseOptions())


def _compile(units: Sequence[tuple[Path, str]], options: ParseOptions) -> ParsedDesign:
    sm = pyslang.SourceManager()
    for directory in options.include_dirs:
        if Path(directory).is_dir():  # slang raises on missing dirs
            sm.addUserDirectories(str(directory))
    bag = _make_bag(options)

    uvm_users: dict[str, tuple[Path, int, int]] = {}
    for path, text in units:
        if match := _UVM_USE_RE.search(text):
            line = text.count("\n", 0, match.start()) + 1
            col = match.start() - (text.rfind("\n", 0, match.start()) + 1) + 1
            uvm_users[_path_key(path)] = (path, line, col)
    uvm = options.uvm if uvm_users else None

    trees = []
    if uvm is not None:
        sm.addUserDirectories(str(uvm.include_dir))
        trees.append(syntax.SyntaxTree.fromFile(str(uvm.package_file), sm, bag))
    texts: dict[str, str] = {}
    for path, text in units:
        texts[_path_key(path)] = text
        # fromText (not fromFile): we already decoded the bytes, so cp949 files work too.
        trees.append(syntax.SyntaxTree.fromText(text, sm, path.name, str(path), bag))

    compilation = ast.Compilation()
    for tree in trees:
        compilation.addSyntaxTree(tree)
    diagnostics = list(compilation.getAllDiagnostics())  # forces full elaboration
    compilation.freeze()

    analysis_options = analysis.AnalysisOptions()
    if options.check_unused:
        analysis_options.flags = analysis.AnalysisFlags.CheckUnused
    manager = analysis.AnalysisManager(analysis_options)
    manager.analyze(compilation)
    diagnostics += list(manager.getDiagnostics())

    return ParsedDesign(
        compilation=compilation,
        source_manager=sm,
        trees=trees,
        texts=texts,
        diagnostics=diagnostics,
        uvm=uvm,
        uvm_missing=uvm_users if uvm is None else {},
        keepalive=(manager, bag),
    )


def _make_bag(options: ParseOptions) -> pyslang.Bag:
    pp = parsing.PreprocessorOptions()
    pp.predefines = [name if value is None else f"{name}={value}" for name, value in options.defines.items()]
    return pyslang.Bag([pp])


def _path_key(path: Path | str) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _code_name(code: pyslang.DiagCode) -> str:
    text = str(code)  # "DiagCode(InferredLatch)"
    return text[len("DiagCode(") : -1] if text.startswith("DiagCode(") else text


class ParsedDesign:
    """A frozen, fully elaborated slang compilation plus what is needed to report on it.

    Rules (Step 5) walk `compilation` and use `location()` to turn slang source
    locations into character-based Locations, exactly like slang diagnostics do.
    """

    def __init__(
        self,
        *,
        compilation: ast.Compilation,
        source_manager: pyslang.SourceManager,
        trees: list[syntax.SyntaxTree],
        texts: dict[str, str],
        diagnostics: list[pyslang.Diagnostic],
        uvm: UvmLibrary | None,
        uvm_missing: dict[str, tuple[Path, int, int]],
        keepalive: tuple[object, ...] = (),
    ) -> None:
        self.compilation = compilation
        self.source_manager = source_manager
        self.trees = trees  # must outlive the compilation
        self.uvm = uvm
        self._texts = texts
        self._diagnostics = diagnostics
        self._uvm_missing = uvm_missing
        self._keepalive = keepalive  # diagnostics may reference memory owned by these
        self._library_dirs = (_path_key(uvm.include_dir),) if uvm else ()
        self._engine = pyslang.DiagnosticEngine(source_manager)
        # A fresh engine enables every warning (thousands inside UVM alone); start from slang's defaults.
        extra = [self._engine.getOptionName(getattr(pyslang.Diags, name)) for name in LEARNING_WARNINGS]
        self._engine.setWarningOptions(["default", *filter(None, extra)])
        self._line_indexes: dict[int, LineIndex | None] = {}

    def findings(self) -> list[Finding]:
        out = [
            Finding(SLANG_RULE_ID, Severity.INFO, UVM_MISSING_MESSAGE, Location.point(path, line, col))
            for path, line, col in self._uvm_missing.values()
        ]
        seen: set[tuple[object, int, int]] = set()
        for diag in self._diagnostics:
            key = (diag.code, diag.location.buffer.id, diag.location.offset)
            if key in seen:
                continue
            seen.add(key)
            if (finding := self._convert(diag)) is not None:
                out.append(finding)
        return sorted(out, key=lambda f: f.sort_key)

    def location(
        self, start: pyslang.SourceLocation, end: pyslang.SourceLocation | None = None
    ) -> Location | None:
        """Character-based Location for a slang location (None if not in a real file)."""
        path = self._file_path(start)
        index = self._line_index(start) if path is not None else None
        if path is None or index is None:
            return None
        line, col = index.position(start.offset)
        end_line, end_col = line, col
        if end is not None and end.buffer.id == start.buffer.id and end.offset >= start.offset:
            end_line, end_col = index.position(end.offset)
        return Location(path, line, col, end_line, end_col)

    # -- internals ---------------------------------------------------------

    def _convert(self, diag: pyslang.Diagnostic) -> Finding | None:
        severity = self._engine.getSeverity(diag.code, diag.location)
        if severity == pyslang.DiagnosticSeverity.Ignored:
            return None
        loc = self._user_location(diag.location, is_error=_SEVERITY[severity] is Severity.ERROR)
        if loc is None or self._root_key(loc) in self._uvm_missing:
            return None
        location = self.location(loc, self._range_end(diag, loc))
        if location is None:
            return None
        return Finding(
            rule_id=SLANG_RULE_ID,
            severity=_SEVERITY[severity],
            message=self._engine.formatMessage(diag),
            location=location,
            origin="slang",
            slang_code=_code_name(diag.code),
        )

    def _user_location(self, loc: pyslang.SourceLocation, *, is_error: bool) -> pyslang.SourceLocation | None:
        """Where the user should look, or None for diagnostics that belong to library code.

        The spelling location wins when it is in user code (this covers macro arguments
        the user typed). Errors spelled inside a library macro body are moved to the
        user's expansion site, since a correct library only errors on bad usage.
        Warnings spelled inside library macros are library noise and are dropped.
        """
        if not self._valid(loc):
            return None
        sm = self.source_manager
        candidates = [sm.getFullyOriginalLoc(loc)]
        if is_error:
            candidates.append(sm.getFullyExpandedLoc(loc))
        for candidate in candidates:
            path = self._file_path(candidate)
            if path is not None and not self._is_library(path):
                return candidate
        return None

    @staticmethod
    def _range_end(diag: pyslang.Diagnostic, loc: pyslang.SourceLocation) -> pyslang.SourceLocation | None:
        for rng in diag.ranges:
            start, end = rng.start, rng.end
            if start.buffer.id == loc.buffer.id and start.offset <= loc.offset <= end.offset:
                return end
        return None

    def _root_key(self, loc: pyslang.SourceLocation) -> str | None:
        """Path key of the compilation unit that (transitively) includes `loc`."""
        sm = self.source_manager
        for _ in range(_MAX_INCLUDE_DEPTH):
            if not sm.isIncludedFileLoc(loc):
                break
            loc = sm.getIncludedFrom(loc.buffer)
        path = self._file_path(loc)
        return _path_key(path) if path is not None else None

    def _valid(self, loc: pyslang.SourceLocation) -> bool:
        return 0 < loc.buffer.id < pyslang.SourceLocation.NoLocation.buffer.id

    def _file_path(self, loc: pyslang.SourceLocation) -> Path | None:
        if not self._valid(loc):
            return None
        path = Path(self.source_manager.getFullPath(loc.buffer))
        return path if path.is_absolute() else None  # macro buffers report "." etc.

    def _is_library(self, path: Path) -> bool:
        key = _path_key(path)
        return any(key == lib or key.startswith(lib + os.sep) for lib in self._library_dirs)

    def _line_index(self, loc: pyslang.SourceLocation) -> LineIndex | None:
        buffer_id = loc.buffer.id
        if buffer_id not in self._line_indexes:
            self._line_indexes[buffer_id] = self._build_line_index(loc)
        return self._line_indexes[buffer_id]

    def _build_line_index(self, loc: pyslang.SourceLocation) -> LineIndex | None:
        path = self._file_path(loc)
        if path is None:
            return None
        text = self._texts.get(_path_key(path))
        if text is not None:
            return LineIndex.from_text(text)
        try:  # headers are read by slang itself, so offsets index the raw bytes
            data = path.read_bytes()
        except OSError:
            return None
        return LineIndex(data, decode_source(data).encoding)
