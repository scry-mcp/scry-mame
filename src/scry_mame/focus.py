"""FOCUS: the debugger's visible cpu, moved by this server and read back.

The console's `focus` IGNORES every other cpu, and ignoring the live one runs the machine until
the focused one executes. With the gdbstub's thread patch, `Hc<id>` makes a cpu visible with no
ignore flag, and the frame counter and register blocks prove nothing ran.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from scry_core import progress as mprogress
from scry_core.reply_contract import or_unavailable

from scry_mame import cpus, inputs, read, running
from scry_mame import envelope as menvelope
from scry_mame import gdb_session as gs
from scry_mame import state as st
from scry_mame.state import STATE

# The run a console `focus` starts lasts until another cpu executes, a slice of one frame.
SETTLE_S = 2.0
SETTLE_POLL_S = 0.05


#: `cpu_focus`'s `was` when the console marked no cpu visible before the call.
NO_WAS_WHY = "`cpulist` marked no cpu visible before the call"
NO_VISIBLE_AFTER_WHY = "`cpulist` marked no cpu visible after the call"


def settled_visible(ses: gs.Session, ignored: list[str]) -> str | None:
    """The visible cpu once MAME has stopped again, or None when it has not within `SETTLE_S`.

    The console answers WHILE the run goes on, and the debugger never stops on an ignored cpu,
    so a live cpu among `ignored` is still running. Without threads it is the visible one.
    """
    clock = mprogress.Ticker(SETTLE_S, mprogress.no_progress)
    while True:
        live, visible = cpus.live_cpu(ses), cpus.visible_cpu(ses)
        if visible is not None and (live or visible) not in ignored:
            return visible
        if clock.expired():
            return None
        time.sleep(SETTLE_POLL_S)


def check_focus(cpu: str = "", **_: Any) -> None:
    """`cpu_focus`'s machine-independent half: a cpu is named."""
    if not inputs.cpu_given(cpu):
        raise st.Invalid("bad_argument", "cpu is empty: `cpu_focus` takes the tag of the cpu to "
                                         "show (`subcpu` or `:subcpu`), which `machine_map` "
                                         "lists")


def focus(ses: gs.Session, scratch: Path, cpu: str) -> dict[str, Any]:
    """The body of the `cpu_focus` tool."""
    check_focus(cpu)
    tag = cpus.named(ses, cpu)
    was = cpus.visible_cpu(ses)
    thread = cpus.thread_of(ses, tag)
    if thread is None:
        return _by_console(ses, scratch, tag, was)
    return _by_stub(ses, tag, was, thread)


def _blocks(ses: gs.Session) -> dict[str, str | None]:
    """Every thread's register block by cpu tag; None where the stub refuses it."""
    out: dict[str, str | None] = {}
    for tid, tag in sorted(ses.threads.items()):
        try:
            out[tag] = ses.register_block(tid)
        except gs.Refused:
            out[tag] = None
    return out


def _by_stub(ses: gs.Session, tag: str, was: str | None, thread: int) -> dict[str, Any]:
    """`Hc<thread>`, read back, with the proof that nothing ran. A cpu whose block the stub
    refuses is named in `unread`, never counted as unchanged; no frame counter leaves `frame`
    unavailable."""
    frame_before, before = read.frame_or_none(ses), _blocks(ses)
    cpus.make_visible(ses, tag, f"`cpu_focus` shows {tag}")
    visible, frame_after, after = cpus.visible_cpu(ses), read.frame_or_none(ses), _blocks(ses)
    unread = sorted(t for t in before if before[t] is None or after.get(t) is None)
    unchanged = [t for t in before if t not in unread and before[t] == after[t]]
    reply: dict[str, Any] = {
        "cpu": or_unavailable(visible, NO_VISIBLE_AFTER_WHY),
        "was": or_unavailable(was, NO_WAS_WHY), "via": "stub",
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
    """The console's `focus`, on a stub without threads; the stop it may cause is surveyed."""
    answer = ses.monitor(f"focus {tag}")
    if not answer.strip().startswith(f"Now focused on CPU '{tag}'"):
        raise st.Invalid("unexpected_answer",
                         f"the console's `focus {tag}` answered {answer.strip()!r}")
    ignored = cpus.ignored(ses)
    base: dict[str, Any] = {"was": or_unavailable(was, NO_WAS_WHY), "via": "console",
                            "machine_ran": tag != was,
                            "ignored": or_unavailable(ignored, "`ignore` answered neither of "
                                                                  "its shapes")}
    if tag == was:
        return menvelope.envelope({"cpu": or_unavailable(cpus.visible_cpu(ses),
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
