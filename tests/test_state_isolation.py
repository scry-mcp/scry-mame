"""The suite's `STATE` is fresh for every test, whatever the test before it left behind.

A PAIR, and the order is the point: the first case writes to `STATE` the way a careless test
would, with no `monkeypatch` to undo it, and the second asserts the defaults. Without the
fixture in `conftest.py` the second goes red, which is the leak made visible on demand rather
than by whichever file happened to run first.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mame_state as mstate  # noqa: E402


def test_a_test_that_writes_state_without_monkeypatch() -> None:
    mstate.STATE.console_run = True
    mstate.STATE.console_writes = 7
    # In place, not rebound: a restore that only put the old OBJECT back would keep this row.
    mstate.STATE.breakpoints[1] = {"owner": ("leaked", ":maincpu"), "addr": 0x400,
                                   "cpu": ":maincpu"}


def test_the_next_test_sees_the_defaults() -> None:
    assert mstate.STATE.console_run is False
    assert mstate.STATE.console_writes == 0
    assert mstate.STATE.breakpoints == {}
