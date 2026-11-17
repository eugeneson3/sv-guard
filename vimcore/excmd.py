"""Ex commands typed after ':' (a small subset).

File and window effects are returned to the host as HostRequests; the engine never
touches files itself.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from vimcore.options import set_option

if TYPE_CHECKING:
    from vimcore.engine import VimEngine

# full name -> minimum abbreviation length (vim's rule: :w :wr :wri ... all mean :write)
_COMMANDS = {
    "write": 1,
    "quit": 1,
    "wq": 2,
    "xit": 1,
    "exit": 3,
    "wall": 2,
    "qall": 2,
    "quitall": 5,
    "wqall": 3,
    "xall": 2,
    "edit": 1,
    "set": 2,
    "nohlsearch": 3,
    "bnext": 2,
    "bprevious": 2,
    "bNext": 2,
}
_BUFFER_COMMANDS = {"bnext": "tab.next", "bprevious": "tab.previous", "bNext": "tab.previous"}
_COMMAND_RE = re.compile(r"\s*([A-Za-z]*)(!?)\s*(.*)")


class ExError(Exception):
    pass


def resolve(name: str) -> str | None:
    if name in _COMMANDS:
        return name
    matches = [full for full, shortest in _COMMANDS.items() if len(name) >= shortest and full.startswith(name)]
    return matches[0] if len(matches) == 1 else None


def run(eng: VimEngine, text: str) -> None:
    text = text.strip().lstrip(":").strip()
    if not text:
        return
    if text == "$" or text.isdigit():
        eng.goto_line(eng.buffer.line_count() if text == "$" else int(text))
        return
    first, _, rest = text.partition(" ")
    if first in eng.shared.host_commands:  # IDE commands by id, e.g. :file.find
        count = int(rest) if rest.strip().isdigit() else None
        eng.request("command", first, count=count)
        return
    match = _COMMAND_RE.fullmatch(text)
    name = resolve(match.group(1)) if match and match.group(1) else None
    if name is None:
        raise ExError(f"E492: Not an editor command: {text}")
    force, arg = match.group(2) == "!", match.group(3).strip()

    if name in _BUFFER_COMMANDS:
        eng.request("command", _BUFFER_COMMANDS[name], count=int(arg) if arg.isdigit() else None)
    elif name == "write":
        eng.request("write", arg or None, force=force)
    elif name == "quit":
        eng.request("quit", force=force)
    elif name == "wq":
        eng.request("write", arg or None, force=force)
        eng.request("quit", force=force)
    elif name in ("xit", "exit"):
        eng.request("write_if_modified", arg or None)
        eng.request("quit", force=force)
    elif name == "wall":
        eng.request("write_all")
    elif name in ("qall", "quitall"):
        eng.request("quit_all", force=force)
    elif name in ("wqall", "xall"):
        eng.request("write_all")
        eng.request("quit_all", force=force)
    elif name == "edit":
        if force and not arg:
            eng.request("reload")
        elif not arg:
            raise ExError("E32: No file name")
        else:
            eng.request("edit", arg)
    elif name == "set":
        _set(eng, arg)
    # nohlsearch: accepted; search highlighting is not drawn yet


def _set(eng: VimEngine, arg: str) -> None:
    if not arg:
        o = eng.options
        eng.set_message(f"  tabstop={o.tabstop} shiftwidth={o.sw} {'' if o.expandtab else 'no'}expandtab")
        return
    shown = []
    for item in arg.split():
        try:
            if (message := set_option(eng.options, item)) is not None:
                shown.append(message.strip())
        except ValueError as exc:
            raise ExError(str(exc)) from None
    eng.request("options")
    if shown:
        eng.set_message("  " + "  ".join(shown))
