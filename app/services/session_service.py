"""State remembered between runs, stored as state.json next to settings.yaml.

    recent_projects   most recent first; the IDE reopens the first on start
    projects          per folder: open tabs (path, cursor, scroll) and the active tab
    window            QMainWindow geometry and dock layout (base64 of Qt's own blobs)
    vim               registers and histories (vimcore.viminfo)

GUI-independent: Qt blobs come in and go out as bytes.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.settings import default_settings_path

STATE_VERSION = 1
MAX_RECENT_PROJECTS = 10
NO_PROJECT = ""  # key for tabs opened while no folder was open


def default_state_path() -> Path:
    return default_settings_path().with_name("state.json")


@dataclass(frozen=True)
class TabState:
    path: str
    line: int = 0  # 0-based cursor row
    col: int = 0  # 0-based cursor column (characters)
    scroll: int = 0  # first visible line


@dataclass(frozen=True)
class ProjectState:
    tabs: tuple[TabState, ...] = ()
    active: int = -1  # index into tabs

    @property
    def active_path(self) -> str | None:
        return self.tabs[self.active].path if 0 <= self.active < len(self.tabs) else None


@dataclass
class _State:
    recent_projects: list[str] = field(default_factory=list)
    projects: dict[str, ProjectState] = field(default_factory=dict)
    window: dict[str, str] = field(default_factory=dict)
    vim: dict[str, Any] = field(default_factory=dict)


def project_key(root: Path | None) -> str:
    return NO_PROJECT if root is None else os.path.normcase(str(Path(root).resolve()))


class SessionService:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_state_path()
        self._state = self._load()

    # -- recent projects ---------------------------------------------------------------

    def recent_projects(self) -> list[Path]:
        """Most recent first; folders that no longer exist are skipped."""
        return [Path(p) for p in self._state.recent_projects if Path(p).is_dir()]

    def last_project(self) -> Path | None:
        recent = self.recent_projects()
        return recent[0] if recent else None

    def remember_project(self, root: Path) -> None:
        root = Path(root).resolve()
        key = os.path.normcase(str(root))
        others = [p for p in self._state.recent_projects if os.path.normcase(p) != key]
        self._state.recent_projects = [str(root), *others][:MAX_RECENT_PROJECTS]
        self.save()

    # -- per-project tabs ----------------------------------------------------------------

    def project_state(self, root: Path | None) -> ProjectState:
        return self._state.projects.get(project_key(root), ProjectState())

    def set_project_state(self, root: Path | None, state: ProjectState) -> None:
        self._state.projects[project_key(root)] = state

    # -- window layout -------------------------------------------------------------------

    def window_state(self) -> tuple[bytes | None, bytes | None]:
        return _unb64(self._state.window.get("geometry")), _unb64(self._state.window.get("layout"))

    def set_window_state(self, geometry: bytes, layout: bytes) -> None:
        self._state.window = {"geometry": _b64(geometry), "layout": _b64(layout)}

    # -- vim state -----------------------------------------------------------------------

    def vim_state(self) -> dict[str, Any]:
        return self._state.vim

    def set_vim_state(self, data: dict[str, Any]) -> None:
        self._state.vim = data

    # -- persistence -----------------------------------------------------------------------

    def save(self) -> None:
        keep = {project_key(Path(p)) for p in self._state.recent_projects} | {NO_PROJECT}
        projects = {k: v for k, v in self._state.projects.items() if k in keep}  # forget old folders
        data = {
            "version": STATE_VERSION,
            "recent_projects": self._state.recent_projects,
            "projects": {
                k: {"tabs": [asdict(t) for t in v.tabs], "active": v.active} for k, v in projects.items()
            },
            "window": self._state.window,
            "vim": self._state.vim,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass  # losing the session is not worth an error dialog

    def _load(self) -> _State:
        state = _State()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return state  # missing or corrupt: start fresh rather than refuse to launch
        if not isinstance(data, dict):
            return state
        recent = data.get("recent_projects")
        if isinstance(recent, list):
            state.recent_projects = [p for p in recent if isinstance(p, str)]
        projects = data.get("projects")
        if isinstance(projects, dict):
            for key, value in projects.items():
                if isinstance(key, str) and (parsed := _project_state(value)) is not None:
                    state.projects[key] = parsed
        if isinstance(window := data.get("window"), dict):
            state.window = {k: v for k, v in window.items() if isinstance(v, str)}
        if isinstance(vim := data.get("vim"), dict):
            state.vim = vim
        return state


def _project_state(value: Any) -> ProjectState | None:
    if not isinstance(value, dict) or not isinstance(value.get("tabs"), list):
        return None
    tabs = []
    for entry in value["tabs"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            continue
        numbers = [entry.get(name, 0) for name in ("line", "col", "scroll")]
        if all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in numbers):
            tabs.append(TabState(entry["path"], *numbers))
    active = value.get("active", -1)
    return ProjectState(tuple(tabs), active if isinstance(active, int) and not isinstance(active, bool) else -1)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str | None) -> bytes | None:
    if not text:
        return None
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return None
