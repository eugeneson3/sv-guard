from vimtest import make, run, show


def test_undo_and_redo_a_delete():
    engine = make("foo |bar baz")
    engine.feed_keys("dw")
    engine.feed_keys("u")
    assert show(engine) == "foo |bar baz"
    engine.feed_keys("<C-r>")
    assert show(engine) == "foo |baz"


def test_insert_session_is_one_undo_step():
    engine = make("|x")
    engine.feed_keys("ifoo<CR>bar<Esc>")
    engine.feed_keys("u")
    assert engine.buffer.text == "x"


def test_cursor_key_in_insert_splits_undo_steps():
    engine = make("|x")
    engine.feed_keys("ia<Left>b<Esc>")
    assert engine.buffer.text == "bax"
    engine.feed_keys("u")
    assert engine.buffer.text == "ax"


def test_undo_count_and_limits():
    engine = make("|abc")
    engine.feed_keys("xxx")
    engine.feed_keys("2u")
    assert engine.buffer.text == "bc"
    result = engine.feed_keys("5u")
    assert engine.buffer.text == "abc"
    assert result.message is None
    assert engine.feed_keys("u").message.text == "Already at oldest change"
    assert engine.feed_keys("<C-r><C-r><C-r><C-r>").message.text == "Already at newest change"


def test_undo_dd_restores_cursor_column():
    engine = make("a\nbc|d\ne")
    engine.feed_keys("ddu")
    assert show(engine) == "a\nbc|d\ne"


def test_dot_repeats_delete():
    assert run("|a b c d", "dw.") == "|c d"


def test_dot_repeats_change_with_typed_text():
    assert run("|foo bar baz", "cwX<Esc>w.") == "X |X baz"


def test_dot_with_new_count_replaces_old_count():
    engine = make("|abcdefgh")
    engine.feed_keys("2x")
    engine.feed_keys("3.")
    assert engine.buffer.text == "fgh"
    engine.feed_keys(".")  # the new count sticks
    assert engine.buffer.text == ""


def test_dot_repeats_insert_and_open_line():
    assert run("|a", "Ab<Esc>.") == "ab|b"
    assert run("|a", "ox<Esc>.") == "a\nx\n|x"


def test_dot_repeats_with_register():
    assert run("|a\nb", '"qyy"qp.') == "a\na\n|a\nb"


def test_dot_is_one_undo_step():
    engine = make("|foo bar")
    engine.feed_keys("cwX<Esc>w.")
    engine.feed_keys("u")
    assert engine.buffer.text == "X bar"


def test_dot_repeats_shift():
    assert run("|a", ">>.") == "        |a"


def test_dot_repeats_visual_linewise_delete():
    assert run("|1\n2\n3\n4\n5", "Vjd.") == "|5"


def test_dot_repeats_visual_charwise_change():
    assert run("|abcdef", "vlcX<Esc>l.") == "X|Xef"


def test_dot_after_cursor_key_repeats_only_the_new_text():
    # "." repeats just "b", as an `i` command
    assert run("|x", "ia<Left>b<Esc>$.") == "ba|bx"


def test_yank_is_not_repeatable():
    assert run("|ab", "xyl.") == "|"


def test_failed_change_keeps_previous_dot():
    # x on an empty line changes nothing, so `.` still repeats dw
    assert run("|a b\n\nc d", "dwjx").startswith("b")
