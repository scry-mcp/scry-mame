"""End-to-end check of the renamed MCP server against a real MAME.

The unit tests never touch the wire. This drives the actual code path: start a machine, verify
it against the ROM on disk, read memory by symbol, run to a target with a control breakpoint,
and prove the honesty guarantees still fire after the rename.
"""

import tempfile
import time
import wave
from pathlib import Path
from typing import Any

from bench_boards import MANIFEST, REFERENCE_ROM, SYMBOLS, radendur_missing
from live_harness import (
    BOOT,
    check,
    finish,
    ignored_of,
    invalid,
    isolate_state,
    rearm_pairs,
    visible_of,
)

from gfx_layouts import BYTES_8X8  # isort: skip -- beside the harness

import mame_clear as mclear  # isort: skip
import mame_lists as mlists  # isort: skip
import mame_machine as machine  # isort: skip
import server as s  # isort: skip

#   uv run python tests/live/live_check.py
# Every check here is on radendur, so a bench without its copies leaves nothing to examine.
if why := radendur_missing():
    invalid(why)
isolate_state("mame-live-check-state-")

print("== start(): the machine must come up and prove itself against the ROM")
r = s.start(**BOOT, symbols=SYMBOLS)
check("rom_check is OK", r.get("rom_check") == "OK", str(r.get("rom_check")))
check("symbols loaded (not zero)", r.get("symbols_total", 0) > 0,
      f"{r.get('symbols_total')} symbols")
check("altered is False on a fresh session", r["session"].get("altered") is False)
check("english keys",
      {"system", "stub_port", "rom_check", "symbols_total", "registers", "pc"} <= set(r))

print("\n== status()")
st = s.status()
check("alive", st.get("alive") is True)

print("\n== read_memory(): by symbol and by hex address, and they must agree")
by_symbol = s.read_memory(ref="irq_vblank", length=8)
by_hex = s.read_memory(ref="0x400", length=8)
check("symbol resolves", by_symbol.get("addr") == "0x00000400", str(by_symbol.get("addr")))
check("same bytes either way", by_symbol.get("hex") == by_hex.get("hex"), str(by_symbol.get("hex")))

print("\n== read_block(): a region by tag and by address, held equal to the protocol read")
r = s.read_block(tag="maincpu", offset=0x400, length=8)
check("the ROM region is read by its bare tag and answered under its full one",
      r.get("status") == "ok" and r.get("kind") == "region" and r.get("tag") == ":maincpu",
      f"{r.get('kind')} {r.get('tag')} size={r.get('size')} ({r.get('code', '')})")
check("the region's bytes at 0x400 are what the protocol reads at address 0x400",
      r.get("hex") == by_hex.get("hex"), f"{r.get('hex')} vs {by_hex.get('hex')}")
check("and it alters nothing", r.get("session", {}).get("altered") is False)
r = s.read_block(ref="0x400", length=8)
check("by address: the map entry names the region and the offset is the address's distance",
      r.get("status") == "ok" and r.get("tag") == ":maincpu" and r.get("offset") == 0x400
      and r.get("hex") == by_symbol.get("hex"),
      f"{r.get('tag')} offset={r.get('offset')} ({r.get('code', '')})")
r = s.read_block(tag="no-such-block")
check("a tag the machine lacks is unknown_ref naming what it has",
      r.get("code") == "unknown_ref" and ":maincpu" in (r.get("tags") or {}), str(r.get("tags")))
size = int(s.read_block(tag="maincpu", length=1).get("size") or 0)
r = s.read_block(tag="maincpu", offset=size - 4, length=8)
check("a read past the block's end is refused, not answered as zeros",
      r.get("code") == "bad_argument" and "past the end" in str(r.get("message")),
      str(r.get("message"))[:60])
r = s.read_block(tag="maincpu", offset=size - 8, length=8)
check("a read that ends exactly at the block's end is answered (the boundary is inclusive)",
      r.get("status") == "ok" and r.get("offset") == size - 8 and len(r.get("hex", "")) == 16,
      f"offset={r.get('offset')} of {size} ({r.get('code', '')})")
last = s.read_block(ref=f"{size - 1:#x}", length=1)
check("the last address of the ROM entry is inside it, at the block's last byte",
      last.get("status") == "ok" and last.get("tag") == ":maincpu"
      and last.get("offset") == size - 1 and last.get("hex") == r.get("hex", "")[-2:],
      f"offset={last.get('offset')} ({last.get('code', '')}: {str(last.get('message', ''))[:60]})")

print("\n== machine_map(): what the board IS, from the cache start built")
mm = s.machine_map()
cpus = {c.get("cpu"): c for c in mm.get("cpus", [])}
check("both 68000s are there, with distinct tags",
      mm.get("status") == "ok" and sorted(cpus) == [":maincpu", ":subcpu"], str(sorted(cpus)))
check("each cpu carries the clock only -listxml knows and the spaces only the machine knows",
      all(c.get("clock_hz") == 16_000_000 and c.get("spaces") == ["cpu_space", "program"]
          for c in cpus.values()),
      str([(t, c.get("clock_hz"), c.get("spaces")) for t, c in cpus.items()]))
# THE DENOMINATOR IS THE REPLY'S OWN SECTIONS. Three keys named by hand is a check that can
# only fail on the three somebody thought of, and the section it did not name was the one with
# no source at all; `counts` is what the reply says its sections are.
missing = sorted(set(mm.get("counts", {})) - set(mm.get("sources", {})))
check("every section the reply carries names the source that backs it",
      bool(mm.get("counts")) and not missing, f"no source for {missing}")
check("and the three channels are each named on a section they alone back",
      mm.get("sources", {}).get("cpus") == ["live", "-listxml"]
      and mm["sources"].get("rom_files") == ["-listxml"]
      and mm["sources"].get("address_map") == ["live"]
      and mm["sources"].get(machine.SYMBOL_SECTION) == [machine.SYMBOL_SOURCE],
      str(mm.get("sources")))
# AND IT IS NAMED WITH THE SECTION EMPTY, which is this session: its table carries no classes,
# so there are no rows and `sources` still says where rows would come from. The POPULATED case,
# the one that hid the defect, is asserted further down against a table that has classes.
check("the symbol channel is named even with no rows to attribute",
      mm.get(machine.SYMBOL_SECTION) == [], str(mm.get(machine.SYMBOL_SECTION)))
# ASSERTED AGAINST THE MODULE'S OWN CONSTANTS, not against a literal typed here: a caller
# that greps for words the tool does not print matches nothing, and reports the miss as a
# finding about the tool.
check("the note carries the banking caveat and the map's boundary",
      machine.BANKING_NOTE in mm.get("note", "")
      and machine.MAP_NOTE in mm.get("note", ""),
      mm.get("note", "")[:60])
check("and it alters nothing and needs no stop",
      mm.get("session", {}).get("altered") is False)

print("\n== symbols_find(): the table start parsed, by name and by address")
r = s.symbols_find(name="irq_vblank")
check("an exact name answers its address", r.get("symbols_total") == 1
      and r.get("symbols", [{}])[0].get("addr") == "0x00000400", str(r.get("symbols")))
r = s.symbols_find(linear="0x40e")
check("an address is placed inside the nearest symbol below it",
      r.get("name") == "IRQ_VBLANK" and r.get("delta") == 0xE, str(r.get("summary")))

print("\n== the readers over the console, and the writes: one live call each")
r = s.disassemble(ref="irq_vblank", length=8)
check("disassemble lists MAME's own lines", len(r.get("lines", [])) >= 1, str(r.get("lines"))[:60])
r = s.disassemble(ref="0x560", length=0x40)
pairs = zip(r.get("lines", []), r.get("flow", []), strict=False)
marked = [(line.split(":")[0], c) for line, c in pairs if c != "sequential"]
check("flow classes the vblank tail off the 68000's table: beq, jsr, rte",
      r.get("flow_source") == "mnemonic_table:m68000"
      and marked == [("000578", "branch"), ("00058C", "call"), ("00059A", "return")],
      f"{r.get('flow_source')} {marked} {r.get('note', '')}")
r = s.find(ref="0x0", length=4096, data_hex=by_hex["hex"][:4])
check("find hits the bytes read_memory just read", r.get("hits_total", 0) >= 1,
      f"{r.get('hits_total')} hits")
r = s.history(limit=4)
check("history answers a trail of `<addr>: <instruction>` lines",
      r.get("status") == "ok" and 1 <= len(r.get("lines", [])) <= 4
      and all(": " in ln for ln in r.get("lines", [])), str(r.get("summary"))[:60])
r = s.log(pattern=".", channel="emulator", limit=3)
check("log reads the driver's log and counts it",
      r.get("status") == "ok" and isinstance(r.get("lines_total"), int)
      and len(r.get("lines", [])) == min(3, r.get("lines_total", 0)), str(r.get("summary"))[:60])
dump = Path(tempfile.mkdtemp(prefix="mame-live-")) / "vectors.bin"
r = s.memdump(ref="0x0", length=256, dest=str(dump))
check("memdump writes and checks the file", r.get("bytes") == 256 and dump.is_file(),
      str(r.get("summary"))[:60])
r = s.scan_start(ref="0x200000", length=0x100)
shut = s.scan_filter(operator="!")
check("scan_start takes the work RAM's cells and a `!` at the same stop closes the scan",
      r.get("hits_total") == 0x100 and shut.get("closed") is True
      and shut.get("hits_total") == 0
      and shut.get("session", {}).get("altered") is False, str(shut.get("summary"))[:60])
