"""Section S of the live matrix: boards with more than one cpu, on a build whose gdbstub serves a
thread per cpu (`MAME_MULTICPU_BINARY`). victory is a Z80 and a 6502, two different register
files; hardhat is two 6502s; topgunnr is a 68000 beside two cpus that stub has no description
of, so its second cpu's registers are refused. Each board's threads and descriptions are read
first; then the calls that name the SECOND cpu (`cpu=`) are made with the FIRST one visible, so
a server that ignored `cpu=` would answer for the wrong cpu, and judged against MAME's own
reading of the second: its console made to look at it (`console_pc`), its Lua, or the stop a
breakpoint on it ends in.

`live_matrix.py` registers this section; run alone, it is the same machinery over it only:

    MAME_MULTICPU_BINARY=... MAME_TEST_ROMS=... uv run python tests/live/matrix_multicpu.py
"""

from __future__ import annotations

from collections.abc import Callable

from live_harness import (
    MULTICPU_BINARY,
    Board,
    blocked,
    boards_cover,
    call,
    cell,
    console_pc,
    free_boot,
    make_visible,
    multicpu_missing,
    ok,
    pc_of,
    refused,
    registers_at_a_telling_pc,
    run_boards,
    run_sections,
    said,
    section,
    tells_byte_order,
    zips_missing,
)

from mame_state import STATE  # isort: skip -- found through the path the harness sets

S_TITLE = "a second cpu named by cpu=, on the build that serves a thread per cpu"
# The second cpu of victory and of hardhat, both on Exidy's sound board.
SOUNDBD = ":soundbd:audiocpu"
TOPGUNNR_AUDIO, TOPGUNNR_MOTOR = ":440audio:audiocpu", ":motorcpu"
S_CELLS = [
    "victory: a thread per cpu, the Z80's and the 6502's, each described as its own "
    "architecture and register file, MAME declaring both little-endian",
    "victory: step(cpu=soundbd:audiocpu) with the Z80 visible steps the 6502: its new pc, as "
    "the console says and as its own thread reads it, is not the one it left",
    "victory: registers(cpu=soundbd:audiocpu) reads the 6502's PC as the console's print curpc "
    "for it at the same stop",
    "victory: read_memory(cpu=soundbd:audiocpu) at the 6502's PC reads what MAME's Lua reads in "
    "that cpu's program space",
    "victory: breakpoint_at(cpu=soundbd:audiocpu) where the 6502 idles stops the machine there, "
    "the stop naming that cpu at that pc",
    "hardhat: a thread per 6502, each described as m6502, MAME declaring both little-endian",
    "hardhat: registers(cpu=soundbd:audiocpu) reads the second 6502's PC as the console's print "
    "curpc for it at the same stop, a PC the first 6502 does not hold",
    "topgunnr: three threads, the 68000 described as m68k and the mc6809 and the 68705 refused "
    "a description by the stub (it has no map for either)",
    "topgunnr: registers(cpu=440audio:audiocpu) is no_channel, quoting the stub's refusal of "
    "the mc6809's description",
]


def _described(threads: dict[int, str]) -> dict[str, tuple[str, int] | str]:
    """Each thread's cpu, the architecture its description declares and the bits its `g` reply
    takes: that cpu's registers and the state the stub appends of the board's other devices,
    which is why one cpu type sums differently on two boards. Or the refusal."""
    assert STATE.ses is not None
    out: dict[str, tuple[str, int] | str] = {}
    for tid, tag in threads.items():
        try:
            lay = STATE.ses.layout(tid)
            out[tag] = (lay.arch, sum(lay.register_bits.values()) + 4 * lay.other_digits)
        except Exception as e:  # noqa: BLE001 -- the refusal is what the cell reads
            out[tag] = f"refused: {e}"
    return out


def _registers_cell(label: str, cpu: str, first: str) -> int | None:
    """`registers` of `cpu` at a stop whose PC tells the byte order, against the console's
    `print curpc` for it, read again with `first` visible so a server that ignored `cpu=` would
    answer `first`'s PC, which must differ. BLOCKED when no stop tells, or when the two cpus
    hold one PC and cannot be told apart. Returns the PC it judged."""
    regs = registers_at_a_telling_pc(cpu)
    pc = pc_of(regs)
    if ok(regs) and not tells_byte_order(pc):
        blocked(label, f"no stop of {cpu} whose PC tells the byte order: {pc}")
        return None
    console = console_pc(cpu)
    shown = make_visible(first)
    again = pc_of(call("registers", cpu=cpu))
    other = pc_of(call("registers", cpu=first))
    held = (ok(regs) and shown and pc is not None and console is not None
            and int(pc, 16) == console and again == pc and other is not None)
    if held and other == pc:
        blocked(label, f"{cpu} and {first} both hold {pc}: no reading can tell them apart")
        return None
    cell(label, held,
         f"registers pc {pc} (again with {first} visible: {again}), print curpc {console}, "
         f"{first} at {other}")
    return int(pc, 16) if ok(regs) and pc else None


