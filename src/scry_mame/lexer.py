from __future__ import annotations

import re

# One grammar for a condition's refusal and `debug`'s classifier.
ASSIGNS = r"(?<![=!<>])=(?!=)|<<=|>>=|\+\+|--"


TEMPS = 10


_TEMP = r"temp(" + "|".join(str(i) for i in range(TEMPS)) + r")(?![0-9A-Za-z_])"
_TEMP_WRITE = re.compile(r"(?<![0-9A-Za-z_])" + _TEMP
                         + r"\s*(?:\+\+|--|(?:<<|>>|[-+*/%&|^])?=(?!=))"
                         + r"|(?:\+\+|--)\s*" + _TEMP, re.I)


# After a size's `@` a temp is an address (`w@temp1=3`).
_AT_BEFORE = re.compile(r"@\s*$")
_STEPS = re.compile(r"\+\+|--")


def blank_quoted(text: str) -> str:
    """`text` with double-quoted strings blanked, offsets kept (MAME `debugcon.cpp` rules)."""
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
    """`text` with every assignment to a debugger temp taken out."""
    def drop(m: re.Match[str]) -> str:
        return m.group(0) if _AT_BEFORE.search(text, 0, m.start()) else " "

    return _TEMP_WRITE.sub(drop, text)


def temps_assigned(text: str) -> set[int]:
    """The numbers of the debugger temps `text` assigns, outside quoted strings."""
    text = blank_quoted(text)
    return {int(m.group(1) or m.group(2)) for m in _TEMP_WRITE.finditer(text)
            if not _AT_BEFORE.search(text, 0, m.start()) or _STEPS.search(m.group(0))}
