"""The lifecycle shared by every Lua write tap: install, removal, answers and dumps.

An install is sent down the console's pipe, never stepped for: stepping would move the pc of the
stop the caller stands on. The script only reads, so `altered` stays.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scry_core.reply_contract import or_unavailable, unavailable

from scry_mame import callbacks, lua_source, transport
from scry_mame import declarations as dec
from scry_mame import files as mfiles
from scry_mame import space as mspace
from scry_mame import state as st
from scry_mame.state import STATE

# Lua locals handed between fragments: `T`, `cpu`, `old`.


def tap_prelude(registry: str) -> str:
    """The callback guard, then the registry in `_G`, made by the first install."""
    return callbacks.LUA + lua_source.render("tap-prelude", registry=lua_source.Code(registry))


def bound_cpu(cpu: str | None) -> str:
    """The `cpu` local; a named cpu is bound at composition, before a `cpu_focus` can move the
    visible one."""
    expr = (f"manager.machine.devices[{transport.lua_string(cpu)}]" if cpu else
            'manager.machine.debugger and manager.machine.debugger.visible_cpu '
            'or manager.machine.devices[":maincpu"]')
    return lua_source.render("tap-bound-cpu", cpu=lua_source.Code(expr)).rstrip("\n")


#: A rerun removes its old tap first.
REMOVE_OLD_TAP = lua_source.render("tap-remove-old").rstrip("\n")


def register_dumper_once(body: str) -> str:
    """The registry's periodic dumper, registered by the first install only; `body` is indented
    under the guard."""
    assert body.endswith("\n"), "a body whose last line runs into the guard's `end`"
    return lua_source.render("tap-dumper-once", body=lua_source.Code(body)).rstrip("\n")

# The stub's stop packet can reach us before the periodic hook has dumped that stop.
DUMP_WAIT_S = 0.5


DUMP_POLL_S = 0.02


ANSWER_PREFIX = "MCP_TALLY"


_INSTALLED = re.compile(rf"^{ANSWER_PREFIX} installed tally_id=(\S+) .*cpu=(\S+)")


# `<sentinel>#n\t<true|false>\t<err>`
_ANSWER_LINE = re.compile(re.escape(st.LUA_SENTINEL).encode() + rb"#(\d+)\t(true|false)\t(.*)")


def remove_script(tally_id: str, registry: str) -> str:
    """The Lua removing tap `tally_id` from `registry`; an absent tap is no error."""
    return lua_source.render("tap-remove", registry=lua_source.Code(registry), id=tally_id,
                             answer=ANSWER_PREFIX).rstrip("\n")


def held(name: str) -> tuple[dec.Owner, dict[str, Any]] | None:
    """The record under ref `name` on any cpu."""
    return next(((o, rec) for o, rec in STATE.tallies.items() if o[0] == name), None)


def send_tap(scratch: Path, owner: dec.Owner, tally_id: str, script: str, registry: str,
             files: list[Path], **fields: Any) -> dict[str, Any]:
    """Send a tap's install `script` and record it under `owner`; a refused send raises first."""
    cpu = owner[1]
    ahead = transport.refuse_if_too_deep(scratch)
    mark = transport.stdout_mark(scratch)
    errorlog_mark = mfiles.log_mark(scratch)
    line, seq = transport.send(script, ours=True)
    # Carry the old counts, or the next stop reports the whole census as new writes. With no
    # record left, the tap survives only if its removal latched as lost or refused.
    old = STATE.tallies.get(owner)
    # Same id replaced with no removal between: the file at the path is the live predecessor's.
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
    """The newest removal of `tally_id` latched as lost or refused, or None."""
    for rem in reversed(STATE.tally_removals):
        if rem["tally_id"] != tally_id:
            continue
        if not rem["state"]:
            _read_removal_answer(scratch, rem)
        return rem if rem["state"] in ("lost", "refused") else None
    return None


def send_remove(scratch: Path, owner: dec.Owner) -> dict[str, Any] | None:
    """Send the removal of `owner`'s tap, forget the record and delete its files; None when none.

    The outcome is recorded: if the removal never runs, the hook re-creates the files.
    """
    rec = STATE.tallies.pop(owner, None)
    if rec is None:
        return None
    ahead = transport.refuse_if_too_deep(scratch)
    mark = transport.stdout_mark(scratch)
    line, seq = transport.send(remove_script(rec["tally_id"], rec["registry"]), ours=True)
    # Keeps the last report: a tap whose removal never runs goes on counting from it.
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
    """What the console did with each sent removal: a row once it reached an end, nothing while
    it is in the pipe.

    It never resends, unlike `_read_install_answer`: `tally_id` is the range, so a resend could
    remove a live tap declared there since. `refused` raised, `lost` was never evaluated
    (`transport.passed_over`); both leave the tap in the guest, and the row latches.
    """
    for rem in list(STATE.tally_removals):
        # A latched row cannot leave its end; re-reading the growing log would cost unboundedly.
        if not rem["state"]:
            _read_removal_answer(scratch, rem)
        if rem["state"] == "removed":
            STATE.tally_removals.remove(rem)
    return st.tallies_not_removed()


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




def answered(scratch: Path, rec: dict[str, Any]) -> bool:
    """Whether `rec`'s tap is installed, reading its answer first."""
    _read_install_answer(scratch, rec)
    return rec["installed"] is True


def _read_install_answer(scratch: Path, rec: dict[str, Any]) -> None:
    """Record once whether the install answered: installed with its cpu, or false with the error.

    A line passed over (`transport.passed_over`) is resent once; a second loss is `lost`, since
    an install that never lands reads as a zero measurement. Frames never age a line: a reader
    can stay busy across frames.
    """
    if rec["installed"] is not None or rec["lost"]:
        return
    raw = transport.since(scratch, int(rec["mark"]))
    for m in _ANSWER_LINE.finditer(raw):
        if int(m.group(1)) != rec["seq"]:
            continue
        if m.group(2) == b"true":
            # Match by id: a re-arm sends every tap at once, so another's line can sit here.
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
    """The dump at `path` parsed, waiting up to `DUMP_WAIT_S` for it to reach `frame`; None if
    absent. A dump with no frame counter is current as soon as it exists."""
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
    """Record on every live tap that the machine was replaced (`event`). The Lua counters survive
    it, so a total spanning one counts two runs; `across` says so."""
    before = st.last_stop_frame()
    for rec in STATE.tallies.values():
        rec.setdefault("across", []).append({"event": event, "frame_from": or_unavailable(
            before, "no stop had read a frame before it")})
    return [{**mspace.shown(ref), "cpu": cpu} for ref, cpu in STATE.tallies]


def read_tap(scratch: Path, owner: dec.Owner, frame: int | None, at_stop: bool,
             parse: Callable[[str], dict[str, Any] | None], state: str
             ) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """What a stop survey (`at_stop`) or a watch listing says of the tap under `owner`, and the
    dump it read (None when nothing further).

    Only a stop moves the `since_last_stop` baseline: a list between stops must not consume the
    delta. A total below the baseline is a `reset`, not a negative.
    """
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
                         "installed, so it recorded NOTHING; "
                         "`declaration_clear(kind=\"watch\")` it and declare it "
                         "again"))
        return item, None
    # `tally_id` is the range, so before the answer the file at its path is another tap's,
    # unless the replaced tap is still live.
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
                frame_as_of=(unavailable("the dump was written with no frame counter to "
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
    """The dumper error (`callbacks.DUMP_FAILED`) that the dump of sequence `seq` is older than,
    or None. A failure is kept with the dump sequence then standing; a newer dump since means it
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
