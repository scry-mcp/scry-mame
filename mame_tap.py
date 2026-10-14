"""A LUA WRITE TAP'S LIFE, whatever it counts or keeps: the skeleton its install script is composed
on, the install sent down the console's pipe and proved by the line it prints, its removal sent
and read back, its dump read at a stop and judged current or superseded. The count watch
(`mame_tally`), the capture (`mame_capture`), the film and the palette write log each compose
their own install script and ride this one lifecycle, so the rules of sending, proving and
reading a tap are written once.

SENT, NEVER STEPPED FOR. An install is put in the console's pipe like a `throttle` asked while
stopped: it is evaluated when the console next reads a line (the install's `note` says what makes
it read one), and the first survey after that reads its sentinel back, which is where `installed`
(or the console's own error) comes from. Arming a change watch moves nothing, and a tap does the
same: a `watch_add` that stepped the machine to prove its tap would move the pc of the stop the
caller is standing on. The script is the server's own and only reads, so the send is not counted
as a write and `altered` stays.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import mame_callbacks as callbacks
import mame_declarations as dec
import mame_files as mfiles
import mame_space as mspace
import mame_state as st
import mame_transport as transport
from mame_state import STATE

# ------------------------------------------------------------------ the install script's skeleton
#
# The fragments every tap's install is composed of, and the Lua locals they hand each other:
# `tap_prelude` binds `T`, the registry; `bound_cpu` binds `dbg` (which a palette log's `by()`
# reads too) and `cpu`; `REMOVE_OLD_TAP` reads `T` and the caller's `id`, and binds `old` for the
# carry-over that follows it; `register_dumper_once` reads `T`.


def tap_prelude(registry: str) -> str:
    """How every tap's install opens: the callback guard, then its registry in the MAME process's
    `_G`, made by the first install and found by every later one."""
    return callbacks.LUA + (f"local T = _G.{registry}\n"
                            f"if T == nil then T = {{items = {{}}, periodic = false}} "
                            f"_G.{registry} = T end\n")


def bound_cpu(cpu: str | None) -> str:
    """The `dbg` and `cpu` locals, the cpu BOUND WHEN THE CHUNK IS COMPOSED: the install waits in
    the pipe until the console next reads a line, and a cpu taken from `visible_cpu` then would be
    whichever a `focus` in between made visible. With no cpu named, the visible one when it
    runs."""
    expr = (f"manager.machine.devices[{transport.lua_string(cpu)}]" if cpu else
            'dbg and dbg.visible_cpu or manager.machine.devices[":maincpu"]')
    return f"local dbg = manager.machine.debugger\nlocal cpu = {expr}"


# An install over an id already held takes its tap away first, so a rerun never taps twice.
REMOVE_OLD_TAP = ("local old = T.items[id]\n"
               "if old ~= nil and old.tap ~= nil then old.tap:remove() end")


def register_dumper_once(body: str) -> str:
    """The registry's one periodic dumper, registered by the first install alone: `body` is the
    dumper's own lines, indented under the guard, each ending its line."""
    assert body.endswith("\n"), "a body whose last line runs into the guard's `end`"
    return f"if not T.periodic then\n  T.periodic = true\n{body}end"

# How long a survey waits for the dumper to write the stop it is standing on: the periodic
# hook runs on the way into the debugger's wait loop, and the stub's stop packet can reach
# this side first.
DUMP_WAIT_S = 0.5


DUMP_POLL_S = 0.02


# The prefix of the line every tap's install prints when it ran, and of a removal's answer: one
# reader (`_INSTALLED`) for the four kinds of tap.
ANSWER_PREFIX = "MCP_TALLY"


_INSTALLED = re.compile(rf"^{ANSWER_PREFIX} installed tally_id=(\S+) .*cpu=(\S+)")


