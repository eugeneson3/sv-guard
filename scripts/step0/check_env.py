"""Step 0: print versions of every dependency and fail loudly if one is missing."""

from __future__ import annotations

import importlib.metadata as md
import platform
import sys

REQUIRED = ["pyslang", "PySide6", "PyYAML", "pytest", "pytest-qt"]
MIN_PYTHON = (3, 11)  # pyslang 12 wheels require >= 3.11


def main() -> int:
    ok = True
    print(f"python   {platform.python_version()}  ({sys.executable})")
    print(f"platform {platform.platform()}")
    if sys.version_info < MIN_PYTHON:
        print(f"  !! python >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]} required")
        ok = False

    for name in REQUIRED:
        try:
            meta = md.metadata(name)
            print(f"{name:10} {meta['Version']:10} requires-python {meta.get('Requires-Python')}")
        except md.PackageNotFoundError:
            print(f"{name:10} MISSING")
            ok = False

    # Import smoke test: catches broken native wheels, not just missing metadata.
    try:
        import pyslang  # noqa: F401
        from PySide6 import QtCore

        print(f"Qt runtime {QtCore.qVersion()}")
    except Exception as exc:  # pragma: no cover - diagnostic script
        print(f"import failed: {exc!r}")
        ok = False

    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
