"""The watch family: typed watchpoint, list, clear, control and the stored declarations."""

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server_support import _running, _RunningSession  # noqa: E402
from session_doubles import (
    MAP_LATCH,
    MAP_RAM,
    MAP_ROM,
    WP_ARM,
    bp_records,
    bplist_add,
    captured,
    one_cpus_list,
    place_row,
    refs,
    refused,
    row_index,
    use_table,  # noqa: E402
    wplist_add,
    wplist_answer,
)
from test_gdb_session import _wired  # noqa: E402
from test_machine import M68K_DUAL, _cached  # noqa: E402

import gdb_session as gs  # noqa: E402
import mame_advance as advance  # noqa: E402
import mame_arming as arming  # noqa: E402
import mame_declarations as dec  # noqa: E402
import mame_inputs as inputs  # noqa: E402
import mame_lists as mlists  # noqa: E402
import mame_map as mmap  # noqa: E402
import mame_read as read  # noqa: E402
import mame_rearm as rearming  # noqa: E402
import mame_running as running  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_watches as watches  # noqa: E402
import server as s  # noqa: E402

# Captured from a live m68k-dual session, never authored (`map`'s are in `session_doubles`).
WPLIST_ONE = "Device ':maincpu' program space watchpoints:\n    1 @ 2031FC-2031FF write\n\n"
WPLIST_NONE = "No watchpoints currently installed\n\n"
STOP_LINE = "Stopped at watchpoint 1 writing 0038 to 2031FE (PC=0000040E)\n"


class _WatchSession(_RunningSession):
    """The running double plus `map`, `wplist`, a byte order, memory and watch stop packets."""

    def __init__(self, scratch: Path) -> None:
        super().__init__(scratch)
        self.byte_order = "big"
        self.pointer_width = 4
        self.memory: dict[int, bytes] = {}
        self.watchpoints: list[tuple[int, int, bool]] = []
        self.rom_write_unmapped: set[int] = {0x400}
        self.latches: set[int] = set()
        self.wplist_rows: list[str] = []
        self.wp_next_index = 1
        self.next_packet = "T05"
        self.packets: list[str] = []
        self.stop_queue: list[int] = []

    def read(self, addr: int, n: int, *, thread: int) -> bytes:
        if thread != 1:
            self.commands.append(f"m@{thread}")
        return self.memory.get(addr, bytes(n))[:n].ljust(n, b"\0")

    def write(self, addr: int, data: bytes, *, thread: int) -> None:
        self.memory[addr] = data
        self.writes += 1

    def watchpoint(self, addr: int, length: int, remove: bool = False, cpu: str | None = None,
                   index: int | None = None, cond: str = "") -> None:
        """What a `wp` or a `wpclear` does to the debugger's list: a row added under the next
        index (on `cpu`, under `cond`), or the row numbered `index` dropped. The console half
        below routes both here, so a case can stand in for the debugger's answer to either."""
        self.watchpoints.append((addr, length, remove))
        if remove:
            self.wplist_rows = [r for r in self.wplist_rows if row_index(r) != index]
        else:
            place_row(self, "wp_devices", wplist_add(self, addr, length, cond), cpu)

    def _stop(self) -> None:
        super()._stop()
        self.last_stop_packet = self.packets.pop(0) if self.packets else self.next_packet

    def poll_stop(self, timeout: float = 0.0) -> bool:
        if self.running and self.stops_after_polls is None and self.stop_queue:
            self.stops_after_polls = self.stop_queue.pop(0)
        return super().poll_stop(timeout)

    def _receive(self, timeout: float | None = None) -> str:
        raise gs.SessionError("no answer within the drain")

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        if (armed := WP_ARM.fullmatch(command)) is not None:
            self.commands.append(command)
            index = self.wp_next_index
            addr, length = int(armed.group(1), 16), int(armed.group(3), 16)
            if armed.group(4):
                self.watchpoint(addr, length, cpu=armed.group(2), cond=armed.group(4))
            else:
                self.watchpoint(addr, length, cpu=armed.group(2))
            return captured("wpset.set.txt").replace("Watchpoint 1 ", f"Watchpoint {index:X} ")
        if command.startswith("wpclear "):
            self.commands.append(command)
            index = int(command[8:], 16)
            row = next((r for r in self.wplist_rows if row_index(r) == index), None)
            if row is None:
                return captured("wpclear.invalid.txt").replace(" 9\n", f" {index:X}\n")
            lo, hi = (int(x, 16) for x in row.split(" @ ", 1)[1].split()[0].split("-"))
            self.watchpoint(lo, hi - lo + 1, remove=True, index=index)
            return captured("wpclear.cleared.txt").replace("Watchpoint 1 ",
                                                           f"Watchpoint {index:X} ")
        if command.startswith("map ") or command == "wplist":
            self.commands.append(command)
        if command.startswith("map "):
            addr = int(command[4:].split(":", 1)[0], 16)
            if addr in self.latches:
                return MAP_LATCH
            return MAP_ROM if addr in self.rom_write_unmapped else MAP_RAM
        if command == "wplist":
            return wplist_answer(self.wplist_rows, getattr(self, "wp_devices", None))
        if command.startswith("wplist :"):
            self.commands.append(command)
            return one_cpus_list(self.wplist_rows, getattr(self, "wp_devices", None),
                                 command.split()[1], wplist_answer, "wplist.sub-none.txt")
        return super().monitor(command, timeout)


def _watching(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _WatchSession:
    ses = _WatchSession(tmp_path)
    _running(monkeypatch, tmp_path, ses)
    use_table(monkeypatch, table={"FRAME_LO": 0x2031FC, "COPY_IN_ROM": 0x400})
    return ses


def test_a_watch_declaration_needs_a_mode_a_format_and_a_coherent_width() -> None:
    """The store refuses an ill-formed watch at construction."""
    with pytest.raises(dec.DeclarationError, match="mode"):
        dec.Declaration("watch", "symbol", "x", width=4, fmt="u32", watch_mode="poll")
    with pytest.raises(dec.DeclarationError, match="format"):
        dec.Declaration("watch", "symbol", "x", width=4, fmt="u64", watch_mode="show")
    with pytest.raises(dec.DeclarationError, match="whole number"):
        dec.Declaration("watch", "symbol", "x", width=2, fmt="u32", watch_mode="show")
    with pytest.raises(dec.DeclarationError, match="no watch fields"):
        dec.Declaration("breakpoint", "symbol", "x", width=4)
    with pytest.raises(dec.DeclarationError, match="kind"):
        dec.Declaration("interrupt", "address", "21")
    ok = dec.Declaration("watch", "symbol", "x", width=8, fmt="u16", watch_mode="change")
    assert ok.to_dict() == {"kind": "watch", "by": "symbol", "ref": "x", "width": 8,
                            "fmt": "u16", "watch_mode": "change"}
    assert dec.Declaration.from_dict(ok.to_dict()) == ok


def test_one_address_may_not_be_both_read_and_change() -> None:
    """Read and change watches on one address stay exclusive, as on the other server."""
    store = dec.DeclarationStore("k", path=None)
    assert store.add(dec.Declaration("watch", "symbol", "x", width=4, fmt="u32",
                                     watch_mode="show")) is True
    with pytest.raises(dec.DeclarationError, match="may not be both"):
        store.add(dec.Declaration("watch", "symbol", "x", width=4, fmt="u32",
                                  watch_mode="change"))
    assert store.add(dec.Declaration("watch", "symbol", "x", width=4, fmt="u32",
                                     watch_mode="show")) is False
    assert len(store.declarations()) == 1


def test_a_declaration_by_name_re_resolves_and_a_vanished_name_is_kept() -> None:
    table = {"FRAME": 0x2031FC}
    by_name = dec.Declaration("watch", "symbol", "frame", width=4, fmt="u32", watch_mode="show")
    assert dec.resolve(by_name, table) == dec.Resolved(by_name, "resolved", 0x2031FC)
    assert dec.resolve(by_name, {"FRAME": 0x300000}).addr == 0x300000, "a rebuild moves it"
    assert dec.resolve(by_name, {}).state == "unresolved", "kept, never dropped"
    by_addr = dec.Declaration("breakpoint", "address", "0x4a0")
    assert dec.resolve(by_addr, {}) == dec.Resolved(by_addr, "address", 0x4A0)


def test_the_spelling_decides_an_address_and_bare_hex_names_a_symbol_or_nothing() -> None:
    """`0x` is an address, a held name a symbol, bare hex naming neither is refused."""
    table, main = {"BEEF": 0x100}, ":maincpu"
    assert inputs.classify("beef", table, main) == "symbol"
    assert inputs.classify("0xbeef", table, main) == "address"
    assert inputs.classify("0X4A0", table, main) == "address"
    assert inputs.classify("scene_id", table, main) == "symbol"
    assert inputs.classify("4a0", table, main, held=["4A0"]) == "symbol"
    with pytest.raises(inputs.BareHex, match="an address is written 0x4a0"):
        inputs.classify("4a0", table, main)


def test_a_change_watch_arms_reads_the_list_back_and_says_where_it_maps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x2031FC] = bytes.fromhex("00000037")
    out = s.watch_add(ref="frame_lo", mode="change", length=4)
    assert out["status"] == "ok" and out["armed"] is True and out["by"] == "symbol"
    assert out["addr"] == "0x002031fc" and out["index"] == 1 and out["stored"] is True
    assert out["entry"] == "1 @ 2031FC-2031FF write", "the debugger's own row, read back"
    assert out["write_maps_to"] == "memory@200000"
    assert out["state"] == "armed" and out["reading"]["value"] == 0x37, (
        "armed is where it is, the reading is the bytes at arming: the `before` of the first hit")
    assert ses.watchpoints == [(0x2031FC, 4, False)]
    assert out["summary"] == "watch_add frame_lo: change watch armed at 0x002031fc, 4 bytes"
    assert out["session"]["altered"] is False, "arming writes nothing to the machine"


def test_a_change_watch_on_an_address_whose_write_side_is_unmapped_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """THE CONTROL. The stub accepts a `Z2` on a ROM address, lists it, and it can
    never fire, which is exactly the silence `run_to`'s control exists to expose. The
    console's `map` says the write side is `unmapped`, so the watch is refused BEFORE it is
    armed, naming the line; nothing is stored, nothing is listed."""
    ses = _watching(monkeypatch, tmp_path)
    out = s.watch_add(ref="copy_in_rom", mode="change", length=2, fmt="u16")
    assert out["status"] == "INVALID" and "unmapped" in out["message"]
    assert "ROM copy" in out["message"] or "never fire" in out["message"]
    assert ses.watchpoints == [], "refused before the stub was touched"
    assert s.declaration_list("watch")["watches"] == []


def test_a_map_answer_of_an_unknown_shape_is_invalid_not_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "monitor", lambda command, timeout=10.0: "Unknown command\n")
    out = s.watch_add(ref="frame_lo", mode="change", length=4)
    assert out["status"] == "INVALID" and "Write" in out["message"]
    assert ses.watchpoints == []


