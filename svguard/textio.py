"""Source decoding and byte-offset -> character-column conversion.

slang reports byte offsets (and byte columns); editors and people count characters.
A line like `/* 가나다 */ assign o = x;` puts `x` at byte column 30 but character column 24.
"""

from __future__ import annotations

import codecs
import os
import re
import shutil
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

# cp949 is the legacy default on Korean Windows; many student files are still saved with it.
_FALLBACK_ENCODINGS = ("utf-8", "cp949")
_NEWLINE = re.compile(b"\n")


@dataclass(frozen=True)
class SourceText:
    text: str
    encoding: str  # "utf-8", "utf-8-sig", "cp949" or "latin-1"


def decode_source(data: bytes) -> SourceText:
    if data.startswith(codecs.BOM_UTF8):
        return SourceText(data[len(codecs.BOM_UTF8) :].decode("utf-8", errors="replace"), "utf-8-sig")
    for encoding in _FALLBACK_ENCODINGS:
        try:
            return SourceText(data.decode(encoding), encoding)
        except UnicodeDecodeError:
            continue
    return SourceText(data.decode("latin-1"), "latin-1")  # never fails


def read_source(path: Path | str) -> SourceText:
    return decode_source(Path(path).read_bytes())


def detect_eol(text: str) -> str:
    """Dominant line ending of `text`: "\\r\\n" or "\\n"."""
    crlf = text.count("\r\n")
    return "\r\n" if crlf > text.count("\n") - crlf else "\n"


def normalize_eol(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def write_source(path: Path | str, text: str, encoding: str = "utf-8", eol: str = "\n") -> None:
    """Write LF-normalized `text` with the given encoding and line ending.

    The data goes to a temporary sibling first and is then swapped in, so a crash
    mid-write never leaves a truncated source file. Raises UnicodeEncodeError if
    `text` cannot be represented in `encoding` (e.g. an emoji in a cp949 file);
    the file is left untouched in that case.
    """
    path = Path(path)
    data = text.replace("\n", eol).encode(encoding)  # "utf-8-sig" adds the BOM itself
    tmp = path.with_name(f".{path.name}.svguard-tmp")
    try:
        tmp.write_bytes(data)
        if path.exists():
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except OSError:
        # e.g. another program holds the file open on Windows: fall back to an in-place write
        tmp.unlink(missing_ok=True)
        path.write_bytes(data)


class LineIndex:
    """Maps byte offsets within `data` (encoded as `encoding`) to 1-based (line, char column)."""

    def __init__(self, data: bytes, encoding: str = "utf-8") -> None:
        self._data = data
        # utf-8-sig strips the BOM only at offset 0, so line-1 columns stay correct.
        self._encoding = encoding
        self._starts = [0, *(m.end() for m in _NEWLINE.finditer(data))]

    @classmethod
    def from_text(cls, text: str) -> LineIndex:
        """Index for text handed to slang as a Python str (slang sees its UTF-8 encoding)."""
        return cls(text.encode("utf-8"), "utf-8")

    @property
    def line_count(self) -> int:
        return len(self._starts)

    def position(self, offset: int) -> tuple[int, int]:
        offset = max(0, min(offset, len(self._data)))
        line = bisect_right(self._starts, offset) - 1
        start = self._starts[line]
        col = len(self._data[start:offset].decode(self._encoding, errors="replace")) + 1
        return line + 1, col
