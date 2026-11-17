from concurrent.futures import ThreadPoolExecutor

import pytest

from app.editor.editor_tabs import EditorTabs
from app.services.analysis_service import AnalysisService


@pytest.fixture(autouse=True)
def _no_modal_close_prompt(monkeypatch):
    """A modal "Save changes?" box during teardown would hang the run forever.
    Tests that care about the answer set `tabs.ask_close` themselves."""
    monkeypatch.setattr(EditorTabs, "_ask_close_dialog", lambda self, path: "discard")


@pytest.fixture(autouse=True)
def _thread_analysis_worker(monkeypatch):
    """Spawning a checker process per window would make every GUI test slow; a thread runs
    the same svguard.runner.analyze. One test exercises the real process pool."""
    monkeypatch.setattr(AnalysisService, "default_executor_factory", staticmethod(lambda: ThreadPoolExecutor(max_workers=1)))
