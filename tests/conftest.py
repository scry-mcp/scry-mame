import sys
from pathlib import Path

import pytest
from scry_core import window as core_window

sys.path.insert(0, str(Path(__file__).resolve().parent))

from session_doubles import blank_session, checked_rearms  # noqa: E402
from window_double import ObeyingHost  # noqa: E402

LIVE = Path(__file__).resolve().parent / "live"


@pytest.fixture(autouse=True)
def fresh_state(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
                tmp_path: Path) -> None:
    if request.node.path.is_relative_to(LIVE):
        return
    blank_session(monkeypatch)
    checked_rearms(monkeypatch)
    # keeps a failed start's output out of the developer's real state dir
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.setattr(core_window, "host", lambda _platform="": ObeyingHost())
    monkeypatch.delenv("MAME_BINARY", raising=False)
