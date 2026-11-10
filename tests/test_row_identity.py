"""A debugger row is known by its index; one address can hold several rows."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from server_support import _running, _RunningSession  # noqa: E402
from session_doubles import (  # noqa: E402
    IDENTITY_KEYS,
    SessionFields,
    bplist_add,
    captured,
    refs,
    wplist_add,
)
from test_expr_watches import _first_stop_through, _foreign_breakpoint_on_the_vblank  # noqa: E402
from test_watches import _watching  # noqa: E402

from scry_mame import (
    advance,  # noqa: E402
    arming,  # noqa: E402
    cpus,  # noqa: E402
)
from scry_mame import declarations as dec  # noqa: E402
from scry_mame import gdb_session as gs  # noqa: E402
from scry_mame import rearm as rearming  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402


def test_a_row_typed_at_a_controls_address_is_foreign_and_ends_run_for(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A row typed at a control's address ends `run_for` as OTHER_STOP."""
    chunk = _first_stop_through("3D").replace("breakpoint 1", "breakpoint 2")
    reg = _foreign_breakpoint_on_the_vblank(monkeypatch, tmp_path, chunk, [])
    assert s.breakpoint_at(ref="0x4a0", role="control")["entry"] == "1 @ 0004A0 if (++temp0)==0"
    bplist_add(reg, 0x4A0)
    landed = reg.current_pc
    reg.current_pc = lambda: 0x4A0 if landed() == 0x400 else 0x100  # type: ignore[method-assign]
    out = s.run_for(frames=5, seconds=2.0)
    assert out["status"] == "ok" and out["verdict"] == "OTHER_STOP", out
    assert out["cause"] == ("breakpoint 2 at 0x000004a0, typed through `debug`: "
                          "`debug(\"bpclear 0x2\")` removes it"), out["cause"]
    assert s.declaration_list("breakpoint")["foreign"] == {"breakpoints": ["2 @ 0004A0"]}


def _sub_row_at_400(ses: _RunningSession) -> None:
    """Row 1 at 0x400 under the sub cpu, while the main cpu is visible."""
    ses.bp_devices = {1: ":subcpu"}
    bplist_add(ses, 0x400)