check("scan_clear says nothing was open once a filter closed it",
      s.scan_clear().get("cleared") is False)
r = s.breakpoint_at(ref="irq_vblank")
listed = s.breakpoint_list()
check("breakpoint_list shows the declaration armed, against MAME's own bplist",
      [(b.get("ref"), b.get("state"), b.get("addr")) for b in listed.get("breakpoints", [])]
      == [("irq_vblank", "armed", "0x00000400")] and listed.get("foreign") == [],
      str(listed.get("breakpoints")))
s.breakpoint_clear(all=True)

print("\n== two cpus: every reply names its cpu, and a row is known by its index")
st = s.status()
check("status lists both cpus and cpu_info marks :maincpu visible, read off the console",
      st.get("cpus") == [":maincpu", ":subcpu"] and visible_of(s.cpu_info()) == ":maincpu",
      f"{st.get('cpus')} visible {visible_of(s.cpu_info())} threads {st.get('threads')}")
check("the stub's readers name the cpu they serve",
      s.registers().get("cpu") == ":maincpu" and s.read_memory(ref="0x400", length=2).get("cpu")
      == ":maincpu")
r = s.debug(command="bp 542:subcpu")
sub_rows = [row for row in mlists.parse_bplist(s.debug(command="bplist")["output"])
            if row["cpu"] == ":subcpu"]
check("a row typed under the sub cpu lists under it and is foreign",
      [row["addr"] for row in sub_rows] == [0x542]
      and s.breakpoint_list().get("foreign") == [sub_rows[0]["entry"]] if sub_rows else False,
      str(sub_rows))
r = s.breakpoint_at(ref="0x542")
listed = s.breakpoint_list()
check("a declaration at the same address on the main cpu arms its own row, not the sub cpu's",
      r.get("cpu") == ":maincpu" and bool(sub_rows) and r.get("entry") != sub_rows[0]["entry"]
      and [b.get("cpu") for b in listed.get("breakpoints", [])] == [":maincpu"]
      and listed.get("foreign") == [sub_rows[0]["entry"]], f"{r.get('entry')} {listed}")
r = s.breakpoint_clear(ref="0x542")
check("its clear removes its own row by index and leaves the sub cpu's",
      s.breakpoint_list().get("foreign") == [sub_rows[0]["entry"]] if sub_rows else False,
      str(r.get("disarmed")))
if sub_rows:
    s.debug(command=mclear.clear_command("breakpoint", sub_rows[0]["index"]))
check("and the typed row goes with its own bpclear", s.breakpoint_list().get("foreign") == [])

print("\n== run_to(): no control declared is a refusal, before the machine moves")
r = s.run_to(ref="irq_vblank", seconds=5.0)
check("refused without a control", r.get("status") == "INVALID" and "no control" in
      str(r.get("message")), str(r.get("message"))[:60])

print("\n== run_to(): a target that DOES run")
# vblank fires constantly, so the target wins the race and the control never needs to speak.
# That is correct: the control only has to have counted when the target did NOT. The control
# is the address inside the vblank handler this repository's own rule measured hot, declared
# here through `run_to` itself, which keeps it: MAME counts it in a temp and never stops on it.
r = s.run_to(ref="irq_vblank", control="0x4a0", seconds=30.0)
check(
    "verdict is a measurement's word",
    r.get("verdict") in {"TARGET", "TIMEOUT", "OTHER_STOP"},
    str(r.get("verdict")),
)
check("a target that runs is reported as TARGET", r.get("verdict") == "TARGET")
check("the run's controls are listed with their cpu and hits", r.get("controls") == [
    {"ref": "0x4a0", "cpu": ":maincpu",
     "hits_in_run": r.get("control_hits")}], str(r.get("controls")))
print(f"        verdict={r.get('verdict')}  pc={r.get('pc')}  control_hits={r.get('control_hits')}")
listed = {b["ref"]: b for b in s.breakpoint_list().get("breakpoints", [])}
check("the control is a declaration MAME lists as a counting condition",
      listed.get("0x4a0", {}).get("role") == "control"
      and "(++temp0)==0" in listed.get("0x4a0", {}).get("entry", ""),
      str(listed.get("0x4a0")))
s.breakpoint_clear(all=True)

print("\n== run_to(condition=...): stop at the vblank only when a RAM word reads a value")
# The vblank handler increments the word at 0x203200 every frame: the condition names the
# value five frames ahead, and the stop is proved by reading the word back.
n = int(s.read_memory(ref="0x203200", length=2)["hex"], 16)
r = s.run_to(ref="irq_vblank", control="0x4a0", seconds=30.0, condition=f"w@0x203200=={n + 5:#x}")
check("a conditioned run_to stops when the condition holds",
      r.get("verdict") == "TARGET" and r.get("condition") == f"w@0x203200=={n + 5:#x}",
      str(r.get("summary") or r.get("message"))[:90])
after = int(s.read_memory(ref="0x203200", length=2)["hex"], 16)
check("and the word reads the value the condition named", after == n + 5, f"{n} -> {after}")
check("a conditioned stop is bookkeeping: the session is not altered",
      r["session"]["altered"] is False)
r = s.run_to(ref="irq_vblank", control="0x4a0", seconds=3.0, condition="w@0x203200==0xffff")
check("a condition that never holds is a TIMEOUT with the control counting",
      r.get("verdict") == "TIMEOUT" and r.get("control_hits", 0) > 0,
      f"{r.get('verdict')} hits={r.get('control_hits')}")
check("the target row was removed after the run",
      not any("@ 000400" in e for e in s.breakpoint_list().get("foreign", [])))
# Two conditioned stops cleared in ONE call: the console renumbers nothing under the clear,
# or the second `bpclear` would hit the wrong row; the list read back is the proof.
held = s.breakpoint_list()["breakpoints"]
s.breakpoint_at(ref="0x4a4", condition="w@0x203200==0x1000")
s.breakpoint_at(ref="0x4a8", condition="w@0x203200==0x2000")
r = s.breakpoint_clear(all=True)
check("console-armed rows clear in one call, the indices holding under the clear",
      r.get("declarations_cleared") == len(held) + 2
      and sum("w@0x203200" in e for e in r.get("disarmed", [])) == 2
      and s.breakpoint_list().get("foreign") == [], str(r.get("disarmed")))

print("\n== run_to(): a target that does NOT run, with a HOT control")
# The control has to be hot ON THIS SCREEN, not just somewhere in the game: the vblank
# handler fires every frame, and the exception handler does not fire on a healthy boot, which
# is the invariant the repository's rule states for it. Declared first, as a session would.
r = s.breakpoint_at(ref="irq_vblank", role="control")
check("a control declares through the console with its temp",
      r.get("armed") is True and str(r.get("temp")).startswith("temp")
      and "(++" in str(r.get("entry")), str(r.get("entry")))
r = s.run_to(ref="exception_handler", seconds=12.0)
check("not reported as TARGET", r.get("verdict") != "TARGET", str(r.get("verdict")))
check(
    "control counted, so the negative MEANS something",
    r.get("control_hits", 0) > 0,
    f"{r.get('control_hits')} hits",
)
frames = 12 * 60
check("the count is the vblank's, about one a frame at flat-out speed, never a stop each",
      r.get("control_hits", 0) > 0, f"{r.get('control_hits')} hits over up to {frames} frames")
s.breakpoint_clear(all=True)

print("\n== a registerpoint: a stop when a register reaches a value, wherever that happens")
# `pc!=<here>` comes true at the very next instruction and stays true, which is the property
# under test: a registerpoint fires at EVERY instruction while its condition holds.
here = str(s.registers()["regs"]["PC"])
r = s.regpoint_add(condition=f"pc!={here}")
check("regpoint_add arms it and reads rplist back",
      r.get("armed") is True and r.get("cpu") == ":maincpu" and "index" in r,
      str(r.get("summary")))
listed = s.regpoint_list().get("regpoints", [])
check("regpoint_list shows it armed",
      [x.get("state") for x in listed] == ["armed"], str(listed)[:80])
r = s.resume(seconds=5.0)
check("the stop it makes is named, with its hit",
      r.get("verdict") == "OTHER_STOP" and str(r.get("how")).startswith("registerpoint ")
      and r.get("regpoint_hit", {}).get("ref") == f"pc!={here}", str(r.get("how")))
r = s.run_for(frames=2, seconds=10.0)
check("still armed: a run by frames is cut at once, and that is a stop, never no_progress",
      r.get("verdict") == "OTHER_STOP" and r.get("session", {}).get("running") is False,
      str(r.get("summary")))
r = s.regpoint_clear(ref=f"pc!={here}")
check("regpoint_clear reads rplist back", len(r.get("disarmed", [])) == 1, str(r))
r = s.run_for(frames=2, seconds=10.0)
check("and the same run then elapses", r.get("verdict") == "ELAPSED", str(r.get("summary")))
r = s.regpoint_add(condition="d1==")
check("a condition MAME would arm and never evaluate is refused in the console's words",
      r.get("code") == "bad_argument" and "stack underflow" in str(r.get("message")),
      str(r.get("message"))[:80])

print("\n== comments: a declaration per place, fed to MAME's pane, kept in a file")
r = s.comment_add(ref="irq_vblank", text="live check", cpu="maincpu")
check("comment_add stores it by symbol and the pane takes it",
      r.get("comment", {}).get("state") == "armed" and r.get("comment", {}).get("by") == "symbol",
      str(r.get("summary")))
line = (s.disassemble(ref="irq_vblank", length=2).get("lines") or [""])[0]
check("disassemble ends the line with the text", line.endswith(" // live check"), line)
listed = s.comment_list()
check("comment_list shows it", [c.get("ref") for c in listed.get("comments", [])]
      == ["irq_vblank"], str(listed.get("summary")))
