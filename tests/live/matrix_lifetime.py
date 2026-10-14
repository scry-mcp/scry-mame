"""Section P of the live matrix: a session's two ends, the port it is reached on and the moment
its emulator stops, and the declarations store a session with its own `state_dir` keeps.

The stub is proved to be this launch's MAME by its pid around the dial (`mame_stub_owner`).
The emulator stops in one of three ways, each proved by its process being gone: an ordered
`close` asks it to quit, the server's death takes it along (`mame_guardian`), and a session
idle past the bound is closed (`mame_idle`). Each cell carries its control: the foreign
listener read back for a dial it must not have had, the same SIGKILL with the guardian
withheld, the MAME seen alive before the bound or the `close` ended it. A `state_dir` session
declares and clears everything over a project store seeded with another session's row, which
it must neither inherit nor touch; its own file is read before the clear, so an unchanged
project hash cannot come from declarations that never landed anywhere. The harness gives each
section a store of its own, so the seed reaches no other.

`live_matrix.py` registers this section before H; run alone, it is the same machinery over this
section only:

    uv run python tests/live/matrix_lifetime.py
"""

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from bench_boards import SYMBOLS, radendur_missing
from live_harness import (
    BOOT,
    Board,
    boards_cover,
    boot,
    call,
    cell,
    fresh,
    ok,
    refused,
    run_boards,
    run_sections,
    said,
    section,
)

import mame_declarations as dec  # isort: skip -- found through the path the harness sets
import mame_guardian as guardian  # isort: skip
import mame_idle as idle  # isort: skip
import mame_launch as launch  # isort: skip
import mame_stub_owner as stub_owner  # isort: skip
import server as s  # isort: skip
from mame_state import STATE  # isort: skip

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from process_probes import alive, gone_within, listener, parent_of  # noqa: E402

P_TITLE = "the session's ends and its own store"
P_CELLS = [f"P{n} {text}" for n, text in enumerate([
    "start with no stub_port dials under the proof, its connection held by the reply's pid",
    "a port another process listens on is refused naming it, and that process got no dial",
    "a SIGKILLed server takes its MAME with it, which outlives it with no guardian",
    "a session idle past the bound is closed, its MAME gone, and status says why",
    "a state_dir session that declares and clears all leaves the project store's bytes unchanged",
    "a state_dir session's own file holds exactly its rows, none inherited from the project's",
    "a listed row carries age_s, which grows with the wall clock between two lists",
    "an ordered close ends MAME by its own quit: exit 0, its pid gone, and status not alive",
], start=1)]

MAME_DIR = Path(launch.__file__).resolve().parent
WITHIN_S = 5 * guardian.GUARDIAN_POLL_S

# The server stand-in for the SIGKILL: the server's own `start`, the guardian withheld when
# told to (the control), MAME's pid printed, then a wait to be killed in.
SERVER = """
import json, sys, time
sys.path.insert(0, sys.argv[1])
import mame_guardian
if sys.argv[3] == "bare":
    mame_guardian.spawn = lambda mame: None
import server as s
r = s.start(**json.loads(sys.argv[2]))
print(json.dumps({"status": r["status"], "pid": r.get("pid"), "said": r.get("summary")}),
      flush=True)
time.sleep(600)
"""


def _p_port(t: list[str]) -> None:
    r = boot()
    if not ok(r):
        raise RuntimeError(f"radendur did not boot: {said(r)}")
    port, pid = r.get("stub_port"), r.get("pid")
    assert STATE.ses is not None
    proof, local = STATE.ses.owner, STATE.ses.local_port
    proved = isinstance(proof, stub_owner.StubOwner) and (proof.pid, proof.port) == (pid, port)
    held = (stub_owner.accepted_by(port, local)
            if isinstance(port, int) and local is not None else set())
    cell(t[0], proved and held == {pid} and port != 23946,
         f"port {port}, pid {pid}, proof {proved}, far end held by {sorted(held)}")
    call("close")


