"""Key mappings (vim's :map): key sequences that run a host command or other keys.

Matching follows vim:
  * the keys exactly match a mapping and no longer mapping starts with them: run it now
  * the keys are the start of a longer mapping: wait; after 'timeoutlen' run the exact
    match if there is one, otherwise treat the keys as unmapped (built-in commands)
  * nothing starts with these keys: they are unmapped
The trie is pure Python so the editor engine and the IDE panels share it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from vimcore.keyparser import parse_keys


@dataclass(frozen=True)
class MapCommand:
    """Run a host command by id (e.g. "file.find")."""

    command: str


@dataclass(frozen=True)
class MapKeys:
    """Replay other keys, without re-mapping them (vim's noremap)."""

    keys: tuple[str, ...]


MapTarget = MapCommand | MapKeys


class _Node:
    __slots__ = ("children", "target")

    def __init__(self) -> None:
        self.children: dict[str, _Node] = {}
        self.target: MapTarget | None = None


class KeyTrie:
    def __init__(self) -> None:
        self._root = _Node()
        self._count = 0

    def __len__(self) -> int:
        return self._count

    def add(self, keys: Sequence[str], target: MapTarget) -> None:
        if not keys:
            raise ValueError("empty key sequence")
        node = self._root
        for key in keys:
            node = node.children.setdefault(key, _Node())
        if node.target is None:
            self._count += 1
        node.target = target

    def lookup(self, keys: Sequence[str]) -> tuple[MapTarget | None, bool]:
        """(exact target or None, whether a longer mapping starts with `keys`)."""
        node = self._root
        for key in keys:
            if not isinstance(key, str) or (node := node.children.get(key)) is None:
                return None, False
        return node.target, bool(node.children)

    def items(self) -> Iterator[tuple[tuple[str, ...], MapTarget]]:
        stack: list[tuple[tuple[str, ...], _Node]] = [((), self._root)]
        while stack:
            keys, node = stack.pop()
            if node.target is not None:
                yield keys, node.target
            stack.extend((keys + (k,), child) for k, child in node.children.items())


@dataclass
class Mappings:
    normal: KeyTrie = field(default_factory=KeyTrie)
    visual: KeyTrie = field(default_factory=KeyTrie)
    timeoutlen: int = 1000  # milliseconds


_LEADER_RE = re.compile("<leader>", re.IGNORECASE)


def expand_lhs(lhs: str, leader: str) -> list[str]:
    """'<leader>f' with leader '<Space>' -> [' ', 'f']."""
    return parse_keys(_LEADER_RE.sub(lambda _m: leader, lhs))
