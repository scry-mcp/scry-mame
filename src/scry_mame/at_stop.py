"""`screen_wait` judged at a declared stop (`on_breakpoint`, `on_watch`): Lua filters, the server
judges.

A gate installed in MAME's Lua does the work a round trip per firing would cost. At each stop
(`emu.register_periodic` runs at the top of the debugger's wait loop) it tells the named row's
firing from any other stop: a breakpoint's by the pc, a change watch's by its bytes differing
from the ones seen at the stop before. It counts the firing, evaluates the condition and, when it
holds, opens a judgement window and lets the machine run on. The window spans two frame
notifiers, because a notifier reads the frame before the one just finished (`film.py`); at each
the gate compares the picture with the ones the server already rejected in this wait and, on a
new one, stops the machine. Only then does the server read the screen and judge it with the one
map code; no match, it releases and the gate files that picture as rejected.

The run is released from the console (`g`), so the stub sends no stop packet: the server learns
of a stop from the gate's state file, written through a rename, and of a stop the gate did not
make (another declared row) from the same file.
"""

from __future__ import annotations

import itertools
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scry_core import progress as mprogress
from scry_core import reply_contract as contract
from scry_core import stop_wait
from scry_core import value_format as vf
from scry_core.prose import counted

from scry_mame import advance, arming, capture, chunk, cpus, running, transport
from scry_mame import declarations as dec
from scry_mame import envelope as menvelope
from scry_mame import gdb_session as gs
from scry_mame import state as st

#: Pictures a wait remembers as rejected; the oldest goes first.
REJECTED_MAX = 16
#: The notifiers a firing's judgement window spans (see the module's docstring).
WINDOW_FRAMES = 2
#: How often the server reads the gate's state file while the machine runs.
POLL_S = 0.01
#: Each wait's gate has files of its own, so a gate a failed install left registered never
#: reads the next wait's word.
_WAITS = itertools.count(1)


def files_of(scratch: Path, n: int) -> tuple[Path, Path]:
    """Wait `n`'s state file and control file."""
    return scratch / f"stop-wait-{n}.state", scratch / f"stop-wait-{n}.ctl"