# A chunk's sentinel line with its outcome word and error: `<sentinel>#n\t<true|false>\t<err>`.
_ANSWER_LINE = re.compile(re.escape(st.LUA_SENTINEL).encode() + rb"#(\d+)\t(true|false)\t(.*)")


def remove_script(tally_id: str, registry: str) -> str:
    """The Lua that removes the tap `tally_id` from `registry`, whichever kind of tap it holds:
    the tap goes, the registry forgets it, and the dumper stops writing it. Removing what is not
    there prints so, and refuses nothing."""
    return f"""local T = _G.{registry}
local id = {transport.lua_string(tally_id)}
local it = T and T.items[id]
if it ~= nil then
  if it.tap ~= nil then it.tap:remove() end
  T.items[id] = nil
  print("{ANSWER_PREFIX} removed tally_id=" .. id)
else print("{ANSWER_PREFIX} absent tally_id=" .. id) end"""


def held(name: str) -> tuple[dec.Owner, dict[str, Any]] | None:
    """The record held under the ref `name`, whatever cpu it was armed on: a log or a film is
    found by its name, and one armed on another cpu must still be reached to be cleared."""
    return next(((o, rec) for o, rec in STATE.tallies.items() if o[0] == name), None)


def send_tap(scratch: Path, owner: dec.Owner, tally_id: str, script: str, registry: str,
             files: list[Path], **fields: Any) -> dict[str, Any]:
    """Put a tap's install `script` in the pipe and record it under `owner`: the line and its
    call number (what the survey reads the answer by), the byte of stdout the send started at,
    the `registry` its removal goes to and the `files` its answers live in, plus the kind's own
    `fields`. The same record serves every kind of tap, whose taps differ only in what they
    keep. The reply half says the line is PENDING until the console reads it, and how many lines
    were ahead of it. A send that is refused (a pipe too deep, a pipe the emulator
    closed) raises before anything is recorded."""
    cpu = owner[1]
    ahead = transport.refuse_if_too_deep(scratch)
    mark = transport.stdout_mark(scratch)
    errorlog_mark = mfiles.log_mark(scratch)
    line, seq = transport.send(script, ours=True)
    # THE INSTALL CARRIES THE OLD TAP'S COUNTS, so a record that replaces one on the same range
    # carries what the survey last reported: from zero, the first stop after a re-declaration
    # reports the whole census again as writes since the last one. With no record left (the
    # range was cleared), the tap is still there only if its removal LATCHED as lost or
    # refused, and that row kept the report; a removal that ran took the counts with it.
    old = STATE.tallies.get(owner)
    # THE PREDECESSOR IS LIVE when this replaces its record under the same id with no removal in
    # between: installed, or itself pending over a live one. The file at the range's path is then
    # that tap's own, which this install carries on, and is read while this one is pending.
    predecessor_live = (old is not None and old["tally_id"] == tally_id
                        and (old["installed"] is True or bool(old.get("predecessor_live"))))
    if old is None or old["tally_id"] != tally_id:
        old = _tap_that_never_went(scratch, tally_id)
    last_total, last_seq = (0, 0) if old is None else (old["last_total"], old["last_seq"])
    STATE.tallies[owner] = {"tally_id": tally_id, "script": script, "registry": registry,
                          "files": files, "line": line, "seq": seq, "mark": mark,
                          "installed": None, "bound": cpu, "cpu": None, "error": None,
                          "resent": 0, "lost": False,
                          "predecessor_live": predecessor_live,
                          "errorlog_mark": errorlog_mark,
                          "last_total": last_total, "last_seq": last_seq, **fields}
    return {"tally_id": tally_id, "installed": False, "pending": True, "lines_ahead": ahead,
            "call": st.sentinel_line(seq),
            "note": (f"the tap is installed when the console next reads a line "
                     f"({transport.CONSOLE_READS}) and counts from there; the survey of the stop "
                     "after that reads it back")}


