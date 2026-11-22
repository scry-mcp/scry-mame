"""Section Z of the live matrix: the presence edge is drawn over the window and never in the
evidence. Circus covers the stills and the window; 1942 covers the recordings, because circus's
do not repeat from one state, so a comparison there would judge the driver, not the edge.

Every cell carries a control that can go red; a host that refuses the window capture BLOCKS
that cell. `live_matrix.py` registers this section; run alone:

    uv run python tests/live/matrix_presence.py
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from live_harness import (
    Board,
    blocked,
    boards_cover,
    call,
    cell,
    circus_boot,
    free_boot,
    fresh,
    invalid,
    ok,
    run_boards,
    run_sections,
    scratch,
    section,
    zips_missing,
)
from presence_leak import leaking_drawer
from scry_core import overlay_timeline as scry_timeline
from scry_core import presence as scry_presence
from scry_core import window_capture

from scry_mame import presence as mpresence  # isort: skip -- found through the path the harness sets
from scry_mame import state as mstate  # isort: skip
from scry_mame import transport  # isort: skip
from scry_mame.state import STATE  # isort: skip

Z_TITLE = "the presence edge, drawn over the window and never in the evidence"
Z_CELLS = [
    "circus: start reports presence true, status says the same, and the edge was drawn held "
    "before either answered",
    "circus: a run raises the acting repaints and console commands while stopped the held ones",
    "circus: the host's capture with the edge acting differs from it off on all four sides of "
    "the content and nowhere deeper than the edge, towards orange",
    "circus: snapshot, screen_view and screen_signature are byte-identical acting and off",
    "1942: record and series_capture from one saved state are byte-identical off, acting by "
    "file and lit by the session",
    "circus: the drawer on the screen's container changes a stopped snapshot: the stills can fail",
    "circus: the bitmap readers and the recordings differ across a moved machine: their "
    "comparison can fail",
    "circus: start(presence=False) draws nothing, writes no state, says false and reports no "
    "overlay",
    "circus: after a driving call that ends stopped and a quiet wait, the state is held and the "
    "held repaints rose; sent by hand, the adapter's repaint draws at least one held frame and "
    "a repaint taken away draws none",
    "circus: start and status report the overlay: the layers MAME can draw, and the one it "
    "cannot with its reason",
    "circus: a caption and a held key are each drawn over the window, the same edge twice is "
    "the same window, and snapshot, screen_view and screen_signature carry neither",
]
#: Long enough for the session's writer to land a pending state.
QUIET_S = 0.3
LEG_FRAMES = 20
RUN_FRAMES = 60
REPAINT_WAIT_S = 1.0
#: Circus's attract screen holds still for stretches shorter than this.
MOVE_FRAMES = 600


def _written(tool: str, suffix: str, **kw: Any) -> str:
    """Digest of what `tool` wrote to a fresh `dest`; "" on failure."""
    dest = Path(fresh(suffix))
    if not ok(call(tool, dest=str(dest), **kw)):
        return ""
    if dest.is_dir():
        frames = sorted(dest.glob("*.png"))
        return (hashlib.sha256(b"".join(f.read_bytes() for f in frames)).hexdigest()
                if frames else "")
    return hashlib.sha256(dest.read_bytes()).hexdigest() if dest.is_file() else ""


def _frames() -> dict[str, int] | None:
    """The drawer's repaint counts, -1 each where no drawer runs; None when the read failed."""
    r = call("lua", script="local f = _G.scry_presence_frames "
                           "if f then print(f.held, f.acting) else print(-1, -1) end",
             read_only=True)
    words = str(r.get("output") or "").split()
    if not ok(r) or len(words) != 2:
        return None
    return {"held": int(words[0]), "acting": int(words[1])}


def _rise(before: dict[str, int] | None, after: dict[str, int] | None, state: str) -> int:
    """Repaints `state` gained between two reads; -1 when either read failed."""
    return -1 if before is None or after is None else after[state] - before[state]


def _state_file() -> Path:
    assert STATE.scratch is not None
    return STATE.scratch / mpresence.STATE_FILE


