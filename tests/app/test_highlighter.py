import pytest
from PySide6.QtGui import QTextDocument

from app.editor.sv_highlighter import _PALETTE, SvHighlighter

LIGHT = {name: colors[0] for name, colors in _PALETTE.items()}


@pytest.fixture
def highlight(qapp):
    """Return [(text, kind)] spans for each line of `source`."""
    doc = QTextDocument()
    doc.documentLayout()  # without a layout Qt never emits contentsChange, so nothing gets highlighted
    highlighter = SvHighlighter(doc, dark=False)
    by_color = {color: kind for kind, color in LIGHT.items()}

    def run(source: str) -> list[list[tuple[str, str]]]:
        doc.setPlainText(source)
        lines = []
        block = doc.begin()
        while block.isValid():
            spans = [
                (block.text()[r.start : r.start + r.length], by_color[r.format.foreground().color().name()])
                for r in sorted(block.layout().formats(), key=lambda r: r.start)
            ]
            lines.append(spans)
            block = block.next()
        return lines

    run.highlighter = highlighter  # keep alive
    return run


def test_keywords_types_and_identifiers(highlight):
    (line,) = highlight("module top(input logic clk);")
    assert line == [("module", "keyword"), ("input", "keyword"), ("logic", "type")]


def test_comment_inside_string_is_not_a_comment(highlight):
    (line,) = highlight('$display("a // b"); // real')
    assert line == [("$display", "system"), ('"a // b"', "string"), ("// real", "comment")]


def test_numbers_and_directives(highlight):
    (line,) = highlight("`define W 8'hFF + 'b1010 + '0 + 10ns + 3.5e2 + a1")
    assert line == [
        ("`define", "directive"),
        ("8'hFF", "number"),
        ("'b1010", "number"),
        ("'0", "number"),
        ("10ns", "number"),
        ("3.5e2", "number"),
    ]


def test_block_comment_spans_lines(highlight):
    lines = highlight("logic a; /* start\nstill comment begin\nend */ wire b;")
    assert lines[0] == [("logic", "type"), ("/* start", "comment")]
    assert lines[1] == [("still comment begin", "comment")]
    assert lines[2] == [("end */", "comment"), ("wire", "type")]


def test_unterminated_string_stops_at_line_end(highlight):
    lines = highlight('x = "oops\nmodule m;')
    assert lines[0] == [('"oops', "string")]
    assert lines[1] == [("module", "keyword")]
