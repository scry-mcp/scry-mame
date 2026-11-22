"""A MAME demo's loop with the presence layers drawn in, from the timeline its own run wrote.

A demo declares the layers that exist for it: the call captions and the keycaps. Pillow and numpy
(scry-core's `decorate` extra) are loaded only while a loop is made.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from scry_core import demo as core
from scry_core import motion, timeline
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


def _drawing() -> Any:
    """`scry_core.decorate`, which needs the extra; `Invalid` naming it when it is not installed."""
    try:
        from scry_core import decorate
    except ImportError as e:
        raise Invalid("a demo's loop is decorated with Pillow and numpy, scry-core's `decorate` "
                      "extra: install it (`uv sync --extra decorate`)") from e
    return decorate


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
              layers: Sequence[ov.Layer]) -> motion.Decorator:
    """What `motion.build` draws each cut with: cut `n` starts at the frame its `record` began."""
    declared(layers)
    decorate = _drawing()
    style = decorate.Style.of(ov.Overlay(calls="calls" in layers, keys="keys" in layers,
                                         pointer=False, pause=False, record=False))
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


@contextlib.contextmanager
def _replaced(owner: Any, name: str, value: Any) -> Iterator[None]:
    old = getattr(owner, name)
    setattr(owner, name, value)
    try:
        yield
    finally:
        setattr(owner, name, old)


def main(demo: core.Demo, layers: Sequence[ov.Layer], argv: Sequence[str] | None = None) -> int:
    """The demo's command line with its loop drawn in `layers`; the runner has no seam for a
    decorator, so for the run it is handed this module's."""
    declared(layers)
    real_execute, real_build = core.execute, motion.build

    def execute(demo_: core.Demo, run: core.Run, transcript: Path,
                update_readme: bool = False) -> int:
        if update_readme and demo_.moments:
            _drawing()  # before the emulator runs, not after

        def build(cuts: Sequence[motion.Cut], work: Path,
                  decorate: motion.Decorator | None = None) -> motion.Built:
            # The runner names its files from the transcript's stem and exports no name for it.
            written = core._beside(transcript).timeline
            if not written.is_file():
                raise Invalid(f"the run wrote no timeline at {written}, and a clip is decorated "
                              "only from its run's timeline")
            document = timeline.loads(written.read_text(encoding="utf-8"))
            return real_build(cuts, work, decorator(demo_, run, document, layers))

        with _replaced(motion, "build", build):
            return real_execute(demo_, run, transcript, update_readme)

    with _replaced(core, "execute", execute):
        return core.main(demo, argv)