def _put(path: Path, word: str) -> None:
    """`word` written atomically, as the session's adapter does."""
    part = path.with_suffix(".part")
    part.write_text(word + "\n", encoding="ascii")
    os.replace(part, path)


@contextlib.contextmanager
def _by_hand() -> Iterator[None]:
    """The session's writer stopped, so only this section writes the state file in the block."""
    STATE.presence.close()
    STATE.presence = scry_presence.Shown()
    time.sleep(QUIET_S)
    try:
        yield
    finally:
        assert STATE.scratch is not None
        STATE.presence = scry_presence.Presence.open(mpresence.FileAdapter(
            STATE.scratch, mstate.LOCK, STATE.repaintable, transport.pending_lines),
            mpresence.DRIVING_TOOLS)


def _repaint() -> None:
    """A still call through the debugger's console, which repaints a stopped MAME."""
    call("cpu_info")


def _paint(state: str) -> None:
    _put(_state_file(), state)
    _repaint()


def _frame() -> int:
    stop = call("status").get("last_stop")
    frame = stop.get("frame") if isinstance(stop, dict) else None
    if not isinstance(frame, int):
        invalid(f"status names no frame to start a series after: {stop!r}")
        return 0
    return frame


def _stills() -> dict[str, str]:
    return {"snapshot": _written("snapshot", ".png"),
            "screen_view": _written("screen_view", ".png", attach=False),
            "screen_signature": str(call("screen_signature").get("signature", ""))}


def _record(tool: str, name: str) -> str:
    """`tool` once from saved state `name`."""
    call("state_write", method="load", name=name)
    if tool == "record":
        return _written("record", ".avi", frames=LEG_FRAMES, seconds=10.0)
    at = _frame()
    return _written("series_capture", "-series", first=at + 1, last=at + LEG_FRAMES // 5,
                    seconds=10.0)


def _legs(tool: str, name: str) -> dict[str, Any]:
    """`tool` from `name`: off twice and acting by file, then lit by the session itself."""
    with _by_hand():
        off = []
        for _ in range(2):
            _put(_state_file(), "off")
            off.append(_record(tool, name))
        _put(_state_file(), "acting")
        by_file = _record(tool, name)
    lit = _record(tool, name)
    return {"off": off, "by_file": by_file, "lit": lit}


