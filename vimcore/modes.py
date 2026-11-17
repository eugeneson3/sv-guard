"""Editor modes. The state machine itself lives in engine.VimEngine."""

from __future__ import annotations

from enum import Enum


class Mode(Enum):
    NORMAL = "NORMAL"
    INSERT = "INSERT"
    VISUAL = "VISUAL"
    VISUAL_LINE = "V-LINE"
    COMMAND = "COMMAND"  # command line: ':' ex commands and '/' '?' searches

    @property
    def label(self) -> str:
        return self.value

    @property
    def is_visual(self) -> bool:
        return self in (Mode.VISUAL, Mode.VISUAL_LINE)

    @property
    def accepts_text(self) -> bool:
        """Modes where typed characters become text, so an IME (e.g. Hangul) should be on."""
        return self in (Mode.INSERT, Mode.COMMAND)

    @property
    def block_cursor(self) -> bool:
        return self in (Mode.NORMAL, Mode.VISUAL, Mode.VISUAL_LINE)
