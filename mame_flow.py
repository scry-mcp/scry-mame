"""WHICH LINES OF A LISTING LEAVE THE FLOW: a call, a branch, a return, or the next instruction.

MAME KNOWS AND DOES NOT SAY. Every disassembler returns flags beside its text (`STEP_OVER`,
`STEP_OUT`, `STEP_COND` in `util::disasm_interface`), and the console's `dasm` reads them into a
local and drops them: the file it writes carries the text alone, and the Lua engine binds no
disassembler at all. `step` cannot lend its knowledge either, because a step over is the
console's own `over`, which reads those flags inside MAME and hands nothing back. So the class is
read here off the mnemonic, from a table per cpu TYPE (the device's shortname, which the boot
harness records beside each cpu), and `flow_source` says so on every reply.

EACH TABLE MIRRORS ITS DISASSEMBLER'S FLAGS, one source file each: `m68kdasm.cpp` and
`necdasm.cpp` under `src/devices/cpu/`, at the MAME the fleet pins. `STEP_OVER` is a call,
`STEP_OUT` a return, and a flow word MAME leaves unflagged is ours and said here: an
unconditional jump (`jmp`, `bra`, `br`, the 8080 mode's `jmp`, `jm` and `pchl`) is a branch,
because the reader following the flow leaves the line just the same. A trap goes to a handler that
returns, so it is a call the way MAME's `brk`, `chk` and `brkv` are, and the two it leaves
unflagged (the 68000's `trap`, the V30's `chkind`) are too.

A WORD NOT IN THE TABLE IS `unknown`, never `sequential`: the sequential set is the table's as
much as the flow words are, so a mnemonic nobody listed (an illegal word, a mode switch, an
instruction of a later model) is surfaced rather than read as the next line. And a TYPE without a
table answers `unknown` on every line, once, rather than borrowing the nearest family's.
"""

from __future__ import annotations

import re

SEQUENTIAL, CALL, BRANCH, RETURN, UNKNOWN = "sequential", "call", "branch", "return", "unknown"

# The 68000's condition codes as MAME's `m_cc` spells them. `t` and `f` never follow a `b`: those
# two encodings ARE `bra` and `bsr`, decoded apart, and `dbf` is printed `dbra`.
_M68K_CC = ("hi", "ls", "cc", "cs", "ne", "eq", "vc", "vs", "pl", "mi", "ge", "lt", "gt", "le")

# THE 68000 AS `m68kdasm.cpp` PRINTS IT, size suffix dropped (`move.w` reads `move`). What a
# 68000 does not execute (`rtd`, `movec`, `bkpt`, the 68020's bit fields) prints `dc.w ...;
# ILLEGAL` on this type and lands on `unknown` with the rest.
_M68000: dict[str, str] = {
    **dict.fromkeys(
        ("abcd", "add", "adda", "addi", "addq", "addx", "and", "andi", "asl", "asr", "bchg",
         "bclr", "bset", "btst", "clr", "cmp", "cmpa", "cmpi", "cmpm", "divs", "divu", "eor",
         "eori", "exg", "ext", "lea", "link", "lsl", "lsr", "move", "movea", "movem", "movep",
         "moveq", "muls", "mulu", "nbcd", "neg", "negx", "nop", "not", "or", "ori", "pea",
         "reset", "rol", "ror", "roxl", "roxr", "sbcd", "stop", "sub", "suba", "subi", "subq",
         "subx", "swap", "tas", "tst", "unlk", "st", "sf", *(f"s{cc}" for cc in _M68K_CC)),
        SEQUENTIAL),
    # `Bcc` and `DBcc` are `STEP_COND`; `bra` and `jmp` carry no flag.
    **dict.fromkeys(("bra", "jmp", "dbra", "dbt", *(f"b{cc}" for cc in _M68K_CC),
                     *(f"db{cc}" for cc in _M68K_CC)), BRANCH),
    # `STEP_OVER`: the two calls and the conditional traps `chk` and `trapv`; and `trap`, which
    # MAME leaves unflagged (the module's docstring).
    **dict.fromkeys(("jsr", "bsr", "trap", "trapv", "chk"), CALL),
    # `STEP_OUT`.
    **dict.fromkeys(("rts", "rte", "rtr"), RETURN),
}