tsv = str(Path(tempfile.mkdtemp(prefix="mame-live-check-comments-")) / "c.comments.tsv")
r = s.comment_save(dest=tsv)
check("comment_save writes one row under the header",
      r.get("comments_total") == 1 and Path(tsv).read_text().count("\n") == 2,
      str(r.get("summary")))
r = s.comment_delete(ref="0x400", cpu="maincpu")
check("comment_delete by address removes the comment made by symbol",
      r.get("deleted", {}).get("ref") == "irq_vblank", str(r.get("summary")))
r = s.comment_load(path=tsv)
check("comment_load brings it back from the file its `path` names",
      r.get("added") == 1 and r.get("path") == str(tsv), str(r.get("summary")))
s.comment_delete(ref="irq_vblank", cpu="maincpu")
check("and none is left", s.comment_list().get("comments") == [])

print("\n== the INVALID path: a COLD control must NOT let a zero pass as an answer")
# The control is a vector-table slot, data that never executes, so it cannot count. The tool
# must refuse to answer rather than report a zero that is indistinguishable from a broken
# breakpoint. The hot control was cleared above: every declared control counts, and a hot
# one beside a cold one would rightly make the zero a measurement.
r = s.run_to(ref="exception_handler", control="vec_chk", seconds=8.0)
check(
    "cold control yields INVALID, not a bare zero",
    r.get("status") == "INVALID" and "verdict" not in r,
    f"status={r.get('status')} verdict={r.get('verdict')}",
)
check("and names the cause in one word", r.get("code") == "control_silent", str(r.get("code")))
s.breakpoint_clear(all=True)
check(
    "and says so in English", "never fired" in str(r.get("message", "")),
    str(r.get("message", ""))[:60],
)

print("\n== the altered guarantee, through both doors")
before = s.status()["session"].get("altered")
s.debug(command="dasm /dev/null,0x400,1")
after_read = s.status()["session"].get("altered")
check(
    "a read-only debug command does not mark the session", before is False and after_read is False
)
s.debug(command="bpset 0x400")
check("a breakpoint typed through debug is bookkeeping and does NOT mark it",
      s.status()["session"].get("altered") is False)
s.debug(command="bpclear")
# `fill` is a command this console has; `pokew` is not, and a line the console refuses is a
# refusal now, so the write that marks the session has to be one the console makes.
s.debug(command="fill 0x200000,2,0x12,0x34")
after_write = s.status()["session"].get("altered")
check("a mutating debug command DOES mark it", after_write is True)
check("and the fill landed: the two bytes read back",
      s.read_memory(ref="0x200000", length=2).get("hex") == "1234")
w = s.write(ref="0x200000", data_hex="00")
check("write() reports in English", "bytes_written" in w, str(list(w)[:4]))
check("and the warning is English", "MODIFIED" in str(w["session"].get("note", "")))
# The two remaining writers, once the session is already marked: what they force is read back.
d0 = s.registers()["regs"]["D0"]
r = s.set_register(name="D0", value=0x1234)
check("set_register forces the register and READS IT BACK", r.get("value") == "0x00001234"
      and r.get("readback") == "0x00001234" and r.get("verified") is True
      and s.registers()["regs"]["D0"] == "0x00001234", f"D0 was {d0}")
r = s.reset()
check("reset is scheduled: the pc stays until the machine runs",
      r.get("kind") == "softreset" and r.get("pc") == s.status()["pc"], str(r.get("pc")))

print("\n== rom_check()")
c = s.rom_check(reference_rom=REFERENCE_ROM, reference_addr="0x0")
check("rom_check still OK", c.get("rom_check") == "OK")
check("deterministic", c.get("deterministic") is True)
print(f"        query_s = {c.get('query_s')}")

# The console breakpoint the altered section typed is the server's blind spot by design (a
# `debug` write is counted, not itemised), and released now the machine would stop on it at
# the very next vblank; it goes before the running section, which arms its own.
s.debug(command="bpclear")

print("\n== the RUNNING guest: resume with no deadline, the readers refuse, a stop is found")
r = s.resume()
check("resume lets it run", "verdict" not in r and "halted" not in r
      and r["session"]["running"] is True)
r = s.registers()
check("a reader refuses on a running machine",
      r.get("status") == "INVALID" and r.get("code") == "not_stopped",
      f"{r.get('code')}: {str(r.get('message'))[:60]}")
check("and names the last stop", isinstance(r.get("last_stop"), dict)
      and "stop_seq" in r.get("last_stop", {}), str(r.get("last_stop"))[:60])
check("and what answers meanwhile", "log_wait" in r.get("answers_while_running", []))
r = s.registers(from_last_stop=True)
check("the last stop's registers answer, superseded", r.get("superseded") is True
      and "stale" not in r and "regs" in r)
r = s.status()
check("status says running", r.get("running") is True and r.get("last_stop") is not None)
r = s.snapshot()
check("snapshot answers while running", r.get("bytes", 0) > 0, str(r.get("bytes")))
r = s.log_wait(pattern=".", channel="emulator", seconds=5.0)
check("log_wait answers while running", "line" in r, str(r.get("summary"))[:70])
r = s.breakpoint_at(ref="irq_vblank")
check("a breakpoint arms while running", r.get("armed") is True and r.get("while_running") is True)
time.sleep(0.3)
r = s.status()
check("the first contact finds the stop the breakpoint produced",
      r.get("running") is False and "stopped_on_its_own" in r,
      str(r.get("stopped_on_its_own"))[:80])
check("and the record moved to it",
      r.get("last_stop", {}).get("how", "").startswith("breakpoint"),
      str(r.get("last_stop", {}).get("how")))
gone = s.breakpoint_clear(all=True).get("disarmed", [])
check("breakpoint_clear reads bplist back", len(gone) == 1 and gone[0].endswith("@ 000400"),
      str(gone))
r = s.resume(seconds=1.0)
check("a bound that expires leaves it running",
      r.get("verdict") == "TIMEOUT" and r["session"]["running"])
r = s.stop()
check("stop interrupts and surveys",
      r.get("interrupted") is True and isinstance(r.get("dasm"), list)
      and isinstance(r.get("frame"), int), f"pc={r.get('pc')} frame={r.get('frame')}")
r = s.run_for(milliseconds=100)
check("run_for carries the survey", r.get("verdict") == "ELAPSED" and "errorlog" in r
      and isinstance(r["errorlog"].get("lines_total"), int))
r = s.trace(frames=2, seconds=10.0)
t = r.get("trace") or {}
set_lines = (len(Path(t["set_path"]).read_text().splitlines())
             if t.get("set_path") and Path(t["set_path"]).is_file() else None)
check("trace answers the executed set, and its set file holds that many rows",
      r.get("verdict") == "ELAPSED" and t.get("addresses", 0) > 0
      and set_lines == t.get("addresses"), f"addresses={t.get('addresses')} lines={set_lines}")
r = s.captures()
check("captures lists the trace, present, as kind trace",
      any(c.get("kind") == "trace" and c.get("path") == t.get("path") and c.get("present")
          for c in r.get("captures", [])))
r = s.step(count=1)
check("step carries the survey", "regs" in r and r.get("how") == "step 1")
s.resume()

print("\n== the watch family: who wrote this byte, measured on the board's own counters")
# The vblank handler increments a word at 0x203200 and a long at 0x2031fc every frame
# (read in its disassembly), so a change watch on either fires within one frame.
r = s.watch_add(ref="0x2031fc", mode="change", length=4)
check("a change watch arms, read back from wplist", r.get("armed") is True
      and isinstance(r.get("index"), int) and r.get("write_maps_to", "").startswith("memory"),
      str(r.get("summary")))
r = s.watch_add(ref="irq_vblank", mode="change", length=2, fmt="u16")
check("a change watch on the ROM copy is refused as INVALID by the map control",
      r.get("status") == "INVALID" and "unmapped" in str(r.get("message")),
      f"{r.get('code')}: {str(r.get('message'))[:70]}")
r = s.watch_add(ref="0x203200", mode="show", length=2, fmt="u16")
check("a show watch arms nothing and reads now", r.get("armed") is False
      and r.get("state") == "evaluated" and "value" in r.get("reading", {}))
r = s.resume(seconds=5.0)
check("the change watch stops the machine and names its writer",
      r.get("verdict") == "OTHER_STOP" and str(r.get("how", "")).startswith("watch 0x2031fc")
      and isinstance(r.get("watch_hit"), dict) and r["watch_hit"].get("writer_pc") is not None,
      f"how={r.get('how')} hit={str(r.get('watch_hit'))[:120]}")
hit = r.get("watch_hit", {})
check("the write landed before the stop: after is before + 1",
      isinstance(hit.get("before"), int) and hit.get("after") == hit["before"] + 1,
      f"before={hit.get('before')} after={hit.get('after')}")
# A 68000 writes a long as two words and the console prints one line per write (measured):
# both lines are this watch's, and the writer is the last one's pc.
check("a long write is two console lines, and the writer is the last",
      len(hit.get("writes", [])) == 2 and hit.get("writer_pc") == hit["writes"][-1].get("pc")
      and len(hit.get("lines", [])) == 2, str(hit.get("writes"))[:120])
check("the survey carries every watch evaluated",
      [w.get("ref") for w in r.get("watches", [])] == ["0x2031fc", "0x203200"],
      str(r.get("watches"))[:100])
