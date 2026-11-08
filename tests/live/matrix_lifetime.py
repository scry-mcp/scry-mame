"""Section P of the live matrix: a session's two ends and its own declarations store.

The emulator stops three ways, each proved by its process being gone: an ordered `close`, the
server's death (`scry_core.guardian`), and the idle bound (`idle`). Each cell carries its
control: the foreign listener, the SIGKILL with the guardian withheld, the MAME seen alive before
the stop. A `state_dir` session runs over a project store seeded with another session's row,
which it must neither inherit nor touch.

    uv run python tests/live/matrix_lifetime.py
"""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

from bench_boards import SYMBOLS, m68k_dual_missing
from live_harness import (
    BOOT,
    Board,
    boards_cover,
    boot,
    call,
    cell,
    fresh,
    live_tmp,
    ok,
    refused,
    run_boards,
    run_sections,
    said,
    section,
)
from scry_core import guardian

from scry_mame import declarations as dec  # isort: skip -- found through the path the harness sets
from scry_mame import idle  # isort: skip
from scry_mame import launch  # isort: skip
from scry_mame import session as msession  # isort: skip
from scry_mame import stub_owner  # isort: skip

from scry_mame import state as mstate  # isort: skip
from scry_mame.state import STATE  # isort: skip

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import process_probes  # noqa: E402
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
    "an ordered close, stopped, running or altered: exit 0, its pid and guardian gone, status "
    "not alive",
    "a start from a .scry/start profile boots the board, the call's own argument untouched and "
    "the reply naming the file and what it filled",
    "a start from this repository's own .scry/start/m68k-dual.json boots the board, the reply "
    "naming that file and what it filled",
    "the recipe this boot ran and the map it learned are written into a store of the run's own "
    "only when the call approves them, and the map reads back from the file",
], start=1)]

WITHIN_S = 5 * guardian.POLL_S

# `bare` withholds the guardian: the control.
SERVER = """
import json, os, sys, time
from scry_core import guardian
if sys.argv[2] == "bare":
    guardian.spawn = lambda *a, **k: None
from scry_mame import server as s
r = s.start(**json.loads(sys.argv[1]))
print(json.dumps({"status": r["status"], "pid": r.get("pid"), "server": os.getpid(),
                  "said": r.get("summary")}), flush=True)
time.sleep(600)
"""


def _p_port(t: list[str]) -> None:
    r = boot()
    if not ok(r):
        raise RuntimeError(f"m68k-dual did not boot: {said(r)}")
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
    # Force the start race: the probe says the port is free while a foreign listener holds it.
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
    """SIGKILL a child server in `mode`: MAME's pid, was it the server's child, was it gone.
    The server names its own pid: a venv's `python.exe` on Windows is a launcher above it."""
    # A SIGKILLed server leaves its scratch behind, so it must land in this run's tmp.
    server = subprocess.Popen(
        [sys.executable, "-c", SERVER, json.dumps(BOOT), mode],
        stdout=subprocess.PIPE, text=True,
        env={**os.environ, "TMPDIR": f"{live_tmp('mame-live-sigkill-')}{os.sep}"})
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
    host = started.get("server")
    before = alive(mame) and parent_of(mame) == host
    # SIGKILL, or TerminateProcess: no `finally` runs
    os.kill(host if isinstance(host, int) else server.pid, guardian.KILL)
    server.wait()
    gone = gone_within(mame, WITHIN_S)
    if not gone:
        os.kill(mame, guardian.KILL)
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
        raise RuntimeError(f"m68k-dual did not boot: {said(r)}")
    pid = r.get("pid")
    before = isinstance(pid, int) and alive(pid)
    clock = idle.IDLE
    clock.last_call -= idle.IDLE_CLOSE_S + 1
    reaped = clock.reap(mstate.LOCK, STATE.machine_alive, msession.close)
    gone = isinstance(pid, int) and gone_within(pid, WITHIN_S)
    note = str(call("status").get("note", ""))
    cell(t[3], before and reaped and gone and "with no tool call" in note,
         f"alive before {before}, reaped {reaped}, gone {gone}, status note {note[:60]!r}")
    clock.clear_note()


def _put_in_state(state: str) -> bool:
    """`boot` leaves the machine stopped; a running one is released, an altered one has a byte
    written back over itself, which the session counts as an altering write. Whether the session
    block then says so, which is what makes the state reached."""
    if state == "running":
        return call("resume").get("session", {}).get("running") is True
    if state == "altered":
        first = str(call("read_memory", ref="0x0", length=1).get("hex", ""))
        return call("write", ref="0x0", data_hex=first).get("session", {}).get("altered") is True
    return call("status").get("session", {}).get("running") is False