def _p_foreign(t: list[str]) -> None:
    foreign, port = listener("accept", timeout_s=30.0)
    # THE RACE, MADE TO HAPPEN: the probe is told the port is free, as it was for the two
    # starts that collided, so the boot meets the foreign listener where its MAME should be.
    real_free = launch.port_is_free
    launch.port_is_free = lambda port: True
    try:
        r = boot(stub_port=port)
    finally:
        launch.port_is_free = real_free
    mame = r.get("pid")
    foreign.kill()
    assert foreign.stdout is not None
    got = foreign.stdout.read().strip()
    foreign.wait()
    cell(t[1], refused(r, "host_failed") and f"port {port} is served by pid {foreign.pid}"
         in str(r.get("message")) and got == "" and STATE.proc is None
         and not (isinstance(mame, int) and alive(mame)),
         f"{said(r, 90)} / the foreign listener heard {got!r}")


def _orphaned(mode: str) -> tuple[int | None, bool, bool]:
    """A child server started in `mode`, then SIGKILLed: MAME's pid, whether it was that
    server's child before the kill, and whether it was gone within the guardian's polls."""
    server = subprocess.Popen(
        [sys.executable, "-c", SERVER, str(MAME_DIR), json.dumps(BOOT), mode],
        stdout=subprocess.PIPE, text=True)
    assert server.stdout is not None
    try:
        started: dict[str, Any] = json.loads(server.stdout.readline() or "{}")
    except json.JSONDecodeError:
        started = {}
    mame = started.get("pid")
    if not isinstance(mame, int):
        server.kill()
        server.wait()
        return None, False, False
    before = alive(mame) and parent_of(mame) == server.pid
    server.send_signal(signal.SIGKILL)
    server.wait()
    gone = gone_within(mame, WITHIN_S)
    if not gone:
        os.kill(mame, signal.SIGKILL)
    return mame, before, gone


def _p_sigkill(t: list[str]) -> None:
    guarded, guarded_before, guarded_gone = _orphaned("guarded")
    bare, bare_before, bare_gone = _orphaned("bare")
    cell(t[2], guarded_before and guarded_gone and bare_before and not bare_gone,
         f"guarded MAME {guarded}: child {guarded_before}, gone {guarded_gone}; "
         f"bare MAME {bare}: child {bare_before}, gone {bare_gone}")


def _p_idle(t: list[str]) -> None:
    r = boot()
    if not ok(r):
        raise RuntimeError(f"radendur did not boot: {said(r)}")
    pid = r.get("pid")
    before = isinstance(pid, int) and alive(pid)
    clock = idle.IDLE
    clock.last_call -= idle.IDLE_CLOSE_S + 1
    reaped = clock.reap(s._LOCK, STATE.machine_alive, launch.close)
    gone = isinstance(pid, int) and gone_within(pid, WITHIN_S)
    note = str(call("status").get("note", ""))
    cell(t[3], before and reaped and gone and "with no tool call" in note,
         f"alive before {before}, reaped {reaped}, gone {gone}, status note {note[:60]!r}")
    clock.clear_note()


def _p_quit(t: list[str]) -> None:
    r = boot()
    if not ok(r):
        raise RuntimeError(f"radendur did not boot: {said(r)}")
    pid = r.get("pid")
    before = isinstance(pid, int) and alive(pid)
    shut = call("close")
    gone = isinstance(pid, int) and gone_within(pid, WITHIN_S)
    after = call("status").get("alive")
    cell(t[7], before and shut.get("ended_by") == "quit" and shut.get("exit_code") == 0 and gone
         and after is False,
         f"alive before {before}, how {shut.get('ended_by')}, exit {shut.get('exit_code')}, "
         f"gone {gone}, status alive {after}")


# Another session's row in the project store: a stop on a routine a healthy boot never runs, so
# a session that inherited it would hold it armed without ever being cut by it.
SEEDED = {"kind": "breakpoint", "by": "symbol", "ref": "exception_handler",
          "origin": "another-session", "created_at": "2026-01-01T00:00:00+00:00"}
STORE_KEY = dec.store_key(str(BOOT["system"]), SYMBOLS)
# How far apart the two lists of the age cell are, and how much later than that the second may
# read: flooring two readings adds up to a second, the list call's latency the rest, so the slack
# bounds a wrong unit, never a slow host.
AGE_GAP_S = 2.2
AGE_SLACK_S = 2


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "absent"