listed = s.watch_list()
check("watch_list shows both, one armed", [w["state"] for w in listed.get("watches", [])]
      == ["armed", "evaluated"] and listed.get("foreign") == [], str(listed.get("summary")))
r = s.watch_clear(all=True)
check("watch_clear disarms what it armed and reads the list back",
      r.get("declarations_cleared") == 2 and len(r.get("disarmed", [])) == 1, str(r.get("summary")))
check("and the debugger holds nothing", s.watch_list().get("watches") == []
      and s.watch_list().get("foreign") == [])

print("\n== a write-only register: the values come off the bus, never off memory")
# The sound latch at 0x740000 is written through the driver's handler and reads back through
# nothing (`map` says so), so a memory read there is noise: the watch's values are the writes.
r = s.watch_add(ref="0x740000", mode="change", length=2)
check("the latch's read side is unmapped and the watch's values come from the bus",
      r.get("read_maps_to") == "unmapped" and r.get("values_from") == "bus"
      and r.get("write_maps_to", "").endswith("latch_w") and "value" not in r,
      f"{r.get('write_maps_to')} / {r.get('read_maps_to')} / {r.get('values_from')}")
r = s.resume(seconds=10.0)
hit = r.get("watch_hit", {})
check("the latch hit's after is the value the console logged as written",
      r.get("verdict") == "OTHER_STOP" and hit.get("values_from") == "bus"
      and isinstance(hit.get("after"), int)
      and hit.get("writes") and hit["after"] == int(hit["writes"][-1]["wrote"], 16),
      f"after={hit.get('after')} writes={str(hit.get('writes'))[:80]}")
(w,) = [w for w in r.get("watches", []) if w.get("ref") == "0x740000"] or [{}]
check("and the survey carries the last value written instead of a memory read",
      w.get("state") == "armed" and w.get("reading", {}).get("state") == "bus"
      and w.get("reading", {}).get("last_wrote") == hit.get("after"), str(w)[:100])
s.watch_clear(all=True)

print("\n== typed watches: the shape of a value, and the build's fingerprint")
raw = s.read_memory(ref="0x2031fc", length=8).get("hex", "")
r = s.watch_add(ref="0x2031fc", mode="show", fmt="u16[4]")
check("an array format implies its width and decodes the bytes read_memory shows",
      r.get("length") == 8 and r.get("reading", {}).get("value")
      == [int(raw[i:i + 4], 16) for i in range(0, 16, 4)],
      f"reading={r.get('reading')} hex={raw}")
r = s.watch_add(ref="0x203200", mode="show", fmt="{lo:u16,hi:u16,tag:char[4]}")
value = r.get("reading", {}).get("value")
check("a struct format decodes to its fields", isinstance(value, dict)
      and set(value) == {"lo", "hi", "tag"} and r.get("length") == 8, str(value))
s.watch_clear(all=True)
fp = s.status().get("fingerprint")
check("status carries the build's fingerprint, sixteen hex digits",
      isinstance(fp, str) and len(fp) == 16 and all(c in "0123456789abcdef" for c in fp), str(fp))

print("\n== watch_add(mode=\"count\"): a tally over a pass, by value and by writer, no stop")
r = s.watch_add(ref="0x2031fc", mode="count", length=4)
check("a count watch is stored and its install SENT, pending until the console reads it",
      r.get("status") == "ok" and r.get("pending") is True and r.get("installed") is False
      and r.get("armed") is False,
      str(r.get("summary") or r.get("message")))
r = s.watch_add(ref="0x20351c", mode="count", length=1)
check("a one-byte tally on the 16-bit bus is accepted (the tap is bus-aligned, filtered)",
      r.get("status") == "ok", str(r.get("summary") or r.get("message")))
r = s.run_for(frames=60)
items = {w.get("ref"): w for w in r.get("watches", [])}
t = items.get("0x2031fc", {})
check("after sixty frames the tally is installed and read as of THIS stop",
      t.get("installed") is True and t.get("state") == "tallied"
      and t.get("frame_as_of") == r.get("frame") and t.get("superseded") is False,
      f"state={t.get('state')} as_of={t.get('frame_as_of')} frame={r.get('frame')}")
check("the vblank handler wrote the frame counter, two words per long, from one pc",
      t.get("total", 0) >= 100 and t.get("writers_total") == 1
      and t.get("writers", [{}])[0].get("pc") == "0x0000040e",
      f"total={t.get('total')} writers={t.get('writers')}")
b = items.get("0x20351c", {})
check("the one-byte tally counts whole bytes in its own format, and nothing partial",
      b.get("installed") is True and b.get("total", 0) > 0
      and all("value" in v and "partial" not in v for v in b.get("values", [])),
      f"total={b.get('total')} values={b.get('values', [])[:3]} error={b.get('error')}")
r = s.watch_add(ref="0x400", mode="count", length=2)
check("a count on the ROM copy is armed, its note saying the writes go nowhere",
      r.get("status") == "ok" and r.get("write_maps_to") == "unmapped"
      and "nothing in the machine handles a write at 0x400" in str(r.get("note")),
      str(r.get("note"))[-120:])
s.watch_clear(ref="0x400")
r = s.watch_clear(ref="0x2031fc")
check("clearing a tally sends its removal and drops the record",
      r.get("tallies_removed", [{}])[0].get("removal") == "pending", str(r.get("summary")))
r = s.run_for(frames=1)
at_next = {w.get("ref"): w for w in r.get("watches", [])}
check("the next stop no longer carries it, and the other tally went on counting",
      "0x2031fc" not in at_next
      and b.get("total", 0) < at_next.get("0x20351c", {}).get("total", 0),
      str([(ref, w.get("total")) for ref, w in at_next.items()]))
s.watch_clear(all=True)

print("\n== screen signature and the snapshot's hash ")
r = s.snapshot()
check("snapshot carries the sha256 of the bytes it wrote",
      r.get("status") == "ok" and len(str(r.get("sha256", ""))) == 64, str(r.get("sha256"))[:16])
altered_before = s.status()["session"]["altered"]
sig1 = s.screen_signature()
check("screen_signature answers a number from a grid of the screen",
      sig1.get("status") == "ok" and isinstance(sig1.get("signature"), int)
      and sig1.get("grid") == 8 and sig1.get("width", 0) > 0,
      f"sig={sig1.get('signature')} {sig1.get('width')}x{sig1.get('height')} "
      f"{sig1.get('evaluated_by')}")
check("and it alters nothing (the count of writes is what it was)",
      sig1.get("session", {}).get("altered") == altered_before,
      f"{altered_before} -> {sig1.get('session', {}).get('altered')}")
sig2 = s.screen_signature()
check("the same screen signs the same", sig2.get("signature") == sig1.get("signature"),
      f"{sig1.get('signature')} vs {sig2.get('signature')} "
      f"({sig2.get('status')} {sig2.get('code', '')} {str(sig2.get('message', ''))[:200]})")
r = s.run_for(frames=120, seconds=30.0)
sig3 = s.screen_signature()
check("120 frames of boot paint a different screen", sig3.get("signature") != sig1.get("signature"),
      f"{sig1.get('signature')} -> {sig3.get('signature')}")

print("\n== graphics: the pens, the screen as pens, bytes as tiles, a patch searched")
altered_before = s.status()["session"]["altered"]
pal = s.palette()
check("palette reads the live pens as a table and a picture",
      pal.get("status") == "ok" and pal.get("entries", 0) > 0 and len(pal.get("colors", [])) > 0
      and str(pal.get("palette", "")).startswith(":")
      and Path(str(pal.get("image", {}).get("path"))).is_file(), str(pal.get("summary")))
hist = s.screen_view(mode="histogram")
check("screen_view counts every pixel of the screen by pen",
      hist.get("status") == "ok"
      and sum(n for _, n in hist.get("histogram", []))
      == hist.get("width", 0) * hist.get("height", 1),
      str(hist.get("summary")))
shot = s.screen_view(scale=1)
check("render of an indexed screen of at most 256 pens is an indexed PNG of the screen's size",
      shot.get("status") == "ok" and shot.get("screen_indexed") is True
      and shot.get("image", {}).get("indexed") is (shot.get("entries", 999) <= 256)
      and shot.get("image", {}).get("width") == shot.get("width"), str(shot.get("summary")))
px = s.screen_view(mode="pixel", point=[0, 0])
check("pixel names a pen the histogram counted",
      px.get("status") == "ok" and px.get("pen") in {p for p, _ in hist.get("histogram", [])},
      str(px.get("summary")))
tiles = s.gfx_view(layout=BYTES_8X8, palette="none", tag="maincpu", count=16)
check("gfx_view decodes a region under a stated layout and says grey is not real colour",
      tiles.get("status") == "ok" and tiles.get("count") == 16
      and tiles.get("real_colors") is False, str(tiles.get("summary")))
found = s.gfx_locate(layouts=[BYTES_8X8], patch=[0, 0, 8, 8], tag="maincpu", count=64)
check("gfx_locate searches the tiles it names and answers matched or nearest",
      found.get("status") == "ok"
      and found.get("candidates", [{}])[0].get("tiles_searched") == [0, 64],
      str(found.get("summary")))
check("and none of the four altered the session",
      s.status()["session"]["altered"] == altered_before)

print("\n== graphics through the project's manifest: a frame's boxes, one blit's source")
man = s.gfx_load(path=MANIFEST)
check("gfx_load reads the project's manifest whole",
      man.get("status") == "ok" and "blit" in man.get("commands", {}), str(man.get("summary")))
