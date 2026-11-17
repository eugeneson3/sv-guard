"""Key notation and the Normal/Visual command grammar.

Keys are tokens: a single character ("d", "%", " "), a special key in vim notation
("<Esc>", "<CR>", "<C-r>"), or InsertText for text committed in one piece (IME, paste).

The grammar is parsed from scratch on every key from the list of pending keys:

    ["x] [count] ( shorthand | operator [count] (operator | motion) | simple | motion )

which yields INCOMPLETE (wait for more keys), CANCEL (<Esc> mid-command),
Invalid (unsupported sequence, shown on the status line) or a Command.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class InsertText:
    """Literal text entered in one go (IME commit, paste); never read as a key name."""

    text: str


Token = str | InsertText

_SPECIAL_NAMES = {
    "esc": "<Esc>",
    "cr": "<CR>",
    "enter": "<CR>",
    "return": "<CR>",
    "bs": "<BS>",
    "backspace": "<BS>",
    "del": "<Del>",
    "delete": "<Del>",
    "tab": "<Tab>",
    "s-tab": "<S-Tab>",
    "space": " ",
    "lt": "<",
    "bar": "|",
    "bslash": "\\",
    "up": "<Up>",
    "down": "<Down>",
    "left": "<Left>",
    "right": "<Right>",
    "home": "<Home>",
    "end": "<End>",
    "pageup": "<PageUp>",
    "pagedown": "<PageDown>",
    "insert": "<Insert>",
}
_CTRL_RE = re.compile(r"c-(s-)?(.)")


def special_key(body: str) -> str | None:
    """Canonical token for the text inside <...>, or None if it is not a key name."""
    low = body.lower()
    if low in _SPECIAL_NAMES:
        return _SPECIAL_NAMES[low]
    if match := _CTRL_RE.fullmatch(low):
        shift, char = match.groups()
        if char == "[" and not shift:
            return "<Esc>"
        return f"<C-{'S-' if shift else ''}{char}>"
    return None


def parse_keys(notation: str) -> list[str]:
    """'d2w<Esc>' -> ['d', '2', 'w', '<Esc>']. An unknown <...> is taken literally."""
    keys: list[str] = []
    i = 0
    while i < len(notation):
        if notation[i] == "<":
            close = notation.find(">", i + 1)
            if close > i + 1 and (key := special_key(notation[i + 1 : close])) is not None:
                keys.append(key)
                i = close + 1
                continue
        keys.append(notation[i])
        i += 1
    return keys


def is_special(token: Token) -> bool:
    return isinstance(token, str) and len(token) > 1 and token.startswith("<") and token.endswith(">")


def format_keys(tokens: Sequence[Token]) -> str:
    out = []
    for token in tokens:
        if isinstance(token, InsertText):
            out.append(token.text)
        else:
            out.append("<Space>" if token == " " else token)
    return "".join(out)


# -- grammar tables ----------------------------------------------------------------

OPERATORS = frozenset("dcy><")

# key -> canonical motion name
MOTION_KEYS = {
    "h": "h", "<Left>": "h", "<BS>": "h",
    "l": "l", "<Right>": "l", " ": "l",
    "j": "j", "<Down>": "j",
    "k": "k", "<Up>": "k",
    "+": "+", "<CR>": "+", "-": "-",
    "w": "w", "W": "W", "b": "b", "B": "B", "e": "e", "E": "E",
    "0": "0", "<Home>": "0", "^": "^", "$": "$", "<End>": "$",
    "G": "G", ";": ";", ",": ",", "%": "%", "n": "n", "N": "N",
    "/": "/", "?": "?",
}  # fmt: skip
CHAR_MOTIONS = frozenset("fFtT")

# Normal-mode shorthands for operator + motion ("line" = the doubled operator, like dd)
SHORTHANDS = {
    "x": ("d", "l"), "<Del>": ("d", "l"), "X": ("d", "h"),
    "D": ("d", "$"), "C": ("c", "$"),
    "s": ("c", "l"), "S": ("c", "line"), "Y": ("y", "line"),
}  # fmt: skip

SIMPLE_COMMANDS = frozenset(
    {"p", "P", "u", "<C-r>", ".", "i", "a", "I", "A", "o", "O", "<Insert>", "v", "V", ":",
     "<C-d>", "<C-u>", "<C-f>", "<C-b>", "<PageDown>", "<PageUp>", "<Esc>", "<C-c>"}
)  # fmt: skip

# two-key commands: prefix -> {second key: command name}
PREFIX_COMMANDS = {"g": {"g": "gg"}, "Z": {"Z": "ZZ", "Q": "ZQ"}}
PREFIX_MOTIONS = frozenset({"gg"})

VISUAL_ACTIONS = {
    "d": "delete", "x": "delete", "<Del>": "delete",
    "X": "delete_lines", "D": "delete_lines",
    "c": "change", "s": "change",
    "C": "change_lines", "S": "change_lines", "R": "change_lines",
    "y": "yank", "Y": "yank_lines",
    ">": "indent", "<": "dedent",
    "p": "put", "P": "put",
    "o": "swap", "O": "swap",
    "v": "char", "V": "line",
    "<Esc>": "exit", "<C-c>": "copy",
}  # fmt: skip


class _Incomplete:
    def __repr__(self) -> str:
        return "INCOMPLETE"


class _Cancel:
    def __repr__(self) -> str:
        return "CANCEL"


INCOMPLETE = _Incomplete()
CANCEL = _Cancel()


@dataclass(frozen=True)
class Invalid:
    keys: tuple[Token, ...]
    message: str | None = None


@dataclass(frozen=True)
class Command:
    keys: tuple[Token, ...]  # without register/count prefixes; replayed by "."
    action: str  # motion name, simple command, "line" (dd/cc/...), or visual action
    register: str | None = None
    count: int | None = None
    operator: str | None = None
    arg: str | None = None  # character after f/F/t/T


ParseResult = Command | Invalid | _Incomplete | _Cancel


def parse_command(keys: Sequence[Token], *, visual: bool = False) -> ParseResult:
    if len(keys) > 1 and keys[-1] in ("<Esc>", "<C-c>"):
        return CANCEL
    if any(isinstance(k, InsertText) for k in keys):
        return Invalid(tuple(keys))

    i = 0
    register = None
    if keys[0] == '"':
        if len(keys) < 2:
            return INCOMPLETE
        register = keys[1]
        i = 2
    count1, i = _read_count(keys, i)
    if i == len(keys):
        return INCOMPLETE
    key = keys[i]

    if visual:
        if key in VISUAL_ACTIONS:
            return Command((key,), VISUAL_ACTIONS[key], register, count1)
        return _motion_command(keys, i, register, count1)

    if key in SHORTHANDS:
        operator, motion = SHORTHANDS[key]
        return Command((key,), motion, register, count1, operator=operator)
    if key in OPERATORS:
        count2, j = _read_count(keys, i + 1)
        if j == len(keys):
            return INCOMPLETE
        count = count1 * count2 if count1 and count2 else count1 or count2
        if keys[j] == key:
            return Command((key, key), "line", register, count, operator=key)
        motion = _parse_motion(keys, j)
        if not isinstance(motion, tuple):
            return motion
        action, arg = motion
        return Command((key, *keys[j:]), action, register, count, operator=key, arg=arg)
    if key in SIMPLE_COMMANDS:
        return Command((key,), key, register, count1)
    if key in PREFIX_COMMANDS and key != "g":
        if i + 1 == len(keys):
            return INCOMPLETE
        name = PREFIX_COMMANDS[key].get(keys[i + 1])
        return Command(tuple(keys[i:]), name, register, count1) if name else Invalid(tuple(keys))
    return _motion_command(keys, i, register, count1)


def _motion_command(keys: Sequence[Token], i: int, register: str | None, count: int | None) -> ParseResult:
    motion = _parse_motion(keys, i)
    if not isinstance(motion, tuple):
        return motion
    action, arg = motion
    return Command(tuple(keys[i:]), action, register, count, arg=arg)


def _parse_motion(keys: Sequence[Token], i: int) -> tuple[str, str | None] | Invalid | _Incomplete:
    """Parse a motion that must end exactly at the last pending key."""
    key = keys[i]
    if key in MOTION_KEYS:
        return (MOTION_KEYS[key], None) if i + 1 == len(keys) else Invalid(tuple(keys))
    if key in CHAR_MOTIONS:
        if i + 1 == len(keys):
            return INCOMPLETE
        arg = keys[i + 1]
        if not isinstance(arg, str) or len(arg) != 1:
            return Invalid(tuple(keys))
        return key, arg
    if key == "g":
        if i + 1 == len(keys):
            return INCOMPLETE
        name = PREFIX_COMMANDS["g"].get(keys[i + 1])
        return (name, None) if name in PREFIX_MOTIONS else Invalid(tuple(keys))
    return Invalid(tuple(keys))


def read_count(keys: Sequence[Token], i: int = 0) -> tuple[int | None, int]:
    """Count at keys[i:] and the index after it."""
    return _read_count(keys, i)


def _read_count(keys: Sequence[Token], i: int) -> tuple[int | None, int]:
    """Digits form a count; a leading '0' is the motion, not a count."""
    if i >= len(keys) or keys[i] not in tuple("123456789"):
        return None, i
    j = i
    while j < len(keys) and isinstance(keys[j], str) and len(keys[j]) == 1 and keys[j].isdigit():
        j += 1
    return int("".join(keys[i:j])), j
