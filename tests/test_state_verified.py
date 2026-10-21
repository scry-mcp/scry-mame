"""`state_load`'s `verified`, proved by each cpu's register block as well as the frame and pc.

After a load every readable cpu's block equals the one read at the save, and a load of another
state differs. But a cpu that sits in a short loop with every other register constant can read
the saved block BEFORE the load too, and then equality after it proves nothing: between the two
readings only `stateload` runs. The double keeps a block per thread, which `statesave`
snapshots by name and `stateload` restores unless the test says MAME ignored it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from session_doubles import refused  # noqa: E402
from test_lua import _channel, _ChannelSession  # noqa: E402

import gdb_session as gs  # noqa: E402
import mame_savestates as savestates  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402

_A = {"D0": "00000001", "D1": "00000002", "PC": "00000400"}


class _BlockSession(_ChannelSession):
    """The channel double with a block per thread: `blocks` is the machine, `unread` the threads
    with no register map, `ignores_load` a `stateload` MAME took and did not apply."""

    blocks: dict[int, dict[str, str]]
    unread: set[int]
    garbled: set[int]
    ignores_load: bool
    saved_blocks: dict[str, tuple[int, dict[int, dict[str, str]]]]

    def register_texts(self, *, thread: int) -> dict[str, str]:
        if thread in self.unread:
            raise gs.Refused("E01")
        if thread in self.garbled:
            raise gs.SessionError("the stub answered `g` with 12 hex digits")
        return dict(self.blocks[thread])

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        word, _, name = command.partition(" ")
        if word == "statesave":
            self.saved_blocks[name] = (self.pc, {t: dict(b) for t, b in self.blocks.items()})
        if word == "stateload" and not self.ignores_load:
            self.pc, saved = self.saved_blocks[name]
            self.blocks = {t: dict(b) for t, b in saved.items()}
            # THE LOADED MACHINE WRITES ON BOTH CHANNELS, after the mark the load answers.
            scratch = mstate.STATE.scratch
            if scratch is not None:
                for log in ("error.log", "stdout.log"):
                    with (scratch / log).open("a") as fh:
                        fh.write("after the load\n")
        return str(super().monitor(command, timeout))


def _board(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, threads: dict[int, str],
           frameless: bool = False, kind: type[_BlockSession] = _BlockSession) -> _BlockSession:
    """A board whose stub serves `threads` (empty: the first cpu on thread 1 alone), each with
    the block `_A`."""
    plain = _channel(monkeypatch, tmp_path)
    plain.__class__ = kind
    ses = cast(_BlockSession, plain)
    monkeypatch.setattr(mstate.STATE, "system", "m68k-dual")
    ses.threads = dict(threads)
    ses.stale_after_load = True                          # the frame comes back at a load
    ses.blocks = {tid: dict(_A) for tid in (threads or {1: ""})}
    ses.unread = set()
    ses.garbled = set()
    ses.ignores_load = False
    ses.saved_blocks = {}
    if frameless:
        ses.frameless = True
        monkeypatch.setattr(mstate.STATE, "frame_symbol", None, raising=False)
    return ses


_TWO = {1: ":maincpu", 2: ":subcpu"}


def _moved(ses: _BlockSession, thread: int = 1, register: str = "D0") -> None:
    """The machine ran: one register of one cpu moved, the frame too where there is one."""
    ses.blocks[thread][register] = "0000beef"
    ses.frame += 3


def test_a_load_that_restores_every_block_is_verified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _board(monkeypatch, tmp_path, threads=_TWO)
    assert s.state_save(name="a")["status"] == "ok"
    _moved(ses, 2)
    out = s.state_load(name="a")
    assert out["status"] == "ok" and out["verified"] is True, out
    assert "differs" not in out, out


def test_a_block_the_load_did_not_restore_is_refused_naming_the_register(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The frame and pc came back (the double restores them) and the sub cpu's D1 did not:
    the frame alone would have passed this load."""
    ses = _board(monkeypatch, tmp_path, threads=_TWO)
    s.state_save(name="a")
    _moved(ses, 2, "D1")
    ses.ignores_load = True
    out = refused(":subcpu", s.state_load(name="a"))
    assert out["code"] == "readback_refused", out
    assert out["differs"] == {"cpu": ":subcpu", "register": "D1", "saved": "0x00000002",
                              "loaded": "0x0000beef"}, out


