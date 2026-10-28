import sys
from pathlib import Path

import pytest
from scry_core import host_args

sys.path.insert(0, str(Path(__file__).resolve().parent))

from session_doubles import blank_session, checked_rearms  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    blank_session(monkeypatch)
    checked_rearms(monkeypatch)
    # keeps a failed start's output out of the developer's real state dir
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.delenv(host_args.VARIABLE, raising=False)
    monkeypatch.delenv("MAME_BINARY", raising=False)
