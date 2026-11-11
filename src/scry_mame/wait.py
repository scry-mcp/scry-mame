"""`screen_wait`: the machine run until one predicate holds, judged at each stop.

THE JUDGE IS THE SERVER'S, NEVER THE EMULATOR'S. A Lua frame notifier can see the screen too,
and it reads it a frame late and sometimes mid-draw: measured on `circus` with the same checksum
on both routes, the notifier matched at frame 72 where a stepped run finds the picture at frame
70, and its rows hold pictures no stop ever shows. So the wait steps the machine and reads it at
the stop, where the picture is whole, and `every` is what buys speed back: it runs N frames per
poll, and a screen alive for fewer than N is passed over.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scry_core import progress as mprogress
from scry_core import reply_contract as contract
from scry_core import stop_wait
from scry_core.prose import counted

from scry_mame import advance, at_stop, maps, running
from scry_mame import envelope as menvelope
from scry_mame import gdb_session as gs
from scry_mame import palette as mpalette
from scry_mame import state as st

#: The least a poll is given when the bound is all but spent.
MIN_STEP_S = 0.001


def screen_wait(ses: gs.Session, scratch: Path, text: str, screen: str, palette: str,
                every: int, seconds: float,
                progress: mprogress.Progress = mprogress.no_progress, *, changed: bool = False,
                on_breakpoint: str = "", on_watch: str = "", condition: str = "", cpu: str = "",
                place: Callable[[str], int] | None = None) -> dict[str, Any]:
    """The body of the `screen_wait` tool; `place` turns a condition's memory ref into its
    address."""
    advance.check_wait(text=text, screen=screen, palette=palette, every=every, changed=changed,
                       on_breakpoint=on_breakpoint, on_watch=on_watch, condition=condition)
    spec = stop_wait.check(on_breakpoint, on_watch, every, condition)
    if text:
        raise st.Invalid("no_channel",
                         "screen_wait's `text` reads the characters of a text mode, and this "
                         "server hands the screen as pixels: map the screen once with "
                         "`screen_map_write` and wait on it with `screen`")
    step = every or 1
    if spec is not None:
        at_stop.declared_row(ses, spec, cpu)        # refused before the screen is read
    judge, name, asked = _judge(ses, scratch, screen, palette, seconds, progress, changed)
    if spec is not None:
        return at_stop.screen_wait_at(ses, scratch, spec, cpu, judge, name, asked, seconds,
                                      progress, place or _no_place)
    began = time.monotonic()
    deadline = began + seconds
    ran = judge()
    if ran is not None:
        return _answer(ran, predicate=name, polls=0, every=every, already=True, began=began)
    polls = 0
    last: dict[str, Any] | None = None
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return _expired(name, asked, polls, every, seconds, began, last)
        last = advance.run_for(ses, scratch, 0, max(left, MIN_STEP_S), progress, frames=step)
        if last.get("status") != "ok":
            # A POLL ITS OWN BOUND CUT LEFT THE MACHINE POSSIBLY RUNNING: the run says so with
            # `not_settled`, and handing that back leaves the next reader refusing `not_stopped`.
            # Brought to rest here, the wait answers the bound it actually spent. A counter
            # that did not move is no verdict about the screen, so it travels as it came.
            if last.get("code") == "not_settled" \
                    and running.stop(ses, scratch).get("status") == "ok":
                return _expired(name, asked, polls, every, seconds, began, None, cut=True)
            return last
        if last.get("verdict") != contract.ELAPSED:
            # A STOP THE WAIT DID NOT ASK FOR, with its bound unspent: the machine sits at that
            # stop, so sealing a TIMEOUT beside its own cause would contradict itself. The twin
            # server asks the caller to look at the stop: `wait_stopped`.
            raise st.Invalid("wait_stopped",
                f"a stop ended the poll before {asked} was judged: "
                f"{last.get('cause') or 'a stop nothing declared'}. The machine is stopped there, "
                f"and the wait did not reach its bound",
                predicate=name, polls=polls,
                **{k: v for k, v in last.items() if k not in ("status", "verdict", "polls")})
        polls += step
        ran = judge()
        if ran is not None:
            return _answer(ran, predicate=name, polls=polls, every=every, already=False,
                           began=began, last=last)


def _no_place(ref: str) -> int:
    raise st.Invalid("bad_argument", f"the condition reads memory at {ref!r}, and no table "
                     "places it")


def _judge(ses: gs.Session, scratch: Path, screen: str, palette: str, seconds: float,
           progress: mprogress.Progress, changed: bool = False,
           ) -> tuple[Callable[[], dict[str, Any] | None], str, str]:
    """The one predicate's reader, the argument that named it, and how a note calls it."""
    if changed:
        def found_now() -> dict[str, Any]:
            reply = maps.screen_map_find(ses, scratch, progress)
            if reply.get("status") != "ok":
                said = f"`changed` judges the map at each stop: {reply.get('message')}"
                if reply.get("code") == "needs_call":
                    raise st.Invalid("needs_call", said)
                raise st.Invalid("no_channel", said)
            return reply
        judge = stop_wait.Changed(found_now())

        def moved() -> dict[str, Any] | None:
            reply = found_now()
            if not judge.judge(reply):
                return None
            return {"screen": {"name": reply["screen"], "layer": reply.get("layer")},
                    "started_on": judge.started_on or contract.unavailable(
                        "the map named no screen when the wait began")}
        return moved, "changed", "a changed screen"
    if screen:
        st.STATE.maps.check_known(screen)       # refused before a frame runs

        def found() -> dict[str, Any] | None:
            reply = maps.screen_map_find(ses, scratch, progress)
            if reply.get("status") == "ok" and reply.get("matched") \
                    and reply.get("screen") == screen:
                return {"screen": {"name": reply["screen"], "layer": reply.get("layer")}}
            return None
        return found, "screen", f"screen {screen!r}"

    def black() -> dict[str, Any] | None:
        reply = mpalette.palette(ses, scratch, "", 0, 0, 0, "", seconds, progress)
        if reply.get("status") != "ok":
            # The wait has no channel to a palette it cannot read, whatever refused the read.
            raise st.Invalid("no_channel",
                             f"the palette could not be read at this stop, so a black one cannot "
                             f"be judged: {reply.get('message')}")
        if all(str(colour).lower() == "#000000" for colour in reply.get("colors", [])):
            return {"palette": palette, "entries": reply.get("entries")}
        return None
    return black, "palette", f"a {palette} palette"


