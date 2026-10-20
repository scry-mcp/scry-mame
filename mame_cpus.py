"""THE MACHINE'S CPUS, and which one a reply is about.

MAME's debugger acts on ONE cpu at a time, the visible one: a console `bp` that names no cpu
and every console reader land there, and MAME makes the cpu that stopped the
visible one at every stop. So which cpu that is is READ, never remembered: the console's
`cpulist` lists every cpu and marks the visible one with `*`, answers on a build with or
without the gdbstub's thread patch, and runs nothing.

The stub's register and memory packets follow the same model where the build lets them
(`thread_for`).
"""

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

# `[*0] :maincpu` / `[1] :subcpu` (captured): the debugger's index, `*` on the visible one.
_CPULIST_ROW = re.compile(r"^\[(\*?)(\d+)\] (\S+)$")


def _cpulist(ses: gs.Session) -> tuple[list[str], str | None]:
    """Every tag `cpulist` lists, in its order, and the one it marks as visible (or None).

    A CPU IS A REPLY'S ANNOTATION, never what the reply read: a console that fails to answer
    here leaves the cpu unknown (`None`) and the reply's own reading stands or falls on its own.
    The failure is not lost: a wait that ran out latches the session `broken`, which every
    reply's `session` block then carries."""
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
    """The tag `cpulist` marks as visible, or None when the console's answer marks none (a
    console without `cpulist`): the caller then decides as it did before a row had a cpu."""
    tags, visible = _cpulist(ses)
    if tags and not STATE.cpus:
        STATE.cpus = tags
    return visible


def listed(ses: gs.Session) -> tuple[list[str], str | None]:
    """Every cpu `cpulist` lists and the one it marks visible, off ONE console read, the tags
    kept for the session as `cpu_list` keeps them. The visible cpu is never remembered."""
    tags, visible = _cpulist(ses)
    if tags and not STATE.cpus:
        STATE.cpus = tags
    return (tags or list(STATE.cpus)), visible


def cpu_list(ses: gs.Session) -> list[str]:
    """Every cpu in the debugger's order, read once a session: empty when the console lists
    none."""
    if not STATE.cpus:
        STATE.cpus = _cpulist(ses)[0]
    return STATE.cpus


def live_cpu(ses: gs.Session) -> str | None:
    """The cpu MAME last stopped on, which it is LIVE on until it next runs: the thread the
    patched stub's `?` names. Only that cpu ignored releases the machine (`device_debug::
    ignore`), and after an `Hc` it is not the visible one. None on a stub without threads,
    where no `Hc` exists and the visible cpu is the one that stopped."""
    if not ses.threads:
        return None
    try:
        return ses.threads.get(ses.stopped_thread() or 0)
    except gs.SessionError:
        return None


def register_blocks(ses: gs.Session) -> dict[str, dict[str, str]]:
    """Every register of every cpu the stub serves, by cpu and then by name, as the stub prints
    them (`Session.register_texts`, which needs no byte order): a thread per cpu on the patched
    stub, else its first cpu on thread 1. A cpu whose block the stub does not give (no register
    map, or a reply that does not cut by the declared widths) is left out, as `pc_reading`
    leaves one out: that is the cpu's, not the session's."""
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
    """The patched stub's thread for `cpu`, or None: a stub without threads names none."""
    return next((tid for tid, tag in ses.threads.items() if tag == cpu), None)


def thread_for(ses: gs.Session, cpu: str) -> tuple[str | None, int]:
    """The cpu a register or memory call acts on, and the stub's thread that serves it: the cpu
    the call names, else the VISIBLE one, read now. A stub without the gdbstub's thread patch
    serves its first cpu alone, thread 1, so there a call naming no cpu reads that one, as it
    always did, and one naming another is refused. On the patched stub a visible cpu `cpulist`
    does not mark is refused rather than guessed: the call names no cpu to act on."""
    if not ses.threads:
        served = stub_cpu(ses)
        if inputs.cpu_given(cpu) and (tag := named(ses, cpu)) != served:
            raise st.Invalid("bad_argument", f"{unthreaded_why(tag, served)}: omit `cpu`"
                             + (f", or name {served}" if served else ""),
                             cpus=[served] if served else [])
        return served, 1
    on = acting(ses, cpu)
    thread = thread_of(ses, on)
    if thread is None:
        threaded = sorted(ses.threads.values())
        raise st.Invalid("bad_argument", f"{no_thread_why(ses, on)}: name one of {threaded} as "
                         "`cpu`", cpus=threaded)
    return on, thread


