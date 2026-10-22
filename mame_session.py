"""The session's own tools beside `start`: `status`, what the session is now; `close`, its end
with the last words of each channel; and `rom_check`, the known-answer read that says the session
is still the one started. The launch and the boot are `mame_launch`'s.
"""

from __future__ import annotations

from typing import Any

from scry_core import narrowing, prose
from scry_core import progress as mprogress
from scry_core.reply_contract import or_unavailable, unavailable

import gdb_session as gs
import mame_cpus as cpus
import mame_declarations as dec
import mame_envelope as menvelope
import mame_idle as idle
import mame_inputs as inputs
import mame_launch as launch
import mame_read as read
import mame_running as running
import mame_state as st
import mame_transport as transport
from mame_state import STATE

#: How a clean close that left MAME's last words out asks for them, and that it is the only way:
#: the scratch they were read from goes with this close.
CLOSE_HOW = ("close(detail=True) keeps the channels' last words on a clean quit too; once a close "
             "has answered they are gone with the scratch")


def close(progress: mprogress.Progress = mprogress.no_progress,
          detail: bool = False) -> dict[str, Any]:
    """The body of the `close` tool. The `session` block describes the state as it was
    BEFORE closing: built after the kill it would read `altered: false` about a session
    that had been written to. The last words come back when the end was not a clean `quit`
    with exit code 0, or with `detail`: a clean quit's are the console's echo and the error
    log's routine lines, which a caller asks for before closing if it wants them."""
    # WHAT NOBODY READ IS COUNTED FIRST, so the session block below says of the console
    # what the log shows and not only what the lua-family readers happened to read.
    if STATE.scratch is not None:
        transport.count_unread(STATE.scratch)
    # WHOLE: the block of the session this call ends is its last account, counts included.
    before = menvelope.session_block(whole=True)
    # THE PIPE IS EMPTIED BEFORE THE EXIT IS ASKED FOR. A chunk left unevaluated is one
    # MAME's Lua state still holds at `quit`, and its collector took one down on the way
    # out (SIGSEGV in `lua_engine::close`); a clean exit is what writes `cfg/` and `nvram/`,
    # so this is spent before the exit and never after. What could not be drained is SAID,
    # so an ugly exit code has a cause beside it instead of being a mystery.
    pending_before, drained = (0, 0)
    was_running = STATE.ses is not None and STATE.ses.running
    # A BROKEN SESSION IS ASKED NOTHING on the way out (`kill` skips its `quit` too): `close`
    # is the one way out of that state, so it may not fail on a channel nobody can believe.
    broken = STATE.broken
    if (STATE.ses is not None and STATE.scratch is not None and not broken
            and STATE.machine_alive()):
        try:
            pending_before, drained = transport.drain(STATE.ses, STATE.scratch)
        except gs.SessionError:
            pending_before, drained = transport.pending_lines(STATE.scratch), 0
    # THE SPEED IS READ BEFORE THE KILL, while the machine still runs: a watched run ended
    # by `close` held its window open until now, and `quit` is about to
    # end it. Nothing when no run was open, and a clock that could not be read is said in
    # the field: `close` is the one way out and may not fail on decoration.
    speed = running.run_speed(STATE.ses) if STATE.ses is not None and not broken else {}
    # A THROTTLE IS JUDGED BEFORE THE SCRATCH GOES, after the drain that may have run its line:
    # its mark lives in the error log the kill deletes, and this is the session's last reply.
    if STATE.scratch is not None:
        running.settle_logged(STATE.scratch)
    not_applied = [dict(r) for r in STATE.throttles_not_applied]
    # THE LAST WORDS ARE READ BEFORE THE SCRATCH GOES: a crash on the way out lived only in
    # `stdout.log`, and the kill deletes the directory, so the reply is where they survive.
    tails = {"stdout_tail": launch.stdout_tail(STATE.scratch),
             "errorlog_tail": launch.channel_tail(STATE.scratch, "emulator")}
    ended = STATE.kill(progress)
    if ended["ended_by"] == "none":
        reply = menvelope.envelope({"closed": False, **ended,
                                    "note": "there was no session to close"})
    else:
        clean = ended["ended_by"] == "quit" and ended.get("exit_code") == 0
        words = tails if detail or not clean else narrowing.omission(list(tails), CLOSE_HOW)
        reply = menvelope.envelope({"closed": True, **words, **ended})
    reply.update(speed)
    if ended["ended_by"] != "none":
        reply["console_pending_before"] = pending_before
        reply["console_drained"] = drained
        if pending_before - drained:
            # A RUNNING MACHINE READS ITS OWN PIPE and is never stepped here, so the two
            # cases are said apart: nothing could be spent, versus nothing worked.
            why = ("the machine was still RUNNING, which reads its own pipe frame by frame, "
                   "so no step was spent on them here"
                   if was_running else
                   "stepping the machine did not get the console to evaluate them")
            st.add_note(reply,
                f"{prose.counted(pending_before - drained, 'console line')} "
                f"{prose.agrees(pending_before - drained, 'was', 'were')} still unevaluated at the "
                f"exit ({why}): MAME's Lua collector has torn one of those down on the way out "
                "(SIGSEGV in `lua_engine::close`), so a non-zero exit code here has that as its "
                "likely cause")
    # THE BLOCK OF THE STATE BEFORE THE CLOSE, kept by `mame_mcp.tool` (`close` is
    # registered with `session_before`), which puts it last.
    reply["session"] = ({**before, "throttles_not_applied": not_applied} if not_applied
                        else before)
    return reply


