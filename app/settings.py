"""User-level IDE preferences, stored as a human-editable YAML file.

Ctrl+, opens the file in the editor; saving it applies the changes immediately.
Location: $SVGUARD_CONFIG_DIR/settings.yaml if set, otherwise Qt's AppConfigLocation
(%LOCALAPPDATA%/SV-Guard on Windows, ~/.config/SV-Guard on Linux).
Per-project overrides in .svguard.yaml arrive with Step 6.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

import yaml

DEFAULT_SETTINGS_YAML = """\
# SV-Guard settings. Save this file (Ctrl+S) to apply changes immediately.
editor:
  tab_width: 4                  # columns per indent level and per tab stop (1-16)
  insert_spaces: true           # Tab key inserts spaces (true) or a tab character (false)
  font_family: ""               # empty = first installed of D2Coding, Cascadia Mono, Consolas, ...
  font_size: 11                 # points (6-72)
  auto_indent: true             # Enter keeps the indentation of the current line
  highlight_current_line: true
  show_whitespace: false        # draw dots for spaces and arrows for tabs
vim:
  enabled: true                 # modal editing (Normal/Insert/Visual); false = plain editor
  clipboard_unnamedplus: false  # true: y/d/p use the system clipboard (vim's clipboard=unnamedplus)
session:
  restore_tabs: true            # reopen each folder's tabs, cursor and scroll positions
  restore_vim_state: true       # registers, search and command history (like vim's viminfo)
"""


@dataclass(frozen=True)
class EditorSettings:
    tab_width: int = 4
    insert_spaces: bool = True
    font_family: str = ""
    font_size: int = 11
    auto_indent: bool = True
    highlight_current_line: bool = True
    show_whitespace: bool = False


@dataclass(frozen=True)
class VimSettings:
    enabled: bool = True
    clipboard_unnamedplus: bool = False


@dataclass(frozen=True)
class SessionSettings:
    restore_tabs: bool = True
    restore_vim_state: bool = True


_INT_LIMITS = {"tab_width": (1, 16), "font_size": (6, 72)}


@dataclass(frozen=True)
class Settings:
    editor: EditorSettings = field(default_factory=EditorSettings)
    vim: VimSettings = field(default_factory=VimSettings)
    session: SessionSettings = field(default_factory=SessionSettings)


def default_settings_path() -> Path:
    override = os.environ.get("SVGUARD_CONFIG_DIR")
    if override:
        return Path(override) / "settings.yaml"
    from PySide6.QtCore import QStandardPaths  # keep the parser usable without Qt

    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    return Path(base) / "settings.yaml"


def parse_settings(text: str) -> tuple[Settings, list[str]]:
    """Parse YAML text. Bad or unknown entries fall back to defaults and produce warnings."""
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        return Settings(), [f"settings.yaml is not valid YAML ({exc}); using defaults"]
    if not isinstance(data, dict):
        return Settings(), ["settings.yaml must be a mapping; using defaults"]

    sections = {"editor": EditorSettings(), "vim": VimSettings(), "session": SessionSettings()}
    warnings = [f"unknown setting section '{key}'" for key in data if key not in sections]
    parsed = {}
    for name, defaults in sections.items():
        section_data = data.get(name) or {}
        if not isinstance(section_data, dict):
            warnings.append(f"'{name}' must be a mapping; using defaults")
            section_data = {}
        parsed[name], section_warnings = _parse_section(defaults, section_data, name)
        warnings += section_warnings
    return Settings(**parsed), warnings


def load_settings(path: Path) -> tuple[Settings, list[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Settings(), []
    except OSError as exc:
        return Settings(), [f"cannot read {path}: {exc}"]
    return parse_settings(text)


def ensure_settings_file(path: Path) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_SETTINGS_YAML, encoding="utf-8")
    return path


def _parse_section(defaults: Any, data: dict[str, Any], section: str) -> tuple[Any, list[str]]:
    known = {f.name: f for f in fields(defaults)}
    values: dict[str, Any] = {}
    warnings: list[str] = []
    for key, value in data.items():
        if key not in known:
            warnings.append(f"unknown setting '{section}.{key}'")
            continue
        default = getattr(defaults, key)
        error = _validate(key, value, default)
        if error:
            warnings.append(f"{section}.{key}: {error}, got {value!r}; using {default!r}")
        else:
            values[key] = value
    return replace(defaults, **values), warnings


def _validate(key: str, value: Any, default: Any) -> str | None:
    if isinstance(default, bool):
        return None if isinstance(value, bool) else "expected true/false"
    if isinstance(default, int):
        lo, hi = _INT_LIMITS.get(key, (None, None))
        if isinstance(value, bool) or not isinstance(value, int):
            return "expected an integer"
        if lo is not None and not lo <= value <= hi:
            return f"expected {lo}..{hi}"
        return None
    if isinstance(default, str):
        return None if isinstance(value, str) else "expected a string"
    return None
