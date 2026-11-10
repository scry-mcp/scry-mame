import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from scry_core import names_written
from scry_core import window as core_window

from scry_mame.state import STATE

sys.path.insert(0, str(Path(__file__).resolve().parent))

from session_doubles import blank_session, checked_rearms  # noqa: E402
from window_double import obeying  # noqa: E402

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
    monkeypatch.setattr(core_window, "host", lambda _platform="": obeying())
    monkeypatch.delenv("MAME_BINARY", raising=False)


#: The MAME double a test hands `start` as its binary, kept beside the server's files.
NAMES = names_written.Names(fixed={"fake-mame"})


@pytest.fixture(autouse=True)
def names_judged(request: pytest.FixtureRequest, fresh_state: None,
                 tmp_path: Path) -> Iterator[None]:
    """Every file a test leaves in the server's directories is named by the rule."""
    yield
    if request.node.path.is_relative_to(LIVE):
        return
    bad = NAMES.outside([STATE.scratch, STATE.state_dir, tmp_path / "xdg-state"])
    if bad:
        pytest.fail("written outside the rule of file names:\n  " + "\n  ".join(map(str, bad)))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if NAMES.judged_nothing(session.config):
        print("\nINVALID: no test left a file in a server's directories, so no name was judged")
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
