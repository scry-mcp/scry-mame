"""Flow class of each listing line, read off the mnemonic.

`dasm` drops the disassemblers' `STEP_OVER`/`STEP_OUT` flags, so each table mirrors them
(`m68kdasm.cpp`, `necdasm.cpp`). Where MAME leaves a flow word unflagged the table decides: jumps
are branches, traps are calls. A word or a type with no table is `unknown`, never `sequential`.
"""

from __future__ import annotations

import re

SEQUENTIAL, CALL, BRANCH, RETURN, UNKNOWN = "sequential", "call", "branch", "return", "unknown"

# No `bt`/`bf` (those encodings are `bra`/`bsr`); `dbf` prints as `dbra`.
_M68K_CC = ("hi", "ls", "cc", "cs", "ne", "eq", "vc", "vs", "pl", "mi", "ge", "lt", "gt", "le")

# 68020+ words (`rtd`, `movec`) print `dc.w ...; ILLEGAL`: `unknown`.
_M68000: dict[str, str] = {
    **dict.fromkeys(
        ("abcd", "add", "adda", "addi", "addq", "addx", "and", "andi", "asl", "asr", "bchg",
         "bclr", "bset", "btst", "clr", "cmp", "cmpa", "cmpi", "cmpm", "divs", "divu", "eor",
         "eori", "exg", "ext", "lea", "link", "lsl", "lsr", "move", "movea", "movem", "movep",
         "moveq", "muls", "mulu", "nbcd", "neg", "negx", "nop", "not", "or", "ori", "pea",
         "reset", "rol", "ror", "roxl", "roxr", "sbcd", "stop", "sub", "suba", "subi", "subq",
         "subx", "swap", "tas", "tst", "unlk", "st", "sf", *(f"s{cc}" for cc in _M68K_CC)),
        SEQUENTIAL),
    **dict.fromkeys(("bra", "jmp", "dbra", "dbt", *(f"b{cc}" for cc in _M68K_CC),
                     *(f"db{cc}" for cc in _M68K_CC)), BRANCH),
    **dict.fromkeys(("jsr", "bsr", "trap", "trapv", "chk"), CALL),
    **dict.fromkeys(("rts", "rte", "rtr"), RETURN),
}

# Both syntaxes (8080 mnemonics in emulation mode). Absent on purpose (`unknown`): V25-only
# words (`brkn`, `brks`), `fpo2` and the x87 words.
_V30: dict[str, str] = {
    **dict.fromkeys(
        ("add", "add4s", "addc", "adj4a", "adj4s", "adjba", "adjbs", "and", "clr1", "cmp",
         "cmp4s", "cmpbkb", "cmpbkw", "cmpmb", "cmpmw", "cvtbd", "cvtbw", "cvtdb", "cvtwl",
         "dec", "di", "dispose", "div", "divu", "ei", "ext", "halt", "in", "inc", "inmb",
         "inmw", "ins", "ldea", "ldmb", "ldmw", "mov", "movbkb", "movbkw", "mul", "mulu", "neg",
         "nop", "not", "not1", "or", "out", "outmb", "outmw", "poll", "pop", "prepare", "push",
         "rol", "rol4", "rolc", "ror", "ror4", "rorc", "set1", "shl", "shr", "shra", "stmb",
         "stmw", "sub", "sub4s", "subc", "test", "test1", "trans", "xch", "xor",
         "aci", "adc", "adi", "ana", "ani", "cma", "cmc", "cpi", "daa", "dad", "dcr", "dcx",
         "hlt", "inr", "inx", "ldax", "lhld", "lxi", "mvi", "ora", "ori", "ral", "rar", "rlc",
         "rrc", "sbb", "sbi", "shld", "shlx", "sphl", "stax", "stc", "sui", "xchg", "xra", "xri",
         "xthl"),
        SEQUENTIAL),
    **dict.fromkeys(
        ("bv", "bnv", "bc", "bnc", "be", "bne", "bnh", "bh", "bn", "bp", "bpe", "bpo", "blt",
         "bge", "ble", "bgt", "dbnz", "dbnze", "dbnzne", "bcwz", "br",
         "jc", "jnc", "jnz", "jz", "jp", "jm", "jpe", "jpo", "jmp", "pchl"), BRANCH),
    **dict.fromkeys(("call", "brk", "brkv", "chkind", "calln", "rst", "cc", "cnc", "cz", "cnz",
                     "cp", "cm", "cpe", "cpo"), CALL),
    **dict.fromkeys(("ret", "retf", "reti", "retem", "rc", "rnc", "rz", "rnz", "rp", "rm",
                     "rpe", "rpo"), RETURN),
}

# A prefix prints ahead of its instruction (`repne   cmpbkb`); classify the next word.
_V30_PREFIXES = frozenset(("rep", "repne", "repc", "repnc", "buslock"))

TABLES: dict[str, tuple[dict[str, str], frozenset[str]]] = {
    "m68000": (_M68000, frozenset()),
    "v30": (_V30, _V30_PREFIXES),
}

# A `dasm` line without opcode bytes: `<addr>: <instruction>`.
_LINE = re.compile(r"^([0-9A-Fa-f]+): (.*)$")


def without_comment(line: str) -> str:
    """A `dasm` line cut at the first ` // `: the comment text can look like an operand."""
    return line.split(" // ", 1)[0]


def source(cpu_type: str | None) -> str | None:
    """The `flow_source` for this type, or None when no table covers it."""
    return f"mnemonic_table:{cpu_type}" if cpu_type in TABLES else None


def classify(instruction: str, cpu_type: str) -> str:
    """The flow class of one instruction's text, off `cpu_type`'s table."""
    table, prefixes = TABLES[cpu_type]
    words = instruction.lower().split()
    while words and words[0] in prefixes:
        words.pop(0)
    if not words:
        return UNKNOWN
    # `move.w` -> `move`; `dc.w` is the illegal word and stays unknown.
    mnemonic = words[0].split(".")[0] if cpu_type == "m68000" and words[0] != "dc.w" else words[0]
    return table.get(mnemonic, UNKNOWN)


def classify_listing(bare: list[str], addresses: list[str], cpu_type: str) -> list[str] | None:
    """The class of each line of `bare` (no opcode bytes), or None if it misaligns `addresses`."""
    if len(bare) != len(addresses):
        return None
    flows: list[str] = []
    for line, addr in zip(bare, addresses, strict=True):
        m = _LINE.match(line)
        if m is None or m.group(1).lower() != addr.lower():
            return None
        flows.append(classify(without_comment(m.group(2)), cpu_type))
    return flows
