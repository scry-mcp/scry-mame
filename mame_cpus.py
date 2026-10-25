"""The machine's cpus. The debugger acts on one, the visible one, which is read from
`cpulist` and never remembered."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from scry_core.reply_contract import unavailable

import gdb_session as gs
import mame_inputs as inputs
import mame_space as mspace
import mame_state as st
from mame_state import STATE

# `[*0] :maincpu` / `[1] :subcpu`: `*` marks the visible one.
_CPULIST_ROW = re.compile(r"^\[(\*?)(\d+)\] (\S+)$")


def _cpulist(ses: gs.Session) -> tuple[list[str], str | None]:
    """Every tag `cpulist` lists, and the visible one (None when the console fails)."""
    tags: list[str] = []
    visible: str | None = None
    try:
        answer = ses.monitor("cpulist")
    except gs.SessionError:
        return [], None
    for line in answer.splitlines():
        if (m := _CPULIST_ROW.match(line.strip())) is not None:
            tags.append(m.group(3))
            if m.group(1):
                visible = m.group(3)
    return tags, visible


def visible_cpu(ses: gs.Session) -> str | None:
    """The tag `cpulist` marks as visible, or None when it marks none."""
    tags, visible = _cpulist(ses)
    if tags and not STATE.cpus:
        STATE.cpus = tags
    return visible


def listed(ses: gs.Session) -> tuple[list[str], str | None]:
    """Every cpu `cpulist` lists and the visible one, off one console read."""
    tags, visible = _cpulist(ses)
    if tags and not STATE.cpus:
        STATE.cpus = tags
    return (tags or list(STATE.cpus)), visible


def cpu_list(ses: gs.Session) -> list[str]:
    """Every cpu in the debugger's order, read once a session."""
    if not STATE.cpus:
        STATE.cpus = _cpulist(ses)[0]
    return STATE.cpus


def live_cpu(ses: gs.Session) -> str | None:
    """The cpu MAME last stopped on, per the patched stub's `?`; None without threads."""
    if not ses.threads:
        return None
    try:
        return ses.threads.get(ses.stopped_thread() or 0)
    except gs.SessionError:
        return None


def register_blocks(ses: gs.Session) -> dict[str, dict[str, str]]:
    """Every register of every served cpu, by cpu then name; a cpu without a block is left out."""
    served = dict(ses.threads) if ses.threads else {1: stub_cpu(ses)}
    out: dict[str, dict[str, str]] = {}
    for tid, tag in sorted(served.items()):
        if tag is None:
            continue
        try:
            out[tag] = ses.register_texts(thread=tid)
        except gs.SessionError:
            continue      # no register map, or a reply that does not cut by its widths
    return out


def thread_of(ses: gs.Session, cpu: str | None) -> int | None:
    """The patched stub's thread for `cpu`, or None."""
    return next((tid for tid, tag in ses.threads.items() if tag == cpu), None)


def thread_for(ses: gs.Session, cpu: str) -> tuple[str | None, int]:
    """The cpu a register or memory call acts on and its stub thread: the named cpu, else the
    visible one."""
    if not ses.threads:
        served = stub_cpu(ses)
        if inputs.cpu_given(cpu) and (tag := named(ses, cpu)) != served:
            raise st.Invalid("bad_argument", f"{unthreaded_why(tag, served)}: omit `cpu`"
                             + (f", or name {served}" if served else ""),
                             cpu_tags=[served] if served else [])
        return served, 1
    on = acting(ses, cpu)
    thread = thread_of(ses, on)
    if thread is None:
        threaded = sorted(ses.threads.values())
        raise st.Invalid("bad_argument", f"{no_thread_why(ses, on)}: name one of {threaded} as "
                         "`cpu`", cpu_tags=threaded)
    return on, thread


def unthreaded_why(tag: str, served: str | None) -> str:
    """Why `tag` cannot be read on a stub without threads."""
    return (f"{tag}'s registers and memory are read through its own thread of the gdbstub's "
            f"thread patch, and this build's stub serves only "
            f"{served or 'its first cpu, which `cpulist` does not name'}")


def no_thread_why(ses: gs.Session, tag: str) -> str:
    """Why the patched stub cannot serve `tag`."""
    return f"the stub names no thread for {tag}; its threads are {ses.threads}"


#: A thread's program counter as (register name, value), or why not.
PcReading = tuple[str, int] | str


def pc_reading(ses: gs.Session, thread: int) -> PcReading:
    """`thread`'s program counter register and value, or why it could not be read. Makes no cpu
    visible."""
    try:
        name = ses.layout(thread).pc_name
        return name, ses.reg(name, thread=thread)
    except gs.SessionError as e:
        return str(e)


