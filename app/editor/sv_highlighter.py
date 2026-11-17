"""SystemVerilog syntax highlighting.

A single left-to-right scan per line (instead of independent regex rules) so that
`//` inside a string or `"` inside a comment never starts the wrong token.
Block comments carry over between lines through the block state.
"""

from __future__ import annotations

import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument

from app.editor.sv_keywords import KEYWORDS, TYPE_KEYWORDS

_NORMAL = 0
_IN_BLOCK_COMMENT = 1

_TOKEN_RE = re.compile(
    r"""
      (?P<line_comment>//.*)
    | (?P<block_comment>/\*)
    | (?P<string>"(?:\\.|[^"\\])*"?)
    | (?P<directive>`[A-Za-z_]\w*)
    | (?P<system>\$[A-Za-z_][\w$]*)
    | (?P<number>
          (?:\d[\d_]*)?'[sS]?[bBoOdDhH][0-9a-fA-FxXzZ?_]+      # 8'hFF  'b1010  4'sd3
        | '[01xXzZ](?!\w)                                      # '0 '1 'x 'z
        | \d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?(?:fs|ps|ns|us|ms|s)?(?!\w)  # 42 1.5e3 10ns
      )
    | (?P<ident>[A-Za-z_][\w$]*)
    """,
    re.VERBOSE,
)

# (light, dark) foreground colors
_PALETTE = {
    "keyword": ("#1f4fd8", "#569cd6"),
    "type": ("#7a3e9d", "#4ec9b0"),
    "comment": ("#6a737d", "#6a9955"),
    "string": ("#b3261e", "#ce9178"),
    "number": ("#0b7a75", "#b5cea8"),
    "directive": ("#9a6700", "#c586c0"),
    "system": ("#795e26", "#dcdcaa"),
}


def _make_formats(dark: bool) -> dict[str, QTextCharFormat]:
    formats = {}
    for name, (light_color, dark_color) in _PALETTE.items():
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(dark_color if dark else light_color))
        if name == "keyword":
            fmt.setFontWeight(QFont.Weight.Bold)
        if name == "comment":
            fmt.setFontItalic(True)
        formats[name] = fmt
    return formats


class SvHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument, *, dark: bool = False) -> None:
        super().__init__(document)
        self._formats = _make_formats(dark)

    def set_dark(self, dark: bool) -> None:
        self._formats = _make_formats(dark)
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt override)
        self.setCurrentBlockState(_NORMAL)
        pos = 0
        if self.previousBlockState() == _IN_BLOCK_COMMENT:
            pos = self._block_comment(text, start=0, search_from=0)
            if pos < 0:
                return
        while (match := _TOKEN_RE.search(text, pos)) is not None:
            kind = match.lastgroup
            start = match.start()
            if kind == "block_comment":
                pos = self._block_comment(text, start=start, search_from=start + 2)  # "/*/" is not closed
                if pos < 0:
                    return
                continue
            if kind == "ident":
                word = match.group()
                kind = "type" if word in TYPE_KEYWORDS else "keyword" if word in KEYWORDS else None
            elif kind == "line_comment":
                kind = "comment"
            if kind is not None:
                self.setFormat(start, match.end() - start, self._formats[kind])
            pos = match.end()

    def _block_comment(self, text: str, *, start: int, search_from: int) -> int:
        """Format a block comment beginning at `start`; return the position after it,
        or -1 if it runs past the end of the line."""
        end = text.find("*/", search_from)
        if end < 0:
            self.setFormat(start, len(text) - start, self._formats["comment"])
            self.setCurrentBlockState(_IN_BLOCK_COMMENT)
            return -1
        self.setFormat(start, end + 2 - start, self._formats["comment"])
        return end + 2
