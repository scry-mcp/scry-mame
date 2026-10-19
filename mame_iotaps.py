"""Taps in a cpu's io space: a count watch on a port, and a capture a port's write triggers.

WHY ANOTHER SPACE. A board that drives its palette or its sound through ports writes them with
`out`, and nothing of that lands in the program space, so a tap there is blind to it. MAME's own
Lua reaches the io space as it reaches the program (`cpu.spaces["io"]`, `install_write_tap`), and
its console answers a port's handlers with `mapi` where an address has `map`. A capture's block
stays in the program space, where a block lives: only its trigger moves.

WHERE IT LIVES. An io tap is never in the declaration store (`NOT_STORED` says why): it is a
record among the session's taps (`STATE.tallies`) under a ref that carries its space, and the
server routes `watch_add`, `watch_list` and `watch_clear` here for it, since this module builds
on `mame_watches` and so cannot be imported by it.
"""

from __future__ import annotations

from typing import Any

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
    """A port is tapped on a cpu that has an io space. A machine whose map `start` could not
    read, or a cpu nobody could name, is not judged here: the install then says what the
    console found."""
    cpu = on or STATE.first_cpu
    if not STATE.machine_map.get("cpus") or cpu is None:
        return
    have = cpus_with_io()
    if cpu not in have:
        raise st.Invalid("bad_argument", f"{cpu} has no io space, so it has no port to tap; "
                         f"the cpus with one: {have or 'none'}", cpus_with_io=have)


def io_ref(text: str, by: str) -> str:
    """The one spelling a ref is held under in the io space: `0x6@io` for an address or a port,
    the symbol upper-case (the table's own case) for a capture's block."""
    ref = text.strip()
    held = f"0x{int(ref, 16):x}" if by == "address" else ref.upper()
    return f"{held}{mspace.suffix(mspace.IO)}"


def _sized(ref: str, mode: str, width: int, fmt: str, by: str, on: str | None) -> tuple[int, str]:
    """A tap's width and format: `length`, a sized `fmt`, or a typed symbol's type for a
    capture's block (a port has no type in any table)."""
    typed = STATE.table(on).types.get(ref.strip().upper()) if by == "symbol" else None
    return watches.size_watch(mode, width, fmt, typed, st.Invalid(
        "bad_argument", f"a {mode} watch on a port needs a length in bytes or a sized fmt"
        + ("" if mode == "count" else ", or a block the symbol table types")))


def _held_elsewhere(owner: dec.Owner, tally_id: str, mode: str, addr: int, width: int
                    ) -> arming.Refusal | None:
    """ONE REF, ONE TAP, as in the program space: the ref already holding another tap (another
    length, trigger or kind) keeps it until it is cleared, since a second install under it would
    leave the first counting where nothing reaches it; and one tap is under one ref, since two
    records of one id are cleared from under each other. Asked BEFORE the port's `mapi`, where the
    program space asks its `map` first (`watches.send_tap`): when both refuse, each space keeps
    the refusal it has always given."""
    held = STATE.tallies.get(owner)
    if held is not None and held["tally_id"] != tally_id:
        port = mspace.shown(owner[0])["ref"]
        return ("ambiguous_ref", f"{port} in the io space already holds the tap "
                f"{held['tally_id']}: clear it (`watch_clear(ref=\"{port}\", space=\"io\")`) "
                "before declaring another under it")
    other = next((mspace.shown(o[0])["ref"] for o, rec in STATE.tallies.items()
                  if o != owner and rec["tally_id"] == tally_id), None)
    if other is None and mode == "count":
        other = watches.range_holder({o: r for o, r in taps() if r["registry"] == tally.REGISTRY},
                                     "width", owner, addr, width)
        other = None if other is None else mspace.shown(other)["ref"]
    if other is not None:
        return ("ambiguous_ref", f"that tap is already declared under {other!r}: "
                f"{mclear.one_declaration('tap', other, 'watch_clear', owner[1], mspace.IO)}")
    return None