GATE = """-- Written by the mame MCP server: the gate of one screen_wait on a declared stop.
local state_path, ctl_path = %(state)s, %(ctl)s
local cpu = manager.machine.devices[%(cpu)s]
local dbg = manager.machine.debugger
local screen = nil
for _, s in pairs(manager.machine.screens) do screen = s break end
local sp = cpu.spaces["program"]
%(beam)s
local T = {kind = %(kind)s, pc = %(pc)d, waddr = %(waddr)d, wwidth = %(wwidth)d, firings = 0,
  examined = 0, window = 0, line = -1, seq = 0, candidate = nil, waiting = false,
  rejected = {}, lastt = nil, mode = "wait", token = "", held = ""}
local missing = nil
for _, name in ipairs(%(registers)s) do
  if cpu.state[name] == nil then missing = name end
end
local function bytes()
  local t = {}
  for i = 0, T.wwidth - 1 do t[#t + 1] = string.char(sp:read_u8(T.waddr + i)) end
  return table.concat(t)
end
local before = T.kind == "watch" and bytes() or nil
-- A change watch also stops on a write of the value already there, so its firing is the
-- console's own line (`Stopped at watchpoint N writing V to A`), read since the last stop, or
-- else its bytes differing.
local function lines() local ok, n = pcall(function() return #dbg.consolelog end)
  return ok and n or 0 end
local read_to = lines()
local function watch_logged()
  local ok, hit = pcall(function()
    local n, found = #dbg.consolelog, false
    for i = read_to + 1, n do
      local a = dbg.consolelog[i]:match("Stopped at watchpoint %%x+ writing %%x+ to (%%x+)")
      if a ~= nil and tonumber(a, 16) >= T.waddr and tonumber(a, 16) < T.waddr + T.wwidth then
        found = true
      end
    end
    read_to = n
    return found
  end)
  return ok and hit
end
local function condition() return %(condition)s end
local function now() return manager.machine.time:as_double() end
local function save(outcome)
  T.seq = T.seq + 1
  local f = assert(io.open(state_path .. ".tmp", "w"))
  f:write(string.format("seq=%%d outcome=%%s firings=%%d examined=%%d line=%%d pc=%%x\\n", T.seq,
    outcome, T.firings, T.examined, T.line, cpu.state["CURPC"].value))
  f:close()
  -- Windows' rename refuses an existing target.
  if not os.rename(state_path .. ".tmp", state_path) then
    os.remove(state_path)
    assert(os.rename(state_path .. ".tmp", state_path))
  end
end
-- The server's word: nothing until `go N` (the console's reader steps the machine after the
-- install, and that stop is nobody's firing); each new N releases a stop held for it; `off`
-- ends the gate and lets its pictures go.
local function control()
  if T.mode ~= "off" then
    local f = io.open(ctl_path, "r")
    if f then
      local word, n = (f:read("l") or ""):match("^(%%a+)%%s*(%%d*)$")
      f:close()
      if word == "off" then
        T.mode, T.rejected, T.candidate = "off", {}, nil
        save("off")
      elseif word == "go" then T.mode, T.token = "go", n end
    end
  end
  return T.mode
end
local function hold(outcome) T.waiting, T.held = true, T.token save(outcome) end
if missing ~= nil then save("noregister") return end
emu.register_periodic(function()
  local mode = control()
  if mode ~= "go" then
    if mode == "wait" and dbg.execution_state == "stop" then T.lastt = now() end
    return
  end
  if T.waiting then
    if T.token == T.held then return end
    T.waiting = false
    -- Released: everything up to here was the server's (its reads step the machine), so the
    -- stop it stands at, the console's lines and the watched bytes are taken as seen.
    T.lastt, read_to = now(), lines()
    if T.kind == "watch" then before = bytes() end
    if T.candidate ~= nil then
      table.insert(T.rejected, T.candidate)
      if #T.rejected > %(rejected_max)d then table.remove(T.rejected, 1) end
      T.candidate = nil
    end
  end
  if dbg.execution_state ~= "stop" then return end
  local t = now()
  if T.lastt == t then return end
  T.lastt = t
  if T.candidate ~= nil then hold("candidate") return end
  local fired
  if T.kind == "breakpoint" then
    fired = cpu.state["CURPC"].value == T.pc
  else
    local b = bytes()
    fired, before = watch_logged() or b ~= before, b
  end
  if not fired then hold("other") return end
  T.firings = T.firings + 1
  if condition() then T.window = %(window)d T.line = beam_line() end
  dbg.execution_state = "run"
end)
emu.register_frame_done(function()
  if control() ~= "go" or T.waiting or T.candidate ~= nil or T.window <= 0 then return end
  T.window = T.window - 1
  T.examined = T.examined + 1
  local px = screen:pixels()
  for _, r in ipairs(T.rejected) do if r == px then return end end
  T.candidate = px
  dbg.execution_state = "stop"
end)
save("installed")
"""

_STATE = re.compile(r"^seq=(\d+) outcome=(\w+) firings=(\d+) examined=(\d+) line=(-?\d+) "
                    r"pc=([0-9a-f]+)$")


def declared_row(ses: gs.Session, spec: stop_wait.StopWait,
                 cpu: str) -> tuple[dec.Declaration, int]:
    """The declaration `spec` names and its address; one that cannot stop where the gate can
    tell it is refused before anything runs."""
    on = cpus.chosen(ses, cpu)
    by = ("pointer" if vf.parse_pointer(spec.ref) is not None
          else "address" if spec.ref.lower().startswith("0x") else "symbol")
    store = arming.store()
    held = store.held_ref(spec.ref, by, (spec.kind,), on)
    if held is None:
        mine = [d.ref for d in store.declarations() if d.kind == spec.kind and d.cpu == on]
        raise st.Invalid("unknown_ref",
            f"{spec.ref!r} matches no {spec.kind} declaration on {on}: `on_{spec.kind}` names a "
            f"row `declaration_list` lists. The {spec.kind} declarations held there: "
            + (", ".join(repr(r) for r in mine) if mine else "none at all"))
    decl = next(d for d in store.declarations()
                if d.kind == spec.kind and d.cpu == on and d.ref == held)
    if spec.kind == "breakpoint" and decl.role != "stop":
        raise st.Invalid("bad_argument", f"the breakpoint {held!r} is a `{decl.role}`, which "
                         "counts its hits and never stops the machine")
    if spec.kind == "watch" and decl.watch_mode != "change":
        raise st.Invalid("bad_argument", f"the watch {held!r} is a `{decl.watch_mode}` watch, "
                         "which never stops the machine: only a `change` watch fires")
    if decl.by == "pointer":
        raise st.Invalid("bad_argument", f"the watch {held!r} follows a pointer, and its bytes "
                         "move between stops, so its firing cannot be told from another stop")
    addr = arming.resolve_decl(decl).addr
    if addr is None:
        raise st.Invalid("bad_argument", f"{held!r} resolves to no address in this build, so "
                         "it arms nothing and can never fire")
    return decl, addr


