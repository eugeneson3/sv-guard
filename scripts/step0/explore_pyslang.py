"""Step 0: explore the installed pyslang API against a real SV file.

Usage:
    python scripts/step0/explore_pyslang.py examples/step0/buggy.sv
    python scripts/step0/explore_pyslang.py --api          # dump API surface only

Sections:
  1. API surface   - which submodules/classes exist in this pyslang version
  2. Parse         - SyntaxTree + syntax-level traversal (module/class names)
  3. Diagnostics   - parse, semantic (Compilation) and analysis (AnalysisManager)
  4. AST traversal - custom check: blocking in always_ff / nonblocking in always_comb
"""

from __future__ import annotations

import argparse
import sys

import pyslang
from pyslang import analysis, ast, syntax


def public(obj) -> list[str]:
    return [n for n in dir(obj) if not n.startswith("_")]


def section(title: str) -> None:
    print(f"\n{'=' * 8} {title} {'=' * (60 - len(title))}")


def dump_api() -> None:
    section("1. API surface")
    print("pyslang version:", getattr(pyslang, "__version__", "?"))
    for sub in ("syntax", "ast", "analysis", "parsing", "driver"):
        print(f"pyslang.{sub}: {len(public(getattr(pyslang, sub)))} names")
    for label, cls in [
        ("syntax.SyntaxTree", syntax.SyntaxTree),
        ("syntax.SyntaxNode", syntax.SyntaxNode),
        ("ast.Compilation", ast.Compilation),
        ("ast.Symbol", ast.Symbol),
        ("analysis.AnalysisManager", analysis.AnalysisManager),
        ("pyslang.Diagnostic", pyslang.Diagnostic),
        ("pyslang.DiagnosticEngine", pyslang.DiagnosticEngine),
        ("pyslang.SourceManager", pyslang.SourceManager),
    ]:
        print(f"\n{label}:\n  " + " ".join(public(cls)))
    print("\nSymbol.visit:", ast.Symbol.visit.__doc__.splitlines()[0])


def parse_section(path: str) -> syntax.SyntaxTree:
    section("2. Parse")
    tree = syntax.SyntaxTree.fromFile(path)
    modules: list[str] = []
    classes: list[tuple[str, str | None]] = []

    def on_module(node):
        modules.append(node.header.name.valueText)

    def on_class(node):
        base = node.extendsClause.baseName if node.extendsClause else None
        # str(node) includes leading trivia (whitespace/comments); strip it.
        classes.append((node.name.valueText, str(base).strip() if base else None))

    tree.root.visit(
        lookup_table={
            syntax.SyntaxKind.ModuleDeclaration: on_module,
            syntax.SyntaxKind.ClassDeclaration: on_class,
        }
    )
    print("modules:", modules)
    print("classes:", classes)
    return tree


def diag_section(tree: syntax.SyntaxTree) -> ast.Compilation:
    section("3. Diagnostics")
    sm = tree.sourceManager
    engine = pyslang.DiagnosticEngine(sm)

    comp = ast.Compilation()
    comp.addSyntaxTree(tree)
    parse_diags = list(comp.getParseDiagnostics())
    semantic_diags = list(comp.getSemanticDiagnostics())

    # AnalysisManager needs a frozen, fully elaborated compilation.
    comp.freeze()
    opts = analysis.AnalysisOptions()
    opts.flags = analysis.AnalysisFlags.CheckUnused
    manager = analysis.AnalysisManager(opts)
    manager.analyze(comp)
    analysis_diags = list(manager.getDiagnostics())

    for stage, diags in (("parse", parse_diags), ("semantic", semantic_diags), ("analysis", analysis_diags)):
        print(f"[{stage}] {len(diags)} diagnostic(s)")
        for d in diags:
            loc = d.location
            sev = engine.getSeverity(d.code, loc).name
            print(
                f"  {sm.getFileName(loc)}:{sm.getLineNumber(loc)}:{sm.getColumnNumber(loc)}"
                f" {sev:7} {str(d.code):34} -W{engine.getOptionName(d.code) or '-':24}"
                f" {engine.formatMessage(d)}"
            )
    return comp


def ast_section(comp: ast.Compilation, sm: pyslang.SourceManager) -> None:
    section("4. AST traversal (custom rule prototype)")
    hits: list[tuple[str, pyslang.SourceLocation]] = []

    def on_proc(proc):
        kind = proc.procedureKind

        def on_assign(expr):
            if kind == ast.ProceduralBlockKind.AlwaysFF and not expr.isNonBlocking:
                hits.append(("blocking '=' in always_ff", expr.sourceRange.start))
            elif kind == ast.ProceduralBlockKind.AlwaysComb and expr.isNonBlocking:
                hits.append(("nonblocking '<=' in always_comb", expr.sourceRange.start))

        proc.body.visit(lookup_table={ast.ExpressionKind.Assignment: on_assign})

    comp.getRoot().visit(lookup_table={ast.SymbolKind.ProceduralBlock: on_proc})
    for msg, loc in hits:
        print(f"  {sm.getLineNumber(loc)}:{sm.getColumnNumber(loc)}  {msg}")
    if not hits:
        print("  (none)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", nargs="?")
    parser.add_argument("--api", action="store_true", help="dump API surface")
    args = parser.parse_args()

    if args.api or not args.file:
        dump_api()
    if args.file:
        tree = parse_section(args.file)
        comp = diag_section(tree)
        ast_section(comp, tree.sourceManager)
    return 0


if __name__ == "__main__":
    sys.exit(main())
