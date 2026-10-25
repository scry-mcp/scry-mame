"""Every reply that touches a cpu says which one."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from session_doubles import captured, refused, visible_in, wplist_add  # noqa: E402
from test_server import _console, _ConsoleSession, _running, _RunningSession  # noqa: E402
from test_watches import _watching  # noqa: E402

import gdb_session as gs  # noqa: E402
import mame_cpus as cpus  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402


def _sub_visible(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _RunningSession:
    """The running double with `:subcpu` visible."""
    ses = _running(monkeypatch, tmp_path)
    ses.visible_cpu = ":subcpu"
    return ses


# Each stub call with the packets the double notes for a thread other than the first (a writer's
# read-back among them).
_STUB_CALLS = [
    ("registers", ["g"], lambda **cpu: s.registers(**cpu)),
    ("read_memory", ["m"], lambda **cpu: s.read_memory(ref="0x400", length=4, **cpu)),
    ("write", ["M", "m"], lambda **cpu: s.write(ref="0x200000", data_hex="00", **cpu)),
    ("set_register", ["P", "p"], lambda **cpu: s.set_register(name="d0", value=1, **cpu)),
    ("rom_check", ["rom"], lambda **cpu: s.rom_check(reference_rom=__file__, **cpu)),
]
_IDS = [name for name, _p, _c in _STUB_CALLS]


@pytest.mark.parametrize(("packets", "call"), [c[1:] for c in _STUB_CALLS], ids=_IDS)
def test_without_threads_the_stubs_readers_serve_the_first_cpu_whichever_is_visible(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, packets: list[str], call: Any,
) -> None:
    """Without the thread patch a call answers for `:maincpu`; naming another cpu is refused."""
    ses = _sub_visible(monkeypatch, tmp_path)
    assert call()["cpu"] == ":maincpu"
    assert call(cpu="maincpu")["cpu"] == ":maincpu"
    out = refused(r":subcpu's registers and memory are read through its own thread of the "
                  r"gdbstub's thread patch, and this build's stub serves only :maincpu",
                  call(cpu="subcpu"))
    assert out["message"].endswith(": omit `cpu`, or name :maincpu") and out["cpu_tags"] == [
        ":maincpu"], "the refusal says what the stub can serve"
    assert not [c for c in ses.commands if "@" in c], "no thread but the first was asked"


@pytest.mark.parametrize(("packets", "call"), [c[1:] for c in _STUB_CALLS], ids=_IDS)
def test_on_the_patched_stub_a_call_acts_on_the_visible_cpu_or_the_one_it_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, packets: list[str], call: Any,
) -> None:
    """No `cpu` means the visible one; naming one reaches its thread and moves nothing.

    The control is the main cpu, whose thread 1 the double notes nothing for."""
    ses = _sub_visible(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    assert call()["cpu"] == ":subcpu", ses.commands
    assert [c for c in ses.commands if "@" in c] == [f"{p}@2" for p in packets], ses.commands
    ses.commands.clear()
    assert call(cpu="maincpu")["cpu"] == ":maincpu"
    assert not [c for c in ses.commands if "@" in c], ses.commands
    assert ses.visible_cpu == ":subcpu", "naming a cpu moved nothing"
    refused(r"no cpu 'nosuch' on this machine", call(cpu="nosuch"))


def test_a_cpus_registers_are_printed_at_the_widths_its_own_description_declares(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`registers` prints the visible cpu's own widths, never the first cpu's."""
    ses = _sub_visible(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    narrow = SimpleNamespace(register_bits={"D0": 16, "PC": 16}, byte_order="big")
    monkeypatch.setattr(ses, "layout", lambda thread: narrow if thread == 2 else ses)
    out = s.registers()
    assert out["register_bits"] == {"D0": 16, "PC": 16} and out["regs"]["D0"] == "0x1234", out
    assert s.registers(cpu="maincpu")["regs"]["D0"] == "0x00001234"


_NARROW = dataclasses.replace(gs.Layout.parse(
    '<target><architecture>i8086</architecture><feature name="org.gnu.gdb.i386.core">'
    '<reg name="d0" bitsize="16" type="int"/><reg name="pc" bitsize="16" type="code_ptr"/>'
    '</feature></target>'), mame_order="little")
_MIPS = dataclasses.replace(_NARROW, arch="mips", mame_order="")


def test_a_register_is_forced_within_the_width_its_own_cpu_declares(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`set_register` judges the width against the named cpu's description."""
    ses = _sub_visible(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    monkeypatch.setattr(ses, "layout", lambda thread: _NARROW if thread == 2 else ses)
    refused(r"D0 is 16 bits on this cpu", s.set_register(name="d0", value=0x10000, cpu="subcpu"))
    assert s.set_register(name="d0", value=0x10000, cpu="maincpu")["verified"] is True


@pytest.mark.parametrize("why", ["no_map", "unknown_order"])
def test_a_cpu_the_stub_does_not_describe_is_no_channel_for_its_registers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, why: str,
) -> None:
    """A cpu with no register map or no established byte order is refused, not raised."""
    ses = _sub_visible(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}

    def layout(thread: int) -> Any:
        if thread == 1:
            return ses
        if why == "no_map":
            raise gs.Refused("the stub refused `qXfer:features:read:target.xml:0,400`: E01")
        return _MIPS

    monkeypatch.setattr(ses, "layout", layout)
    for out in (s.registers(), s.set_register(name="d0", value=1, cpu="subcpu")):
        assert refused(r":subcpu's registers cannot be read here", out)["code"] == "no_channel"
    assert s.registers(cpu="maincpu")["cpu"] == ":maincpu", "the described cpu still reads"


def test_a_rom_check_mismatch_names_the_cpu_it_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A mismatch names the cpu read, so it does not read as a session that lies."""
    ses = _sub_visible(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}

    def lies(*_a: Any, **_k: Any) -> None:
        raise gs.Mismatch("the session LIES: at 0x400 it returns 00 and the ROM holds 01")

    monkeypatch.setattr(ses, "self_check", lies)
    out = s.rom_check(reference_rom=__file__)
    assert out["status"] == "INVALID" and out["code"] == "readback_refused", out
    assert out["message"].startswith("read on :subcpu: the session LIES") and \
        out["cpu"] == ":subcpu", out
    assert getattr(ses, "broken", None) is None, "a verdict about the machine latches nothing"


def test_without_threads_a_first_cpu_the_console_does_not_name_is_said_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _sub_visible(monkeypatch, tmp_path)
    monkeypatch.setattr(cpus, "stub_cpu", lambda _ses: None)
    out = refused(r"serves only its first cpu, which `cpulist` does not name",
                  s.registers(cpu="subcpu"))
    assert out["cpu_tags"] == [] and "name None" not in out["message"], out
    assert out["message"].endswith(": omit `cpu`"), out["message"]


def test_a_visible_cpu_the_stub_names_no_thread_for_is_refused_naming_the_served_ones(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A visible cpu with no thread is refused naming the served ones, never read elsewhere."""
    ses = _sub_visible(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu"}
    out = refused(r"the stub names no thread for :subcpu", s.read_memory(ref="0x400", length=4))
    assert out["code"] == "bad_argument" and not [c for c in ses.commands if "@" in c]
    assert out["cpu_tags"] == [":maincpu"] and "name one of [':maincpu'] as `cpu`" in out["message"]


def test_on_the_patched_stub_a_dump_with_no_visible_cpu_is_refused_before_save(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _sub_visible(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    monkeypatch.setattr(cpus, "visible_cpu", lambda _ses: None)
    out = refused(r"`cpulist` marked no cpu visible",
                  s.memdump(ref="0x400", length=16, dest=str(tmp_path / "none.bin")))
    assert out["code"] == "unexpected_answer" and not any(c.startswith("save") for c in
                                                          ses.commands)


def test_on_the_patched_stub_a_visible_cpu_nobody_marks_is_refused_not_guessed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A `cpulist` marking no cpu refuses a call naming none; naming the cpu still answers."""
    ses = _sub_visible(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    monkeypatch.setattr(cpus, "visible_cpu", lambda _ses: None)
    out = refused(r"`cpulist` marked no cpu visible", s.registers())
    assert out["code"] == "unexpected_answer"
    assert s.registers(cpu="subcpu")["cpu"] == ":subcpu"


def test_the_last_stops_registers_take_no_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A `cpu` beside `from_last_stop` is a request nothing honours, so it is refused."""
    _sub_visible(monkeypatch, tmp_path)
    refused(r"`from_last_stop` hands back", s.registers(from_last_stop=True, cpu="subcpu"))
    assert s.registers(from_last_stop=True)["superseded"] is True


def test_the_consoles_readers_name_the_visible_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The console readers act on the visible cpu."""
    ses = _ConsoleSession(bytes(0x1000), replies={
        "find": captured("find.none.txt"), "history": captured("history.txt"),
        "cpulist": captured("cpulist.sub-visible.txt")})
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    scratch = _console(monkeypatch, tmp_path, ses)

    def dasm(command: str) -> str:
        (scratch / command[len("dasm "):].split(",")[0]).write_text(captured("dasm.txt"))
        return captured("dasm.reply.txt")

    def save(command: str) -> str:
        path, start, length = command[len("save "):].split(",")
        Path(path).write_bytes(bytes(int(length, 16)))
        return "Data saved successfully\n"

    ses.replies.update(dasm=dasm, save=save)
    for out in (s.disassemble(ref="0x0", length=16), s.find(ref="0x0", length=0x10,
                                                            data_hex="dead"),
                s.history(limit=8),
                s.memdump(ref="0x0", length=0x10, dest=str(tmp_path / "d.bin"))):
        assert out["status"] == "ok" and out["cpu"] == ":subcpu", out


def test_a_stop_on_the_sub_cpu_surveys_the_sub_cpus_registers_through_its_thread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The survey reads the stopping cpu's registers through its thread, and the record keeps it."""
    ses = _running(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    s.resume()
    ses.visible_cpu = ":subcpu"
    ses.commands.clear()
    stop = s.stop()
    assert stop["interrupted"] and stop["cpu"] == ":subcpu" and "regs_cpu" not in stop, stop
    assert "g@2" in ses.commands and stop["regs"]["D0"] == "0x00001234", (ses.commands, stop)
    last = s.registers(from_last_stop=True)
    assert (last["cpu"], last["regs"], last["register_bits"]["D0"]) == (":subcpu", stop["regs"], 32)
    assert s.stop()["last_stop"]["cpu"] == ":subcpu", "the record names the stop's cpu"
    s.resume()
    refused(r"last seen stopped at pc \S+ on :subcpu", s.registers())
    s.stop()
    s.resume()
    ses.visible_cpu = ":maincpu"
    ses.commands.clear()
    stop = s.stop()
    assert stop["cpu"] == ":maincpu" and "g@2" not in ses.commands, (ses.commands, stop)
    s.resume()
    ses.visible_cpu, ses.stops_after_polls = ":subcpu", 1
    found = s.declaration_list("breakpoint")["stopped_on_its_own"]
    assert found["cpu"] == ":subcpu", found


@pytest.mark.parametrize("why", ["no_thread_patch", "no_map"])
def test_a_stop_on_a_cpu_this_build_cannot_read_says_so_in_place_of_its_registers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, why: str,
) -> None:
    """An unreadable stopping cpu still surveys: `regs` says why, never the first cpu's file."""
    ses = _running(monkeypatch, tmp_path)
    if why == "no_map":
        ses.threads = {1: ":maincpu", 2: ":subcpu"}

        def layout(thread: int) -> Any:
            if thread == 1:
                return ses
            raise gs.Refused("the stub refused `qXfer:features:read:target.xml:0,400`: E01")

        monkeypatch.setattr(ses, "layout", layout)
    s.resume()
    ses.visible_cpu = ":subcpu"
    stop = s.stop()
    assert stop["status"] == "ok" and stop["cpu"] == ":subcpu", stop
    assert stop["regs"]["available"] is False, stop
    assert ("thread patch" if why == "no_thread_patch" else "cannot be read here") in (
        stop["regs"]["why"]), stop["regs"]
    last = s.registers(from_last_stop=True)
    assert last["regs"] == stop["regs"] and last["register_bits"] == {}, last
    assert last["summary"].startswith("registers: none read, from the last stop: "), last


def test_status_names_every_cpu_and_cpu_info_the_visible_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    assert s.status()["cpu_tags"] == [":maincpu", ":subcpu"]
    assert visible_in(s.cpu_info()) == ":maincpu"
    ses.visible_cpu = ":subcpu"
    assert visible_in(s.cpu_info()) == ":subcpu", "read at every call, never remembered"


def test_the_arming_replies_and_their_lists_carry_the_rows_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    assert s.breakpoint_at(ref="0x4a0")["cpu"] == ":maincpu"
    assert s.breakpoint_at(ref="0x25a4", role="control")["cpu"] == ":maincpu"
    assert {b["cpu"] for b in s.declaration_list("breakpoint")["breakpoints"]} == {":maincpu"}
    assert s.watch_add(ref="FRAME_LO", mode="change", length=4, fmt="u32")["cpu"] == ":maincpu"
    (w,) = s.declaration_list("watch")["watches"]
    assert w["cpu"] == ":maincpu"
    ses.wp_devices = {2: ":subcpu"}  # type: ignore[attr-defined]
    wplist_add(ses, 0x8000, 2)
    assert s.declaration_list("watch")["foreign"] == {"watches": ["2 @ 008000-008001 write"]}


def test_status_on_a_broken_session_asks_no_cpu_and_one_that_breaks_under_it_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A broken session is asked nothing; a `cpulist` timeout latches it and the reply says so."""
    ses = _running(monkeypatch, tmp_path)
    s.status()
    ses.broken = "the stub stopped answering"
    ses.commands.clear()
    out = s.status()
    assert out["cpu_tags"] == [":maincpu", ":subcpu"], out
    assert "cpulist" not in ses.commands
    monkeypatch.setattr(mstate.STATE, "cpus", [])
    ses.broken = None
    real = ses.monitor

    def times_out(command: str, timeout: float = 10.0) -> str:
        if command == "cpulist":
            ses.broken = "`cpulist` got no answer"
            raise gs.Timeout(ses.broken)
        return str(real(command, timeout))

    monkeypatch.setattr(ses, "monitor", times_out)
    out = s.status()
    assert out["broken"] == "`cpulist` got no answer" and out["cpu_tags"] == [], out
