"""Entry point: `python -m app [PATH]` or `svguard-ide [PATH]`.

PATH may be a project folder or a file (its folder becomes the project).
Without PATH the last folder comes back with its tabs, cursors and window layout.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow

APP_NAME = "SV-Guard"
ICON_PATH = Path(__file__).parent / "resources" / "svguard.png"


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    parser = argparse.ArgumentParser(prog="svguard-ide")
    parser.add_argument("path", nargs="?", type=Path, help="project folder or file to open")
    args, qt_args = parser.parse_known_args(argv[1:])

    app = QApplication([argv[0], *qt_args])
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(ICON_PATH)))

    window = MainWindow()
    window.restore_layout()
    window.show()
    window.restore_workspace(args.path)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
