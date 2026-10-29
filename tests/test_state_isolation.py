"""STATE is fresh for every test."""



from scry_mame import state as mstate  # noqa: E402


def test_a_test_that_writes_state_without_monkeypatch() -> None:
    mstate.STATE.console_run = True
    mstate.STATE.console_writes = 7
    mstate.STATE.breakpoints[1] = {"owner": ("leaked", ":maincpu"), "addr": 0x400,
                                   "cpu": ":maincpu"}


def test_the_next_test_sees_the_defaults() -> None:
    assert mstate.STATE.console_run is False
    assert mstate.STATE.console_writes == 0
    assert mstate.STATE.breakpoints == {}
