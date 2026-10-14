"""What a pass run with `disarm_watches=True` reports about the watches it took off
(`watches.place_after_pass`): each one re-armed is placed as `watch_list` places it, and a
pointer watch the survey already followed to a new place is armed there once.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_pointer_watches import ENGINE, HEAP2, _pointing  # noqa: E402
from test_watches import _watching, _WatchSession  # noqa: E402

import gdb_session as gs  # noqa: E402
import mame_advance as advance  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_watches as watches  # noqa: E402
import server as s  # noqa: E402


def _to_target(monkeypatch: pytest.MonkeyPatch, ses: _WatchSession) -> None:
    """The next `run_to(ref="0x4a0", control="0x25a4")` reaches its target with the control hot."""
    monkeypatch.setattr(advance, "RUN_POLL_S", 0.0)
    ses.pcs = [0xF2034, 0x4A0]
    ses.stop_queue = [1]
    real_go = ses.go

    def go() -> None:
        real_go()
        ses.temps[0] = 1

    ses.go = go  # type: ignore[method-assign]


def _listing_nothing(ses: _WatchSession) -> None:
    """The stub takes every `wp` and lists no row for it; a removal still goes."""
    real = ses.watchpoint

    def listing_nothing(addr: int, length: int, remove: bool = False, cpu: str | None = None,
                        index: int | None = None, cond: str = "") -> None:
        if remove:
            real(addr, length, remove, cpu, index, cond)

    ses.watchpoint = listing_nothing  # type: ignore[method-assign]


def _row(out: dict[str, Any], ref: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = [w for w in out["watches"] if w["ref"] == ref]
    (row,) = rows
    return row


def test_a_pass_reports_a_watch_it_re_armed_as_armed_with_its_new_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    _to_target(monkeypatch, ses)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0, disarm_watches=True)
    assert out["verdict"] == "TARGET", out
    armed = mstate.STATE.armed_watches[("frame_lo", ":maincpu")]
    row = _row(out, "frame_lo")
    assert row["state"] == "armed" and row["entry"] == armed["entry"], row
    assert row["entry"].startswith("2 @ "), "the row the debugger numbered afresh"
    listed = _row(s.watch_list(), "frame_lo")
    assert (listed["state"], listed["entry"]) == (row["state"], row["entry"])
    assert "not_rearmed" not in out


def test_a_run_without_the_flag_reports_the_row_it_never_took_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    _to_target(monkeypatch, ses)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    row = _row(out, "frame_lo")
    assert row["state"] == "armed" and row["entry"].startswith("1 @ "), row
    assert "disarmed_watches" not in out


def test_a_watch_the_re_arm_lost_stays_gone_and_is_named_not_rearmed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    _to_target(monkeypatch, ses)
    _listing_nothing(ses)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0, disarm_watches=True)
    assert out["not_rearmed"] == [{"ref": "frame_lo", "cpu": ":maincpu"}], out
    assert _row(out, "frame_lo")["state"] == "gone", out


POINTER = "_g_engine->sync_delta"


def test_a_pointer_watch_that_moved_during_the_pass_is_armed_once_at_its_new_place(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The survey follows the pointer and arms the new place during the pass: the re-arm
    takes that row as its own, and the debugger holds one row there, owned."""
    ses = _pointing(monkeypatch, tmp_path)
    s.watch_add(ref=POINTER, mode="change")
    ses.memory[ENGINE] = HEAP2.to_bytes(4, "big")         # the pointer moves
    _to_target(monkeypatch, ses)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0, disarm_watches=True)
    assert out["status"] == "ok", out
    at_new = [r for r in ses.wplist_rows if f"{HEAP2 + 4:06X}" in r]
    assert len(at_new) == 1 and len(ses.wplist_rows) == 1, ses.wplist_rows
    row = _row(out, POINTER)
    assert row["state"] == "armed" and row["addr"] == f"{HEAP2 + 4:#010x}", row
    assert s.watch_list()["foreign"] == [], "a row nothing owns"
    assert "not_rearmed" not in out


def test_a_pointer_watch_whose_follow_lost_both_rows_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A follow that lost both places drops the record: the ref is named `not_rearmed`, its
    row stays `gone`, and the pass answers."""
    ses = _pointing(monkeypatch, tmp_path)
    s.watch_add(ref=POINTER, mode="change")
    ses.memory[ENGINE] = HEAP2.to_bytes(4, "big")
    _to_target(monkeypatch, ses)
    _listing_nothing(ses)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0, disarm_watches=True)
    assert out["status"] == "ok", out
    assert out["not_rearmed"] == [{"ref": POINTER, "cpu": ":maincpu"}], out
    assert _row(out, POINTER)["state"] == "gone", out
    assert ses.broken is None


def test_a_pointer_watch_gone_null_keeps_its_null_pointer_row_after_the_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _pointing(monkeypatch, tmp_path)
    s.watch_add(ref=POINTER, mode="change")
    ses.memory[ENGINE] = bytes(4)                           # the pointer went null
    _to_target(monkeypatch, ses)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0, disarm_watches=True)
    row = _row(out, POINTER)
    assert row["state"] == "null_pointer" and row["why"], row
    assert _row(s.watch_list(), POINTER)["state"] == "null_pointer"


def test_a_list_that_breaks_the_session_after_the_re_arm_is_in_the_reply_s_session_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The rows are placed against one more `wplist`, read after the run built its block: a
    read that latches the session there is newer than that block."""
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    _to_target(monkeypatch, ses)
    real = watches.rearm_after_pass

    def rearm_then_break(ses_: Any, refs: list[Any]) -> list[Any]:
        rearmed = real(ses_, refs)

        def latching(command: str, timeout: float = 10.0) -> str:
            ses.broken = "the stub stopped answering"
            raise gs.SessionError("no answer to `wplist`")

        ses.monitor = latching  # type: ignore[method-assign]
        return rearmed

    monkeypatch.setattr(watches, "rearm_after_pass", rearm_then_break)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0, disarm_watches=True)
    assert out["session"].get("broken") == "the stub stopped answering", out["session"]


def test_the_rows_of_every_watch_re_armed_are_placed_against_one_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Two watches cost the pass as many `wplist` reads as one: the list read after the re-arm
    places every row."""
    asked: dict[int, int] = {}
    for n, refs in ((1, ["frame_lo"]), (2, ["frame_lo", "0x203200"])):
        (tmp_path / str(n)).mkdir()
        ses = _watching(monkeypatch, tmp_path / str(n))
        for ref in refs:
            s.watch_add(ref=ref, mode="change", length=2 if ref == "0x203200" else 4)
        _to_target(monkeypatch, ses)
        ses.commands.clear()
        out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0, disarm_watches=True)
        assert [_row(out, r)["state"] for r in refs] == ["armed"] * n, out["watches"]
        asked[n] = ses.commands.count("wplist")
    assert asked[1] == asked[2], asked
