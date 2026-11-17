"""Map Hangul typed on a 2-set (두벌식) keyboard back to the QWERTY keys pressed.

Normal mode normally runs with the IME disabled, so keys arrive as Latin letters.
This is the fallback for when an IME still commits Hangul (e.g. "ㅓ" for j).
Composed syllables and compound jamo are decomposed first ("ㅘ" -> "hk", "다" -> "ek").
"""

from __future__ import annotations

_JAMO_TO_KEY = {
    "ㅂ": "q", "ㅈ": "w", "ㄷ": "e", "ㄱ": "r", "ㅅ": "t", "ㅛ": "y", "ㅕ": "u", "ㅑ": "i", "ㅐ": "o", "ㅔ": "p",
    "ㅁ": "a", "ㄴ": "s", "ㅇ": "d", "ㄹ": "f", "ㅎ": "g", "ㅗ": "h", "ㅓ": "j", "ㅏ": "k", "ㅣ": "l",
    "ㅋ": "z", "ㅌ": "x", "ㅊ": "c", "ㅍ": "v", "ㅠ": "b", "ㅜ": "n", "ㅡ": "m",
    "ㅃ": "Q", "ㅉ": "W", "ㄸ": "E", "ㄲ": "R", "ㅆ": "T", "ㅒ": "O", "ㅖ": "P",
}  # fmt: skip

_COMPOUND = {
    "ㅘ": "ㅗㅏ", "ㅙ": "ㅗㅐ", "ㅚ": "ㅗㅣ", "ㅝ": "ㅜㅓ", "ㅞ": "ㅜㅔ", "ㅟ": "ㅜㅣ", "ㅢ": "ㅡㅣ",
    "ㄳ": "ㄱㅅ", "ㄵ": "ㄴㅈ", "ㄶ": "ㄴㅎ", "ㄺ": "ㄹㄱ", "ㄻ": "ㄹㅁ", "ㄼ": "ㄹㅂ",
    "ㄽ": "ㄹㅅ", "ㄾ": "ㄹㅌ", "ㄿ": "ㄹㅍ", "ㅀ": "ㄹㅎ", "ㅄ": "ㅂㅅ",
}  # fmt: skip

# Unicode syllable composition order (initial, medial, final) as compatibility jamo
_INITIALS = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_MEDIALS = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_FINALS = ["", *"ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"]
_SYLLABLE_BASE, _SYLLABLE_LAST = 0xAC00, 0xD7A3


def is_hangul(text: str) -> bool:
    return bool(text) and all(ch in _JAMO_TO_KEY or ch in _COMPOUND or _is_syllable(ch) for ch in text)


def to_qwerty(text: str) -> str | None:
    """'ㅓㅏ' -> 'jk'; None if `text` contains anything that is not Hangul."""
    keys = []
    for ch in text:
        for jamo in _decompose(ch):
            if jamo not in _JAMO_TO_KEY:
                return None
            keys.append(_JAMO_TO_KEY[jamo])
    return "".join(keys)


def _is_syllable(ch: str) -> bool:
    return _SYLLABLE_BASE <= ord(ch) <= _SYLLABLE_LAST


def _decompose(ch: str) -> str:
    if _is_syllable(ch):
        index = ord(ch) - _SYLLABLE_BASE
        initial, rest = divmod(index, 21 * 28)
        medial, final = divmod(rest, 28)
        jamo = _INITIALS[initial] + _MEDIALS[medial] + _FINALS[final]
        return "".join(_COMPOUND.get(j, j) for j in jamo)
    return _COMPOUND.get(ch, ch)
