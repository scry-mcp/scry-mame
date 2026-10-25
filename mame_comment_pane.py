"""MAME's pane: the store's comments fed through `comadd`, read back off one `dasm` line.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gdb_session as gs
import mame_arming as arming
import mame_cpus as cpus
import mame_declarations as dec
import mame_read as read
import mame_state as st
from mame_state import STATE

#: A comment's place: its cpu and resolved address, or the upper-cased name when unresolved.
Place = tuple[str | None, int | str]


def console_fault(text: str) -> str | None:
    """Why MAME's console cannot carry `text` into the pane, or None."""
    if '"' in text:
        return ("the text holds a `\"`, which MAME's console keeps together with the backslash "
                "that escapes it, so the pane would show another text")
    if text.endswith("\\"):
        return ("the text ends with `\\`, which escapes the closing quote of the console's "
                "`comadd`, so the console refuses the line")
    return None


def comments() -> list[dec.Declaration]:
    return [d for d in arming.store().declarations() if d.kind == "comment"]


def place(d: dec.Declaration) -> Place:
    res = arming.resolve_decl(d)
    return d.cpu, (res.addr if res.addr is not None else d.ref.strip().upper())


def state(d: dec.Declaration) -> dict[str, Any]:
    """`d`'s state and why: `unresolved`, `stale`, else the last feed's `armed` or `unarmable`."""
    res = arming.resolve_decl(d)
    if res.state == "unresolved":
        return {"state": "unresolved",
                "why": (f"{d.ref!r} is not a symbol of {d.cpu}'s table in this build: kept, and "
                        "fed to the pane once a start's table defines it")}
    if arming.stale(d):
        return {"state": "stale", "why": arming.stale_why()}
    fed = STATE.comment_feed.get(d.owner) or {
        "state": "unarmable", "why": "not fed to MAME's pane in this session"}
    return {k: v for k, v in fed.items() if k != "landed"}


def is_shown(d: dec.Declaration) -> bool:
    """Whether the pane shows `d`, as its last feed read it back."""
    return bool(state(d)["state"] == "armed")


def record_feed(d: dec.Declaration, why: str | None, landed: bool = False) -> None:
    """Record the feed's outcome for `d`: shown (`why` None) or not. `landed`: the pane holds a
    text at `d`'s place that a delete must clear (its own, or the older one it replaced)."""
    STATE.comment_feed[d.owner] = ({"state": "armed", "landed": True} if why is None
                                   else {"state": "unarmable", "why": why, "landed": landed})


def forget(d: dec.Declaration) -> None:
    """Drop what the feed recorded of `d`."""
    STATE.comment_feed.pop(d.owner, None)


def holds_text_to_clear(d: dec.Declaration) -> bool:
    """Whether the pane holds a text at `d`'s place that is `d`'s to clear (`record_feed`)."""
    return bool((STATE.comment_feed.get(d.owner) or {}).get("landed"))


def pane_line(ses: gs.Session, scratch: Path, addr: int, cpu: str | None) -> str:
    """MAME's line at `addr` on `cpu`, or why it could not be read. A commented line ends
    ` // <text>`."""
    try:
        return read.dasm_lines(ses, scratch, addr, 1, cpu)[0]
    except gs.SessionError as e:
        return f"the pane could not be read back: {e}"


def shows(line: str, text: str) -> bool:
    return line.endswith(f" // {text}")


def displace_rivals(d: dec.Declaration, addr: int, rivals: list[dec.Declaration]) -> None:
    """`d`'s `comadd` landed at `addr`: mark every other comment of `rivals` not shown and not
    landed; its why names `d`, unless its own text is one the console cannot carry."""
    taken = (f"{d.ref!r} is at the same place ({st.hex_addr(addr)} on {d.cpu}) and is what the "
             "pane shows: it holds one comment per place")
    for other in rivals:
        if other.owner != d.owner:
            record_feed(other, console_fault(other.text) or taken)


def _feed_one(ses: gs.Session, scratch: Path, d: dec.Declaration, addr: int,
              shown: bool, rivals: list[dec.Declaration]) -> None:
    """One `comadd` and its read back. `shown`: the pane holds an older text here, which a
    comment that cannot be fed clears; `rivals`: the store's comments at the place."""
    command = f'comadd {addr:#x},"{d.text}"'
    why = console_fault(d.text)
    if why is None:
        try:
            ses.console_packet(command)
        except gs.CommandTooLong as e:
            why = str(e)
    if why is not None:
        record_feed(d, why)
        if shown:
            ses.monitor(f"comdelete {addr:#x}")
        return
    said = ses.monitor(command).strip()
    if said:
        record_feed(d, f"the console answered `comadd` with {' '.join(said.split())!r}",
                landed=shown)
        return
    displace_rivals(d, addr, rivals)
    line = pane_line(ses, scratch, addr, d.cpu)
    record_feed(d, None if shows(line, d.text) else
            f"after the `comadd`, MAME's line at {addr:#x} reads {line!r}", landed=True)


