"""Section C.16 of the live matrix: `debug` writes whose effect lives in a parameter, and a
condition judged on another cpu whose visible cpu cannot be put back (m68k-dual).

Each write cell has its read beside it, so a cell cannot pass on a classifier that marks
everything. Run alone, it is the same machinery over this section only:

    uv run python tests/live/matrix_console.py
"""

import time
from pathlib import Path
from typing import Any

from bench_boards import SUB_SYMBOLS, SYMBOLS
from live_harness import boot, call, cell, live_tmp, ok, run_sections, said, section

from mame_state import STATE  # isort: skip -- found through the path the harness sets

MAIN, SUB = ":maincpu", ":subcpu"

C16_TITLE = ("16. the console's grammar in a parameter, a visible cpu not put back, and a stop "
             "inside a declaring call")
C16 = [
    "a bare suspend, resume, ignore or observe lists: no write, and no cpu read back",
    "suspend and resume naming a cpu are writes",
    "a trace with an action is a write, and one with none a read",
    "source runs a file of console commands, and is a write",
    "// and /* are the comment pane's commands: answered, and never a write",
    "a condition judged on the other cpu whose put-back is refused keeps its outcome, names "
    "the cpu left visible, and stores nothing",
    "a registerpoint added while running whose own stop arrives during the call says "
    "while_running",
    "a typed hardreset is refused unsent, and the session still runs",
]


def _writes() -> Any:
    return call("status")["session"]["altering_writes"]


def c16_console() -> None:
    boot(symbols={MAIN: SYMBOLS, SUB: SUB_SYMBOLS})
    call("run_for", frames=60, seconds=10.0)  # sub cpu out of reset
    t = C16
    before = _writes()
    bare = {word: call("debug", command=word)
            for word in ("suspend", "resume", "ignore", "observe")}
    cell(t[0], all(ok(r) and r.get("mutates") is False and "visible_cpu" not in r
                   and "ignored" not in r for r in bare.values()) and _writes() == before,
         "; ".join(f"{w}: {said(r, 60)} mutates {r.get('mutates')} "
                   f"visible_cpu {'visible_cpu' in r}" for w, r in bare.items()))
    named = [call("debug", command=f"{word} {SUB}") for word in ("suspend", "resume")]
    cell(t[1], all(ok(r) and r.get("mutates") is True for r in named),
         "; ".join(said(r, 60) for r in named))
    log = str(live_tmp("mame-live-c16-"))
    acted = call("debug", command=f"trace {log}/a.log,{MAIN},noloop,{{print pc}}")
    call("debug", command=f"trace off,{MAIN}")
    plain = call("debug", command=f"trace {log}/b.log,{MAIN}")
    call("debug", command=f"trace off,{MAIN}")
    cell(t[2], ok(acted) and acted.get("mutates") is True and ok(plain)
         and plain.get("mutates") is False,
         f"with an action {said(acted, 60)} mutates {acted.get('mutates')}; without "
         f"{said(plain, 60)} mutates {plain.get('mutates')}")
    script = Path(log) / "script.txt"
    script.write_text("print pc\n")
    sourced = call("debug", command=f"source {script}")
    cell(t[3], ok(sourced) and sourced.get("mutates") is True,
         f"{said(sourced, 80)} mutates {sourced.get('mutates')}")
    before = _writes()
    pane = [call("debug", command=f"{word} 0x400,c16 note") for word in ("//", "/*")]
    cell(t[4], all(ok(r) and r.get("mutates") is False for r in pane) and _writes() == before,
         "; ".join(f"{said(r, 60)} mutates {r.get('mutates')}" for r in pane))
    # a run by frames stops on the main cpu; ignoring the sub cpu shown runs nothing
    call("run_for", frames=1, seconds=10.0)
    declared = (call("cpu_info", cpu=MAIN).get("cpus") or [{}])[0].get("declarations")
    shown = call("focus", cpu=SUB)
    ignored = call("debug", command=f"ignore {SUB}")
    out = call("breakpoint_at", ref="0x400", condition="d0==1", cpu=MAIN)
    visible = call("cpu_info", cpu=MAIN)
    listed = (visible.get("cpus") or [{}])[0].get("declarations")
    call("debug", command=f"observe {SUB}")
    message = str(out.get("message"))
    cell(t[5], ok(shown) and ok(ignored) and out.get("status") == "INVALID"
         and "evaluates" in message and SUB in message and out.get("visible_cpu") == MAIN
         and declared is not None and listed == declared
         and (visible.get("cpus") or [{}])[0].get("visible") is True,
         f"focus {said(shown, 50)}; ignore {said(ignored, 50)}; {said(out, 200)}; "
         f"declarations on {MAIN} {declared} -> {listed}")
    # the rplist readback is held back so the condition's stop lands before the reply is composed
    ses = STATE.ses
    assert ses is not None
    send = ses.monitor

    def slow(command: str, *a: Any, **k: Any) -> str:
        if command == "rplist":
            time.sleep(0.5)
        return str(send(command, *a, **k))

    ses.monitor = slow  # type: ignore[method-assign]
    try:
        released = call("resume")
        added = call("regpoint_add", condition="pc!=0")
        stopped = (call("status").get("last_stop") or {}).get("cause")
    finally:
        ses.monitor = send  # type: ignore[method-assign]
    call("declaration_clear", kind="regpoint", all=True)
    cell(t[6], ok(released) and ok(added) and added.get("while_running") is True
         and (added.get("session") or {}).get("running") is False
         and stopped == "registerpoint 'pc!=0'",
         f"{said(added, 80)}; while_running {added.get('while_running')}; last stop {stopped}")
    hard = call("debug", command="hardreset")
    after = call("run_for", frames=2, seconds=10.0)
    cell(t[7], hard.get("status") == "INVALID" and hard.get("code") == "bad_argument"
         and "`close`" in str(hard.get("message")) and ok(after),
         f"{said(hard, 120)}; then {said(after, 80)}")
    call("close")


def register_c16() -> None:
    """Register section C.16 after every section registered before it."""
    section("C", C16_TITLE, C16)(c16_console)


if __name__ == "__main__":
    register_c16()
    run_sections("SECTION C.16")