def unthreaded_why(tag: str, served: str | None) -> str:
    """Why `tag`'s registers cannot be read on a stub without threads, which serves `served`."""
    return (f"{tag}'s registers and memory are read through its own thread of the gdbstub's "
            f"thread patch, and this build's stub serves only "
            f"{served or 'its first cpu, which `cpulist` does not name'}")


def no_thread_why(ses: gs.Session, tag: str) -> str:
    """Why the patched stub cannot serve `tag`: it names no thread for it."""
    return f"the stub names no thread for {tag}; its threads are {ses.threads}"


#: A program counter read off one thread: the register's name and its value, or why not.
PcReading = tuple[str, int] | str


def pc_reading(ses: gs.Session, thread: int) -> PcReading:
    """`thread`'s program counter register, the one `Layout.pc_name` names, and its value, or
    why it could not be read. A packet to that thread alone, so no cpu is made visible."""
    try:
        name = ses.layout(thread).pc_name
        return name, ses.reg(name, thread=thread)
    except gs.SessionError as e:
        return str(e)


def pc_readings(ses: gs.Session) -> dict[str, PcReading]:
    """Every cpu's `pc_reading`, off its own thread of the patched stub, by tag. Empty on a
    stub without threads."""
    return {tag: pc_reading(ses, tid) for tid, tag in sorted(ses.threads.items())}


def pc_fields(reading: PcReading) -> dict[str, Any]:
    """A `pc_reading` as a reply carries it: `reg` and `value`, or `unavailable` with why."""
    if isinstance(reading, str):
        return unavailable(reading)
    return {"reg": reading[0], "value": st.hex_addr(reading[1])}


def pc_by_cpu(ses: gs.Session, tags: list[str]) -> dict[str, PcReading]:
    """A `pc_reading` for each of `tags`, in their order: each off its own thread, or, on a stub
    without threads, the one cpu it serves on thread 1 and why not for the rest."""
    if ses.threads:
        return {tag: no_thread_why(ses, tag) if (tid := thread_of(ses, tag)) is None
                else pc_reading(ses, tid) for tag in tags}
    served = stub_cpu(ses)
    return {tag: pc_reading(ses, 1) if tag == served else unthreaded_why(tag, served)
            for tag in tags}


def make_visible(ses: gs.Session, tag: str, needs: str) -> None:
    """`tag` made the debugger's visible cpu through the stub's `Hc`, which ignores no cpu and
    runs nothing. `needs` says what needed it, for the refusal: a build without the thread patch
    cannot show a cpu without running, and the stub will not show one the debugger ignores,
    since a step on it would never end."""
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
    """MAKE A CPU VISIBLE, ACT, PUT `visible` BACK: the bracket for a call that shows another cpu
    for one act and leaves the visible one where it was (`visible`, the caller's own reading,
    so a second one that failed cannot leave nothing to put back). `act(item, refusal)` for each
    item of `groups`, by cpu, with that cpu made visible first when it is not (`needs` says why,
    for the refusal), and `visible` put back after, whatever `act` did. A cpu that cannot be made
    visible is handed to `act` as the refusal in place of None. Returns a note naming the cpu
    left visible when the put-back was refused, which never replaces what was done: by then the
    act has completed. An act that refused goes out as its own refusal with that note added, so
    the cpu is never left moved with nothing saying so."""
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
    """`visible` made visible again when `shown` moved it, or the note naming the cpu left."""
    if visible is None or shown == visible:
        return None
    try:
        make_visible(ses, visible, f"{visible} is put back as the visible cpu")
    except (st.Invalid, gs.SessionError) as e:
        return (f"{visible} could not be made visible again ({e}), so {shown} is the visible cpu "
                f"now: `focus(cpu={visible!r})` shows it again")
    return None