def _z_recordings(t: list[str]) -> None:
    """The recordings from one saved state, on 1942, whose recording repeats."""
    free_boot("1942", ["srb-03.m3"], "0x0", presence=True)
    first = _frames()
    call("run_for", frames=RUN_FRAMES, seconds=10.0)
    call("state_write", method="save", name="z")
    runs = {tool: _legs(tool, "z") for tool in ("record", "series_capture")}
    drawn = _rise(first, _frames(), "acting")
    owed = RUN_FRAMES + 2 * (LEG_FRAMES + LEG_FRAMES // 5)
    broken = {tool: r for tool, r in runs.items()
              if not all([*r["off"], r["by_file"], r["lit"]])}
    unrepeatable = {tool: r["off"] for tool, r in runs.items()
                    if tool not in broken and r["off"][0] != r["off"][1]}
    if broken:
        cell(t[4], False, f"a recording leg failed or wrote nothing: {broken}")
    elif unrepeatable:
        # Two disagreeing off recordings say nothing of the edge.
        blocked(t[4], f"two recordings from one state with the edge off differ: {unrepeatable}")
    else:
        cell(t[4], all(r["off"][0] == r["by_file"] == r["lit"] for r in runs.values())
             and drawn >= owed, f"{runs}; acting repaints {drawn} of at least {owed}")
    call("close")


def _z_circus(t: list[str]) -> None:
    started = circus_boot(presence=True)
    at_start = _frames()
    status = call("status")
    cell(t[0], started.get("presence") is True and status.get("presence") is True
         and at_start is not None and at_start["held"] >= 1,
         f"start {started.get('presence')!r}, status {status.get('presence')!r}, "
         f"repaints before any other call {at_start}")
    drawn = ["edge", "keys", "calls", "pause", "record"]
    cell(t[9], all(r.get("overlay", {}).get("layers") == drawn
                   and set(r["overlay"].get("lacking", {})) == {"pointer"}
                   and r["overlay"]["lacking"]["pointer"].strip() != ""
                   for r in (started, status)),
         f"start {started.get('overlay')}, status {status.get('overlay')}")
    call("run_for", frames=60, seconds=10.0)
    before = _frames()
    call("run_for", frames=60, seconds=10.0)
    after_run = _frames()
    for _ in range(3):
        _repaint()
    after_commands = _frames()
    acted = _rise(before, after_run, "acting") >= 30
    held = _rise(after_run, after_commands, "held")
    cell(t[1], acted and held >= 2,
         f"before {before}, after a run of 60 frames {after_run}, after three "
         f"console commands {after_commands}")

    with _by_hand():
        _paint("off")
        off_stills = _stills()
        off_window = _window("off")
        drawn_before = _frames()
        _paint("acting")
        acting_stills = _stills()
        acting_window = _window("acting")
        drawn_after = _frames()
    drew = _rise(drawn_before, drawn_after, "acting")
    if isinstance(off_window, str) or isinstance(acting_window, str):
        blocked(t[2], off_window if isinstance(off_window, str) else str(acting_window))
    else:
        _judge_window(t[2], off_window, acting_window)
    cell(t[3], all(off_stills.values()) and off_stills == acting_stills and drew > 0,
         f"off {off_stills}, acting {acting_stills}, acting repaints between {drew}")

    _z_layers(t[10])
    _z_repaint(t[8])
    call("state_write", method="save", name="z")
    moved_before = {**_stills(), "record": _record("record", "z"),
                    "series_capture": _record("series_capture", "z")}
    call("run_for", frames=MOVE_FRAMES, seconds=10.0)
    call("state_write", method="save", name="z2")
    moved_after = {**_stills(), "record": _record("record", "z2"),
                   "series_capture": _record("series_capture", "z2")}
    keys = ("screen_view", "screen_signature", "record", "series_capture")
    cell(t[6], all(moved_before[k] and moved_after[k] and moved_before[k] != moved_after[k]
                   for k in keys), f"before {moved_before}, after {moved_after}")
    call("close")

    _z_leak(t[5])

    quiet = circus_boot(presence=False)
    quiet_status = call("status")
    counts = _frames()
    cell(t[7], quiet.get("presence") is False and quiet_status.get("presence") is False
         and "overlay" not in quiet and "overlay" not in quiet_status
         and counts == {"held": -1, "acting": -1} and not _state_file().exists(),
         f"start {quiet.get('presence')!r}, status {quiet_status.get('presence')!r}, "
         f"repaints {counts}, state file {_state_file().exists()}")
    call("close")


def _z_layers(label: str) -> None:
    """A caption and a key held, each written as the session writes them, change the window
    beyond the edge alone and leave every still as it was with the edge off; the edge alone twice
    is the same window, so what differs is the layer."""
    caption = scry_timeline.Caption("registers cpu=:maincpu", "read", 0xFFFFFF, 1)
    payloads = {"edge": scry_presence.Payload(layers=("edge",)),
                "again": scry_presence.Payload(layers=("edge",)),
                "calls": scry_presence.Payload(layers=("edge", "calls"), caption=caption),
                "keys": scry_presence.Payload(layers=("edge", "keys"), keys=("Coin 1",))}
    windows: dict[str, window_capture.Image | str] = {}
    with _by_hand():
        _put(_state_file(), "off")
        off_stills = _stills()
        layered_stills = []
        for name, payload in payloads.items():
            _put(_state_file(), mpresence.encode("acting", payload).rstrip("\n"))
            _repaint()
            windows[name] = _window(name)
            layered_stills.append(_stills())
    if refused := [w for w in windows.values() if isinstance(w, str)]:
        blocked(label, refused[0])
        return
    images = {name: w for name, w in windows.items() if not isinstance(w, str)}
    try:
        changed = {name: window_capture.difference(images["edge"], shown).changed
                   for name, shown in images.items() if name != "edge"}
    except ValueError as e:
        blocked(label, f"the window changed between its captures: {e}")
        return
    cell(label, all(off_stills.values()) and all(held == off_stills for held in layered_stills)
         and changed["again"] == 0 and changed["calls"] > 0 and changed["keys"] > 0,
         f"off {off_stills}; window pixels differing from the edge alone: {changed}")


def _z_repaint(label: str) -> None:
    """The edge goes dim on a stopped MAME: through the session, then the repaint by hand.
    The red is not taken through the session: its writer delivers states off the call's path, so
    a count read there can rise with the repaint taken away; `_by_hand` removes that race."""
    def repaints_drawn(repaint: Callable[[Callable[[], bool]], None]) -> int:
        """The held repaints `repaint` drew, with the file `held` around it alone."""
        before = _frames()
        time.sleep(REPAINT_WAIT_S)
        _put(_state_file(), "held")
        due = time.monotonic() + REPAINT_WAIT_S
        repaint(lambda: time.monotonic() < due)
        time.sleep(REPAINT_WAIT_S)
        _put(_state_file(), "off")
        return _rise(before, _frames(), "held")
    call("run_for", frames=10, seconds=10.0)
    after_run = _frames()
    time.sleep(REPAINT_WAIT_S)
    # Before the count: `lua` drives, so the file says `acting` while it runs.
    word = _state_file().read_text().partition("\n")[0] if _state_file().exists() else ""
    rose = _rise(after_run, _frames(), "held")
    assert STATE.scratch is not None
    adapter = mpresence.FileAdapter(STATE.scratch, mstate.LOCK, STATE.repaintable,
                                    transport.pending_lines)
    with _by_hand():
        _put(_state_file(), "off")
        by_repaint = repaints_drawn(adapter.repaint)
        by_nothing = repaints_drawn(lambda still: None)
    cell(label, rose >= 1 and word == "held" and by_repaint >= 1 and by_nothing == 0,
         f"after the quiet wait {rose} held repaints (state {word!r}); by hand the "
         f"repaint drew {by_repaint}, no repaint {by_nothing}")


def _judge_window(label: str, off: window_capture.Image, acting: window_capture.Image) -> None:
    try:
        d = window_capture.difference(off, acting)
    except ValueError as e:
        blocked(label, f"the window changed between its two captures: {e}")
        return
    cell(label, *window_capture.edge_verdict(d))


def _window(tag: str) -> window_capture.Image | str:
    """The window captured, or why the host refused."""
    assert STATE.proc is not None
    try:
        return window_capture.capture(STATE.proc.pid, scratch() / f"z-window-{tag}.png")
    except window_capture.Blocked as e:
        return str(e)


def _z_leak(label: str) -> None:
    """The red of the stills: the production drawer moved onto the screen's container."""
    leak_state = scratch() / "z-leak.state"
    _put(leak_state, "off")
    leaking, moved, path_moved = leaking_drawer(scratch(), leak_state)
    if moved != 1 or path_moved != 1:
        invalid(f"the leaking drawer could not be derived ({moved} containers, {path_moved} "
                "paths moved): the production drawer changed shape")
    harness = scratch() / "z-leak.lua"
    harness.write_text(leaking.replace("_G.scry_presence_frames", "_G.scry_leak_frames"))
    circus_boot(presence=False, boot_lua=str(harness))
    call("run_for", frames=60, seconds=10.0)
    snaps: list[str] = []
    for state in ("off", "off", "acting"):
        _put(leak_state, state)
        _repaint()
        snaps.append(_written("snapshot", ".png"))
    cell(label, all(snaps) and snaps[0] == snaps[1] != snaps[2], f"off, off, acting: {snaps}")
    call("close")


Z_BOARDS = (Board(_z_circus, (0, 1, 2, 3, 5, 6, 7, 8, 9, 10), lambda: zips_missing("circus")),
            Board(_z_recordings, (4,), lambda: zips_missing("1942")))
boards_cover("Z", Z_CELLS, Z_BOARDS)


def register_z() -> None:
    """Register section Z with the matrix: after every section registered before it."""
    section("Z", Z_TITLE, Z_CELLS)(lambda: run_boards(Z_CELLS, Z_BOARDS))


if __name__ == "__main__":
    register_z()
    run_sections("SECTION Z")
