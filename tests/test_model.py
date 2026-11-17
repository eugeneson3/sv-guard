from pathlib import Path

from svguard.model import Finding, Location, Severity


def _finding(file="a.sv", line=1, col=1, severity=Severity.WARNING, rule_id="SVG-C000"):
    return Finding(rule_id, severity, "msg", Location.point(Path(file), line, col))


def test_severity_rank_orders_most_severe_first():
    ranked = sorted(Severity, key=lambda s: s.rank)
    assert ranked == [Severity.ERROR, Severity.WARNING, Severity.INFO, Severity.HINT]


def test_explain_id_defaults_to_rule_id():
    assert _finding(rule_id="SVG-C001").explain_id == "SVG-C001"


def test_sort_key_orders_by_file_line_col_then_severity():
    findings = [
        _finding("b.sv", 1, 1),
        _finding("a.sv", 2, 1),
        _finding("a.sv", 1, 5, Severity.WARNING),
        _finding("a.sv", 1, 5, Severity.ERROR),
    ]
    ordered = sorted(findings, key=lambda f: f.sort_key)
    assert [(str(f.location.file), f.location.line, f.severity) for f in ordered] == [
        ("a.sv", 1, Severity.ERROR),
        ("a.sv", 1, Severity.WARNING),
        ("a.sv", 2, Severity.WARNING),
        ("b.sv", 1, Severity.WARNING),
    ]


def test_dict_round_trip():
    original = Finding(
        "SVG-C000",
        Severity.ERROR,
        "expected ';'",
        Location(Path("x.sv"), 3, 4, 3, 9),
        fix_hint="add ';'",
        origin="slang",
        slang_code="ExpectedToken",
    )
    assert Finding.from_dict(original.to_dict()) == original
