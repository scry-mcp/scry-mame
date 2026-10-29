"""`while_running` is the machine state at call arrival; a mid-call stop is `last_stop`'s."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from server_support import _running  # noqa: E402

from scry_mame import (
    arming,  # noqa: E402
    regpoints,  # noqa: E402
    tally,  # noqa: E402
)
from scry_mame import clear as mclear  # noqa: E402
from scry_mame import lists as mlists  # noqa: E402
from scry_mame import read as mread  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402
from scry_mame import tap as mtap  # noqa: E402


def _stops_after(monkeypatch: pytest.MonkeyPatch, ses: Any, module: Any, name: str) -> None:
    """`module.name` answers, then the stop it let through clears `running`."""
    plain: Callable[..., Any] = getattr(module, name)

    def reading(*a: Any, **k: Any) -> Any:
        out = plain(*a, **k)
        ses.running = False
        return out

    monkeypatch.setattr(module, name, reading)


@pytest.mark.parametrize(("module", "name", "call"), [
    (regpoints, "rp_held", lambda: s.regpoint_add(condition="d1==7fff")),
    (regpoints, "rp_held", lambda: s.declaration_clear("regpoint", ref="d1==7fff")),
    (mlists, "bp_held", lambda: s.declaration_clear("breakpoint", ref="0x4a0")),
    (mtap, "send_remove", lambda: s.declaration_clear("watch", ref="0x6", space="io")),
    (mclear, "clearing", lambda: s.declaration_clear("watch", ref="0x4a8")),
    (arming, "resolve_decl", lambda: s.watch_add(ref="0x4ac", mode="show", length=2)),
    (arming, "resolve_decl", lambda: s.breakpoint_at(ref="0x4a4")),
    (mread, "print_values", lambda: s.watch_add(ref="curpc", mode="expr")),
])
def test_while_running_is_the_machine_the_call_arrived_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, module: Any, name: str,
    call: Callable[[], dict[str, Any]],
) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.regpoint_add(condition="d1==7fff")
    s.breakpoint_at(ref="0x4a0")
    assert s.watch_add(ref="0x4a8", mode="show", length=2)["status"] == "ok"
    monkeypatch.setitem(mstate.STATE.tallies, ("0x6@io", ":maincpu"), {
        "tally_id": "6_1@io", "registry": tally.REGISTRY, "files": [], "last_total": 0,
        "space": "io", "last_seq": 0})
    monkeypatch.setattr(mtap, "send_remove", lambda _scratch, owner: {
        "tally_id": "6_1@io", "removal": "pending", "lines_ahead": 0, "call": "x"})
    ses.go()
    assert ses.running is True
    _stops_after(monkeypatch, ses, module, name)
    out = call()
    assert out["status"] == "ok", out
    assert out["while_running"] is True, out
    assert ses.running is False, "the flip happened inside the call"
