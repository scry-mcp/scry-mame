"""THE DEBUGGER'S OWN LISTS, `bplist` and `wplist`, read into rows: a row's index, its address,
its cpu, its condition and action, and whether it is enabled, and which row is the one a call
just placed or may adopt. Every arm, clear and re-arm reads the machine's answer here, so the
debugger's account of what it holds is parsed in one place.
"""

from __future__ import annotations

import re
from typing import Any

import gdb_session as gs
import mame_cpus as cpus
import mame_state as st

# The console's list shapes, CAPTURED live and held to in the tests: one `wplist` row per watch
# (`    1 @ 2031FC-2031FF write`, a leading `D` when disabled), one `bplist` row per
# breakpoint (`    1 @ 000400`) and the sentence for none.
# THE FLAG IS ONE COLUMN (`%c%4X`: a space, or `D` when disabled), read before the index
# rather than skipped as whitespace: an enabled row numbered `D1` prints `  D1`, and a pattern
# that lets the flag be optional after any indent reads it as row 1, disabled.
# A row carries its condition and its action after the address, in the console's own words
# (`    2 @ 000404 if (++temp1)==0`, `    1 @ 0025A4 do temp0++ ; g`, captured), on a watchpoint
# as on a breakpoint: `execute_wplist` builds its rows with the same tails. A watchpoint's type
# is padded (`read `, `r/w  `), so a tail can follow it after more than one space.
_WPLIST_ROW = re.compile(
    r"^([ D]) *([0-9A-Fa-f]+) @ ([0-9A-Fa-f]+)-([0-9A-Fa-f]+) (read|write|r/w)\s*?"
    r"(?: if (?P<cond>.+?))?(?: do (?P<act>.+?))?\s*$")
_BPLIST_ROW = re.compile(
    r"^([ D]) *([0-9A-Fa-f]+) @ ([0-9A-Fa-f]+)(?: if (?P<cond>.+?))?(?: do (?P<act>.+?))?\s*$")


# EVERY LINE THE TWO LISTS PRINT, read in `execute_bplist` and `execute_wplist`
# (`src/emu/debug/debugcmd.cpp`): a row (`%c%4X @ ...`, whose index widens past four digits),
# a device's header (`Device '%s' breakpoints:`, `Device '%s' %s space watchpoints:`), the
# sentence for none, bare or naming a CPU, and `Device %s is not a CPU`, which starts a line no
# list accepts. `unwrap_console` reads these only where the wrap's geometry cannot decide.
_LIST_STARTS = re.compile(r"^(?:[ D] *[0-9A-Fa-f]+ @ |Device |No (?:break|watch)points )")
_LIST_HEADER = re.compile(
    r"^Device '(?P<cpu>[^']*)' (?:breakpoints|(?P<space>\S+) space watchpoints):$")
_LIST_NONE = re.compile(r"^No (?:break|watch)points currently installed(?: for CPU \S+)?$")


def list_rows(text: str, command: str, row: re.Pattern[str],
              starts: re.Pattern[str] = _LIST_STARTS, header: re.Pattern[str] = _LIST_HEADER,
              none: re.Pattern[str] = _LIST_NONE,
              ) -> list[tuple[re.Match[str], dict[str, str | None]]]:
    """The rows of a `bplist`, `wplist` or `rplist` answer, each read WHOLE however the console
    wrapped it, each with the `cpu` (and `space`, on a `wplist`) of the header it sits under, or
    a refusal: a line that is neither a row, a device's header nor the sentence for none is
    quoted, never dropped, and an answer with no row and no such sentence is not a list at
    all. A row's header is the only word of which device it belongs to: the same address can
    sit under each cpu, under one counter. `starts`, `header` and `none` default to the
    breakpoint and watchpoint lists' shapes; `header` names a `cpu` group and may name a
    `space`."""
    rows: list[tuple[re.Match[str], dict[str, str | None]]] = []
    listed_none = False
    under: dict[str, str | None] = {"cpu": None, "space": None}
    for line in gs.unwrap_console(text, starts):
        if m := row.match(line):
            rows.append((m, dict(under)))
        elif none.match(line):
            listed_none = True
        elif heading := header.match(line):
            under = {"cpu": heading.group("cpu"), "space": heading.groupdict().get("space")}
        else:
            raise st.Invalid("unexpected_answer",
                             f"the console's `{command}` answered a line that is neither a row, "
                             f"a device's header nor the sentence for none: {line!r}; "
                             f"`debug(\"{command}\")` shows the whole answer, and `close` then "
                             "`start` gives a fresh console")
    if not rows and not listed_none:
        raise st.Invalid("unexpected_answer",
            f"the console's `{command}` answered something other than a list "
            f"(`debug(\"{command}\")` shows it; `close` then `start` gives a fresh console): "
                           f"{text.strip()!r}")
    return rows


def _tails(m: re.Match[str]) -> str:
    """A row's condition and action, spelled as the console spells them."""
    return ((f" if {m.group('cond')}" if m.group("cond") else "")
            + (f" do {m.group('act')}" if m.group("act") else ""))


