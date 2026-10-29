"""Section K of the live matrix: links, counts, queued installs and lost removals."""


from pathlib import Path
from typing import Any

from bench_boards import (
    m68k_dual_missing,
)
from live_harness import (
    Board,
    blocked,
    boards_cover,
    boot,
    call,
    cell,
    circus_boot,
    free_boards_missing,
    ok,
    refused,
    run_boards,
    said,
    section,
)
from matrix_removals import (
    K_CAPTURE_LEFTOVER,
    K_REDECLARE_LIVE,
    K_REMOVALS,
    k_capture_leftover,
    k_redeclare_live,
    k_removals,
)
from reader_fault import reader_fault, reader_fault_counts

from scry_mame import transport

# A bool is an `int` to Python, and a client's schema refuses it before any tool runs, so only a
# direct call (what `call` makes) reaches the server's guard. Queued installs still to run are
# waiting, not lost.

K_OWN = [
    "circus: state_list lists the saved state with its bytes",
    "circus: state_list lists a link to nothing with bytes unavailable and its why",
    "circus: state_write load refuses a link to nothing as unknown_ref naming it",
    "circus: state_write save refuses the link's name as already there",
    "circus: run_for refuses frames=True and the frame does not move",
    "circus: resume refuses seconds=False and the machine stays stopped",
    "circus: four count watches queued while stopped: none resent across four frames, all "
    "installed by then, none lost",
]
K_RESEND = [
    "the reader fault kills its install line, where the control's install answers at once",
    "an install whose reader dies once is resent once and installed",
    "an install whose reader dies twice is install_lost at the stop, and stays lost",
    "an install handed back with no death is resent while the machine only steps",
    "an install whose reader lags three frames is neither resent nor lost, then installed",
]


def on_board(board: str, whats: list[str]) -> list[str]:
    """`whats` as `board`'s cells."""
    return [f"{board}: {what}" for what in whats]


K_LEFTOVER, K_REDECLARE = f"m68k-dual: {K_CAPTURE_LEFTOVER}", f"circus: {K_REDECLARE_LIVE}"
K_CELLS = (K_OWN + on_board("circus", K_RESEND + K_REMOVALS)
           + on_board("m68k-dual", K_RESEND + K_REMOVALS) + [K_LEFTOVER, K_REDECLARE])


def _states_by_name(r: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["name"]: row for row in r.get("states") or []}


def _stop_and_frame(status: dict[str, Any]) -> tuple[Any, Any]:
    """The last stop's number and frame; not `last_stop` whole, whose `since_s` ticks."""
    last = status.get("last_stop") or {}
    return last.get("stop_seq"), last.get("frame")


def _k_circus(_cells: list[str]) -> None:
    t = K_OWN
    circus_boot()
    saved = call("state_write", method="save", name="kept")
    listed = call("state_list")
    mine = _states_by_name(listed).get("kept", {})
    # Control, taken before any link exists, so a FAIL below is about the link.
    cell(t[0], ok(saved) and ok(listed) and isinstance(mine.get("bytes"), int)
         and mine.get("bytes") == saved.get("bytes"), f"{said(saved, 50)}; {mine}")
    folder = Path(str(listed.get("state_dir")))
    link, target = folder / "dangle.sta", folder / "nowhere" / "dangle.sta"
    try:
        link.symlink_to(target)
        listed = call("state_list")
        row = _states_by_name(listed).get("dangle", {})
        gone = [row.get(k) or {} for k in ("bytes", "frame", "pc")]
        cell(t[1], ok(listed) and "why" not in row
             and all(g.get("available") is False and str(target) in str(g.get("why"))
                     for g in gone), said(listed) if not row else str(row))
        load = call("state_write", method="load", name="dangle")
        cell(t[2], refused(load, "unknown_ref") and str(link) in str(load.get("message"))
             and str(target) in str(load.get("message")), said(load, 160))
        again = call("state_write", method="save", name="dangle")
        cell(t[3], refused(again, "bad_argument") and "already exists" in str(again.get("message")),
             said(again))
    finally:
        link.unlink(missing_ok=True)
        (folder / "kept.sta").unlink(missing_ok=True)
    before = _stop_and_frame(call("status"))
    ran = call("run_for", frames=True, seconds=5.0)
    after = _stop_and_frame(call("status"))
    cell(t[4], refused(ran, "bad_argument") and None not in before and after == before,
         f"{said(ran)}; (stop_seq, frame) {before} -> {after}")
    released = call("resume", seconds=False)
    now = call("status")
    if now.get("session", {}).get("running"):
        call("stop")
    cell(t[5], refused(released, "bad_argument") and now.get("session", {}).get("running") is False,
         f"{said(released)}; running after it: {now.get('running')}")
    # The fault holds the first install two frames so the other three queue behind it past the
    # first stop, whose console commands would drain a released queue (REFERENCE.md, *The
    # console*). No queue means nothing to judge: BLOCKED.
    call("run_for", frames=3, seconds=5.0)
    call("throttle", on=False)
    call("step")
    planted = reader_fault(f"tally-{_tally_id('0x20', 1)}.txt", lag=2)
    adds = [call("watch_add", ref=ref, mode="count", length=1)
            for ref in ("0x20", "0x36", "0x1f", "0x1b")]
    ran = call("run_for", frames=1, seconds=5.0)
    rows = ran.get("watches") or []
    queued = [w.get("installed", True) for w in rows]
    later = [call("run_for", frames=1, seconds=5.0) for _ in range(3)][-1]
    settled = [(w.get("installed", True), w.get("install_resent", 0))
               for w in later.get("watches") or []]
    lost = call("status")["session"]["console"]["lost"]
    detail = (f"lines_ahead {[a.get('lines_ahead') for a in adds]}; after one frame installed "
              f"{queued}, resent {[w.get('install_resent', 0) for w in rows]}; "
              f"three frames on {settled}, lost {lost}")
    if not (ok(planted) and "planted" in str(planted.get("output"))):
        blocked(t[6], f"the reader fault was not planted, so nothing was held: {detail}")
    elif all(ok(a) for a in adds) and ok(ran) and queued == [True] * 4:
        blocked(t[6], f"no install was still queued after the frame, nothing to judge: {detail}")
    else:
        cell(t[6], all(ok(a) for a in adds) and ok(ran) and ok(later)
             and [w.get("install_resent", 0) for w in rows] == [0, 0, 0, 0]
             and settled == [(True, 0)] * 4 and lost == 0, detail)
    call("declaration_clear", kind="watch", all=True)
    refs = ("0x20", "0x36", "0x1f", "0x1b")
    _k_resend(on_board("circus", K_RESEND), refs, 1)
    k_removals(on_board("circus", K_REMOVALS), refs[1:], 1)
    call("close")