def condition_lua(terms: tuple[stop_wait.Term, ...], place: Callable[[str], int]) -> str:
    """The condition as a Lua expression over `cpu` and `sp`; `place` turns a memory ref into
    its address."""
    reads = {1: "read_u8", 2: "read_u16", 4: "read_u32"}
    lua_op = {"!=": "~="}
    parts = [(f'cpu.state["{t.operand}"].value' if t.size == 0
              else f"sp:{reads[t.size]}({place(t.operand):#x})")
             + f" {lua_op.get(t.op, t.op)} {t.value:#x}" for t in terms]
    return " and ".join(parts) if parts else "true"


def gate(state: Path, control: Path, spec: stop_wait.StopWait, decl: dec.Declaration, addr: int,
         cpu: str, place: Callable[[str], int]) -> str:
    """The gate's chunk for one wait, writing `state` and reading `control`."""
    registers = [t.operand for t in spec.condition if t.size == 0]
    return GATE % {
        "state": transport.lua_string(str(state)),
        "ctl": transport.lua_string(str(control)),
        "cpu": transport.lua_string(cpu), "beam": capture.BEAM_LINE_LUA,
        "kind": transport.lua_string(spec.kind), "pc": addr if spec.kind == "breakpoint" else -1,
        "waddr": addr if spec.kind == "watch" else 0,
        "wwidth": (decl.width or 1) if spec.kind == "watch" else 0,
        "registers": "{" + ", ".join(transport.lua_string(r) for r in registers) + "}",
        "condition": condition_lua(spec.condition, place),
        "rejected_max": REJECTED_MAX, "window": WINDOW_FRAMES}


def read_state(path: Path) -> dict[str, Any] | None:
    """The gate's last state, or None before it wrote one."""
    try:
        text = path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return None
    m = _STATE.match(text)
    if m is None:
        raise st.Invalid("unexpected_answer", f"the wait's gate wrote {text!r}, which is not its "
                         "state line")
    return {"seq": int(m[1]), "outcome": m[2], "firings": int(m[3]), "examined": int(m[4]),
            "line": int(m[5]), "pc": int(m[6], 16)}


