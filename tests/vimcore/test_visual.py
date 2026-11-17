import pytest
from vimtest import FakeClipboard, make, run, show

from vimcore import Mode, Pos


@pytest.mark.parametrize(
    ("text", "keys", "expected"),
    [
        ("a|bcd", "vld", "a|d"),
        ("a|bcd", "vlhd", "a|cd"),
        ("ab|cd", "vhd", "a|d"),
        ("a\n|b\nc\nd", "Vjd", "a\n|d"),
        ("|ab\ncd", "v$d", "|cd"),  # v$ includes the line break
        ("a|b\ncd", "vjd", "|a"),  # selects b..d (same column on the next line)
        ("a|bcd", "vlx", "a|d"),
        ("a|bcd", "vlcX<Esc>", "a|Xd"),
        ("a\n|b\nc", "VjcX<Esc>", "a\n|X"),
        ("|a\nb", "Vj>", "    |a\n    b"),
        ("|a\nb", "Vj2>", "        |a\n        b"),
        ("    |a", "v<", "|a"),
        ("ab|cd", "vlD", "|"),  # D in Visual deletes whole lines
        ("x\na|b\ny", "vX", "x\n|y"),
    ],
)
def test_visual_operators(text, keys, expected):
    assert run(text, keys) == expected


def test_visual_yank_returns_to_normal_at_start():
    engine = make("foo b|ar")
    engine.feed_keys("vby")  # selects "ba" (the cursor character is included)
    assert engine.mode is Mode.NORMAL
    assert show(engine) == "foo |bar"
    engine.feed_keys("$p")
    assert show(engine) == "foo barb|a"


def test_swap_ends_with_o():
    engine = make("a|bcd")
    engine.feed_keys("vllo")  # selection b..d, cursor back on b
    assert engine.cursor == Pos(0, 1)
    engine.feed_keys("hd")  # extend to a, delete a..d
    assert show(engine) == "|"


def test_selection_property():
    engine = make("a|bcd\nefg")
    engine.feed_keys("vl")
    assert engine.selection.start == Pos(0, 1) and engine.selection.end == Pos(0, 3)
    engine.feed_keys("V")
    assert engine.mode is Mode.VISUAL_LINE
    assert engine.selection.linewise and engine.selection.end == Pos(0, 4)
    engine.feed_keys("<Esc>")
    assert engine.selection is None


def test_v_toggles_and_switches():
    engine = make("|ab")
    engine.feed_keys("v")
    assert engine.mode is Mode.VISUAL
    engine.feed_keys("V")
    assert engine.mode is Mode.VISUAL_LINE
    engine.feed_keys("v")
    assert engine.mode is Mode.VISUAL
    engine.feed_keys("v")
    assert engine.mode is Mode.NORMAL


def test_visual_put_replaces_selection():
    # yw yanks "foo ", then "bar" is selected and replaced by it
    assert run("|foo bar", "ywwvep") == "foo foo| "


def test_visual_put_linewise():
    assert run("|a\nb\nc", "yyjVp") == "a\n|a\nc"


def test_ctrl_c_copies_selection_to_clipboard():
    clipboard = FakeClipboard()
    engine = make("|foo bar", clipboard=clipboard)
    engine.feed_keys("vee<C-c>")
    assert clipboard.text == "foo bar"
    assert engine.mode is Mode.NORMAL


def test_search_extends_visual_selection():
    engine = make("|foo bar baz")
    engine.feed_keys("v/baz<CR>")
    assert engine.mode is Mode.VISUAL
    engine.feed_keys("d")
    assert show(engine) == "|az"


def test_mouse_selection_enters_visual():
    engine = make("abcdef")
    engine.set_visual(Pos(0, 1), Pos(0, 3))
    assert engine.mode is Mode.VISUAL
    engine.feed_keys("d")
    assert show(engine) == "a|ef"
