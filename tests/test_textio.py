import codecs

import pytest

from svguard.textio import LineIndex, decode_source, detect_eol, normalize_eol, write_source


def test_detect_eol_majority():
    assert detect_eol("a\r\nb\r\nc\n") == "\r\n"
    assert detect_eol("a\nb\nc\r\n") == "\n"
    assert detect_eol("no newline") == "\n"


def test_normalize_eol():
    assert normalize_eol("a\r\nb\rc\n") == "a\nb\nc\n"


@pytest.mark.parametrize(
    ("encoding", "eol", "expected"),
    [
        ("utf-8", "\n", "// 한글\nx\n".encode()),
        ("utf-8", "\r\n", "// 한글\r\nx\r\n".encode()),
        ("cp949", "\r\n", "// 한글\r\nx\r\n".encode("cp949")),
        ("utf-8-sig", "\n", codecs.BOM_UTF8 + "// 한글\nx\n".encode()),
    ],
)
def test_write_source_keeps_encoding_and_eol(tmp_path, encoding, eol, expected):
    path = tmp_path / "f.sv"
    write_source(path, "// 한글\nx\n", encoding, eol)
    assert path.read_bytes() == expected
    assert [p.name for p in tmp_path.iterdir()] == ["f.sv"]  # temp file cleaned up


def test_write_source_unencodable_leaves_file_untouched(tmp_path):
    path = tmp_path / "f.sv"
    path.write_bytes(b"original")
    with pytest.raises(UnicodeEncodeError):
        write_source(path, "emoji \U0001f600", "cp949")
    assert path.read_bytes() == b"original"


def test_decode_utf8():
    assert decode_source("// 한글\n".encode()).encoding == "utf-8"


def test_decode_utf8_bom_is_stripped():
    src = decode_source(codecs.BOM_UTF8 + b"module m; endmodule\n")
    assert src.encoding == "utf-8-sig"
    assert src.text.startswith("module")


def test_decode_falls_back_to_cp949():
    src = decode_source("// 한글 주석\n".encode("cp949"))
    assert src.encoding == "cp949"
    assert src.text == "// 한글 주석\n"


def test_line_index_counts_characters_not_bytes():
    text = "module m;\n/* 가나다 */ assign o = x;\n"
    index = LineIndex.from_text(text)
    byte_offset = text.encode().index(b"x;")
    assert index.position(byte_offset) == (2, text.splitlines()[1].index("x") + 1)


def test_line_index_cp949_bytes():
    data = "a\n/*가*/ b\n".encode("cp949")
    index = LineIndex(data, "cp949")
    assert index.position(data.index(b"b")) == (2, 7)


def test_line_index_bom_on_first_line():
    data = codecs.BOM_UTF8 + b"ab"
    assert LineIndex(data, "utf-8-sig").position(len(codecs.BOM_UTF8) + 1) == (1, 2)


def test_line_index_clamps_out_of_range_offsets():
    index = LineIndex.from_text("ab\ncd")
    assert index.position(-5) == (1, 1)
    assert index.position(999) == (2, 3)