def watch_add(ses: gs.Session, ref: str, mode: str, width: int, fmt: str, by: str, cpu: str,
              trigger: str) -> dict[str, Any]:
    """The body of `watch_add(space="io")`: a count watch on the port `ref`, or a capture of the
    program block `ref` on the port `trigger`. Nothing is stored."""
    watches.check_watch_add(ref, mode, width, fmt, by, "", trigger, mspace.IO)
    on = cpus.chosen(ses, cpu)
    check_has_io(on)
    scratch = STATE.scratch
    assert scratch is not None
    reply: dict[str, Any] = {"mode": mode, "cpu": st.or_unavailable(on, st.NO_CPU_READ_WHY),
                             "space": mspace.IO}
    if mode == "count":
        chosen, addr = "address", mspace.port(ref, "ref")
        width, fmt = _sized(ref, mode, width, fmt, chosen, on)
        owner: dec.Owner = (io_ref(ref, chosen), on)
        # JUDGED BY THE IO BUS'S OWN WIDTH, as a program count is by the program's: a word `out`
        # at an odd port reaches the tap as two bus-word fragments, as a program write does.
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
                     read_maps_to=st.or_unavailable(read_maps_to, mmap.NO_READ_SIDE_WHY))
    else:
        chosen = arming.decide_by(ref, by, on, "watch")
        tally.check_count_watch(chosen, mode)
        port = mspace.port(trigger, "trigger")
        # THE BLOCK IS READ AS `by` SAYS, never re-read: a `by="address"` not written `0x` is the
        # declaration's refusal, and a name this build lacks is refused, not guessed.
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
    # STAMPED BY THE DECLARATIONS' ONE CLOCK (`st.now`), so its row ages as theirs do; declared
    # again, the record is new, and the stamp with it, as a re-declaration re-stamps a row.
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
    """Each io tap as `watch_list` (`at_stop` False) or a stop's survey (True) shows a watch, cut
    where theirs are: a count's tables at the bucket ceiling in a list, a capture's first rows,
    and at a stop no rows at all."""
    out: list[dict[str, Any]] = []
    scratch = STATE.scratch
    if scratch is None:
        return out
    for owner, rec in taps(cpu):
        evaluate = capture.evaluate if rec["mode"] == "capture" else tally.evaluate
        shown = st.ROWS_SHOWN if at_stop or rec["mode"] == "capture" else tally.BUCKETS_MAX
        out.append({**mspace.shown(owner[0]), "by": "address",
                    "cpu": st.or_unavailable(owner[1], st.NO_CPU_READ_WHY),
                    "stored": False, "mode": rec["mode"], "length": rec["width"],
                    "fmt": rec["fmt"],
                    "created_at": st.or_unavailable(rec.get("created_at"), arming.UNDATED_WHY),
                    "age_s": st.or_unavailable(st.age_s(rec.get("created_at")),
                                               arming.UNDATED_WHY),
                    **evaluate(scratch, owner, rec["width"], rec["fmt"], frame, shown,
                               at_stop)})
    return out


def held_key(ref: str) -> str:
    """The key an io tap a call names is held under: a port in its one address spelling
    (`0x06` is `0x6`), a capture's block by its symbol, so a clear matches any spelling."""
    held = ref.strip()
    return io_ref(held, "address" if inputs.is_address(held) else "symbol")


def clear(ref: str, cpu: str | None = None) -> list[dict[str, Any]]:
    """Send the removal of the io taps under `ref` (every one when empty), on `cpu` or every
    cpu, and answer what went, as `watch_clear` reports a tap's removal."""
    gone: list[dict[str, Any]] = []
    if STATE.scratch is None:
        return gone
    wanted = held_key(ref) if ref.strip() else ""
    for owner, _rec in taps(cpu):
        if (not wanted or owner[0] == wanted) and (
                removed := mtap.send_remove(STATE.scratch, owner)):
            gone.append(removed)
    return gone


def watch_clear(ses: gs.Session, ref: str, cpu: str | None) -> dict[str, Any]:
    """The body of `watch_clear` for an io ref: its tap's removal, in `watch_clear`'s own reply
    shape, with nothing in the store to drop."""
    running = arming.running_on_arrival(ses)
    gone = clear(ref, cpu)
    if not gone:
        held = mclear.nothing_matched(ref.strip(), "io tap", " in the io space",
                                      [repr(mspace.shown(o[0])["ref"]) for o, _ in taps()],
                                      "cleared")
        return menvelope.invalid("unknown_ref",
                                 f"{held} `watch_list` shows each one's `ref` and `space`. "
                                 f"Matching: {dec.REF_MATCH['watch']}.")
    return menvelope.envelope({"declarations_cleared": 0, "disarmed": [],
                               "while_running": running, "tallies_removed": gone})
