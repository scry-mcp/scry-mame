"""A server whose client went away abruptly ends the machine: SIGTERM, SIGHUP or Ctrl-C reach a
`SignalledEnd`, whose default would otherwise skip the `finally` that kills MAME."""

from __future__ import annotations

import signal
from typing import Any

import pytest
from scry_core import signalled_end

from scry_mame import server  # noqa: E402
from scry_mame import state as st  # noqa: E402


def _killed(kills: list[bool]) -> dict[str, Any]:
    kills.append(True)
    return {}


@pytest.fixture
def handlers() -> Any:
    saved = {s: signal.getsignal(s) for s in signalled_end.EXIT_SIGNALS}
    yield
    for s, handler in saved.items():
        signal.signal(s, handler if handler is not None else signal.SIG_DFL)


def test_main_answers_the_signals_and_ends_the_machine_on_its_way_out(
        monkeypatch: pytest.MonkeyPatch, handlers: None) -> None:
    installed: list[Any] = []
    kills: list[bool] = []
    monkeypatch.setattr(server.mcp, "run", lambda: installed.extend(
        signal.getsignal(s) for s in signalled_end.EXIT_SIGNALS))
    monkeypatch.setattr(st.STATE, "kill", lambda *a, **k: _killed(kills))
    server.main()
    assert installed and all(h == server.END.on_signal for h in installed), installed
    assert kills == [True]


def test_a_signalled_end_kills_the_machine_and_leaves(monkeypatch: pytest.MonkeyPatch) -> None:
    kills: list[bool] = []
    left: list[int] = []
    monkeypatch.setattr(st.STATE, "kill", lambda *a, **k: _killed(kills))
    monkeypatch.setattr(server.END, "leave", left.append)
    server.END.end(128 + signal.SIGTERM)
    assert kills == [True] and left == [128 + signal.SIGTERM]