def described(ses: gs.Session, on: str | None, thread: int) -> gs.Layout:
    """`thread`'s register file with a byte order it can be decoded in, or the refusal of a cpu
    the stub does not describe (no register map: its description is refused) or whose byte
    order cannot be known (`gs.UnknownByteOrder`). A fact about that cpu, answered as
    `no_channel`; a channel that failed still raises and latches as every other."""
    try:
        lay = ses.layout(thread)
        _ = lay.byte_order
    except (gs.Refused, gs.UnknownByteOrder) as e:
        raise st.Invalid("no_channel", f"{on}'s registers cannot be read here: {e}") from None
    return lay


def program_endianness(ses: gs.Session, machine_map: dict[str, Any] | None,
                       first_cpu: str | None) -> dict[int, str]:
    """MAME's endianness of each served cpu's PROGRAM space (`gdb_session._BYTE_ORDER` says why
    that one), by the stub's thread: every thread the stub names, else thread 1 for
    `first_cpu`, the one a stub without threads serves. A cpu the inventory has no program space
    row for gets no word."""
    served = ses.threads or ({1: first_cpu} if first_cpu else {})
    spaces = {row["cpu"]: row["endianness"] for row in (machine_map or {}).get("spaces", [])
              if row.get("space") == "program"}
    return {tid: spaces[tag] for tid, tag in served.items() if tag in spaces}


def layout(ses: gs.Session, cpu: str | None) -> gs.Layout:
    """`cpu`'s register file and byte order, off its own thread's description: the first cpu's
    when no cpu is named, or on a stub without threads, which describes its first cpu alone."""
    return ses.layout(thread_of(ses, cpu) or 1)


def same_cpu(a: str | None, b: str | None) -> bool:
    """Whether two cpus are one place: the same tag, or either unknown (a console that marks no
    cpu), where the address alone decides as it did before a row had a cpu."""
    return None in (a, b) or a == b


def match_tag(cpu: str, tags: list[str]) -> str:
    """The tag among `tags` that `cpu` names, in either spelling (`subcpu` or `:subcpu`), or
    the refusal naming the ones there are. The one rule for every `cpu` a caller passes."""
    wanted = next((tag for tag in tags if cpu.strip() in (tag, tag.lstrip(":"))), "")
    if not wanted:
        raise st.Invalid("unknown_ref",
                         f"no cpu {cpu!r} on this machine; it has "
                         f"{tags or 'none this gather recognised'}", cpus=tags)
    return wanted


def named(ses: gs.Session, cpu: str) -> str:
    """The absolute tag of the cpu a call names: judged against the inventory `start`
    gathered, or the debugger's own `cpulist` when the gather saw none."""
    tags = [row["tag"] for row in (STATE.machine_map or {}).get("cpus", [])]
    return match_tag(cpu, tags or cpu_list(ses))


def acting(ses: gs.Session, cpu: str) -> str:
    """`chosen`, or the refusal when the call names no cpu and `cpulist` marks none visible: a
    call that acts on one cpu has none to act on then, and guessing would act on the wrong one."""
    on = chosen(ses, cpu)
    if on is None:
        raise st.Invalid("unexpected_answer",
                         "`cpulist` marked no cpu visible, so a call naming no cpu has none to "
                         "act on: name one with `cpu`")
    return on


def chosen(ses: gs.Session, cpu: str) -> str | None:
    """The cpu a call acts on: the one it names, judged against the machine's, else the
    visible one, read now (None when `cpulist` marks none)."""
    return named(ses, cpu) if inputs.cpu_given(cpu) else visible_cpu(ses)


