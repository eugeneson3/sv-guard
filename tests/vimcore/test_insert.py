import pytest
from vimtest import FakeClipboard, make, run, show

from vimcore import InsertText, Mode


@pytest.mark.parametrize(
    ("text", "keys", "expected"),
    [
        ("ab|c", "iX<Esc>", "ab|Xc"),
        ("ab|c", "aX<Esc>", "abc|X"),
        ("|", "aX<Esc>", "|X"),
        ("  ab|c", "IX<Esc>", "  |Xabc"),
        ("a|bc", "AX<Esc>", "abc|X"),
        ("  a|b\nc", "oX<Esc>", "  ab\n  |X\nc"),  # autoindent
        ("  a|b\nc", "OX<Esc>", "  |X\n  ab\nc"),
        ("ab|c", "<Insert>X<Esc>", "ab|Xc"),
        ("|a", "3iab<Esc>", "ababa|ba"),
        ("|a", "2oX<Esc>", "a\nX\n|X"),
    ],
)
def test_enter_and_leave_insert(text, keys, expected):
    assert run(text, keys) == expected


def test_esc_moves_left_and_mode_changes():
    engine = make("ab|c")
    assert engine.feed_keys("i").mode is Mode.INSERT
    result = engine.feed_keys("<Esc>")
    assert result.mode is Mode.NORMAL
    assert show(engine) == "a|bc"


@pytest.mark.parametrize(
    ("text", "keys", "expected"),
    [
        ("    fo|o", "a<CR>x<Esc>", "    foo\n    |x"),
        ("ab|c", "i<CR><Esc>", "ab\n|c"),
        ("ab|c", "a<Tab>x<Esc>", "abc |x"),  # expandtab: spaces up to the next multiple of 4
        ("ab|c", "i<BS><Esc>", "|ac"),
        ("a\n|b", "i<BS><Esc>", "|ab"),  # backspace at column 0 joins lines
        ("        |x", "i<BS><Esc>", "   | x"),  # one indent level at a time
        ("ab|c", "i<Del><Esc>", "a|b"),
        ("foo ba|r", "a<C-w><Esc>", "foo| "),
        ("    foo ba|r", "a<C-u><Esc>", "   | "),
    ],
)
def test_insert_editing_keys(text, keys, expected):
    assert run(text, keys) == expected


def test_backspace_in_text_deletes_one_char_even_with_expandtab():
    assert run("    a|b", "a<BS><Esc>", expandtab=True) == "    |a"


def test_tab_without_expandtab():
    assert run("|", "i<Tab><Esc>", expandtab=False) == "|\t"


def test_insert_text_token_is_literal():
    engine = make("|")
    engine.feed_keys("i")
    engine.insert_text("<Esc>한글")
    engine.feed_keys("<Esc>")
    assert engine.buffer.text == "<Esc>한글"


def test_ctrl_v_pastes_clipboard_in_insert_mode():
    clipboard = FakeClipboard("hello")
    engine = make("|", clipboard=clipboard)
    engine.feed_keys("i<C-v><Esc>")
    assert show(engine) == "hell|o"


def test_unsupported_insert_key_is_reported_not_inserted():
    engine = make("|")
    result = engine.feed_keys("i<C-x>")
    assert result.message.error and "<C-x>" in result.message.text
    assert engine.buffer.text == ""
    assert engine.mode is Mode.INSERT


def test_arrow_keys_move_within_insert_mode():
    assert run("a|b", "i<Right>X<Esc>") == "ab|X"
