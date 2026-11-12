"""The Lua the server sends MAME, kept as `.lua` files beside this module so a linter and a
formatter read them as Lua. A value enters through a slot, `__SCRY_<name>__`: a valid identifier,
so the file parses as it stands, filled by `render` with a Lua literal of the value's type. A line
that is only `--- __SCRY_<name>__`, indented or not, is a statement slot, a comment until
`render` puts the `Code` of shared statements there. A line that is only a comment stays in the
file and is not sent: the console takes a script as one line of bounded length."""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path

from scry_mame import state as st
from scry_mame.transport import lua_string

HERE = Path(__file__).parent / "lua"
SLOT = re.compile(r"__SCRY_([a-z0-9_]+?)__")
STATEMENT = re.compile(r"^[ \t]*--- __SCRY_([a-z0-9_]+?)__$", re.MULTILINE)
COMMENT_LINE = re.compile(r"^[ \t]*--(?!\[=*\[).*\n", re.MULTILINE)


@dataclass(frozen=True)
class Code:
    """Lua the server built, which goes in as it is."""
    text: str


Value = str | int | float | bool | None | Code


@functools.cache
def load(name: str) -> str:
    return (HERE / f"{name}.lua").read_text(encoding="utf-8")


def slots(name: str) -> frozenset[str]:
    return frozenset(SLOT.findall(load(name)))


def literal(value: Value) -> str:
    """`value` as Lua source."""
    if isinstance(value, Code):
        return value.text
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return lua_string(value)
    raise st.Invalid("bad_argument", f"a Lua slot takes a str, a number, a bool, None or Code, "
                     f"not a {type(value).__name__}")


def render(name: str, **values: Value) -> str:
    """Script `name` with every slot filled; a slot with no value, or a value for no slot, is
    refused."""
    wanted = slots(name)
    if missing := sorted(wanted - values.keys()):
        raise st.Invalid("bad_argument", f"lua/{name}.lua: no value for "
                         + ", ".join(f"__SCRY_{m}__" for m in missing))
    if extra := sorted(values.keys() - wanted):
        raise st.Invalid("bad_argument", f"lua/{name}.lua has no slot for {', '.join(extra)}")
    statements = set(STATEMENT.findall(load(name)))
    if loose := sorted(k for k in statements if not isinstance(values[k], Code)):
        raise st.Invalid("bad_argument", f"lua/{name}.lua: a statement slot takes Code: "
                         + ", ".join(loose))
    shown = {key: literal(value) for key, value in values.items()}
    text = STATEMENT.sub(lambda m: "\x00" + m.group(1), load(name))
    text = COMMENT_LINE.sub("", text)
    text = re.sub(r"^\x00([a-z0-9_]+)$", lambda m: shown[m.group(1)].rstrip("\n"), text,
                  flags=re.MULTILINE)
    return SLOT.sub(lambda m: shown[m.group(1)], text)
