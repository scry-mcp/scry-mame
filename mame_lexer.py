"""HOW THE CONSOLE READS A LINE'S WORDS, beneath its grammar (`mame_console`): where a quoted
string ends, what counts as an assignment, and which debugger temps a line writes. `debug`'s
classifier and the console's splitter read a line through these, and a condition's refusal
takes its assignment grammar from here, so a line never gets two answers about what it writes.
"""

from __future__ import annotations

import re

# WHAT THE CONSOLE COUNTS AS AN ASSIGNMENT, as an unanchored alternation: an `=` that is not
# half of a comparison (`==`, `!=`, `<=`, `>=`), the two shift-assignments that lookbehind
# would otherwise exclude with them (`<<=`, `>>=`), `++` or `--`. The console's parser executes
# any of them inside an expression. ONE DECISION WITH TWO CONSUMERS, a condition's refusal
# (`mame_conditions`) and `debug`'s classifier (`mame_console`), so it lives beneath both and a
# change to the grammar moves both.
ASSIGNS = r"(?<![=!<>])=(?!=)|<<=|>>=|\+\+|--"


# THE DEBUGGER'S TEMP VARIABLES, `temp0` to `temp9`. Ten is MAME's number, not a choice made
# here.
TEMPS = 10


# AN ASSIGNMENT WHOSE TARGET IS A TEMP, in each of the console's forms (`tempN=`, a compound
# `tempN+=`, `++tempN`, `tempN++`): the temps belong to the debugger, not to the guest, so a
# line that writes only them leaves the machine as it was. The target is a whole word, so
# `temp0=w@100=1` loses only its `temp0=` and the chained write to memory still counts.
_TEMP = r"temp(" + "|".join(str(i) for i in range(TEMPS)) + r")(?![0-9A-Za-z_])"
_TEMP_WRITE = re.compile(r"(?<![0-9A-Za-z_])" + _TEMP
                         + r"\s*(?:\+\+|--|(?:<<|>>|[-+*/%&|^])?=(?!=))"
                         + r"|(?:\+\+|--)\s*" + _TEMP, re.I)


# A TEMP AFTER A SIZE'S `@` IS AN ADDRESS (`w@temp1=3` writes memory), spaces allowed.
_AT_BEFORE = re.compile(r"@\s*$")
_STEPS = re.compile(r"\+\+|--")


def blank_quoted(text: str) -> str:
    """`text` with the inside of every double-quoted string turned to spaces, the quotes and
    every offset kept. MAME's console rule (`debugcon.cpp`): a `"` whose previous character is
    a backslash does not close the string, and a string left open runs to the end of the line.
    THE ONE READING OF A STRING: the console's splitter, its expression test, the write
    classifier and the temps read here all walk what this leaves, so a line never gets two
    answers about where its string ends."""
    out, quoted = list(text), False
    for i, c in enumerate(text):
        if quoted:
            quoted = not (c == '"' and text[i - 1] != "\\")
            if quoted:
                out[i] = " "
        elif c == '"':
            quoted = True
    return "".join(out)


def without_temp_writes(text: str) -> str:
    """`text` with every assignment to a debugger temp taken out, so what is left writes the
    guest only if something in it still assigns. `debug`'s classifier reads a line through
    this; A BREAKPOINT CONDITION DOES NOT, on purpose: the controls own the temps, and a
    condition that wrote one would change a control's count at every hit."""
    def drop(m: re.Match[str]) -> str:
        return m.group(0) if _AT_BEFORE.search(text, 0, m.start()) else " "

    return _TEMP_WRITE.sub(drop, text)


def temps_assigned(text: str) -> set[int]:
    """The numbers of the debugger temps `text` assigns, by the match `without_temp_writes`
    takes out, read on the text outside quoted strings (`printf "temp3=%d",temp3` only reads).
    After a size's `@` the temp is the address, and only a step (`w@temp3++=1`) moves it."""
    text = blank_quoted(text)
    return {int(m.group(1) or m.group(2)) for m in _TEMP_WRITE.finditer(text)
            if not _AT_BEFORE.search(text, 0, m.start()) or _STEPS.search(m.group(0))}
