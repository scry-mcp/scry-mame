"""Taps in a cpu's io space: a count watch on a port, and a capture a port's write triggers.

A board that drives its palette or sound through `out` lands nothing in the program space, so a
program-space tap is blind to it. A capture's block stays in the program space: only its trigger
moves. An io tap is never in the declaration store (`NOT_STORED`): it is a record among
`STATE.tallies` under a ref that carries its space, and the server routes the watch tools here
(this module builds on `mame_watches`, so that one cannot import it).
"""

from __future__ import annotations

from typing import Any

from scry_core import declaration_rows
from scry_core.reply_contract import or_unavailable

import gdb_session as gs
import mame_arming as arming
import mame_capture as capture
import mame_clear as mclear
import mame_cpus as cpus
import mame_declarations as dec
import mame_envelope as menvelope
import mame_inputs as inputs
import mame_map as mmap
import mame_space as mspace
import mame_state as st
import mame_tally as tally
import mame_tap as mtap
import mame_watches as watches
from mame_state import STATE

NOT_STORED = ("an io tap lives for this session only: the declaration store has no space, and a "
              "server reading it would re-arm the port as the program address of the same "
              "number. Declare it again after the next `start`")


def cpus_with_io() -> list[str]:
    """The machine's cpus that have an io space, as `start` read them (`machine_map`)."""
    return [c["tag"] for c in STATE.machine_map.get("cpus", [])
            if mspace.IO in c.get("spaces", [])]


def check_has_io(on: str | None) -> None:
    """Refuse a cpu with no io space; an unreadable map or unnamed cpu is left to the install."""
    cpu = on or STATE.first_cpu
    if not STATE.machine_map.get("cpus") or cpu is None:
        return
    have = cpus_with_io()
    if cpu not in have:
        raise st.Invalid("bad_argument", f"{cpu} has no io space, so it has no port to tap; "
                         f"the cpus with one: {have or 'none'}", cpus_with_io=have)


def io_ref(text: str, by: str) -> str:
    """The one spelling a ref is held under: `0x6@io` for a port, a block's symbol upper-case."""
    ref = text.strip()
    held = f"0x{int(ref, 16):x}" if by == "address" else ref.upper()
    return f"{held}{mspace.suffix(mspace.IO)}"


def _sized(ref: str, mode: str, width: int, fmt: str, by: str, on: str | None) -> tuple[int, str]:
    """A tap's width and format; a port has no type in any table, only a capture's block does."""
    typed = STATE.table(on).types.get(ref.strip().upper()) if by == "symbol" else None
    return watches.size_watch(mode, width, fmt, typed, st.Invalid(
        "bad_argument", f"a {mode} watch on a port needs a length in bytes or a sized fmt"
        + ("" if mode == "count" else ", or a block the symbol table types")))


def _held_elsewhere(owner: dec.Owner, tally_id: str, mode: str, addr: int, width: int
                    ) -> arming.Refusal | None:
    """One ref, one tap, and one tap under one ref, as in the program space. Asked before the
    port's `mapi`, as the program space asks its `map` first, so each space keeps its refusal."""
    held = STATE.tallies.get(owner)
    if held is not None and held["tally_id"] != tally_id:
        port = mspace.shown(owner[0])["ref"]
        return ("ambiguous_ref", f"{port} in the io space already holds the tap "
                f"{held['tally_id']}: clear it (`declaration_clear(kind=\"watch\", ref=\"{port}\", "
                "space=\"io\")`) "
                "before declaring another under it")
    other = next((mspace.shown(o[0])["ref"] for o, rec in STATE.tallies.items()
                  if o != owner and rec["tally_id"] == tally_id), None)
    if other is None and mode == "count":
        other = watches.range_holder({o: r for o, r in taps() if r["registry"] == tally.REGISTRY},
                                     "width", owner, addr, width)
        other = None if other is None else mspace.shown(other)["ref"]
    if other is not None:
        return ("ambiguous_ref", f"that tap is already declared under {other!r}: "
                f"{mclear.one_declaration('tap', other, 'watch', owner[1], mspace.IO)}")
    return None


