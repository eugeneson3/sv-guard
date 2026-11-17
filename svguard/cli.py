"""Command-line entry point.

    svguard check PATH... [-I DIR] [-D NAME[=VALUE]] [--exclude GLOB]
                          [--uvm-home DIR | --no-uvm] [--check-unused]
                          [--format text|json] [--fail-on error|warning|never]

Exit codes: 0 = nothing at/above --fail-on, 1 = findings at/above --fail-on, 2 = usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from svguard import __version__
from svguard.model import Finding, Severity
from svguard.runner import AnalysisError, AnalysisReport, AnalysisRequest, analyze

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2

_FAIL_THRESHOLD = {"error": Severity.ERROR, "warning": Severity.WARNING}


class UsageError(Exception):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="svguard", description="Check SystemVerilog/UVM code for common mistakes.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="check files or project directories")
    check.add_argument("paths", nargs="+", type=Path, help="files and/or directories")
    check.add_argument("-I", "--include-dir", dest="include_dirs", action="append", type=Path, default=[])
    check.add_argument("-D", "--define", dest="defines", action="append", default=[], metavar="NAME[=VALUE]")
    check.add_argument("--exclude", action="append", default=[], metavar="GLOB", help="e.g. 'third_party/**'")
    uvm = check.add_mutually_exclusive_group()
    uvm.add_argument("--uvm-home", type=Path, help="UVM source dir or Vivado install root")
    uvm.add_argument("--no-uvm", action="store_true", help="do not auto-detect a UVM library")
    check.add_argument("--check-unused", action="store_true", help="enable slang unused-* warnings")
    check.add_argument("--format", choices=("text", "json"), default="text")
    check.add_argument("--fail-on", choices=("error", "warning", "never"), default="error")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _make_output_safe()
    try:
        return _run_check(args)
    except (UsageError, AnalysisError) as exc:
        print(f"svguard: error: {exc}", file=sys.stderr)
        return EXIT_USAGE


def _run_check(args: argparse.Namespace) -> int:
    request = AnalysisRequest(
        paths=tuple(args.paths),
        exclude=tuple(args.exclude),
        include_dirs=tuple(args.include_dirs),
        defines=tuple(_parse_defines(args.defines).items()),
        uvm_home=args.uvm_home,
        find_uvm=not args.no_uvm,
        check_unused=args.check_unused,
    )
    report = analyze(request)
    if args.format == "json":
        _print_json(report)
    else:
        _print_text(report)
    return EXIT_FINDINGS if _fails(report.findings, args.fail_on) else EXIT_OK


def _parse_defines(items: Sequence[str]) -> dict[str, str | None]:
    defines: dict[str, str | None] = {}
    for item in items:
        name, sep, value = item.partition("=")
        if not name:
            raise UsageError(f"bad define: {item!r}")
        defines[name] = value if sep else None
    return defines


def _fails(findings: Sequence[Finding], fail_on: str) -> bool:
    threshold = _FAIL_THRESHOLD.get(fail_on)
    return threshold is not None and any(f.severity.rank <= threshold.rank for f in findings)


def _display(path: Path) -> str:
    cwd = Path.cwd()
    return path.relative_to(cwd).as_posix() if path.is_relative_to(cwd) else str(path)


def _print_text(report: AnalysisReport) -> None:
    for f in report.findings:
        loc = f.location
        tag = f"{f.rule_id} {f.slang_code}" if f.slang_code else f.rule_id
        print(f"{_display(loc.file)}:{loc.line}:{loc.col}: {f.severity.value}: {f.message} [{tag}]")
    counts = Counter(f.severity for f in report.findings)
    summary = (
        f"{len(report.files)} file(s) checked: {counts[Severity.ERROR]} error(s), "
        f"{counts[Severity.WARNING]} warning(s), {counts[Severity.INFO]} info"
    )
    if report.uvm is not None:
        summary += f" | UVM: {report.uvm}"
    print(summary)


def _print_json(report: AnalysisReport) -> None:
    counts = Counter(f.severity for f in report.findings)
    payload = {
        "tool": "svguard",
        "version": __version__,
        "files": [str(p) for p in report.files],
        "uvm": report.uvm,
        "summary": {s.value: counts[s] for s in Severity},
        "findings": [f.to_dict() for f in report.findings],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _make_output_safe() -> None:
    # A piped stdout on Korean Windows is cp949; never crash on an unencodable character.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(main())