def feed(ses: gs.Session, scratch: Path, decls: list[dec.Declaration],
         shown: frozenset[Place] = frozenset()) -> str | None:
    """Feed every resolving comment of `decls` to the pane on its cpu, recording each outcome
    in `STATE.comment_feed`; `shown` names the places whose pane holds an older text. Returns a
    note when the visible cpu could not be put back. Callers never pass a stale comment."""
    by_place: dict[Place, list[dec.Declaration]] = {}
    for c in comments():
        by_place.setdefault(place(c), []).append(c)
    groups: dict[str | None, list[tuple[dec.Declaration, int]]] = {}
    for d in decls:
        res = arming.resolve_decl(d)
        if res.addr is None:
            forget(d)
            continue
        groups.setdefault(d.cpu, []).append((d, res.addr))

    def act(item: tuple[dec.Declaration, int], refusal: st.Invalid | None) -> None:
        d, addr = item
        if refusal is not None:
            record_feed(d, str(refusal), landed=(d.cpu, addr) in shown)
        else:
            _feed_one(ses, scratch, d, addr, (d.cpu, addr) in shown,
                      by_place.get((d.cpu, addr), []))

    return cpus.on_cpus(ses, cpus.visible_cpu(ses), groups, "a comment is fed to MAME's pane on "
                        "the visible cpu, the one `comadd` acts on", act)


def feed_in_turn(ses: gs.Session, scratch: Path, places: dict[Place, list[dec.Declaration]],
                  shown: frozenset[Place] = frozenset()) -> list[str]:
    """Feed each place's comments in turn, the next only where the pane does not show the last,
    so a text the console cannot carry never hides one it can. Returns the cpu-restore notes."""
    notes: list[str] = []
    pending = places
    while pending:
        note = feed(ses, scratch, [rows[0] for rows in pending.values()], shown)
        if note and note not in notes:
            notes.append(note)
        pending = {at: rows[1:] for at, rows in pending.items()
                   if len(rows) > 1 and not is_shown(rows[0])}
    return notes


def rivals(d: dec.Declaration) -> list[dec.Declaration]:
    """The other non-stale comments the store holds at `d`'s place."""
    at = place(d)
    return [c for c in comments()
            if c.owner != d.owner and place(c) == at and not arming.stale(c)]


def clear_or_hand_over(ses: gs.Session, scratch: Path, target: dec.Declaration,
                        gone: dict[str, Any], on: str | None, pane_holds_it: bool,
                        shown_by_its_feed: bool, others: list[dec.Declaration]) -> list[str]:
    """The pane after `target` left the store, and the notes to report. A rebuild can leave
    `others` at the place: one already shown keeps it, else the first that can show takes it.
    With none, a held text is cleared; MAME keys a comment by address and the bytes under it,
    so `comdelete` cannot clear a text whose bytes changed since its feed."""
    notes: list[str] = []
    addr = int(gone["addr"], 16) if "addr" in gone else None
    if others and any(is_shown(d) for d in others):
        return notes                     # a rival already holds the pane, and keeps it
    if others:
        at = place(target)
        notes.extend(feed_in_turn(ses, scratch, {at: others},
                                  frozenset({at}) if pane_holds_it else frozenset()))
        if all(not is_shown(d) for d in others):
            pane_said = ""
            if pane_holds_it and addr is not None:
                pane_said = (", which still shows the deleted text"
                        if shows(pane_line(ses, scratch, addr, on), target.text)
                        else ", which was cleared")
            notes.append(f"no other comment at {gone.get('addr')} on {on} could take its place "
                         f"in MAME's pane{pane_said}: `comment_list` says why for each")
        return notes
    if not pane_holds_it or addr is None:
        return notes

    def act(_item: None, refusal: st.Invalid | None) -> None:
        if refusal is not None:
            notes.append(f"the pane could not be cleared: {refusal}")
            return
        before = pane_line(ses, scratch, addr, on)
        ses.monitor(f"comdelete {addr:#x}")
        if shown_by_its_feed and not shows(before, target.text):
            notes.append(f"the bytes at {addr:#x} changed since its text was fed, and MAME keys a "
                         "comment by them: it keeps this one, hidden, and shows it again if they "
                         "come back, until `close`")
        elif shows(line := pane_line(ses, scratch, addr, on), target.text):
            notes.append(f"MAME's line at {addr:#x} still shows the text ({line!r}) and keeps "
                         "it until `close`")

    put_back = cpus.on_cpus(ses, cpus.visible_cpu(ses), {on: [None]}, "a comment is cleared "
                            "from MAME's pane on the visible cpu, the one `comdelete` acts on",
                            act)
    return [*notes, *([put_back] if put_back else [])]
