from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from app.commands.fuzzy import fuzzy_filter, fuzzy_score
from app.commands.keymap import Keymap, PanelKeyDispatcher, load_keymap
from app.commands.registry import AppCommand, CommandRegistry
from app.panels.fuzzy_finder import FinderItem, FuzzyFinder
from vimcore.mapping import MapCommand, MapKeys


# -- fuzzy -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "text", "matches"),
    [("gtf", "Go to File...", True), ("alu", "rtl/alu.sv", True), ("xyz", "rtl/alu.sv", False), ("", "x", True)],
)
def test_fuzzy_score_matches_subsequences(query, text, matches):
    assert (fuzzy_score(query, text) is not None) is matches


def test_fuzzy_prefers_word_starts_and_short_names():
    items = ["src/fallback_counter.sv", "rtl/alu.sv", "alu_tb.sv"]
    assert fuzzy_filter("alu", items)[:2] == ["alu_tb.sv", "rtl/alu.sv"]
    assert fuzzy_filter("gf", ["Go: Next Tab", "File: Go to File..."])[0] == "File: Go to File..."


def test_fuzzy_filter_empty_query_keeps_order_and_limit():
    assert fuzzy_filter("", list("abcdef"), limit=3) == ["a", "b", "c"]


# -- registry --------------------------------------------------------------------------


def test_registry_runs_commands_with_count():
    seen = []
    registry = CommandRegistry()
    registry.add(AppCommand("tab.next", "Next Tab", lambda count: seen.append(count), "Go"))
    assert registry.run("tab.next", 3) and seen == [3]
    assert not registry.run("missing")
    assert "tab.next" in registry and registry.ids() == {"tab.next"}
    with pytest.raises(ValueError):
        registry.add(AppCommand("tab.next", "dup", lambda c: None))


# -- keymap ----------------------------------------------------------------------------


def test_default_keymap_loads_cleanly():
    keymap, warnings = load_keymap(None)
    assert warnings == []
    assert keymap.leader == "<Space>"
    assert keymap.sections["normal"]["<leader>f"] == MapCommand("file.find")
    assert keymap.bindings_for("file.find") == ["<Space>f"]
    assert len(keymap.mappings().normal) == len(keymap.sections["normal"])


def test_user_keymap_overrides_and_removes(tmp_path: Path):
    user = tmp_path / "keymap.yaml"
    user.write_text(
        'leader: ","\ntimeoutlen: 300\nnormal:\n  "<leader>f": null\n  "H": {keys: "^"}\n  "<leader>q": app.quit\n',
        encoding="utf-8",
    )
    keymap, warnings = load_keymap(user)
    assert warnings == []
    assert (keymap.leader, keymap.timeoutlen) == (",", 300)
    assert "<leader>f" not in keymap.sections["normal"]
    assert keymap.sections["normal"]["H"] == MapKeys(("^",))
    assert keymap.bindings_for("app.quit") == [",q"]


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("leader: 3\n", "leader must be"),
        ("timeoutlen: 1\n", "timeoutlen must be"),
        ("normal: [1]\n", "'normal' must be a mapping"),
        ('normal:\n  "x": {foo: 1}\n', "target must be"),
        ("bogus: 1\n", "unknown key 'bogus'"),
        ("normal: {x: [\n", "cannot read"),
    ],
)
def test_bad_user_keymap_is_reported_not_fatal(tmp_path: Path, text, fragment):
    user = tmp_path / "keymap.yaml"
    user.write_text(text, encoding="utf-8")
    keymap, warnings = load_keymap(user)
    assert any(fragment in w for w in warnings)
    assert keymap.sections["normal"]["<leader>f"] == MapCommand("file.find")  # defaults survive


def test_panel_trie_only_takes_global_sequences():
    keymap, _ = load_keymap(None)
    trie = keymap.panel_trie()
    assert trie.lookup([" ", "f"])[0] == MapCommand("file.find")
    assert trie.lookup(["<C-w>", "l"])[0] == MapCommand("window.focusRight")
    assert trie.lookup(["g", "t"]) == (None, False)  # gt stays an editor mapping


def test_panel_dispatcher_sequences_and_passthrough(qtbot):
    keymap = Keymap()
    keymap.sections["normal"] = {"<leader>f": MapCommand("file.find"), "<C-w>h": MapCommand("left")}
    dispatcher = PanelKeyDispatcher(keymap.panel_trie(), 50)
    seen = []
    dispatcher.command.connect(seen.append)
    assert dispatcher.feed(" ") and dispatcher.pending == "<Space>"
    assert dispatcher.feed("f") and seen == ["file.find"]
    assert not dispatcher.feed("j")  # j belongs to the panel
    assert dispatcher.feed(" ")
    assert not dispatcher.feed("j")  # <Space>j maps to nothing: j still reaches the panel
    assert dispatcher.feed("<C-w>") and dispatcher.feed("h") and seen[-1] == "left"


# -- fuzzy finder widget ------------------------------------------------------------------


def test_finder_closes_when_clicking_outside(qtbot):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMainWindow

    window = QMainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    finder = FuzzyFinder([FinderItem("File: Save", payload="file.save")], placeholder="x", parent=window)

    def click_outside():
        assert finder.isVisible() and finder.isActiveWindow()
        window.activateWindow()  # what a click on the main window (or another app) does

    QTimer.singleShot(100, click_outside)
    QTimer.singleShot(3000, finder.reject)  # safety net: never hang the test run
    finder.run()
    assert not finder.isVisible()
    assert finder.selected is None


def test_finder_escape_closes(qtbot):
    from PySide6.QtCore import QTimer

    finder = FuzzyFinder([FinderItem("File: Save", payload="file.save")], placeholder="x")
    qtbot.addWidget(finder)
    QTimer.singleShot(100, lambda: qtbot.keyClick(finder.input, Qt.Key.Key_Escape))
    QTimer.singleShot(3000, finder.reject)
    finder.run()
    assert finder.selected is None and not finder.isVisible()


def test_finder_filters_moves_and_accepts_with_keys(qtbot):
    items = [FinderItem("File: Save", "Ctrl+S", "file.save"), FinderItem("Go: Next Tab", "", "tab.next")]
    finder = FuzzyFinder(items, placeholder="Type a command")
    qtbot.addWidget(finder)
    assert finder.visible_labels() == ["File: Save", "Go: Next Tab"]
    qtbot.keyClicks(finder.input, "next")
    assert finder.visible_labels() == ["Go: Next Tab"]
    finder.input.clear()
    qtbot.keyClick(finder.input, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyClick(finder.input, Qt.Key.Key_Return)
    assert finder.selected.payload == "tab.next"