def test_a_board_with_no_counter_is_verified_by_its_blocks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """topgunnr: no frame, and the stub serves its first cpu alone."""
    ses = _board(monkeypatch, tmp_path, threads={}, frameless=True)
    s.state_save(name="a")
    _moved(ses, 1, "PC")
    out = s.state_load(name="a")
    assert out["status"] == "ok" and out["verified"] is True, out


def test_a_board_with_no_counter_refuses_a_load_whose_block_differs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _board(monkeypatch, tmp_path, threads={}, frameless=True)
    s.state_save(name="a")
    _moved(ses, 1, "PC")
    ses.ignores_load = True
    out = refused("PC", s.state_load(name="a"))
    assert out["code"] == "readback_refused" and out["differs"]["register"] == "PC", out


@pytest.mark.parametrize("frameless", [True, False])
def test_a_machine_that_already_read_as_the_save_proves_no_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, frameless: bool,
) -> None:
    """The measured loop: before the load every block (and the frame, where there is one)
    already equals the save, so a load MAME ignored would read the same: null, and why."""
    ses = _board(monkeypatch, tmp_path, threads={}, frameless=frameless)
    s.state_save(name="a")
    ses.ignores_load = True
    out = s.state_load(name="a")
    assert out["status"] == "ok" and out["verified"]["available"] is False, out
    assert "before the load" in out["verified"]["why"], out


def test_a_board_with_no_counter_and_no_register_map_has_nothing_to_judge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _board(monkeypatch, tmp_path, threads={}, frameless=True)
    ses.unread = {1}
    s.state_save(name="a")
    out = s.state_load(name="a")
    assert out["status"] == "ok" and out["verified"]["available"] is False, out
    assert out["verified"]["why"] == savestates.NOTHING_TO_JUDGE, out
    assert "register" in out["verified"]["why"], out


def test_a_cpu_with_no_register_map_is_left_out_and_the_rest_judged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _board(monkeypatch, tmp_path, threads=_TWO, frameless=True)
    ses.unread = {2}
    s.state_save(name="a")
    _moved(ses, 1)
    assert s.state_load(name="a")["verified"] is True


class _NoByteOrder(_BlockSession):
    """A cpu whose byte order is not established: its block is still the stub's digits,
    compared as they came."""

    @property
    def byte_order(self) -> str:
        raise gs.UnknownByteOrder("mips")

    @byte_order.setter
    def byte_order(self, _: Any) -> None:
        return None


def test_a_cpu_whose_byte_order_is_unknown_is_judged_by_its_digits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _board(monkeypatch, tmp_path, threads={}, frameless=True, kind=_NoByteOrder)
    s.state_save(name="a")
    _moved(ses, 1)
    ses.ignores_load = True
    out = refused("D0", s.state_load(name="a"))
    assert out["differs"] == {"cpu": ":maincpu", "register": "D0", "saved": "00000001",
                              "loaded": "0000beef"}, out


def test_a_cpu_whose_block_the_stub_garbles_is_left_out_and_saves_and_loads_go_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A `g` reply that does not cut by the declared widths is that cpu's fault, not the
    session's: the save and the load go on, judged by the other cpus."""
    ses = _board(monkeypatch, tmp_path, threads=_TWO, frameless=True)
    ses.garbled = {2}
    assert s.state_save(name="a")["status"] == "ok"
    _moved(ses, 1)
    out = s.state_load(name="a")
    assert out["status"] == "ok" and out["verified"] is True, out


def test_a_block_unreadable_only_after_the_load_still_records_the_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _board(monkeypatch, tmp_path, threads=_TWO, frameless=True)
    s.state_save(name="a")
    _moved(ses, 1)
    before = mstate.STATE.last_stop.get("seq")
    plain = ses.register_texts

    def late(*, thread: int) -> dict[str, str]:
        if thread == 2 and any(c.startswith("stateload") for c in ses.commands):
            raise gs.SessionError("the stub answered `g` with 12 hex digits")
        return plain(thread=thread)

    ses.register_texts = late  # type: ignore[method-assign]
    out = s.state_load(name="a")
    assert out["status"] == "ok" and out["verified"] is True, out
    assert mstate.STATE.last_stop.get("seq") != before, "the load's stop was recorded"


