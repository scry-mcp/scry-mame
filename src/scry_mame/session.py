"""`status`, `close` and `rom_check`: the session tools beside `start`."""

from __future__ import annotations

from typing import Any

from scry_core import narrowing, prose, session_block
from scry_core import progress as mprogress
from scry_core.reply_contract import or_unavailable, unavailable

from scry_mame import cpus, idle, inputs, launch, read, running, transport
from scry_mame import declarations as dec
from scry_mame import envelope as menvelope
from scry_mame import gdb_session as gs
from scry_mame import state as st
from scry_mame.state import STATE

#: The last words are read from the scratch, which this close deletes.
CLOSE_HOW = ("close(detail=True) keeps the channels' last words on a clean quit too; once a close "
             "has answered they are gone with the scratch")


def close(progress: mprogress.Progress = mprogress.no_progress,
          detail: bool = False) -> dict[str, Any]:
    """The body of the `close` tool; its `session` block is the state AFTER the kill.

    The last words come back unless the end was a clean `quit` with exit code 0, or with `detail`.
    """
    # Counted first so the console tallies carried out below are the log's.
    if STATE.scratch is not None:
        transport.count_unread(STATE.scratch)
    before = menvelope.session_block(whole=True)
    # Drain before `quit`: an unevaluated chunk in MAME's Lua state crashed its collector on
    # exit (SIGSEGV in `lua_engine::close`), and a clean exit is what writes `cfg/` and `nvram/`.
    pending_before, drained = (0, 0)
    was_running = STATE.ses is not None and STATE.ses.running
    # A broken session is asked nothing: `close` is its only way out.
    broken = STATE.broken
    if (STATE.ses is not None and STATE.scratch is not None and not broken
            and STATE.machine_alive()):
        try:
            pending_before, drained = transport.drain(STATE.ses, STATE.scratch)
        except gs.SessionError:
            pending_before, drained = transport.pending_lines(STATE.scratch), 0
    # Read while the machine still runs; `close` may not fail on this decoration.
    speed = running.run_speed(STATE.ses) if STATE.ses is not None and not broken else {}
    # After the drain, which may have run its line; its mark is in the error log the kill deletes.
    if STATE.scratch is not None:
        running.settle_logged(STATE.scratch)
    not_applied = [dict(r) for r in STATE.throttles_not_applied]
    # A crash on the way out lives only in `stdout.log`, which the kill deletes.
    tails = {"stdout_tail": launch.stdout_tail(STATE.scratch),
             "errorlog_tail": launch.channel_tail(STATE.scratch, "emulator")}
    ended = STATE.kill(progress)
    if ended["ended_by"] == "none":
        reply = menvelope.envelope({"closed": False, **ended,
                                    "note": session_block.NO_SESSION_CLOSE_NOTE})
    else:
        clean = ended["ended_by"] == "quit" and ended.get("exit_code") == 0
        words = tails if detail or not clean else narrowing.omission(list(tails), CLOSE_HOW)
        reply = menvelope.envelope({"closed": True, **words, **ended})
    reply.update(speed)
    if ended["ended_by"] != "none":
        reply["console_pending_before"] = pending_before
        reply["console_drained"] = drained
        if pending_before - drained:
            # A running machine reads its own pipe and is never stepped here.
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
    # What the kill resets is read after it, so the block is a no-session one; what it cannot
    # reset (a doubt about the session's reports) rides along.
    carried = {k: v for k, v in before.items() if k == "console" and any(v.values())}
    if not_applied:
        carried["throttles_not_applied"] = not_applied
    after = menvelope.session_block(whole=True)
    reply["session"] = {**{k: after[k] for k in ("alive", "running", "altered")}, **carried}
    return reply


def status() -> dict[str, Any]:
    """The body of the `status` tool; a broken session is not asked, its latch is reported."""
    if STATE.ses is None or STATE.proc is None:
        why = idle.IDLE.note()
        return menvelope.envelope({"last_stop": STATE.as_of(), **({"note": why} if why else {})})
    code = STATE.proc.poll()
    if code is not None:
        return menvelope.envelope({"exit_code": code, "last_stop": STATE.as_of(),
                                   "note": "MAME exited under this session: `close` collects the "
                                   "exit code and the last lines of each channel before the "
                                   "scratch is deleted"})
    ses, scratch = STATE.live()
    if not ses.broken:
        try:
            running.observe_stop(ses, scratch)
        except gs.SessionError as e:
            # Latched here so it is reported below as `broken`, not refused as other tools do.
            ses.latch(f"the stop observation failed: {e}")
    broken = ses.broken     # read again: the observation may have latched it
    # Before `broken` is read for the reply: a `cpulist` that times out latches it.
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
    # `pc` is read now or unavailable; the last stop's is `last_stop.pc`.
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
        # By cpu tag; the flat table names no cpu and is `fingerprint`.
        "fingerprints": {cpu: f for cpu, f in STATE.fingerprints.items() if cpu is not None},
        **launch.channels(),
        "pc": pc,
        "last_stop": last,
        # One key, so a family's name never collides with a survey's (`watches`).
        "in_debugger": {
            "breakpoints": [dec.owner_fields(r["owner"]) for r in sorted(
                STATE.breakpoints.values(), key=lambda r: (r["addr"], r["owner"][0]))],
            "watches": [dec.owner_fields(o) for o in STATE.armed_watches],
            "regpoints": [dec.owner_fields(o) for o in STATE.regpoints]},
        "threads": {str(tid): tag for tid, tag in ses.threads.items()},
        "cpu_tags": tags,
        # A backlog of unevaluated lines took a `quit` down.
        "console_pending": transport.pending_lines(scratch),
        **running.still_pending(scratch),
        **read.frame_fields(),
    })


def rom_check(ses: gs.Session, reference_rom: str, reference_addr: str, reference_base: str,
              cpu: str) -> dict[str, Any]:
    """The body of the `rom_check` tool: the known-answer read on `cpu`."""
    addr = inputs.hex_arg("reference_addr", reference_addr)
    on, thread = cpus.thread_for(ses, cpu)
    try:
        ses.self_check(launch.reference_rom_file(reference_rom).read_bytes(), addr,
                       base=inputs.hex_arg("reference_base", reference_base), thread=thread)
    except gs.Mismatch as e:
        # The image is one cpu's: name the cpu read, so a wrong-cpu check is not a lying session.
        raise st.Invalid("readback_refused", f"read on {on}: {e}", cpu=on) from e
    return menvelope.envelope({
        "rom_check": "OK",
        "deterministic": ses.determinism(addr, thread=thread),
        "query_s": st.measured_s(ses.cost_per_query(addr, times=50, thread=thread)),
        "cpu": or_unavailable(on, st.NO_CPU_READ_WHY),
    })
