"""vimcore: a GUI-independent vim engine (Phase V1 subset).

    from vimcore import MemoryBuffer, VimEngine
    eng = VimEngine(MemoryBuffer("foo bar"))
    eng.feed_keys("dw")   # buffer is now "bar"
"""

from vimcore.buffer import MemoryBuffer, Pos, TextBuffer
from vimcore.engine import CmdlineView, FeedResult, HostRequest, Message, Selection, SharedState, VimEngine
from vimcore.keyparser import InsertText, parse_keys
from vimcore.modes import Mode
from vimcore.options import VimOptions
from vimcore.registers import Clipboard, Registers, RegisterValue

__all__ = [
    "Clipboard",
    "CmdlineView",
    "FeedResult",
    "HostRequest",
    "InsertText",
    "MemoryBuffer",
    "Message",
    "Mode",
    "Pos",
    "RegisterValue",
    "Registers",
    "Selection",
    "SharedState",
    "TextBuffer",
    "VimEngine",
    "VimOptions",
    "parse_keys",
]
