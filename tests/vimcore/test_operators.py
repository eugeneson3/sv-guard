import pytest
from vimtest import FakeClipboard, make, run, show


@pytest.mark.parametrize(
    ("text", "keys", "expected"),
    [
        ("foo |bar baz", "dw", "foo |baz"),
        ("foo |bar\nbaz", "dw", "foo| \nbaz"),  # dw on the last word stops at the line end
        ("|foo bar baz", "d2w", "|baz"),
        ("|foo bar baz", "2dw", "|baz"),
        ("foo |bar baz", "de", "foo | baz"),
        ("foo |bar baz", "db", "|bar baz"),
        ("foo |bar baz", "d$", "foo| "),
        ("foo |bar baz", "D", "foo| "),
        ("foo |bar baz", "d0", "|bar baz"),
        ("a\n|b\nc", "dd", "a\n|c"),
        ("a\nb\n|c", "dd", "a\n|b"),
        ("|a", "dd", "|"),
        ("a\n|b\nc", "5dd", "|a"),  # count beyond the end deletes to the end
        ("a\n|b\nc\nd", "dj", "a\n|d"),
        ("a\nb\n|c", "dk", "|a"),
        ("a\n|b\nc", "dG", "|a"),
        ("a\nb\n|c", "dgg", "|"),
        ("ab|cd", "x", "ab|d"),
        ("ab|cd", "3x", "a|b"),
        ("abc|d", "x", "ab|c"),
        ("ab|cd", "X", "a|cd"),
        ("ab|cd", "<Del>", "ab|d"),
        ("|", "x", "|"),
        ("call(a, |b, c)", "dt)", "call(a, |)"),
        ("call(a, |b, c)", "df,", "call(a, | c)"),
        ("x = |(a + (b)) + c", "d%", "x = | + c"),
    ],
)
def test_delete(text, keys, expected):
    assert run(text, keys) == expected


def test_delete_with_search_motion():
    assert run("|one two three", "d/thr<CR>") == "|three"


def test_exclusive_motion_to_column_zero_becomes_linewise():
    # :help exclusive-linewise
    assert run("|foo\nbar\nbaz", "d/baz<CR>") == "|baz"


@pytest.mark.parametrize(
    ("text", "keys", "expected"),
    [
        ("foo |bar baz", "cwX<Esc>", "foo |X baz"),  # cw acts like ce
        ("foo |bar baz", "c2wX<Esc>", "foo |X"),
        ("foo| bar", "cwX<Esc>", "foo|Xbar"),  # cw on blanks behaves like dw
        ("fo|o bar", "cwX<Esc>", "fo|X bar"),  # on the last char of a word: just that char
        ("foo |bar baz", "CX<Esc>", "foo |X"),
        ("ab|cd", "sX<Esc>", "ab|Xd"),
        ("    fo|o\nbar", "ccX<Esc>", "    |X\nbar"),  # cc keeps the indent
        ("    fo|o\nbar", "SX<Esc>", "    |X\nbar"),
    ],
)
def test_change(text, keys, expected):
    assert run(text, keys) == expected


@pytest.mark.parametrize(
    ("text", "keys", "expected"),
    [
        ("foo |bar baz", "ywP", "foo bar| bar baz"),
        ("foo |bar", "ywP", "foo ba|rbar"),  # cursor ends on the last pasted character
        ("|a\nb", "yyp", "a\n|a\nb"),
        ("a\n|b", "yyP", "a\n|b\nb"),
        ("|a\nb", "Yjp", "a\nb\n|a"),
        ("|a\nb", "yjGp", "a\nb\n|a\nb"),
        ("|ab", "yl3p", "aaa|ab"),
        ("|ab", "x$p", "b|a"),
        ("    |x\ny", "yyjp", "    x\ny\n    |x"),
    ],
)
def test_yank_and_put(text, keys, expected):
    assert run(text, keys) == expected


def test_yank_moves_cursor_to_start_of_range():
    assert run("foo b|ar", "yb") == "foo |bar"


def test_put_multiline_charwise_leaves_cursor_at_start():
    engine = make("|ab\ncd")
    engine.feed_keys("vjy")  # charwise "ab\nc"
    engine.feed_keys("G$p")
    assert show(engine) == "ab\ncd|ab\nc"


def test_put_from_empty_register_is_an_error():
    result = make("|a").feed_keys("p")
    assert result.message.error and "E353" in result.message.text


@pytest.mark.parametrize(
    ("text", "keys", "shiftwidth", "expected"),
    [
        ("|a\nb", ">>", 0, "    |a\nb"),  # shiftwidth 0 = tabstop (4)
        ("|a\nb", "2>>", 0, "    |a\n    b"),
        ("|a\n\nb", ">2j", 0, "    |a\n\n    b"),  # blank lines stay blank
        ("      |a", "<<", 0, "  |a"),
        ("  |a", "<<", 0, "|a"),
        ("|a", ">>", 2, "  |a"),
    ],
)
def test_shift(text, keys, shiftwidth, expected):
    assert run(text, keys, shiftwidth=shiftwidth) == expected


def test_shift_with_tabs_when_noexpandtab():
    assert run("|a", ">>>>", expandtab=False, tabstop=4) == "\t\t|a"


def test_line_count_report():
    result = make("|1\n2\n3\n4").feed_keys("3dd")
    assert result.message.text == "3 fewer lines"


class TestRegisters:
    def test_named_register(self):
        assert run("|a\nb", '"ayyj"ap') == "a\nb\n|a"

    def test_uppercase_appends(self):
        assert run("|a\nb\nc", '"ayyj"Ayy"ap') == "a\nb\n|a\nb\nc"

    def test_black_hole_keeps_unnamed(self):
        assert run("|a\nb", 'yyj"_ddp') == "a\n|a"

    def test_zero_register_holds_last_yank(self):
        assert run("|a\nb\nc", 'yyjdd"0p') == "a\nc\n|a"

    def test_invalid_register(self):
        result = make("|a").feed_keys('"!yy')
        assert "E354" in result.message.text

    def test_plus_register_uses_clipboard(self):
        clipboard = FakeClipboard()
        engine = make("|foo bar", clipboard=clipboard)
        engine.feed_keys('"+yw')
        assert clipboard.text == "foo "
        clipboard.text = "XY"
        engine.feed_keys('$"+p')
        assert show(engine) == "foo barX|Y"

    def test_linewise_clipboard_round_trip(self):
        clipboard = FakeClipboard()
        engine = make("|a\nb", clipboard=clipboard)
        engine.feed_keys('"+yy')
        assert clipboard.text == "a\n"
        engine.feed_keys('j"+p')
        assert show(engine) == "a\nb\n|a"
