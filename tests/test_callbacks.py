"""The census callbacks' guard (`mame_callbacks`): its text pinned, plus a structural check of
every family's install script. Its behaviour in MAME is proven live."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mame_callbacks as callbacks  # noqa: E402

_TAP = r"\w+:install_write_tap\((?:[^,()]+(?:\([^()]*\))?,){3}\s*guarded\(t, function"
_NOTIFIER = r"emu\.add_machine_\w+_notifier\(guarded\(t, function"
_REGISTERS = (r"install_\w+_tap\(", r"add_machine_\w+_notifier\(", r"register_\w+\(")


def assert_every_callback_guarded(script: str, taps: int, notifiers: int) -> None:
    """Every callback `script` installs is `guarded`, and the dumper is registered once."""
    assert script.startswith(callbacks.LUA)
    body = script[len(callbacks.LUA):]
    assert len(re.findall(_TAP, body)) == taps == len(re.findall(r"install_write_tap\(", body))
    assert len(re.findall(_NOTIFIER, body)) == notifiers == len(
        re.findall(r"add_machine_\w+_notifier\(", body))
    others = [m for k in _REGISTERS for m in re.findall(k, body)
              if not m.startswith(("install_write_tap", "add_machine_"))]
    assert others == [], f"a callback registered another way: {others}"
    assert body.count("dump_at_stops(T, ") == 1, "one dumper, through the shared guard"


def test_the_guard_counts_each_error_keeps_the_first_and_marks_the_item_dirty() -> None:
    lua = callbacks.LUA
    assert "local ok, err = pcall(f, a, b, c)\n    if not ok then fault(t, err) end" in lua
    assert "t.errors = (t.errors or 0) + 1" in lua and "t.dirty = true" in lua
    assert "if t.first_error == nil then" in lua, "the FIRST message, never the last"
    assert f"1,\n                               {callbacks.FIRST_ERROR_MAX_CHARS})" in lua


def test_the_first_message_is_cut_to_one_line_of_printable_ascii() -> None:
    """`splitlines` breaks on bytes Lua's `%s` misses, and a byte cut can split a character."""
    assert 'gsub("[^\\32-\\126]+", " ")' in callbacks.LUA


def test_a_dumper_that_keeps_failing_is_counted_once_per_run() -> None:
    """The periodic calls a dumper several times a stop; counting each would measure time."""
    lua = callbacks.LUA
    assert "if ok then it.dump_failing = nil" in lua
    assert "elseif not it.dump_failing then\n    it.dump_failing = true\n    fault(it, err)" in lua
    assert "for _, it in pairs(T.items) do dump_guarded(it, dump, fr) end" in lua
    assert lua.count("emu.register_periodic(") == 1


def test_the_error_line_is_the_one_right_before_end_and_nowhere_else() -> None:
    assert callbacks.split_error_line(["h", "e boom", "end"]) == (["h", "end"], "boom")
    assert callbacks.split_error_line(["h", "e ", "end"]) == (["h", "end"], "")
    assert callbacks.split_error_line(["h", "e boom", "v 1", "end"]) == (
        ["h", "e boom", "v 1", "end"], None), "an `e` line elsewhere is no error line"
    assert callbacks.split_error_line(["h", "e a", "e b", "end"]) == (["h", "e a", "end"], "b"), (
        "two leave the first one for the parser, which refuses it")
    assert callbacks.split_error_line(["h", "e boom"]) == (["h", "e boom"], None), "no `end`"


def test_a_count_of_zero_is_zero_and_an_absent_one_is_none() -> None:
    assert callbacks.parsed("0", None) == {"errors": 0, "first_error": None}
    assert callbacks.parsed(None, None) == {"errors": None, "first_error": None}
    assert callbacks.parsed("3", None) == {"errors": 3, "first_error": None}
    assert callbacks.reply({"errors": 0, "first_error": None}) == {
        "count": 0, "first": {"available": False, "why": callbacks.NONE_RAISED_WHY}}
    assert callbacks.reply({"errors": None}) is None and callbacks.reply({}) is None


def test_the_clause_is_said_only_for_a_count_above_zero() -> None:
    assert callbacks.said(None) == "" and callbacks.said({"count": 0, "first": None}) == ""
    assert callbacks.said({"count": 2, "first": "mcp:3: x"}, "the log's") == (
        "the log's callbacks raised 2 times (the first: mcp:3: x)")


