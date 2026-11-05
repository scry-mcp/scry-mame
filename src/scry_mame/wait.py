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
from scry_core.prose import counted

from scry_mame import advance, maps
from scry_mame import gdb_session as gs
from scry_mame import palette as mpalette
from scry_mame import state as st

#: The least a poll is given when the bound is all but spent.
MIN_STEP_S = 0.001


def screen_wait(ses: gs.Session, scratch: Path, text: str, screen: str, palette: str,
                every: int, seconds: float,
                progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `screen_wait` tool."""
    advance.check_wait(text=text, screen=screen, palette=palette, every=every)
    if text:
        raise st.Invalid("no_channel",
                         "screen_wait's `text` reads the characters of a text mode, and this "
                         "server hands the screen as pixels: map the screen once with "
                         "`screen_map_write` and wait on it with `screen`")
    step = every or 1
    judge, name, asked = _judge(ses, scratch, screen, palette, seconds, progress)
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
            return last
        polls += step
        if last.get("verdict") != contract.ELAPSED:
            return _expired(name, asked, polls, every, seconds, began, last)
        ran = judge()
        if ran is not None:
            return _answer(ran, predicate=name, polls=polls, every=every, already=False,
                           began=began, last=last)


def _judge(ses: gs.Session, scratch: Path, screen: str, palette: str, seconds: float,
           progress: mprogress.Progress,
           ) -> tuple[Callable[[], dict[str, Any] | None], str, str]:
    """The one predicate's reader, the argument that named it, and how a note calls it."""
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
    return {**(last or {}), **own}


def _expired(predicate: str, asked: str, polls: int, every: int, seconds: float,
             began: float, last: dict[str, Any] | None) -> dict[str, Any]:
    """`TIMEOUT`: what was examined, and the step when it sampled."""
    sampled = ("" if not every else
               f", judged every {every} frames, so a screen shorter than that is passed over")
    own = {"verdict": contract.TIMEOUT, "predicate": predicate, "already": False,
           "polls": polls, "sampled_every": every, "frames": polls,
           "waited_s": round(time.monotonic() - began, 1),
           "note": f"{asked} was not found in {counted(polls, 'frame')} within "
                   f"{seconds:g} s{sampled}"}
    return {**(last or {}), **own}