def _tap_that_never_went(scratch: Path, tally_id: str) -> dict[str, Any] | None:
    """The newest removal of `tally_id` that LATCHED as lost or refused, or None. A removal
    nobody has looked at since is looked at first: its end may already be in the log, and
    one still pending says nothing, because it may yet run and take the counts with it."""
    for rem in reversed(STATE.tally_removals):
        if rem["tally_id"] != tally_id:
            continue
        if not rem["state"]:
            _read_removal_answer(scratch, rem)
        return rem if rem["state"] in ("lost", "refused") else None
    return None


def send_remove(scratch: Path, owner: dec.Owner) -> dict[str, Any] | None:
    """Put the removal of `owner`'s tap (a count watch's or a capture's) in its registry's pipe
    and forget the record; None when no tap is recorded under `owner`. The files its answers live
    in go with it, so a later tap on the same range cannot read this one's numbers as its
    own -- PROVIDED the removal is evaluated, which is why what became of it is recorded rather
    than assumed: the periodic hook re-creates those files at the next stop for any tap still in
    the registry."""
    rec = STATE.tallies.pop(owner, None)
    if rec is None:
        return None
    ahead = transport.refuse_if_too_deep(scratch)
    mark = transport.stdout_mark(scratch)
    line, seq = transport.send(remove_script(rec["tally_id"], rec["registry"]), ours=True)
    # THE ROW KEEPS THE LAST REPORT: if the removal never runs the tap goes on counting from
    # there, and a tally declared again on the range needs it (`mame_tally.send_install`).
    STATE.tally_removals.append({"tally_id": rec["tally_id"], "line": line, "seq": seq,
                                 "mark": mark, "state": "", "error": "",
                                 "last_total": rec["last_total"],
                                 "last_seq": rec["last_seq"]})
    for path in rec["files"]:
        for p in (path, path.with_name(path.name + ".tmp")):
            p.unlink(missing_ok=True)
    return {"tally_id": rec["tally_id"], "removal": "pending", "lines_ahead": ahead,
            "call": st.sentinel_line(seq)}


def read_removal_answers(scratch: Path) -> list[dict[str, Any]]:
    """What the console did with each removal that was sent: nothing while it is still in
    the pipe, and a row once it reached an end the caller can act on.

    IT ONLY LOOKS, and that is the difference from `_read_install_answer` below rather than
    an omission. The install can resend a line its reader died holding, because the record
    it would resend is still there. A removal's is not: it is dropped the moment the
    removal is SENT, so that a later tally on the same range cannot read this one's
    numbers. And `tally_id` is the RANGE, so a blind resend would carry away whatever tap
    holds that range NOW, which after a re-declaration is a LIVE one. Looking can be wrong
    about nothing; the remedy is the caller's, and the install performs it itself.

    TWO ENDS, and the sentinel's own word separates them the way the install's does:
    `false` is a removal the console EVALUATED and that RAISED, `lost` is one the console is
    done with and never evaluated at all (`transport.passed_over`, the install's rule: a death, the
    console's error or the next reader's prompt behind its echo), and both leave the tap in the
    guest. Neither is a state to
    mention once: the row LATCHES and every later call says it again, because the
    declaration it would otherwise hang from is already gone.
    """
    out: list[dict[str, Any]] = []
    for rem in list(STATE.tally_removals):
        # A LATCHED ROW READS NOTHING. The console's log only grows, so a row that reached
        # an end cannot leave it, and re-reading a tail that grows for the rest of the
        # session would put an unbounded cost on a tool that only lists.
        if not rem["state"]:
            _read_removal_answer(scratch, rem)
        if rem["state"] == "removed":
            # THE TAP WENT, which is what was asked for and therefore not news. The record
            # goes with it, so the common case leaves nothing behind to walk over.
            STATE.tally_removals.remove(rem)
        elif rem["state"]:
            # ONE REASON KEY: the branch's sentence, and the console's own words when it raised
            why = _REMOVAL_WHY[rem["state"]]
            out.append({"tally_id": rem["tally_id"], "state": rem["state"],
                        "why": f"{why}. The console said: {rem['error']}" if rem["error"] else why})
    return out


