import pytest
from vimtest import make

from vimcore.hangul import is_hangul, to_qwerty
from vimcore.keyparser import CANCEL, INCOMPLETE, Command, Invalid, format_keys, parse_command, parse_keys


@pytest.mark.parametrize(
    ("notation", "keys"),
    [
        ("d2w", ["d", "2", "w"]),
        ("<Esc><esc><C-[>", ["<Esc>", "<Esc>", "<Esc>"]),
        ("<C-R><c-w><C-S-V>", ["<C-r>", "<C-w>", "<C-S-v>"]),
        ("<lt>a<Space>", ["<", "a", " "]),
        ("<Enter><Return><CR>", ["<CR>", "<CR>", "<CR>"]),
        ("<foo>", ["<", "f", "o", "o", ">"]),  # unknown names are literal
        ("a<", ["a", "<"]),
    ],
)
def test_parse_keys(notation, keys):
    assert parse_keys(notation) == keys


def test_format_keys():
    assert format_keys(['"', "a", "2", "d", " "]) == '"a2d<Space>'


def _parse(notation: str, visual: bool = False):
    return parse_command(parse_keys(notation), visual=visual)


@pytest.mark.parametrize("notation", ['"', '"a', "2", "d", "d2", "g", "f", "dt", "Z", '"a3d4'])
def test_incomplete(notation):
    assert _parse(notation) is INCOMPLETE


def test_count_register_operator_motion():
    cmd = _parse('"a3d4w')
    assert cmd == Command(("d", "w"), "w", register="a", count=12, operator="d")


def test_zero_is_a_motion_unless_inside_a_count():
    assert _parse("0").action == "0"
    assert _parse("10j").count == 10


def test_doubled_operator_and_shorthands():
    assert _parse("dd") == Command(("d", "d"), "line", operator="d")
    assert _parse("x") == Command(("x",), "l", operator="d")
    assert _parse("Y").action == "line"


def test_escape_cancels_a_pending_command():
    assert _parse("d<Esc>") is CANCEL
    assert _parse("2<C-c>") is CANCEL


def test_unsupported_keys_are_invalid():
    assert isinstance(_parse("gx"), Invalid)
    assert isinstance(_parse("dq"), Invalid)
    assert isinstance(_parse("q"), Invalid)


def test_visual_actions():
    assert _parse("d", visual=True).action == "delete"
    assert _parse("2>", visual=True).count == 2
    assert _parse("w", visual=True).action == "w"


@pytest.mark.parametrize("keys", ["q", "gq", "<C-a>", "zz"])
def test_engine_reports_unsupported_keys_on_the_status_line(keys):
    result = make("|x").feed_keys(keys)
    assert result.message is not None and result.message.error
    assert result.message.text.startswith("Unsupported key")
    assert result.pending == ""


def test_pending_keys_are_visible():
    assert make("|x").feed_keys('"a2d').pending == '"a2d'


@pytest.mark.parametrize(
    ("text", "keys"),
    [("ㅓ", "j"), ("ㅓㅏ", "jk"), ("ㅘ", "hk"), ("다", "ek"), ("ㅆ", "T"), ("값", "rkqt")],
)
def test_hangul_to_qwerty(text, keys):
    assert is_hangul(text)
    assert to_qwerty(text) == keys


def test_non_hangul_is_not_mapped():
    assert to_qwerty("j") is None
    assert not is_hangul("abc")
