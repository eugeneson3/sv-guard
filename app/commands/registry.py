"""Every IDE feature is a named command, so the palette, the menus, keymap.yaml
mappings and ex commands (:file.find) all reach it the same way."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

Handler = Callable[[int | None], object]  # receives the count typed before a mapping (3gt)


@dataclass(frozen=True)
class AppCommand:
    id: str  # "file.find"
    title: str  # "Go to File..." (shown in menus and the palette)
    handler: Handler
    category: str = ""
    shortcuts: tuple[str, ...] = ()  # Qt key sequences, e.g. ("Ctrl+P",)
    planned_step: str | None = None  # set for features that arrive in a later step

    @property
    def label(self) -> str:
        return f"{self.category}: {self.title}" if self.category else self.title


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, AppCommand] = {}

    def add(self, command: AppCommand) -> AppCommand:
        if command.id in self._commands:
            raise ValueError(f"duplicate command id: {command.id}")
        self._commands[command.id] = command
        return command

    def get(self, command_id: str) -> AppCommand | None:
        return self._commands.get(command_id)

    def __contains__(self, command_id: object) -> bool:
        return command_id in self._commands

    def __iter__(self) -> Iterator[AppCommand]:
        return iter(sorted(self._commands.values(), key=lambda c: c.label.lower()))

    def ids(self) -> frozenset[str]:
        return frozenset(self._commands)

    def run(self, command_id: str, count: int | None = None) -> bool:
        command = self._commands.get(command_id)
        if command is None:
            return False
        command.handler(count)
        return True
