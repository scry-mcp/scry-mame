"""The guard the callbacks of every census this server keeps (the count watch, the capture, the
palette log, the film) run their bodies under, and how a dump carries what it caught.

WHY IT EXISTS. MAME drops an error raised inside a write tap without a trace (not on
stdout, not in `error.log`, and the tap goes on firing and raising at every write), so a body with
a bug read as a tap that saw nothing, a zero indistinguishable from a register nobody writes. An
error in a notifier or a periodic hook lands on stdout as a `[LUA ERROR]` line per call, which no
census reads. So each tap and notifier passes its body through `guarded`, and each dumper runs
under `dump_guarded`: an error is counted on its item and the first message kept, the dump writes
both (`errors=` on its head line, read by name, the message on an `e` line right before `end`),
and the reply carries them as `callback_errors`. A dumper opens its files through the guard's
`opened`, so one that raises half way through a write has them closed, and its failure logged.

It imports nothing of the server's: every census module imports it.
"""

from __future__ import annotations

import re
from typing import Any

from scry_core import prose
from scry_core.reply_contract import or_unavailable

# The characters of the first error a dump keeps: it rides on every survey of its tap.
FIRST_ERROR_MAX_CHARS = 300
# The frame a dump carries on a machine with no screen.
NO_FRAME = -1

# THE NAME OF THE GUARD'S OPEN, interpolated where a dumper writes after it opens (the tally's,
# the capture's, the palette log's; the film's composes its text first), so a dumper that raises
# half way through a write has its handles closed by the guard rather than left to the collector.
OPENED = "opened"
# The mark a dumper that raised logs, once per run of failures, under its tap's id: the dump on disk
# is then an older one, and a reply reading it says the error and not a timing.
DUMP_FAILED = "MCP_DUMP_FAILED"

# Three arguments and no varargs in `guarded`, because a tap is the hot path. The first message is
# cut to printable ASCII on one line: the `e` line must read back as the one line it was written
# as, and a byte cut must not split a character. A dumper that keeps failing is counted once per
# run of failures, not once per periodic call, so `count` stays a count of events.
LUA = f"""local function fault(t, err)
  t.errors = (t.errors or 0) + 1
  if t.first_error == nil then
    t.first_error = string.sub((tostring(err):gsub("[^\\32-\\126]+", " ")), 1,
                               {FIRST_ERROR_MAX_CHARS})
  end
  t.dirty = true
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

# A dump head's error count, read by its NAME wherever the head puts it: a group read by its
# position in a head pattern shifts silently when a field is added or reordered before it. Optional:
# the dumps captured as fixtures carry none, and a dump that does not say is read as saying nothing,
# never as a zero.
_ERRORS = re.compile(r" errors=(\d+)(?= |$)")


def match_head(pattern: re.Pattern[str], head: str) -> tuple[re.Match[str], str | None] | None:
    """A dump's head line matched by `pattern` once its `errors=` field is taken out, and that
    count (None when the head carries none); None when the rest does not match, or the head
    names a count twice."""
    found = _ERRORS.findall(head)
    m = pattern.match(_ERRORS.sub("", head)) if len(found) <= 1 else None
    return None if m is None else (m, found[0] if found else None)


def split_error_line(lines: list[str]) -> tuple[list[str], str | None]:
    """A dump's lines without the `e` line the first error is written on, right before `end`, and
    that message; None when no callback raised."""
    if len(lines) >= 2 and lines[-1] == "end" and lines[-2].startswith("e "):
        return lines[:-2] + lines[-1:], lines[-2][2:]
    return lines, None


def parsed(count: str | None, first: str | None) -> dict[str, Any]:
    """The `errors` and `first_error` a parser adds to a dump: `errors` None for a dump that
    carries no count."""
    return {"errors": None if count is None else int(count), "first_error": first}


def read_whole(text: str, head: re.Pattern[str], with_body: bool
               ) -> tuple[re.Match[str], list[str], dict[str, Any]] | None:
    """A dump or a header as a dumper wrote it: its head line matched by `head`, the lines
    between it and `end` (none for a header alone, `with_body` False), and its error account
    (`parsed`); None when the text is not a whole one, since a half-written file is no answer."""
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
    """A parsed dump's `callback_errors` as a reply carries them, None when it carries no count."""
    if dump.get("errors") is None:
        return None
    return {"count": dump["errors"],
            "first": or_unavailable(dump.get("first_error"), NONE_RAISED_WHY)}


def said(errors: dict[str, Any] | None, whose: str = "its") -> str:
    """The clause a reply's prose adds when `whose` callbacks raised, empty when none did: the one
    sentence every summary, `why` and refusal carries."""
    if not errors or not errors.get("count"):
        return ""
    return (f"{whose} callbacks raised {prose.counted(errors['count'], 'time')} (the first: "
            f"{errors['first']})")