s.watch_add(ref="0x700000", mode="capture", length=32, trigger="0x70001e")
s.run_for(frames=3, seconds=10.0)
boxes = s.gfx_blits(draw_command="blit")
check("gfx_blits reads a finished frame of the blitter's capture as boxes over the screen",
      boxes.get("status") == "ok" and boxes.get("blits_in_frame", 0) > 0
      and Path(str(boxes.get("image", {}).get("path"))).is_file(), str(boxes.get("summary")))
src = s.gfx_blit_source(draw_command="blit", frame=boxes.get("frame_blit"), index=0)
check("gfx_blit_source decodes the rectangle that blit reads, the destination's size",
      src.get("status") == "ok"
      and src.get("rect", {}).get("width") == src.get("destination", {}).get("width"),
      str(src.get("summary")))
s.watch_clear(ref="0x700000")
check("and none of the three altered the session",
      s.status()["session"]["altered"] == altered_before)

print("\n== the palette write log: who set a pen, joined to a pixel")
armed = s.palette_log(palette_port="ramdac", arm=True)
check("palette_log arms the RAMDAC the manifest declares", armed.get("armed_now") is True,
      str(armed.get("summary")))
s.run_for(frames=2, seconds=10.0)
logged = s.palette_log(palette_port="ramdac")
check("and reads the writes its tap placed on pens",
      logged.get("status") == "ok" and logged.get("writes_total", 0) > 0
      and logged.get("pens_written"), str(logged.get("summary")))
# a pixel of a pen the log holds: the first point of a coarse grid whose pen the game has written
spans = [[int(end, 16) for end in run.split("-")] for run in logged.get("pens_written", [])]
written = {p for span in spans for p in range(span[0], span[-1] + 1)}
who: dict[str, Any] = {}
for point in ([x, y] for y in range(0, 240, 40) for x in range(0, 320, 40)):
    who = s.screen_view(mode="pixel", point=point)
    if who.get("pen") in written:
        break
check("screen_view's pixel names the game's write that set its pen",
      who.get("status") == "ok"
      and (who.get("set_by") or {}).get("last", {}).get("written_by") == "guest",
      str(who.get("summary")))
s.palette_log(palette_port="ramdac", clear=True)
check("and none of them altered the session",
      s.status()["session"]["altered"] == altered_before)

print("\n== the conditioned film: the frames in which the blitter fired")
armed = s.gfx_film(trigger="0x70001e", length=2, value=0xFFFF, keep=2, frames=4)
check("gfx_film arms on the blitter's strobe, its frames checkable against MAME's rendering",
      armed.get("armed_now") is True and armed.get("film", {}).get("checked") is True,
      str(armed.get("summary")))
s.run_for(frames=6, seconds=10.0)
film = s.gfx_film()
check("and keeps the frames the strobe fired in, each passing its check, on a labelled sheet",
      film.get("status") == "ok" and film.get("kept") == 2 and film.get("refused") == 0
      and (film.get("image") or {}).get("inline") is True, str(film.get("summary")))
s.gfx_film(clear=True)
check("and none of it altered the session", s.status()["session"]["altered"] == altered_before)

print("\n== discovery: a sweep of the graphics ROM and a draft of what this session proved")
sweep = s.gfx_sweep(tag="gfx1", planes=[8], count=8)
check("gfx_sweep draws gfx1 under its 8-bit candidates on one labelled, attached sheet",
      sweep.get("status") == "ok" and [c["shown"] for c in sweep.get("candidates", [])]
      == [8, 8, 8] and (sweep.get("image") or {}).get("inline") is True,
      str(sweep.get("summary")))
draft_dir = Path(tempfile.mkdtemp(prefix="mame-live-draft-"))
draft = s.gfx_draft(dest=str(draft_dir / "radendur-gfx.yaml"))
check("gfx_draft writes a draft the loader takes and its report beside it",
      draft.get("status") == "ok"
      and (draft_dir / "radendur-gfx.yaml").read_text().startswith("# DRAFT")
      and (draft_dir / "radendur-gfx.report.json").is_file(), str(draft.get("summary")))
check("and neither altered the session", s.status()["session"]["altered"] == altered_before)

print("\n== drive: look, act, verify on the emulator log")
r = s.drive(act=[{"op": "run_for", "frames": 2, "seconds": 30.0}], pattern=".", limit=5)
check("drive runs its act and looks at the emulator log since the mark",
      r.get("status") == "ok" and r.get("act", {}).get("steps_completed") == 1
      and r.get("looked", {}).get("emulator", {}).get("available") is True,
      f"lines_written={r.get('looked', {}).get('emulator', {}).get('lines_written')}")
check("with no expect the verify says so", r.get("verify", {}).get("checked") is False)
r = s.drive(act=[{"op": "run_for", "frames": 2, "seconds": 30.0}], expect="nothing logs this",
            seconds=1.0)
check("an expectation a stopped machine did not meet is wait_stopped with the act's account",
      r.get("status") == "INVALID" and r.get("code") == "wait_stopped"
      and r.get("act", {}).get("steps_completed") == 1, str(r.get("code")))

print("\n== perform: a goldens run in ONE call, and run_for by frames")
snap_dir = Path(tempfile.mkdtemp(prefix="mame-live-goldens-"))
r = s.perform(steps=[
    {"op": "breakpoint_at", "ref": "irq_vblank", "role": "control"},
    {"op": "run_to", "ref": "0x4a0", "seconds": 20.0},
    {"op": "snapshot", "dest": str(snap_dir / "scene_a.png")},
    {"op": "run_for", "frames": 60, "seconds": 30.0},
    {"op": "snapshot", "dest": str(snap_dir / "scene_b.png")},
], settle_seconds=5.0)
check("the whole list ran", r.get("status") == "ok" and r.get("steps_completed") == 5
      and (r.get("failed_at") or {}).get("available") is False, str(r.get("summary")))
steps = {i: step.get("reply", {}) for i, step in enumerate(r.get("ran", []))}
check("run_to inside the batch reached its target with the control counting",
      steps.get(1, {}).get("verdict") == "TARGET", str(steps.get(1, {}).get("summary")))
frames_run = steps.get(3, {})
check("run_for by frames moved the counter by exactly sixty",
      frames_run.get("frame_after", 0) - frames_run.get("frame_before", 0) == 60,
      f"{frames_run.get('frame_before')} -> {frames_run.get('frame_after')}")
# THE EXPECTED CYCLES COME FROM THE BOARD, NOT FROM A CONSTANT: the cpu clock is the driver's
# (the crystal halved) and the frame rate is what the screen declares, read off the machine,
# because a fixed rate written here lies the moment a driver's video timing moves.
CPU_HZ = 16_000_000
rate = s.lua("for _, sc in pairs(manager.machine.screens) do print(sc.refresh) break end",
             read_only=True)
try:
    refresh_hz = float(str(rate.get("output", "")).strip())
except ValueError:
    refresh_hz = 0.0
check("the screen declares its refresh rate", refresh_hz > 0, str(rate.get("output"))[:40])
expected = 60 * CPU_HZ / refresh_hz if refresh_hz else 0
check("sixty frames on a 16 MHz cpu is sixty times the cycles per frame the refresh rate gives, "
      "give or take a frame",
      refresh_hz > 0 and abs(frames_run.get("cycles", 0) - expected) <= CPU_HZ / refresh_hz,
      f"cycles={frames_run.get('cycles')} expected={expected:.0f} at {refresh_hz:.3f} Hz")
check("both snapshots landed as complete PNGs",
      all(steps.get(i, {}).get("bytes", 0) > 0 for i in (2, 4)),
      f"{steps.get(2, {}).get('bytes')} and {steps.get(4, {}).get('bytes')} bytes")
brief = s.perform(steps=[{"op": "run_for", "frames": 1, "seconds": 30.0},
                         {"op": "run_for", "frames": 1, "seconds": 30.0},
                         {"op": "registers"}], settle_seconds=5.0, summaries=True)
brief_ran = brief.get("ran", [])
check("summaries=True cuts each earlier stop to its line, its status and where and when it "
      "stopped, without its lists",
      brief.get("status") == "ok" and len(brief_ran) == 3
      and all(set(step["reply"]) == {"summary", "status", "how", "pc", "frame", "stop_seq"}
              for step in brief_ran[:2])
      and "run_for 1 frame:" in str(brief_ran[0]["reply"]["summary"]),
      str([step["reply"].get("summary") for step in brief_ran[:2]]))
check("and the last step keeps its whole reply",
      "regs" in brief_ran[-1]["reply"] if brief_ran else False)
bad = s.perform(steps=[{"op": "run_to", "ref": "0x4a0"}, {"op": "warp_core"}])
check("a batch with a bad step is refused whole, nothing run",
      bad.get("status") == "INVALID" and bad.get("steps_completed") == 0 and bad.get("ran") == [],
      str(bad.get("message"))[:80])
s.breakpoint_clear(all=True)

print("\n== expr watches: the debugger's own variables at every stop, in one print")
r = s.watch_add(ref="beamy", mode="expr")
check("beamy declares as an expr watch with a value now",
      r.get("status") == "ok" and r.get("mode") == "expr"
      and isinstance(r.get("reading", {}).get("value"), int),
      str(r.get("summary")))
r = s.watch_add(ref="nosuchvariable_zz", mode="expr")
check("an expression the debugger cannot evaluate is refused before it is stored",
      r.get("status") == "INVALID" and r.get("code") == "bad_argument",
      str(r.get("message"))[:80])
