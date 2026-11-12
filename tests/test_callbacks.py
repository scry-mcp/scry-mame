"""The census callbacks' guard (`callbacks`): its text pinned, plus a structural check of
every family's install script. Its behaviour in MAME is proven live."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from lua_text import has, squash

from scry_mame import callbacks  # noqa: E402

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
    assert has(lua, "local ok, err = pcall(f, a, b, c)\n    if not ok then fault(t, err) end")
    assert has(lua, "t.errors = (t.errors or 0) + 1") and has(lua, "t.dirty = true")
    assert has(lua, "if t.first_error == nil then"), "the FIRST message, never the last"
    assert has(lua, f"1,\n                               {callbacks.FIRST_ERROR_MAX_CHARS})")


def test_the_first_message_is_cut_to_one_line_of_printable_ascii() -> None:
    """`splitlines` breaks on bytes Lua's `%s` misses, and a byte cut can split a character."""
    assert 'gsub("[^\\32-\\126]+", " ")' in callbacks.LUA


def test_a_dumper_that_keeps_failing_is_counted_once_per_run() -> None:
    """The periodic calls a dumper several times a stop; counting each would measure time."""
    lua = callbacks.LUA
    assert has(lua, "if ok then it.dump_failing = nil")
    assert has(lua, "elseif not it.dump_failing then it.dump_failing = true fault(it, err)")
    assert has(lua, "for _, it in pairs(T.items) do dump_guarded(it, dump, fr) end")
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
    from scry_mame import capture, tally
    from scry_mame import film as mfilm
    from scry_mame import manifest as mm
    from scry_mame import ramdac_lua as rlua

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
        assert squash(script).index(squash(message)) < squash(script).index(
            squash('f:write("end\\n")')), script[-900:]
    script = mfilm.install_script(film, Path("/s/film-1/film.txt"))
    assert has(script, 'baseline_value=%d errors=%d\\n"')
    assert has(script,
               '(t.first_error ~= nil and "e " .. t.first_error .. "\\n" or "") .. "end\\n")')


@pytest.mark.parametrize(("name", "module", "parser", "count"), [
    ("tally-raised.txt", "scry_mame.tally", "parse_dump", 678),
    ("capture-raised.txt", "scry_mame.capture", "parse_capture_header", 4),
    ("film-raised.txt", "scry_mame.film", "parse_film_header", 678),
    ("ramdac-raised.txt", "scry_mame.ramdac", "parse_dump", 3072),
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
end""".replace("callbacks_opened", "opened"))
    assert "handle\tclosed file" in out, out
    assert "errors\t1" in out, out
    failed = [ln for ln in out if ln.startswith(f"log {callbacks.DUMP_FAILED} ")]
    assert len(failed) == 1 and "70001e_2" in failed[0] and "the value table raised" in failed[0]


def test_every_dumper_that_writes_after_its_open_opens_through_the_guard() -> None:
    """A dumper calling `io.open` itself would leave its handle to the collector. The film's
    composes its text before opening, so nothing can raise between."""
    from scry_mame import lua_source
    bodies = {
        "tally-dumper": ("local function dump(it, fr)", "dump_at_stops("),
        "capture-dumper": ("local function dump(it, fr)", "dump_at_stops("),
        "ramdac-install": ("T.dump = function(it, fr)", "T.settle = "),
    }
    for name, (begin, end) in bodies.items():
        body = lua_source.load(name).split(begin, 1)[1].split(end, 1)[0]
        opens = body.count("io.open(")
        assert opens and opens == body.count("opened(it, io.open("), name


def test_a_dump_replaces_its_file_where_rename_will_not_overwrite(tmp_path: Path) -> None:
    """Windows' `rename` refuses an existing target, so every dump after the first stayed unread;
    `replace` takes the old one away first and raises when it still cannot."""
    from session_doubles import run_host_lua

    path = (tmp_path / "dump.txt").as_posix()
    windows = ('local real = os.rename\nos.rename = function(a, b)\n'
               '  local f = io.open(b, "rb")\n'
               '  if f ~= nil then f:close() return nil, "exists" end\n'
               '  return real(a, b)\nend\n')
    writes = "".join(f'do local f = io.open("{path}.tmp", "w") f:write("{n}") f:close() end\n'
                     f'replace("{path}.tmp", "{path}")\n' for n in ("one", "two"))
    run_host_lua(windows + callbacks.LUA + writes)
    assert (tmp_path / "dump.txt").read_text() == "two"
    assert not (tmp_path / "dump.txt.tmp").exists()
    stuck = 'os.rename = function() return nil, "denied" end\n'
    said = run_host_lua(callbacks.LUA + stuck + f'print(pcall(replace, "{path}.tmp", "{path}"))\n')
    assert said[0].startswith("false") and "denied" in said[0], said
