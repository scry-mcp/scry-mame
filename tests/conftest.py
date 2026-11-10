import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from scry_core import file_names
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


#: Names another program fixes, found where a test keeps it beside the server's files: the MAME
#: double a test hands `start` as its binary.
FOREIGN = frozenset({"fake-mame"})
_judged = [0]
_ran = [0]


@pytest.fixture(autouse=True)
def names_written(request: pytest.FixtureRequest, fresh_state: None,
                  tmp_path: Path) -> Iterator[None]:
    """Every file a test leaves in the scratch, the state directory and the state home is named
    by `scry_core.file_names`'s rule, or the test fails naming it."""
    yield
    if request.node.path.is_relative_to(LIVE):
        return
    _ran[0] += 1
    folders = {Path(f) for f in (STATE.scratch, STATE.state_dir, tmp_path / "xdg-state") if f}
    bad: list[str] = []
    for folder in sorted(folders):
        if not folder.is_dir() or not any(p.is_file() for p in folder.rglob("*")):
            continue
        _judged[0] += sum(1 for p in folder.rglob("*") if p.is_file())
        bad += [str(p) for p in file_names.outside(folder) if p.name not in FOREIGN]
    if bad:
        pytest.fail("written outside the rule of file names:\n  " + "\n  ".join(bad))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    narrowed = config.option.keyword or config.args != config.getini("testpaths")
    if _ran[0] and not _judged[0] and not narrowed:
        print("\nINVALID: no test left a file in a server's directories, so no name was judged")
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