def _read_removal_answer(scratch: Path, rem: dict[str, Any]) -> None:
    """Fix `rem`'s end if the console reached one, else leave it pending."""
    raw = transport.since(scratch, int(rem["mark"]))
    for m in _ANSWER_LINE.finditer(raw):
        if int(m.group(1)) != rem["seq"]:
            continue
        if m.group(2) != b"true":
            rem["state"] = "refused"
            rem["error"] = m.group(3).decode("utf-8", "replace").strip()
        else:
            rem["state"] = "removed"
        return
    if transport.passed_over(raw, rem["line"]):
        transport.record_lost(int(rem["seq"]))
        rem["state"] = "lost"


# WHAT EACH END MEANS TO A CALLER, and no more than this branch knows: the removal was not
# carried out, and whether a tap is installed is what the install's own answer said (the
# tally's `installed`), never this row's claim. The remedy is the same for both because the
# cause is: declaring the range again installs over whatever is there, and the install removes
# it first. It carries the old tap's counts across, which is the part worth warning about.
_REMOVAL_WHY = {
    "refused": ("the console evaluated the removal and it RAISED, so the removal was not "
                "carried out and this server no longer holds the tally's record; whether a "
                "tap is installed is what the install's own answer said. Declaring the range "
                "again (`watch_add(mode=\"count\")`, `space=\"io\"` for a port's) installs over "
                "it and CARRIES ITS "
                "COUNTS: read the first total as this tally's, not as a fresh one"),
    "lost": ("the console took the removal line and never evaluated it (its echo is in "
             "`log`, channel `process`, with a reader death, the console's error or the next "
             "reader's prompt after it and no sentinel), so the removal was not "
             "carried out and this server no longer holds the tally's record; whether a tap "
             "is installed is what the install's own answer said. Declaring the range again "
             "(`watch_add(mode=\"count\")`, `space=\"io\"` for a port's) installs over it "
             "and CARRIES ITS COUNTS: read "
             "the first total as this tally's, not as a fresh one"),
}


def answered(scratch: Path, rec: dict[str, Any]) -> bool:
    """Whether the tap recorded in `rec` is installed, its install's answer read first: until it
    is, the files at its paths are the range's and may be a removed tap's
    (`mame_tally.install_script`)."""
    _read_install_answer(scratch, rec)
    return rec["installed"] is True


def _read_install_answer(scratch: Path, rec: dict[str, Any]) -> None:
    """Record in `rec` what the console answered to the install, once: `installed` true
    with the cpu the tap sits on, or false with the console's error words. The sentinel is
    matched by this call's own number from the byte the send started at, so a rerun of an
    EARLIER chunk printing its own sentinel again is passed over; the console mark is not
    moved, because the raw form's accounting counts sentinels, not marks.

    A LINE THE CONSOLE IS DONE WITH AND NEVER RAN IS SENT AGAIN, ONCE: its echo is there, a
    reader death, the console's own error or the next reader's prompt follows it, and its
    sentinel never came (`transport.passed_over`), so the chunk was never evaluated and resending
    runs it once. A tally that never installs is a zero that reads as a measurement, so a
    second loss is `lost`, said in the survey.

    NOTHING ELSE AGES IT, frames least of all: the hook runs a line only once the reader that
    echoed it is idle, and a reader can stay busy across frames, so a frame count says nothing
    about a line the console echoed. One echoed and not yet run, or not echoed yet, waits."""
    if rec["installed"] is not None or rec["lost"]:
        return
    raw = transport.since(scratch, int(rec["mark"]))
    for m in _ANSWER_LINE.finditer(raw):
        if int(m.group(1)) != rec["seq"]:
            continue
        if m.group(2) == b"true":
            # THIS TAP'S LINE, by its id: another install sent before this one (a `start`'s
            # re-arm sends every tap at once) can be answered after this record's mark, so its
            # `installed` line can sit between the mark and this sentinel.
            text = raw[:m.start()].decode("utf-8", "replace")
            hit = next((h for ln in text.splitlines() if (h := _INSTALLED.match(ln))
                        and h.group(1) == rec["tally_id"]), None)
            rec["installed"] = True
            rec["cpu"] = hit.group(2) if hit else None
        else:
            rec["installed"] = False
            rec["error"] = m.group(3).decode("utf-8", "replace").strip()
        return
    if not transport.passed_over(raw, rec["line"]):
        return
    transport.record_lost(int(rec["seq"]))
    if rec["resent"]:
        rec["lost"] = True
        return
    rec["mark"] = transport.stdout_mark(scratch)
    rec["line"], rec["seq"] = transport.send(rec["script"], ours=True)
    rec["resent"] += 1


