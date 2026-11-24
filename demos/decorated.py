"""A MAME demo's loop with the presence layers drawn in, from the timeline its own run wrote.

A demo declares the layers that exist for it: the call captions and the keycaps. Pillow and numpy
(scry-core's `decorate` extra) are loaded only while a loop is made.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from scry_core import demo as core
from scry_core import motion, presence
from scry_core import overlay as ov
from scry_core.verdict import Invalid

#: The layers a MAME demo may declare.
DRAWN: tuple[ov.Layer, ...] = ("calls", "keys")
CALLS: tuple[ov.Layer, ...] = ("calls",)
CALLS_AND_KEYS: tuple[ov.Layer, ...] = ("calls", "keys")
#: The layers it may not, each with why.
LACKING: Mapping[ov.Layer, str] = {
    "pointer": "MAME has no pointer to draw: its inputs are port fields, not a mouse",
    "pause": "a decorated demo draws no pause mark: a recording holds only frames the machine ran",
    "record": "a decorated demo draws no record mark: no capture carries one"}


def declared(layers: Sequence[ov.Layer]) -> None:
    """Refuse, as `ValueError`, a layer a MAME demo cannot declare."""
    for layer in layers:
        if layer in LACKING:
            raise ValueError(f"a MAME demo declares no `{layer}` layer: {LACKING[layer]}")
        if layer not in DRAWN:
            raise ValueError(f"a MAME demo declares `calls` and `keys`, not {layer!r}")


def passes(document: Mapping[str, Any], demo: core.Demo) -> list[dict[str, Any]]:
    """The timeline per moment: the calls up to the step that ends it. A state load rewinds the
    frame count, so one frame number belongs to two passes of a run."""
    steps = [call["step"] for call in document["calls"]]
    shown = []
    for moment in demo.moments:
        if moment.until not in steps:
            raise Invalid(f"the timeline holds no call of step {moment.until!r}, so the moment "
                          "it ends cannot be decorated")
        shown.append({**document, "calls": document["calls"][:steps.index(moment.until) + 1]})
    return shown


def decorator(demo: core.Demo, run: core.Run, document: Mapping[str, Any],
              layers: Sequence[ov.Layer],
              look: presence.Look = presence.LOOK) -> motion.Decorator:
    """What `motion.build` draws each cut with: cut `n` starts at the frame its `record` began."""
    declared(layers)
    from scry_core import decorate  # the `decorate` extra: only the making of a loop needs it
    style = decorate.Style.of(ov.Overlay(calls="calls" in layers, keys="keys" in layers,
                                         pointer=False, pause=False, record=False), look=look)
    tools = {step.name: step.tool for step in demo.steps}
    starts = []
    for moment in demo.moments:
        begun = run.replies[moment.until].get("frame_begin") if moment.until in run.replies \
            else None
        if tools[moment.until] != core.RECORD_TOOL or type(begun) is not int:
            raise Invalid(f"the moment until {moment.until!r} is not a `record` step whose "
                          "reply says the frame it began at, so its clip cannot be placed in "
                          "the run's timeline")
        starts.append(begun)
    drawn = [decorate.for_loop(one, starts, style) for one in passes(document, demo)]

    def each(n: int, numbers: Sequence[int], pictures: Sequence[motion.Picture],
             rate: Any, box: motion.Box) -> list[motion.Picture]:
        shown: list[motion.Picture] = drawn[n](n, numbers, pictures, rate, box)
        return shown
    return each


def main(demo: core.Demo, layers: Sequence[ov.Layer], argv: Sequence[str] | None = None,
         look: presence.Look = presence.LOOK) -> int:
    """The demo's command line with its loop drawn in `layers`."""
    declared(layers)
    return core.main(replace(demo, decorator=lambda demo_, run, document: decorator(
        demo_, run, document, layers, look)), argv)