def screen_wait_at(ses: gs.Session, scratch: Path, spec: stop_wait.StopWait, cpu: str,
                   judge: Callable[[], dict[str, Any] | None], predicate: str, said: str,
                   seconds: float, progress: mprogress.Progress,
                   place: Callable[[str], int]) -> dict[str, Any]:
    """The wait itself; `judge` reads the screen at a stop and answers the hit or None."""
    decl, addr = declared_row(ses, spec, cpu)
    on = cpus.chosen(ses, cpu) or ""
    state, control = files_of(scratch, next(_WAITS))
    script = gate(state, control, spec, decl, addr, on, place)
    measured = advance.clock_before(ses)
    began = time.monotonic()
    clock = mprogress.Ticker(seconds, progress)
    released = False
    try:
        chunk.run(ses, scratch, script, seconds, progress, "screen wait's gate")
        last = read_state(state)
        if last is not None and last["outcome"] == "noregister":
            names = sorted({t.operand for t in spec.condition if t.size == 0})
            raise st.Invalid("bad_argument", f"the condition names a register {on} does not "
                             f"have, among {names}", cpu=on)
        if last is None or last["outcome"] != "installed":
            raise st.Invalid("unexpected_answer", "the wait's gate wrote no state after its "
                             "install")
        token = 0
        with advance.console_run(ses):
            while True:
                token += 1
                control.write_text(f"go {token}\n", encoding="ascii")
                released = True
                ses.monitor("g")
                while True:
                    seen = read_state(state)
                    if seen is not None and seen["seq"] > last["seq"]:
                        last, released = seen, False
                        break
                    if clock.expired():
                        control.write_text("off\n", encoding="ascii")
                        released = False
                        return _bound(ses, scratch, state, spec, predicate, said, seconds,
                                      began, measured)
                    clock.tick("screen_wait {said} at {ref}: {elapsed:.0f}s of {bound:g}s",
                               said=said, ref=decl.ref, bound=seconds)
                    time.sleep(POLL_S)
                if last["outcome"] == "other":
                    stop = _record(ses, scratch)
                    raise st.Invalid("wait_stopped",
                        f"a stop the wait did not make ended it before {said} was judged, at "
                        f"{st.hex_addr(last['pc'])}", firings=last["firings"],
                        frames_examined=last["examined"], **stop)
                hit = judge()
                if hit is not None:
                    surveyed = running.survey(ses, scratch)
                    return running.finish_stop(ses, surveyed, _cause(surveyed), **_fields(
                        contract.TARGET, spec, predicate, last, began), **measured(), **hit)
    except BaseException:
        if released:
            advance.left_running(ses)     # let go and not seen to stop: `stop` brings it back
        raise
    finally:
        control.write_text("off\n", encoding="ascii")


def _cause(surveyed: dict[str, Any]) -> str:
    return running.attribute(int(surveyed["pc"], 16), surveyed["cpu"])


def _record(ses: gs.Session, scratch: Path) -> dict[str, Any]:
    """The stop a refusal ends at, recorded, as the fields a refusal may carry."""
    surveyed = running.survey(ses, scratch)
    stop = running.finish_stop(ses, surveyed, _cause(surveyed))
    return {k: v for k, v in stop.items() if k not in contract.RESERVED}


def _fields(verdict: str, spec: stop_wait.StopWait, predicate: str, last: dict[str, Any],
            began: float) -> dict[str, Any]:
    line = last["line"]
    return {"verdict": verdict, "predicate": predicate, "already": False,
            "waited_s": round(time.monotonic() - began, 1),
            **stop_wait.fields(spec, last["firings"], last["examined"],
                               line if line >= 0 else contract.unavailable(
                                   "no firing met its condition, so none was placed"))}


#: How long the bound waits for the gate to write its final counts once told `off`.
FINAL_WAIT_S = 2.0


def _final(state: Path) -> dict[str, Any]:
    """The counts the gate writes when it reads `off`, at the next hook; else its last ones."""
    until = time.monotonic() + FINAL_WAIT_S
    last = read_state(state)
    while (last is None or last["outcome"] != "off") and time.monotonic() < until:
        time.sleep(POLL_S)
        last = read_state(state)
    return last or {"firings": 0, "examined": 0, "line": -1}


def _bound(ses: gs.Session, scratch: Path, state: Path, spec: stop_wait.StopWait,
           predicate: str, said: str, seconds: float, began: float,
           measured: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """The bound ran out with the machine running: stop it (the gate already told `off`),
    then `TIMEOUT` on that stop's reply, or `never_fired`."""
    advance.left_running(ses)
    stopped = running.stop(ses, scratch)
    if stopped.get("status") != "ok":
        return stopped
    last = _final(state)
    if not last["firings"]:
        raise stop_wait.never_fired(spec, seconds, firings=0, frames_examined=last["examined"],
                                    **{k: v for k, v in stopped.items()
                                       if k not in contract.RESERVED})
    note = (f"{said} was not found after any of {counted(last['firings'], 'firing')} of the "
            f"{spec.kind} {spec.ref!r} within {seconds:g} s" if last["examined"] else
            f"none of {counted(last['firings'], 'firing')} of the {spec.kind} {spec.ref!r} "
            f"within {seconds:g} s met the condition, so no screen was judged")
    return menvelope.envelope({**stopped, **_fields(contract.TIMEOUT, spec, predicate, last,
                                                    began), **measured(), "note": note})
