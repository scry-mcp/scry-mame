"""The debugger's `bplist` and `wplist` answers parsed into rows, and the row-matching helpers."""

from __future__ import annotations

import re
from typing import Any

import gdb_session as gs
import mame_cpus as cpus
import mame_state as st

# The flag is one column (`%c%4X`), read before the index: an enabled row numbered `D1` prints
# `  D1`, and an optional flag would read it as row 1, disabled. A watchpoint's padded type
# (`read `) can leave more than one space before the tails.
_WPLIST_ROW = re.compile(
    r"^([ D]) *([0-9A-Fa-f]+) @ ([0-9A-Fa-f]+)-([0-9A-Fa-f]+) (read|write|r/w)\s*?"
    r"(?: if (?P<cond>.+?))?(?: do (?P<act>.+?))?\s*$")
_BPLIST_ROW = re.compile(
    r"^([ D]) *([0-9A-Fa-f]+) @ ([0-9A-Fa-f]+)(?: if (?P<cond>.+?))?(?: do (?P<act>.+?))?\s*$")


# Every line `execute_bplist`/`execute_wplist` (`src/emu/debug/debugcmd.cpp`) print, for
# `unwrap_console` where the wrap's geometry cannot decide. The index widens past four digits.
_LIST_STARTS = re.compile(r"^(?:[ D] *[0-9A-Fa-f]+ @ |Device |No (?:break|watch)points )")
_LIST_HEADER = re.compile(
    r"^Device '(?P<cpu>[^']*)' (?:breakpoints|(?P<space>\S+) space watchpoints):$")
_LIST_NONE = re.compile(r"^No (?:break|watch)points currently installed(?: for CPU \S+)?$")


def list_rows(text: str, command: str, row: re.Pattern[str],
              starts: re.Pattern[str] = _LIST_STARTS, header: re.Pattern[str] = _LIST_HEADER,
              none: re.Pattern[str] = _LIST_NONE,
              ) -> list[tuple[re.Match[str], dict[str, str | None]]]:
    """The rows of a list answer with their header's `cpu` (and `space`); anything else raises."""
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
    """The debugger's watchpoints as `wplist` lists them; a disabled row keeps its `D`."""
    return [{"index": int(m.group(2), 16), "addr": int(m.group(3), 16), **under,
             "length": int(m.group(4), 16) - int(m.group(3), 16) + 1, "kind": m.group(5),
             "enabled": m.group(1) != "D",
             "entry": f"{'D ' if m.group(1) == 'D' else ''}{m.group(2)} @ {m.group(3)}-"
                      f"{m.group(4)} {m.group(5)}" + _tails(m),
             "condition": m.group("cond"), "action": m.group("act")}
            for m, under in list_rows(text, "wplist", _WPLIST_ROW)]


def parse_bplist(text: str) -> list[dict[str, Any]]:
    """The debugger's breakpoints as `bplist` lists them."""
    return [{"index": int(m.group(2), 16), "addr": int(m.group(3), 16), "cpu": under["cpu"],
             "enabled": m.group(1) != "D",
             "entry": f"{'D ' if m.group(1) == 'D' else ''}{m.group(2)} @ {m.group(3)}"
                      + _tails(m),
             "condition": m.group("cond"), "action": m.group("act")}
            for m, under in list_rows(text, "bplist", _BPLIST_ROW)]


def bp_held(ses: gs.Session, cpu: str | None = None) -> list[dict[str, Any]]:
    """The debugger's breakpoint list, or `cpu`'s alone."""
    return parse_bplist(ses.monitor(f"bplist {cpu}" if cpu else "bplist"))


def wp_held(ses: gs.Session, cpu: str | None = None) -> list[dict[str, Any]]:
    """The debugger's watchpoint list, or `cpu`'s alone; also answers while the machine runs."""
    return parse_wplist(ses.monitor(f"wplist {cpu}" if cpu else "wplist"))


def rows_at(held: list[dict[str, Any]], addr: int) -> list[dict[str, Any]]:
    """Every row held at `addr`, under any cpu."""
    return [r for r in held if r["addr"] == addr]


def row_at_index(held: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    """The listed row numbered `index`, or None."""
    return next((r for r in held if r["index"] == index), None)


def armed_row(before: list[dict[str, Any]], after: list[dict[str, Any]], addr: int,
              length: int | None = None, cpu: str | None = None) -> dict[str, Any] | None:
    """The row an arm placed on `cpu`: new since `before`; another cpu's may share the address."""
    return fresh_row(after, {r["index"] for r in before}, addr, length, cpu)


def fresh_row(rows: list[dict[str, Any]], old: set[int], addr: int,
              length: int | None = None, cpu: str | None = None) -> dict[str, Any] | None:
    """The row at `addr` (and `length`, and `cpu` when both sides name one) not among `old`."""
    return next((r for r in rows if r["index"] not in old and r["addr"] == addr
                 and (length is None or r["length"] == length)
                 and cpus.same_cpu(cpu, r["cpu"])), None)


def adoptable_row(held: list[dict[str, Any]], addr: int, cpu: str | None, taken: set[int],
                  length: int | None = None) -> dict[str, Any] | None:
    """A row at `addr` that no record holds (`taken`); another cpu's is never adopted."""
    return next((r for r in held if r["addr"] == addr and r["index"] not in taken
                 and (length is None or r["length"] == length)
                 and (cpu is None or r["cpu"] == cpu)), None)


def row_state(row: dict[str, Any]) -> str:
    """`armed` for an enabled row, `disabled` for one listed with a `D`."""
    return "armed" if row["enabled"] else "disabled"


def adopted_state(family: str, row: dict[str, Any]) -> dict[str, str]:
    """What a re-arm says of an adopted row: nothing if enabled, else how to enable it."""
    if row["enabled"]:
        return {}
    return {"state": "disabled",
            "note": f"the debugger lists it disabled ({row['entry']}): it does not fire until "
                    f"`debug(\"{family}enable {row['index']:#x}\")`"}


def listed_as_sent(row: dict[str, Any] | None, condition: str) -> bool:
    """Whether the row read back is the one sent; only the list proves the condition took."""
    return row is not None and not (condition and not row.get("condition"))


def not_listed(sent: str, listing: str, conditioned: bool = False) -> str:
    """The sentence for a row the console took and its `listing` does not show."""
    return (f"the console took {sent} and its `{listing}` does not list "
            f"{'a conditioned row' if conditioned else 'it'}: nothing is armed")
