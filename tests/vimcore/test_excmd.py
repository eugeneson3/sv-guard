import pytest
from vimtest import make, show

from vimcore import HostRequest, Mode


@pytest.mark.parametrize(
    ("keys", "requests"),
    [
        (":w<CR>", [HostRequest("write")]),
        (":write<CR>", [HostRequest("write")]),
        (":w other.sv<CR>", [HostRequest("write", "other.sv")]),
        (":q<CR>", [HostRequest("quit")]),
        (":q!<CR>", [HostRequest("quit", force=True)]),
        (":wq<CR>", [HostRequest("write"), HostRequest("quit")]),
        (":x<CR>", [HostRequest("write_if_modified"), HostRequest("quit")]),
        (":wa<CR>", [HostRequest("write_all")]),
        (":qa!<CR>", [HostRequest("quit_all", force=True)]),
        (":e rtl/top.sv<CR>", [HostRequest("edit", "rtl/top.sv")]),
        (":e!<CR>", [HostRequest("reload")]),
        ("ZZ", [HostRequest("write_if_modified"), HostRequest("quit")]),
        ("ZQ", [HostRequest("quit", force=True)]),
    ],
)
def test_file_commands_become_host_requests(keys, requests):
    result = make("|x").feed_keys(keys)
    assert list(result.requests) == requests
    assert result.mode is Mode.NORMAL


def test_unknown_command():
    result = make("|x").feed_keys(":frobnicate<CR>")
    assert result.message.error and "E492" in result.message.text


def test_edit_needs_a_file_name():
    assert "E32" in make("|x").feed_keys(":e<CR>").message.text


def test_goto_line():
    engine = make("|a\nb\n  c")
    engine.feed_keys(":3<CR>")
    assert show(engine) == "a\nb\n  |c"
    engine.feed_keys(":1<CR>:$<CR>")
    assert show(engine) == "a\nb\n  |c"


def test_set_options():
    engine = make("|x")
    result = engine.feed_keys(":set ts=2 sw=2 noet<CR>")
    assert (engine.options.tabstop, engine.options.sw, engine.options.expandtab) == (2, 2, False)
    assert HostRequest("options") in result.requests
    assert engine.feed_keys(":set ts?<CR>").message.text.strip() == "tabstop=2"
    engine.feed_keys(":set et!<CR>")
    assert engine.options.expandtab is True


@pytest.mark.parametrize(("arg", "code"), [("bogus", "E518"), ("ts=abc", "E521"), ("ts=0", "E474"), ("et=1", "E474")])
def test_set_errors(arg, code):
    assert code in make("|x").feed_keys(f":set {arg}<CR>").message.text


def test_command_line_editing_and_view():
    engine = make("|x")
    engine.feed_keys(":wx<Left><BS>")
    assert engine.cmdline.text == "x" and engine.cmdline.cursor == 0
    engine.feed_keys("<End><BS><BS>")  # backspace on an empty line leaves the command line
    assert engine.mode is Mode.NORMAL and engine.cmdline is None


def test_escape_cancels_command_line():
    result = make("|x").feed_keys(":q<Esc>")
    assert result.mode is Mode.NORMAL and result.requests == ()


def test_history():
    engine = make("|x")
    engine.feed_keys(":set ts=2<CR>:set sw=3<CR>:")
    engine.feed_keys("<Up>")
    assert engine.cmdline.text == "set sw=3"
    engine.feed_keys("<Up>")
    assert engine.cmdline.text == "set ts=2"
    engine.feed_keys("<Down><Down>")
    assert engine.cmdline.text == ""


def test_scroll_request():
    engine = make("|" + "\n".join("x" * 50))
    engine.options.page = 20
    result = engine.feed_keys("<C-d>")
    assert engine.cursor.row == 10
    assert HostRequest("scroll", "10") in result.requests
