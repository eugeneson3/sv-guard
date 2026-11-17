"""keymap.yaml: leader key, timeout and key-sequence mappings.

config/keymap.default.yaml ships the defaults; the user's keymap.yaml (next to
settings.yaml) is merged on top. Editors get the mappings through vimcore.Mappings;
panels (file tree, ...) get leader / <C-w> / <C-^> sequences through PanelKeyDispatcher.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import QEvent, QObject, QTimer, Signal
from PySide6.QtGui import QKeyEvent

from app.editor.vim_adapter import vim_key
from app.settings import default_settings_path
from vimcore.keyparser import format_keys, parse_keys
from vimcore.mapping import KeyTrie, MapCommand, Mappings, MapKeys, MapTarget, expand_lhs

DEFAULT_KEYMAP_PATH = Path(__file__).resolve().parents[2] / "config" / "keymap.default.yaml"
SECTIONS = ("normal", "visual", "panel")
_PANEL_PREFIXES = ("<leader>", "<c-w>", "<c-^>")

USER_KEYMAP_TEMPLATE = """\
# Your key mappings, merged over config/keymap.default.yaml. Save to apply.
# Targets: a command id (Ctrl+Shift+P lists them) or {keys: "..."}; null removes a default.
#
# leader: ","
# timeoutlen: 800
normal:
  # "<leader>q": app.quit
  # "H": {keys: "^"}
"""


def default_user_keymap_path() -> Path:
    return default_settings_path().with_name("keymap.yaml")


@dataclass
class Keymap:
    leader: str = "<Space>"
    timeoutlen: int = 1000
    sections: dict[str, dict[str, MapTarget]] = field(default_factory=lambda: {s: {} for s in SECTIONS})

    def mappings(self) -> Mappings:
        return Mappings(self._trie("normal"), self._trie("visual"), self.timeoutlen)

    def panel_trie(self) -> KeyTrie:
        trie = KeyTrie()
        for lhs, target in self.sections["normal"].items():
            if lhs.lower().startswith(_PANEL_PREFIXES) and isinstance(target, MapCommand):
                trie.add(expand_lhs(lhs, self.leader), target)
        for lhs, target in self.sections["panel"].items():
            trie.add(expand_lhs(lhs, self.leader), target)
        return trie

    def bindings_for(self, command_id: str) -> list[str]:
        """How to type a command, for the palette: ['<Space>f', ...]."""
        found = []
        for section in ("normal", "panel"):
            for lhs, target in self.sections[section].items():
                if isinstance(target, MapCommand) and target.command == command_id:
                    keys = format_keys(expand_lhs(lhs, self.leader))
                    if keys not in found:
                        found.append(keys)
        return found

    def command_ids(self) -> set[str]:
        return {t.command for s in self.sections.values() for t in s.values() if isinstance(t, MapCommand)}

    def _trie(self, section: str) -> KeyTrie:
        trie = KeyTrie()
        for lhs, target in self.sections[section].items():
            trie.add(expand_lhs(lhs, self.leader), target)
        return trie


def load_keymap(user_path: Path | None = None, default_path: Path = DEFAULT_KEYMAP_PATH) -> tuple[Keymap, list[str]]:
    """Defaults merged with the user's file. Problems become warnings, never exceptions."""
    keymap, warnings = Keymap(), []
    for path, required in ((default_path, True), (user_path, False)):
        if path is None or (not required and not path.exists()):
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            warnings.append(f"{path.name}: cannot read ({exc}); ignored")
            continue
        if not isinstance(data, dict):
            warnings.append(f"{path.name}: must be a mapping; ignored")
            continue
        _merge(keymap, data, path.name, warnings)
    return keymap, warnings


def _merge(keymap: Keymap, data: dict[str, Any], source: str, warnings: list[str]) -> None:
    for key, value in data.items():
        if key == "leader":
            if isinstance(value, str) and value:
                keymap.leader = value
            else:
                warnings.append(f"{source}: leader must be a key like '<Space>' or ','")
        elif key == "timeoutlen":
            if isinstance(value, int) and not isinstance(value, bool) and 50 <= value <= 10_000:
                keymap.timeoutlen = value
            else:
                warnings.append(f"{source}: timeoutlen must be 50..10000 (ms)")
        elif key in SECTIONS:
            if not isinstance(value, dict):
                warnings.append(f"{source}: '{key}' must be a mapping")
                continue
            section = keymap.sections[key]
            for lhs, target in value.items():
                lhs = str(lhs)
                if target is None:
                    section.pop(lhs, None)
                elif (parsed := _target(target)) is None:
                    warnings.append(f"{source}: {key}.{lhs}: target must be a command id or {{keys: ...}}")
                else:
                    section[lhs] = parsed
        else:
            warnings.append(f"{source}: unknown key '{key}'")


def _target(value: Any) -> MapTarget | None:
    if isinstance(value, str) and value:
        return MapCommand(value)
    if isinstance(value, dict) and set(value) == {"keys"} and isinstance(value["keys"], str):
        return MapKeys(tuple(parse_keys(value["keys"])))
    return None


class PanelKeyDispatcher(QObject):
    """Event filter that gives panels the global sequences (<Space>f, <C-w>l, ...).

    Keys that start no mapping pass through to the panel untouched."""

    command = Signal(str)

    def __init__(self, trie: KeyTrie, timeoutlen: int, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._trie = trie
        self._pending: list[str] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(timeoutlen)
        self._timer.timeout.connect(self._on_timeout)

    def configure(self, trie: KeyTrie, timeoutlen: int) -> None:
        self._trie = trie
        self._timer.setInterval(timeoutlen)
        self._pending.clear()

    @property
    def pending(self) -> str:
        return format_keys(self._pending)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.KeyPress:
            return False
        assert isinstance(event, QKeyEvent)
        key = vim_key(event.key(), event.text(), event.modifiers())
        return key is not None and self.feed(key)

    def feed(self, key: str) -> bool:
        """True if the key was consumed by a mapping (or is waiting for one)."""
        self._timer.stop()
        keys = [*self._pending, key]
        target, longer = self._trie.lookup(keys)
        if longer:
            self._pending = keys
            self._timer.start()
            return True
        if target is not None:
            self._pending = []
            self._emit(target)
            return True
        if self._pending:  # the earlier keys went nowhere; try this key on its own
            self._pending = []
            return self.feed(key)
        return False

    def _on_timeout(self) -> None:
        target, _longer = self._trie.lookup(self._pending)
        self._pending = []
        if target is not None:
            self._emit(target)

    def _emit(self, target: MapTarget) -> None:
        if isinstance(target, MapCommand):
            self.command.emit(target.command)
