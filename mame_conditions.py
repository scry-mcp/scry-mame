"""A CONDITION IN THE CONSOLE'S GRAMMAR, as a breakpoint, a change watch, a registerpoint or a run
takes one: what it may not contain (an assignment, a statement), how a name in it becomes the
console's (a symbol resolved here, a console variable kept), whether the console evaluates it
on the row's cpu before anything is armed, and the fields a reply says it with.
"""

from __future__ import annotations

import re
from typing import Any, Literal, NamedTuple, assert_never

import gdb_session as gs
import mame_cpus as cpus
import mame_declarations as dec
import mame_lexer as lexer
import mame_state as st
from mame_state import STATE

# A NAME IN A CONDITION: the console's expression parser knows MAME's own symbols and none of
# the project's, so every word of the table is replaced by its address before the condition
# reaches it, which needs no channel of its own. A word is matched whole, not
# inside a number or another word, so `0x25` and `$beef` stay as they are, and never the SIZE
# before an `@` (`w@`, `b@`, `d@`, `q@`), which is the console's own syntax and not a name.
_SYMBOL_WORD = re.compile(r"(?<![0-9A-Za-z_$])[A-Za-z_][A-Za-z0-9_]*(?![A-Za-z0-9_@])")


# A CONDITION READS AND NEVER WRITES: a condition reaches the console outside `debug`'s
# classifier, on a path whose reply says the session is not altered, and it is evaluated at
# every hit. So an assignment is refused here, and so is `;`, `{` or `}`, which would start
# another statement or an action.
CONDITION_WRITES = re.compile(lexer.ASSIGNS + r"|[;{}]")


#: The rule a console expression breaks, as `expression_fault` names it.
ExpressionRule = Literal["empty", "split", "writes"]


def expression_fault(text: str) -> tuple[ExpressionRule, str] | None:
    """Which rule a console expression breaks, and what broke it, or None: `empty`, `split` for a
    comma or a newline (the console splits the line there), or `writes` with what the console
    would EXECUTE at every evaluation. The rules are the console's; each caller says
    them in its own sentence, because a condition and an expr watch are refused for different
    consequences."""
    stripped = text.strip()
    if not stripped:
        return ("empty", "")
    if "\n" in stripped or "," in stripped:
        return ("split", "\n" if "\n" in stripped else ",")
    if (hit := CONDITION_WRITES.search(stripped)) is not None:
        return ("writes", hit.group(0))
    return None


# THE CONSOLE'S OWN NAMES a condition may use: a project symbol spelled like one of them is
# ambiguous, and substituting it would turn `pc==0x400` into a comparison of two constants.
# Read off the debugger's global symbol table (`debugcpu.cpp`, `debugcmd.cpp`, `points.cpp`):
# its variables, its functions, and each screen's own counter on a board with several.
_CONSOLE_NAMES = frozenset({"pc", "curpc", "frame", "totalcycles", "cycles",
                            "lastinstructioncycles", "cpunum", "beamx", "beamy", "wpaddr",
                            "wpdata", "wpsize", "abs", "bit", "if", "max", "min", "s8", "s16",
                            "s32", *(f"temp{i}" for i in range(lexer.TEMPS))})
_CONSOLE_NUMBERED = re.compile(r"(?:beamx|beamy|frame)\d+")


def is_console_name(name: str) -> bool:
    """Whether the console already knows `name` (case aside) as one of its own symbols."""
    low = name.lower()
    return low in _CONSOLE_NAMES or _CONSOLE_NUMBERED.fullmatch(low) is not None


def console_condition(condition: str, cpu: str | None = None) -> str:
    """`condition` as the console will read it: stripped, every symbol of `cpu`'s table (the cpu
    the row is armed on, the first cpu's when None) replaced by `0x<addr>`. Refused: an empty
    condition (`bp addr,` arms nothing a caller meant), a comma or a newline (the start of an
    ACTION), an assignment or a step (a write at every evaluation), and a symbol spelled like a
    register of that cpu or like a console variable (ambiguous)."""
    text = check_condition(condition)
    registers = {r.lower() for r in (cpus.register_names(STATE.ses, cpu) if STATE.ses else [])}
    symbols = STATE.table(cpu).table

    def word(m: re.Match[str]) -> str:
        name = m.group(0)
        addr = symbols.get(name.upper())
        if addr is None:
            return name
        if name.lower() in registers or is_console_name(name):
            raise st.Invalid("ambiguous_ref",
                f"{name!r} is both a symbol of the table and a name the console knows: "
                "write its address instead, which `symbols_find(name=...)` answers")
        return f"0x{addr:x}"

    return _SYMBOL_WORD.sub(word, text)


_ONE_NUMBER = re.compile(r"^[0-9A-Fa-f]+$")


def not_evaluated(ses: gs.Session, condition: str) -> str | None:
    """The console's own words when it cannot evaluate `condition`, or None when it can.
    MAME ARMS a condition its evaluator refuses (`rpset {d1==}`, captured), on a breakpoint
    as on a registerpoint, so the text is put to the evaluator before it is armed. The
    braces are the console's: bare, it reads the condition as an assignment."""
    answer = ses.monitor(evaluate_command(condition)).strip()
    return None if _ONE_NUMBER.fullmatch(answer) else " ".join(answer.split())


