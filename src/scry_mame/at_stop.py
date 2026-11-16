"""`screen_wait` judged at a declared stop (`on_breakpoint`, `on_watch`): Lua filters, the server
judges.

A gate installed in MAME's Lua does the work a round trip per firing would cost. At each stop
(`emu.register_periodic` runs at the top of the debugger's wait loop) it tells the named row's
firing from any other stop: a breakpoint's by the pc, a change watch's by its bytes differing
from the ones seen at the stop before. It counts the firing, evaluates the condition and, when it
holds, opens a judgement window and lets the machine run on. The window spans two frame ends
(`emu.register_frame_done`), because once a frame ends `screen:pixels()` reads the buffer the
next frame draws into, which still holds the frame before: the frame the firing ran in is read at
the second frame end, as a frame notifier reads it (`film.py`). At each the gate compares the
picture with the ones the server already rejected in this wait and, on a new one, stops the
machine. Only then does the server read the screen and judge it with the one
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

from scry_mame import advance, arming, capture, chunk, cpus, lua_source, running, transport
from scry_mame import declarations as dec
from scry_mame import envelope as menvelope
from scry_mame import gdb_session as gs
from scry_mame import state as st

#: Pictures a wait remembers as rejected; the oldest goes first.
REJECTED_MAX = 16
#: The frame ends a firing's judgement window spans (see the module's docstring).
WINDOW_FRAMES = 2
#: How often the server reads the gate's state file while the machine runs.
POLL_S = 0.01
#: Each wait's gate has files of its own, so a gate a failed install left registered never
#: reads the next wait's word.
_WAITS = itertools.count(1)


def files_of(scratch: Path, n: int) -> tuple[Path, Path]:
    """Wait `n`'s state file and control file."""
    return scratch / f"stop-wait-{n}.state", scratch / f"stop-wait-{n}.ctl"


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
        raise stop_wait.no_such_row(spec, [d.ref for d in store.declarations()
                                           if d.kind == spec.kind and d.cpu == on], cpu=on or "")
    decl = next(d for d in store.declarations()
                if d.kind == spec.kind and d.cpu == on and d.ref == held)
    if spec.kind == "breakpoint" and decl.role != "stop":
        raise st.Invalid("bad_argument", f"the breakpoint {held!r} is a `{decl.role}`, which "
                         "counts its hits and never stops the machine")
    if spec.kind == "watch" and decl.watch_mode != "change":
        raise stop_wait.not_a_change_watch(held, str(decl.watch_mode))
    if decl.by == "pointer":
        raise stop_wait.follows_pointer(held)
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
    return lua_source.render(
        "at-stop-gate", state=str(state), ctl=str(control), cpu=cpu,
        beam=lua_source.Code(capture.BEAM_LINE_LUA), kind=spec.kind,
        pc=addr if spec.kind == "breakpoint" else -1,
        waddr=addr if spec.kind == "watch" else 0,
        wwidth=(decl.width or 1) if spec.kind == "watch" else 0,
        registers=lua_source.Code("{" + ", ".join(transport.lua_string(r) for r in registers)
                                  + "}"),
        condition=lua_source.Code(condition_lua(spec.condition, place)),
        rejected_max=REJECTED_MAX, window=WINDOW_FRAMES)


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
    note = stop_wait.timeout_note(said, spec, last["firings"], last["examined"], seconds,
                                  judged_at="at the frame's end")
    return menvelope.envelope({**stopped, **_fields(contract.TIMEOUT, spec, predicate, last,
                                                    began), **measured(), "note": note})
