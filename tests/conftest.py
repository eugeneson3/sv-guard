from __future__ import annotations

import os
from pathlib import Path

import pytest

# GUI tests run headless; must be set before pytest-qt creates the QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _isolated_config_dir(tmp_path_factory, monkeypatch):
    """Never touch the real user settings.yaml from tests."""
    monkeypatch.setenv("SVGUARD_CONFIG_DIR", str(tmp_path_factory.mktemp("config")))


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def uvm_library():
    """A real UVM library (e.g. from a local Vivado install); skips the test if none is found."""
    from svguard.uvm import find_uvm

    lib = find_uvm()
    if lib is None:
        pytest.skip("no UVM library installed (Vivado or UVM_HOME)")
    return lib