def _flag_listing(ses: gs.Session, command: str, listing: str, empty: str) -> list[str] | None:
    """The devices a debugger flag's listing names, off `command` with no argument, which only
    lists: the sentence `listing` followed by each tag quoted, comma-separated, or `empty` for
    none (`execute_ignore`, `execute_suspend`, captured). None when the console answered
    neither shape. An annotation, like the visible cpu: a console that fails here leaves it
    unknown and the reply's own reading stands."""
    try:
        # ONE LOGICAL LINE, which MAME's console wraps at its column: a board with enough cpus
        # flagged answers it in pieces, rebuilt before it is read.
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
    """The cpus the debugger ignores, off its own `ignore` with no argument, which runs
    nothing, or None when the console answered neither shape. A breakpoint or a watchpoint on
    an ignored cpu has no effect (`help ignore`)."""
    return _flag_listing(ses, "ignore", "Currently ignoring device",
                    "Not currently ignoring any devices")


def suspended(ses: gs.Session) -> list[str] | None:
    """The cpus the debugger's own `suspend` holds, off `suspend` with no argument, which only
    lists, or None when the console answered neither shape."""
    return _flag_listing(ses, "suspend", "Currently suspended device",
                    "No currently suspended devices")


def ignored_note(ses: gs.Session, cpu: str | None) -> str | None:
    """The note for a row armed on a cpu the debugger ignores, which the row cannot stop or
    count on until that cpu is observed again (`st.add_note` adds it to the reply); None for any
    other cpu, or when the ignored set could not be read."""
    if cpu is None or cpu not in (ignored(ses) or []):
        return None
    return f"the debugger ignores {cpu}, so this row has no effect until `debug(\"observe {cpu}\")`"


#: The cache key of every cpu's register names, as the boot gather read them off its state
#: entries (the names its console symbol table takes): a condition is judged against the cpu it
#: is armed on, never against the stub's first cpu. Not a section of `machine_map`'s reply.
CPU_REGISTERS = "cpu_registers"


def register_names(ses: gs.Session, cpu: str | None) -> list[str]:
    """The names `cpu`'s console knows as registers: the gather's for that cpu, else the stub's
    description of that cpu's thread, which is the first cpu's on a stub without threads or
    for no cpu named."""
    known = (STATE.machine_map or {}).get(CPU_REGISTERS, {})
    if cpu is not None and cpu in known:
        return list(known[cpu])
    return layout(ses, cpu).register_names


def cpu_type(cpu: str | None) -> str | None:
    """MAME's shortname for `cpu` (`m68000`), off the inventory `start` cached, or None: the word
    a disassembly picks its flow table by."""
    rows = STATE.machine_map.get("cpus", []) if STATE.machine_map else []
    return next((row.get("type") for row in rows if cpu is not None and row["tag"] == cpu), None)


def _space_row(cpu: str | None, space: str = mspace.PROGRAM) -> dict[str, Any] | None:
    """`cpu`'s `space` row as `start` gathered it, or None (no gather, no cpu named, a cpu
    without that space)."""
    rows = STATE.machine_map.get("spaces", []) if STATE.machine_map else []
    return next((row for row in rows if (row["cpu"], row["space"]) == (cpu, space)), None)


def program_mask(cpu: str | None) -> int | None:
    """The last address `cpu`'s program space reaches, or None when the inventory has no such
    row: a range is then the console's, since a mask taken from another cpu is the wrong one."""
    row = _space_row(cpu)
    return int(row["address_mask"], 16) if row is not None and "address_mask" in row else None


def bus_width(cpu: str | None, space: str = mspace.PROGRAM) -> int | None:
    """The bus width in bits of `cpu`'s `space` (`mame_space.SPACES`), or None when the
    inventory has no such row: MAME's `data_width` of that space."""
    row = _space_row(cpu, space)
    return (int(row["data_width_bits"]) if row is not None and "data_width_bits" in row
            else None)


def stub_cpu(ses: gs.Session) -> str | None:
    """The cpu the stub's register and memory packets serve: the tag the stub gives thread 1
    when it names its threads, else the first cpu `cpulist` lists, which is the one a stub
    without threads binds; None when neither says."""
    if ses.threads:
        return ses.threads.get(1)
    tags = cpu_list(ses)
    return tags[0] if tags else None
