"""Vim options changed with :set (a small subset)."""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass
class VimOptions:
    tabstop: int = 4
    shiftwidth: int = 0  # 0 = use tabstop
    expandtab: bool = True
    autoindent: bool = True
    ignorecase: bool = False
    smartcase: bool = False
    wrapscan: bool = True
    scroll: int = 0  # lines for <C-d>/<C-u>; 0 = half of `page`
    page: int = 30  # visible lines, kept up to date by the host

    @property
    def sw(self) -> int:
        return self.shiftwidth or self.tabstop

    @property
    def scroll_lines(self) -> int:
        return self.scroll or max(1, self.page // 2)


ALIASES = {
    "ts": "tabstop",
    "sw": "shiftwidth",
    "et": "expandtab",
    "ai": "autoindent",
    "ic": "ignorecase",
    "scs": "smartcase",
    "ws": "wrapscan",
    "scr": "scroll",
}
_LIMITS = {"tabstop": (1, 32), "shiftwidth": (0, 32), "scroll": (0, 1000)}
_SETTABLE = {f.name for f in fields(VimOptions)} - {"page"}


def set_option(options: VimOptions, arg: str) -> str | None:
    """Apply one :set argument (`ts=2`, `et`, `noet`, `et!`, `invet`, `ts?`).

    Returns a message to show (a queried value) or raises ValueError with a vim-style error.
    """
    name, value, query = arg, None, False
    if "=" in arg:
        name, value = arg.split("=", 1)
    elif arg.endswith("?"):
        name, query = arg[:-1], True
    toggle = name.endswith("!")
    name = name.rstrip("!")
    negate = invert = False
    full = ALIASES.get(name, name)
    if full not in _SETTABLE:
        if name.startswith("no"):
            negate, full = True, ALIASES.get(name[2:], name[2:])
        elif name.startswith("inv"):
            invert, full = True, ALIASES.get(name[3:], name[3:])
    if full not in _SETTABLE:
        raise ValueError(f"E518: Unknown option: {arg}")

    current = getattr(options, full)
    if isinstance(current, bool):
        if value is not None:
            raise ValueError(f"E474: Invalid argument: {arg}")
        if query:
            return f"  {'' if current else 'no'}{full}"
        setattr(options, full, not current if (toggle or invert) else not negate)
        return None

    if negate or invert or toggle:
        raise ValueError(f"E474: Invalid argument: {arg}")
    if value is None or query:
        return f"  {full}={current}"
    try:
        number = int(value)
    except ValueError:
        raise ValueError(f"E521: Number required after =: {arg}") from None
    lo, hi = _LIMITS.get(full, (0, 10_000))
    if not lo <= number <= hi:
        raise ValueError(f"E474: Invalid argument: {arg}")
    setattr(options, full, number)
    return None
