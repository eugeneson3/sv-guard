"""Cross-platform task runner. The Makefile delegates here because Windows has no `make` by default.

    python tasks.py install            setup + shortcut (what setup.bat runs on a fresh clone)
    python tasks.py setup              create .venv and install sv-guard with gui+dev extras
    python tasks.py test [pytest args] run the test suite
    python tasks.py check [paths]      run `svguard check` (default: examples/basic)
    python tasks.py run [path]         start the IDE (optionally on a project folder or file)
    python tasks.py shortcut           add SV-Guard to the desktop and Start menu / app launcher
    python tasks.py clean              remove caches and build outputs
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENV_PY = VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
# gui-scripts launcher from pyproject.toml: starts without a console window on Windows
IDE_EXE = VENV / ("Scripts/svguard-ide.exe" if sys.platform == "win32" else "bin/svguard-ide")
ICON = ROOT / "app" / "resources"
# Deepest file PySide6 6.11 installs, measured from the project root (\.venv\Lib\...\*.cpp.obj).
# Windows stops at 259 characters unless long paths are enabled, and pip then fails halfway
# through PySide6 with a bare OSError, so a project path longer than ROOT_MAX is refused up front.
VENV_DEPTH = 176
ROOT_MAX = 259 - VENV_DEPTH


def _run(*args: object) -> int:
    return subprocess.call([str(a) for a in args], cwd=ROOT)


def _python() -> Path:
    if not VENV_PY.exists():
        sys.exit("No .venv found. Run: python tasks.py setup")
    return VENV_PY


def install(args: list[str]) -> int:
    return setup(args) or shortcut([])


def setup(args: list[str]) -> int:
    if sys.platform == "win32" and len(str(ROOT)) > ROOT_MAX and not _long_paths_enabled():
        sys.exit(
            f"The project path is {len(str(ROOT))} characters long: {ROOT}\n"
            f"PySide6 needs it to be {ROOT_MAX} or less unless Windows long paths are enabled.\n"
            r"Clone to a shorter path such as C:\dev\easySV and run setup again."
        )
    if not VENV_PY.exists():
        # The venv inherits this interpreter, and pyslang 12 has no wheels before 3.11
        if sys.version_info < (3, 11):
            sys.exit(f"Python 3.11+ is required, this is {sys.version.split()[0]}: {sys.executable}")
        print(f"creating {VENV}")
        venv.create(VENV, with_pip=True)
    return _run(VENV_PY, "-m", "pip", "install", "-e", ".[gui,dev]", *args)


def _long_paths_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
    except OSError:
        return False


def test(args: list[str]) -> int:
    return _run(_python(), "-m", "pytest", *args)


def check(args: list[str]) -> int:
    return _run(_python(), "-m", "svguard", "check", *(args or ["examples/basic"]))


def run(args: list[str]) -> int:
    return _run(_python(), "-m", "app", *args)


def shortcut(args: list[str]) -> int:
    """Shortcuts point at the venv launcher, so they always run the current source tree."""
    if not IDE_EXE.exists():
        sys.exit("No IDE launcher found. Run: python tasks.py setup")
    if sys.platform == "win32":
        return _windows_shortcuts()
    return _linux_desktop_entry()


def _windows_shortcuts() -> int:
    script = f"""
$shell = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {{
    $link = $shell.CreateShortcut((Join-Path $dir 'SV-Guard.lnk'))
    $link.TargetPath = '{IDE_EXE}'
    $link.WorkingDirectory = '{ROOT}'
    $link.IconLocation = '{ICON / "svguard.ico"},0'
    $link.Description = 'SV-Guard: SystemVerilog/UVM learning IDE'
    $link.Save()
    Write-Output "created $($link.FullName)"
}}
"""
    return subprocess.call(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])


def _linux_desktop_entry() -> int:
    apps = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    entry = apps / "sv-guard.desktop"
    entry.write_text(
        "[Desktop Entry]\nType=Application\nName=SV-Guard\n"
        "Comment=SystemVerilog/UVM learning IDE\n"
        f"Exec={IDE_EXE} %f\nPath={ROOT}\nIcon={ICON / 'svguard.png'}\n"
        "Terminal=false\nCategories=Development;IDE;\n",
        encoding="utf-8",
    )
    print(f"created {entry}")
    return 0


def clean(args: list[str]) -> int:
    for pattern in ("**/__pycache__", ".pytest_cache", "*.egg-info", "build", "dist"):
        for path in ROOT.glob(pattern):
            if ".venv" not in path.relative_to(ROOT).parts:
                shutil.rmtree(path, ignore_errors=True)
    return 0


TASKS = {
    "install": install, "setup": setup, "test": test, "check": check,
    "run": run, "shortcut": shortcut, "clean": clean,
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in TASKS:
        print(__doc__)
        return 2
    return TASKS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    raise SystemExit(main())
