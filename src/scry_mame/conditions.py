"""A condition in the console's grammar: refusals, symbol substitution, pre-arm evaluation."""

from __future__ import annotations

import re
from typing import Any, Literal, NamedTuple, assert_never

from scry_mame import cpus, lexer
from scry_mame import declarations as dec
from scry_mame import gdb_session as gs
from scry_mame import state as st
from scry_mame.state import STATE

# The console knows MAME's symbols and none of the project's, so table words become addresses.
# Whole words only: `0x25`, `$beef` and the size before `@` (`w@`) are not names.
_SYMBOL_WORD = re.compile(r"(?<![0-9A-Za-z_$])[A-Za-z_][A-Za-z0-9_]*(?![A-Za-z0-9_@])")


# A condition reaches the console outside `debug`'s classifier and is evaluated at every hit,
# so assignments and `;{}` (a new statement or action) are refused.
CONDITION_WRITES = re.compile(lexer.ASSIGNS + r"|[;{}]")


#: The rule `expression_fault` names.
ExpressionRule = Literal["empty", "split", "writes"]


def expression_fault(text: str) -> tuple[ExpressionRule, str] | None:
    """Which rule a console expression breaks, and what broke it, or None."""
    stripped = text.strip()
    if not stripped:
        return ("empty", "")
    if "\n" in stripped or "," in stripped:
        return ("split", "\n" if "\n" in stripped else ",")
    if (hit := CONDITION_WRITES.search(stripped)) is not None:
        return ("writes", hit.group(0))
    return None


# A project symbol spelled like one of these would turn `pc==0x400` into a constant comparison.
_CONSOLE_NAMES = frozenset({"pc", "curpc", "frame", "totalcycles", "cycles",
                            "lastinstructioncycles", "cpunum", "beamx", "beamy", "wpaddr",
                            "wpdata", "wpsize", "abs", "bit", "if", "max", "min", "s8", "s16",
                            "s32", *(f"temp{i}" for i in range(lexer.TEMPS))})
_CONSOLE_NUMBERED = re.compile(r"(?:beamx|beamy|frame)\d+")


def is_console_name(name: str) -> bool:
    """Whether the console already knows `name` as one of its own symbols."""
    low = name.lower()
    return low in _CONSOLE_NAMES or _CONSOLE_NUMBERED.fullmatch(low) is not None


def console_condition(condition: str, cpu: str | None = None) -> str:
    """`condition` as the console reads it: stripped, `cpu`'s symbols replaced by `0x<addr>`.
    Refuses what `check_condition` refuses and a symbol spelled like a register or console name."""
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
    """The console's words when it cannot evaluate `condition`, or None.

    MAME arms a condition its evaluator refuses (`rpset {d1==}`); the braces stop an assignment."""
    answer = ses.monitor(evaluate_command(condition)).strip()
    return None if _ONE_NUMBER.fullmatch(answer) else " ".join(answer.split())


def evaluate_command(condition: str) -> str:
    return f"print {{{condition}}}"


def check_condition_fits(ses: gs.Session, arm: str, condition: str) -> None:
    """Both commands a condition goes out in, the LONGER first so the refusal names it."""
    for command in sorted((arm, evaluate_command(condition)), key=len, reverse=True):
        ses.console_packet(command)


class ConditionVerdict(NamedTuple):
    """What `judged_condition` found; `left_visible` never replaces `refusal`."""

    refusal: str | None
    left_visible: str | None


def judged_condition(ses: gs.Session, arm: str, condition: str,
                     cpu: str | None = None) -> ConditionVerdict:
    """The condition put to the console's evaluator once both commands fit a packet.

    `print` reads the VISIBLE cpu's symbols while `bp` and `wp` parse in the named cpu's, so
    the row's cpu is made visible for the evaluation and put back."""
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
    """Refuse a declaration whose visible cpu could not be put back."""
    if judged.left_visible is None:
        return
    found = ("evaluates" if judged.refusal is None
             else f"does not evaluate ({judged.refusal})")
    raise st.Invalid("unexpected_answer",
        f"`{condition}` {found} on {cpu}, and then {judged.left_visible}; nothing is stored: "
        "`focus` the cpu you want visible, then declare it again", visible_cpu=cpu)


def condition_fields(reply: dict[str, Any], typed: str, cond: str) -> None:
    """`condition` as the console reads it, and `condition_typed` only when it differs."""
    reply["condition"] = cond
    if typed != cond:
        reply["condition_typed"] = typed


def typed_condition(item: dict[str, Any], decl: dec.Declaration) -> None:
    """A listed declaration's condition fields; as typed alone when the table refuses a name."""
    try:
        condition_fields(item, decl.condition, console_condition(decl.condition, decl.cpu))
    except st.Invalid:
        item["condition"] = decl.condition


def check_condition(condition: str) -> str:
    """The machine-independent half of a condition check; returns the stripped text."""
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


def refused_on_rearm(refusal: str | None, cond: str, kind: str, owner: dec.Owner,
                     name: dict[str, Any], out: dict[str, list[Any]]) -> bool:
    """A condition the console would not evaluate, sorted for the re-arm report; True if sorted."""
    if refusal is None:
        return False
    if "unknown symbol" in refusal:
        STATE.conditions_unresolved.add((kind, owner))
        out["unresolved"].append(name)
    else:
        out["unarmable"].append({**name, "why": f"the debugger did not evaluate `{cond}`: "
                                                f"{refusal}"})
    return True
