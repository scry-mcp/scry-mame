"""Section N of the live matrix: `trace`, the addresses a bounded run executed.

On radendur, the harness's own board, whose maincpu runs its vblank handler at 0x4a0 every frame
and never reaches its exception handler at 0x25a4 on a healthy boot: the set file must hold the
first and not the second. Every predicate is a named function, so each can be shown False on a
copy of its own green reply turned wrong (`MUTATIONS`, run by `--mutations`).

`live_matrix.py` registers this section before H; run alone, it is the same machinery over this
section only:

    uv run python tests/live/matrix_traces.py [--mutations]
"""

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from bench_boards import radendur_missing
from live_harness import (
    WAIT_CEILING_S,
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

import mame_trace as mtrace  # isort: skip -- found through the path the harness sets

# radendur's known answers, written here and not read from the server: the vblank handler, hot
# every frame, and the exception handler, silent on a healthy boot; and the 68000's program
# space, which every subcpu address must sit inside.
VBLANK = "0x000004a0"
EXCEPTION = "0x000025a4"
MASK_68000 = 0xFFFFFF

N_TITLE = "trace: the executed set of a bounded run, read back from its own file"
N_CELLS = [f"N{n} {text}" for n, text in enumerate([
    "radendur maincpu over 2 frames: the set file holds the vblank handler and not the "
    "exception handler, whose address the symbol table confirms",
    "radendur subcpu over 2 frames: trace.cpu is :subcpu and every address is inside its "
    "program space",
    "the set file has exactly trace.addresses rows, ascending, none repeated, and is the raw "
    "trace file's pcs with the parked edges applied from the stop before and the stop after",
    "frames=0 is refused bad_argument and writes no trace file",
    "the same dest again is refused and the file is left byte for byte",
    "a run_for after a trace leaves the trace file as it was, where a tracer left armed through "
    "debug grows its file over the same run",
    "an ignored subcpu traces nothing and is refused readback_refused; observed again it "
    "traces",
    "captures lists the trace, present, as kind trace",
    "a trace on a fresh start leaves session.altered false",
    "one frame and one millisecond past the caps are refused bad_argument, nothing armed",
    "radendur maincpu traced from a fresh start: the pc it was parked on, which the raw file "
    "never logs, is in the set, where only the start edge can have put it",
])]


def rows_of(r: dict[str, Any]) -> list[dict[str, Any]] | None:
    path = (r.get("trace") or {}).get("set_path")
    if not path or not Path(path).is_file():
        return None
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def holds_vblank_not_exception(rows: list[dict[str, Any]] | None) -> bool:
    addrs = {row["addr"] for row in rows or []}
    return VBLANK in addrs and EXCEPTION not in addrs


def subcpu_inside(r: dict[str, Any], rows: list[dict[str, Any]] | None) -> bool:
    return (ok(r) and (r.get("trace") or {}).get("cpu") == ":subcpu" and bool(rows)
            and all(int(row["addr"], 16) <= MASK_68000 for row in rows or []))


def raw_pcs(r: dict[str, Any]) -> list[int]:
    """The pcs of the trace file itself in its order, by a regex the server's parser does not
    share."""
    path = (r.get("trace") or {}).get("path")
    if not path or not Path(path).is_file():
        return []
    return [int(m, 16) for m in re.findall(r"^([0-9A-F]+): ", Path(path).read_text(), re.M)]


def executed(raw: list[int], start: int | None, end: int | None) -> set[int]:
    """The set the window executed, from the raw file and two stops read apart from the trace:
    the last line out when it is where the run ended and appears nowhere else (an arrival), then
    the pc the run started parked on in (executed first, never logged)."""
    out = set(raw)
    if end is not None and raw and raw[-1] == end and raw.count(end) == 1:
        out.discard(end)
    if start is not None:
        out.add(start)
    return out


def set_file_whole(r: dict[str, Any], rows: list[dict[str, Any]] | None, raw: list[int],
                   start: int | None) -> bool:
    # the start read off the stop before: without it the start edge would go unjudged
    if not ok(r) or not rows or not raw or start is None:
        return False
    addrs = [int(row["addr"], 16) for row in rows]
    stopped_here = r.get("cpu") == (r.get("trace") or {}).get("cpu")
    end = int(r["pc"], 16) if stopped_here and isinstance(r.get("pc"), str) else None
    return (len(rows) == (r.get("trace") or {}).get("addresses") and addrs == sorted(addrs)
            and len(set(addrs)) == len(addrs) and set(addrs) == executed(raw, start, end))


def zero_refused(r: dict[str, Any], before: set[str], after: set[str]) -> bool:
    return refused(r, "bad_argument") and bool(before) and before == after


def dest_kept(r: dict[str, Any], before: str | None, after: str | None) -> bool:
    return (refused(r, "bad_argument") and "already exists" in str(r.get("message"))
            and before is not None and before == after)


def closed_size(before: int | None, after: int | None, armed_grew: bool) -> bool:
    return armed_grew and before is not None and before > 0 and before == after


def ignored_then_observed(gone: dict[str, Any], back: dict[str, Any]) -> bool:
    return refused(gone, "readback_refused") and ok(back) and (back.get("trace") or {}).get(
        "addresses", 0) > 0


def listed_as_trace(captures: dict[str, Any], path: str | None) -> bool:
    return any(c.get("kind") == "trace" and c.get("path") == path and c.get("present") is True
               for c in captures.get("captures") or [])


def start_edge_only(rows: list[dict[str, Any]] | None, raw: list[int], start: int | None) -> bool:
    """The window's start pc is in the set and nowhere in the raw file: a window whose start pc
    the run never reached again, so a server without the start edge would leave it out."""
    return (start is not None and bool(raw) and start not in raw
            and set_row_addr(start) in {row["addr"] for row in rows or []})


def set_row_addr(addr: int) -> str:
    """An address as the set file's rows spell it."""
    return f"0x{addr:08x}"


def not_altered(r: dict[str, Any]) -> bool:
    return ok(r) and (r.get("session") or {}).get("altered") is False


def caps_refused(frames: dict[str, Any], ms: dict[str, Any], before: set[str],
                 after: set[str]) -> bool:
    return (refused(frames, "bad_argument") and refused(ms, "bad_argument")
            and "at most" in str(frames.get("message")) and "at most" in str(ms.get("message"))
            and bool(before) and before == after)


def _sha(path: str | None) -> str | None:
    return (hashlib.sha256(Path(path).read_bytes()).hexdigest()
            if path and Path(path).is_file() else None)


def _snap(r: dict[str, Any]) -> set[str]:
    scratch = r.get("scratch_dir")
    return {p.name for p in Path(scratch, "snap").glob("trace-*.trace")} if scratch else set()


def _trace(**kw: Any) -> dict[str, Any]:
    return call("trace", seconds=WAIT_CEILING_S, **kw)


def _size(path: str | None) -> int | None:
    return Path(path).stat().st_size if path and Path(path).is_file() else None


def _n_radendur(t: list[str]) -> None:
    started = boot()
    r = _trace(frames=2)
    cell(t[8], not_altered(r), said(r))
    reset = int(started["pc"], 16) if isinstance(started.get("pc"), str) else None
    cell(t[10], start_edge_only(rows_of(r), raw_pcs(r), reset),
         f"parked at {started.get('pc')}, raw holds it {reset in raw_pcs(r)} / {said(r)}")
    window = call("run_for", frames=60, seconds=WAIT_CEILING_S)
    # a run by frames stops on maincpu, visible, so the trace starts parked where it stopped
    start = int(window["pc"], 16) if window.get("cpu") == ":maincpu" else None
    found = call("symbols_find", name="exception_handler")
    handler = [x.get("addr") for x in found.get("symbols") or []]
    main = _trace(frames=2, cpu="maincpu")
    rows = rows_of(main)
    cell(t[0], ok(main) and handler == [EXCEPTION] and holds_vblank_not_exception(rows),
         f"exception_handler at {handler}, {len(rows or [])} rows / {said(main)}")
    raw = raw_pcs(main)
    cell(t[2], set_file_whole(main, rows, raw, start),
         f"{len(rows or [])} rows, {len(set(raw))} raw pcs, parked at {start}")
    sub = _trace(frames=2, cpu="subcpu")
    sub_rows = rows_of(sub)
    cell(t[1], subcpu_inside(sub, sub_rows), said(sub))
    green = fresh(".json")
    Path(green).write_text(json.dumps({"main": main, "rows": rows, "raw": raw, "start": start,
                                       "sub": sub, "sub_rows": sub_rows}))
    print(f"   green replies for --mutations: {green}")
    before = _snap(started)
    zero = _trace(frames=0)
    cell(t[3], zero_refused(zero, before, _snap(started)), said(zero))
    dest = fresh(".trace")
    first = _trace(frames=2, dest=dest)
    sha = _sha(dest)
    again = _trace(frames=2, dest=dest)
    cell(t[4], ok(first) and dest_kept(again, sha, _sha(dest)), said(again))
    size = _size(dest)
    call("run_for", frames=10, seconds=WAIT_CEILING_S)
    after = _size(dest)
    # the control: the same run with a tracer left armed through `debug` grows its file
    leak = fresh(".trace")
    call("debug", command=f"trace {leak},:maincpu")
    call("run_for", frames=10, seconds=WAIT_CEILING_S)
    call("debug", command="trace off,:maincpu")
    grew = (_size(leak) or 0) > 0
    cell(t[5], closed_size(size, after, grew), f"bytes {size} then {after}; armed control {grew}")
    cell(t[7], listed_as_trace(call("captures"), dest), dest)
    call("debug", command="ignore :subcpu")
    gone = _trace(frames=2, cpu="subcpu")
    call("debug", command="observe :subcpu")
    back = _trace(frames=2, cpu="subcpu")
    cell(t[6], ignored_then_observed(gone, back), f"{said(gone)} / {said(back)}")
    before = _snap(started)
    over_f = _trace(frames=mtrace.FRAMES_MAX + 1)
    over_m = _trace(milliseconds=mtrace.MILLISECONDS_MAX + 1)
    cell(t[9], caps_refused(over_f, over_m, before, _snap(started)),
         f"{said(over_f)} / {said(over_m)}")
    call("close")


N_BOARDS = (
    Board(_n_radendur, tuple(range(len(N_CELLS))), radendur_missing),
)
boards_cover("N_BOARDS", N_CELLS, N_BOARDS)


def register_n() -> None:
    """Register section N with the matrix: after every section registered before it."""
    section("N", N_TITLE, N_CELLS)(lambda: run_boards(N_CELLS, N_BOARDS))


def mutations(green: dict[str, Any]) -> list[tuple[str, bool]]:
    """Each predicate applied to a copy of a green reply turned wrong: every one must be False.
    `green` is the file a green run of `_n_radendur` wrote and printed the path of."""
    main, rows, sub, raw = green["main"], green["rows"], green["sub"], green["raw"]
    start = green["start"]
    wrong_rows = [r for r in rows if r["addr"] != VBLANK] + [{"addr": EXCEPTION}]
    sub_main = {**sub, "trace": {**sub["trace"], "cpu": ":maincpu"}}
    turned_ok = {"summary": "x", "status": "ok", "session": {"altered": False}}
    return [
        ("vblank removed, exception added", holds_vblank_not_exception(wrong_rows)),
        ("subcpu reply naming :maincpu", subcpu_inside(sub_main, green["sub_rows"])),
        ("set file one row short", set_file_whole(main, rows[:-1], raw, start)),
        ("set file far from the raw file", set_file_whole(main, rows, [1, 2, 3], start)),
        ("set file missing the pc parked at both edges",
         set_file_whole(*_both_edges(drop_parked=True))),
        ("start of the window never read", set_file_whole(main, rows, raw, None)),
        ("start pc absent from the set", start_edge_only([], [1, 2], 3)),
        ("start pc in the raw file too", start_edge_only([{"addr": set_row_addr(3)}], [3], 3)),
        ("zero refusal turned ok", zero_refused(turned_ok, {"a"}, {"a"})),
        ("zero refusal over an empty snap", zero_refused(_refusal(), set(), set())),
        ("zero refusal that wrote a file", zero_refused(_refusal(), {"a"}, {"a", "b"})),
        ("dest refusal turned ok", dest_kept(turned_ok, "a", "a")),
        ("file grown by one byte", closed_size(100, 101, True)),
        ("armed control that did not grow", closed_size(100, 100, False)),
        ("ignored trace turned ok", ignored_then_observed(main, main)),
        ("captures without the trace", listed_as_trace({"captures": []}, main["trace"]["path"])),
        ("altered true", not_altered({**main, "session": {"altered": True}})),
        ("cap refusal turned ok", caps_refused(turned_ok, turned_ok, {"a"}, {"a"})),
        ("cap refusal that wrote a file", caps_refused(_cap(), _cap(), {"a"}, {"a", "b"})),
    ]


def controls(green: dict[str, Any]) -> list[tuple[str, bool]]:
    """The same predicates on the green replies and on refusals of the right shape: each must
    be True, or a mutation reading False proves nothing about the predicate."""
    main, rows, sub, raw = green["main"], green["rows"], green["sub"], green["raw"]
    path = main["trace"]["path"]
    dest = {**_refusal(), "message": "dest='x' already exists; this tool never overwrites"}
    gone = {**_refusal(), "code": "readback_refused"}
    return [
        ("vblank in, exception out", holds_vblank_not_exception(rows)),
        ("subcpu inside", subcpu_inside(sub, green["sub_rows"])),
        ("set file whole", set_file_whole(main, rows, raw, green["start"])),
        ("set file holding the pc parked at both edges",
         set_file_whole(*_both_edges(drop_parked=False))),
        ("zero refused", zero_refused(_refusal(), {"a"}, {"a"})),
        ("dest kept", dest_kept(dest, "a", "a")),
        ("closed size", closed_size(100, 100, True)),
        ("ignored then observed", ignored_then_observed(gone, main)),
        ("listed", listed_as_trace({"captures": [{"kind": "trace", "path": path,
                                                  "present": True}]}, path)),
        ("not altered", not_altered(main)),
        ("caps refused", caps_refused(_cap(), _cap(), {"a"}, {"a"})),
    ]


def _both_edges(drop_parked: bool) -> tuple[dict[str, Any], list[dict[str, Any]], list[int],
                                            int]:
    """A window that starts and ends parked on 0x400, logged once at the end: executed once,
    so in the set (Speed Fight's frame stop on its vblank handler)."""
    pcs = [0x402, 0x404] + ([] if drop_parked else [0x400])
    rows = [{"addr": f"{pc:#010x}"} for pc in sorted(pcs)]
    reply = {"summary": "x", "status": "ok", "cpu": ":maincpu", "pc": "0x00000400",
             "trace": {"cpu": ":maincpu", "addresses": len(rows)}, "session": {}}
    return reply, rows, [0x402, 0x404, 0x400], 0x400


def _refusal() -> dict[str, Any]:
    return {"summary": "x", "status": "INVALID", "code": "bad_argument", "message": "x",
            "session": {}}


def _cap() -> dict[str, Any]:
    return {"summary": "x", "status": "INVALID", "code": "bad_argument",
            "message": "frames=9 ... (at most 8)", "session": {}}


if __name__ == "__main__":
    if "--mutations" in sys.argv:
        green = json.loads(Path(sys.argv[sys.argv.index("--mutations") + 1]).read_text())
        base = controls(green)
        for name, value in base:
            print(f"{'GREEN' if value is True else 'NOT GREEN'} {name}: {value}")
        out = mutations(green)
        for name, value in out:
            print(f"{'RED ' if value is False else 'NOT RED'} {name}: {value}")
        if not out:
            print("INVALID: no mutation examined")
            sys.exit(3)
        sys.exit(0 if all(v is False for _, v in out) and all(v is True for _, v in base)
                 else 1)
    register_n()
    run_sections("SECTION N")
