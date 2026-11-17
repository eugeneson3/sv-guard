"""Registers: unnamed ("), last yank (0), named a-z (A-Z appends), black hole (_),
and the system clipboard (+ and *) through a host-provided Clipboard."""

from __future__ import annotations

from dataclasses import dataclass
from string import ascii_letters
from typing import Protocol

VALID_NAMES = frozenset('"0_+*' + ascii_letters)


@dataclass(frozen=True)
class RegisterValue:
    text: str  # linewise text has no trailing newline
    linewise: bool = False


class Clipboard(Protocol):
    def get(self) -> str: ...

    def set(self, text: str) -> None: ...


class Registers:
    def __init__(self, clipboard: Clipboard | None = None, *, unnamedplus: bool = False) -> None:
        self.clipboard = clipboard
        self.unnamedplus = unnamedplus  # like `set clipboard=unnamedplus`
        self._store: dict[str, RegisterValue] = {}
        self._clipboard_value: RegisterValue | None = None  # last value we put there

    @staticmethod
    def is_valid(name: str) -> bool:
        return name in VALID_NAMES

    def snapshot(self) -> dict[str, RegisterValue]:
        """Stored registers (unnamed, 0, a-z); the clipboard is never part of it."""
        return dict(self._store)

    def restore(self, values: dict[str, RegisterValue]) -> None:
        for name, value in values.items():
            if name == '"' or name == "0" or (len(name) == 1 and name.islower()):
                self._store[name] = value

    def get(self, name: str | None = None) -> RegisterValue | None:
        name = name or '"'
        if name == "_":
            return None
        if name in "+*" or (name == '"' and self.unnamedplus):
            return self._from_clipboard() or self._store.get('"')
        return self._store.get(name.lower())

    def put(self, name: str | None, value: RegisterValue, *, yank: bool) -> None:
        name = name or '"'
        if name == "_":
            return
        if name.isupper():
            name = name.lower()
            if (old := self._store.get(name)) is not None:
                linewise = old.linewise or value.linewise
                value = RegisterValue(old.text + ("\n" if linewise else "") + value.text, linewise)
        if name in "+*":
            self._to_clipboard(value)
        elif name != '"':
            self._store[name] = value
        self._store['"'] = value
        if yank and name == '"':
            self._store["0"] = value
        if self.unnamedplus and name == '"':
            self._to_clipboard(value)

    def _to_clipboard(self, value: RegisterValue) -> None:
        if self.clipboard is None:
            return
        # Vim convention: a trailing newline on the clipboard means "linewise".
        self.clipboard.set(value.text + ("\n" if value.linewise else ""))
        self._clipboard_value = value

    def _from_clipboard(self) -> RegisterValue | None:
        if self.clipboard is None:
            return None
        text = self.clipboard.get()
        if not text:
            return None
        mine = self._clipboard_value
        if mine is not None and text == mine.text + ("\n" if mine.linewise else ""):
            return mine
        if text.endswith("\n"):
            return RegisterValue(text[:-1].replace("\r\n", "\n"), linewise=True)
        return RegisterValue(text.replace("\r\n", "\n"))