def pc_readings(ses: gs.Session) -> dict[str, PcReading]:
    """Every cpu's `pc_reading` by tag; empty on a stub without threads."""
    return {tag: pc_reading(ses, tid) for tid, tag in sorted(ses.threads.items())}


def pc_fields(reading: PcReading) -> dict[str, Any]:
    """A `pc_reading` as a reply carries it."""
    if isinstance(reading, str):
        return unavailable(reading)
    return {"reg": reading[0], "value": st.hex_addr(reading[1])}


def pc_by_cpu(ses: gs.Session, tags: list[str]) -> dict[str, PcReading]:
    """A `pc_reading` for each of `tags`; on an unthreaded stub only the served cpu has one."""
    if ses.threads:
        return {tag: no_thread_why(ses, tag) if (tid := thread_of(ses, tag)) is None
                else pc_reading(ses, tid) for tag in tags}
    served = stub_cpu(ses)
    return {tag: pc_reading(ses, 1) if tag == served else unthreaded_why(tag, served)
            for tag in tags}


def make_visible(ses: gs.Session, tag: str, needs: str) -> None:
    """Make `tag` visible through the stub's `Hc`, which runs nothing; the stub refuses an
    ignored cpu. `needs` words the refusal."""
    thread = thread_of(ses, tag)
    if thread is None:
        raise st.Invalid("bad_argument", f"{needs}, and this build's stub cannot make {tag} "
                                         "visible without running (no thread patch): "
                                         f"`focus(cpu=\"{tag}\")` makes it visible through the "
                                         "console, which runs the machine and ignores every "
                                         "other cpu until it is observed")
    try:
        ses.make_visible(thread)
    except gs.Refused as e:
        if tag in (ignored(ses) or []):
            raise st.Invalid("needs_call",
                             f"{needs}, and the debugger ignores {tag}, which the stub will not "
                             f"show (a step on it would never end): `debug(\"observe {tag}\")` "
                             "first") from None
        raise st.Invalid("unexpected_answer", f"{e}: {tag} was not made visible; `cpu_info` says "
                                              "which cpu is visible now") from None


def on_cpus(ses: gs.Session, visible: str | None, groups: dict[str | None, list[Any]],
            needs: str, act: Callable[[Any, st.Invalid | None], None]) -> str | None:
    """Make each cpu of `groups` visible, `act(item, refusal)` its items, put `visible` back.
    A cpu that cannot be shown is passed to `act` as the refusal. Returns a note naming the
    cpu left visible when the put-back was refused; a refusing act carries it too."""
    shown = visible
    try:
        for cpu, items in groups.items():
            refusal: st.Invalid | None = None
            if cpu is not None and cpu != shown:
                try:
                    make_visible(ses, cpu, needs)
                    shown = cpu
                except st.Invalid as e:
                    refusal = e
            for item in items:
                act(item, refusal)
    except st.Invalid as e:
        if (put_back := _put_back(ses, visible, shown)) is None:
            raise
        raise st.Invalid(e.code, f"{e}; {put_back}", **e.fields) from e
    except BaseException:
        _put_back(ses, visible, shown)
        raise
    return _put_back(ses, visible, shown)


def _put_back(ses: gs.Session, visible: str | None, shown: str | None) -> str | None:
    """Restore `visible` if `shown` moved it, or return the note naming the cpu left."""
    if visible is None or shown == visible:
        return None
    try:
        make_visible(ses, visible, f"{visible} is put back as the visible cpu")
    except (st.Invalid, gs.SessionError) as e:
        return (f"{visible} could not be made visible again ({e}), so {shown} is the visible cpu "
                f"now: `focus(cpu={visible!r})` shows it again")
    return None


def described(ses: gs.Session, on: str | None, thread: int) -> gs.Layout:
    """`thread`'s register file with a known byte order, else `no_channel`."""
    try:
        lay = ses.layout(thread)
        _ = lay.byte_order
    except (gs.Refused, gs.UnknownByteOrder) as e:
        raise st.Invalid("no_channel", f"{on}'s registers cannot be read here: {e}") from None
    return lay


def program_endianness(ses: gs.Session, machine_map: dict[str, Any] | None,
                       first_cpu: str | None) -> dict[int, str]:
    """Endianness of each served cpu's program space, by stub thread."""
    served = ses.threads or ({1: first_cpu} if first_cpu else {})
    spaces = {row["cpu"]: row["endianness"] for row in (machine_map or {}).get("spaces", [])
              if row.get("space") == "program"}
    return {tid: spaces[tag] for tid, tag in served.items() if tag in spaces}


def layout(ses: gs.Session, cpu: str | None) -> gs.Layout:
    """`cpu`'s register file and byte order; the first cpu's when none is named."""
    return ses.layout(thread_of(ses, cpu) or 1)


def same_cpu(a: str | None, b: str | None) -> bool:
    """Whether two cpus are one place: the same tag, or either unknown."""
    return None in (a, b) or a == b