s.watch_add(ref="totalcycles", mode="expr")
r = s.run_for(milliseconds=100, seconds=30.0)
watched = {w.get("ref"): w for w in r.get("watches", [])}
check("run_for's stop carries beamy and totalcycles evaluated",
      all(watched.get(k, {}).get("state") == "evaluated"
          and watched.get(k, {}).get("reading", {}).get("available") is True
          for k in ("beamy", "totalcycles")),
      str(r.get("watches"))[:120])
check("run_for reports the cycles the run took, a positive count",
      isinstance(r.get("cycles"), int) and r["cycles"] > 0, f"cycles={r.get('cycles')}")
frames = r.get("frame_after", 0) - r.get("frame_before", 0)
check("about 100 ms of frames at 60 Hz (5 to 7)", 5 <= frames <= 7, f"{frames} frames")
s.watch_clear(all=True)
# Declared BY NAME and left in the store: the next start below must bring them back.
s.breakpoint_at(ref="irq_vblank")
s.watch_add(ref="main_ram", mode="change", length=4)
s.watch_add(ref="line_counter", mode="show", length=2, fmt="u16")
s.resume()

print("\n== close() on a RUNNING machine")
check("closed", s.close().get("closed") is True)

print("\n== start(throttle_from_frame): fly flat out, real speed from the frame")
r = s.start(**BOOT, symbols=SYMBOLS, throttle_from_frame=300)
rearm = r.get("declarations", {}).get("rearm", {})
# EACH ENTRY NAMES ITS CPU: a declaration keeps the cpu it was declared on, and the re-arm
# puts it there.
by_name = [(ref, ":maincpu") for ref in ("irq_vblank", "main_ram")]
check("the declarations left by name came back, re-resolved and re-armed on their cpu",
      rearm_pairs(rearm, "rearmed") == by_name
      and rearm_pairs(rearm, "evaluated") == [("line_counter", ":maincpu")]
      and rearm.get("stale") == [] and rearm.get("unresolved") == [], str(rearm))
back = rearm.get("rearmed", []) + rearm.get("evaluated", [])
check("each re-armed row says it is inherited, whose and how old",
      bool(back) and all(e.get("inherited") is True and e.get("origin")
                         and type(e.get("age_s")) is int and e.get("created_at")
                         and e.get("by") for e in back), str(rearm))
check("and the debugger's own lists hold them",
      [b.get("state") for b in s.breakpoint_list().get("breakpoints", [])] == ["armed"]
      and [w.get("state") for w in s.watch_list().get("watches", [])] == ["armed", "evaluated"]
      and [len(v) for v in s.status().get("in_debugger", {}).values()] == [1, 1, 0])
check("the store reports itself", r.get("declarations", {}).get("persistent") is True
      and r["declarations"].get("held") == 3, str(r.get("declarations"))[:120])
s.breakpoint_clear(all=True)
s.watch_clear(all=True)
check("start reports what it handed over", r.get("throttle_from_frame") == 300
      and r.get("env", {}).get("MAME_MCP_THROTTLE_FRAME") == "300" and r.get("display") == ""
      and "-nothrottle" in r.get("flags", []), str(r.get("flags")))
t0 = time.time()
s.resume()
r = s.log_wait(pattern="MAME_MCP throttled from frame", channel="emulator", seconds=20.0)
flew = time.time() - t0
check("the harness logged the arrival", "line" in r, str(r.get("line") or r.get("message"))[:80])
check("and it flew there (300 frames well under 300/60 s at real speed)", flew < 3.0,
      f"{flew:.2f} s")
r = s.stop()
f0, t0 = r.get("frame"), time.time()
s.resume(seconds=1.0)
r = s.stop()
f1, dt = r.get("frame"), time.time() - t0
rate = (f1 - f0) / dt if isinstance(f0, int) and isinstance(f1, int) and dt else 0.0
check("and runs at real speed from there (about 60 frames a second)", 40 < rate < 90,
      f"{rate:.0f} frames/s")
check("closed", s.close().get("closed") is True)

print("\n== step over, and a run the console started")
r = s.start(**BOOT, symbols=SYMBOLS)
pc0 = r.get("pc")
r = s.step(count=1, mode="over")
check("step over goes through the console and lands one instruction on",
      r.get("status") == "ok" and r.get("mode") == "over" and r.get("instructions_completed") == 1
      and r.get("pc") != pc0, f"{pc0} -> {r.get('pc')}: {str(r.get('message'))[:60]}")
r = s.step(count=3, mode="into")
check("step into still answers the survey", r.get("instructions_completed") == 3 and "regs" in r)
r = s.debug(command="g")
check("a g typed through debug marks the session RUNNING", "running" not in r
      and r["session"]["running"] is True, str(r.get("summary")))
r = s.registers()
check("and a reader refuses while it runs", r.get("code") == "not_stopped", str(r.get("code")))
r = s.log_wait(pattern=".", channel="emulator", seconds=5.0)
check("log_wait waits on the console-started run", "line" in r, str(r.get("message"))[:60])
r = s.stop()
check("stop halts it and proves the rest on the frame counter",
      r.get("interrupted") is True and r["session"]["running"] is False
      and isinstance(r.get("frame"), int), str(r.get("summary") or r.get("message"))[:80])
r = s.registers()
check("the readers answer again", r.get("status") == "ok")
s.breakpoint_at(ref="irq_vblank")
s.debug(command="g")
time.sleep(0.5)
r = s.status()
check("a stop the console's run reached at a breakpoint is found by the first contact",
      r.get("running") is False and "stopped_on_its_own" in r,
      str(r.get("stopped_on_its_own"))[:90])
s.breakpoint_clear(all=True)
check("closed", s.close().get("closed") is True)

print("\n== the Lua channel: MAME's own console through stdin, measured on radendur")
r = s.start(**BOOT, symbols=SYMBOLS)
check("a fresh session for the channel", r.get("rom_check") == "OK", str(r.get("summary")))
image = Path(REFERENCE_ROM).read_bytes()
r = s.lua('print(string.format("PROBE %02x %02x", '
          'manager.machine.devices[":maincpu"].spaces["program"]:read_u8(1), '
          'manager.machine.devices[":maincpu"].spaces["program"]:read_u8(7)))')
check("lua answers the known bytes of the image, evaluated by one step",
      r.get("output") == f"PROBE {image[1]:02x} {image[7]:02x}\n"
      and r.get("evaluated_by") == "one step",
      str(r.get("output") or r.get("message"))[:80])
check("and the raw form marks the session altered", r["session"]["altered"] is True
      and r.get("pc_before") != r.get("pc"), f"{r.get('pc_before')} -> {r.get('pc')}")
r = s.lua("this_function_does_not_exist()")
check("the console's own error is a refusal in its words", r.get("status") == "INVALID"
      and "attempt to call a nil value" in str(r.get("message")), str(r.get("message"))[:80])
r = s.lua("local t = {}\nfor i = 1, 3 do t[#t + 1] = i * 2 end\nprint(table.concat(t, ','))")
check("a multi-line script runs as ONE chunk", r.get("output") == "2,4,6\n", str(r.get("output")))

print("\n== input(): the coin of radendur, by port and field name, read back off the port")
# The game's credit counter (nav-phase.lua reads it at 0x20351e); the menu needs the machine
# past its boot, so run there first.
s.run_for(frames=300)
credits0 = int(s.read_memory(ref="0x20351e", length=2)["hex"], 16)
r = s.input(port=":P1", field="Coin 1", value=1, frames=40)
check("input holds the field and reads it active off the port", r.get("active") is True
      and r.get("frame_released", 0) - r.get("frame_set", 0) >= 40, str(r.get("summary")))
print(f"        {r.get('summary')}  port_before={r.get('port_before')} "
      f"port_held={r.get('port_held')}")
s.run_for(frames=30)
credits1 = int(s.read_memory(ref="0x20351e", length=2)["hex"], 16)
check("and the game took the coin (credits moved)", credits1 > credits0,
      f"{credits0} -> {credits1}")
r = s.input(port=":P1", field="No Such Field", frames=2)
check("a field that does not exist is refused in the console's words", r.get("status") == "INVALID"
      and "no field" in str(r.get("message")), str(r.get("message"))[:80])

print("\n== state_save()/state_load(): the console's own savestate, checked by file and frame")
r = s.state_save(name="live")
saved_frame = r.get("frame")
check("state_save writes a .sta with MAME's magic", r.get("status") == "ok"
      and Path(str(r.get("path"))).is_file(), str(r.get("summary") or r.get("message"))[:90])
s.run_for(frames=120)
r = s.state_load(name="live")
check("state_load restores the frame it was saved at, ROM re-checked, verified",
      r.get("rom_check") == "OK" and r.get("frame") == saved_frame and r.get("verified") is True,
      f"saved at {saved_frame}, after load {r.get('frame')}: {str(r.get('message'))[:60]}")
r = s.state_list()
check("state_list names the state this session wrote, with its frame",
      r.get("status") == "ok" and any(x.get("name") == "live" and x.get("frame") == saved_frame
                                      for x in r.get("states", [])),
      str(r.get("summary") or r.get("message"))[:90])
r = s.state_load(name="nope")
check("a state that does not exist is refused before the console", r.get("code") == "unknown_ref")
# MAME refuses a bad state in SILENCE from the console (measured: nothing in any log), so
# the header is judged before the console: a corrupt magic and another system's name.
good = Path(str(s.status().get("state_dir") or s.status().get("scratch_dir"))) / "sta" / "radendur"
corrupt = bytearray((good / "live.sta").read_bytes())
corrupt[0:8] = b"NOTASAVE"
(good / "corrupt.sta").write_bytes(corrupt)
foreign = bytearray((good / "live.sta").read_bytes())
foreign[0x0A:0x1C] = b"pacman".ljust(0x12, b"\0")
(good / "foreign.sta").write_bytes(foreign)
r = s.state_load(name="corrupt")
check("a corrupt header is refused before the console", r.get("code") == "readback_refused"
      and "magic" in str(r.get("message")), str(r.get("message"))[:70])