def _answer(hit: dict[str, Any], *, predicate: str, polls: int, every: int,
            already: bool, began: float, last: dict[str, Any] | None = None) -> dict[str, Any]:
    """`TARGET`: the wait's fields in the stop's own reply."""
    own = {"verdict": contract.TARGET, "predicate": predicate, "already": already, "polls": polls,
           "sampled_every": every, "frames": polls,
           "waited_s": round(time.monotonic() - began, 1), **hit}
    # No poll behind it, so no stop reply to inherit `status` from.
    return menvelope.envelope({**(last or {}), **own})


def _expired(predicate: str, asked: str, polls: int, every: int, seconds: float,
             began: float, last: dict[str, Any] | None, cut: bool = False) -> dict[str, Any]:
    """`TIMEOUT`: what was examined, the step when it sampled, and the poll the bound cut."""
    sampled = ("" if not every else
               f", judged every {every} frames, so a screen shorter than that is passed over")
    own = {"verdict": contract.TIMEOUT, "predicate": predicate, "already": False,
           "polls": polls, "sampled_every": every, "frames": polls,
           "waited_s": round(time.monotonic() - began, 1),
           "note": f"{asked} was not found in {counted(polls, 'frame')} within "
                   f"{seconds:g} s{sampled}"
                   + (", and the bound cut its last poll, which was stopped here" if cut
                      else "")}
    return menvelope.envelope({**(last or {}), **own})
