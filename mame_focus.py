"""FOCUS: the debugger's visible cpu, moved by this server and read back.

MAME's debugger acts on ONE cpu at a time, the visible one, and its console's own `focus` does
not simply show another: it IGNORES every other cpu (`execute_focus`), and ignoring the cpu that
is live makes the debugger run until the focused one executes (`device_debug::ignore` calls
`go_next_device`). After it, a breakpoint on any other cpu has no effect. So the tool takes the
path that moves nothing where the build has one: the gdbstub's thread patch answers `Hc<id>` by
making that cpu visible and touching no ignore flag. Nothing running is PROVED, not assumed: the
frame counter and every cpu's whole register block are read before and after. A build without
the patch has only the console's `focus`, and the reply says what that did: which cpus it left
ignored, and, when it released the machine, the survey of where the machine stopped.

The cpu that ends up visible is read back off `cpulist` (`mame_cpus`), never taken from the
request.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import gdb_session as gs
import mame_cpus as cpus
import mame_envelope as menvelope
import mame_inputs as inputs
import mame_progress as mprogress
import mame_read as read
import mame_running as running
import mame_state as st
from mame_state import STATE

# How long a console `focus` or `ignore` that released the machine is given to reach the next
# cpu, and how often the visible cpu is asked meanwhile: that run lasts until another cpu
# executes, a slice of one frame.
SETTLE_S = 2.0
SETTLE_POLL_S = 0.05


#: `focus`'s `was` when the console marked no cpu visible before the call.
NO_WAS_WHY = "`cpulist` marked no cpu visible before the call"
NO_VISIBLE_AFTER_WHY = "`cpulist` marked no cpu visible after the call"


def settled_visible(ses: gs.Session, ignored: list[str]) -> str | None:
    """The visible cpu once MAME has stopped again after the console ignored the cpu it was live
    on, or None when it has not within `SETTLE_S`. The debugger answers the console WHILE that
    run goes on (measured: `cpulist` read right after a typed `focus subcpu` still marked
    `:maincpu`, which it now ignored), and it never stops on a cpu it ignores, so a live cpu
    among `ignored` is a machine still running to the next one. The live cpu is the patched
    stub's `?`, which names the last stop's until the next one; without threads the visible
    cpu is the one that stopped, since no `Hc` can have moved it."""
    clock = mprogress.Ticker(SETTLE_S, mprogress.no_progress)
    while True:
        live, visible = cpus.live_cpu(ses), cpus.visible_cpu(ses)
        if visible is not None and (live or visible) not in ignored:
            return visible
        if clock.expired():
            return None
        time.sleep(SETTLE_POLL_S)


def check_focus(cpu: str = "", **_: Any) -> None:
    """`focus`'s machine-independent half: a cpu is named. Which cpus there are is the
    machine's to say."""
    if not inputs.cpu_given(cpu):
        raise st.Invalid("bad_argument", "cpu is empty: `focus` takes the tag of the cpu to show "
                                         "(`subcpu` or `:subcpu`), which `machine_map` lists")


def focus(ses: gs.Session, scratch: Path, cpu: str) -> dict[str, Any]:
    """The body of the `focus` tool."""
    check_focus(cpu)
    tag = cpus.named(ses, cpu)
    was = cpus.visible_cpu(ses)
    thread = cpus.thread_of(ses, tag)
    if thread is None:
        return _by_console(ses, scratch, tag, was)
    return _by_stub(ses, tag, was, thread)


def _blocks(ses: gs.Session) -> dict[str, str | None]:
    """Every thread's whole register block, by its cpu's tag; None for a cpu the stub has no
    register map for, whose block it refuses."""
    out: dict[str, str | None] = {}
    for tid, tag in sorted(ses.threads.items()):
        try:
            out[tag] = ses.register_block(tid)
        except gs.Refused:
            out[tag] = None
    return out


def _by_stub(ses: gs.Session, tag: str, was: str | None, thread: int) -> dict[str, Any]:
    """`Hc<thread>`, read back, with the proof that nothing ran: the frame and each cpu's
    register block equal before and after. A cpu whose block the stub refuses is named in
    `unread`, never counted as unchanged. A board with no frame counter proves it by the
    blocks alone, its `frame` unavailable."""
    frame_before, before = read.frame_or_none(ses), _blocks(ses)
    cpus.make_visible(ses, tag, f"`focus` shows {tag}")
    visible, frame_after, after = cpus.visible_cpu(ses), read.frame_or_none(ses), _blocks(ses)
    unread = sorted(t for t in before if before[t] is None or after.get(t) is None)
    unchanged = [t for t in before if t not in unread and before[t] == after[t]]
    reply: dict[str, Any] = {
        "cpu": st.or_unavailable(visible, NO_VISIBLE_AFTER_WHY),
        "was": st.or_unavailable(was, NO_WAS_WHY), "via": "stub",
        "machine_ran": frame_after != frame_before or len(unchanged) + len(unread) < len(before),
        "frame": st.frame_shown(frame_after), "unchanged": unchanged}
    if unread:
        reply["unread"] = unread
    if visible != tag:
        return menvelope.invalid("readback_refused",
                                 f"the stub took `Hc{thread:x}` and `cpulist` shows {visible} "
                                 f"visible, not {tag}: `cpu_info` says which cpu is visible now",
                                 **reply)
    return menvelope.envelope(reply)


def _by_console(ses: gs.Session, scratch: Path, tag: str, was: str | None) -> dict[str, Any]:
    """The console's `focus`, on a stub without threads. It ignores every other cpu; when the
    cpu that was visible is one of them, the debugger runs until `tag` executes, and the stop
    it reaches is surveyed like any other, once the frame counter proves it at rest."""
    answer = ses.monitor(f"focus {tag}")
    if not answer.strip().startswith(f"Now focused on CPU '{tag}'"):
        raise st.Invalid("unexpected_answer",
                         f"the console's `focus {tag}` answered {answer.strip()!r}")
    ignored = cpus.ignored(ses)
    base: dict[str, Any] = {"was": st.or_unavailable(was, NO_WAS_WHY), "via": "console",
                            "machine_ran": tag != was,
                            "ignored": st.or_unavailable(ignored, "`ignore` answered neither of "
                                                                  "its shapes")}
    if tag == was:
        return menvelope.envelope({"cpu": st.or_unavailable(cpus.visible_cpu(ses),
                                                            NO_VISIBLE_AFTER_WHY), **base})
    if ignored is None or settled_visible(ses, ignored) is None:
        # No packet comes for a run the console started: the next contact proves the stop.
        ses.running = True
        STATE.console_run = True
        return menvelope.invalid("not_settled",
                                 f"the console's `focus` released the machine until {tag} "
                                 "executes, and no stop on a cpu it observes was read: it may be "
                                 f"RUNNING. {running.STOP_RECOVERS}", **base)
    return running.stop_reply(
        ses, scratch, f"focus {tag}: the console ignored {was} and ran until {tag} executed",
        **base)