def match_tag(cpu: str, tags: list[str]) -> str:
    """The tag among `tags` that `cpu` names, as `subcpu` or `:subcpu`, else the refusal."""
    wanted = next((tag for tag in tags if cpu.strip() in (tag, tag.lstrip(":"))), "")
    if not wanted:
        raise st.Invalid("unknown_ref",
                         f"no cpu {cpu!r} on this machine; it has "
                         f"{tags or 'none this gather recognised'}", cpu_tags=tags)
    return wanted


def named(ses: gs.Session, cpu: str) -> str:
    """The absolute tag of the cpu a call names, from the `start` inventory or `cpulist`."""
    tags = [row["tag"] for row in (STATE.machine_map or {}).get("cpus", [])]
    return match_tag(cpu, tags or cpu_list(ses))


def acting(ses: gs.Session, cpu: str) -> str:
    """`chosen`, or a refusal when no cpu is named and none is visible."""
    on = chosen(ses, cpu)
    if on is None:
        raise st.Invalid("unexpected_answer",
                         "`cpulist` marked no cpu visible, so a call naming no cpu has none to "
                         "act on: name one with `cpu`")
    return on


def chosen(ses: gs.Session, cpu: str) -> str | None:
    """The cpu a call acts on: the named one, else the visible one read now."""
    return named(ses, cpu) if inputs.cpu_given(cpu) else visible_cpu(ses)


def _flag_listing(ses: gs.Session, command: str, listing: str, empty: str) -> list[str] | None:
    """The devices a flag's listing names (`listing` then quoted tags, or `empty`); None when
    the console answered neither shape."""
    try:
        # MAME's console wraps one logical line at its column.
        lines = gs.unwrap_console(ses.monitor(command).strip(),
                                  re.compile(f"^(?:{re.escape(listing)}|{re.escape(empty)})"))
    except gs.SessionError:
        return None
    answer = lines[0] if len(lines) == 1 else ""
    if answer == empty:
        return []
    m = re.match(f"^{re.escape(listing)} (.*)$", answer)
    return None if m is None else re.findall(r"'([^']*)'", m.group(1))


def ignored(ses: gs.Session) -> list[str] | None:
    """The cpus the debugger ignores, or None; a breakpoint on one has no effect."""
    return _flag_listing(ses, "ignore", "Currently ignoring device",
                    "Not currently ignoring any devices")


def suspended(ses: gs.Session) -> list[str] | None:
    """The cpus the debugger suspends, or None."""
    return _flag_listing(ses, "suspend", "Currently suspended device",
                    "No currently suspended devices")


def ignored_note(ses: gs.Session, cpu: str | None) -> str | None:
    """The note for a row armed on an ignored cpu, else None."""
    if cpu is None or cpu not in (ignored(ses) or []):
        return None
    return f"the debugger ignores {cpu}, so this row has no effect until `debug(\"observe {cpu}\")`"


#: Cache key of each cpu's console register names; not a section of `machine_map`'s reply.
CPU_REGISTERS = "cpu_registers"


def register_names(ses: gs.Session, cpu: str | None) -> list[str]:
    """The names `cpu`'s console knows as registers."""
    known = (STATE.machine_map or {}).get(CPU_REGISTERS, {})
    if cpu is not None and cpu in known:
        return list(known[cpu])
    return layout(ses, cpu).register_names


def cpu_type(cpu: str | None) -> str | None:
    """MAME's shortname for `cpu` (`m68000`), or None."""
    rows = STATE.machine_map.get("cpus", []) if STATE.machine_map else []
    return next((row.get("type") for row in rows if cpu is not None and row["tag"] == cpu), None)


def _space_row(cpu: str | None, space: str = mspace.PROGRAM) -> dict[str, Any] | None:
    """`cpu`'s `space` row from the `start` inventory, or None."""
    rows = STATE.machine_map.get("spaces", []) if STATE.machine_map else []
    return next((row for row in rows if (row["cpu"], row["space"]) == (cpu, space)), None)


def program_mask(cpu: str | None) -> int | None:
    """The last address `cpu`'s program space reaches, or None without an inventory row."""
    row = _space_row(cpu)
    return int(row["address_mask"], 16) if row is not None and "address_mask" in row else None


def bus_width(cpu: str | None, space: str = mspace.PROGRAM) -> int | None:
    """The bus width in bits of `cpu`'s `space`, or None."""
    row = _space_row(cpu, space)
    return (int(row["data_width_bits"]) if row is not None and "data_width_bits" in row
            else None)


def stub_cpu(ses: gs.Session) -> str | None:
    """The cpu the stub's register and memory packets serve, or None."""
    if ses.threads:
        return ses.threads.get(1)
    tags = cpu_list(ses)
    return tags[0] if tags else None