def _k_m68k_dual(_cells: list[str]) -> None:
    boot()
    call("run_for", frames=3, seconds=10.0)
    refs = ("0x70001e", "0x70001c", "0x70001a", "0x700018")
    _k_resend(on_board("m68k-dual", K_RESEND), refs, 2)
    # The last range is the frame counter's low word; the blitter's can go three frames unwritten.
    k_removals(on_board("m68k-dual", K_REMOVALS), (refs[1], refs[2], "0x2031fe"), 2)
    k_capture_leftover(K_LEFTOVER, "0x2031fc", "0x2031fe")
    call("close")


def _k_circus_redeclare(_cells: list[str]) -> None:
    # 0x1b is written every frame
    circus_boot()
    call("run_for", frames=3, seconds=10.0)
    k_redeclare_live(K_REDECLARE, "0x1b", 1)
    call("close")


def _tally_id(ref: str, length: int) -> str:
    """The `tally_id` of a count watch on `ref`, known before the watch exists."""
    return f"{int(ref, 16):x}_{length}"


def _k_resend(t: list[str], refs: tuple[str, ...], length: int) -> None:
    """`K_RESEND`'s five cells on a stopped machine, one count watch per `refs` entry. Only the
    first cell carries the control; the rest stand on it."""
    def tid(ref: str) -> str:
        return _tally_id(ref, length)

    def add(ref: str) -> dict[str, Any]:
        r = call("watch_add", ref=ref, mode="count", length=length)
        r["mine"] = ok(r) and r.get("tally_id") == tid(ref)    # the id the fault targets
        return r

    def mine(r: dict[str, Any], ref: str) -> dict[str, Any]:
        return next((w for w in r.get("watches") or [] if w.get("ref") == ref), {})

    def seen(r: dict[str, Any], ref: str) -> tuple[Any, Any, Any]:
        """A stop's row: installed, state, and how often the install was resent."""
        w = mine(r, ref)
        return w.get("installed", bool(w)), w.get("state"), w.get("install_resent", 0)

    def fault(ref: str, **how: Any) -> bool:
        planted = reader_fault(f"tally-{tid(ref)}.txt", **how)
        return ok(planted) and "planted" in str(planted.get("output"))

    def lost() -> Any:
        return (call("status").get("session") or {}).get("console", {}).get("lost")

    def cell_if_planted(label: str, planted: bool, condition: bool, detail: str) -> None:
        """BLOCKED when the plant did not take: nothing was faulted to judge."""
        if planted:
            cell(label, condition, detail)
        else:
            blocked(label, f"the reader fault was not planted, so nothing was faulted: {detail}")

    def log() -> bytes:
        return Path(str(call("status").get("stdout_path"))).read_bytes()

    # Control: no fault, nothing ahead in the pipe.
    for _ in range(4):
        if not call("status").get("console_pending"):
            break
        call("run_for", frames=1, seconds=5.0)
    control = add(refs[0])
    ctl = seen(call("step"), refs[0])
    call("declaration_clear", kind="watch", ref=refs[0])
    planted = fault(refs[1], kills=1)
    mark = len(log())
    added = add(refs[1])
    first = call("step")
    fired = reader_fault_counts()[0]
    # The plant's own echo travels split, so only a real death carries the line whole.
    after_add = log()[mark:]
    at = after_add.find(f"tally-{tid(refs[1])}.txt".encode())
    died = at >= 0 and b"[LUA ERROR] in thread: killed" in after_add[at:]
    cell_if_planted(t[0], planted, control["mine"] and control.get("lines_ahead") == 0
          and ctl == (True, "tallied", 0) and added["mine"] and fired == 1 and died,
          f"control {ctl}, lines_ahead {control.get('lines_ahead')}; planted {planted}; "
          f"fired {fired}; death behind the echo {died}")
    second = call("step")
    once = [seen(first, refs[1]), seen(second, refs[1])]
    cell_if_planted(t[1], planted, once[0][2] == 1 and once[0][0] is False
          and mine(first, refs[1]).get("pending") is True
          and once[1] == (True, "tallied", 1), f"step by step {once}")
    call("declaration_clear", kind="watch", ref=refs[1])

    lost_before = lost()
    planted = fault(refs[2], kills=2)
    added = add(refs[2])
    twice = [seen(call("step"), refs[2]) for _ in range(3)]
    fired = reader_fault_counts()[0]
    cell_if_planted(t[2], planted, added["mine"] and fired == 2 and twice[0][2] == 1
          and twice[1:] == [(False, "install_lost", 1)] * 2
          and isinstance(lost_before, int) and lost() == lost_before + 2,
          f"fired {fired}; steps {twice}; lost {lost_before} -> {lost()}")
    call("declaration_clear", kind="watch", ref=refs[2])

    before = _stop_and_frame(call("status"))[1]
    planted = fault(refs[3], kills=1, loud=False)
    mark = len(log())
    added = add(refs[3])
    quiet = [seen(call("step"), refs[3]) for _ in range(4)]
    after = _stop_and_frame(call("status"))[1]
    fired = reader_fault_counts()[0]
    # Silent: nothing between the echo and the next prompt.
    tail = log()[mark:]
    echo = tail.find(f"tally-{tid(refs[3])}.txt".encode())
    gap = tail[echo:tail.find(transport.CONSOLE_PROMPT, echo)] if echo >= 0 else b""
    silent = echo >= 0 and transport.CONSOLE_PROMPT in tail[echo:] and b"[LUA ERROR]" not in gap \
        and b"error:" not in gap
    cell_if_planted(t[3], planted, added["mine"] and fired == 1 and silent and before is not None
          and before == after and quiet[-1] == (True, "tallied", 1)
          and all(q[1] != "install_lost" for q in quiet),
          f"fired {fired}; prompt-only {silent}; frame {before} -> {after}; steps {quiet}")
    call("declaration_clear", kind="watch", ref=refs[3])

    lost_before = lost()
    planted = fault(refs[0], lag=3)
    added = add(refs[0])
    lagging = [seen(call("run_for", frames=1, seconds=5.0), refs[0]) for _ in range(6)]
    _fired, lagged, held = reader_fault_counts()
    detail = (f"held {held} frames over {lagged} hook runs; frame by frame {lagging}; "
              f"lost {lost_before} -> {lost()}")
    if planted and added["mine"] and held < 1:
        blocked(t[4], f"the reader was not held past a frame, nothing to judge: {detail}")
    else:
        cell_if_planted(t[4], planted, added["mine"]
              and all(lg[2] == 0 and lg[1] != "install_lost" for lg in lagging)
              and lagging[-1] == (True, "tallied", 0) and isinstance(lost_before, int)
              and lost() == lost_before, detail)
    call("declaration_clear", kind="watch", all=True)


def k_owned(labels: list[str]) -> tuple[int, ...]:
    """The indexes of `labels` in `K_CELLS`."""
    return tuple(K_CELLS.index(label) for label in labels)


K_BOARDS = (Board(_k_circus, k_owned(K_OWN + on_board("circus", K_RESEND + K_REMOVALS)),
                  free_boards_missing),
            Board(_k_m68k_dual, k_owned(on_board("m68k-dual", K_RESEND + K_REMOVALS)
                                       + [K_LEFTOVER]), m68k_dual_missing),
            Board(_k_circus_redeclare, k_owned([K_REDECLARE]), free_boards_missing))
boards_cover("K_BOARDS", K_CELLS, K_BOARDS)


@section("K", "a link where a state goes, a bool given as a count, installs queued, resent and "
         "lost, removals lost and never resent", K_CELLS)
def block_k_defects() -> None:
    run_boards(K_CELLS, K_BOARDS)
