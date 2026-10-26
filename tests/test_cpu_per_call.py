"""`cpu` per call: a row armed on the cpu the call names, and the visible cpu left where it was."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scry_core import value_format as vf  # noqa: E402
from server_support import _running  # noqa: E402
from session_doubles import captured, refused, use_table, visible_in  # noqa: E402
from test_watches import STOP_LINE, _watching  # noqa: E402

import gdb_session as gs  # noqa: E402
import mame_arming as arming  # noqa: E402
import mame_cpus as cpus  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_tally as tally  # noqa: E402
import mame_transport as transport  # noqa: E402
import mame_watches as watches  # noqa: E402
import server as s  # noqa: E402


def test_a_breakpoint_named_on_the_sub_cpu_lands_there_and_moves_no_visible_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    out = s.breakpoint_at(ref="0x542", cpu="subcpu")
    assert out["status"] == "ok" and out["cpu"] == ":subcpu", out
    assert "bp 0x542::subcpu" in ses.commands
    assert "note" not in out, "the declaration keeps its cpu: the next `start` re-arms it there"
    listed = s.declaration_list("breakpoint")["breakpoints"]
    assert [(b["ref"], b["cpu"], b["state"]) for b in listed] == [("0x542", ":subcpu", "armed")]
    assert visible_in(s.cpu_info()) == ":maincpu"
    assert not any(c.startswith(("Hc", "focus")) for c in ses.commands), "nothing moved it"
    control = s.breakpoint_at(ref="0x25a4", role="control", cpu=":subcpu")
    assert control["cpu"] == ":subcpu" and "bp 0x25a4::subcpu,(++temp0)==0" in ses.commands


def test_with_no_cpu_named_a_row_lands_on_the_visible_cpu_and_says_nothing_of_a_rearm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.visible_cpu = ":subcpu"
    out = s.breakpoint_at(ref="0x542")
    assert out["cpu"] == ":subcpu" and "note" not in out, out
    assert "bp 0x542::subcpu" in ses.commands


def test_a_cpu_the_machine_lacks_is_unknown_ref_naming_its_cpus_before_anything_is_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    out = refused(r"no cpu 'audiocpu' on this machine", s.breakpoint_at(ref="0x542",
                                                                        cpu="audiocpu"))
    assert out["code"] == "unknown_ref" and out["cpu_tags"] == [":maincpu", ":subcpu"]
    assert not any(c.startswith("bp ") for c in ses.commands)
    assert arming.store().declarations() == [], "nothing stored"
    refused(r"no cpu 'audiocpu'", s.watch_add(ref="0x2031fc", mode="change", length=4,
                                               cpu="audiocpu"))


def test_the_same_ref_declared_after_a_stop_elsewhere_is_a_second_declaration_there(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The same ref on two cpus is two declarations; naming the first cpu again adopts its row."""
    ses = _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x542")
    ses.visible_cpu = ":subcpu"
    again = s.breakpoint_at(ref="0x542")
    assert again["cpu"] == ":subcpu" and not again.get("already_stored"), again
    assert len(ses.bplist_rows) == 2
    same = s.breakpoint_at(ref="0x542", cpu="maincpu")
    assert same["cpu"] == ":maincpu" and same["already_stored"], same
    assert len(ses.bplist_rows) == 2, "no third row"
    listed = s.declaration_list("breakpoint")["breakpoints"]
    assert [(b["ref"], b["cpu"]) for b in listed] == [("0x542", ":maincpu"), ("0x542", ":subcpu")]


def test_run_to_arms_its_target_on_the_visible_cpu_and_removes_it_by_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x4A0]
    ses.stops_after_polls = 1
    real_go = ses.go

    def go() -> None:
        real_go()
        ses.temps[0] = 1

    ses.go = go  # type: ignore[method-assign]
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["verdict"] == "TARGET", out
    assert "bp 0x4a0::maincpu" in ses.commands and "bpclear 0x2" in ses.commands, ses.commands
    assert ses.bplist_rows == ["    1 @ 0025A4 if (++temp0)==0"], "the control stays"


