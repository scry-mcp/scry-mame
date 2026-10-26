"""Section Q of the live matrix: saved states. Run alone:

    MAME_STOCK_BINARY=... MAME_TEST_ROMS=... uv run python tests/live/matrix_states.py

topgunnr's main cpu sits in a short loop, so a run can bring it back to the saved block and then
no load is proved: the cells that need the block to have moved say BLOCKED, not judge nothing.
"""

import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

from live_harness import (
    Board,
    blocked,
    boards_cover,
    call,
    cell,
    circus_boot,
    free_boards_missing,
    free_boot,
    fresh_state,
    last_wall,
    ok,
    refused,
    run_boards,
    run_sections,
    said,
    section,
    unavailable_why,
)
from scry_core import host_program

from mame_state import STATE  # isort: skip -- found through the path the harness sets

Q_TITLE = "saved states: what is not a state, a load proved by the registers, a stale counter"
Q_CELLS = [
    "circus: a .sta that is a directory, a link to one or a FIFO is listed with null bytes and "
    "what it is, and its load is refused unknown_ref at once",
    "circus: a load after a run is verified",
    "circus: a state loaded with nothing run since its save is not verified, and says why",
    "circus: stateload, rewind and softreset typed through debug withhold the next run's cycles, "
    "and the run after reports them",
    "topgunnr: a load after a run is verified by the main cpu's register block, with no frame "
    "counter",
    "topgunnr: a state file swapped for another save is refused, naming the register that "
    "differs",
    "circus: a rewind the console refused (no state to step back to) replaced nothing, and the "
    "next run reports the cycles a control run of the same length did",
    "victory: a load MAME held behind a sound command written through the stub is completed by "
    "one step, verified, and does not land in the next run",
]

#: A server opening a FIFO blocks until a writer comes; the harness opens the other end after this.
FIFO_RELEASE_S = 3.0


def _release_after(path: Path) -> threading.Thread:
    """Open and close `path`'s writing end after `FIFO_RELEASE_S`, releasing a blocked reader."""
    def release() -> None:
        time.sleep(FIFO_RELEASE_S)
        host_program.release_fifo(path)
    thread = threading.Thread(target=release, daemon=True)
    thread.start()
    return thread


def _not_states(t: str) -> None:
    folder = Path(str(call("state_list").get("state_dir")))
    folder.mkdir(parents=True, exist_ok=True)
    elsewhere = folder.parent / "q-elsewhere"
    elsewhere.mkdir(exist_ok=True)
    made = {"qdir": "a directory", "qlink": f"a link to {elsewhere}, which is a directory"}
    (folder / "qdir.sta").mkdir()
    (folder / "qlink.sta").symlink_to(elsewhere)
    if sys.platform != "win32":                 # Windows has no FIFO
        made["qfifo"] = "a FIFO"
        os.mkfifo(folder / "qfifo.sta")
    try:
        rows = {r["name"]: r for r in call("state_list").get("states") or []}
        listed = {name: (rows.get(name, {}).get("bytes") or {}) for name in made}
        loads: dict[str, tuple[Any, bool, float]] = {}
        for name, what in made.items():
            release = _release_after(folder / f"{name}.sta") if name == "qfifo" else None
            r = call("state_write", method="load", name=name)
            loads[name] = (r.get("code"), what in str(r.get("message")), last_wall())
            if release is not None:
                release.join()
        cell(t, all(b.get("available") is False and what in str(b.get("why"))
                    for b, what in zip(listed.values(), made.values(), strict=True))
             and all(code == "unknown_ref" and named and wall < FIFO_RELEASE_S
                     for code, named, wall in loads.values()),
             f"listed {listed}; loads (code, names it, wall s) {loads}")
    finally:
        for name in ("qdir.sta", "qlink.sta", "qfifo.sta"):
            p = folder / name
            if p.is_dir() and not p.is_symlink():
                p.rmdir()
            else:
                p.unlink(missing_ok=True)
        shutil.rmtree(elsewhere, ignore_errors=True)


def _cycles_of(r: dict[str, Any]) -> tuple[Any, Any]:
    return r.get("cycles"), unavailable_why(r.get("cycles"))


def _q_circus(t: list[str]) -> None:
    circus_boot("rewind 1\n")
    _not_states(t[0])
    call("run_for", frames=10, seconds=10.0)
    first = fresh_state()
    call("state_write", method="save", name=first)
    call("run_for", frames=7, seconds=10.0)
    loaded = call("state_write", method="load", name=first)
    cell(t[1], ok(loaded) and loaded.get("verified") is True, said(loaded, 160))
    again = fresh_state()
    call("state_write", method="save", name=again)
    at_once = call("state_write", method="load", name=again)
    cell(t[2], ok(at_once)
         and "before the load" in str(unavailable_why(at_once.get("verified"))),
         said(at_once, 200))
    seen: dict[str, Any] = {}
    call("run_for", frames=5, seconds=10.0)
    for line in (f"stateload {first}", "rewind", "softreset"):
        if line == "rewind":
            for _ in range(3):
                call("step")          # debugger steps capture the rewind states
        typed = call("debug", command=line)
        stale = call("run_for", frames=2, seconds=10.0)
        after = call("run_for", frames=2, seconds=10.0)
        seen[line] = (ok(typed) and "error" not in str(typed.get("output")).lower(),
                      _cycles_of(stale), _cycles_of(after))
    cell(t[3], all(typed and stale[1] and isinstance(after[0], int)
                   and after[0] > 0 and after[1] is None
                   for typed, stale, after in seen.values()), str(seen))
    call("close")


