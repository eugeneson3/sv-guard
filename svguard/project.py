"""Collect the SystemVerilog files that make up a project.

Classification:
  * compilation units: .sv / .v files that no other project file `include`s
  * headers:           .svh / .vh files, plus .sv/.v files pulled in via `include
                       (common in UVM: tb_pkg.sv does `include "my_driver.sv")
Compiling an included file on its own would duplicate its classes and break on
names it expects from the including package, so it is never a compilation unit.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from svguard.textio import read_source

SOURCE_SUFFIXES = frozenset({".sv", ".v"})
HEADER_SUFFIXES = frozenset({".svh", ".vh"})

DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".*",  # hidden: .git, .venv, .Xil, .svguard ...
    "__pycache__",
    "node_modules",
    "venv",
    "xsim.dir",
    # Vivado project outputs (generated netlists, simulation copies, IP wrappers)
    "*.cache",
    "*.runs",
    "*.sim",
    "*.gen",
    "*.hw",
    "*.ip_user_files",
    "*.srcs/*/ip/**",
)

_INCLUDE_RE = re.compile(r'^[ \t]*`include[ \t]+"([^"\n]+)"', re.MULTILINE)


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """`*` and `?` stay within one path component, `**` spans components."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out))


class PathFilter:
    """Exclude matcher for paths relative to the project root (posix separators).

    A pattern without `/` matches any single path component (`build`, `*.cache`).
    A pattern with `/` matches the whole relative path (`third_party/**`).
    """

    def __init__(self, patterns: Iterable[str]) -> None:
        self._component: list[re.Pattern[str]] = []
        self._full: list[re.Pattern[str]] = []
        for raw in patterns:
            pattern = raw.strip().removeprefix("./").rstrip("/")
            if not pattern:
                continue
            target = self._full if "/" in pattern else self._component
            target.append(_glob_to_regex(pattern))

    def excluded(self, rel_posix: str, *, is_dir: bool) -> bool:
        parts = rel_posix.split("/")
        if any(rx.fullmatch(part) for rx in self._component for part in parts):
            return True
        candidate = f"{rel_posix}/" if is_dir else rel_posix
        return any(rx.fullmatch(candidate) for rx in self._full)


def _walk(root: Path, path_filter: PathFilter) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root).as_posix()
        prefix = "" if rel == "." else f"{rel}/"
        dirnames[:] = sorted(d for d in dirnames if not path_filter.excluded(prefix + d, is_dir=True))
        for name in sorted(filenames):
            if not path_filter.excluded(prefix + name, is_dir=False):
                yield Path(dirpath, name)


def _unique(paths: Iterable[Path]) -> tuple[Path, ...]:
    seen: dict[str, Path] = {}
    for path in paths:
        seen.setdefault(os.path.normcase(str(path)), path)
    return tuple(seen.values())


@dataclass(frozen=True)
class Project:
    root: Path
    sources: tuple[Path, ...]  # compilation units, sorted
    headers: tuple[Path, ...]  # include-only files, sorted
    include_dirs: tuple[Path, ...]

    @property
    def files(self) -> tuple[Path, ...]:
        return tuple(sorted((*self.sources, *self.headers)))

    @classmethod
    def discover(
        cls,
        root: Path | str,
        *,
        exclude: Sequence[str] = (),
        include_dirs: Sequence[Path] = (),
        default_excludes: bool = True,
    ) -> Project:
        root = Path(root).resolve()
        patterns = (*DEFAULT_EXCLUDES, *exclude) if default_excludes else tuple(exclude)
        suffixes = SOURCE_SUFFIXES | HEADER_SUFFIXES
        files = [p for p in _walk(root, PathFilter(patterns)) if p.suffix.lower() in suffixes]
        return cls._build(root, files, include_dirs)

    @classmethod
    def from_files(cls, files: Sequence[Path | str], *, include_dirs: Sequence[Path] = ()) -> Project:
        paths = [Path(f).resolve() for f in files]
        if not paths:
            raise ValueError("no files given")
        root = Path(os.path.commonpath([p.parent for p in paths]))
        return cls._build(root, paths, include_dirs)

    @classmethod
    def _build(cls, root: Path, files: Sequence[Path], include_dirs: Sequence[Path]) -> Project:
        files = _unique(files)
        headers = [p for p in files if p.suffix.lower() in HEADER_SUFFIXES]
        sources = [p for p in files if p.suffix.lower() not in HEADER_SUFFIXES]
        inc_dirs = _unique(
            [*(Path(d).resolve() for d in include_dirs), root, *sorted({h.parent for h in headers})]
        )
        included = _included_sources(sources, inc_dirs)
        return cls(
            root=root,
            sources=tuple(sorted(p for p in sources if p not in included)),
            headers=tuple(sorted([*headers, *included])),
            include_dirs=inc_dirs,
        )


def _included_sources(sources: Sequence[Path], include_dirs: Sequence[Path]) -> set[Path]:
    """Sources that some other source pulls in with `include "..."`."""
    by_key = {os.path.normcase(str(p)): p for p in sources}
    included: set[Path] = set()
    for src in sources:
        try:
            text = read_source(src).text
        except OSError:
            continue
        for name in _INCLUDE_RE.findall(text):
            for base in (src.parent, *include_dirs):
                key = os.path.normcase(os.path.normpath(base / name))
                if key in by_key:
                    if by_key[key] != src:
                        included.add(by_key[key])
                    break
    return included
