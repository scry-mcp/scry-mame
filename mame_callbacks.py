"""Guards for census callbacks, and how a dump carries what they caught.

MAME drops an error raised in a write tap silently, so a buggy body read as a tap that saw nothing.
"""

from __future__ import annotations

import re
from typing import Any

from scry_core import prose
from scry_core.reply_contract import or_unavailable

FIRST_ERROR_MAX_CHARS = 300
NO_FRAME = -1

OPENED = "opened"
# Logged once per run of failures: the dump on disk is then an older one.
DUMP_FAILED = "MCP_DUMP_FAILED"

# Windows' `rename` refuses an existing target: `replace` takes it away first, so a reader meets
# the dump whole or absent, never the first one for ever.
# No varargs in `guarded`: a tap is the hot path. The first error is cut to printable ASCII on
# one line so the `e` line reads back whole.
LUA = f"""local function fault(t, err)
  t.errors = (t.errors or 0) + 1
  if t.first_error == nil then
    t.first_error = string.sub((tostring(err):gsub("[^\\32-\\126]+", " ")), 1,
                               {FIRST_ERROR_MAX_CHARS})
  end
  t.dirty = true
end
local function replace(tmp, path)
  if not os.rename(tmp, path) then
    os.remove(path)
    assert(os.rename(tmp, path))
  end
end
local function guarded(t, f)
  return function(a, b, c)
    local ok, err = pcall(f, a, b, c)
    if not ok then fault(t, err) end
  end
end
local function {OPENED}(it, f)
  if f ~= nil then it.handles[#it.handles + 1] = f end
  return f
end
local function dump_guarded(it, dump, fr)
  it.handles = {{}}
  local ok, err = pcall(dump, it, fr)
  for _, h in ipairs(it.handles) do
    if io.type(h) == "file" then pcall(h.close, h) end
  end
  it.handles = nil
  if ok then it.dump_failing = nil
  elseif not it.dump_failing then
    it.dump_failing = true
    fault(it, err)
    manager.machine:logerror(string.format("{DUMP_FAILED} %s %s\\n", tostring(it.id),
      (tostring(err):gsub("[^\\32-\\126]+", " "))))
  end
end
local function dump_at_stops(T, dump, before)
  emu.register_periodic(function()
    local d = manager.machine.debugger
    if d == nil or d.execution_state ~= "stop" then return end
    if before ~= nil then before() end
    local fr = {NO_FRAME}
    for _, scr in pairs(manager.machine.screens) do fr = scr:frame_number() break end
    for _, it in pairs(T.items) do dump_guarded(it, dump, fr) end
  end)
end
"""

# Read by name: a positional group shifts silently when a head field moves. A dump without it
# says nothing, which is not a zero.
_ERRORS = re.compile(r" errors=(\d+)(?= |$)")


def match_head(pattern: re.Pattern[str], head: str) -> tuple[re.Match[str], str | None] | None:
    """Match `pattern` on the head minus `errors=`; also that count (None if absent)."""
    found = _ERRORS.findall(head)
    m = pattern.match(_ERRORS.sub("", head)) if len(found) <= 1 else None
    return None if m is None else (m, found[0] if found else None)


def split_error_line(lines: list[str]) -> tuple[list[str], str | None]:
    """The lines without the `e` line before `end`, and its message (or None)."""
    if len(lines) >= 2 and lines[-1] == "end" and lines[-2].startswith("e "):
        return lines[:-2] + lines[-1:], lines[-2][2:]
    return lines, None


def parsed(count: str | None, first: str | None) -> dict[str, Any]:
    """The `errors` and `first_error` a parser adds to a dump."""
    return {"errors": None if count is None else int(count), "first_error": first}


def read_whole(text: str, head: re.Pattern[str], with_body: bool
               ) -> tuple[re.Match[str], list[str], dict[str, Any]] | None:
    """Head match, body and error account of a whole dump."""
    lines, first = split_error_line(text.splitlines())
    if not lines or lines[-1] != "end" or (not with_body and len(lines) != 2):
        return None
    matched = match_head(head, lines[0])
    if matched is None:
        return None
    m, errors = matched
    return m, lines[1:-1], parsed(errors, first)


#: `callback_errors.first` when no callback raised.
NONE_RAISED_WHY = "no callback raised"


def reply(dump: dict[str, Any]) -> dict[str, Any] | None:
    """A parsed dump's `callback_errors`, None without a count."""
    if dump.get("errors") is None:
        return None
    return {"count": dump["errors"],
            "first": or_unavailable(dump.get("first_error"), NONE_RAISED_WHY)}


def said(errors: dict[str, Any] | None, whose: str = "its") -> str:
    """The clause a reply adds when `whose` callbacks raised."""
    if not errors or not errors.get("count"):
        return ""
    return (f"{whose} callbacks raised {prose.counted(errors['count'], 'time')} (the first: "
            f"{errors['first']})")