r = s.state_load(name="foreign")
check("another system's state is refused before the console", r.get("system") == "pacman",
      str(r.get("message"))[:70])

print("\n== record(): an AVI bounded by the frame counter, checked by its header")
r = s.record(frames=30)
check("record produces a finished AVI declaring EXACTLY the frames asked for",
      r.get("status") == "ok" and r.get("avi_frames") == 30,
      str(r.get("summary") or r.get("message"))[:100])
print(f"        {r.get('summary')}  frames {r.get('frame_begin')} to {r.get('frame_end')}")
r = s.captures()
check("captures lists the AVI record wrote, with its frames",
      r.get("status") == "ok" and any(c.get("kind") == "avi" and c.get("present") is True
                                      for c in r.get("captures", [])),
      str(r.get("summary") or r.get("message"))[:90])

print("\n== audio_record(): the mixer's WAV bounded by the frame counter, checked by its header")
r = s.audio_record(frames=30)
samples = r.get("samples") or 0
# READ BY A READER THE SERVER DOES NOT USE: the standard library's `wave` against the reply, so
# a header the server's own parser misreads goes red here, where the server's own refusals,
# restated, could not.
try:
    with wave.open(str(r.get("path")), "rb") as wav:
        heard: tuple[int, int, int, int] | str = (
            wav.getnframes(), wav.getnchannels(), wav.getframerate(),
            Path(str(r.get("path"))).stat().st_size)
except (OSError, EOFError, wave.Error) as e:
    heard = f"wave could not read it: {e}"
# and that file holds the span asked for: 30 frames of the counter, its samples that span's at
# the rate within one of the mixer's updates of a fiftieth of an emulated second
rate, emulated = r.get("sample_rate_hz") or 0, r.get("emulated_s") or 0.0
check("audio_record's WAV reads, by the standard library's own reader, as the reply says, over "
      "exactly the 30 frames asked for",
      r.get("status") == "ok" and samples > 0
      and heard == (samples, r.get("channels"), r.get("sample_rate_hz"), r.get("bytes"))
      and r.get("frame_end", 0) - r.get("frame_begin", 0) + 1 == 30
      and abs(samples - emulated * rate) <= rate // 50 + 1,
      f"{str(r.get('summary') or r.get('message'))[:60]} / wave {heard}")
r = s.captures()
check("captures lists the WAV audio_record wrote, with its samples",
      r.get("status") == "ok" and any(c.get("kind") == "wav" and c.get("present") is True
                                      and c.get("samples") == samples
                                      for c in r.get("captures", [])),
      str(r.get("summary") or r.get("message"))[:90])

print("\n== throttle(): pending on a stopped machine, applied on a running one")
r = s.throttle(on=False)
check("stopped: pending, with this call's own mark to wait for", r.get("pending") is True
      and str(r.get("mark")).startswith("MAME_MCP_THROTTLE#"), str(r.get("mark")))
s.resume()
r = s.log_wait(pattern=f"{r.get('mark')} throttled=false", channel="emulator", seconds=5.0)
check("the pending switch applied on the first frame of the run", "line" in r,
      str(r.get("line") or r.get("message"))[:80])
r = s.throttle(on=True)
check("running: applied, with the frame",
      r.get("pending") is False and isinstance(r.get("frame"), int),
      str(r.get("summary") or r.get("message")))
r = s.throttle(on=False)
check("and back off", r.get("pending") is False)
check("closed", s.close().get("closed") is True)

# THE ACCEPTANCE OF machine_map, which needs sessions of its own: the board's YAML table
# carries no classes, so the symbol half of the tool can only be exercised by handing `start`
# a linker-map-shaped table. The addresses are the board's own: the CODE rows are real ROM
# addresses and the DATA rows are offsets into the RAM the map declares at 0x200000.

print("\n== machine_map(): a session with NO symbols invents no range")
r = s.start(**BOOT)
check("a session starts with no symbol file", r.get("status") == "ok", str(r.get("code")))
bare = s.machine_map()
check("symbol_coverage is an EMPTY LIST, never omitted: the absence is the answer",
      bare.get("symbol_coverage") == [], str(bare.get("symbol_coverage")))
check("and the note says which of the two reasons it is",
      "no classes" in bare.get("note", ""), bare.get("note", "")[-90:])
bare_ranges = [(e["cpu"], e["space"], e["start"], e["end"]) for e in bare.get("address_map", [])]
check("every range in the reply is one the machine declared, and each is well formed",
      bool(bare_ranges) and all(int(a, 16) <= int(b, 16) for _, _, a, b in bare_ranges),
      f"{len(bare_ranges)} entries")
s.close()

print("\n== machine_map(): symbol_coverage against a table that carries classes")
table = Path(tempfile.mkdtemp(prefix="mame-live-symbols-")) / "radendur.map"
table.write_text(
    "boot_entry\tF2034\t_TEXT\t0\tCODE\n"
    "irq_vblank\t400\t_TEXT\t0\tCODE\n"
    "score\t100\t_DATA\t100\tDATA\n"
    "lives\t2000\t_DATA\t2000\tDATA\n")
r = s.start(**BOOT, symbols=str(table), bases={"DATA": "0x200000"})
check("the map table loads with both classes",
      r.get("symbols_by_class") == {"CODE": 2, "DATA": 2},
      f"{r.get('symbols_by_class')} {r.get('code', '')}")
mm = s.machine_map()
rows = {row.get("class"): row for row in mm.get("symbol_coverage", [])}
check("symbol_coverage carries a row per class", sorted(rows) == ["CODE", "DATA"],
      str(sorted(rows)))
# THE POPULATED CASE, which is the one that hid the defect: with rows present the note that
# explains an EMPTY section is suppressed, so `sources` is the only thing left saying where
# these rows came from, and it said nothing.
check("and with rows present the symbol channel is still named in sources",
      mm.get("sources", {}).get(machine.SYMBOL_SECTION) == [machine.SYMBOL_SOURCE]
      and machine.NO_CLASSES_NOTE not in mm.get("note", ""),
      str(mm.get("sources", {}).get(machine.SYMBOL_SECTION)))
check("a class the bases DO disambiguate reports its base",
      rows.get("DATA", {}).get("base") == "0x00200000", str(rows.get("DATA")))
check("a class the bases do NOT disambiguate reports base unavailable, not an absent field",
      "base" in rows.get("CODE", {})
      and (rows.get("CODE", {}).get("base") or {}).get("available") is False,
      str(rows.get("CODE")))
check("each class names the cpu its table was given for, since a linker map names none",
      all(row.get("cpu") == ":maincpu" for row in rows.values()), str(list(rows.values()))[:80])
# THE AGREEMENT, and it is why the span is ONE constant shared with `find`: the same symbols,
# looked up one by one through the OTHER tool, must be exactly the ends of the span this one
# reports. Zero disagreement, not "close".
disagreed = []
for klass, names in (("CODE", ("boot_entry", "irq_vblank")), ("DATA", ("score", "lives"))):
    found = [int(s.symbols_find(name=n)["symbols"][0]["addr"], 16) for n in names]
    row = rows.get(klass, {})
    span = row.get("span", {})
    lo, length = int(span.get("from", "0"), 16), span.get("length", 0)
    if (lo, lo + length - 1) != (min(found), max(found)):
        disagreed.append(f"{klass}: symbols_find {min(found):#x}..{max(found):#x} vs span "
                         f"{lo:#x}..{lo + length - 1:#x}")
    if row.get("symbols") != len(names):
        disagreed.append(f"{klass}: counted {row.get('symbols')} symbols, not {len(names)}")
check("symbol_coverage and symbols_find agree about every symbol, with zero disagreement",
      not disagreed, "; ".join(disagreed))
check("and the span carries find's own caveat, from the one constant",
      "past the last symbol's own start" in rows.get("CODE", {}).get("span", {}).get("note", ""),
      str(rows.get("CODE", {}).get("span", {}).get("note"))[:60])
# THE SYMBOL TABLE CONTRIBUTES NO RANGE TO THE MAP: the same board, read with symbols and
# without, answers the same address map. A range invented from the table would show up here.
with_symbols = [(e["cpu"], e["space"], e["start"], e["end"]) for e in mm.get("address_map", [])]
check("the address map is the machine's, identical with symbols and without",
      with_symbols == bare_ranges, f"{len(with_symbols)} vs {len(bare_ranges)} entries")
check("the machine map session closes", s.close().get("closed") is True)

print("\n== the published contract: each sentence a stranger reads, against a reply")
# A DOCSTRING IS CHECKED AGAINST A REPLY, NEVER AGAINST THE CODE'S INTENTION. Every sentence
# below was once wrong while every unit test was green, because each test asserted what its
# author meant and none asked the running server. A clean store of its own, so the re-arm
# below sees only what this section declared.
isolate_state("mame-live-contract-state-")
PER_CALL = ("thread_errors", "console_reruns", "resent")
r = s.start(**BOOT, symbols=SYMBOLS)
check("the contract session starts", r.get("status") == "ok", str(r.get("code")))
first, second = s.run_for(frames=1, seconds=30.0), s.run_for(frames=1, seconds=30.0)
check("polls: one frame from the park aligns first (2), from a vblank it does not (1)",
      (first.get("polls"), second.get("polls")) == (2, 1),
      f"polls {first.get('polls')} then {second.get('polls')}")