def evaluate_command(condition: str) -> str:
    return f"print {{{condition}}}"


def check_condition_fits(ses: gs.Session, arm: str, condition: str) -> None:
    """Both commands a declared condition goes out in, `arm` (the row's own `bp` or `wp`) and
    its evaluation, judged against the stub's packet before either is sent, the LONGER first so
    the refusal names the one that decides."""
    for command in sorted((arm, evaluate_command(condition)), key=len, reverse=True):
        ses.console_packet(command)


class ConditionVerdict(NamedTuple):
    """What `judged_condition` found: the console's own words when it cannot evaluate the
    condition (None when it can), and the note naming the cpu left visible when the visible one
    could not be put back (None when it was, or never moved). The second never replaces the
    first: the evaluation had completed."""

    refusal: str | None
    left_visible: str | None


def judged_condition(ses: gs.Session, arm: str, condition: str,
                     cpu: str | None = None) -> ConditionVerdict:
    """The condition put to the console's evaluator once both commands it goes out in fit a
    packet (a `CommandTooLong` raises): what every conditioned row, a breakpoint's or a change
    watch's, is put through before it is armed.

    EVALUATED ON THE CPU THE ROW IS ARMED ON. `print` reads the VISIBLE cpu's symbols while `bp`
    and `wp` parse their condition in the named cpu's (src/emu/debug/debugcmd.cpp), so on a
    board of two cpus a register of the one would be judged by the other: `hl` refused under a
    68000, `d0` taken as the constant 0xd0 under a Z80. The row's cpu is made visible through
    the stub for the evaluation and the visible one put back (`mame_cpus.on_cpus`), which runs
    nothing; a build that cannot show a cpu without running refuses, naming `focus`."""
    check_condition_fits(ses, arm, condition)
    visible = cpus.visible_cpu(ses)
    if cpu is None or visible is None or cpus.same_cpu(cpu, visible):
        return ConditionVerdict(not_evaluated(ses, condition), None)
    words: list[str | None] = []

    def evaluate(_item: None, refusal: st.Invalid | None) -> None:
        if refusal is not None:
            raise refusal
        words.append(not_evaluated(ses, condition))

    needs = (f"the condition of a row on {cpu} is evaluated against the visible cpu, {visible}; "
             f"`focus(cpu={cpu!r})` first")
    put_back = cpus.on_cpus(ses, visible, {cpu: [None]}, needs, evaluate)
    return ConditionVerdict(words[0], put_back)


def refuse_if_left_visible(judged: ConditionVerdict, condition: str, cpu: str | None) -> None:
    """A declaration on `cpu` whose condition was judged and whose visible cpu could not be put
    back is refused there, before anything is stored, carrying what the evaluation found and
    naming the cpu left visible (`visible_cpu`): `cpu`, the one shown for the evaluation."""
    if judged.left_visible is None:
        return
    found = ("evaluates" if judged.refusal is None
             else f"does not evaluate ({judged.refusal})")
    raise st.Invalid("unexpected_answer",
        f"`{condition}` {found} on {cpu}, and then {judged.left_visible}; nothing is stored: "
        "`focus` the cpu you want visible, then declare it again", visible_cpu=cpu)


def condition_fields(reply: dict[str, Any], typed: str, cond: str) -> None:
    """`condition` as the console reads it now, and `condition_typed` only when the caller
    typed something else, which is when there is anything to recognise."""
    reply["condition"] = cond
    if typed != cond:
        reply["condition_typed"] = typed


def typed_condition(item: dict[str, Any], decl: dec.Declaration) -> None:
    """A listed declaration's condition fields, as its arming reply gave them; as typed alone
    when this build's table refuses a name in it."""
    try:
        condition_fields(item, decl.condition, console_condition(decl.condition, decl.cpu))
    except st.Invalid:
        item["condition"] = decl.condition


def check_condition(condition: str) -> str:
    """A console condition's machine-independent half, and the stripped text it judged. The rule
    it does NOT apply is the last one: whether a word in the condition collides with a register
    name, which is a question about THIS cpu and has no answer without one."""
    text = condition.strip()
    fault = expression_fault(text)
    if fault is None:
        return text
    rule, hit = fault
    if rule == "empty":
        raise st.Invalid("bad_argument", "condition is empty: nothing for the console to judge. "
                                         "`breakpoint_at`, `run_to` and `regpoint_add` take an "
                                         "expression in the debugger's own grammar (`d0==1`, "
                                         "`w@DemoLen==0x25`)")
    if rule == "split":
        raise st.Invalid("bad_argument",
            f"condition={condition!r} holds a comma or a newline, which the console reads as "
            "the end of the condition and the start of an ACTION: a declaration carries a "
            "condition alone, and an action is typed through `debug` "
            "(`bp <address>,<condition>,{ <action> }`)")
    if rule == "writes":
        raise st.Invalid("bad_argument",
            f"condition={condition!r} holds {hit!r}, which the console EXECUTES at every "
            "evaluation: a condition compares (`==`, `!=`, `<`, `>=`) and never assigns; a "
            "command that writes goes through `debug`")
    assert_never(rule)