def test_a_save_that_recorded_no_frame_on_a_board_with_a_counter_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _board(monkeypatch, tmp_path, threads={})
    ses.unread = {1}
    monkeypatch.setattr(savestates, "_frame", lambda _ses: None)
    s.state_save(name="a")
    out = s.state_load(name="a")
    assert out["verified"]["available"] is False, out
    assert "no frame counter" not in out["verified"]["why"], out
    assert "frame" in out["verified"]["why"] and "register" in out["verified"]["why"], out


def test_a_frame_unread_before_the_load_is_not_a_frame_that_moved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An unknown is not a difference: with nothing else moved, the load is not proved."""
    ses = _board(monkeypatch, tmp_path, threads={})
    s.state_save(name="a")
    ses.ignores_load = True
    real = savestates._frame
    calls: list[int] = []

    def frame(ses_: object) -> int | None:
        calls.append(1)
        return None if len(calls) == 1 else real(ses_)  # type: ignore[arg-type]

    monkeypatch.setattr(savestates, "_frame", frame)
    out = s.state_load(name="a")
    assert out["verified"]["available"] is False, out
    assert "before the load" in out["verified"]["why"], out


def test_a_pc_that_moved_within_the_frame_is_enough_to_prove_the_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A step moves the pc and no frame: the frame alone would call the load unproved."""
    ses = _board(monkeypatch, tmp_path, threads={})
    s.state_save(name="a")
    ses.pc += 4
    out = s.state_load(name="a")
    assert out["status"] == "ok" and out["verified"] is True, out


def test_the_second_cpu_alone_moving_is_enough_to_prove_the_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _board(monkeypatch, tmp_path, threads=_TWO, frameless=True)
    s.state_save(name="a")
    ses.blocks[2]["D0"] = "0000beef"
    out = s.state_load(name="a")
    assert out["status"] == "ok" and out["verified"] is True, out


def test_a_register_the_load_left_out_of_a_block_is_said_null(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _board(monkeypatch, tmp_path, threads={}, frameless=True)
    s.state_save(name="a")
    _moved(ses, 1, "PC")
    ses.ignores_load = True
    del ses.blocks[1]["D0"]
    out = refused("D0", s.state_load(name="a"))
    assert out["differs"]["register"] == "D0", out
    assert out["differs"]["loaded"]["available"] is False, out


def test_a_cpu_readable_at_the_save_and_not_after_the_load_is_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The load stays proved by the cpus that were read, and the one that could not be is said,
    never left out in silence."""
    ses = _board(monkeypatch, tmp_path, threads=_TWO, frameless=True)
    s.state_save(name="a")
    _moved(ses, 1)
    plain = ses.register_texts

    def late(*, thread: int) -> dict[str, str]:
        if thread == 2 and any(c.startswith("stateload") for c in ses.commands):
            raise gs.Refused("E01")
        return plain(thread=thread)

    ses.register_texts = late  # type: ignore[method-assign]
    out = s.state_load(name="a")
    assert out["status"] == "ok" and out["verified"] is True, out
    assert ":subcpu" in out.get("note", "") and "not judged" in out["note"], out


def test_a_load_answers_where_each_channel_ended_as_it_was_sent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _board(monkeypatch, tmp_path, threads=_TWO)
    assert s.state_save(name="a")["status"] == "ok"
    _moved(ses, 2)
    scratch = mstate.STATE.scratch
    assert scratch is not None
    (scratch / "error.log").write_bytes(b"before the load\n")   # bytes: a mark is a byte position
    (scratch / "stdout.log").write_bytes(b"boot\nbefore the load\n")
    before = {"emulator": len("before the load\n"), "process": len("boot\nbefore the load\n")}
    out = s.state_load(name="a")
    assert out["status"] == "ok", out
    assert out["mark"] == before, out
    after = s.log(pattern=".", channel="process", since_mark=out["mark"]["process"])
    assert after["lines"] == ["after the load"], after
