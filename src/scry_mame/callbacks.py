"""Guards for census callbacks, and how a dump carries what they caught.

MAME drops an error raised in a write tap silently, so a buggy body read as a tap that saw nothing.
"""

from __future__ import annotations

import re
from typing import Any

from scry_core import prose
from scry_core.reply_contract import or_unavailable

from scry_mame import lua_source

FIRST_ERROR_MAX_CHARS = 300
NO_FRAME = -1

# Logged once per run of failures: the dump on disk is then an older one.
DUMP_FAILED = "MCP_DUMP_FAILED"

LUA = lua_source.render("callbacks", first_error_max=FIRST_ERROR_MAX_CHARS,
                        dump_failed=DUMP_FAILED, no_frame=NO_FRAME)

# Read by name: a positional group shifts silently when a head field moves.
_ERRORS = re.compile(r" errors=(\d+)(?= |$)")


def match_head(pattern: re.Pattern[str], head: str) -> tuple[re.Match[str], str | None] | None:
    """Match `pattern` on the head minus `errors=`, and that count (None, never 0, if absent)."""
    found = _ERRORS.findall(head)
    m = pattern.match(_ERRORS.sub("", head)) if len(found) <= 1 else None
    return None if m is None else (m, found[0] if found else None)


def split_error_line(lines: list[str]) -> tuple[list[str], str | None]:
    """The lines without the `e` line before `end`, and its message."""
    if len(lines) >= 2 and lines[-1] == "end" and lines[-2].startswith("e "):
        return lines[:-2] + lines[-1:], lines[-2][2:]
    return lines, None


def parsed(count: str | None, first: str | None) -> dict[str, Any]:
    """A dump's `errors` and `first_error`."""
    return {"errors": None if count is None else int(count), "first_error": first}


def read_whole(text: str, head: re.Pattern[str], with_body: bool
               ) -> tuple[re.Match[str], list[str], dict[str, Any]] | None:
    """A whole dump's head match, body and errors."""
    lines, first = split_error_line(text.splitlines())
    if not lines or lines[-1] != "end" or (not with_body and len(lines) != 2):
        return None
    matched = match_head(head, lines[0])
    if matched is None:
        return None
    m, errors = matched
    return m, lines[1:-1], parsed(errors, first)


NONE_RAISED_WHY = "no callback raised"


def reply(dump: dict[str, Any]) -> dict[str, Any] | None:
    """A parsed dump's `callback_errors`, None without a count."""
    if dump.get("errors") is None:
        return None
    return {"count": dump["errors"],
            "first": or_unavailable(dump.get("first_error"), NONE_RAISED_WHY)}


def said(errors: dict[str, Any] | None, whose: str = "its") -> str:
    """A reply's clause for `whose` callbacks that raised."""
    if not errors or not errors.get("count"):
        return ""
    return (f"{whose} callbacks raised {prose.counted(errors['count'], 'time')} (the first: "
            f"{errors['first']})")
