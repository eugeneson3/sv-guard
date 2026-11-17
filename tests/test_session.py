"""SessionService and vimcore.viminfo: persistence without Qt."""

import json
from pathlib import Path

from app.services.session_service import NO_PROJECT, ProjectState, SessionService, TabState, project_key
from vimcore import RegisterValue
from vimcore.engine import SharedState
from vimcore import viminfo


def test_project_state_round_trip(tmp_path: Path):
    path = tmp_path / "state.json"
    root = tmp_path / "proj"
    root.mkdir()
    session = SessionService(path)
    session.remember_project(root)
    state = ProjectState((TabState(str(root / "a.sv"), 3, 4, 10), TabState(str(root / "b.sv"))), active=1)
    session.set_project_state(root, state)
    session.save()

    reloaded = SessionService(path)
    assert reloaded.project_state(root) == state
    assert reloaded.project_state(root).active_path == str(root / "b.sv")


def test_unknown_project_has_an_empty_state(tmp_path: Path):
    assert SessionService(tmp_path / "state.json").project_state(tmp_path) == ProjectState()


def test_window_blobs_round_trip(tmp_path: Path):
    session = SessionService(tmp_path / "state.json")
    session.set_window_state(b"\x01\x02geometry", b"\x00layout")
    session.save()
    assert SessionService(tmp_path / "state.json").window_state() == (b"\x01\x02geometry", b"\x00layout")


def test_folders_dropped_from_recent_are_forgotten(tmp_path: Path):
    session = SessionService(tmp_path / "state.json")
    roots = []
    for i in range(12):  # more than MAX_RECENT_PROJECTS
        root = tmp_path / f"p{i}"
        root.mkdir()
        roots.append(root)
        session.remember_project(root)
        session.set_project_state(root, ProjectState((TabState(str(root / "x.sv")),), 0))
    session.set_project_state(None, ProjectState((TabState("loose.sv"),), 0))
    session.save()
    data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert project_key(roots[0]) not in data["projects"]  # oldest folder fell off the recent list
    assert project_key(roots[-1]) in data["projects"]
    assert NO_PROJECT in data["projects"]  # tabs opened without a folder are kept


def test_malformed_state_is_tolerated(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "recent_projects": ["ok", 3],
                "projects": {"k": {"tabs": [{"path": "a.sv", "line": -1}, {"path": "b.sv", "line": 2}, "junk"], "active": True}},
                "window": {"geometry": "%%%not base64%%%"},
                "vim": "nope",
            }
        ),
        encoding="utf-8",
    )
    session = SessionService(path)
    assert session.project_state(None) == ProjectState()
    assert session._state.projects["k"] == ProjectState((TabState("b.sv", 2),), -1)
    assert session.window_state() == (None, None)


def test_viminfo_round_trip():
    source = SharedState()
    source.registers.put("a", RegisterValue("line a", linewise=True), yank=True)
    source.registers.put(None, RegisterValue("word"), yank=True)
    source.history[":"] += ["w", "set ts=2"]
    source.history["/"].append("always_ff")
    source.last_search, source.search_forward = "always_ff", False

    target = SharedState()
    viminfo.load(target, json.loads(json.dumps(viminfo.dump(source))))
    assert target.registers.get("a") == RegisterValue("line a", linewise=True)
    assert target.registers.get(None) == RegisterValue("word")
    assert target.registers.get("0") == RegisterValue("word")
    assert target.history == {":": ["w", "set ts=2"], "/": ["always_ff"]}
    assert (target.last_search, target.search_forward) == ("always_ff", False)


def test_viminfo_skips_huge_registers_and_garbage():
    source = SharedState()
    source.registers.put("b", RegisterValue("x" * (viminfo.MAX_REGISTER_CHARS + 1)), yank=True)
    assert "b" not in viminfo.dump(source)["registers"]

    target = SharedState()
    viminfo.load(target, {"registers": {"a": {"text": 3}, "+": {"text": "clip"}}, "history": {":": [1, "ok"]}})
    assert target.registers.get("a") is None
    assert target.registers.snapshot() == {}  # "+" (clipboard) is never restored
    assert target.history[":"] == ["ok"]
    viminfo.load(target, "not a dict")
