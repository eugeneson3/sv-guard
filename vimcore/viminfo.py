"""Persist what vim keeps in its viminfo/shada file: registers, command-line and search
history, the last search. Plain JSON-able dicts; the host decides where they are stored."""

from __future__ import annotations

from typing import Any

from vimcore.engine import SharedState
from vimcore.registers import RegisterValue

MAX_REGISTER_CHARS = 50_000  # skip huge yanks rather than bloat the state file
MAX_HISTORY = 50


def dump(shared: SharedState) -> dict[str, Any]:
    registers = {
        name: {"text": value.text, "linewise": value.linewise}
        for name, value in shared.registers.snapshot().items()
        if len(value.text) <= MAX_REGISTER_CHARS
    }
    return {
        "registers": registers,
        "history": {kind: entries[-MAX_HISTORY:] for kind, entries in shared.history.items()},
        "last_search": shared.last_search,
        "search_forward": shared.search_forward,
    }


def load(shared: SharedState, data: Any) -> None:
    """Merge saved state into `shared`; anything malformed is skipped."""
    if not isinstance(data, dict):
        return
    registers = data.get("registers")
    if isinstance(registers, dict):
        values = {
            name: RegisterValue(entry["text"], bool(entry.get("linewise")))
            for name, entry in registers.items()
            if isinstance(name, str) and isinstance(entry, dict) and isinstance(entry.get("text"), str)
        }
        shared.registers.restore(values)
    history = data.get("history")
    if isinstance(history, dict):
        for kind in shared.history:
            entries = history.get(kind)
            if isinstance(entries, list):
                shared.history[kind] = [e for e in entries if isinstance(e, str)][-MAX_HISTORY:]
    if isinstance(data.get("last_search"), str):
        shared.last_search = data["last_search"]
        shared.search_forward = data.get("search_forward") is not False
