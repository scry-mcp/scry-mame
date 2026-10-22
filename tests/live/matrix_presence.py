"""Section Z of the live matrix: the presence edge, drawn over the window and never in the
evidence, on circus, and on 1942 for the recordings. Why it cannot reach the evidence is
`mame_presence`'s to say; this section proves each claim on a running MAME, each with a control
that can go red.

DRAWN: the drawer counts the repaints it draws in each state, read back through `lua`; a run
(`acting`) and the console commands of a stopped machine (`held`) must each raise their own count
by the frames they drew. SEEN: the host's capture of the window with the edge `acting` against the
same stopped machine with it `off` differs on all four sides of the content and nowhere deeper
than the edge, towards orange; a host that does not grant the capture BLOCKS that cell.

NEVER IN THE EVIDENCE: `snapshot`, `screen_view` and `screen_signature` compared byte for byte
with the edge `acting` and `off` on one stopped machine, and `record` and `series_capture` from
one saved state, with the edge off twice first (two that disagree say nothing of the edge, so
the cell is BLOCKED), then held at `acting` by the state file, then lit by the session itself as
it would be. The recordings are 1942's: circus's do not repeat from one state (REFERENCE, Saved
states), so a comparison there would judge the driver, not the edge. Where the state file is
written here, the session's writer is set aside and given time to land what it had pending, so
the file is the test's alone; every such leg reads the drawer's count, so a drawer that drew
nothing cannot pass it. The reds: the production drawer
moved onto the screen's container must change a stopped `snapshot`; and the bitmap readers and
the recordings, which nothing drawn at frame-done reaches, must differ across a machine moved on.

`live_matrix.py` registers this section; run alone, it is the same machinery over it only:

    uv run python tests/live/matrix_presence.py
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
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
from scry_core import presence as scry_presence
from scry_core import window_capture

import mame_presence as mpresence  # isort: skip -- found through the path the harness sets
import mame_state as mstate  # isort: skip
import mame_transport as transport  # isort: skip
from mame_state import STATE  # isort: skip

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
    "circus: start(presence=False) draws nothing, writes no state and says false",
    "circus: after a driving call that ends stopped and a quiet wait, the state is held and the "
    "held repaints rose; sent by hand, the adapter's repaint draws at least one held frame and "
    "a repaint taken away draws none",
]
#: Long enough for the session's writer to land a state it had pending.
QUIET_S = 0.3
#: The frames each recording leg records, and the run before the state they start from.
LEG_FRAMES = 20
RUN_FRAMES = 60
#: How long a stopped machine is left alone for the writer to land `held` and repaint it.
REPAINT_WAIT_S = 1.0
#: How far the machine is moved for the reds that compare across it: circus's attract screen
#: holds still for stretches shorter than this.
MOVE_FRAMES = 600


def _written(tool: str, suffix: str, **kw: Any) -> str:
    """`tool` writing to a fresh `dest`, and the digest of what it wrote there: of the file, or
    of a series folder's frames in order; "" when the call failed or nothing was written."""
    dest = Path(fresh(suffix))
    if not ok(call(tool, dest=str(dest), **kw)):
        return ""
    if dest.is_dir():
        frames = sorted(dest.glob("*.png"))
        return (hashlib.sha256(b"".join(f.read_bytes() for f in frames)).hexdigest()
                if frames else "")
    return hashlib.sha256(dest.read_bytes()).hexdigest() if dest.is_file() else ""


def _frames() -> dict[str, int] | None:
    """The drawer's repaint counts, `{held, acting}`; -1 each where no drawer runs; None when the
    read itself failed, which no cell may take for an answer."""
    r = call("lua", script="local f = _G.scry_presence_frames "
                           "if f then print(f.held, f.acting) else print(-1, -1) end",
             read_only=True)
    words = str(r.get("output") or "").split()
    if not ok(r) or len(words) != 2:
        return None
    return {"held": int(words[0]), "acting": int(words[1])}


def _rise(before: dict[str, int] | None, after: dict[str, int] | None, state: str) -> int:
    """How many repaints `state` gained between two reads; -1 when either read failed."""
    return -1 if before is None or after is None else after[state] - before[state]


