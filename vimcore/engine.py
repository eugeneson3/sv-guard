"""VimEngine: the modal state machine.

GUI-independent: feed it key tokens, read back mode/cursor/selection/messages, and carry
out the HostRequests it returns (save, quit, open file, scroll...). Text lives in a
TextBuffer; the engine edits only through `edit()` so every change is undoable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from vimcore import excmd, operators
from vimcore.buffer import Pos, TextBuffer, first_nonblank, get_text, leading_whitespace, pos_after
from vimcore.keyparser import (
    CANCEL,
    INCOMPLETE,
    VISUAL_ACTIONS,
    Command,
    InsertText,
    Invalid,
    Token,
    format_keys,
    parse_command,
    parse_keys,
    read_count,
)
from vimcore.macros import DotRecord, VisualExtent
from vimcore.mapping import MapCommand, Mappings, MapTarget
from vimcore.modes import Mode
from vimcore.motions import MAXCOL, Motion, backward_word, char_class, end_word, find_char, forward_word, match_pair
from vimcore.operators import TextRange, indent_width, motion_range
from vimcore.options import VimOptions
from vimcore.registers import Registers, RegisterValue
from vimcore.search import search
from vimcore.undo import Edit, UndoHistory


@dataclass(frozen=True)
class Message:
    text: str
    error: bool = False


@dataclass(frozen=True)
class HostRequest:
    """Something only the host can do: write, write_if_modified, write_all, quit, quit_all,
    edit (arg = path), reload, options (re-read engine.options), scroll (arg = lines),
    command (arg = host command id, from a mapping or an ex command)."""

    name: str
    arg: str | None = None
    force: bool = False
    count: int | None = None


@dataclass(frozen=True)
class Selection:
    start: Pos
    end: Pos  # exclusive
    linewise: bool


@dataclass(frozen=True)
class CmdlineView:
    prefix: str  # ":", "/" or "?"
    text: str
    cursor: int


@dataclass(frozen=True)
class FeedResult:
    mode: Mode
    cursor: Pos
    pending: str
    message: Message | None
    requests: tuple[HostRequest, ...]


class VimError(Exception):
    pass


@dataclass
class SharedState:
    """What vim keeps per session rather than per buffer: registers, last search, `.`."""

    registers: Registers = field(default_factory=Registers)
    last_search: str | None = None
    search_forward: bool = True
    last_find: tuple[str, str] | None = None  # (f/F/t/T, char) for ; and ,
    last_change: DotRecord | None = None
    history: dict[str, list[str]] = field(default_factory=lambda: {":": [], "/": []})
    mappings: Mappings = field(default_factory=Mappings)
    host_commands: frozenset[str] = frozenset()  # ids the host accepts as ex commands (:file.find)


@dataclass
class _InsertSession:
    kind: str  # i a I A o O c
    count: int  # 3ix<Esc> inserts "xxx"
    tokens: list[Token] = field(default_factory=list)


@dataclass
class _Cmdline:
    prefix: str
    return_mode: Mode
    operator: Command | None = None  # d/foo<CR>
    text: str = ""
    cursor: int = 0
    history_index: int | None = None
    draft: str = ""


_INSERT_MOVES = frozenset({"<Left>", "<Right>", "<Up>", "<Down>", "<Home>", "<End>"})
_PASTE_KEYS = frozenset({"<C-v>", "<C-S-v>"})
_HISTORY_LIMIT = 100


class VimEngine:
    def __init__(self, buffer: TextBuffer, *, options: VimOptions | None = None, shared: SharedState | None = None) -> None:
        self.buffer = buffer
        self.options = options or VimOptions()
        self.shared = shared or SharedState()
        self.mode = Mode.NORMAL
        self.cursor = Pos(0, 0)
        self._curswant = 0
        self._pending: list[Token] = []
        self._anchor: Pos | None = None
        self._undo = UndoHistory()
        self._insert: _InsertSession | None = None
        self._cmdline: _Cmdline | None = None
        self._recording: DotRecord | None = None
        self._change_open = False  # a change entered Insert/command-line mode; its undo step is open
        self._replaying = False
        self._noremap = 0  # > 0 while replaying keys that must not be mapped again
        self._awaiting_timeout = False
        self._message: Message | None = None
        self._requests: list[HostRequest] = []

    # == host-facing state =================================================================

    @property
    def registers(self) -> Registers:
        return self.shared.registers

    @property
    def pending(self) -> str:
        return format_keys(self._pending)

    @property
    def message(self) -> Message | None:
        return self._message

    @property
    def selection(self) -> Selection | None:
        if self._visual_mode() is None or self._anchor is None:
            return None
        rng = self._visual_range()
        if rng.linewise:
            return Selection(Pos(rng.start.row, 0), Pos(rng.end.row, len(self.buffer.line(rng.end.row))), True)
        return Selection(rng.start, rng.end, False)

    @property
    def cmdline(self) -> CmdlineView | None:
        c = self._cmdline
        return CmdlineView(c.prefix, c.text, c.cursor) if c else None

    @property
    def undo_state(self) -> object:
        """Opaque marker of the undo position. The host stores it on save; when it is the
        same object again (and no change is in progress) the text equals the saved file."""
        return self._undo.state

    @property
    def change_in_progress(self) -> bool:
        return self._change_open

    @property
    def awaiting_timeout(self) -> bool:
        """The pending keys could still grow into a longer mapping. The host should call
        timeout() after shared.mappings.timeoutlen ms unless another key arrives first."""
        return self._awaiting_timeout

    def timeout(self) -> FeedResult:
        self._begin_feed()
        if self._awaiting_timeout:
            self._awaiting_timeout = False
            keys = list(self._pending)
            self._pending.clear()
            count, start = read_count(keys)
            target, _longer = self._trie().lookup(keys[start:])
            try:
                if target is not None:
                    self._run_mapping(target, count)
                else:
                    self._feed_unmapped(keys)
            except (VimError, excmd.ExError) as exc:
                self._pending.clear()
                self.set_message(str(exc), error=True)
        return self._result()

    # == input =============================================================================

    def feed(self, key: Token) -> FeedResult:
        self._begin_feed()
        self._dispatch(key)
        return self._result()

    def feed_keys(self, notation: str) -> FeedResult:
        """Feed keys written in vim notation, e.g. 'd2w' or 'cwfoo<Esc>'."""
        self._begin_feed()
        for key in parse_keys(notation):
            self._dispatch(key)
        return self._result()

    def insert_text(self, text: str) -> FeedResult:
        """Text committed in one piece (IME) in Insert or command-line mode."""
        return self.feed(InsertText(text))

    def paste_text(self, text: str) -> FeedResult:
        """Host paste (context menu, drag and drop): typed text in Insert/command-line mode,
        otherwise inserted at the cursor as one undoable change."""
        if self.mode.accepts_text:
            return self.insert_text(text)
        self._begin_feed()
        if self.mode.is_visual:
            self._exit_visual()
        self._undo.begin(self.cursor)
        try:
            operators.put(self, RegisterValue(text), 1, after=False)
        finally:
            self._undo.end()
        return self._result()

    def set_cursor(self, pos: Pos) -> None:
        """The host moved the cursor (mouse click)."""
        if self.mode is Mode.COMMAND:
            return
        self._pending.clear()
        if self.mode.is_visual:
            self._exit_visual()
        if self.mode is Mode.INSERT:
            self._break_insert()
        self.move_cursor(pos)

    def set_visual(self, anchor: Pos, cursor: Pos) -> None:
        """The host made a selection (mouse drag): enter charwise Visual mode."""
        if self.mode is Mode.COMMAND:
            return
        if self.mode is Mode.INSERT:
            self._finish_insert(move_left=False)
        self._pending.clear()
        self.mode = Mode.VISUAL
        self._anchor = self._clamped(anchor, Mode.NORMAL)
        self.cursor = self._clamped(cursor, Mode.NORMAL)
        self._curswant = self.cursor.col

    def reset_undo(self) -> None:
        """Forget undo history (the host replaced the whole text, e.g. after a reload)."""
        self._undo.clear()

    # == primitives used by operators and ex commands =========================================

    def edit(self, start: Pos, end: Pos, text: str) -> None:
        old = get_text(self.buffer, start, end)
        if old != text:
            self.buffer.replace(start, end, text)
            self._undo.record(Edit(start, old, text))

    def move_cursor(self, pos: Pos, *, clamp: bool = True) -> None:
        """clamp=False allows the end-of-line position (for entering Insert mode)."""
        self.cursor = self._clamped(pos, self.mode if clamp else Mode.INSERT)
        self._curswant = self.cursor.col

    def set_message(self, text: str, *, error: bool = False) -> None:
        self._message = Message(text, error)

    def request(self, name: str, arg: str | None = None, *, force: bool = False, count: int | None = None) -> None:
        self._requests.append(HostRequest(name, arg, force, count))

    def start_insert(self, kind: str, count: int = 1) -> None:
        self.mode = Mode.INSERT
        self._insert = _InsertSession(kind, max(1, count))

    def goto_line(self, number: int) -> None:
        row = min(max(number, 1), self.buffer.line_count()) - 1
        self.move_cursor(Pos(row, first_nonblank(self.buffer.line(row))))

    # == dispatch ==========================================================================

    def _begin_feed(self) -> None:
        self._message = None
        self._requests = []

    def _result(self) -> FeedResult:
        return FeedResult(self.mode, self.cursor, self.pending, self._message, tuple(self._requests))

    def _dispatch(self, key: Token) -> None:
        try:
            self._dispatch_raw(key)
        except (VimError, excmd.ExError) as exc:
            self._pending.clear()
            self.set_message(str(exc), error=True)

    def _dispatch_raw(self, key: Token) -> None:
        if self.mode is Mode.INSERT:
            self._insert_key(key)
        elif self.mode is Mode.COMMAND:
            self._cmdline_key(key)
        else:
            self._normal_key(key)

    def _record_token(self, token: Token) -> None:
        if self._recording is not None:
            self._recording.keys.append(token)

    # == Normal / Visual ====================================================================

    def _normal_key(self, key: Token) -> None:
        self._pending.append(key)
        self._awaiting_timeout = False
        if self._noremap == 0 and self._try_mapping():
            return
        parsed = parse_command(self._pending, visual=self.mode.is_visual)
        if parsed is INCOMPLETE:
            return
        keys = tuple(self._pending)
        self._pending.clear()
        if parsed is CANCEL:
            return
        if isinstance(parsed, Invalid):
            raise VimError(parsed.message or f"Unsupported key: {format_keys(keys)}")
        assert isinstance(parsed, Command)
        if parsed.register is not None and not Registers.is_valid(parsed.register):
            raise VimError(f"E354: Invalid register name: '{parsed.register}'")
        if self.mode.is_visual:
            self._visual_command(parsed)
        else:
            self._normal_command(parsed)

    # -- mappings ------------------------------------------------------------------------

    def _trie(self):
        mappings = self.shared.mappings
        return mappings.visual if self.mode.is_visual else mappings.normal

    def _try_mapping(self) -> bool:
        """Handle the pending keys as a mapping. True if they were consumed (or must wait)."""
        trie = self._trie()
        if not len(trie) or self._pending[0] == '"':
            return False
        count, start = read_count(self._pending)
        keys = self._pending[start:]
        if not keys:
            return False
        target, longer = trie.lookup(keys)
        if longer:
            self._awaiting_timeout = True
            return True
        if target is None:
            return False
        self._pending.clear()
        self._run_mapping(target, count)
        return True

    def _run_mapping(self, target: MapTarget, count: int | None) -> None:
        if isinstance(target, MapCommand):
            self.request("command", target.command, count=count)
            return
        self._feed_unmapped([*(str(count) if count else ""), *target.keys])

    def _feed_unmapped(self, keys: list[Token]) -> None:
        self._noremap += 1
        try:
            for key in keys:
                self._dispatch_raw(key)
        finally:
            self._noremap -= 1

    def _normal_command(self, cmd: Command) -> None:
        if cmd.operator == "y":
            self._operator(cmd)  # yanking is not a change: no undo step, no "."
            return
        if cmd.operator:
            self._run_change(cmd, lambda: self._operator(cmd))
            return
        action = cmd.action
        if action in ("i", "a", "I", "A", "o", "O", "<Insert>"):
            self._run_change(cmd, lambda: self._enter_insert(action, cmd.count))
        elif action in ("p", "P"):
            self._run_change(cmd, lambda: self._put(cmd))
        elif action == "u":
            self._undo_redo(cmd.count, redo=False)
        elif action == "<C-r>":
            self._undo_redo(cmd.count, redo=True)
        elif action == ".":
            self._repeat(cmd.count)
        elif action in ("v", "V"):
            self.mode = Mode.VISUAL_LINE if action == "V" else Mode.VISUAL
            self._anchor = self.cursor
        elif action == ":":
            self._open_cmdline(":")
        elif action in ("/", "?"):
            self._open_cmdline(action)
        elif action in ("<C-d>", "<C-u>", "<C-f>", "<C-b>", "<PageDown>", "<PageUp>"):
            self._scroll(action, cmd.count)
        elif action == "ZZ":
            self.request("write_if_modified")
            self.request("quit")
        elif action == "ZQ":
            self.request("quit", force=True)
        elif action in ("<Esc>", "<C-c>"):
            pass  # vim beeps; nothing to cancel
        else:
            motion = self._motion(action, cmd.count, cmd.arg, op=None)
            if motion is not None:
                self._apply_motion(motion)

    def _run_change(self, cmd: Command, action: Callable[[], None], *, visual: VisualExtent | None = None) -> None:
        """Run a change as one undo step and remember it for `.`.

        If the change enters Insert or command-line mode, the step stays open until the
        user returns to Normal mode (see _settle)."""
        record = None if self._replaying else DotRecord(list(cmd.keys), cmd.count, cmd.register, visual)
        version = self.buffer.version
        self._undo.begin(self.cursor)
        try:
            action()
        except BaseException:
            self._undo.end()
            raise
        if self.mode in (Mode.INSERT, Mode.COMMAND):
            self._recording = record
            self._change_open = True
            return
        self._undo.end()
        if record is not None and self.buffer.version != version:
            self.shared.last_change = record

    def _settle(self, mode: Mode = Mode.NORMAL) -> None:
        """Leave Insert/command-line mode: close the open change and store it for `.`."""
        self.mode = mode
        if self._change_open:
            self._change_open = False
            self._undo.end()
            # An Insert session restarted by a cursor key with nothing typed after it
            # must not replace the change made before the cursor key.
            if self._recording is not None and self._recording.keys != ["i", "<Esc>"]:
                self.shared.last_change = self._recording
        self._recording = None

    # -- operators ----------------------------------------------------------------------

    def _operator(self, cmd: Command) -> None:
        if cmd.action == "line":
            first = self.cursor.row
            last = min(first + (cmd.count or 1) - 1, self.buffer.line_count() - 1)
            rng = TextRange(Pos(first, 0), Pos(last, 0), True)
        elif cmd.action in ("/", "?"):
            self._open_cmdline(cmd.action, operator=cmd)
            return
        else:
            motion = self._operator_motion(cmd)
            if motion is None:
                return  # a failing motion cancels the operator
            rng = motion_range(self.buffer, self.cursor, motion)
        self._apply_operator(cmd.operator, rng, cmd.register)

    def _operator_motion(self, cmd: Command) -> Motion | None:
        if cmd.operator == "c" and cmd.action in ("w", "W"):
            line = self.buffer.line(self.cursor.row)
            here = line[self.cursor.col] if self.cursor.col < len(line) else ""
            if here not in ("", " ", "\t"):  # cw on a word changes to its end, like ce
                pos, ok = end_word(self.buffer, self.cursor, cmd.count or 1, cmd.action == "W", stop=True)
                return Motion(pos, inclusive=True) if ok else None
        return self._motion(cmd.action, cmd.count, cmd.arg, op=cmd.operator)

    def _apply_operator(self, op: str | None, rng: TextRange, register: str | None, times: int = 1) -> None:
        if op == "d":
            operators.delete(self, rng, register)
        elif op == "c":
            operators.change(self, rng, register)
        elif op == "y":
            operators.yank(self, rng, register)
        elif op in (">", "<"):
            lines = TextRange(Pos(rng.start.row, 0), Pos(rng.end.row, 0), True)
            operators.shift(self, lines, 1 if op == ">" else -1, times)

    def _put(self, cmd: Command) -> None:
        value = self.registers.get(cmd.register)
        if value is None:
            name = cmd.register or '"'
            raise VimError(f"E353: Nothing in register {name}")
        operators.put(self, value, cmd.count or 1, after=cmd.action == "p")

    # -- motions ------------------------------------------------------------------------

    def _motion(self, action: str, count: int | None, arg: str | None, *, op: str | None) -> Motion | None:
        buf, cur = self.buffer, self.cursor
        n = count or 1
        last = buf.line_count() - 1
        line = buf.line(cur.row)

        if action == "h":
            col = max(0, cur.col - n)
            return Motion(Pos(cur.row, col)) if col != cur.col else None
        if action == "l":
            limit = len(line) if op else max(0, len(line) - 1)  # `dl` may reach the line end
            col = min(cur.col + n, limit)
            return Motion(Pos(cur.row, col)) if col != cur.col else None
        if action in ("j", "k", "+", "-"):
            down = action in ("j", "+")
            if (down and cur.row == last) or (not down and cur.row == 0):
                return None
            row = min(cur.row + n, last) if down else max(cur.row - n, 0)
            if action in ("j", "k"):
                return Motion(Pos(row, cur.col), linewise=True, keep_column=True)
            return Motion(Pos(row, first_nonblank(buf.line(row))), linewise=True)
        if action == "0":
            return Motion(Pos(cur.row, 0))
        if action == "^":
            return Motion(Pos(cur.row, first_nonblank(line)))
        if action == "$":
            row = min(cur.row + n - 1, last)
            return Motion(Pos(row, max(0, len(buf.line(row)) - 1)), inclusive=True, curswant=MAXCOL)
        if action in ("G", "gg"):
            row = min(n, last + 1) - 1 if count else (last if action == "G" else 0)
            return Motion(Pos(row, first_nonblank(buf.line(row))), linewise=True)
        if action in ("w", "W"):
            pos, _ok = forward_word(buf, cur, n, action == "W", stop_at_eol=op is not None)
            return Motion(pos)  # on failure vim still moves as far as it got
        if action in ("b", "B"):
            pos, _ok = backward_word(buf, cur, n, action == "B")
            return Motion(pos) if pos != cur else None
        if action in ("e", "E"):
            pos, ok = end_word(buf, cur, n, action == "E")
            return Motion(pos, inclusive=True) if ok else None
        if action in ("f", "F", "t", "T"):
            assert arg is not None
            self.shared.last_find = (action, arg)
            return self._find(line, action, arg, n, repeat=False)
        if action in (";", ","):
            if self.shared.last_find is None:
                return None
            kind, char = self.shared.last_find
            return self._find(line, kind.swapcase() if action == "," else kind, char, n, repeat=True)
        if action == "%":
            if count:  # N% goes to that percentage of the file
                row = min((count * (last + 1) + 99) // 100, last + 1) - 1
                return Motion(Pos(row, first_nonblank(buf.line(row))), linewise=True)
            pos = match_pair(buf, cur)
            return Motion(pos, inclusive=True) if pos else None
        if action in ("n", "N"):
            pattern = self.shared.last_search
            if not pattern:
                raise VimError("E35: No previous regular expression")
            return self._search_motion(pattern, self.shared.search_forward == (action == "n"), n)
        raise VimError(f"Unsupported motion: {action}")

    def _find(self, line: str, kind: str, char: str, count: int, *, repeat: bool) -> Motion | None:
        col = find_char(line, self.cursor.col, char, count, forward=kind in "ft", till=kind in "tT", repeat=repeat)
        return Motion(Pos(self.cursor.row, col), inclusive=kind in "ft") if col is not None else None

    def _search_motion(self, pattern: str, forward: bool, count: int) -> Motion:
        opts = self.options
        ignorecase = opts.ignorecase and not (opts.smartcase and any(ch.isupper() for ch in pattern))
        pos, wrapped_any = self.cursor, False
        for _ in range(count):
            found = search(self.buffer, pattern, pos, forward=forward, wrapscan=opts.wrapscan, ignorecase=ignorecase)
            if found is None:
                raise VimError(f"E486: Pattern not found: {pattern}")
            pos, wrapped = found
            wrapped_any |= wrapped
        if wrapped_any:
            self.set_message("search hit BOTTOM, continuing at TOP" if forward else "search hit TOP, continuing at BOTTOM")
        return Motion(pos)

    def _apply_motion(self, motion: Motion) -> None:
        target = motion.target
        if motion.keep_column:
            self.cursor = Pos(target.row, self._column_for_curswant(target.row))
            return
        if self._visual_mode() is not None and motion.curswant == MAXCOL:
            self.cursor = Pos(target.row, len(self.buffer.line(target.row)))  # v$ selects the line end too
        else:
            self.cursor = self._clamped(target, self.mode)
        self._curswant = MAXCOL if motion.curswant == MAXCOL else self.cursor.col

    def _column_for_curswant(self, row: int) -> int:
        length = len(self.buffer.line(row))
        if self._curswant == MAXCOL:
            return length if self._visual_mode() is not None else max(0, length - 1)
        limit = length if self.mode is Mode.INSERT else max(0, length - 1)
        return min(self._curswant, limit)

    def _clamped(self, pos: Pos, mode: Mode) -> Pos:
        row = min(max(pos.row, 0), self.buffer.line_count() - 1)
        length = len(self.buffer.line(row))
        maxcol = length if mode is Mode.INSERT else max(0, length - 1)
        return Pos(row, min(max(pos.col, 0), maxcol))

    def _scroll(self, action: str, count: int | None) -> None:
        half = action in ("<C-d>", "<C-u>")
        down = action in ("<C-d>", "<C-f>", "<PageDown>")
        if half and count:
            self.options.scroll = count  # vim: a count sets 'scroll'
        lines = self.options.scroll_lines if half else max(1, self.options.page - 2)
        last = self.buffer.line_count() - 1
        row = min(self.cursor.row + lines, last) if down else max(self.cursor.row - lines, 0)
        if row == self.cursor.row:
            return
        self.request("scroll", str(lines if down else -lines))
        self.cursor = Pos(row, self._column_for_curswant(row))

    # -- undo / redo / repeat -------------------------------------------------------------

    def _undo_redo(self, count: int | None, *, redo: bool) -> None:
        for i in range(count or 1):
            pos = self._undo.redo(self.buffer) if redo else self._undo.undo(self.buffer)
            if pos is None:
                if i == 0:
                    self.set_message("Already at newest change" if redo else "Already at oldest change")
                return
            self.move_cursor(pos)

    def _repeat(self, count: int | None) -> None:
        record = self.shared.last_change
        if record is None:
            return
        if count:
            record.count = count  # the new count sticks for later "." too
        self._replaying = True
        self._noremap += 1  # recorded keys are already resolved; never map them again
        self._undo.begin(self.cursor)
        try:
            if record.visual is not None:
                self._replay_visual(record)
            else:
                for token in record.replay_tokens():
                    self._dispatch_raw(token)
            if self.mode is Mode.INSERT:
                self._finish_insert()
        finally:
            self._replaying = False
            self._noremap -= 1
            self._undo.end()

    # -- Visual mode ----------------------------------------------------------------------

    def _visual_mode(self) -> Mode | None:
        if self.mode.is_visual:
            return self.mode
        if self.mode is Mode.COMMAND and self._cmdline is not None and self._cmdline.return_mode.is_visual:
            return self._cmdline.return_mode
        return None

    def _visual_range(self, *, linewise: bool = False) -> TextRange:
        assert self._anchor is not None
        a, b = sorted((self._anchor, self.cursor))
        if linewise or self._visual_mode() is Mode.VISUAL_LINE:
            return TextRange(Pos(a.row, 0), Pos(b.row, 0), True)
        line = self.buffer.line(b.row)
        if b.col >= len(line):  # on an empty line or past `$`: the line break is selected too
            last = self.buffer.line_count() - 1
            end = Pos(b.row + 1, 0) if b.row < last else Pos(b.row, len(line))
        else:
            end = Pos(b.row, b.col + 1)
        return TextRange(a, end, False)

    def _exit_visual(self) -> None:
        self.mode = Mode.NORMAL
        self._anchor = None
        self.cursor = self._clamped(self.cursor, Mode.NORMAL)
        self._curswant = self.cursor.col

    def _visual_command(self, cmd: Command) -> None:
        action = cmd.action
        if cmd.keys[0] not in VISUAL_ACTIONS:  # a motion extends the selection
            if action in ("/", "?"):
                self._open_cmdline(action)
            elif (motion := self._motion(action, cmd.count, cmd.arg, op=None)) is not None:
                self._apply_motion(motion)
            return
        if action == "exit":
            self._exit_visual()
        elif action == "swap":
            assert self._anchor is not None
            self._anchor, self.cursor = self.cursor, self._anchor
            self._curswant = self.cursor.col
        elif action in ("char", "line"):
            target = Mode.VISUAL if action == "char" else Mode.VISUAL_LINE
            if self.mode is target:
                self._exit_visual()
            else:
                self.mode = target
        else:
            rng = self._visual_range(linewise=action.endswith("_lines"))
            if action in ("copy", "yank", "yank_lines"):
                self._exit_visual()
                operators.yank(self, rng, "+" if action == "copy" else cmd.register)
                return
            extent = self._extent(rng)
            self._exit_visual()
            self._run_change(cmd, lambda: self._visual_apply(cmd.keys[0], rng, cmd.register, cmd.count), visual=extent)

    def _visual_apply(self, key: Token, rng: TextRange, register: str | None, count: int | None) -> None:
        action = VISUAL_ACTIONS[key]
        if action in ("delete", "delete_lines"):
            operators.delete(self, rng, register)
        elif action in ("change", "change_lines"):
            operators.change(self, rng, register)
        elif action in ("indent", "dedent"):
            lines = TextRange(Pos(rng.start.row, 0), Pos(rng.end.row, 0), True)
            operators.shift(self, lines, 1 if action == "indent" else -1, count or 1)
        elif action == "put":
            self._visual_put(rng, register, count or 1, keep_registers=key == "P")

    def _visual_put(self, rng: TextRange, register: str | None, count: int, *, keep_registers: bool) -> None:
        value = self.registers.get(register)
        if value is None:
            raise VimError(f"E353: Nothing in register {register or chr(34)}")
        operators.delete(self, rng, "_" if keep_registers else None)
        buf = self.buffer
        if rng.linewise or value.linewise:
            block = "\n".join([value.text] * count)
            if rng.linewise:
                if buf.line_count() == 1 and buf.line(0) == "":
                    self.edit(Pos(0, 0), Pos(0, 0), block)
                    row = 0
                elif rng.start.row >= buf.line_count():
                    end = Pos(buf.line_count() - 1, len(buf.line(buf.line_count() - 1)))
                    self.edit(end, end, "\n" + block)
                    row = end.row + 1
                else:
                    self.edit(Pos(rng.start.row, 0), Pos(rng.start.row, 0), block + "\n")
                    row = rng.start.row
            else:  # linewise text into a charwise selection splits the line
                self.edit(rng.start, rng.start, "\n" + block + "\n")
                row = rng.start.row + 1
            self.move_cursor(Pos(row, first_nonblank(buf.line(row))))
            return
        text = value.text * count
        self.edit(rng.start, rng.start, text)
        self.move_cursor(pos_after(rng.start, text) if "\n" in text else Pos(rng.start.row, rng.start.col + len(text) - 1))

    def _extent(self, rng: TextRange) -> VisualExtent:
        if rng.linewise:
            return VisualExtent(True, len(rng.rows), 0)
        rows = rng.end.row - rng.start.row + 1
        return VisualExtent(False, rows, rng.end.col - rng.start.col if rows == 1 else rng.end.col)

    def _replay_visual(self, record: DotRecord) -> None:
        extent = record.visual
        assert extent is not None
        cur, buf = self.cursor, self.buffer
        last = buf.line_count() - 1
        if extent.linewise:
            rng = TextRange(Pos(cur.row, 0), Pos(min(cur.row + extent.rows - 1, last), 0), True)
        elif extent.rows == 1:
            rng = TextRange(cur, Pos(cur.row, min(cur.col + extent.width, len(buf.line(cur.row)))), False)
        else:
            end_row = min(cur.row + extent.rows - 1, last)
            rng = TextRange(cur, Pos(end_row, min(extent.width, len(buf.line(end_row)))), False)
        self._visual_apply(record.keys[0], rng, record.register, record.count)
        for token in record.keys[1:]:
            self._dispatch_raw(token)

    # == Insert mode =======================================================================

    def _enter_insert(self, kind: str, count: int | None) -> None:
        row, col = self.cursor
        line = self.buffer.line(row)
        if kind == "a" and line:
            col += 1
        elif kind == "I":
            col = first_nonblank(line)
        elif kind == "A":
            col = len(line)
        elif kind in ("o", "O"):
            self._open_line(below=kind == "o")
            row, col = self.cursor
        self.cursor = Pos(row, col)
        self._curswant = col
        self.start_insert("i" if kind == "<Insert>" else kind, count or 1)

    def _open_line(self, *, below: bool) -> None:
        row = self.cursor.row
        line = self.buffer.line(row)
        indent = leading_whitespace(line) if self.options.autoindent else ""
        if below:
            self.edit(Pos(row, len(line)), Pos(row, len(line)), "\n" + indent)
            self.cursor = Pos(row + 1, len(indent))
        else:
            self.edit(Pos(row, 0), Pos(row, 0), indent + "\n")
            self.cursor = Pos(row, len(indent))

    def _insert_key(self, key: Token) -> None:
        if key in ("<Esc>", "<C-c>"):
            self._record_token("<Esc>")
            self._finish_insert()
            return
        if key in _INSERT_MOVES:
            self._insert_move(key)
            return
        if key in _PASTE_KEYS:
            value = self.registers.get("+")
            if value is None:
                return
            key = InsertText(value.text + ("\n" if value.linewise else ""))
        self._insert_apply(key)
        assert self._insert is not None
        self._insert.tokens.append(key)
        self._record_token(key)

    def _insert_apply(self, key: Token) -> None:
        if isinstance(key, InsertText):
            self._insert_string(key.text)
        elif key == "<CR>":
            self._insert_newline()
        elif key in ("<Tab>", "<S-Tab>"):
            self._insert_tab()
        elif key in ("<BS>", "<C-h>"):
            self._insert_backspace()
        elif key == "<Del>":
            self._insert_delete()
        elif key == "<C-w>":
            self._insert_delete_word()
        elif key == "<C-u>":
            self._insert_delete_to_indent()
        elif len(key) == 1:
            self._insert_string(key)
        else:
            raise VimError(f"Unsupported key in Insert mode: {key}")

    def _insert_string(self, text: str) -> None:
        self.edit(self.cursor, self.cursor, text)
        self.cursor = pos_after(self.cursor, text)
        self._curswant = self.cursor.col

    def _insert_newline(self) -> None:
        row, col = self.cursor
        indent = leading_whitespace(self.buffer.line(row)[:col]) if self.options.autoindent else ""
        self.edit(self.cursor, self.cursor, "\n" + indent)
        self.cursor = Pos(row + 1, len(indent))
        self._curswant = self.cursor.col

    def _insert_tab(self) -> None:
        if not self.options.expandtab:
            self._insert_string("\t")
            return
        row, col = self.cursor
        width = indent_width(self.buffer.line(row)[:col], self.options.tabstop)
        self._insert_string(" " * (self.options.tabstop - width % self.options.tabstop))

    def _delete_back_to(self, col: int) -> None:
        row = self.cursor.row
        self.edit(Pos(row, col), self.cursor, "")
        self.cursor = Pos(row, col)
        self._curswant = col

    def _insert_backspace(self) -> None:
        row, col = self.cursor
        if col == 0:
            if row > 0:  # join with the previous line
                prev = len(self.buffer.line(row - 1))
                self.edit(Pos(row - 1, prev), Pos(row, 0), "")
                self.cursor = Pos(row - 1, prev)
                self._curswant = prev
            return
        before = self.buffer.line(row)[:col]
        n = (col - 1) % self.options.sw + 1 if self.options.expandtab and not before.strip(" ") else 1
        self._delete_back_to(col - n)

    def _insert_delete(self) -> None:
        row, col = self.cursor
        line = self.buffer.line(row)
        if col < len(line):
            self.edit(self.cursor, Pos(row, col + 1), "")
        elif row < self.buffer.line_count() - 1:
            self.edit(self.cursor, Pos(row + 1, 0), "")

    def _insert_delete_word(self) -> None:
        row, col = self.cursor
        if col == 0:
            self._insert_backspace()
            return
        line = self.buffer.line(row)
        i = col
        while i > 0 and line[i - 1] in " \t":
            i -= 1
        if i > 0:
            cls = char_class(line[i - 1])
            while i > 0 and char_class(line[i - 1]) == cls:
                i -= 1
        self._delete_back_to(i)

    def _insert_delete_to_indent(self) -> None:
        row, col = self.cursor
        if col == 0:
            self._insert_backspace()
            return
        indent = first_nonblank(self.buffer.line(row))
        self._delete_back_to(indent if col > indent else 0)

    def _insert_move(self, key: str) -> None:
        row, col = self.cursor
        line = self.buffer.line(row)
        keep_want = False
        if key == "<Left>":
            col = max(0, col - 1)
        elif key == "<Right>":
            col = min(len(line), col + 1)
        elif key == "<Home>":
            col = 0
        elif key == "<End>":
            col = len(line)
        else:
            row = max(0, row - 1) if key == "<Up>" else min(self.buffer.line_count() - 1, row + 1)
            col = min(self._curswant, len(self.buffer.line(row)))
            keep_want = True
        if (row, col) == self.cursor:
            return
        self._break_insert()
        self.cursor = Pos(row, col)
        if not keep_want:
            self._curswant = col

    def _break_insert(self) -> None:
        """Cursor keys in Insert mode end the undo step, and `.` afterwards repeats only
        what is typed from here on, as an `i` command (vim's ins-special-special)."""
        if self._change_open:
            self._undo.end()
            self._undo.begin(self.cursor)
        if not self._replaying:
            if self._recording is not None and len(self._recording.keys) > 1:
                self.shared.last_change = self._recording
            self._recording = DotRecord(["i"])
        self._insert = _InsertSession("i", 1)

    def _finish_insert(self, *, move_left: bool = True) -> None:
        session = self._insert
        if session is not None and session.count > 1 and session.tokens:
            for _ in range(session.count - 1):
                if session.kind in ("o", "O"):
                    self._open_line(below=session.kind == "o")
                for token in session.tokens:
                    self._insert_apply(token)
        self._insert = None
        row, col = self.cursor
        self.cursor = self._clamped(Pos(row, col - 1 if move_left and col > 0 else col), Mode.NORMAL)
        self._curswant = self.cursor.col
        self._settle(Mode.NORMAL)

    # == command line ======================================================================

    def _open_cmdline(self, prefix: str, *, operator: Command | None = None) -> None:
        return_mode = self.mode if self.mode.is_visual else Mode.NORMAL
        self._cmdline = _Cmdline(prefix, return_mode, operator)
        self.mode = Mode.COMMAND

    def _cmdline_key(self, key: Token) -> None:
        c = self._cmdline
        assert c is not None
        if key in _PASTE_KEYS:
            value = self.registers.get("+")
            if value is None:
                return
            key = InsertText(value.text.split("\n")[0])
        self._record_token(key)
        if key in ("<Esc>", "<C-c>"):
            self._cmdline = None
            self._recording = None
            self._settle(c.return_mode)
        elif key == "<CR>":
            self._submit_cmdline()
        elif isinstance(key, InsertText) or (len(key) == 1):
            text = key.text if isinstance(key, InsertText) else key
            c.text = c.text[: c.cursor] + text + c.text[c.cursor :]
            c.cursor += len(text)
        elif key in ("<BS>", "<C-h>"):
            if not c.text:  # backspace on an empty command line leaves it
                self._cmdline = None
                self._recording = None
                self._settle(c.return_mode)
            elif c.cursor > 0:
                c.text = c.text[: c.cursor - 1] + c.text[c.cursor :]
                c.cursor -= 1
        elif key == "<Del>":
            c.text = c.text[: c.cursor] + c.text[c.cursor + 1 :]
        elif key == "<C-w>":
            i = c.cursor
            while i > 0 and c.text[i - 1] == " ":
                i -= 1
            while i > 0 and c.text[i - 1] != " ":
                i -= 1
            c.text, c.cursor = c.text[:i] + c.text[c.cursor :], i
        elif key == "<C-u>":
            c.text, c.cursor = c.text[c.cursor :], 0
        elif key in ("<Left>", "<Right>", "<Home>", "<End>"):
            c.cursor = {
                "<Left>": max(0, c.cursor - 1),
                "<Right>": min(len(c.text), c.cursor + 1),
                "<Home>": 0,
                "<End>": len(c.text),
            }[key]
        elif key in ("<Up>", "<Down>"):
            self._cmdline_history(c, older=key == "<Up>")
        else:
            raise VimError(f"Unsupported key in command line: {key}")

    def _cmdline_history(self, c: _Cmdline, *, older: bool) -> None:
        history = self.shared.history[":" if c.prefix == ":" else "/"]
        if not history:
            return
        if c.history_index is None:
            if not older:
                return
            c.draft = c.text
            c.history_index = len(history)
        index = c.history_index + (-1 if older else 1)
        if index < 0:
            return
        if index >= len(history):
            c.history_index, c.text = None, c.draft
        else:
            c.history_index, c.text = index, history[index]
        c.cursor = len(c.text)

    def _submit_cmdline(self) -> None:
        c = self._cmdline
        assert c is not None
        self._cmdline = None
        text = c.text
        history = self.shared.history[":" if c.prefix == ":" else "/"]
        if text and (not history or history[-1] != text):
            history.append(text)
            del history[:-_HISTORY_LIMIT]
        self.mode = c.return_mode
        try:
            if c.prefix == ":":
                excmd.run(self, text)
            else:
                self._submit_search(text, forward=c.prefix == "/", operator=c.operator)
        except BaseException:
            self._recording = None
            raise
        finally:
            if self.mode not in (Mode.INSERT, Mode.COMMAND):
                self._settle(self.mode)

    def _submit_search(self, text: str, *, forward: bool, operator: Command | None) -> None:
        pattern = text or self.shared.last_search
        if not pattern:
            raise VimError("E35: No previous regular expression")
        self.shared.last_search = pattern
        self.shared.search_forward = forward
        motion = self._search_motion(pattern, forward, 1)
        if operator is None:
            self._apply_motion(motion)
            return
        self._apply_operator(operator.operator, motion_range(self.buffer, self.cursor, motion), operator.register)
