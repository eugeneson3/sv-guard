"""Fuzzy matching for the palette and the finders (no Qt; unit-testable).

`query` must appear in `text` as a subsequence. Matches that start words ("gf" in
"go to file"), follow each other, or sit in short texts score higher.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import TypeVar

T = TypeVar("T")

_CONSECUTIVE = 6
_WORD_START = 8
_CAMEL = 6


def fuzzy_score(query: str, text: str) -> int | None:
    if not query:
        return 0
    q, t = query.lower(), text.lower()
    score = 0
    pos = 0
    previous = -2
    for ch in q:
        if ch == " ":
            continue
        idx = t.find(ch, pos)
        if idx < 0:
            return None
        bonus = 1
        if idx == previous + 1:
            bonus += _CONSECUTIVE
        if idx == 0 or not t[idx - 1].isalnum():
            bonus += _WORD_START
        elif text[idx].isupper() and text[idx - 1].islower():
            bonus += _CAMEL
        score += bonus - min(idx - pos, 9) // 3
        previous, pos = idx, idx + 1
    return score - len(t) // 16


def fuzzy_filter(query: str, items: Sequence[T], key: Callable[[T], str] = str, limit: int = 200) -> list[T]:
    """Items matching `query`, best first; ties keep their original order."""
    if not query.strip():
        return list(items[:limit])
    scored: Iterable[tuple[int, int, T]] = (
        (score, -i, item) for i, item in enumerate(items) if (score := fuzzy_score(query, key(item))) is not None
    )
    return [item for _score, _i, item in sorted(scored, key=lambda s: (s[0], s[1]), reverse=True)[:limit]]