def _declare_all() -> list[dict[str, Any]]:
    """One declaration of every family the store keeps, the seeded control among them."""
    return [call("breakpoint_at", ref="exception_handler"),
            call("breakpoint_at", ref="0x4a0", role="control"),
            call("watch_add", ref="main_ram", mode="change", length=4),
            call("regpoint_add", condition="d1==0x7fff"),
            call("comment_add", ref="exception_handler", text="this session's own")]


def _stored_rows(path: Path) -> list[tuple[str, str]]:
    rows = json.loads(path.read_text()).get(STORE_KEY, []) if path.exists() else []
    return sorted((r.get("kind", ""), r.get("ref", "")) for r in rows)


def _p_own_store(t: list[str]) -> None:
    project = dec.default_path()
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text(json.dumps({STORE_KEY: [SEEDED]}))
    before = _sha(project)
    own = Path(fresh("-state")) / "declarations.json"
    r = boot(state_dir=str(own.parent))
    if not ok(r):
        raise RuntimeError(f"radendur did not boot: {said(r)}")
    decl = r.get("declarations", {})
    declared = _declare_all()
    rows = _stored_rows(own)
    listed = [*call("breakpoint_list").get("breakpoints", []),
              *call("watch_list").get("watches", []),
              *call("regpoint_list").get("regpoints", []),
              *call("comment_list").get("comments", [])]
    cleared = [call("breakpoint_clear", all=True), call("watch_clear", all=True),
               call("regpoint_clear", all=True),
               call("comment_delete", ref="exception_handler")]
    after_clear = _stored_rows(own)
    call("close")
    landed = all(ok(x) for x in declared) and all(ok(x) for x in cleared)
    cell(t[4], landed and len(rows) == len(declared) and after_clear == []
         and _sha(project) == before,
         f"declared {len(declared)} ok {landed}, own file {len(rows)} rows then "
         f"{len(after_clear)}, project {before[:12]} -> {_sha(project)[:12]}")
    want = sorted([("breakpoint", "exception_handler"), ("breakpoint", "0x4a0"),
                   ("watch", "main_ram"), ("regpoint", "d1==0x7fff"),
                   ("comment", "exception_handler")])
    cell(t[5], decl.get("path") == str(own) and decl.get("held") == 0
         and not decl.get("rearm", {}).get("rearmed") and rows == want
         and len(listed) == len(want) and not any(x.get("inherited") for x in listed),
         f"path {decl.get('path')}, held {decl.get('held')}, own rows {rows}, "
         f"inherited {[x.get('ref') for x in listed if x.get('inherited')]}")


def _p_age(t: list[str]) -> None:
    r = boot(state_dir=fresh("-state"))
    if not ok(r):
        raise RuntimeError(f"radendur did not boot: {said(r)}")
    call("breakpoint_at", ref="exception_handler")
    first = call("breakpoint_list").get("breakpoints", [{}])[0].get("age_s")
    time.sleep(AGE_GAP_S)
    second = call("breakpoint_list").get("breakpoints", [{}])[0].get("age_s")
    call("close")
    cell(t[6], isinstance(first, int) and isinstance(second, int) and 0 <= first < 60
         and int(AGE_GAP_S) <= second - first <= int(AGE_GAP_S) + AGE_SLACK_S,
         f"age_s {first} then {second}, {AGE_GAP_S} s apart")


P_BOARDS = (
    Board(_p_port, (0,), radendur_missing),
    Board(_p_foreign, (1,), radendur_missing),
    Board(_p_sigkill, (2,), radendur_missing),
    Board(_p_idle, (3,), radendur_missing),
    Board(_p_own_store, (4, 5), radendur_missing),
    Board(_p_age, (6,), radendur_missing),
    Board(_p_quit, (7,), radendur_missing),
)
boards_cover("section P", P_CELLS, P_BOARDS)


def register_p() -> None:
    """Register section P with the matrix: after every section registered before it."""
    section("P", P_TITLE, P_CELLS)(lambda: run_boards(P_CELLS, P_BOARDS))


if __name__ == "__main__":
    register_p()
    run_sections("SECTION P")