def test_a_watch_the_debugger_did_not_list_after_arming_is_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The acknowledgement is not the proof: the row has to be in `wplist`."""
    ses = _watching(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "watchpoint", lambda addr, length, remove=False, cpu=None,
                        index=None: None)
    out = s.watch_add(ref="frame_lo", mode="change", length=4)
    assert out["status"] == "INVALID" and "wplist" in out["message"]


def test_a_read_watch_arms_nothing_and_is_evaluated_at_every_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x2031FC] = bytes.fromhex("00000037")
    out = s.watch_add(ref="frame_lo", mode="show", length=4)
    assert out["armed"] is False and out["state"] == "evaluated"
    assert out["reading"] == {"available": True, "value": 0x37, "raw_hex": "00000037"}
    assert ses.watchpoints == []
    ses.memory[0x2031FC] = bytes.fromhex("00000038")
    stop = s.step()
    assert stop["watches"] == [{
        "ref": "frame_lo", "cpu": ":maincpu",
        "state": "evaluated", "reading": {"available": True, "value": 0x38, "raw_hex": "00000038"},
    }]
    assert stop["omitted"] == ["addr", "by", "fmt", "length", "mode"]
    assert stop["how"] == watches.STOP_HOW
    listed = s.declaration_list("watch")["watches"]
    assert {k: listed[0][k] for k in stop["omitted"]} == {
        "addr": "0x002031fc", "by": "symbol", "fmt": "u32", "length": 4, "mode": "show"}
    assert "watches" not in s.status(), "a survey field, not a status one"


def test_one_read_watch_speaks_one_vocabulary_in_all_three_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """ONE UNCHANGED SHOW WATCH, THREE READERS, ONE SHAPE. Its `state` is `evaluated` in all
    three, because that is where it is placed; its `reading` is `read` with `value` and
    `bytes` wherever THIS call read it, and absent on a running machine, which answers no
    read. The listing tool is where a caller looks first, so it reads too: a word that
    changes under an unchanged watch reads as a state machine that is not there. The FIELDS
    are asserted, not the word alone, or a value dropped passes."""
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x2031FC] = bytes.fromhex("00000037")
    reading = {"state": "evaluated", "addr": "0x002031fc",
               "reading": {"available": True, "value": 0x37, "raw_hex": "00000037"}}

    def fields(w: dict[str, Any]) -> dict[str, Any]:
        return {k: w.get(k) for k in reading}

    added = s.watch_add(ref="frame_lo", mode="show", length=4)
    listed = s.declaration_list("watch")["watches"]
    surveyed = s.step()["watches"]
    assert [fields(added), *map(fields, listed)] == [reading] * 2
    assert [{k: w.get(k) for k in ("state", "reading")} for w in surveyed] == [
        {k: reading[k] for k in ("state", "reading")}], "a stop reads the same, placed or not"
    ses.go()
    running = s.declaration_list("watch")["watches"]
    assert [(w["state"], "reading" in w) for w in running] == [
        ("evaluated", False)], "a running machine answers no read, and says so"


def test_values_render_in_the_targets_byte_order_and_in_every_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A value is rendered in its cpu's byte order, and one rendered the wrong way round is a
    plausible wrong number."""
    big = watches._value(bytes.fromhex("00010002"), 4, "u16", "big")
    assert big == [1, 2]
    assert watches._value(bytes.fromhex("00010002"), 4, "u16", "little") == [0x100, 0x200]
    assert watches._value(bytes.fromhex("ffffffff"), 4, "i32", "big") == -1
    assert watches._value(bytes.fromhex("3f800000"), 4, "f32", "big") == 1.0
    assert watches._value(bytes.fromhex("fffb"), 2, "i16", "big") == -5
    assert watches._value(bytes.fromhex("80"), 1, "i8", "big") == -128
    assert watches._value(bytes.fromhex("0102"), 2, "u8", "big") == [1, 2]


def test_a_watch_stop_is_attributed_from_the_packet_and_the_console_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """WHO WROTE THIS BYTE. On a 68000 board the stub's stop packet is
    `T05watch:<addr>;...`, the write has LANDED when the machine stops, the stop's pc is the
    instruction AFTER the writer, and the console's own line (`-debuglog`, in the scratch)
    names the watchpoint, the value written, the address and the writer's pc. The reply
    carries all of it and quotes the line."""
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x2031FC] = bytes.fromhex("00000037")
    s.watch_add(ref="frame_lo", mode="change", length=4)
    (tmp_path / "debug.log").write_text("F2034\n" + "Data dumped successfully\n")
    s.resume()
    (tmp_path / "debug.log").open("a").write(STOP_LINE + "25F6\n")
    ses.memory[0x2031FC] = bytes.fromhex("00000038")
    ses.next_packet = "T05watch:2031fc;0e:00000000;11:0000040e;"
    ses.stops_after_polls = 1
    st = s.status()
    found = st["stopped_on_its_own"]
    assert found["cause"] == "watch frame_lo: 0x002031fc written by pc 0x0000040e"
    assert st["last_stop"]["cause"] == found["cause"]
    hit = mstate.STATE.last_stop["watch_hit"]
    assert hit == {
        "ref": "frame_lo", "addr": "0x002031fc", "cpu": ":maincpu", "index": 1,
        "writer_pc": "0x0000040e",
        "writes": [{"wrote": "0x0038", "to": "0x002031fe", "pc": "0x0000040e"}],
        "writes_total": 1, "truncated": False,
        "before": 0x37, "after": 0x38, "lines": [STOP_LINE.strip()], "values_from": "memory",
    }
    ses.next_packet = "T05watch:2031fc;"
    ses.stops_after_polls = 1
    (tmp_path / "debug.log").open("a").write(STOP_LINE.replace("0038", "0039") + "25F6\n")
    ses.memory[0x2031FC] = bytes.fromhex("00000039")
    out = s.resume(seconds=1.0)
    assert out["cause"].startswith("watch frame_lo")
    assert out["watch_hit"]["writes"][0]["wrote"] == "0x0039"
    assert out["watch_hit"]["cpu"] == ":maincpu", "a hit names the cpu its watch is on"
    assert out["watch_hit"]["before"] == 0x38 and out["watch_hit"]["after"] == 0x39
    assert out["watches"][0]["reading"]["value"] == 0x39, (
        "a change watch's bytes are read too: no trap")
    keys = list(out)
    assert keys.index("watches") < keys.index("watch_hit"), (
        "the survey lists every watch evaluated, then the one that stopped it")


def test_a_watch_that_stops_a_console_started_run_is_attributed_from_the_log_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A watch stopping a console-started run (`gtime`, no packet) is attributed from the log."""
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x2031FC] = bytes.fromhex("00000037")
    s.watch_add(ref="frame_lo", mode="change", length=4)
    (tmp_path / "debug.log").write_text("F2034\n")
    ses.last_stop_packet = ""
    (tmp_path / "debug.log").open("a").write(STOP_LINE + "25F6\n")
    ses.memory[0x2031FC] = bytes.fromhex("00000038")
    found = watches.watch_stop(ses, arming.debuglog_since(tmp_path))  # type: ignore[arg-type]
    assert found is not None, "a watch stop with a console line and no packet was lost"
    how, hit, fresh = found
    assert how == "watch frame_lo: 0x002031fc written by pc 0x0000040e"
    assert hit is not None and hit["writes"][0]["wrote"] == "0x0038" and hit["after"] == 0x38
    assert fresh == {("frame_lo", ":maincpu"): bytes.fromhex("00000038")}
    assert watches.watch_stop(ses, arming.debuglog_since(tmp_path)) is None  # type: ignore[arg-type]


def test_a_run_for_cut_by_a_watch_before_a_frame_is_a_stop_and_not_a_void_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A change watch firing inside `run_for` is a measurement (`OTHER_STOP`), not `no_progress`."""
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x2031FC] = bytes.fromhex("00000037")
    s.watch_add(ref="frame_lo", mode="change", length=4)
    (tmp_path / "debug.log").write_text("F2034\n")
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    ses.last_stop_packet = ""
    (tmp_path / "debug.log").open("a").write(STOP_LINE + "25F6\n")
    ses.memory[0x2031FC] = bytes.fromhex("00000038")
    out = s.run_for(milliseconds=1)
    assert out["status"] == "ok" and out["verdict"] == "OTHER_STOP", out
    assert out["cause"] == "watch frame_lo: 0x002031fc written by pc 0x0000040e", out["cause"]
    assert out["watch_hit"]["after"] == 0x38 and out["frame_before"] == out["frame_after"]
    assert "code" not in out and "message" not in out


def test_a_write_by_this_server_moves_the_watchs_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`before` is the previous survey's value, and a `write` is a survey (arm at 18, write 4660,
    the game writes 4661: before is 4660)."""
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x2031FC] = bytes.fromhex("00000012")
    s.watch_add(ref="frame_lo", mode="change", length=4)
    s.watch_add(ref="0x2000", mode="change", length=2, fmt="u16")
    assert s.write(ref="frame_lo", data_hex="00001234")["verified"] is True
    (tmp_path / "debug.log").write_text(STOP_LINE + "25F6\n")
    ses.memory[0x2031FC] = bytes.fromhex("00001235")
    ses.last_stop_packet = "T05watch:2031fc;"
    found = watches.watch_stop(ses, arming.debuglog_since(tmp_path))  # type: ignore[arg-type]
    assert found is not None
    _how, hit, _fresh = found
    assert hit is not None and hit["before"] == 0x1234 and hit["after"] == 0x1235, hit


def test_a_short_read_refreshing_a_baseline_after_a_write_refuses_and_names_the_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A short re-read after the write is an answer: `readback_refused`, nothing latches."""
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    plain = ses.read

    def short_on_the_watch(addr: int, n: int, *, thread: int) -> bytes:
        got = plain(addr, n, thread=thread)
        return got[:-1] if (addr, n) == (0x2031FC, 4) else got

    monkeypatch.setattr(ses, "read", short_on_the_watch)
    out = s.write(ref="0x2031fe", data_hex="1234")
    assert out["status"] == "INVALID" and out["code"] == "readback_refused", out
    assert out["bytes_written"] == 2 and out["verified"] is True and out["readback"] == "1234", out
    assert getattr(ses, "broken", None) is None, "an answer latches nothing"
    assert "3 bytes for 4" in out["message"], out
    # Only the channel's failure is dressed as a broken session; a re-read defect stays itself.

    def defective(ses_: Any, addr: int, n: int, cpu: str | None) -> None:
        raise KeyError("last")

    monkeypatch.setattr(watches, "refresh_baselines", defective)
    with pytest.raises(KeyError):
        s.write(ref="0x2031fe", data_hex="1234")