def _read_dump(path: Path, frame: int | None,
               parse: Callable[[str], dict[str, Any] | None]) -> dict[str, Any] | None:
    """The dump at `path` as `parse` reads it, waited for up to the bound when the machine has
    a frame the dump has not reached yet; None when there is none to read. A dump with no frame
    (a machine with no screen) is current as soon as it exists: there is nothing to wait for."""
    deadline = time.monotonic() + DUMP_WAIT_S
    dump: dict[str, Any] | None = None
    while True:
        try:
            dump = parse(path.read_text(encoding="utf-8", errors="replace"))
        except FileNotFoundError:
            dump = None
        if dump is not None and (frame is None or dump["frame"] == callbacks.NO_FRAME
                                 or dump["frame"] >= frame):
            return dump
        if time.monotonic() >= deadline:
            return dump
        time.sleep(DUMP_POLL_S)


def mark_across(event: str) -> list[dict[str, str | None]]:
    """Record on every live tap that the machine was REPLACED under it (`event`: a soft reset,
    a `stateload`), and answer the taps it was recorded on. The Lua counters are the host's and
    survive it, so a total that spans one counts two runs of the same code; the tap keeps
    counting and says so in `across`, rather than being reset behind the caller's back."""
    before = st.last_stop_frame()
    for rec in STATE.tallies.values():
        rec.setdefault("across", []).append({"event": event, "frame_from": st.or_unavailable(
            before, "no stop had read a frame before it")})
    return [{**mspace.shown(ref), "cpu": cpu} for ref, cpu in STATE.tallies]


