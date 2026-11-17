"""Repeat support. V1: the `.` command (q/@ macros arrive in Phase V2).

A DotRecord holds the keys of the last change without its count/register prefix, plus
everything typed in the Insert or command-line mode that change entered, up to <Esc>/<CR>.
Replaying feeds those keys again; a new count replaces the recorded one, as in vim.
"""

from __future__ import annotations

from dataclasses import dataclass

from vimcore.keyparser import Token


@dataclass(frozen=True)
class VisualExtent:
    """Size of a Visual selection, so `.` acts on the same amount of text from the cursor."""

    linewise: bool
    rows: int
    width: int  # single-line charwise: number of characters; multi-line: end column (exclusive)


@dataclass
class DotRecord:
    keys: list[Token]  # for a Visual change, keys[0] is the Visual operator key (d, c, >, ...)
    count: int | None = None
    register: str | None = None
    visual: VisualExtent | None = None

    def replay_tokens(self) -> list[Token]:
        prefix: list[Token] = ['"', self.register] if self.register else []
        if self.count:
            prefix += list(str(self.count))
        return prefix + self.keys