def _q_circus_refused_rewind(t: list[str]) -> None:
    """A rewind with no captured state is refused, and the next run is counted like a control."""
    circus_boot("rewind 1\n")
    call("run_for", frames=10, seconds=10.0)
    control = call("run_for", frames=2, seconds=10.0)
    typed = call("debug", command="rewind")
    after = call("run_for", frames=2, seconds=10.0)
    refused_it = "Rewind error occured" in str(typed.get("output"))
    # within a tenth of the control: a count across a replaced machine is off by the state distance
    cell(t[6], ok(typed) and refused_it and isinstance(control.get("cycles"), int)
         and isinstance(after.get("cycles"), int)
         and abs(after["cycles"] - control["cycles"]) * 10 <= control["cycles"],
         f"refused {refused_it}; control {_cycles_of(control)}, after {_cycles_of(after)}")
    call("close")


def _q_topgunnr(t: list[str]) -> None:
    started = free_boot("topgunnr", ["tgl-2.9r", "tgl-2.10r"], "0x804000")
    counted = isinstance(started.get("frame_symbol"), str)
    call("run_for", milliseconds=200, seconds=10.0)
    first = fresh_state()
    call("state_write", method="save", name=first)
    call("run_for", milliseconds=137, seconds=10.0)
    loaded = call("state_write", method="load", name=first)
    if ok(loaded) and "before the load" in str(unavailable_why(loaded.get("verified"))):
        blocked(t[4], f"the block came back to the saved one before the load: {said(loaded)}")
    else:
        cell(t[4], ok(loaded) and loaded.get("verified") is True, said(loaded, 200))
    # two saves whose blocks differ, the second's file put where the first's is
    names = [fresh_state(), fresh_state()]
    call("run_for", milliseconds=137, seconds=10.0)
    call("state_write", method="save", name=names[0])
    for _ in range(5):
        call("run_for", milliseconds=50, seconds=10.0)
        call("state_write", method="save", name=names[1])
        if STATE.states[names[1]]["blocks"] != STATE.states[names[0]]["blocks"]:
            break
        Path(str(call("state_list").get("state_dir")), f"{names[1]}.sta").unlink()
        STATE.states.pop(names[1], None)
    else:
        blocked(t[5], "five saves 50 ms apart all read the first one's block")
        call("close")
        return
    if counted:
        # MAME 0.289's release gives the board a frame counter, and the swap is then refused by
        # its frame and pc, before any register is compared.
        blocked(t[5], f"this build's topgunnr has a frame counter ({said(started, 60)})")
        call("close")
        return
    folder = Path(str(call("state_list").get("state_dir")))
    shutil.copyfile(folder / f"{names[1]}.sta", folder / f"{names[0]}.sta")
    swapped = call("state_write", method="load", name=names[0])
    differs = swapped.get("differs") or {}
    cell(t[5], refused(swapped, "readback_refused") and differs.get("cpu") == ":maincpu"
         and differs.get("saved") != differs.get("loaded")
         and str(differs.get("register")) in str(swapped.get("message")), said(swapped, 220))
    call("close")


def _q_victory_held(t: list[str]) -> None:
    """The stub's write runs victory's synchronizing sound handler, so the next load is held."""
    free_boot("victory", ["vic3.j2"], "0x0")
    call("run_for", frames=10, seconds=10.0)
    name = fresh_state()
    saved = call("state_write", method="save", name=name)
    call("run_for", frames=5, seconds=10.0)
    wrote = call("write", ref="0xf800", data_hex="01")
    loaded = call("state_write", method="load", name=name)
    after = call("run_for", frames=1, seconds=10.0)
    cell(t[7], ok(saved) and "held" not in saved and ok(wrote) and ok(loaded)
         and "held" in loaded and loaded.get("verified") is True
         and loaded.get("frame") == saved.get("frame")
         and after.get("frame") == int(saved.get("frame") or 0) + 1,
         f"saved at {saved.get('frame')}; load held {'held' in loaded}, verified "
         f"{loaded.get('verified')}, frame {loaded.get('frame')}; "
         f"one frame on {after.get('frame')}")
    call("close")


Q_BOARDS = (Board(_q_circus, (0, 1, 2, 3), free_boards_missing),
            Board(_q_topgunnr, (4, 5), free_boards_missing),
            Board(_q_circus_refused_rewind, (6,), free_boards_missing),
            Board(_q_victory_held, (7,), free_boards_missing))
boards_cover("section Q", Q_CELLS, Q_BOARDS)


def register_q() -> None:
    """Register section Q with the matrix: after every section registered before it."""
    section("Q", Q_TITLE, Q_CELLS)(lambda: run_boards(Q_CELLS, Q_BOARDS))


if __name__ == "__main__":
    register_q()
    run_sections("SECTION Q")