def read_tap(scratch: Path, owner: dec.Owner, frame: int | None, at_stop: bool,
             parse: Callable[[str], dict[str, Any] | None], state: str
             ) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """What a stop survey (`at_stop`) or `watch_list` says about the tap under `owner` before
    its kind's own tables, and the dump they are read from (None when there is nothing further
    to say): `installed` and `pending` (installed; not yet answered, `installed` false with
    `pending` true; refused, false with the console's words in its `why`), and once there
    is a dump, its `state` word, `frame_as_of`, `superseded` and `total`, a count watch's writes or
    a capture's trigger writes, and `callback_errors` beside them (`mame_callbacks`; absent only
    from a dump composed before the guard). Only a STOP moves the `since_last_stop` baseline and
    reports it: a list between two stops is a look, and a look that consumed the delta would hand
    the next stop a zero for writes that happened. A dump whose total fell below the baseline is a
    `reset` (the tap was installed afresh over a cleared registry), said rather than reported
    negative."""
    rec = STATE.tallies[owner]
    _read_install_answer(scratch, rec)
    item: dict[str, Any] = {"tally_id": rec["tally_id"], "addr": st.hex_addr(rec["addr"])}
    if rec.get("across"):
        item["across"] = rec["across"]
    if rec["installed"] is False:
        item.update(state="install_failed", installed=False, pending=False, why=rec["error"])
        return item, None
    if rec["lost"]:
        item.update(state="install_lost", installed=False, pending=False,
                    install_resent=rec["resent"],
                    why=("the console never evaluated the install line, twice: each time "
                         "its echo is in `log` (channel `process`) with no sentinel after it, "
                         "and a dead reader, the console's own `error:` line or the next "
                         "reader's prompt behind it. The tap was never "
                         "installed, so it recorded NOTHING; `watch_clear` it and declare it "
                         "again"))
        return item, None
    # A PENDING INSTALL READS NO DUMP: `tally_id` is the range, so until the install answered,
    # whatever sits at its path is another tap's (`mame_tally.install_script` says when it
    # goes); unless the tap it replaces is still live (`send_tap`), whose dump it is and whose
    # counts it carries.
    reads_no_dump = rec["installed"] is None and not rec.get("predecessor_live")
    dump = None if reads_no_dump else _read_dump(rec["path"], frame, parse)
    if rec["installed"] is None:
        item.update(installed=False, pending=True, install_resent=rec["resent"],
                    call=st.sentinel_line(rec["seq"]))
    else:
        item.update(installed=True, pending=False, cpu=rec["cpu"], install_resent=rec["resent"])
    if dump is None:
        item.update(state="no_dump_yet",
                    why=("no dump of this tap is on disk and its install has no answer: "
                         "the console evaluates the install when it next reads a line, and "
                         "the periodic hook writes at a stop after that"
                         if rec["installed"] is None else
                         "no dump of this tap is on disk: the periodic hook writes one "
                         "at a stop"))
        return item, None
    no_frame = dump["frame"] == callbacks.NO_FRAME
    item.update(state=state,
                frame_as_of=(st.unavailable("the dump was written with no frame counter to "
                                            "read") if no_frame else dump["frame"]),
                superseded=(not no_frame and frame is not None and dump["frame"] < frame),
                total=dump["total"])
    if (errors := callbacks.reply(dump)) is not None:
        item["callback_errors"] = errors
    if at_stop:
        moved = dump["seq"] != rec["last_seq"]
        reset = moved and dump["total"] < int(rec["last_total"])
        if reset:
            item["since_last_stop"], item["reset"] = dump["total"], True
        else:
            item["since_last_stop"] = dump["total"] - int(rec["last_total"]) if moved else 0
        if moved:
            rec["last_total"], rec["last_seq"] = dump["total"], dump["seq"]
    if item["superseded"]:
        failed = _dump_failed(scratch, rec, int(dump["seq"]))
        item["why"] = (f"the newest dump is of frame {dump['frame']} and the machine stands "
                       f"at frame {frame}: "
                       + (f"the dumper raised writing a newer one ({failed}), and the dump on disk "
                          "is the last it finished" if failed is not None else
                          f"the dumper had not written this stop within {DUMP_WAIT_S}s"))
    return item, dump


def _dump_failed(scratch: Path, rec: dict[str, Any], seq: int) -> str | None:
    """The error the guard logged for `rec`'s dumper (`callbacks.DUMP_FAILED`) that the dump on
    disk, of sequence `seq`, is older than, or None. The log is read on from where the last look
    stopped, so a stall re-reads nothing; a failure is kept beside the sequence of the dump that
    stood when it was seen, and a newer dump since means the dumper wrote again, so that failure
    is not why this one is old."""
    lines, rec["errorlog_mark"] = mfiles.errorlog_since(scratch, int(rec.get("errorlog_mark", 0)))
    said = f"{callbacks.DUMP_FAILED} {rec['tally_id']} "
    found = [ln.split(said, 1)[1].strip() for ln in lines if said in ln]
    if found:
        rec["dump_failed"] = (found[-1], seq)
    failed = rec.get("dump_failed")
    if failed is not None and seq > failed[1]:
        rec.pop("dump_failed")
        return None
    return None if failed is None else str(failed[0])
