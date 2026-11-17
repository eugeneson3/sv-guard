import pytest
from vimtest import make, show

from vimcore import HostRequest, Mode
from vimcore.mapping import KeyTrie, MapCommand, MapKeys, expand_lhs


def _engine_with(text: str, mappings: dict[str, object]):
    engine = make(text)
    trie = engine.shared.mappings.normal
    for lhs, target in mappings.items():
        trie.add(expand_lhs(lhs, "<Space>"), target)
    return engine


def test_trie_lookup():
    trie = KeyTrie()
    trie.add(["g", "t"], MapCommand("tab.next"))
    trie.add([" "], MapCommand("x"))
    trie.add([" ", "f"], MapCommand("file.find"))
    assert trie.lookup(["g"]) == (None, True)
    assert trie.lookup(["g", "t"]) == (MapCommand("tab.next"), False)
    assert trie.lookup([" "]) == (MapCommand("x"), True)
    assert trie.lookup(["q"]) == (None, False)
    assert len(trie) == 3
    assert sorted(k for k, _ in trie.items()) == [(" ",), (" ", "f"), ("g", "t")]


def test_expand_leader():
    assert expand_lhs("<leader>f", "<Space>") == [" ", "f"]
    assert expand_lhs("<Leader><leader>", ",") == [",", ","]
    assert expand_lhs("<C-w>h", "<Space>") == ["<C-w>", "h"]


def test_unique_mapping_runs_a_host_command():
    engine = _engine_with("|x", {"gt": MapCommand("tab.next")})
    result = engine.feed_keys("gt")
    assert result.requests == (HostRequest("command", "tab.next"),)


def test_count_is_passed_to_the_command():
    engine = _engine_with("|x", {"gt": MapCommand("tab.next")})
    assert engine.feed_keys("3gt").requests == (HostRequest("command", "tab.next", count=3),)


def test_builtin_prefix_still_works_through_a_mapping_prefix():
    engine = _engine_with("a\nb\n|c", {"gt": MapCommand("tab.next")})
    engine.feed_keys("gg")  # 'g' could have become gt; 'gg' is the built-in motion
    assert show(engine) == "|a\nb\nc"


def test_leader_waits_for_timeout_then_falls_back_to_builtin():
    engine = _engine_with("|ab", {"<leader>f": MapCommand("file.find")})
    result = engine.feed_keys(" ")
    assert engine.awaiting_timeout and result.pending == "<Space>"
    assert engine.cursor.col == 0
    engine.timeout()
    assert not engine.awaiting_timeout
    assert show(engine) == "a|b"  # <Space> alone is `l`


def test_leader_sequence_before_timeout():
    engine = _engine_with("|ab", {"<leader>f": MapCommand("file.find")})
    result = engine.feed_keys(" f")
    assert result.requests == (HostRequest("command", "file.find"),)
    assert not engine.awaiting_timeout


def test_exact_and_longer_mapping_uses_the_short_one_on_timeout():
    engine = _engine_with("|x", {"<leader>g": MapCommand("short"), "<leader>gs": MapCommand("long")})
    engine.feed_keys(" g")
    assert engine.awaiting_timeout
    assert engine.timeout().requests == (HostRequest("command", "short"),)


def test_prefix_without_builtin_meaning_reports_after_timeout():
    engine = _engine_with("|x", {"<C-w>h": MapCommand("window.focusLeft")})
    engine.feed_keys("<C-w>")
    result = engine.timeout()
    assert result.message.text == "Unsupported key: <C-w>"


def test_key_mapping_is_not_remapped():
    engine = _engine_with("  a|bc", {"H": MapKeys(("^",)), "^": MapCommand("never")})
    result = engine.feed_keys("H")
    assert show(engine) == "  |abc"
    assert result.requests == ()


def test_mappings_do_not_apply_in_insert_mode():
    engine = _engine_with("|", {"<leader>f": MapCommand("file.find")})
    result = engine.feed_keys("i f<Esc>")
    assert engine.buffer.text == " f"
    assert result.requests == ()


def test_dot_repeat_is_not_affected_by_mappings():
    engine = _engine_with("|a b c", {"x": MapCommand("boom")})
    engine.feed_keys("dw")
    assert engine.feed_keys(".").requests == ()
    assert engine.buffer.text == "c"


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        (":bn<CR>", HostRequest("command", "tab.next")),
        (":bp<CR>", HostRequest("command", "tab.previous")),
        (":file.find<CR>", HostRequest("command", "file.find")),
    ],
)
def test_ex_commands_reach_host_commands(keys, expected):
    engine = make("|x")
    engine.shared.host_commands = frozenset({"file.find"})
    result = engine.feed_keys(keys)
    assert result.requests == (expected,)
    assert result.mode is Mode.NORMAL