s.breakpoint_at(ref="0x4a0")
added = s.watch_add(ref="0x203200", mode="show", length=2, fmt="u16")
in_list: dict[str, Any] = next(
    (w for w in s.watch_list().get("watches", []) if w.get("ref") == "0x203200"), {})
surveyed: dict[str, Any] = next(
    (w for w in s.step().get("watches", []) if w.get("ref") == "0x203200"), {})
shapes = [{k: w.get(k) for k in ("state", "reading")} for w in (added, in_list, surveyed)]
check("one show watch, one shape in watch_add, watch_list and the stop survey",
      shapes[0] == shapes[1] == shapes[2] and shapes[0]["state"] == "evaluated"
      and (shapes[0]["reading"] or {}).get("raw_hex") is not None, str(shapes))
t1 = s.throttle(on=True)
ran = s.lua("print(1)")
t2 = s.throttle(on=False)
check("the per-call console trio rides on `lua` and not on `throttle`",
      all(k in ran for k in PER_CALL) and not any(k in t1 or k in t2 for k in PER_CALL),
      f"throttle keys {sorted(t1)}")
check("a throttle mark's number is the console's session sequence, not a throttle count",
      t2.get("mark") != "MAME_MCP_THROTTLE#2", f"{t1.get('mark')} then {t2.get('mark')}")
saved = s.state_save(name="contract")
loaded = s.state_load(name="contract")
check("state_save and state_load carry no per-call trio",
      not any(k in saved or k in loaded for k in PER_CALL), f"load keys {sorted(loaded)}")
check("state_load's console text is `output`, and `console` is only the session's counters",
      isinstance(loaded.get("output"), str) and "console" not in loaded
      and isinstance(loaded.get("session", {}).get("console"), dict), repr(loaded.get("output")))
s.close()
r = s.start(**BOOT, symbols=SYMBOLS)
rearm = r.get("declarations", {}).get("rearm", {})
check("a raw address over the SAME build is rearmed on its cpu, never stale",
      ("0x4a0", ":maincpu") in rearm_pairs(rearm, "rearmed") and rearm.get("stale") == [],
      str(rearm))
s.breakpoint_at(ref="irq_vblank")
inherited = [(b.get("ref"), b.get("inherited"))
             for b in s.breakpoint_list().get("breakpoints", [])]
check("every list row says whether the store brought it back",
      inherited == [("0x4a0", True), ("irq_vblank", False)], str(inherited))
s.breakpoint_clear(all=True)

print("\n== cpu per call: rows armed on the sub cpu, the visible cpu left where it was")
r = s.breakpoint_at(ref="0x542", cpu="subcpu")
listed = s.breakpoint_list()
check("breakpoint_at(cpu=subcpu) arms under :subcpu and leaves the visible cpu where it was",
      r.get("cpu") == ":subcpu" and visible_of(s.cpu_info()) == ":maincpu"
      and [(b.get("ref"), b.get("cpu")) for b in listed.get("breakpoints", [])]
      == [("0x542", ":subcpu")], f"{r.get('entry')} {r.get('note')}")
r = s.watch_add(ref="0x2031fc", mode="change", length=4, cpu="subcpu")
check("watch_add(cpu=subcpu) arms under :subcpu and reads through the sub cpu's thread",
      r.get("cpu") == ":subcpu" and r.get("state") == "armed"
      and r.get("reading", {}).get("available") is True, str(r)[:200])
r = s.resume(seconds=10.0)
check("the sub cpu's row stops the machine there, named as this server's",
      r.get("verdict") == "OTHER_STOP" and r.get("cpu") == ":subcpu"
      and str(r.get("how")).startswith(("breakpoint at 0x542", "watch 0x2031fc")),
      f"{r.get('pc')} {r.get('cpu')} {r.get('how')}")
sub = {"dasm": s.disassemble(ref="0x0", length=8, cpu="subcpu"),
       "find": s.find(ref="0x0", length=16, data_hex="00000400", cpu="subcpu"),
       "history": s.history(limit=4, cpu="subcpu")}
main = {"dasm": s.disassemble(ref="0x0", length=8, cpu="maincpu"),
        "find": s.find(ref="0x0", length=16, data_hex="00000400", cpu="maincpu")}
check("each reader reads the cpu it names, and the other cpu answers otherwise (the control)",
      {r.get("cpu") for r in sub.values()} == {":subcpu"}
      and sub["find"].get("hits") == ["0x00000004"] and main["find"].get("hits") == []
      and sub["dasm"].get("lines") != main["dasm"].get("lines"),
      f"{sub['find'].get('hits')} vs {main['find'].get('hits')}")
check("the lists narrow to one cpu",
      [b.get("ref") for b in s.breakpoint_list(cpu="subcpu").get("breakpoints", [])] == ["0x542"]
      and s.breakpoint_list(cpu="maincpu").get("breakpoints") == [])
s.breakpoint_clear(all=True)
s.watch_clear(all=True)
check("both clears leave the debugger's lists empty",
      s.breakpoint_list().get("foreign") == [] and s.watch_list().get("foreign") == [])
s.focus(cpu="maincpu")

# LAST, because a stop on the sub cpu leaves it the visible one for everything after it.
print("\n== a stop on the sub cpu: its pc and its own registers, named once")
s.debug(command="bp 542:subcpu")
r = s.resume(seconds=10.0)
stop_pc = next((v for k, v in r.get("regs", {}).items() if k.lower() == "pc"), None)
check("the stop names the sub cpu and surveys the sub cpu's registers, PC at the breakpoint",
      r.get("verdict") == "OTHER_STOP" and r.get("pc") == "0x00000542" and r.get("cpu") == ":subcpu"
      and "regs_cpu" not in r and stop_pc is not None and int(stop_pc, 16) == 0x542,
      f"{r.get('pc')} {r.get('cpu')} regs PC {stop_pc}")
regs = s.registers()
pc_now = next((v for k, v in regs.get("regs", {}).items() if k.lower() == "pc"), None)
check("the registers read after it are the visible sub cpu's, and say so",
      regs.get("cpu") == ":subcpu" and pc_now is not None and int(pc_now, 16) == 0x542,
      f"{regs.get('cpu')} pc {pc_now}")
main_regs = s.registers(cpu="maincpu")
main_pc = next((v for k, v in main_regs.get("regs", {}).items() if k.lower() == "pc"), None)
check("the main cpu's registers are read by naming it, at another pc (the control)",
      main_regs.get("cpu") == ":maincpu" and main_pc is not None and int(main_pc, 16) != 0x542,
      f"{main_regs.get('cpu')} pc {main_pc}")
check("cpu_info names the sub cpu visible", visible_of(s.cpu_info()) == ":subcpu")

print("\n== focus: the stub's `Hc` shows another cpu, read back, and nothing runs")
r = s.focus(cpu="maincpu")
check("focus back to the main cpu goes through the stub and proves nothing ran",
      r.get("status") == "ok" and (r.get("cpu"), r.get("was"), r.get("via"), r.get("machine_ran"))
      == (":maincpu", ":subcpu", "stub", False) and r.get("unchanged") == [":maincpu", ":subcpu"],
      str(r.get("summary")))
check("cpu_info reads the same visible cpu", visible_of(s.cpu_info()) == ":maincpu")
r = s.focus(cpu="nosuchcpu")
check("a cpu the machine lacks is unknown_ref naming its cpus",
      r.get("code") == "unknown_ref" and r.get("cpus") == [":maincpu", ":subcpu"], str(r))
s.focus(cpu="subcpu")
dump = Path(tempfile.mkdtemp(prefix="mame-live-")) / "sub-vectors.bin"
r = s.memdump(ref="0x0", length=16, dest=str(dump))
check("memdump with the sub cpu visible saves its memory and checks it through its thread",
      r.get("status") == "ok" and r.get("cpu") == ":subcpu" and dump.is_file(), str(r)[:160])
# LIVE ON THE MAIN CPU: a stop there, so a typed `focus subcpu` ignores the cpu MAME runs.
s.focus(cpu="maincpu")
s.debug(command="bpclear")          # the sub cpu's typed row, which would cut the run first
landed = s.run_to(ref="irq_vblank", control="0x4a0", seconds=10.0)
check("a run to the vblank handler stops on the main cpu",
      (landed.get("verdict"), landed.get("cpu")) == ("TARGET", ":maincpu"),
      str(landed.get("summary")))
r = s.debug(command="focus subcpu")
check("a focus typed through debug that ignores the live cpu is read back, and its run said",
      (r.get("visible_cpu"), r.get("ignored")) == (":subcpu", [":maincpu"])
      and "so it ran until :subcpu executed" in str(r.get("note")),
      f"{r.get('visible_cpu')} {r.get('ignored')} {r.get('note')}")
r = s.debug(command="observe maincpu")
check("an observe typed through debug empties the ignored set",
      r.get("ignored") == [] and ignored_of(s.cpu_info()) == [], str(r)[:160])
# LIVE ON THE SUB CPU, the main one visible through the stub: the same line runs nothing.
s.focus(cpu="maincpu")
r = s.debug(command="focus subcpu")
check("a focus typed through debug that ignores a cpu MAME is not live on runs nothing",
      (r.get("visible_cpu"), r.get("ignored")) == (":maincpu", [":maincpu"])
      and "was not live, so nothing ran" in str(r.get("note")), str(r)[:240])
s.debug(command="observe maincpu")
check("the contract session closes", s.close().get("closed") is True)

finish("LIVE CHECK")