def _rom_under_write(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _WatchSession:
    """m68k-dual answers a write to its ROM: `map` gives no write side, the bytes land nowhere."""
    ses = _watching(monkeypatch, tmp_path)
    ses.rom_write_unmapped.add(0x7B8)
    ses.memory[0x7B8] = bytes.fromhex("80a0")
    landing = ses.write
    monkeypatch.setattr(ses, "write",
                        lambda addr, data, *, thread: None if addr in ses.rom_write_unmapped
                        else landing(addr, data, thread=thread))
    _cached(monkeypatch, tmp_path)
    return ses


def test_a_write_that_goes_nowhere_on_rom_says_so_and_names_the_region_behind_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """m68k-dual 0x7b8: write side unmapped, read side memory at offset 0x7b8 of `:maincpu`."""
    ses = _rom_under_write(monkeypatch, tmp_path)
    out = s.write(ref="0x7b8", data_hex="8020")
    assert out["verified"] is False and out["readback"] == "80a0", out
    assert (out["target"], out["region"], out["region_offset"]) == ("rom", ":maincpu", 0x7B8), out
    assert "no write side" in out["note"], out
    assert ses.commands.count("map 0x7b8::maincpu") == 1, ses.commands


def test_a_rom_write_on_two_cpus_names_the_region_of_the_cpu_it_went_to(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """m68k-dual backs 0..0xfffff on both cpus; write, read-back and `map` ask one named cpu."""
    ses = _rom_under_write(monkeypatch, tmp_path)
    real = ses.monitor
    monkeypatch.setattr(ses, "monitor",
                        lambda c, timeout=10.0: "[0] :maincpu\n[1] :subcpu\n\n" if c == "cpulist"
                        else real(c))
    out = s.write(ref="0x7b8", data_hex="8020")
    assert (out["cpu"], out["region"], out["region_offset"]) == (":maincpu", ":maincpu", 0x7B8)
    assert "map 0x7b8::maincpu" in ses.commands, ses.commands


def test_a_rom_write_to_a_cpu_the_console_cannot_name_names_no_region(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A `cpulist` naming no cpu leaves a threadless stub with no name for a region."""
    ses = _rom_under_write(monkeypatch, tmp_path)
    real = ses.monitor
    monkeypatch.setattr(ses, "monitor",
                        lambda c, timeout=10.0: "\n" if c == "cpulist" else real(c))
    monkeypatch.setattr(mstate.STATE, "cpus", [])
    out = s.write(ref="0x7b8", data_hex="8020")
    assert out["target"] == "rom" and out["cpu"]["available"] is False and "region" not in out, out
    assert "`cpulist` named no cpu the write went to" in out["note"], out


def test_a_map_the_console_refuses_after_a_rom_write_keeps_what_landed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A refused `map` explanation latches nothing; the reply keeps the write and read-back."""
    ses = _rom_under_write(monkeypatch, tmp_path)
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("map "):
            wire, _ = _wired(["E01"])
            return str(wire.monitor(command))
        return str(real(command, timeout))

    monkeypatch.setattr(ses, "monitor", monitor)
    out = s.write(ref="0x7b8", data_hex="8020")
    assert out["code"] == "readback_refused" and out["readback"] == "80a0", out
    assert out["verified"] is False and getattr(ses, "broken", None) is None, out


@pytest.mark.parametrize(("threads", "went_to"), [
    ({}, ":maincpu"), ({1: ":maincpu", 2: ":subcpu"}, ":subcpu")], ids=["no-threads", "threads"])
def test_a_rom_write_with_another_cpu_visible_is_explained_on_the_cpu_it_went_to(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, threads: dict[int, str], went_to: str,
) -> None:
    """After a `focus` the `map` is asked of the sub cpu by name and the region is its own."""
    ses = _rom_under_write(monkeypatch, tmp_path)
    ses.visible_cpu, ses.threads = ":subcpu", threads
    out = s.write(ref="0x7b8", data_hex="8020")
    assert (out["cpu"], out["region"], out["region_offset"]) == (went_to, went_to, 0x7B8), out
    assert f"map 0x7b8:{went_to}" in ses.commands, ses.commands


# m68k-dual's :maincpu ROM entry with a mirror bit, then one overlapped by a second entry.
_ROM_ENTRY = "ENTRY :maincpu program 1 start=0 end=fffff mirror=0 "
_MIRRORED = M68K_DUAL.replace(_ROM_ENTRY, "ENTRY :maincpu program 1 start=0 end=fffff "
                             "mirror=100000 ")
_OVERLAPPED = M68K_DUAL.replace(
    _ROM_ENTRY, "ENTRY :maincpu program 1 start=0 end=fff mirror=0 mask=0 share=- "
    "region=:user1 region_offset=0\n" + _ROM_ENTRY.replace(" 1 ", " 2 ", 1))


def test_a_rom_write_through_a_mirror_names_the_bytes_it_mirrors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """MAME ignores mirror bits: 0x1007b8 mirrored at 0x100000 is offset 0x7b8 of the region."""
    assert _MIRRORED != M68K_DUAL, "the anchor matched nothing"
    ses = _rom_under_write(monkeypatch, tmp_path)
    ses.rom_write_unmapped.add(0x1007B8)
    ses.memory[0x1007B8] = bytes.fromhex("80a0")
    _cached(monkeypatch, tmp_path, dump=_MIRRORED)
    out = s.write(ref="0x1007b8", data_hex="8020")
    assert (out["region"], out["region_offset"]) == (":maincpu", 0x7B8), out


def test_a_rom_write_under_two_entries_of_one_cpu_names_no_region(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    assert _OVERLAPPED != M68K_DUAL, "the anchor matched nothing"
    _rom_under_write(monkeypatch, tmp_path)
    _cached(monkeypatch, tmp_path, dump=_OVERLAPPED)
    out = s.write(ref="0x7b8", data_hex="8020")
    assert out["target"] == "rom" and "region" not in out, out
    assert "more than one entry" in out["note"], out


@pytest.mark.parametrize("where", ["map", "refresh"])
def test_a_request_after_a_rom_write_that_loses_the_connection_latches(
    where: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The `map` asked why and a watched range's re-read follow the read-back's rule."""
    ses = _rom_under_write(monkeypatch, tmp_path)
    gone = gs._connection_failed(ConnectionResetError(54, "Connection reset by peer"))
    if where == "map":
        real = ses.monitor

        def monitor(command: str, timeout: float = 10.0) -> str:
            if command.startswith("map "):
                raise gone
            return str(real(command, timeout))

        monkeypatch.setattr(ses, "monitor", monitor)
    else:
        def lost(ses_: Any, addr: int, n: int, cpu: str | None) -> None:
            raise gone

        monkeypatch.setattr(watches, "refresh_baselines", lost)
    out = s.write(ref="0x7b8", data_hex="8020")
    assert out["code"] == "session_broken" and ses.broken is not None, out
    assert out["readback"] == "80a0" and out["verified"] is False, out


@pytest.mark.parametrize(("addr", "dump", "said"), [
    (0x300000, "", "no region in the cached address map"),
    (0x7B8, "masked", "masks its addresses"),
], ids=["unbacked", "masked"])
def test_a_rom_write_the_map_cannot_place_names_no_offset(
    addr: int, dump: str, said: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _rom_under_write(monkeypatch, tmp_path)
    ses.rom_write_unmapped.add(addr)
    ses.memory[addr] = bytes.fromhex("80a0")
    if dump:
        masked = M68K_DUAL.replace(_ROM_ENTRY + "mask=0 ", _ROM_ENTRY + "mask=fffff ")
        assert masked != M68K_DUAL, "the anchor matched nothing"
        _cached(monkeypatch, tmp_path, dump=masked)
    out = s.write(ref=f"{addr:#x}", data_hex="8020")
    assert out["target"] == "rom" and "region_offset" not in out and said in out["note"], out


def test_a_write_that_does_not_read_back_on_ram_is_not_explained_as_rom(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`verified: false` off ROM has causes the map cannot tell apart, so nothing is added."""
    ses = _rom_under_write(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "write", lambda addr, data, *, thread: None)
    out = s.write(ref="0x200000", data_hex="8020")
    assert out["verified"] is False and "target" not in out and "note" not in out, out
    assert "map 0x200000::maincpu" in ses.commands, "the map was asked, and said RAM"


def test_a_write_that_reads_back_asks_the_map_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A verified write is not explained: no extra round trip."""
    ses = _rom_under_write(monkeypatch, tmp_path)
    out = s.write(ref="0x200000", data_hex="8020")
    assert out["verified"] is True and "target" not in out, out
    assert not [c for c in ses.commands if c.startswith("map ")], ses.commands


def test_a_watch_stop_with_no_console_line_says_so_instead_of_inventing_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Without the console's line no row can be named, even the one armed here."""
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    s.resume()
    ses.next_packet = "T05watch:0;"
    ses.stops_after_polls = 1
    out = s.stop()
    assert out["interrupted"] is False
    assert out["stopped_on_its_own"]["cause"] == (
        "a watchpoint stopped the machine and the console logged no line for it, so which one "
        "is not known")
    assert "watch_hit" not in mstate.STATE.last_stop


def test_a_watch_stop_by_a_row_this_server_did_not_arm_is_named_as_foreign(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    s.resume()
    (tmp_path / "debug.log").open("a").write(STOP_LINE.replace("watchpoint 1 ", "watchpoint 7 "))
    ses.next_packet = "T05watch:0;"
    ses.stops_after_polls = 1
    out = s.stop()
    assert out["stopped_on_its_own"]["cause"] == (
        "watch 7 at 0x002031fe this server did not arm, wrote 0038 by pc 0x0000040e: "
        "`debug(\"wpclear 0x7\")` removes it")
    assert "watch_hit" not in mstate.STATE.last_stop


def test_the_watchpoint_stop_line_the_doubles_author_is_the_shape_the_console_prints(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Captured (`debuglog.foreign-wp.resume.txt`): holds the authored `STOP_LINE` to the
    printed shape."""
    ses = _watching(monkeypatch, tmp_path)
    (tmp_path / "debug.log").write_text(captured("debuglog.foreign-wp.resume.txt"))
    found = watches.watch_stop(ses, arming.debuglog_since(tmp_path))  # type: ignore[arg-type]
    assert found is not None and found[0] == (
        "watch 1 at 0x002031fc this server did not arm, wrote 00 by pc 0x000025f4: "
        '`debug("wpclear 0x1")` removes it'), found


def test_a_foreign_watch_stop_with_no_packet_is_named_by_its_console_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A `wpset` typed through `debug` stops `run_for`: the log line names it, not the packet.
    A console-started run sends no packet, and a packet naming 0x0 yields to the line."""
    ses = _watching(monkeypatch, tmp_path)
    (tmp_path / "debug.log").write_text(
        "Stopped at watchpoint 1 writing 0003 to 700011 (PC=0009BC74)\n")
    found = watches.watch_stop(ses, arming.debuglog_since(tmp_path))  # type: ignore[arg-type]
    assert found is not None and found[0] == (
        "watch 1 at 0x00700011 this server did not arm, wrote 0003 by pc 0x0009bc74: "
        "`debug(\"wpclear 0x1\")` removes it"), found
    assert mstate.STATE.debuglog_mark > 0, "the log is read at every stop now"
    assert watches.watch_stop(ses, arming.debuglog_since(tmp_path)) is None  # type: ignore[arg-type]
    ses.last_stop_packet = "T05watch:0;"
    with open(tmp_path / "debug.log", "a") as fh:
        fh.write("Stopped at watchpoint 1 writing 0001 to 700011 (PC=000EAB8E)\n")
    found = watches.watch_stop(ses, arming.debuglog_since(tmp_path))  # type: ignore[arg-type]
    assert found is not None and found[0] == (
        "watch 1 at 0x00700011 this server did not arm, wrote 0001 by pc 0x000eab8e: "
        '`debug("wpclear 0x1")` removes it'), found


def test_watch_list_names_every_declaration_and_its_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    s.watch_add(ref="scene_id", mode="show", length=2, fmt="u16")
    listed = s.declaration_list("watch")
    assert [(w["ref"], w["mode"], w["state"]) for w in listed["watches"]] == [
        ("frame_lo", "change", "armed"), ("scene_id", "show", "unresolved")]
    assert listed["watches"][0]["entry"] == "1 @ 2031FC-2031FF write"
    assert listed["watches"][0]["origin"] == "s1" and listed["watches"][0]["created_at"]
    assert "foreign" not in listed
    assert listed["summary"] == "declaration_list watch: 2 watches (1 armed)"
    ses.wplist_rows.append("    7 @ 300000-300003 write")
    assert s.declaration_list("watch")["foreign"] == {"watches": ["7 @ 300000-300003 write"]}
    s.resume()
    listed = s.declaration_list("watch")
    assert listed["session"]["running"] is True and listed["last_stop"]["stop_seq"] == 1
    assert [w["state"] for w in listed["watches"]] == ["armed", "unresolved"]


def test_watch_clear_disarms_what_this_server_armed_and_refuses_an_unknown_ref(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    s.watch_add(ref="scene_id", mode="show", length=2, fmt="u16")
    out = s.declaration_clear("watch", ref="frame_lo")
    assert out["declarations_cleared"] == 1 and out["disarmed"] == ["1 @ 2031FC-2031FF write"]
    assert ses.watchpoints[-1] == (0x2031FC, 4, True) and ses.wplist_rows == []
    assert out["summary"] == "declaration_clear watch frame_lo: 1 cleared, 1 disarmed"
    refused = s.declaration_clear("watch", ref="frame_lo")
    assert refused["status"] == "INVALID" and "'scene_id'" in refused["message"]
    assert " ".join(refused["message"].split()).endswith(
        "`declaration_list(kind=\"watch\")` shows as `ref`. Matching: "
        f"{dec.REF_MATCH['watch']}."), (
        "the refusal names its own family's list and rule")
    assert refused["summary"].startswith("declaration_clear: INVALID")
    assert s.declaration_clear("watch",
                               all=True)["declarations_cleared"] == 1, "no ref clears everything"
    cleared = s.declaration_clear("watch", all=True)
    assert cleared["declarations_cleared"] == 0, "and an empty store's zero is ok"


def test_a_watch_arms_and_clears_while_running_and_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A `Z2` sent to a running machine is taken and fires, like `Z0`."""
    ses = _watching(monkeypatch, tmp_path)
    s.resume()
    out = s.watch_add(ref="frame_lo", mode="change", length=4)
    assert out["armed"] is True and out["while_running"] is True and ses.running
    assert out["index"] == 1, "the debugger's list is read back even while running"
    assert "value" not in out, "no bytes are read off a running machine"
    out = s.declaration_clear("watch", ref="frame_lo")
    assert out["while_running"] is True and ses.running


def test_watch_add_refuses_a_bad_mode_width_or_format_before_the_stub(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    for kwargs, why in (
        ({"mode": "poll", "length": 4}, "mode"),
        ({"mode": "show", "length": 3, "fmt": "u16"}, "whole number"),
        ({"mode": "show", "length": 4, "fmt": "u64"}, "format"),
        ({"mode": "show", "length": 256, "fmt": "u8"}, "128"),
        ({"mode": "change", "length": 0}, "length"),
    ):
        refused(why,
        s.watch_add(ref="frame_lo", **kwargs))
    assert ses.watchpoints == [] and s.declaration_list("watch")["watches"] == []


def test_the_watch_tools_refuse_with_no_machine_unless_the_argument_says_otherwise() -> None:
    """`mode="poll"` is refused even with no machine: the vocabulary is this server's."""
    mstate.STATE.kill()
    bad_vocabulary = s.watch_add(ref="x", mode="poll", length=0)
    assert bad_vocabulary["code"] == "bad_argument", bad_vocabulary
    assert "poll" in bad_vocabulary["message"], bad_vocabulary["message"]
    needs_a_machine: list[Callable[[], dict[str, Any]]] = [
        lambda: s.watch_add(ref="x", mode="show", length=2),
        lambda: s.declaration_list("watch"), lambda: s.declaration_clear("watch", ref="x")]
    for call in needs_a_machine:
        refused("no machine running", call())


def test_the_command_line_carries_the_debug_log() -> None:
    """The console's own line about a watch stop reaches a file only with `-debuglog`."""
    import mame_launch as launch
    cmd = launch.build_command("/bin/mame", "x", "/roms", 1, [], "/scratch/mame-mcp-t")
    assert "-debuglog" in cmd


def test_the_watch_double_numbers_its_rows_as_mame_prints_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """MAME numbers watchpoint rows from a counter that only increments; a clear frees no number."""
    ses = _watching(monkeypatch, tmp_path)
    for i in range(11):
        ses.watchpoint(0x200000 + 4 * i, 4)
    assert ses.wplist_rows[9] == "    A @ 200024-200027 write", ses.wplist_rows[9]
    rows = mlists.parse_wplist(ses.monitor("wplist"))
    assert [r["index"] for r in rows] == list(range(1, 12))
    assert bplist_add(ses, 0x400) == 1, "a watch spends no breakpoint number"
    ses.watchpoint(0x200000, 4, remove=True)
    ses.watchpoint(0x300000, 4)
    assert ses.wplist_rows[-1] == "    C @ 300000-300003 write", ses.wplist_rows
    assert [r["index"] for r in mlists.parse_wplist(ses.monitor("wplist"))][-1] == 0xC


def test_two_stored_watches_of_one_range_in_one_pass_say_sent_and_never_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The second watch of a pass meets a `Z2` sent but not yet read back."""
    ses = _watching(monkeypatch, tmp_path)
    for by, ref in (("symbol", "frame_lo"), ("address", "0x2031fc")):
        arming.store().add(dec.Declaration("watch", by, ref, width=4, fmt="u32",
                                           watch_mode="change", origin="s0",
                                           fingerprint="fp-test"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["frame_lo"], out
    assert "already sent under 'frame_lo' in this pass" in out["unarmable"][0]["why"]


def test_a_stored_change_watch_overlapping_one_sent_in_the_pass_is_unarmable_and_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """At `start` a change watch sharing a byte with one sent in the pass is not armed; it stays
    stored."""
    ses = _watching(monkeypatch, tmp_path)
    for ref, width, fmt in (("frame_lo", 4, "u32"), ("0x2031fe", 2, "u16")):
        arming.store().add(dec.Declaration("watch", "symbol" if ref == "frame_lo" else "address",
                                           ref, width=width, fmt=fmt, watch_mode="change",
                                           origin="s0", fingerprint="fp-test"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["frame_lo"], out
    assert out["unarmable"][0]["ref"] == "0x2031fe", out
    why = out["unarmable"][0]["why"]
    assert why.endswith("under 'frame_lo' in this pass: one watched range is one declaration"), why
    assert [d.ref for d in arming.store().declarations()] == ["frame_lo", "0x2031fe"]


def test_a_pointer_watch_on_a_released_machine_is_refused_for_what_the_flag_says(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`running` is set at every release and cleared only by a read stop: the machine MAY be
    running."""
    ses = _watching(monkeypatch, tmp_path)
    ses.running = True
    out = refused("no stop read since, so it is taken as RUNNING: `stop` it, then `watch_add` "
                  "again",
                  s.watch_add(ref="[frame_lo]+0x4", mode="change", length=2))
    assert out["code"] == "not_stopped" and "machine is RUNNING" not in out["message"]


def test_wplist_rows_are_parsed_from_the_captured_shape() -> None:
    rows = mlists.parse_wplist(WPLIST_ONE)
    assert rows == [{"index": 1, "addr": 0x2031FC, "cpu": ":maincpu", "space": "program",
                     "length": 4, "kind": "write",
                     "enabled": True, "entry": "1 @ 2031FC-2031FF write",
                     "condition": None, "action": None}]
    assert mlists.parse_wplist(WPLIST_NONE) == []
    with pytest.raises(mstate.Invalid, match="wplist"):
        mlists.parse_wplist("Unknown command\n")


CONSOLE = Path(__file__).parent / "fixtures" / "console"


def test_a_conditioned_wplist_row_keeps_its_condition_short_or_wrapped() -> None:
    short = mlists.parse_wplist((CONSOLE / "wplist.cond-short.txt").read_text())
    assert [(r["index"], r["addr"], r["length"], r["kind"], r["condition"], r["entry"])
            for r in short] == [(1, 0x2031FC, 4, "write", "d0==1",
                                 "1 @ 2031FC-2031FF write if d0==1")]
    wrapped = mlists.parse_wplist((CONSOLE / "wplist.cond-wrapped.txt").read_text())
    assert [(r["index"], r["condition"]) for r in wrapped] == [(2, "d0==0x" + "0" * 400 + "1")]


def test_a_wplist_row_with_an_action_keeps_it_as_the_console_prints_it() -> None:
    """Captured action row (`wplist.action.txt`): text after `do`, no condition as `1` prints no
    `if`."""
    assert mlists.parse_wplist((CONSOLE / "wplist.action.txt").read_text()) == [
        {"index": 1, "addr": 0x25A4, "cpu": ":maincpu", "space": "program", "length": 2,
         "kind": "write", "enabled": True, "entry": "1 @ 0025A4-0025A5 write do temp1++ ; g",
         "condition": None, "action": "temp1++ ; g"}]


def test_wplist_with_a_line_it_does_not_recognise_is_refused_naming_it() -> None:
    with pytest.raises(mstate.Invalid, match="Unexpected thing"):
        mlists.parse_wplist("Unexpected thing\n" + WPLIST_ONE)


def test_the_model_refuses_every_malformed_shape_by_name() -> None:
    for kwargs, why in (
        ({"kind": "watch", "by": "index", "ref": "x", "width": 4, "fmt": "u32",
          "watch_mode": "show"}, "`by`"),
        ({"kind": "breakpoint", "by": "symbol", "ref": ""}, "needs a ref"),
        ({"kind": "breakpoint", "by": "address", "ref": "main"}, "`0x` address"),
    ):
        with pytest.raises(dec.DeclarationError, match=why):
            dec.Declaration(**kwargs)
    with pytest.raises(dec.DeclarationError, match="non-integer width"):
        dec.Declaration.from_dict({"kind": "watch", "by": "symbol", "ref": "x", "width": "four",
                                   "fmt": "u32", "watch_mode": "show"})
    with pytest.raises(dec.DeclarationError, match="identity"):
        dec.DeclarationStore("", path=None)
    store = dec.DeclarationStore("k", path=None)
    assert store.persistent is False


def test_a_re_declaration_from_another_session_adopts_it_and_a_raw_address_is_stale() -> None:
    """The stamp travels outside the declaration's equality: a raw address over ANOTHER build
    is stale, a symbol never is."""
    store = dec.DeclarationStore("k", path=None)
    first = dec.Declaration("breakpoint", "address", "0x4a0", created_at="t1", origin="s1",
                            fingerprint="fp1")
    assert store.add(first) is True
    assert first.to_dict() == {"kind": "breakpoint", "by": "address", "ref": "0x4a0",
                               "created_at": "t1", "origin": "s1", "fingerprint": "fp1"}
    assert dec.is_stale(first, "fp2") and not dec.is_stale(first, "fp1")
    assert not dec.is_stale(dec.Declaration("breakpoint", "symbol", "main", origin="s1"), "fp2")
    again = dec.Declaration("breakpoint", "address", "0x4a0", created_at="t2", origin="s2")
    assert store.add(again) is False, "the same declaration, not a second one"
    held = store.declarations()[0]
    assert (held.origin, held.created_at) == ("s2", "t2") and held == first
    stampless = dec.Declaration("breakpoint", "address", "0x4a0")
    assert store.add(stampless) is False
    assert store.declarations()[0].origin == "s2", "a stampless duplicate changes nothing"


def test_watch_add_refuses_a_bad_by_and_the_other_half_of_a_held_watch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    refused("by is one of .*got 'index'",
    s.watch_add(ref="frame_lo", mode="show", length=4, by="index"))
    s.watch_add(ref="frame_lo", mode="show", length=4)
    refused("may not be both",
    s.watch_add(ref="frame_lo", mode="change", length=4))
    assert ses.watchpoints == [], "refused before the stub was touched"


def test_watch_list_and_the_survey_name_the_odd_states(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`state` is where a watch is placed (`gone`, `stale`, `evaluated`, `unresolved`); `reading` is
    what was read (`read`, or `unreadable` with the stub's refusal, never a zero)."""
    ses = _watching(monkeypatch, tmp_path)
    store = arming.store()
    store.add(dec.Declaration("breakpoint", "symbol", "frame_lo", origin="s1"))
    s.watch_add(ref="frame_lo", mode="change", length=4)
    ses.wplist_rows.clear()
    store.add(dec.Declaration("watch", "address", "0x203200", width=2, fmt="u16",
                              watch_mode="change", origin="another"))
    store.add(dec.Declaration("watch", "symbol", "copy_in_rom", width=1, fmt="u8",
                              watch_mode="show", origin="s1"))
    store.add(dec.Declaration("watch", "symbol", "scene_id", width=1, fmt="u8",
                              watch_mode="show", origin="s1"))
    placed = [("frame_lo", "gone"), ("0x203200", "stale"), ("copy_in_rom", "evaluated"),
              ("scene_id", "unresolved")]
    listed = s.declaration_list("watch")["watches"]
    assert [(w["ref"], w["state"]) for w in listed] == placed
    assert "another build" in listed[1]["why"]
    assert listed[2]["reading"]["available"] is True and "value" not in listed[2]

    def refuse(addr: int, n: int, *, thread: int) -> bytes:
        if addr == 0x400:
            raise gs.SessionError("the stub refused `m400,1`: E01")
        return bytes(n)

    monkeypatch.setattr(ses, "read", refuse)
    seen = s.step()["watches"]
    assert [(w["ref"], w["state"]) for w in seen] == placed, "the survey places as the list"
    assert [w.get("reading", {}).get("available") for w in seen] == [True, True, False, None]
    assert "E01" in seen[2]["reading"]["why"] and "value" not in seen[2]["reading"]
    assert not any("value" in w for w in seen), "a value lives in `reading`, never beside it"


def test_a_survey_whose_wplist_fails_places_by_its_own_record_and_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A console that cannot answer `wplist` must not sink the stop's reply: `why` says so."""
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x2031FC] = bytes.fromhex("00000037")
    s.watch_add(ref="frame_lo", mode="change", length=4)
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "wplist":
            raise gs.SessionError("the console's reader died")
        return real(command, timeout)

    monkeypatch.setattr(ses, "monitor", monitor)
    out = s.step()
    assert out["status"] == "ok", out
    (w,) = out["watches"]
    assert w["state"] == "armed" and "reader died" in w["why"], w
    assert w["reading"]["available"] is True, w


def test_a_change_watch_whose_bytes_cannot_be_read_at_arming_is_armed_and_unreadable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A refused read is the watch's `reading` (`unreadable`), never a failed call, with no
    baseline."""
    ses = _watching(monkeypatch, tmp_path)

    def refuse(addr: int, n: int, *, thread: int) -> bytes:
        raise gs.SessionError("the stub refused `m2031fc,4`: E01")

    monkeypatch.setattr(ses, "read", refuse)
    out = s.watch_add(ref="frame_lo", mode="change", length=4)
    assert out["status"] == "ok" and out["state"] == "armed", out
    assert out["reading"]["available"] is False and "E01" in out["reading"]["why"], out
    assert mstate.STATE.armed_watches[("frame_lo", ":maincpu")]["last"] is None


def test_symbols_find_answers_by_name_exact_then_prefix_and_by_address(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`symbols_find`: exact name else prefixes up to `limit`; by `linear`, the nearest symbol
    at or below."""
    _watching(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"IRQ_VBLANK": 0x400, "IRQ_BLITTER": 0x506, "IRQ1_CHAIN": 0x71C,
                                  "MAIN_RAM": 0x00200000, "IRQ": 0x300})
    out = s.symbols_find(name="irq_vblank")
    assert out["query"] == "irq_vblank" and out["symbols_total"] == 1
    assert out["symbols"] == [{"name": "IRQ_VBLANK", "addr": "0x00000400", "memory": "rom"}]
    assert out["summary"] == "symbols_find irq_vblank: 1 match"
    assert "note" not in out, "stopped: the console answered `map`"
    out = s.symbols_find(name="irq")
    assert out["symbols_total"] == 1 and out["symbols"][0]["name"] == "IRQ", "exact beats prefix"
    out = s.symbols_find(name="irq_", limit=2)
    assert out["symbols_total"] == 2 and out["truncated"] is False, "at the limit nothing is cut"
    out = s.symbols_find(name="irq_", limit=1)
    assert out["symbols_total"] == 2 and out["truncated"] is True
    assert [x["name"] for x in out["symbols"]] == ["IRQ_VBLANK"], "by address, the lowest first"
    out = s.symbols_find(name="nothing_like_it")
    assert out["symbols_total"] == 0 and out["symbols"] == []
    out = s.symbols_find(linear="0x50a")
    assert out == {**out, "name": "IRQ_BLITTER", "addr": "0x00000506", "delta": 4}
    assert out["summary"] == "symbols_find 0x0000050a: IRQ_BLITTER + 4"
    out = s.symbols_find(linear="0x506")
    assert out["name"] == "IRQ_BLITTER" and out["delta"] == 0, "a symbol contains its own address"
    out = s.symbols_find(linear="0x2ff")
    assert out["status"] == "INVALID" and out["linear"] == "0x000002ff", "below every symbol"
    refused("one question",
    s.symbols_find(name="x", linear="0x0"))
    refused("one question",
    s.symbols_find())
    refused("limit",
    s.symbols_find(name="x", limit=0))
    assert s.symbols_find(name="x", limit=read.SYMBOLS_LIMIT_MAX)["symbols_total"] == 0
    refused("limit", s.symbols_find(name="x", limit=read.SYMBOLS_LIMIT_MAX + 1))


def test_symbols_find_is_invalid_with_no_table_and_answers_while_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    use_table(monkeypatch, table={})
    out = s.symbols_find(name="x")
    assert out["status"] == "INVALID" and "no symbol" in out["message"]
    use_table(monkeypatch, table={"A": 1})
    s.resume()
    assert ses.running and s.symbols_find(name="a")["symbols_total"] == 1, "a table is not a value"


def test_a_watch_hit_whose_bytes_cannot_be_read_says_so_and_a_short_read_is_unreadable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Fewer bytes than declared are `unreadable` at a stop and `after: None` on a hit, never a
    value."""
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    s.resume()
    ses.memory[0x2031FC] = b"\x00\x01"
    monkeypatch.setattr(ses, "read", lambda addr, n, *, thread: ses.memory.get(addr, bytes(n)))
    (tmp_path / "debug.log").open("a").write(STOP_LINE)
    ses.next_packet = "T05watch:0;"
    ses.stops_after_polls = 1
    s.status()
    hit = mstate.STATE.last_stop["watch_hit"]
    assert hit["after"]["available"] is False and "2 bytes for 4" in hit["after"]["why"]
    seen = s.step()["watches"][0]
    assert seen["state"] == "armed" and seen["reading"]["available"] is False
    assert "2 bytes for 4" in seen["reading"]["why"]
    monkeypatch.setattr(mstate.STATE, "store", None)
    assert rearming.rearm_breakpoints_and_watches(ses) == {  # type: ignore[arg-type]
        "rearmed": [], "stale": [], "unresolved": [], "unarmable": [], "evaluated": []}


def test_a_rearm_never_stacks_a_row_the_debugger_already_holds_and_a_clear_reads_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A listed breakpoint or watch is not armed twice; a show watch declared while running reads
    nothing; a row still held after the `z2` is not `disarmed`."""
    ses = _watching(monkeypatch, tmp_path)
    store = arming.store()
    store.add(dec.Declaration("breakpoint", "symbol", "frame_lo", origin="s1"))
    store.add(dec.Declaration("watch", "symbol", "frame_lo", width=4, fmt="u32",
                              watch_mode="change", origin="s1"))
    ses.bplist_rows.append("    1 @ 2031FC")
    ses.wplist_rows.append("    1 @ 2031FC-2031FF write")
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["frame_lo", "frame_lo"]
    assert ses.armed == [] and ses.watchpoints == []
    s.resume()
    read = s.watch_add(ref="0x203200", mode="show", length=2, fmt="u16")
    assert read["armed"] is False and "value" not in read
    monkeypatch.setattr(ses, "watchpoint", lambda addr, length, remove=False, cpu=None,
                        index=None: None)
    gone = s.declaration_clear("watch", ref="frame_lo")
    assert gone["declarations_cleared"] == 1 and gone["disarmed"] == [], (
        "the row is still listed, so nothing is claimed disarmed")


def test_a_watch_redeclared_under_one_ref_with_another_shape_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The same ref redeclared with another width, format or mode is refused, not stored twice."""
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    refused("already declared.*width 4.*declaration_clear",
    s.watch_add(ref="frame_lo", mode="change", length=8))
    refused("already declared",
    s.watch_add(ref="frame_lo", mode="change", length=4, fmt="i32"))
    assert ses.watchpoints == [(0x2031FC, 4, False)] and len(arming.store().declarations()) == 1
    again = s.watch_add(ref="frame_lo", mode="change", length=4)
    assert again.get("already_stored", False) is True, "the same shape adopts"


def test_two_refs_on_one_address_do_not_share_a_watchpoint_in_silence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Two declarations resolving to one address would share one `Z2`: the second is refused."""
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    refused("already armed under 'frame_lo'",
    s.watch_add(ref="0x2031fc", mode="change", length=4))
    assert len(ses.watchpoints) == 1 and [d.ref for d in arming.store().declarations()] == [
        "frame_lo"]


@pytest.mark.parametrize(("ref", "length"), [("0x2031fe", 2), ("0x2031fa", 4), ("0x2031f8", 16)],
                         ids=["inside", "straddling the start", "around it"])
def test_a_change_watch_sharing_a_byte_with_an_armed_one_is_refused_naming_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ref: str, length: int,
) -> None:
    """A change watch over a byte another arms is refused naming the holder, keeping the writer
    unambiguous."""
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    out = refused("shares a byte with a range already armed under 'frame_lo'",
                  s.watch_add(ref=ref, mode="change", length=length))
    assert out["code"] == "ambiguous_ref", out
    assert len(ses.watchpoints) == 1 and [d.ref for d in arming.store().declarations()] == [
        "frame_lo"]


def test_a_change_watch_beside_an_armed_one_is_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The ranges touch and share no byte: both are armed."""
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    for ref in ("0x2031f8", "0x203200"):
        assert s.watch_add(ref=ref, mode="change", length=4)["status"] == "ok"
    assert len(ses.watchpoints) == 3


def test_watch_clear_keeps_its_record_when_the_stub_refuses_the_removal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)

    def refuse(addr: int, length: int, remove: bool = False, cpu: str | None = None,
        index: int | None = None) -> None:
        raise gs.Refused("the stub refused `z2`: E01")

    monkeypatch.setattr(ses, "watchpoint", refuse)
    out = s.declaration_clear("watch", ref="frame_lo")
    assert out["status"] == "INVALID" and out["code"] == "readback_refused", out
    assert ("frame_lo", ":maincpu") in mstate.STATE.armed_watches, "still armed, still recorded"
    assert [d.ref for d in arming.store().declarations()] == ["frame_lo"]


def test_watch_clear_keeps_its_record_while_the_list_still_shows_the_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The stub took the removal but `wplist` still lists the row: the record stays until the list
    drops it, and the `note` names the row."""
    ses = _watching(monkeypatch, tmp_path)
    ses.wp_next_index = 0x1F
    s.watch_add(ref="frame_lo", mode="change", length=4)

    def taken_but_listed(addr: int, length: int, remove: bool = False, cpu: str | None = None,
        index: int | None = None) -> None:
        ses.watchpoints.append((addr, length, remove))

    monkeypatch.setattr(ses, "watchpoint", taken_but_listed)
    out = s.declaration_clear("watch", ref="frame_lo")
    assert ses.watchpoints[-1] == (0x2031FC, 4, True), "the removal went out"
    assert out["declarations_cleared"] == 1 and out["disarmed"] == []
    assert "1F @ 2031FC-2031FF write" in out["note"] and "still" in out["note"], out
    assert out["note"].endswith('`debug("wpclear 0x1f")` removes the row'), out["note"]
    assert out["summary"] == "declaration_clear watch frame_lo: 1 cleared, 0 disarmed"
    refused("already armed under 'frame_lo'",
            s.watch_add(ref="0x2031fc", mode="change", length=4))
    (tmp_path / "debug.log").open("a").write(STOP_LINE.replace("watchpoint 1 ", "watchpoint 1F "))
    ses.next_packet = "T05watch:0;0e:00000000;11:0000040e;"
    ses.stops_after_polls = 1
    stop = s.resume(seconds=1.0)
    assert stop["status"] == "ok" and stop["cause"].startswith("watch frame_lo"), stop["cause"]
    assert ("cleared" in stop["cause"]
            and "`debug(\"wpclear 0x1f\")`" in stop["cause"]), stop["cause"]
    assert stop.get("watch_hit") is None, "nothing renders a hit whose declaration is gone"
    monkeypatch.setattr(ses, "watchpoint", _WatchSession.watchpoint.__get__(ses))
    ses.wplist_rows.clear()
    s.debug(command="wpclear 1F")
    assert ("frame_lo", ":maincpu") not in mstate.STATE.armed_watches, "forgotten"
    assert s.watch_add(ref="0x2031fc", mode="change", length=4)["armed"] is True


def test_a_change_watch_the_list_does_not_show_after_the_z2_is_refused_with_nothing_stored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A `Z2` taken but not listed is `readback_refused`: nothing stored, the note says what to
    do."""
    ses = _watching(monkeypatch, tmp_path)

    def taken_but_not_listed(addr: int, length: int, remove: bool = False, cpu: str | None = None,
        index: int | None = None) -> None:
        ses.watchpoints.append((addr, length, remove))

    monkeypatch.setattr(ses, "watchpoint", taken_but_not_listed)
    out = s.watch_add(ref="frame_lo", mode="change", length=4)
    assert out["status"] == "INVALID" and out["code"] == "readback_refused", out
    assert (out["ref"], out["addr"]) == ("frame_lo", "0x002031fc")
    assert "nothing is armed" in out["message"]
    assert (out["stored"], out["armed"], out["state"]) == (False, False, "gone"), out
    assert "nothing is stored" in out["note"] and "watch_add" in out["note"], out["note"]
    assert "`debug(\"wplist\")`" in out["note"], out["note"]
    assert arming.store().declarations() == [] and s.declaration_list("watch")["watches"] == []
    ses.running = True
    out = s.watch_add(ref="frame_lo", mode="change", length=4)
    assert out["code"] == "readback_refused" and out["stored"] is False, out
    assert arming.store().declarations() == [], "nothing stored while running either"
    ses.running = False
    monkeypatch.setattr(ses, "watchpoint", _WatchSession.watchpoint.__get__(ses))
    out = s.watch_add(ref="frame_lo", mode="change", length=4)
    assert (out["stored"], out["armed"], out["state"]) == (True, True, "armed"), out


def test_a_disabled_row_is_listed_disabled_and_never_counts_as_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`wpdisable`/`bpdisable` typed through `debug` leave a row with a `D`; read as armed,
    it leaves the watch dead under a green state."""
    rows = mlists.parse_wplist("Device ':maincpu' program space watchpoints:\n"
                               "D   1 @ 2031FC-2031FF write\n\n")
    assert rows[0]["enabled"] is False and rows[0]["entry"] == "D 1 @ 2031FC-2031FF write"
    assert mlists.parse_wplist(WPLIST_ONE)[0]["enabled"] is True
    assert mlists.parse_bplist("Device ':maincpu' breakpoints:\nD   2 @ 000400\n\n")[0][
        "enabled"] is False
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    s.breakpoint_at(ref="0x4a0")
    ses.wplist_rows[0] = "D" + ses.wplist_rows[0][1:]
    ses.bplist_rows[0] = "D" + ses.bplist_rows[0][1:]
    assert s.declaration_list("watch")["watches"][0]["state"] == "disabled"
    assert s.declaration_list("breakpoint")["breakpoints"][0]["state"] == "disabled"
    assert "foreign" not in s.declaration_list("watch")
    assert "foreign" not in s.declaration_list("breakpoint")


def test_the_console_line_is_matched_to_the_firing_watchs_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Another watch's line in the window is not the firing one's; `writer_pc` is the LAST of
    its own."""
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x2031FC] = bytes.fromhex("00000037")
    s.watch_add(ref="frame_lo", mode="change", length=4)
    s.watch_add(ref="0x203200", mode="change", length=2, fmt="u16")
    s.resume()
    (tmp_path / "debug.log").write_text(
        "Stopped at watchpoint 2 writing 0001 to 203200 (PC=0000040A)\n"
        "Stopped at watchpoint 1 writing 0038 to 2031FE (PC=0000040E)\n"
        "Stopped at watchpoint 1 writing 0000 to 2031FC (PC=00000410)\n")
    ses.memory[0x2031FC] = bytes.fromhex("00000038")
    ses.next_packet = "T05watch:2031fc;"
    ses.stops_after_polls = 1
    s.status()
    hit = mstate.STATE.last_stop["watch_hit"]
    assert [w["to"] for w in hit["writes"]] == ["0x002031fe", "0x002031fc"]
    assert hit["writer_pc"] == "0x00000410" and len(hit["lines"]) == 2
    assert mstate.STATE.last_stop["cause"] == "watch frame_lo: 0x002031fc written by pc 0x00000410"


def test_a_write_inside_the_range_names_its_watch_and_a_read_watch_with_no_line_is_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The row is named by the console's line, whichever byte was written; no line, no guess."""
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    s.resume()
    (tmp_path / "debug.log").open("a").write(STOP_LINE)
    ses.next_packet = "T05watch:0;"
    ses.stops_after_polls = 1
    assert s.status()["stopped_on_its_own"]["cause"].startswith("watch frame_lo: 0x002031fc")
    s.resume()
    ses.next_packet = "T05rwatch:0;"
    ses.stops_after_polls = 1
    assert "logged no line for it" in s.status()["stopped_on_its_own"]["cause"]


def test_run_to_names_a_watch_stop_at_its_own_target_as_another_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A change watch stopping at the target's own address is attributed to the watch."""
    import mame_advance as advance
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    monkeypatch.setattr(advance, "RUN_POLL_S", 0.0)
    ses.pcs = [0xF2034, 0x4A0]
    ses.packets = ["T05watch:0;"]
    ses.stop_queue = [1]
    (tmp_path / "debug.log").open("a").write(STOP_LINE)
    real_go = ses.go

    def go() -> None:
        real_go()
        ses.temps[0] = 1

    ses.go = go  # type: ignore[method-assign]
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["verdict"] == "OTHER_STOP" and out["control_hits"] == 1
    assert out["cause"].startswith("watch frame_lo") and out["pc"] == "0x000004a0"


def test_a_run_cut_by_a_watch_before_the_control_fired_does_not_call_the_control_cold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A watch stopping the run before the control had its chance is named a cut, not
    `control_silent`."""
    import mame_advance as advance
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    monkeypatch.setattr(advance, "RUN_POLL_S", 0.0)
    ses.pcs = [0xF2034, 0x1000]
    ses.packets = ["T05watch:0;"]
    ses.stop_queue = [1]
    (tmp_path / "debug.log").open("a").write(STOP_LINE)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["status"] == "INVALID" and out["code"] == "cut_by_other_stop", out
    assert out["cause"].startswith("watch frame_lo") and out["control_hits"] == 0
    assert "control_dasm" not in out and "disarm_watches" in out["message"]


def test_a_watch_row_is_matched_by_address_and_length_and_by_is_honoured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    held = [{"index": 1, "addr": 0x2031FC, "length": 2, "entry": "x", "enabled": True,
             "cpu": ":maincpu"}]
    assert mlists.adoptable_row(held, 0x2031FC, ":maincpu", set(), 4) is None
    assert mlists.adoptable_row(held, 0x2031FC, ":maincpu", set(), 2) is not None
    ses = _watching(monkeypatch, tmp_path)
    refused("`0x` address",
    s.watch_add(ref="frame_lo", mode="show", length=4, by="address"))
    forced = s.breakpoint_at(ref="beef", by="symbol")
    assert forced["by"] == "symbol" and forced["state"] == "unresolved"
    assert ses.armed == [], "a name forced as a symbol is not read as the address 0xbeef"


def test_a_stop_at_a_watch_reads_the_bytes_once_and_the_log_at_every_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The log is read at every stop: a watchpoint typed through `debug` is not a `gvblank`
    landing."""
    ses = _watching(monkeypatch, tmp_path)
    (tmp_path / "debug.log").write_text("boot noise\n" * 3, newline="")
    s.step()
    assert mstate.STATE.debuglog_mark == len("boot noise\n") * 3, "read at the first stop"
    ses.memory[0x2031FC] = bytes.fromhex("00000037")
    s.watch_add(ref="frame_lo", mode="change", length=4)
    reads: list[tuple[int, int]] = []
    real = ses.read

    def counting(addr: int, n: int, *, thread: int) -> bytes:
        reads.append((addr, n))
        return real(addr, n, thread=thread)

    monkeypatch.setattr(ses, "read", counting)
    s.resume()
    (tmp_path / "debug.log").open("a").write(STOP_LINE)
    ses.next_packet = "T05watch:2031fc;"
    ses.stops_after_polls = 1
    out = s.stop()
    assert reads.count((0x2031FC, 4)) == 1, "one read serves `after` and the evaluation"
    assert out["stopped_on_its_own"]["cause"].endswith("written by pc 0x0000040e")


def test_watch_add_adopting_a_disabled_row_reports_it_disabled_and_so_does_the_rearm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A row already listed at the range is adopted without a second `Z2`, and `armed` follows
    the row's `enabled` as the breakpoint twin does, at declaration and at the re-arm."""
    ses = _watching(monkeypatch, tmp_path)
    ses.wplist_rows.append("D   1 @ 2031FC-2031FF write")
    out = s.watch_add(ref="frame_lo", mode="change", length=4)
    assert out["armed"] is False and out["state"] == "disabled", out
    assert out["entry"] == "D 1 @ 2031FC-2031FF write" and ses.watchpoints == []
    mstate.STATE.armed_watches.clear()
    account = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(account["rearmed"]) == ["frame_lo"] and account["unarmable"] == [], account
    assert account["rearmed"][0]["state"] == "disabled", account
    assert 'debug("wpenable 0x1")' in account["rearmed"][0]["note"]


def test_a_pass_can_hold_the_armed_watches_and_gets_them_back_renumbered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`disarm_watches` disarms every armed change watch for one pass and re-arms after it,
    reading the rows back; a re-armed row takes the next index, which a stop's log line matches."""
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    s.watch_add(ref="0x202e86", mode="show", length=2, fmt="u16")
    before = dict(mstate.STATE.armed_watches[("frame_lo", ":maincpu")])
    ses.watchpoints.clear()

    def run() -> dict[str, Any]:
        assert ses.wplist_rows == [], "the watch was still armed during the pass"
        return {"verdict": "ELAPSED"}

    out = advance._with_watches_disarmed(ses, True, run)  # type: ignore[arg-type]
    assert out["disarmed_watches"] == [{"ref": "frame_lo", "cpu": ":maincpu"}]
    assert "not_rearmed" not in out
    assert ses.watchpoints == [(0x2031FC, 4, True), (0x2031FC, 4, False)]
    after = mstate.STATE.armed_watches[("frame_lo", ":maincpu")]
    assert after["addr"] == before["addr"] and after["enabled"] is True
    assert after["index"] == before["index"] + 1 and "2031FC" in after["entry"]
    ses.watchpoints.clear()
    real = ses.watchpoint

    def refusing(addr: int, length: int, remove: bool = False, cpu: str | None = None,
        index: int | None = None, cond: str = "") -> None:
        if not remove:
            return
        real(addr, length, remove, cpu, index, cond)

    ses.watchpoint = refusing  # type: ignore[method-assign]
    out = advance._with_watches_disarmed(ses, True, lambda: {"verdict": "ELAPSED"})  # type: ignore[arg-type]
    assert out["not_rearmed"] == [{"ref": "frame_lo", "cpu": ":maincpu"}]
    assert mstate.STATE.armed_watches[("frame_lo", ":maincpu")]["enabled"] is False
    plain = advance._with_watches_disarmed(ses, False, lambda: {"verdict": "ELAPSED"})  # type: ignore[arg-type]
    assert plain == {"verdict": "ELAPSED"}


def test_the_write_side_is_read_past_an_armed_watchpoints_annotation() -> None:
    """`map` annotates the write side of an address carrying a watchpoint (`-> (wp@91d0) handler`);
    the handler is the rest of the line."""
    from types import SimpleNamespace
    lines = {
        0x91D0: ("   Read: 091D0 logical program == 091D0 physical program -> (wp@91d0) "
                 "twins_state::access_w\n  Write: 091D0 logical program == 091D0 physical "
                 "program -> (wp@91d0) twins_state::access_w\n"),
        0x2000: MAP_RAM, 0x400: MAP_ROM,
    }
    ses = SimpleNamespace(monitor=lambda cmd, timeout=10.0: lines[int(cmd.split()[1], 16)])
    assert mmap.write_side(ses, 0x91D0) == (  # type: ignore[arg-type]
        None, "twins_state::access_w", "twins_state::access_w")
    assert mmap.write_side(ses, 0x2000) == (None, "memory@200000", "memory@200000")  # type: ignore[arg-type]
    assert mmap.write_side(ses, 0x400) == (None, "unmapped", "memory@0")  # type: ignore[arg-type]
    refused, _write, _read = mmap.change_watch_side(ses, 0x400)  # type: ignore[arg-type]
    assert refused is not None and refused[0] == "bad_argument" and "unmapped" in refused[1]
    assert 'mode=\"count\"' in refused[1], "the refusal names the tap that does see the writes"


def test_watch_add_picks_a_format_that_fits_the_width_when_none_is_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """With no `fmt` the server picks the widest unsigned format the width divides; an explicit
    `fmt` that does not fit is still refused."""
    ses = _watching(monkeypatch, tmp_path)
    two = s.watch_add(ref="frame_lo", mode="show", length=2)
    assert two["status"] == "ok" and two["fmt"] == "u16", two
    one = s.watch_add(ref="copy_in_rom", mode="show", length=1)
    assert one["status"] == "ok" and one["fmt"] == "u8", one
    assert ses is not None


def test_a_stop_from_a_watch_re_armed_from_a_prior_session_says_it_was_a_leftover(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A change watch re-armed from an earlier session says so in its stop: `rearmed: true` in
    `watch_hit` and in the `cause`."""
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x2031FC] = bytes.fromhex("00000037")
    s.watch_add(ref="frame_lo", mode="change", length=4)
    # Make it a prior session's leftover: the store keeps the original origin.
    monkeypatch.setattr(mstate.STATE, "session_origin", "a_later_session")
    (tmp_path / "debug.log").write_text(STOP_LINE + "25F6\n")
    ses.memory[0x2031FC] = bytes.fromhex("00000038")
    ses.last_stop_packet = "T05watch:2031fc;"
    found = watches.watch_stop(ses, arming.debuglog_since(tmp_path))  # type: ignore[arg-type]
    assert found is not None
    how, hit, _fresh = found
    assert hit is not None and hit["rearmed"] is True, hit
    assert "re-armed" in how, how


def _frame_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ticks: bool, writes: bool,
               stale: str = "") -> tuple[dict[str, Any], list[str], list[int]]:
    """`run_for(frames=3)` over a change watch on `frame_lo`, each `gvblank` intercepted:
    `ticks` moves the counter, `writes` fires the watch in the first, `stale` is surveyed log."""
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x2031FC] = bytes.fromhex("00000037")
    s.watch_add(ref="frame_lo", mode="change", length=4)
    log = tmp_path / "debug.log"
    log.write_text("F2034\n" + stale)
    monkeypatch.setattr(mstate.STATE, "debuglog_mark", log.stat().st_size)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    ses.last_stop_packet = ""
    sent: list[str] = []
    surveyed: list[int] = []
    real, real_survey = ses.monitor, running.survey

    def console(command: str, timeout: float = 10.0) -> str:
        if command == "gvblank":
            sent.append(command)
            ses.frame += int(ticks)
            if writes and len(sent) == 1:
                with log.open("a") as fh:
                    fh.write(STOP_LINE + "25F6\n")
                ses.memory[0x2031FC] = bytes.fromhex("00000038")
            return ""
        return real(command, timeout)

    def survey(ses_: Any, scratch: Path) -> dict[str, Any]:
        surveyed.append(len(sent))
        return real_survey(ses_, scratch)

    ses.monitor = console  # type: ignore[method-assign]
    monkeypatch.setattr(running, "survey", survey)
    return s.run_for(frames=3), sent, surveyed


def test_a_frame_run_cut_by_a_watch_between_two_vblanks_is_a_stop_and_sends_nothing_after(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A change watch firing before the vblank leaves the counter unticked (the tell): the stop is
    named from the log and no `gvblank` follows."""
    out, sent, _ = _frame_run(monkeypatch, tmp_path, ticks=False, writes=True)
    assert out["status"] == "ok" and out["verdict"] == "OTHER_STOP", out
    assert out["cause"] == "watch frame_lo: 0x002031fc written by pc 0x0000040e", out["cause"]
    assert out["watch_hit"]["after"] == 0x38 and out["frame_before"] == out["frame_after"]
    assert sent == ["gvblank"], sent


def test_a_frame_run_cut_by_a_watch_that_lands_with_the_tick_is_a_stop_and_sends_nothing_after(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The watch fires in a frame whose tick was taken: only the console's line says it is a
    stop."""
    out, sent, surveyed = _frame_run(monkeypatch, tmp_path, ticks=True, writes=True)
    assert out["status"] == "ok" and out["verdict"] == "OTHER_STOP", out
    assert out["cause"] == "watch frame_lo: 0x002031fc written by pc 0x0000040e", out["cause"]
    assert out["frame_after"] == out["frame_before"] + 1, out
    assert sent == ["gvblank"] and surveyed == [1], (sent, surveyed)


@pytest.mark.parametrize("stale", ["", STOP_LINE + "25F6\n"])
def test_a_frame_run_whose_landings_all_tick_with_no_new_stop_line_surveys_only_its_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stale: str,
) -> None:
    """Control: every landing ticks and no stop line is logged, so the run is ELAPSED, surveyed
    once."""
    out, sent, surveyed = _frame_run(monkeypatch, tmp_path, ticks=True, writes=False, stale=stale)
    assert out["status"] == "ok" and out["verdict"] == "ELAPSED", out
    assert sent == ["gvblank"] * 3 and surveyed == [3], (sent, surveyed)


@pytest.mark.parametrize(("line", "stop"), [
    (STOP_LINE, True),
    ("Stopped at watchpoint 2 writing 03 to 042C\n", True),
    ("Stopped at breakpoint 3\n", True),
    ("Stopped at registerpoint 1\n", True),
    ("Stopped at VBLANK\n", False),
    ("Watchpoint 1 set\n", False),
    ("F2034\n", False),
])
def test_the_stop_lines_a_frame_run_looks_for(line: str, stop: bool) -> None:
    """Every family the survey names off the log, and the console's other lines, which are not
    a stop somebody armed."""
    assert running.stop_logged_in(["D682\n", line]) is stop


def test_a_watch_hit_lists_at_most_the_shared_ceiling_of_writes_and_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A latch written many times a frame is capped at the list ceiling, keeping the LAST writes."""
    from mame_read import LOG_LIMIT_MAX
    assert watches.WRITES_MAX == LOG_LIMIT_MAX, "one ceiling for every list this server hands back"
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x2031FC] = bytes.fromhex("00000037")
    s.watch_add(ref="frame_lo", mode="change", length=4)
    s.resume()
    (tmp_path / "debug.log").write_text("".join(
        f"Stopped at watchpoint 1 writing {i:04X} to 2031FE (PC={0x400 + i:08X})\n"
        for i in range(LOG_LIMIT_MAX + 1)))
    ses.memory[0x2031FC] = bytes.fromhex("00000038")
    ses.next_packet = "T05watch:2031fc;"
    ses.stops_after_polls = 1
    s.status()
    hit = mstate.STATE.last_stop["watch_hit"]
    assert len(hit["writes"]) == LOG_LIMIT_MAX and hit["writes_total"] == LOG_LIMIT_MAX + 1
    assert hit["truncated"] is True and hit["writes"][-1]["wrote"] == f"0x{LOG_LIMIT_MAX:04x}"
    assert hit["writer_pc"] == f"{0x400 + LOG_LIMIT_MAX:#010x}"


def test_symbols_find_says_whether_each_symbol_is_live_ram_or_its_rom_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A symbol's `memory` kind comes from the console's `map` when stopped; `unknown` while
    running."""
    ses = _watching(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"IRQ_VBLANK": 0x400, "MAIN_RAM": 0x00200000,
                                  "SOUND_LATCH": 0x00740000})
    ses.latches.add(0x740000)
    assert mmap.memory_kind(ses, 0x400) == "rom"  # type: ignore[arg-type]
    # Captured shape with paired handler names; no fleet board has one, so authored from it.
    paired = MAP_LATCH.replace("-> unmapped\n", "-> m68k_dual_state::latch_r\n", 1)
    real_monitor = ses.monitor
    monkeypatch.setattr(ses, "monitor", lambda command, timeout=10.0:
                        paired if command == "map 0x740004" else real_monitor(command, timeout))
    assert mmap.memory_kind(ses, 0x00740004) == "handlers"  # type: ignore[arg-type]
    assert mmap.memory_kind(ses, 0x00200000) == "ram"  # type: ignore[arg-type]
    assert mmap.memory_kind(ses, 0x00740000) == "latch"  # type: ignore[arg-type]
    out = s.symbols_find(name="main_ram")
    assert out["symbols"] == [{"name": "MAIN_RAM", "addr": "0x00200000", "memory": "ram"}], out
    out = s.symbols_find(name="irq_vblank")
    assert out["symbols"][0]["memory"] == "rom"
    out = s.symbols_find(linear="0x740002")
    assert out["name"] == "SOUND_LATCH" and out["memory"] == "latch"
    ses.running = True
    out = s.symbols_find(name="main_ram")
    assert out["symbols"][0]["memory"] == "unknown" and "running" in out["note"], out


def test_memory_kind_is_unknown_when_the_console_names_no_side(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "monitor", lambda command, timeout=10.0: "no such address\n")
    assert mmap.memory_kind(ses, 0x999999) == "unknown"  # type: ignore[arg-type]


def test_drive_waits_for_the_expectation_only_while_the_machine_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A run left RUNNING waits up to `seconds` for the expectation: a landing line is seen, none is
    `wait_expired`, a stop ends the wait with one log read, a bad regex is refused as it is."""
    import threading
    ses = _watching(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "breakpoints", bp_records((1, "SOMEWHERE", 0x500)))
    log = tmp_path / "error.log"
    threading.Timer(0.3, lambda: log.open("a").write("[driver] RE_DAC start=1\n")).start()
    out = s.drive(act=[{"op": "resume", "seconds": 0}], expect="RE_DAC start", seconds=3,
                  pattern="RE_DAC")
    assert out["status"] == "ok" and out["verify"]["seen"] is True, out
    assert out["verify"]["waited_s"] > 0 and out["looked"]["emulator"]["lines_total"] == 1, out
    assert out["act"]["still_running"] is True and "the wait" in out["act"]["note"], out["act"]
    out = s.drive(act=[{"op": "status"}], expect="never", seconds=0.3)
    assert out["status"] == "ok" and out["verify"]["verdict"] == "TIMEOUT", out
    assert "still running" in out["verify"]["why"], out
    threading.Timer(0.3, lambda: setattr(ses, "stops_after_polls", 1)).start()
    out = s.drive(act=[{"op": "status"}], expect="never", seconds=3)
    assert out["status"] == "INVALID" and "STOPPED" in out["verify"]["why"], out
    assert out["verify"]["waited_s"] < 2
    assert "does not compile" in s.drive(act=[{"op": "status"}], pattern="(")["message"]


def test_watch_add_replies_say_stored_armed_and_state_for_every_placement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    unresolved = s.watch_add(ref="scene_id", mode="show", length=2)
    assert (unresolved["stored"], unresolved.get("already_stored", False), unresolved["armed"]) == (
        True, False, False), unresolved
    assert unresolved["state"] == "unresolved" and "not a symbol in this build" in (
        unresolved["note"]), unresolved
    assert s.watch_add(ref="scene_id", mode="show", length=2)["already_stored"] is True
    read = s.watch_add(ref="frame_lo", mode="show", length=4)
    assert (read["stored"], read.get("already_stored", False), read["state"]) == (
        True, False, "evaluated")
    s.watch_add(ref="0x2031fc", mode="change", length=4)
    again = s.watch_add(ref="0x2031FC", mode="change", length=4)
    assert again["ref"] == "0x2031fc" and again.get("already_stored", False) is True, again
    assert len([d for d in arming.store().declarations() if d.kind == "watch"]) == 3
    out = refused("unmapped", s.watch_add(ref="copy_in_rom", mode="change", length=2))
    assert (out["code"], out["ref"], out["addr"]) == ("bad_argument", "copy_in_rom", "0x00000400")
    out = refused("by is one of",
                  s.watch_add(ref="0x203200", mode="change", length=2, by="expr"))
    assert out["code"] == "bad_argument" and ses.watchpoints == [(0x2031FC, 4, False)]


def test_a_survey_evaluates_every_declaration_after_an_unresolved_or_a_bus_watch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Rows a survey skips (unresolved, bus-sourced) must not end it; the bus row carries its
    reading."""
    ses = _watching(monkeypatch, tmp_path)
    ses.latches.add(0x740000)
    s.watch_add(ref="scene_id", mode="show", length=2)
    s.watch_add(ref="0x740000", mode="change", length=2)
    s.watch_add(ref="frame_lo", mode="show", length=4)
    rows = s.step()["watches"]
    assert [(r["ref"], r["state"]) for r in rows] == [
        ("scene_id", "unresolved"), ("0x740000", "armed"), ("frame_lo", "evaluated")], rows
    assert rows[1]["reading"]["state"] == "bus", rows[1]
    listed = s.declaration_list("watch")["watches"]
    assert listed[1]["addr"] == "0x00740000", "where it is, the list says"


def test_a_survey_that_cannot_read_wplist_places_by_its_record_and_says_gone_without_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    arming.store().add(dec.Declaration("watch", "address", "0x203200", width=2, fmt="u16",
                                       watch_mode="change", origin="s1"))
    real = ses.monitor

    def no_list(command: str, timeout: float = 10.0) -> str:
        if command == "wplist":
            raise gs.SessionError("the console answered nothing for `wplist`")
        return real(command, timeout)

    ses.monitor = no_list  # type: ignore[method-assign]
    rows = {w["ref"]: w for w in s.step()["watches"]}
    assert rows["frame_lo"]["state"] == "armed" and "could not be read" in rows["frame_lo"]["why"]
    assert rows["0x203200"]["state"] == "gone" and "could not be read" in rows["0x203200"]["why"]


def test_memory_kind_reads_both_sides_of_the_map_answer() -> None:
    """Address kind from `map`: a missing side `unknown`, both unmapped `unmapped`, write only
    `rom`, read only `latch`, same memory `ram`, same handler `handlers`."""
    from types import SimpleNamespace
    both_handlers = ("   Read: 091D0 logical program == 091D0 physical program -> "
                     "twins_state::access_w\n  Write: 091D0 logical program == 091D0 physical "
                     "program -> twins_state::access_w\n")
    lines = {0x2000: MAP_RAM, 0x400: MAP_ROM, 0x740000: MAP_LATCH, 0x91D0: both_handlers,
             0x1: "   Read: 000001 logical program == 000001 physical program -> memory@0\n",
             0x2: ("   Read: 000002 logical program == 000002 physical program -> unmapped\n"
                   "  Write: 000002 logical program == 000002 physical program -> unmapped\n")}
    ses = SimpleNamespace(monitor=lambda cmd, timeout=10.0: lines[int(cmd.split()[1], 16)])
    assert [mmap.memory_kind(ses, a) for a in (0x2000, 0x400, 0x740000, 0x91D0, 0x1, 0x2)] == [  # type: ignore[arg-type]
        "ram", "rom", "latch", "handlers", "unknown", "unmapped"]


def test_a_pass_re_arms_each_watch_by_its_own_range_and_refreshes_its_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """After a pass the stub renumbers rows: each record takes the new index of the row at ITS
    range."""
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    s.watch_add(ref="0x203200", mode="change", length=2)
    refs = watches.disarm_for_pass(ses)  # type: ignore[arg-type]
    assert refs == [("frame_lo", ":maincpu"), ("0x203200", ":maincpu")] and ses.wplist_rows == []
    real = ses.watchpoint

    def lose_the_first(addr: int, length: int, remove: bool = False, cpu: str | None = None,
        index: int | None = None) -> None:
        if addr == 0x2031FC:
            wplist_add(ses, addr, 2)
            return
        real(addr, length, remove, cpu, index)

    monkeypatch.setattr(ses, "watchpoint", lose_the_first)
    assert watches.rearm_after_pass(ses, refs) == [("0x203200", ":maincpu")]  # type: ignore[arg-type]
    listed = {w["ref"]: w for w in s.declaration_list("watch")["watches"]}
    assert listed["frame_lo"]["state"] == "gone", listed["frame_lo"]
    assert listed["0x203200"]["state"] == "armed", listed["0x203200"]
    assert listed["0x203200"]["entry"] == "4 @ 203200-203201 write", "the row numbered afresh"
    assert s.declaration_clear("watch", ref="0x203200")["disarmed"] == ["4 @ 203200-203201 write"]


def test_the_console_log_is_read_from_the_first_arm_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A log line from before anything was armed is nobody's: the mark is taken at the first arm."""
    ses = _watching(monkeypatch, tmp_path)
    (tmp_path / "debug.log").write_text("F2034\n" + STOP_LINE + "25F6\n")
    s.watch_add(ref="frame_lo", mode="change", length=4)
    assert arming.debuglog_since(tmp_path) == [], "nothing before the first arm is a watch's"
    (tmp_path / "debug.log").open("a").write(STOP_LINE + "25F6\n")
    s.watch_add(ref="0x203200", mode="change", length=2)
    assert arming.debuglog_since(tmp_path) == [STOP_LINE.strip(), "25F6"], (
        "a second arm does not move the mark past a line already logged")
    assert ses.wplist_rows, "both armed"


def test_a_write_by_another_cpu_is_named_without_a_writer_pc() -> None:
    """`watchpoint::hit` prints `(PC=...)` only for the watch's own cpu; the bare line is still
    its."""
    bare = "Stopped at watchpoint 1 writing 0025 to 002031FC"
    own = bare + " (PC=0004A0)"
    for line, pc in ((bare, None), (own, "0x000004a0")):
        m = watches._STOP_LINE.search(line)
        assert m is not None and watches._writer(m) == pc, line
    found = watches._STOP_LINE.search(bare)
    assert found is not None and "another cpu or device" in watches._foreign_cause(found)


@pytest.mark.parametrize(("space", "read_side", "says"), [
    ("program", "memory@0", "reads as memory, the ROM copy"),
    ("program", "x_state::status_r", None), ("program", "unmapped", None),
    ("program", None, None), ("io", "memory@0", None),
])
def test_the_unmapped_note_points_at_the_live_datum_only_where_the_address_reads_as_memory(
    space: str, read_side: str | None, says: str | None,
) -> None:
    """A read handler is a register, not a datum's ROM copy; nothing read copies nothing; a port
    has none."""
    note = mmap.unmapped_note(0x400, space, read_side)
    assert "the tap still sees every one the cpu makes" in note
    assert ("ROM" in note) == (says is not None) and (says is None or says in note), note


def test_a_tap_on_a_mapped_side_keeps_its_note_untouched() -> None:
    assert mmap.with_unmapped_note("installed", "memory@200000", 0x2, "program",
                                   "memory@200000", trigger=True) == "installed"
    assert mmap.with_unmapped_note("installed", "unmapped", 0x2, "io", None, trigger=True
                                      ).startswith("installed; the trigger: nothing")


def test_a_stop_keeps_a_taps_count_and_its_alarms_while_they_hold_and_names_the_rest() -> None:
    tally = {"ref": "0x20351c", "by": "address", "cpu": ":maincpu", "mode": "count",
             "length": 1, "fmt": "u8", "tally_id": "t1", "addr": "0x0020351c",
             "installed": True, "pending": False, "install_resent": 0, "state": "tallied",
             "frame_as_of": 9, "superseded": False, "total": 12, "since_last_stop": 3,
             "values": [{"value": 1}], "writers": [{"pc": "0x40e"}], "values_total": 1,
             "overflow_values": 0, "writers_total": 1, "overflow_pcs": 0,
             "callback_errors": {"count": 0}}
    rows, left = watches.at_stop([tally, {**tally, "ref": "b", "superseded": True,
                                          "install_resent": 1, "reset": True,
                                          "across": {"from": "s"}, "why": "older"}])
    assert rows[0] == {"ref": "0x20351c", "cpu": ":maincpu", "state": "tallied", "total": 12,
                       "since_last_stop": 3, "callback_errors": {"count": 0}}
    assert {k: rows[1][k] for k in ("superseded", "install_resent", "reset", "across", "why")} \
        == {"superseded": True, "install_resent": 1, "reset": True, "across": {"from": "s"},
            "why": "older"}
    assert "values" in left and "writers" in left and "frame_as_of" in left
    assert "total" not in left and "superseded" in left, "named where it was left out"
    # A tap whose state could not be read is an alarm: kept on the row, not folded away.
    unread = {"available": False, "why": "the console did not answer"}
    rows, _ = watches.at_stop([{**tally, "installed": False}, {**tally, "installed": unread}])
    assert rows[0]["installed"] is False and rows[1]["installed"] == unread, rows


def test_a_pass_places_a_row_again_with_only_what_a_stop_shows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    placed = {"state": "armed", "entry": "2 @ 0x2031fc", "index": 2, "addr": "0x002031fc"}
    monkeypatch.setattr(watches, "_placement", lambda held, decl, addr: dict(placed))
    monkeypatch.setattr(watches, "_wplist_or_error", lambda ses: [])
    decl = type("D", (), {"ref": "frame_lo", "cpu": ":maincpu", "kind": "watch",
                          "watch_mode": "change", "owner": ("frame_lo", ":maincpu")})()
    monkeypatch.setattr(arming, "store",
                        lambda: type("S", (), {"declarations": lambda self: [decl]})())
    monkeypatch.setitem(mstate.STATE.armed_watches, decl.owner, {"addr": 0x2031FC})
    rows = [{"ref": "frame_lo", "cpu": ":maincpu", "state": "gone"}]
    watches.place_after_pass(cast(Any, None), rows, [decl.owner])
    assert rows == [{"ref": "frame_lo", "cpu": ":maincpu", "state": "armed"}]