def _state_file() -> Path:
    assert STATE.scratch is not None
    return STATE.scratch / mpresence.STATE_FILE


def _put(path: Path, word: str) -> None:
    """`word` written whole, the way the session's adapter writes it."""
    part = path.with_suffix(".part")
    part.write_text(word + "\n", encoding="ascii")
    os.replace(part, path)


@contextlib.contextmanager
def _by_hand() -> Iterator[None]:
    """The session's writer stopped, so nothing but this section writes the state file until the
    block ends; a fresh one is opened after."""
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
    """One still call that goes through the debugger's console, which repaints a stopped MAME."""
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
    """`tool` once from the saved state `name`."""
    call("state_load", name=name)
    if tool == "record":
        return _written("record", ".avi", frames=LEG_FRAMES, seconds=10.0)
    at = _frame()
    return _written("series_capture", "-series", first=at + 1, last=at + LEG_FRAMES // 5,
                    seconds=10.0)


def _legs(tool: str, name: str) -> dict[str, Any]:
    """`tool` from `name`: off twice and acting by the file, the writer set aside; then once more
    with the session lighting the edge itself."""
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
    """The recordings from one saved state, on 1942, whose recording repeats. The state is saved
    at a frame's end, and the drawer's count is read before the run that ends at the save and
    after every leg: the rise it must show is what that run and the legs that draw drew."""
    free_boot("1942", ["srb-03.m3"], "0x0", presence=True)
    first = _frames()
    call("run_for", frames=RUN_FRAMES, seconds=10.0)
    call("state_save", name="z")
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
        # TWO RECORDINGS WITH THE EDGE OFF THAT DISAGREE say nothing of the edge: the instrument.
        blocked(t[4], f"two recordings from one state with the edge off differ: {unrepeatable}")
    else:
        cell(t[4], all(r["off"][0] == r["by_file"] == r["lit"] for r in runs.values())
             and drawn >= owed, f"{runs}; acting repaints {drawn} of at least {owed}")
    call("close")


def _z_circus(t: list[str]) -> None:
    started = circus_boot(presence=True)
    at_start = _frames()                 # the first call: whatever `start` itself repainted
    status = call("status")
    cell(t[0], started.get("presence") is True and status.get("presence") is True
         and at_start is not None and at_start["held"] >= 1,
         f"start {started.get('presence')!r}, status {status.get('presence')!r}, repaints "
         f"before any other call {at_start}")
    call("run_for", frames=60, seconds=10.0)
    before = _frames()
    call("run_for", frames=60, seconds=10.0)
    after_run = _frames()
    for _ in range(3):
        _repaint()
    after_commands = _frames()
    cell(t[1], _rise(before, after_run, "acting") >= 30
         and _rise(after_run, after_commands, "held") >= 2,
         f"before {before}, after a run of 60 frames {after_run}, after three console "
         f"commands {after_commands}")

    # SEEN, and the stills, on one stopped machine.
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

    _z_repaint(t[8])
    # THE RED OF EVERYTHING FRAME-DONE CANNOT REACH: the same comparisons across a machine one
    # run apart.
    call("state_save", name="z")        # at a frame's end, as every save of this section
    moved_before = {**_stills(), "record": _record("record", "z"),
                    "series_capture": _record("series_capture", "z")}
    call("run_for", frames=MOVE_FRAMES, seconds=10.0)
    call("state_save", name="z2")       # at a frame's end too, as `z` was
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
         and counts == {"held": -1, "acting": -1} and not _state_file().exists(),
         f"start {quiet.get('presence')!r}, status {quiet_status.get('presence')!r}, "
         f"repaints {counts}, state file {_state_file().exists()}")
    call("close")