def parse_wplist(text: str) -> list[dict[str, Any]]:
    """The debugger's watchpoints as `wplist` lists them, or a refusal (`list_rows`). A
    disabled row keeps its `D`."""
    return [{"index": int(m.group(2), 16), "addr": int(m.group(3), 16), **under,
             "length": int(m.group(4), 16) - int(m.group(3), 16) + 1, "kind": m.group(5),
             "enabled": m.group(1) != "D",
             "entry": f"{'D ' if m.group(1) == 'D' else ''}{m.group(2)} @ {m.group(3)}-"
                      f"{m.group(4)} {m.group(5)}" + _tails(m),
             "condition": m.group("cond"), "action": m.group("act")}
            for m, under in list_rows(text, "wplist", _WPLIST_ROW)]


def parse_bplist(text: str) -> list[dict[str, Any]]:
    """The debugger's breakpoints as `bplist` lists them (`    1 @ 000400` per row, measured),
    or a refusal (`list_rows`)."""
    return [{"index": int(m.group(2), 16), "addr": int(m.group(3), 16), "cpu": under["cpu"],
             "enabled": m.group(1) != "D",
             "entry": f"{'D ' if m.group(1) == 'D' else ''}{m.group(2)} @ {m.group(3)}"
                      + _tails(m),
             "condition": m.group("cond"), "action": m.group("act")}
            for m, under in list_rows(text, "bplist", _BPLIST_ROW)]


def bp_held(ses: gs.Session, cpu: str | None = None) -> list[dict[str, Any]]:
    """The debugger's own breakpoint list, read back, or `cpu`'s alone (`bplist <cpu>`, its
    `help`); `run_to` reads it too, for the two rows it arms."""
    return parse_bplist(ses.monitor(f"bplist {cpu}" if cpu else "bplist"))


def wp_held(ses: gs.Session, cpu: str | None = None) -> list[dict[str, Any]]:
    """The debugger's own list, read back, or `cpu`'s alone (`wplist <cpu>`). Read on a
    RUNNING machine too: the stub answers the console while it runs (measured), and a list of
    armed rows is not a value off a moving machine, so the refusal the readers make does not
    apply to it."""
    return parse_wplist(ses.monitor(f"wplist {cpu}" if cpu else "wplist"))


def rows_at(held: list[dict[str, Any]], addr: int) -> list[dict[str, Any]]:
    """Every row `bplist` holds at `addr`, under any cpu: the same address can carry one per
    cpu, and a row typed through `debug` beside one of this server's."""
    return [r for r in held if r["addr"] == addr]


def row_at_index(held: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    """The listed row numbered `index`, or None: the index is a row's identity (see
    `STATE.breakpoints`)."""
    return next((r for r in held if r["index"] == index), None)


def armed_row(before: list[dict[str, Any]], after: list[dict[str, Any]], addr: int,
              length: int | None = None, cpu: str | None = None) -> dict[str, Any] | None:
    """The row an arm placed on `cpu`: the one at `addr` (and `length`, for a watchpoint) under
    that cpu whose index the list read before it did not hold. What sits at the address under
    another cpu may be a row sent in the same pass, so the cpu decides and not the index
    alone."""
    return fresh_row(after, {r["index"] for r in before}, addr, length, cpu)


def fresh_row(rows: list[dict[str, Any]], old: set[int], addr: int,
              length: int | None = None, cpu: str | None = None) -> dict[str, Any] | None:
    """The row at `addr` (and `length`, and under `cpu` when both sides name one) whose index
    is not among `old`."""
    return next((r for r in rows if r["index"] not in old and r["addr"] == addr
                 and (length is None or r["length"] == length)
                 and cpus.same_cpu(cpu, r["cpu"])), None)


def adoptable_row(held: list[dict[str, Any]], addr: int, cpu: str | None, taken: set[int],
                  length: int | None = None) -> dict[str, Any] | None:
    """A row at `addr` (and `length`, for a watchpoint) that nobody's record holds (`taken`),
    under `cpu`, where this server's own arm would land: a row under another cpu watches
    another program and is never adopted. With the cpu unknown (`None`) the address decides
    alone."""
    return next((r for r in held if r["addr"] == addr and r["index"] not in taken
                 and (length is None or r["length"] == length)
                 and (cpu is None or r["cpu"] == cpu)), None)


def row_state(row: dict[str, Any]) -> str:
    """`armed` for a row the debugger lists enabled, `disabled` for one it lists with a `D`."""
    return "armed" if row["enabled"] else "disabled"


def adopted_state(family: str, row: dict[str, Any]) -> dict[str, str]:
    """What a re-arm says of a row it ADOPTED rather than sent: nothing for an enabled one, and
    for a disabled one that it is, and what enables it. Adopted either way, as `breakpoint_at`
    and `watch_add` adopt it: the row is the declaration's, and `<family>enable` is the
    caller's."""
    if row["enabled"]:
        return {}
    return {"state": "disabled",
            "note": f"the debugger lists it disabled ({row['entry']}): it does not fire until "
                    f"`debug(\"{family}enable {row['index']:#x}\")`"}


def listed_as_sent(row: dict[str, Any] | None, condition: str) -> bool:
    """Whether the row read back for a `bp`/`wp` is the one sent: listed, and with a condition
    when one was sent. The console answers a command the same whatever it did with the
    condition, so the list is the only proof, and a row that lost it stops at every hit."""
    return row is not None and not (condition and not row.get("condition"))


def not_listed(sent: str, listing: str, conditioned: bool = False) -> str:
    """The one sentence for a row the console took and its list does not show: `sent` is the
    command as the reply names it (quoted, or described), `listing` the list that was read."""
    return (f"the console took {sent} and its `{listing}` does not list "
            f"{'a conditioned row' if conditioned else 'it'}: nothing is armed")