# THE V30 AS `necdasm.cpp` PRINTS IT, BOTH OF ITS SYNTAXES. The disassembler switches to 8080
# mnemonics when the cpu is in its emulation mode, so a listing can carry either; every word the
# two sets share (`call`, `ret`, `mov`, `push`...) means the same in both, which is what lets one
# table hold them. Absent on purpose, and so `unknown`: the words the same file prints for a V30
# though only a V25 executes them (`brkn`, `brks`), `fpo2`, which its own comment says is for a
# coprocessor that was never made, and the x87 words it prints for an escape opcode, since no
# board this table was checked on carries the coprocessor.
_V30: dict[str, str] = {
    **dict.fromkeys(
        ("add", "add4s", "addc", "adj4a", "adj4s", "adjba", "adjbs", "and", "clr1", "cmp",
         "cmp4s", "cmpbkb", "cmpbkw", "cmpmb", "cmpmw", "cvtbd", "cvtbw", "cvtdb", "cvtwl",
         "dec", "di", "dispose", "div", "divu", "ei", "ext", "halt", "in", "inc", "inmb",
         "inmw", "ins", "ldea", "ldmb", "ldmw", "mov", "movbkb", "movbkw", "mul", "mulu", "neg",
         "nop", "not", "not1", "or", "out", "outmb", "outmw", "poll", "pop", "prepare", "push",
         "rol", "rol4", "rolc", "ror", "ror4", "rorc", "set1", "shl", "shr", "shra", "stmb",
         "stmw", "sub", "sub4s", "subc", "test", "test1", "trans", "xch", "xor",
         # The 8080 emulation mode's.
         "aci", "adc", "adi", "ana", "ani", "cma", "cmc", "cpi", "daa", "dad", "dcr", "dcx",
         "hlt", "inr", "inx", "ldax", "lhld", "lxi", "mvi", "ora", "ori", "ral", "rar", "rlc",
         "rrc", "sbb", "sbi", "shld", "shlx", "sphl", "stax", "stc", "sui", "xchg", "xra", "xri",
         "xthl"),
        SEQUENTIAL),
    # `STEP_COND`, and the unflagged unconditional jumps.
    **dict.fromkeys(
        ("bv", "bnv", "bc", "bnc", "be", "bne", "bnh", "bh", "bn", "bp", "bpe", "bpo", "blt",
         "bge", "ble", "bgt", "dbnz", "dbnze", "dbnzne", "bcwz", "br",
         "jc", "jnc", "jnz", "jz", "jp", "jm", "jpe", "jpo", "jmp", "pchl"), BRANCH),
    # `STEP_OVER`, conditional ones included, and `chkind` with them (the module's docstring).
    **dict.fromkeys(("call", "brk", "brkv", "chkind", "calln", "rst", "cc", "cnc", "cz", "cnz",
                     "cp", "cm", "cpe", "cpo"), CALL),
    # `STEP_OUT`, conditional ones included.
    **dict.fromkeys(("ret", "retf", "reti", "retem", "rc", "rnc", "rz", "rnz", "rp", "rm",
                     "rpe", "rpo"), RETURN),
}

# A PREFIX IS NOT THE INSTRUCTION: `necdasm` prints it as a word of its own ahead of the one it
# modifies (`repne   cmpbkb`), so the class is the next word's.
_V30_PREFIXES = frozenset(("rep", "repne", "repc", "repnc", "buslock"))

TABLES: dict[str, tuple[dict[str, str], frozenset[str]]] = {
    "m68000": (_M68000, frozenset()),
    "v30": (_V30, _V30_PREFIXES),
}

# One line of a `dasm` listing written WITHOUT its opcode bytes: `<addr>: <instruction>`.
_LINE = re.compile(r"^([0-9A-Fa-f]+): (.*)$")


def without_comment(line: str) -> str:
    """A `dasm` line without the comment MAME appends to it, ` // <text>` (`execute_dasm` in
    `src/emu/debug/debugcmd.cpp`), cut at the FIRST one, since the text may hold another: the
    only half a reader of mnemonics or operands may read, because a comment can say anything, an
    address in an operand's shape included."""
    return line.split(" // ", 1)[0]


def source(cpu_type: str | None) -> str | None:
    """The `flow_source` a listing on this type carries, or None when no table covers it."""
    return f"mnemonic_table:{cpu_type}" if cpu_type in TABLES else None


def classify(instruction: str, cpu_type: str) -> str:
    """The flow class of one instruction's text, off `cpu_type`'s table."""
    table, prefixes = TABLES[cpu_type]
    words = instruction.lower().split()
    while words and words[0] in prefixes:
        words.pop(0)
    if not words:
        return UNKNOWN
    # A size suffix is the 68000's (`move.w`); `dc.w` is its illegal word, and stays unknown.
    mnemonic = words[0].split(".")[0] if cpu_type == "m68000" and words[0] != "dc.w" else words[0]
    return table.get(mnemonic, UNKNOWN)


def classify_listing(bare: list[str], addresses: list[str], cpu_type: str) -> list[str] | None:
    """The class of every line of a listing, off the same range written without opcode bytes
    (`bare`), or None when the two listings do not describe the same instructions: each line
    of `bare` must start with the address of the line it classifies, or a class would land on
    the wrong line."""
    if len(bare) != len(addresses):
        return None
    flows: list[str] = []
    for line, addr in zip(bare, addresses, strict=True):
        m = _LINE.match(line)
        if m is None or m.group(1).lower() != addr.lower():
            return None
        flows.append(classify(without_comment(m.group(2)), cpu_type))
    return flows
