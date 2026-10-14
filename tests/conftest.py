"""Every test starts on a blank `STATE` (`blank_session` says why), with no test having to ask,
and every re-arm account it drives is checked row by row (`checked_rearms`)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from session_doubles import blank_session, checked_rearms  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    blank_session(monkeypatch)
    checked_rearms(monkeypatch)
    # THE STATE DIRECTORY IS THE TEST'S OWN, so nothing a case provokes (a failed start's
    # kept output, a persistent store) lands in the owner's real one.
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