def _guards() -> list[int]:
    """The guardian processes beside this one; on Windows the guardian is a job, not a process,
    so nothing is listed and the check is the pid's alone."""
    return ([] if sys.platform == "win32"
            else process_probes.children_named(os.getpid(), launch.GUARDIAN_NAME))


def _quit_in(state: str) -> tuple[bool, str]:
    r = boot()
    if not ok(r):
        raise RuntimeError(f"m68k-dual did not boot: {said(r)}")
    pid = r.get("pid")
    guards = _guards()
    reached = _put_in_state(state)
    before = (isinstance(pid, int) and alive(pid)
              and (bool(guards) or sys.platform == "win32") and reached)
    shut = call("close")
    gone = isinstance(pid, int) and gone_within(pid, WITHIN_S)
    after = call("status").get("session", {}).get("alive")
    unguarded = not [g for g in guards if alive(g)]
    good = before and shut.get("exit_code") == 0 and gone and after is False and unguarded
    return good, (f"{state}: state reached {reached}, alive and guarded before {before}, how "
                  f"{shut.get('ended_by')}, exit {shut.get('exit_code')}, gone {gone}, status "
                  f"alive {after}, guardian gone {unguarded}")


def _p_quit(t: list[str]) -> None:
    results = [_quit_in(state) for state in ("stopped", "running", "altered")]
    cell(t[7], all(good for good, _ in results), "; ".join(why for _, why in results))


# A stop on a routine a healthy boot never runs, so an inherited row is armed but never hit.
SEEDED = {"kind": "breakpoint", "by": "symbol", "ref": "exception_handler",
          "origin": "another-session", "created_at": "2026-01-01T00:00:00+00:00"}


def _store_key() -> str:
    """The m68k-dual store key; at import it would refuse a host without that board."""
    return dec.store_key(str(BOOT["system"]), SYMBOLS)


# Flooring two readings adds up to a second; the slack bounds a wrong unit, not a slow host.
AGE_GAP_S = 2.2
AGE_SLACK_S = 2


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "absent"


def _declare_all() -> list[dict[str, Any]]:
    """One declaration of every family the store keeps."""
    return [call("breakpoint_at", ref="exception_handler"),
            call("breakpoint_at", ref="0x4a0", role="control"),
            call("watch_add", ref="main_ram", mode="change", length=4),
            call("regpoint_add", condition="d1==0x7fff"),
            call("comment_write", method="add", ref="exception_handler", text="this session's own")]


def _stored_rows(path: Path) -> list[tuple[str, str]]:
    rows = json.loads(path.read_text()).get(_store_key(), []) if path.exists() else []
    return sorted((r.get("kind", ""), r.get("ref", "")) for r in rows)


def _p_own_store(t: list[str]) -> None:
    project = dec.default_path()
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text(json.dumps({_store_key(): [SEEDED]}))
    before = _sha(project)
    own = Path(fresh("-state")) / "declarations.json"
    r = boot(state_dir=str(own.parent))
    if not ok(r):
        raise RuntimeError(f"m68k-dual did not boot: {said(r)}")
    decl = r.get("declarations", {})
    declared = _declare_all()
    rows = _stored_rows(own)
    listed = [*call("declaration_list", kind="breakpoint").get("breakpoints", []),
              *call("declaration_list", kind="watch").get("watches", []),
              *call("declaration_list", kind="regpoint").get("regpoints", []),
              *call("comment_list").get("comments", [])]
    cleared = [call("declaration_clear", kind="breakpoint", all=True), call("declaration_clear",
                                                                            kind="watch", all=True),
               call("declaration_clear", kind="regpoint", all=True),
               call("comment_write", method="delete", ref="exception_handler")]
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
        raise RuntimeError(f"m68k-dual did not boot: {said(r)}")
    call("breakpoint_at", ref="exception_handler")
    first = call("declaration_list", kind="breakpoint").get("breakpoints", [{}])[0].get("age_s")
    time.sleep(AGE_GAP_S)
    second = call("declaration_list", kind="breakpoint").get("breakpoints", [{}])[0].get("age_s")
    call("close")
    cell(t[6], isinstance(first, int) and isinstance(second, int) and 0 <= first < 60
         and int(AGE_GAP_S) <= second - first <= int(AGE_GAP_S) + AGE_SLACK_S,
         f"age_s {first} then {second}, {AGE_GAP_S} s apart")