def status() -> dict[str, Any]:
    """The body of the `status` tool: whether a machine is alive, which one, and what the
    session holds. It asks a broken session nothing and reports the latch instead."""
    if STATE.ses is None or STATE.proc is None:
        why = idle.IDLE.note()
        return menvelope.envelope({**({"note": why} if why else {})})
    code = STATE.proc.poll()
    if code is not None:
        return menvelope.envelope({"exit_code": code,
                                   "note": "MAME exited under this session: `close` collects the "
                                   "exit code and the last lines of each channel before the "
                                   "scratch is deleted"})
    ses, scratch = STATE.live()
    if not ses.broken:
        try:
            running.observe_stop(ses, scratch)
        except gs.SessionError as e:
            # THIS IS WHERE A LATCH IS READ, so one the observation made -- or the failure
            # that makes it, latched here -- is reported below as `broken`, never answered as
            # the refusal every other tool gives.
            ses.latch(f"the stop observation failed: {e}")
    broken = ses.broken     # read again: the observation may have latched it
    # Read BEFORE `broken` is read for the reply: a `cpulist` that times out latches it.
    tags = list(STATE.cpus) if broken else cpus.cpu_list(ses)
    pc: str | dict[str, Any] = unavailable(
        "the machine is running, so its pc moves on: the last stop's is `last_stop.pc`")
    if not (ses.running or ses.broken):
        try:
            pc = st.hex_addr(ses.current_pc())
        except gs.SessionError as e:
            ses.latch(f"reading the pc failed: {e}")
    if ses.broken:
        pc = unavailable("the session is broken, so the pc is not read: the last stop's is "
                         "`last_stop.pc`")
    broken = ses.broken
    last = STATE.as_of()
    # `broken` AS THE SESSION BLOCK SAYS IT: present when the session broke, absent when not.
    # `pc` IS THE MACHINE'S, READ NOW, and only then: while it runs or once the session broke
    # it is unavailable with why, and the last stop's is `last_stop.pc`. `alive` and `running`
    # are the session block's, which every reply carries.
    return menvelope.envelope({
        **({"broken": broken} if broken else {}),
        "system": STATE.system,
        "pid": STATE.proc.pid,
        "stub_port": STATE.port,
        "scratch_dir": str(STATE.scratch),
        "state_dir": STATE.state_dir,
        "cfg": launch.cfg_report(),
        "debugger": launch.debugger_report(),
        "presence": STATE.presence_shown(),
        "fingerprint": STATE.fingerprint(),
        # BY CPU TAG: a flat table's names no cpu, and is `fingerprint`.
        "fingerprints": {cpu: f for cpu, f in STATE.fingerprints.items() if cpu is not None},
        **launch.channels(),
        "pc": pc,
        "last_stop": last,
        # WHAT THIS SERVER ARMED IN THE DEBUGGER, one shape per family: each `ref` and its `cpu`,
        # under one key so a family's name never collides with a survey's (`watches`).
        "in_debugger": {
            "breakpoints": [dec.owner_fields(r["owner"]) for r in sorted(
                STATE.breakpoints.values(), key=lambda r: (r["addr"], r["owner"][0]))],
            "watches": [dec.owner_fields(o) for o in STATE.armed_watches],
            "regpoints": [dec.owner_fields(o) for o in STATE.regpoints]},
        "threads": {str(tid): tag for tid, tag in ses.threads.items()},
        "cpu_tags": tags,
        # THE PIPE'S DEPTH, readable before it bites: a line the console has not evaluated
        # is one MAME's Lua state still holds, and a backlog took a `quit` down with it.
        "console_pending": transport.pending_lines(scratch),
        **running.still_pending(scratch),
        **read.frame_fields(),
    })


def rom_check(ses: gs.Session, reference_rom: str, reference_addr: str, reference_base: str,
              cpu: str) -> dict[str, Any]:
    """The body of the `rom_check` tool: the known-answer read on `cpu`, repeated for
    determinism, and the cost of a query."""
    addr = inputs.hex_arg("reference_addr", reference_addr)
    on, thread = cpus.thread_for(ses, cpu)
    try:
        ses.self_check(launch.reference_rom_file(reference_rom).read_bytes(), addr,
                       base=inputs.hex_arg("reference_base", reference_base), thread=thread)
    except gs.Mismatch as e:
        # THE IMAGE IS ONE CPU'S: a mismatch names the cpu that was read, so an image checked
        # against the wrong cpu reads as that and not as a session that lies. A verdict about
        # the machine, answered like `state_load`'s own ROM check.
        raise st.Invalid("readback_refused", f"read on {on}: {e}", cpu=on) from e
    return menvelope.envelope({
        "rom_check": "OK",
        "deterministic": ses.determinism(addr, thread=thread),
        "query_s": st.measured_s(ses.cost_per_query(addr, times=50, thread=thread)),
        "cpu": or_unavailable(on, st.NO_CPU_READ_WHY),
    })
