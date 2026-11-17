import pytest
from vimtest import make, run, show


@pytest.mark.parametrize(
    ("text", "keys", "expected"),
    [
        ("ab|cd", "h", "a|bcd"),
        ("|abcd", "h", "|abcd"),
        ("ab|cd", "l", "abc|d"),
        ("abc|d", "l", "abc|d"),  # cannot move past the last character
        ("|abcd", "9l", "abc|d"),
        ("ab|cd", "<Left><Right><Right>", "abc|d"),
        ("a|b\ncd\nef", "2j", "ab\ncd\ne|f"),
        ("ab\ncd\ne|f", "k", "ab\nc|d\nef"),
        ("|a\nb", "9j", "a\n|b"),  # count is clamped
        ("a\n|b", "j", "a\n|b"),  # j on the last line fails
        ("  ab|c", "0", "|  abc"),
        ("  ab|c", "^", "  |abc"),
        ("|abc", "$", "ab|c"),
        ("|ab\ncdef", "2$", "ab\ncde|f"),
        ("a\n|b\nc", "gg", "|a\nb\nc"),
        ("|a\nb\n  c", "G", "a\nb\n  |c"),
        ("|a\nb\nc", "2G", "a\n|b\nc"),
        ("|a\nb\nc", "3gg", "a\nb\n|c"),
        ("a\n  b\n|c", "-", "a\n  |b\nc"),
        ("|a\n  b", "+", "a\n  |b"),
        ("|a\n  b", "<CR>", "a\n  |b"),
    ],
)
def test_basic_motions(text, keys, expected):
    assert run(text, keys) == expected


def test_vertical_motion_remembers_the_column():
    assert run("abc|def\nx\nabcdef", "jj") == "abcdef\nx\nabc|def"


def test_dollar_sticks_to_line_end():
    assert run("|ab\nabcdef\nabc", "$jj") == "ab\nabcdef\nab|c"


@pytest.mark.parametrize(
    ("text", "keys", "expected"),
    [
        ("|foo bar baz", "w", "foo |bar baz"),
        ("|foo bar baz", "2w", "foo bar |baz"),
        ("|foo.bar baz", "w", "foo|.bar baz"),
        ("|foo.bar baz", "W", "foo.bar |baz"),
        ("|foo\n\nbar", "w", "foo\n|\nbar"),  # an empty line is a word
        ("|foo\n  bar", "w", "foo\n  |bar"),
        ("foo |bar", "w", "foo ba|r"),  # last word of the file: moves to its end
        ("|한글abc", "w", "한글|abc"),  # Hangul and ASCII are different word classes
        ("foo bar |baz", "b", "foo |bar baz"),
        ("foo bar b|az", "b", "foo bar |baz"),
        ("foo\n|bar", "b", "|foo\nbar"),
        ("foo.bar |baz", "B", "|foo.bar baz"),
        ("|foo bar", "e", "fo|o bar"),
        ("fo|o bar", "e", "foo ba|r"),
        ("|foo.bar", "E", "foo.ba|r"),
    ],
)
def test_word_motions(text, keys, expected):
    assert run(text, keys) == expected


@pytest.mark.parametrize(
    ("text", "keys", "expected"),
    [
        ("|a(b)c(d)", "f(", "a|(b)c(d)"),
        ("|a(b)c(d)", "2f(", "a(b)c|(d)"),
        ("|a(b)c(d)", "t(", "|a(b)c(d)"),  # already just before it: t fails
        ("|xa(b)c(d)", "t(", "x|a(b)c(d)"),
        ("a(b)c(d|)", "F(", "a(b)c|(d)"),
        ("a(b)c(d|)", "T(", "a(b)c(|d)"),
        ("|a,b,c,d", "f,;", "a,b|,c,d"),
        ("|a,b,c,d", "f,;,", "a|,b,c,d"),
        ("|a,b,c,d", "t,;", "a,|b,c,d"),  # ; after t skips the adjacent match
        ("|abc", "fz", "|abc"),
    ],
)
def test_find_char(text, keys, expected):
    assert run(text, keys) == expected


@pytest.mark.parametrize(
    ("text", "keys", "expected"),
    [
        ("|if (a[0] == b) {", "%", "if (a[0] == b|) {"),
        ("if (a[0] == b|) {", "%", "if |(a[0] == b) {"),
        ("begin {\n  x;\n|}", "%", "begin |{\n  x;\n}"),
        ("|no brackets", "%", "|no brackets"),
    ],
)
def test_percent(text, keys, expected):
    assert run(text, keys) == expected


def test_percent_with_count_goes_to_percentage_of_file():
    assert run("|" + "\n".join(str(i) for i in range(1, 11)), "50%").split("\n")[4] == "|5"


def test_search_forward_backward_and_repeat():
    engine = make("|foo bar\nbaz bar\nqux")
    engine.feed_keys("/bar<CR>")
    assert show(engine) == "foo |bar\nbaz bar\nqux"
    engine.feed_keys("n")
    assert show(engine) == "foo bar\nbaz |bar\nqux"
    engine.feed_keys("N")
    assert show(engine) == "foo |bar\nbaz bar\nqux"
    engine.feed_keys("?foo<CR>")
    assert show(engine) == "|foo bar\nbaz bar\nqux"


def test_search_wraps_with_message():
    engine = make("foo\nba|r foo")
    result = engine.feed_keys("/foo<CR>n")
    assert show(engine) == "|foo\nbar foo"
    assert result.message.text == "search hit BOTTOM, continuing at TOP"


def test_search_not_found_is_an_error():
    engine = make("|foo")
    result = engine.feed_keys("/zzz<CR>")
    assert result.message.error
    assert "E486" in result.message.text
    assert show(engine) == "|foo"


def test_empty_search_reuses_last_pattern():
    assert run("|a x a x a", "/x<CR>/<CR>") == "a x a |x a"


def test_smartcase():
    assert run("|Foo foo", "/foo<CR>", ignorecase=True, smartcase=True) == "Foo |foo"
    assert run("|foo Foo", "/Foo<CR>", ignorecase=True, smartcase=True) == "foo |Foo"