def test_a_row_under_the_other_cpu_is_not_adopted_by_a_declaration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A row at the same address under the other cpu stays foreign."""
    ses = _running(monkeypatch, tmp_path)
    _sub_row_at_400(ses)
    out = s.breakpoint_at(ref="0x400")
    assert out["entry"] == "2 @ 000400", out
    assert s.declaration_list("breakpoint")["foreign"] == {"breakpoints": ["1 @ 000400"]}
    assert [r["owner"] for r in mstate.STATE.breakpoints.values()] == [("0x400", ":maincpu")]
    assert list(mstate.STATE.breakpoints) == [2]


def test_starts_rearm_does_not_adopt_a_row_under_the_other_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The `start` re-arm does not adopt the sub cpu's row."""
    ses = _running(monkeypatch, tmp_path)
    _sub_row_at_400(ses)
    arming.store().add(dec.Declaration("breakpoint", "address", "0x400", origin="s0",
                                       fingerprint="fp-test"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["0x400"], out
    assert list(mstate.STATE.breakpoints) == [2], mstate.STATE.breakpoints


def test_breakpoint_clear_removes_its_own_row_by_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The clear removes its own row by index."""
    ses = _running(monkeypatch, tmp_path)
    _sub_row_at_400(ses)
    s.breakpoint_at(ref="0x400")
    out = s.declaration_clear("breakpoint", ref="0x400")
    assert out["disarmed"] == ["2 @ 000400"], out
    assert "bpclear 0x2" in ses.commands
    assert ses.bplist_rows == ["    1 @ 000400"], "the sub cpu's row is left where it was"
    assert mstate.STATE.breakpoints == {}


def test_a_typed_watch_row_on_an_armed_range_is_foreign(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A watchpoint typed over an armed watch's range is a second, foreign row."""
    ses = _watching(monkeypatch, tmp_path)
    assert s.watch_add(ref="FRAME_LO", mode="change", length=4, fmt="u32")["status"] == "ok"
    wplist_add(ses, 0x2031FC, 4)
    assert s.declaration_list("watch")["foreign"] == {"watches": ["2 @ 2031FC-2031FF write"]}


@pytest.mark.parametrize(("answer", "visible"), [
    (captured("cpulist-main-visible.txt"), ":maincpu"),
    (captured("cpulist-sub-visible.txt"), ":subcpu"),
    ("Unknown command\n\n", None),
], ids=["main", "sub", "no-cpulist"])
def test_the_visible_cpu_is_the_one_cpulist_marks(answer: str, visible: str | None) -> None:
    """`cpulist` marks the visible cpu; none marked means unknown."""
    class Console(SessionFields):
        def monitor(self, command: str, timeout: float = 10.0) -> str:
            assert command == "cpulist"
            return answer

    assert cpus.visible_cpu(Console()) == visible  # type: ignore[arg-type]


def test_with_no_cpulist_the_address_alone_decides_what_a_declaration_adopts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """With no visible cpu, a declaration adopts an unowned row."""
    ses = _running(monkeypatch, tmp_path)
    _sub_row_at_400(ses)
    real = ses.monitor
    lacks = captured("rpset-unknown-command.txt").replace("rpzzzset {1}", "cpulist")
    monkeypatch.setattr(ses, "monitor", lambda command, timeout=10.0: (
        lacks if command == "cpulist" else real(command, timeout)))
    assert s.breakpoint_at(ref="0x400")["entry"] == "1 @ 000400"
    assert list(mstate.STATE.breakpoints) == [1]


def test_a_console_that_fails_under_cpulist_leaves_the_cpu_unknown() -> None:
    """A console that raises under `cpulist` leaves the cpu unknown."""
    class Failing:
        def monitor(self, command: str, timeout: float = 10.0) -> str:
            raise gs.ConnectionFailed("the stub closed the connection")

    assert cpus.visible_cpu(Failing()) is None  # type: ignore[arg-type]
    assert cpus.cpu_list(Failing()) == []  # type: ignore[arg-type]


def test_a_watch_declared_again_on_its_cpu_after_a_stop_on_the_other_keeps_its_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Re-declaring a watch finds its existing row."""
    ses = _watching(monkeypatch, tmp_path)
    assert s.watch_add(ref="FRAME_LO", mode="change", length=4, fmt="u32")["index"] == 1
    ses.visible_cpu = ":subcpu"
    again = s.watch_add(ref="FRAME_LO", mode="change", length=4, fmt="u32", cpu="maincpu")
    assert again["index"] == 1 and len(ses.wplist_rows) == 1, (again, ses.wplist_rows)
    assert "foreign" not in s.declaration_list("watch")


def test_a_watch_re_armed_after_a_pass_takes_only_a_row_under_its_own_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A row reappearing under another cpu is not adopted."""
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="FRAME_LO", mode="change", length=4, fmt="u32")
    ses.wp_devices = {2: ":subcpu"}  # type: ignore[attr-defined]
    out = advance._with_watches_disarmed(ses, True, lambda: {"verdict": "ELAPSED"})  # type: ignore[arg-type]
    armed = mstate.STATE.armed_watches[("FRAME_LO", ":maincpu")]
    assert armed["enabled"] is False, armed
    assert out["not_rearmed"] == [{"ref": "FRAME_LO", "cpu": ":maincpu"}], out


def test_starts_rearm_tells_the_sessions_own_row_from_an_inherited_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Re-armed rows read `inherited` by origin."""
    ses = _running(monkeypatch, tmp_path)
    own = mstate.STATE.session_origin
    arming.store().add(dec.Declaration("breakpoint", "address", "0x400", origin=own,
                                       created_at="2026-01-01T00:00:00+00:00",
                                       fingerprint="fp-test"))
    arming.store().add(dec.Declaration("breakpoint", "address", "0x4a0", origin="s0",
                                       created_at="2025-06-01T00:00:00+00:00",
                                       fingerprint="fp-test"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    held = {d.ref: d for d in arming.store().declarations()}
    assert [r["inherited"] for r in out["rearmed"]] == [False, True], out
    for row in out["rearmed"]:
        assert {k: row[k] for k in IDENTITY_KEYS} == arming.decl_row(held[row["ref"]]), row
