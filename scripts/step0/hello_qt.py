"""Step 0: minimal PySide6 window.

Usage:
    python scripts/step0/hello_qt.py              # opens a window, Esc or Ctrl+Q closes it
    python scripts/step0/hello_qt.py --smoke 500  # auto-quit after 500 ms (CI / headless check)
"""

from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import Qt, QTimer, qVersion
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMainWindow, QPlainTextEdit


class HelloWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"SV-Guard Step 0 - Qt {qVersion()}")
        self.resize(800, 500)

        editor = QPlainTextEdit(self)
        editor.setFont(QFont("Monospace", 11))
        editor.setPlainText("module hello;\nendmodule\n\n// Esc or Ctrl+Q to quit\n")
        self.setCentralWidget(editor)
        self.statusBar().showMessage("NORMAL")

        # Keyboard-only exit, matching the project's no-mouse requirement.
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", type=int, metavar="MS", help="quit automatically after MS milliseconds")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    win = HelloWindow()
    win.show()
    if args.smoke:
        QTimer.singleShot(args.smoke, app.quit)
    rc = app.exec()
    print(f"Qt event loop exited with {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