def test_a_change_watch_named_on_the_sub_cpu_arms_maps_and_reads_through_that_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The write side is asked of that cpu's `map`, and its bytes are read through its thread."""
    ses = _watching(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    out = s.watch_add(ref="0x2031fc", mode="change", length=4, cpu="subcpu")
    assert out["status"] == "ok" and out["cpu"] == ":subcpu", out
    assert "map 0x2031fc::subcpu" in ses.commands and "wp 0x2031fc::subcpu,0x4,w" in ses.commands
    assert "m@2" in ses.commands, "the reading came through the sub cpu's thread"
    assert [w["cpu"] for w in s.declaration_list("watch")["watches"]] == [":subcpu"]
    assert s.declaration_clear("watch", ref="0x2031fc")["disarmed"] == ["1 @ 2031FC-2031FF write"]
    assert "wpclear 0x1" in ses.commands and ses.wplist_rows == []


def test_without_threads_another_cpus_watch_is_armed_and_its_bytes_are_unreadable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A stub without threads arms the row anyway, and the reading says why it has no value."""
    _watching(monkeypatch, tmp_path)
    out = s.watch_add(ref="0x2031fc", mode="change", length=4, cpu="subcpu")
    assert out["cpu"] == ":subcpu" and out["reading"]["available"] is False, out
    assert "reads only :maincpu" in out["reading"]["why"], out["reading"]


def test_a_watch_armed_on_the_sub_cpu_is_re_armed_there_after_a_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="0x2031fc", mode="change", length=4, cpu="subcpu")
    refs = watches.disarm_for_pass(ses)  # type: ignore[arg-type]
    owner = ("0x2031fc", ":subcpu")
    assert refs == [owner] and "wpclear 0x1" in ses.commands and ses.wplist_rows == []
    assert watches.rearm_after_pass(ses, refs) == [owner]  # type: ignore[arg-type]
    assert ses.commands.count("wp 0x2031fc::subcpu,0x4,w") == 2
    assert mstate.STATE.armed_watches[owner]["cpu"] == ":subcpu"


def test_an_expr_watch_refuses_a_cpu_other_than_the_visible_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The console evaluates an expression on the visible cpu, so an expr watch has no cpu."""
    ses = _watching(monkeypatch, tmp_path)
    out = refused("by the console, on the visible cpu",
                  s.watch_add(ref="beamy", mode="expr", cpu="subcpu"))
    assert out["code"] == "bad_argument" and arming.store().declarations() == []
    assert not any(c.startswith("wp ") for c in ses.commands)
    assert "`focus(cpu=...)` makes the one you name the visible one" in out["message"] and (
        'mode="change"' not in out["message"]), (
        "a change watch takes a symbol, not an expression: it is no remedy for one")


def test_a_read_watch_named_on_another_cpu_is_that_cpus_and_read_through_its_thread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The declaration keeps its cpu, so every stop reads it through that cpu's thread."""
    ses = _watching(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    out = s.watch_add(ref="0x2031fc", mode="show", length=4, cpu="subcpu")
    assert out["status"] == "ok" and out["cpu"] == ":subcpu", out
    assert "m@2" in ses.commands, "read through the sub cpu's thread"
    assert [(w["ref"], w["cpu"]) for w in s.declaration_list("watch")["watches"]] == [("0x2031fc",
                                                                                       ":subcpu")]
    main = s.watch_add(ref="0x2031fc", mode="show", length=4, cpu="maincpu")
    assert main["status"] == "ok" and not main.get("already_stored"), main


def test_a_count_watch_binds_its_tap_to_the_cpu_named_when_it_is_composed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The install waits in the pipe, so an unnamed cpu is taken at run time, not at compose."""
    named = tally.install_script("2031fc_4", 0x2031FC, 4, tmp_path / "t.txt", ":subcpu")
    assert 'local cpu = manager.machine.devices[":subcpu"]' in named
    unnamed = tally.install_script("2031fc_4", 0x2031FC, 4, tmp_path / "t.txt")
    assert "dbg.visible_cpu" in unnamed and ":subcpu" not in unnamed


def test_a_watch_stop_is_named_by_the_consoles_line_under_a_packet_that_names_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The console line's index names the row under a packet that names no address."""
    ses = _watching(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    s.watch_add(ref="0x2031fc", mode="change", length=4, cpu="subcpu")
    s.resume()
    (tmp_path / "debug.log").open("a").write(STOP_LINE)
    ses.next_packet = "T05watch:0;"
    ses.stops_after_polls = 1
    how = s.status()["stopped_on_its_own"]["cause"]
    assert how.startswith("watch 0x2031fc: 0x002031fc written by pc"), how


def test_a_watch_on_another_cpu_is_decoded_in_that_cpus_byte_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A change watch decodes in its own cpu's byte order, never the main cpu's."""
    ses = _watching(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    orders = {1: ses, 2: SimpleNamespace(byte_order="little", pc_name="PC")}
    monkeypatch.setattr(ses, "layout", lambda thread: orders[thread])
    ses.memory[0x2031FC] = bytes.fromhex("00000000")
    s.watch_add(ref="0x2031fc", mode="change", length=4, fmt="u32", cpu="subcpu")
    s.resume()
    (tmp_path / "debug.log").open("a").write(STOP_LINE)
    ses.memory[0x2031FC] = (0x12345678).to_bytes(4, "little")
    ses.next_packet = "T05watch:0;"
    ses.stops_after_polls = 1
    assert s.status()["stopped_on_its_own"]["cause"].startswith("watch 0x2031fc")
    hit = mstate.STATE.last_stop["watch_hit"]
    assert (hit["before"], hit["after"]) == (0, 0x12345678), hit


@pytest.mark.parametrize(("fmt", "length", "value"), [
    ("u8", 1, 0x12), ("u8[4]", 4, [0x12, 0x34, 0x56, 0x78]), ("char[4]", 4, "\x124Vx"),
    ("{hi:u8,lo:i8}", 2, {"hi": 0x12, "lo": 0x34})], ids=["u8", "u8 array", "string", "struct"])
def test_a_watch_of_one_byte_scalars_reads_on_a_cpu_of_an_unknown_byte_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fmt: str, length: int, value: object,
) -> None:
    """A byte has no order, so one-byte scalars read on a cpu of unknown order."""
    ses = _watching(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    mips = gs.Layout({}, 0, "mips", [])
    monkeypatch.setattr(ses, "layout", lambda thread: mips if thread == 2 else ses)
    ses.memory[0x2031FC] = bytes.fromhex("12345678")
    out = s.watch_add(ref="0x2031fc", mode="show", length=length, fmt=fmt, cpu="subcpu")
    assert out["reading"] == {"available": True, "value": value,
                              "raw_hex": "12345678"[:2 * length]}, out
    (row,) = s.declaration_list("watch")["watches"]
    assert row["reading"]["available"] is True, row
    wide = s.watch_add(ref="0x203200", mode="show", length=2, fmt="u16", cpu="subcpu")
    assert wide["reading"]["available"] is False, wide
    assert "(architecture 'mips') was not read" in wide["reading"]["why"], wide


def test_a_format_the_one_byte_rule_frees_from_an_order_decodes_alike_in_either_order() -> None:
    """Every format the one-byte rule admits decodes alike in both orders; wider ones are barred."""
    raw = bytes.fromhex("1234")
    for spec in ("u8", "i8", "u8[2]", "i8[2]", "char[2]", "{a:u8,b:i8}", "{s:char[2]}"):
        fmt = vf.parse(spec)
        assert watches._one_byte_scalars(fmt), spec
        width = fmt.size or 1
        assert fmt.decode(raw[:width], "big", width) == fmt.decode(raw[:width], "little", width)
    for spec in ("u16", "i16", "ptr16", "u16[1]", "{a:u8,b:u16}", "{p:ptr16}"):
        assert not watches._one_byte_scalars(vf.parse(spec)), spec

def test_a_change_watch_of_one_byte_reports_its_hit_on_a_cpu_of_an_unknown_byte_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    mips = gs.Layout({}, 0, "mips", [])
    monkeypatch.setattr(ses, "layout", lambda thread: mips if thread == 2 else ses)
    ses.memory[0x2031FC] = bytes.fromhex("00")
    s.watch_add(ref="0x2031fc", mode="change", length=1, fmt="u8", cpu="subcpu")
    s.resume()
    (tmp_path / "debug.log").open("a").write(STOP_LINE)
    ses.memory[0x2031FC] = bytes.fromhex("2a")
    ses.next_packet = "T05watch:0;"
    ses.stops_after_polls = 1
    assert s.status()["stopped_on_its_own"]["cause"].startswith("watch 0x2031fc")
    hit = mstate.STATE.last_stop["watch_hit"]
    assert (hit["before"], hit["after"]) == (0, 0x2A), hit


def test_a_watch_on_a_cpu_of_an_unknown_byte_order_is_unreadable_and_the_stops_go_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A watch value that cannot be decoded is `unreadable` with the reason and fails no call."""
    ses = _watching(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    mips = gs.Layout({}, 0, "mips", [])
    monkeypatch.setattr(ses, "layout", lambda thread: mips if thread == 2 else ses)
    out = s.watch_add(ref="0x2031fc", mode="change", length=4, fmt="u32", cpu="subcpu")
    assert out["status"] == "ok" and out["reading"]["available"] is False, out
    assert "(architecture 'mips') was not read" in out["reading"]["why"], out["reading"]
    (row,) = s.declaration_list("watch")["watches"]
    assert row["cpu"] == ":subcpu", row
    s.resume()
    (tmp_path / "debug.log").open("a").write(STOP_LINE)
    ses.next_packet = "T05watch:0;"
    ses.stops_after_polls = 1
    assert s.status()["stopped_on_its_own"]["cause"].startswith("watch 0x2031fc")
    hit = mstate.STATE.last_stop["watch_hit"]
    assert hit["after"]["available"] is False, hit
    assert "(architecture 'mips') was not read" in hit["after"]["why"], hit


def test_the_same_watch_ref_on_another_cpu_is_a_second_declaration_with_its_own_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """One range on two cpus is two rows; a clear naming a cpu takes that cpu's alone."""
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="0x2031fc", mode="change", length=4)
    other = s.watch_add(ref="0x2031fc", mode="change", length=4, cpu="subcpu")
    assert other["status"] == "ok" and other["cpu"] == ":subcpu", other
    assert len(ses.wplist_rows) == 2
    again = s.watch_add(ref="0x2031fc", mode="change", length=4)
    assert again["cpu"] == ":maincpu" and again["already_stored"], again
    assert len(ses.wplist_rows) == 2, "its own row, adopted"
    cleared = s.declaration_clear("watch", ref="0x2031fc", cpu="subcpu")
    assert cleared["declarations_cleared"] == 1 and len(ses.wplist_rows) == 1, cleared
    assert [(w["ref"], w["cpu"]) for w in s.declaration_list("watch")["watches"]] == [("0x2031fc",
                                                                                       ":maincpu")]


def _console_on_two_cpus(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """The console double with two cpus, the sub one reaching less (m68k-dual's masks are equal)."""
    from server_support import _console, _ConsoleSession, _masked

    def save(command: str) -> str:
        path, _start, length = command[len("save "):].split(",")
        Path(path).write_bytes(bytes(int(length, 16)))
        return "Data saved successfully\n"

    def dasm(command: str) -> str:
        (scratch / command[len("dasm "):].split(",")[0]).write_text(captured("dasm.sub.txt"))
        return "Data dumped successfully\n\n"

    ses = _ConsoleSession(bytes(0x5000), replies={
        "cpulist": captured("cpulist.main-visible.txt"), "save": save, "dasm": dasm,
        "find": captured("find.sub.txt"), "history": captured("history.sub.txt")})
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    scratch = _console(monkeypatch, tmp_path, ses)
    monkeypatch.setattr(mstate.STATE, "machine_map", {
        "cpus": [{"tag": ":maincpu"}, {"tag": ":subcpu"}],
        "spaces": _masked(0xFFFFFF)["spaces"] + _masked(0x3FFF, ":subcpu")["spaces"]})
    return ses


def test_each_console_reader_names_the_cpu_in_its_own_syntax_and_says_which(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`dasm`, `find`, `history` and `save` each take the cpu in their own syntax."""
    ses = _console_on_two_cpus(monkeypatch, tmp_path)
    out = [s.disassemble(ref="0x542", length=8, cpu="subcpu"),
           s.find(ref="0x0", length=0x10, data_hex="00000400", cpu="subcpu"),
           s.history(limit=4, cpu="subcpu"),
           s.memdump(ref="0x0", length=8, dest=str(tmp_path / "sub.bin"), cpu="subcpu")]
    assert [o["cpu"] for o in out] == [":subcpu"] * 4, out
    sent = [c for c in ses.commands if c.split()[0] in ("dasm", "find", "history", "save")]
    assert sent == ["dasm dasm.txt,0x542,0x8,1,:subcpu",
                    "find 0x0::subcpu,0x10,0x00,0x00,0x04,0x00", "history :subcpu,0x4",
                    f"save {tmp_path / 'sub.bin'},0x0::subcpu,0x8"], sent
    assert "m@2" in ses.commands, "the dump is checked against the sub cpu's own memory"
    assert out[1]["hits"] == ["0x00000004"] and out[2]["lines"][0] == "000542: bra     $542"
    ses.commands.clear()
    plain = s.history(limit=4)
    assert plain["cpu"] == ":maincpu" and "history ,0x4" in ses.commands


def test_a_write_on_the_sub_cpu_reads_back_there_and_refreshes_only_that_cpus_watch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A write refreshes only the watch on its own cpu; the main cpu's is other memory."""
    ses = _watching(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    main, sub = ("w", ":maincpu"), ("w", ":subcpu")
    mstate.STATE.armed_watches = {
        main: {"addr": 0x2031FC, "length": 4, "cpu": ":maincpu", "last": b"main", "index": 1},
        sub: {"addr": 0x2031FC, "length": 4, "cpu": ":subcpu", "last": b"sub!", "index": 2}}
    out = s.write(ref="0x2031fc", data_hex="0102", cpu="subcpu")
    assert out["cpu"] == ":subcpu" and "m@2" in ses.commands, (out, ses.commands)
    assert mstate.STATE.armed_watches[main]["last"] == b"main", "the main cpu's is untouched"
    assert mstate.STATE.armed_watches[sub]["last"] != b"sub!", "the sub cpu's is re-read"


def test_on_the_patched_stub_a_dump_names_the_cpu_its_control_reads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`save` gets the visible cpu by name, so it and the control read the same cpu."""
    ses = _running(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    ses.visible_cpu = ":subcpu"
    dest = tmp_path / "vis.bin"
    s.memdump(ref="0x400", length=16, dest=str(dest))
    assert f"save {dest},0x400::subcpu,0x10" in ses.commands, ses.commands


def test_find_and_memdump_judge_a_range_by_the_named_cpus_own_mask(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _console_on_two_cpus(monkeypatch, tmp_path)
    refused("0x4001 bytes .* mask is 0x3fff", s.find(ref="0x0", length=0x4001, data_hex="00",
                                                     cpu="subcpu"))
    assert s.find(ref="0x0", length=0x4001, data_hex="00")["status"] == "ok", "the main reaches it"
    refused("wraps", s.memdump(ref="0x3ffc", length=8, dest=str(tmp_path / "w.bin"), cpu="subcpu"))


def test_read_memory_and_write_judge_a_range_by_the_named_cpus_own_mask(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The named cpu's mask decides; nothing is read or written past it."""
    _console_on_two_cpus(monkeypatch, tmp_path)
    refused("mask is 0x3fff", s.read_memory("0x3ffc", length=8, cpu="subcpu"))
    refused("mask is 0x3fff", s.write(ref="0x4000", data_hex="aa", cpu="subcpu"))
    assert s.read_memory("0x3ffc", length=8)["status"] == "ok", "the main reaches it"

def test_without_threads_a_dump_of_another_cpu_is_refused_before_save(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _console_on_two_cpus(monkeypatch, tmp_path)
    ses.threads = {}
    out = refused(r"reads only :maincpu: `memdump\(cpu=':maincpu'\)`",
                  s.memdump(ref="0x0", length=8, dest=str(tmp_path / "s.bin"), cpu="subcpu"))
    assert out["code"] == "bad_argument" and not any(c.startswith("save") for c in ses.commands)


def test_a_reader_refuses_a_cpu_the_machine_lacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _console_on_two_cpus(monkeypatch, tmp_path)
    for out in (s.disassemble(ref="0x0", cpu="audiocpu"), s.history(cpu="audiocpu"),
                s.find(ref="0x0", length=4, data_hex="00", cpu="audiocpu"),
                s.memdump(ref="0x0", length=4, dest=str(tmp_path / "a.bin"), cpu="audiocpu")):
        assert out["code"] == "unknown_ref" and out["cpu_tags"] == [":maincpu", ":subcpu"], out
    assert not any(c.split()[0] in ("dasm", "find", "history", "save") for c in ses.commands)


def test_a_block_found_by_address_is_looked_up_in_the_named_cpus_map(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The named cpu is in the script as composed, not read off the visible cpu."""
    from lua_support import _channel

    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "machine_map",
                        {"cpus": [{"tag": ":maincpu"}, {"tag": ":subcpu"}]})
    ses.answers = {1: (b"MAME_MCP_BLOCK kind=region tag=:subcpu size=64 bytewidth=2 endian=big "
                       b"start=0 offset=1024 hex=46fc2700\n") + ses.sentinel(1)}
    out = s.read_block(ref="0x400", length=4, cpu="subcpu")
    assert out["status"] == "ok" and out["addr_cpu"] == ":subcpu", out
    sent = ses.stdin.getvalue().decode()
    assert 'manager.machine.devices[\\":subcpu\\"].spaces[\\"program\\"]' in sent, sent[-400:]


def test_the_lists_narrow_to_a_cpu_through_the_consoles_own_filter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x542", cpu="subcpu")
    s.breakpoint_at(ref="0x4a0")
    sub = s.declaration_list("breakpoint", cpu="subcpu")
    assert sub["cpu"] == ":subcpu" and [b["ref"] for b in sub["breakpoints"]] == ["0x542"], sub
    assert "bplist :subcpu" in ses.commands and "foreign" not in sub
    main = s.declaration_list("breakpoint", cpu="maincpu")
    assert [b["ref"] for b in main["breakpoints"]] == ["0x4a0"], main
    listed = s.declaration_list("breakpoint")
    assert len(listed["breakpoints"]) == 2 and listed["cpu"]["available"] is False, listed
    s.watch_add(ref="0x2031fc", mode="change", length=4, cpu="subcpu")
    s.watch_add(ref="0x203200", mode="change", length=2)
    s.watch_add(ref="0x203300", mode="show", length=2)
    watched = s.declaration_list("watch", cpu="subcpu")
    assert watched["cpu"] == ":subcpu" and [w["ref"] for w in watched["watches"]] == ["0x2031fc"]
    assert "wplist :subcpu" in ses.commands and "foreign" not in watched
    assert [w["ref"] for w in s.declaration_list("watch", cpu="maincpu")["watches"]] == ["0x203200",
                                                                                         "0x203300"]
    assert len(s.declaration_list("watch")["watches"]) == 3


def test_a_registerpoint_names_only_the_visible_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`rpset` takes no cpu, so a registerpoint on another is refused naming `focus`."""
    ses = _running(monkeypatch, tmp_path)
    out = refused(r"visible cpu, :maincpu, .*`focus\(cpu=':subcpu'\)` first",
                  s.regpoint_add(condition="d1==7fff", cpu="subcpu"))
    assert out["code"] == "needs_call" and not any(c.startswith("rpset") for c in ses.commands)
    assert s.regpoint_add(condition="d1==7fff", cpu="maincpu")["cpu"] == ":maincpu"
    listed = s.declaration_list("regpoint", cpu=":maincpu")
    assert listed["cpu"] == ":maincpu" and len(listed["regpoints"]) == 1
    other = s.declaration_list("regpoint", cpu="subcpu")
    assert other["cpu"] == ":subcpu" and other["regpoints"] == [], "narrowed, as breakpoints are"


def test_the_gather_reads_each_cpus_register_names_off_its_own_state() -> None:
    from test_machine import M68K_DUAL

    import mame_cpus as cpus
    import mame_machine as machine

    regs = machine.parse(M68K_DUAL)[cpus.CPU_REGISTERS]
    assert sorted(regs) == [":maincpu", ":subcpu"]
    assert {"D0", "A7", "PC"} - set(regs[":subcpu"]) == {"A7"}, "the console's own names"


def test_a_condition_is_judged_against_the_registers_of_the_cpu_it_arms_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A symbol spelled like the sub cpu's register is ambiguous there only."""
    import mame_cpus as cpus

    _running(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"IX": 0x2000})
    monkeypatch.setattr(mstate.STATE, "machine_map", {
        "cpus": [{"tag": ":maincpu"}, {"tag": ":subcpu"}],
        cpus.CPU_REGISTERS: {":maincpu": ["D0", "PC"], ":subcpu": ["IX", "PC"]}})
    out = refused(r"'IX' is both a symbol of the table and a name the console knows",
                  s.breakpoint_at(ref="0x542", condition="IX==1", cpu="subcpu"))
    assert out["code"] == "ambiguous_ref"
    main = s.breakpoint_at(ref="0x4a0", condition="IX==1")
    assert main["status"] == "ok" and main["condition"] == "0x2000==1", main


def test_the_debuggers_temps_are_one_pool_across_cpus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The console's temps are global: each control takes its own, read in one `print`."""
    ses = _running(monkeypatch, tmp_path)
    main = s.breakpoint_at(ref="0x4a0", role="control")
    sub = s.breakpoint_at(ref="0x542", role="control", cpu="subcpu")
    assert (main["temp"], main["cpu"]) == ("temp0", ":maincpu"), main
    assert (sub["temp"], sub["cpu"]) == ("temp1", ":subcpu"), sub
    assert "bp 0x542::subcpu,(++temp1)==0" in ses.commands
    ses.temps = {0: 50, 1: 15625}
    listed = s.declaration_list("breakpoint")["breakpoints"]
    counts = {b["ref"]: b["hits_since_armed"] for b in listed}
    assert counts == {"0x4a0": 50, "0x542": 15625}
    assert "print temp0,temp1" in ses.commands


def test_one_range_tallied_on_two_cpus_is_two_taps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A tap counts one cpu's writes, so its tally id carries a named sub cpu."""
    _watching(monkeypatch, tmp_path)
    sent: list[str] = []

    def send(script: str, ours: bool = False) -> tuple[str, int]:
        sent.append(script)
        return "l", len(sent)

    monkeypatch.setattr(transport, "send", send)
    sub = s.watch_add(ref="0x2031fc", mode="count", length=4, cpu="subcpu")
    assert sub["cpu"] == ":subcpu" and sub["tally_id"] == "2031fc_4_subcpu", sub
    assert 'devices[":subcpu"]' in sent[-1]
    main = s.watch_add(ref="0x2031fc", mode="count", length=4, cpu="maincpu")
    assert main["status"] == "ok" and main["tally_id"] == "2031fc_4", main
    assert 'devices[":maincpu"]' in sent[-1]
    again = s.watch_add(ref="0x2031fc", mode="count", length=4, cpu="subcpu")
    assert again["already_stored"] and again["tally_id"] == "2031fc_4_subcpu", again


def test_a_silent_controls_listing_is_decoded_on_the_controls_own_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The control's listing is decoded on the control's cpu, which need not be the visible one."""
    import mame_advance as advance

    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(advance, "RUN_POLL_S", 0.0)
    s.breakpoint_at(ref="0x25a4", role="control")
    ses.visible_cpu = ":subcpu"
    out = s.run_to(ref="0x4a0", cpu="maincpu", seconds=0.05)
    assert out["code"] == "control_silent", out
    assert any(c.startswith("dasm ") and c.endswith(",1,:maincpu") and "0x25a4" in c
               for c in ses.commands), [c for c in ses.commands if c.startswith("dasm")]


def test_a_pointer_watch_is_read_and_placed_on_its_declarations_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The pointer is read through its declaration's cpu thread; without threads it is refused."""
    from test_pointer_watches import _pointing

    ses = _pointing(monkeypatch, tmp_path)
    ses.visible_cpu = ":subcpu"
    out = refused("read through a thread", s.watch_add(ref="_g_engine->sync_delta",
                                                       mode="change"))
    assert arming.store().declarations() == [], out
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    out = s.watch_add(ref="_g_engine->sync_delta", mode="change")
    assert out["status"] == "ok" and out["cpu"] == ":subcpu", out
    assert any(c.startswith("wp ") and "::subcpu," in c for c in ses.commands), ses.commands


def test_a_watch_declared_again_after_a_stop_elsewhere_is_the_visible_cpus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An unnamed declaration is the visible cpu's, wherever a stop left it."""
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="0x2031fc", mode="change", length=4)
    ses.visible_cpu = ":subcpu"
    ses.commands.clear()
    again = s.watch_add(ref="0x2031fc", mode="change", length=4)
    assert again["cpu"] == ":subcpu" and not again.get("already_stored"), again
    assert "map 0x2031fc::subcpu" in ses.commands, ses.commands


def test_a_typed_ignore_of_the_live_cpu_records_the_stop_it_ran_to(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The run a typed `focus` released ends at a stop with no packet; it is still recorded."""
    ses = _running(monkeypatch, tmp_path)
    before = mstate.STATE.last_stop["seq"]
    out = s.debug(command="focus subcpu")
    assert "that stop is recorded" in out["note"], out
    assert mstate.STATE.last_stop["seq"] == before + 1
    assert mstate.STATE.last_stop["cause"].startswith("debug: the console ignored :maincpu")
    assert s.status()["last_stop"]["stop_seq"] == before + 1 and not ses.running


_SPACES = {"spaces": [
    {"cpu": ":maincpu", "space": "cpu_space", "endianness": "little"},
    {"cpu": ":maincpu", "space": "program", "endianness": "big"},
    {"cpu": ":audiocpu", "space": "io", "endianness": "big"},
    {"cpu": ":audiocpu", "space": "program", "endianness": "little"}]}


def test_each_thread_takes_its_own_cpus_program_space_endianness() -> None:
    """A thread's registers are in its cpu's program space's order, never another space's."""
    ses = gs.Session()
    ses.threads = {1: ":maincpu", 2: ":audiocpu"}
    assert cpus.program_endianness(ses, _SPACES, ":maincpu") == {1: "big", 2: "little"}


def test_a_stub_without_threads_serves_its_first_cpu_as_thread_one() -> None:
    assert cpus.program_endianness(gs.Session(), _SPACES, ":audiocpu") == {1: "little"}


def test_a_cpu_the_inventory_has_no_program_space_for_gets_no_word() -> None:
    """No program-space row gives no word, and never a fallback."""
    ses = gs.Session()
    ses.threads = {1: ":maincpu", 2: ":motorcpu"}
    assert cpus.program_endianness(ses, _SPACES, ":maincpu") == {1: "big"}
    assert cpus.program_endianness(ses, {"spaces": []}, ":maincpu") == {}
    assert cpus.program_endianness(gs.Session(), None, None) == {}