def watch_add(ses: gs.Session, ref: str, mode: str, width: int, fmt: str, by: str, cpu: str,
              trigger: str) -> dict[str, Any]:
    """The body of `watch_add(space="io")`; nothing is stored."""
    watches.check_watch_add(ref, mode, width, fmt, by, "", trigger, mspace.IO)
    on = cpus.chosen(ses, cpu)
    check_has_io(on)
    scratch = STATE.scratch
    assert scratch is not None
    reply: dict[str, Any] = {"mode": mode, "cpu": or_unavailable(on, st.NO_CPU_READ_WHY),
                             "space": mspace.IO}
    if mode == "count":
        chosen, addr = "address", mspace.port(ref, "ref")
        width, fmt = _sized(ref, mode, width, fmt, chosen, on)
        owner: dec.Owner = (io_ref(ref, chosen), on)
        # a word `out` at an odd port reaches the tap as two bus-word fragments
        split, unchecked = watches.bus_word_split(addr, width, on, mspace.IO)
        if split is not None:
            return menvelope.invalid("bad_argument", split, **mspace.shown(owner[0]))
        refused = _held_elsewhere(owner, tally.id_for(on, addr, width, mspace.IO), mode, addr,
                                  width)
        if refused is None:
            refused, maps_to, read_maps_to = mmap.write_side(ses, addr, on, mspace.IO)
        if refused is not None:
            code, why = refused
            return menvelope.invalid(code, why, **mspace.shown(owner[0]))
        sent = watches.send_count(scratch, owner, addr, width, mspace.IO, unchecked, maps_to,
                                  read_maps_to)
        reply.update(write_maps_to=maps_to,
                     read_maps_to=or_unavailable(read_maps_to, mmap.NO_READ_SIDE_WHY))
    else:
        chosen = arming.decide_by(ref, by, on, "watch")
        tally.check_count_watch(chosen, mode)
        port = mspace.port(trigger, "trigger")
        # the block is read as `by` says, never re-read, so a bad spelling is refused, not guessed
        res = arming.resolve_decl(arming.declare("watch", chosen, ref.strip(), on, width=1,
                                                 fmt="u8", watch_mode="show"))
        if res.addr is None:
            raise st.Invalid("unknown_ref", inputs.not_a_ref("the block", ref.strip(), on))
        addr = res.addr
        width, fmt = _sized(ref, mode, width, fmt, chosen, on)
        owner = (io_ref(ref, chosen), on)
        refused = _held_elsewhere(owner, capture.id_for(on, addr, width, port, mspace.IO), mode,
                                  addr, width)
        if refused is None:
            refused, maps_to, _read = mmap.write_side(ses, port, on, mspace.IO)
            if refused is not None:
                refused = (refused[0], f"the trigger: {refused[1]}")
        if refused is not None:
            code, why = refused
            return menvelope.invalid(code, why, **mspace.shown(owner[0]))
        try:
            src = capture.source(addr, width, on, mmap.read_side(ses, on))
        except st.Invalid as e:
            return menvelope.invalid(e.code, str(e), **mspace.shown(owner[0]))
        sent = watches.send_capture(scratch, owner, addr, width, port, src, mspace.IO, maps_to,
                                    None)
        reply.update(trigger=f"{port:#x}", trigger_addr=st.hex_addr(port),
                     trigger_maps_to=maps_to, source=src.fields())
    # the declarations' one clock, so the row ages as theirs do
    STATE.tallies[owner].update(mode=mode, fmt=fmt, created_at=st.now())
    return menvelope.envelope(st.add_note(st.merged(
        {**mspace.shown(owner[0]), "by": chosen, **reply, "length": width, "fmt": fmt,
         "addr": st.hex_addr(addr), "stored": False, "armed": False, "state": "pending"}, sent),
        NOT_STORED))


def taps(cpu: str | None = None) -> list[tuple[dec.Owner, dict[str, Any]]]:
    """This session's io taps, on `cpu` or on every cpu, in the order recorded."""
    return [(o, r) for o, r in STATE.tallies.items()
            if r.get("space") == mspace.IO and (cpu is None or o[1] == cpu)]


def taps_by_cpu() -> dict[str, int]:
    """How many io taps sit on each cpu: watches the declaration store never holds."""
    out: dict[str, int] = {}
    for (_ref, cpu), _rec in taps():
        if cpu is not None:
            out[cpu] = out.get(cpu, 0) + 1
    return out


def rows(frame: int | None, at_stop: bool, cpu: str | None = None) -> list[dict[str, Any]]:
    """Each io tap as a watch row of `declaration_list` or a stop survey, cut as theirs are."""
    out: list[dict[str, Any]] = []
    scratch = STATE.scratch
    if scratch is None:
        return out
    for owner, rec in taps(cpu):
        evaluate = capture.evaluate if rec["mode"] == "capture" else tally.evaluate
        shown = st.ROWS_SHOWN if at_stop or rec["mode"] == "capture" else tally.BUCKETS_MAX
        out.append({**mspace.shown(owner[0]), "by": "address",
                    "cpu": or_unavailable(owner[1], st.NO_CPU_READ_WHY),
                    "stored": False, "mode": rec["mode"], "length": rec["width"],
                    "fmt": rec["fmt"],
                    "created_at": or_unavailable(rec.get("created_at"),
                                                 declaration_rows.UNDATED_WHY),
                    "age_s": or_unavailable(declaration_rows.age_s(rec.get("created_at"),
                                                                   st.utc_now()),
                                            declaration_rows.UNDATED_WHY),
                    **evaluate(scratch, owner, rec["width"], rec["fmt"], frame, shown,
                               at_stop)})
    return out


def held_key(ref: str) -> str:
    """The key a named io tap is held under, so a clear matches any spelling (`0x06` is `0x6`)."""
    held = ref.strip()
    return io_ref(held, "address" if inputs.is_address(held) else "symbol")


def clear(ref: str, cpu: str | None = None) -> list[dict[str, Any]]:
    """Remove the io taps under `ref` (every one when empty), on `cpu` or every cpu."""
    gone: list[dict[str, Any]] = []
    if STATE.scratch is None:
        return gone
    wanted = held_key(ref) if ref.strip() else ""
    for owner, _rec in taps(cpu):
        if (not wanted or owner[0] == wanted) and (
                removed := mtap.send_remove(STATE.scratch, owner)):
            gone.append(removed)
    return gone


def clear_taps(ses: gs.Session, ref: str, cpu: str | None) -> dict[str, Any]:
    """The body of `declaration_clear(kind="watch")` for an io ref; nothing in the store to drop."""
    running = arming.running_on_arrival(ses)
    gone = clear(ref, cpu)
    if not gone:
        held = mclear.nothing_matched(ref.strip(), "io tap", " in the io space",
                                      [repr(mspace.shown(o[0])["ref"]) for o, _ in taps()],
                                      "cleared")
        return menvelope.invalid("unknown_ref",
                                 f"{held} `declaration_list(kind=\"watch\")` shows each one's "
                                 "`ref` and `space`. "
                                 f"Matching: {dec.REF_MATCH['watch']}.")
    return menvelope.envelope({"declarations_cleared": 0, "disarmed": [],
                               "while_running": running, "tallies_removed": gone})