def _s_victory(t: list[str]) -> None:
    free_boot("victory", ["vic3.j2"], "0x0", binary=MULTICPU_BINARY)
    assert STATE.ses is not None
    threads, endian = dict(STATE.ses.threads), dict(STATE.ses.endianness)
    seen = _described(threads)
    cell(t[0], threads == {1: ":maincpu", 2: SOUNDBD}
         and seen == {":maincpu": ("z80", 280), SOUNDBD: ("m6502", 320)}
         and endian == {1: "little", 2: "little"}, f"{threads} {seen} {endian}")
    pc = _registers_cell(t[2], SOUNDBD, ":maincpu")
    if pc is None:
        blocked(t[3], "no PC of the 6502 was judged")
        blocked(t[1], "no PC of the 6502 was judged")
    else:
        shown = make_visible(":maincpu")
        read = call("read_memory", ref=f"{pc:#x}", length=4, cpu=SOUNDBD)
        lua = str(call("lua", read_only=True, script=(
            f'local s = manager.machine.devices["{SOUNDBD}"].spaces["program"] '
            f'print(string.format("%02x%02x%02x%02x", s:read_u8({pc}), s:read_u8({pc}+1), '
            f's:read_u8({pc}+2), s:read_u8({pc}+3)))')).get("output", "")).strip()
        got = str(read.get("hex", "")).replace(" ", "").lower()
        cell(t[3], shown and ok(read) and len(got) == 8 and got == lua,
             f"{said(read, 80)} / lua {lua}")
        shown = make_visible(":maincpu")
        stepped = call("step", cpu=SOUNDBD)
        after = pc_of(call("registers", cpu=SOUNDBD))
        cell(t[1], shown and ok(stepped) and stepped.get("cpu") == SOUNDBD and after is not None
             and int(str(stepped.get("pc")), 16) == int(after, 16) and int(after, 16) != pc,
             f"step on {stepped.get('cpu')} from {pc:#x}: console {stepped.get('pc')}, "
             f"stub {after}")
    _s_victory_breakpoint(t[4])
    call("close")


def _s_victory_breakpoint(label: str) -> None:
    """A breakpoint on the 6502, armed with the Z80 visible, at the pc the 6502 holds after a
    stretch of running: its idle loop, which it comes back to. Judged on the stop the release
    ends in: that cpu, that pc, and named as that breakpoint's rather than an unattributed stop."""
    ran = call("run_for", frames=60, seconds=10.0)
    idle = pc_of(call("registers", cpu=SOUNDBD))
    if not ok(ran) or idle is None:
        cell(label, False, f"the run or the 6502's pc read after it failed: {said(ran, 100)}")
        return
    shown = make_visible(":maincpu")
    armed = call("breakpoint_at", ref=idle, by="address", cpu=SOUNDBD)
    hit = call("resume", seconds=10.0)
    cause = str(hit.get("cause", ""))
    cell(label, shown and ok(armed) and ok(hit) and hit.get("verdict") == "OTHER_STOP"
         and hit.get("cpu") == SOUNDBD and int(str(hit.get("pc")), 16) == int(idle, 16)
         and cause.startswith("breakpoint") and "no breakpoint" not in cause,
         f"armed at {idle}: {said(armed, 60)} / {said(hit, 120)}")
    cleared = call("breakpoint_clear", ref=idle, cpu=SOUNDBD)
    if not ok(cleared):
        cell(label, False, f"the breakpoint did not clear: {said(cleared)}")


def _s_hardhat(t: list[str]) -> None:
    """The pair of one architecture: two descriptions alike, so only the registers cell, read
    with the first 6502 visible and its own PC beside, tells the two cpus apart."""
    free_boot("hardhat", ["hhl-2.11a"], "0xa000", binary=MULTICPU_BINARY)
    assert STATE.ses is not None
    threads, endian = dict(STATE.ses.threads), dict(STATE.ses.endianness)
    seen = _described(threads)
    cell(t[5], threads == {1: ":maincpu", 2: SOUNDBD}
         and seen == {":maincpu": ("m6502", 136), SOUNDBD: ("m6502", 136)}
         and endian == {1: "little", 2: "little"}, f"{threads} {seen} {endian}")
    _registers_cell(t[6], SOUNDBD, ":maincpu")
    call("close")


def _s_topgunnr(t: list[str]) -> None:
    """A second cpu with no description: its registers are refused naming it, which is all a
    call on it can be judged by here."""
    free_boot("topgunnr", ["tgl-2.9r", "tgl-2.10r"], "0x804000", binary=MULTICPU_BINARY)
    assert STATE.ses is not None
    threads, endian = dict(STATE.ses.threads), dict(STATE.ses.endianness)
    seen = _described(threads)
    cell(t[7], threads == {1: ":maincpu", 2: TOPGUNNR_AUDIO, 3: TOPGUNNR_MOTOR}
         and isinstance(seen.get(":maincpu"), tuple) and seen[":maincpu"][0] == "m68k"
         and endian.get(1) == "big"
         and all(str(seen.get(c, "")).startswith("refused: ") and "E01" in str(seen.get(c))
                 for c in (TOPGUNNR_AUDIO, TOPGUNNR_MOTOR)), f"{threads} {seen} {endian}")
    regs = call("registers", cpu=TOPGUNNR_AUDIO)
    message = str(regs.get("message"))
    cell(t[8], refused(regs, "no_channel") and message.startswith(TOPGUNNR_AUDIO)
         and "target.xml" in message and "E01" in message, said(regs, 200))
    call("close")


def _missing(system: str) -> Callable[[], str]:
    return lambda: multicpu_missing() or zips_missing(system)


S_BOARDS = (Board(_s_victory, (0, 1, 2, 3, 4), _missing("victory")),
            Board(_s_hardhat, (5, 6), _missing("hardhat")),
            Board(_s_topgunnr, (7, 8), _missing("topgunnr")))
boards_cover("section S", S_CELLS, S_BOARDS)


def register_s() -> None:
    """Register section S with the matrix: after every section registered before it."""
    section("S", S_TITLE, S_CELLS)(lambda: run_boards(S_CELLS, S_BOARDS))


if __name__ == "__main__":
    register_s()
    run_sections("SECTION S")