def _p_profile(t: list[str]) -> None:
    """A store of this run's own, found from the process's directory as a session's is, with a
    `boot_seconds` the call overrides: the caller's own argument is the one that boots."""
    root = Path(fresh("-store"))
    (root / ".scry" / "start").mkdir(parents=True)
    (root / "roms").symlink_to(str(BOOT["rompath"]), target_is_directory=True)
    entry = root / ".scry" / "start" / "probe-profile.json"
    entry.write_text(json.dumps({
        "format": "scry-start/1", "system": BOOT["system"], "rompath": "roms",
        "reference_rom": BOOT["reference_rom"], "binary": BOOT["binary"],
        "inipath": BOOT["inipath"], "boot_seconds": 20.0}), encoding="utf-8")
    here = os.getcwd()
    os.chdir(root)
    try:
        r = call("start", profile="probe-profile", boot_seconds=40.0)
    finally:
        os.chdir(here)
    raw = r.get("profile")
    shown: dict[str, Any] = raw if isinstance(raw, dict) else {}
    shown_file = Path(str(shown.get("file", "")))
    cell(t[8], ok(r) and shown_file.resolve() == entry.resolve()
         and shown.get("supplied") == ["binary", "inipath", "reference_rom", "rompath",
                                       "system"]
         and r.get("system") == BOOT["system"] and STATE.machine_alive(),
         f"{said(r, 90)} / profile {shown}")
    call("close")


def _p_repo_profile(t: list[str]) -> None:
    """The recipe this repository ships, read through the same call the matrix makes: the file
    that boots is the one under `.scry/start`, not a copy of it made in this run."""
    root = Path(__file__).resolve().parents[2]
    entry = root / ".scry" / "start" / "m68k-dual.json"
    r = boot(profile=str(entry))
    raw = r.get("profile")
    shown: dict[str, Any] = raw if isinstance(raw, dict) else {}
    shown_file = Path(str(shown.get("file", "")))
    # `presence` is the harness's own: `call` gives it to every start, so the recipe's value
    # loses to it and the block does not list it. The other eight are the recipe's.
    cell(t[9], ok(r) and shown_file.resolve() == entry.resolve()
         and shown.get("supplied") == ["binary", "boot_seconds", "inipath", "reference_addr",
                                       "reference_rom", "rompath", "symbols", "system"]
         and r.get("system") == BOOT["system"], f"{said(r, 90)} / profile {shown}")
    call("close")


def _p_promote(t: list[str]) -> None:
    """A store of this run's own: what the boot ran and the map it learned are reviewed, then
    the two chosen are written and the map is read back from the file the promotion wrote."""
    STATE.drafts.kept.clear()       # the earlier cells' recipes name this run's scratch
    store = live_tmp("mame-live-promote-")
    ini = store / "ini"
    ini.mkdir()
    for part in Path(str(BOOT["inipath"])).iterdir():
        (ini / part.name).write_bytes(part.read_bytes())
    r = call("start", **cast(dict[str, Any], {**BOOT, "inipath": str(ini)}))
    added = call("screen_map_write", method="add", screen="learned", match=[[0, 0, 8, 8]])
    reviewed = call("promote", dry_run=True, root=str(store))
    found = {c.get("entry"): c.get("change") for c in reviewed.get("candidates", [])}
    created = (store / ".scry").exists()
    written = call("promote", entries=["maps/radendur", "start/radendur"], root=str(store))
    read = call("screen_map_write", method="load",
                path=str(store / ".scry" / "maps" / "radendur.screen-map.json"))
    closed = call("close")
    cell(t[10], ok(r) and ok(added) and ok(reviewed)
         and found.get("maps/radendur") == "new" and found.get("start/radendur") == "new"
         and not created and (store / ".scry").is_dir()
         and ok(written) and sorted(w.get("entry") for w in written.get("written", []))
         == ["maps/radendur", "start/radendur"]
         and not {"maps/radendur", "start/radendur"} & set(written.get("draft", []))
         and ok(read) and read.get("application") == "radendur"
         and not {"maps/radendur", "start/radendur"} & set(closed.get("draft", [])),
         f"{said(reviewed, 80)} / written {written.get('written')} / read {said(read, 60)}")


P_BOARDS = (
    Board(_p_port, (0,), m68k_dual_missing),
    Board(_p_foreign, (1,), m68k_dual_missing),
    Board(_p_sigkill, (2,), m68k_dual_missing),
    Board(_p_idle, (3,), m68k_dual_missing),
    Board(_p_own_store, (4, 5), m68k_dual_missing),
    Board(_p_age, (6,), m68k_dual_missing),
    Board(_p_quit, (7,), m68k_dual_missing),
    Board(_p_profile, (8,), m68k_dual_missing),
    Board(_p_repo_profile, (9,), m68k_dual_missing),
    Board(_p_promote, (10,), m68k_dual_missing),
)
boards_cover("section P", P_CELLS, P_BOARDS)


def register_p() -> None:
    """Register section P after every section registered before it."""
    section("P", P_TITLE, P_CELLS)(lambda: run_boards(P_CELLS, P_BOARDS))


if __name__ == "__main__":
    register_p()
    run_sections("SECTION P")