def _z_repaint(label: str) -> None:
    """THE EDGE GOES DIM ON A STOPPED MAME, in two halves. The session's: a `run_for` that ends
    stopped, a quiet wait, and the state file says `held` and the drawer's held count rose. The
    repaint's own, by hand: the file says `held` only around the adapter's repaint and `off`
    while the count is read, since a read is `lua`, whose steps repaint a stopped machine.

    WHY THE RED IS NOT TAKEN THROUGH THE SESSION: the writer delivers each state off the call's
    path, so on a loaded host a driving call's first repaints can still find the previous `held`
    in the file, and a count read through the session rises with the repaint taken away;
    `_by_hand` removes that race. That the writer asks for the repaint once `held` lands is
    scry-core's `test_presence`."""
    def repaints_drawn(repaint: Callable[[Callable[[], bool]], None]) -> int:
        """The held repaints `repaint` drew, the file `held` around it alone."""
        before = _frames()
        time.sleep(REPAINT_WAIT_S)               # what the read drew late lands on `off`
        _put(_state_file(), "held")
        due = time.monotonic() + REPAINT_WAIT_S  # still due until then: a lock never freed ends it
        repaint(lambda: time.monotonic() < due)
        time.sleep(REPAINT_WAIT_S)
        _put(_state_file(), "off")
        return _rise(before, _frames(), "held")
    call("run_for", frames=10, seconds=10.0)
    after_run = _frames()
    time.sleep(REPAINT_WAIT_S)
    # READ BEFORE THE COUNT: `lua` drives, so the file says `acting` while it runs.
    word = _state_file().read_text().strip() if _state_file().exists() else ""
    rose = _rise(after_run, _frames(), "held")
    assert STATE.scratch is not None
    adapter = mpresence.FileAdapter(STATE.scratch, mstate.LOCK, STATE.repaintable,
                                    transport.pending_lines)
    with _by_hand():
        _put(_state_file(), "off")
        by_repaint = repaints_drawn(adapter.repaint)
        by_nothing = repaints_drawn(lambda still: None)
    cell(label, rose >= 1 and word == "held" and by_repaint >= 1 and by_nothing == 0,
         f"after the quiet wait {rose} held repaints (state {word!r}); by hand the repaint "
         f"drew {by_repaint}, no repaint {by_nothing}")


def _judge_window(label: str, off: window_capture.Image, acting: window_capture.Image) -> None:
    try:
        d = window_capture.difference(off, acting)
    except ValueError as e:
        blocked(label, f"the window changed between its two captures: {e}")
        return
    cell(label, *window_capture.edge_verdict(d))


def _window(tag: str) -> window_capture.Image | str:
    """The window captured, or why the host would not."""
    assert STATE.proc is not None
    try:
        return window_capture.capture(STATE.proc.pid, scratch() / f"z-window-{tag}.png")
    except window_capture.Blocked as e:
        return str(e)


def _z_leak(label: str) -> None:
    """THE RED of the stills: the production drawer, moved onto the screen's container and
    reading a file of this cell's own, as a caller's boot harness. Two snapshots with it off
    agree first, so a difference with it on is the drawer's."""
    leak_state = scratch() / "z-leak.state"
    _put(leak_state, "off")
    leaking, moved = re.subn(r"manager\.machine\.render\.ui_container",
                             "manager.machine.screens[':screen'].container",
                             mpresence.drawer(scratch()))
    path_moved = leaking.count(f"{scratch() / mpresence.STATE_FILE}")
    if moved != 1 or path_moved != 1:
        invalid(f"the leaking drawer could not be derived ({moved} containers, {path_moved} "
                "paths moved): the production drawer changed shape")
    leaking = leaking.replace(str(scratch() / mpresence.STATE_FILE), str(leak_state))
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


Z_BOARDS = (Board(_z_circus, (0, 1, 2, 3, 5, 6, 7, 8), lambda: zips_missing("circus")),
            Board(_z_recordings, (4,), lambda: zips_missing("1942")))
boards_cover("Z", Z_CELLS, Z_BOARDS)


def register_z() -> None:
    """Register section Z with the matrix: after every section registered before it."""
    section("Z", Z_TITLE, Z_CELLS)(lambda: run_boards(Z_CELLS, Z_BOARDS))


if __name__ == "__main__":
    register_z()
    run_sections("SECTION Z")