def test_every_dumper_writes_the_count_last_on_its_head_and_the_message_right_before_end(
) -> None:
    """The writer's half of the format the parsers read."""
    import mame_capture as capture
    import mame_film as mfilm
    import mame_manifest as mm
    import mame_ramdac_lua as rlua
    import mame_tally as tally

    ramdac = mm.PalettePort("x", "palette", "", 1, 3, ("r", "g", "b"), 6, True, 256, "declared",
                            "s")
    film = mfilm.Film(**{**{f: None for f in mfilm.Film.__dataclass_fields__},  # type: ignore[arg-type]
                         "trigger": "0x70001e", "trigger_addr": 0x70001E, "length": 2,
                         "frames": 4, "keep": 2, "changed": False, "checked": False,
                         "screen": ":screen", "dir": Path("/s/film-1"), "space": "program"})
    message = 'f:write("e ", it.first_error, "\\n") end\n'
    for script, head_end in (
            (tally.install_script("x_2", 0x10, 2, Path("/s/t.txt")), 'cpu=%s errors=%d\\n"'),
            (capture.install_script("x_t2", 0x12, capture.TapSource("space", "", 0x10), 4,
                                    Path("/s/h.txt"), Path("/s/r.rows")),
             'cpu=%s errors=%d\\n"'),
            (rlua.install_script("x", ramdac, Path("/s/h.txt"), Path("/s/r.rows"), None),
             'partial_writes=%d errors=%d\\n"')):
        assert head_end in script, head_end
        assert script.index(message) < script.index('f:write("end\\n")'), script[-900:]
    script = mfilm.install_script(film, Path("/s/film-1/film.txt"))
    assert 'baseline_value=%d errors=%d\\n"' in script
    assert '(t.first_error ~= nil and "e " .. t.first_error .. "\\n" or "") .. "end\\n")' in script


@pytest.mark.parametrize(("name", "module", "parser", "count"), [
    ("tally-raised.txt", "mame_tally", "parse_dump", 678),
    ("capture-raised.txt", "mame_capture", "parse_capture_header", 4),
    ("film-raised.txt", "mame_film", "parse_film_header", 678),
    ("ramdac-raised.txt", "mame_ramdac", "parse_dump", 3072),
])
def test_a_dump_s_error_count_is_read_by_its_name_wherever_the_head_puts_it(
        name: str, module: str, parser: str, count: int) -> None:
    """The count is read by name, never a neighbour's number by position."""
    import importlib
    parse = getattr(importlib.import_module(module), parser)
    text = (Path(__file__).parent / "fixtures" / "callbacks" / name).read_text()
    head, rest = text.split("\n", 1)
    moved = re.sub(r" errors=(\d+)$", "", head)
    moved = moved.replace(" seq=", f" errors={count} seq=", 1)
    assert moved != head and f"errors={count}" in moved
    plain, reordered = parse(text), parse(moved + "\n" + rest)
    assert plain is not None and plain["errors"] == count, plain
    assert reordered == plain, (reordered, plain)


def test_a_head_naming_its_error_count_twice_is_not_a_head() -> None:
    head = re.compile(r"^MCP_TALLY (\S+) seq=(\d+) cpu=(\S+)$")
    assert callbacks.match_head(head, "MCP_TALLY x seq=1 errors=2 cpu=:a errors=3") is None
    matched = callbacks.match_head(head, "MCP_TALLY x seq=1 cpu=:a")
    assert matched is not None and matched[0].groups() == ("x", "1", ":a") and matched[1] is None


GUARD_HOST = """
local logged = {}
manager = {machine = {debugger = {execution_state = "stop"}, screens = {s = {frame_number =
    function() return 904 end}}}}
function manager.machine:logerror(s) io.write("log ", s) end
local periodic = nil
emu = {register_periodic = function(f) periodic = f end}
"""


def _run_guard(tmp_path: Path, dumper: str) -> list[str]:
    """Run `callbacks.LUA` over one item with `dumper`, its periodic called twice: lines printed."""
    from session_doubles import run_host_lua
    chunk = (GUARD_HOST + callbacks.LUA
             + 'local T = {items = {x = {id = "70001e_2", errors = 0}}}\n'
             + f"local path = {str(tmp_path / 'd.txt')!r}\n" + dumper
             + "\ndump_at_stops(T, dump)\nperiodic()\nperiodic()\n"
             + 'print("handle", io.type(LEFT))\nprint("errors", T.items.x.errors)\n')
    return run_host_lua(chunk)


def test_a_dumper_that_raises_after_its_open_has_the_file_closed_and_the_error_logged(
        tmp_path: Path) -> None:
    """The guard closes the handle a failing dumper opened and logs the failure once per run."""
    out = _run_guard(tmp_path, """local function dump(it, fr)
  local f = callbacks_opened(it, io.open(path .. ".tmp", "w"))
  LEFT = f
  f:write("MCP_TALLY partial")
  error("the value table raised")
end""".replace("callbacks_opened", callbacks.OPENED))
    assert "handle\tclosed file" in out, out
    assert "errors\t1" in out, out
    failed = [ln for ln in out if ln.startswith(f"log {callbacks.DUMP_FAILED} ")]
    assert len(failed) == 1 and "70001e_2" in failed[0] and "the value table raised" in failed[0]


def test_every_dumper_that_writes_after_its_open_opens_through_the_guard() -> None:
    """A dumper calling `io.open` itself would leave its handle to the collector. The film's
    composes its text before opening, so nothing can raise between."""
    import inspect

    import mame_capture
    import mame_ramdac_lua
    import mame_tally
    bodies = {
        "tally": (inspect.getsource(mame_tally), "local function dump(it, fr)", "dump_at_stops("),
        "capture": (inspect.getsource(mame_capture), "local function dump(it, fr)",
                    "dump_at_stops("),
        "ramdac": (inspect.getsource(mame_ramdac_lua), "T.dump = function(it, fr)",
                   "T.settle = "),
    }
    for name, (text, begin, end) in bodies.items():
        body = text.split(begin, 1)[1].split(end, 1)[0]
        opens = body.count("io.open(")
        assert opens and opens == body.count("{callbacks.OPENED}(it, io.open("), name
