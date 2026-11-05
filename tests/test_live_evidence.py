"""`tests/live/evidence.py`, loaded by path as `map_edges` is."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from scry_mame import files


def _evidence() -> ModuleType:
    path = Path(__file__).parent / "live" / "evidence.py"
    spec = importlib.util.spec_from_file_location("evidence", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _session(tmp_path: Path, **logs: str) -> Path:
    scratch = tmp_path / "session"
    scratch.mkdir()
    for channel, text in logs.items():
        files.log_path(scratch, channel).write_text(text, encoding="utf-8")
    return scratch


def test_both_logs_of_a_failed_cell_are_copied_under_its_label(tmp_path: Path) -> None:
    scratch = _session(tmp_path, process="the console said\n", emulator="the driver said\n")
    kept = _evidence().keep(scratch, tmp_path / "evidence", "lua while running")
    assert kept is not None and kept.parent == tmp_path / "evidence"
    assert sorted(p.name for p in kept.iterdir()) == ["error.log", "stdout.log"]
    assert (kept / "stdout.log").read_text(encoding="utf-8") == "the console said\n"
    assert (kept / "error.log").read_text(encoding="utf-8") == "the driver said\n"
    assert files.log_path(scratch, "process").exists(), "a copy: `close` still owns the original"


def test_one_missing_log_does_not_cost_the_other(tmp_path: Path) -> None:
    scratch = _session(tmp_path, emulator="the driver said\n")
    kept = _evidence().keep(scratch, tmp_path / "evidence", "a cell")
    assert kept is not None
    assert [p.name for p in kept.iterdir()] == ["error.log"]


def test_a_session_with_no_log_keeps_nothing_and_says_so(tmp_path: Path) -> None:
    dest = tmp_path / "evidence"
    assert _evidence().keep(_session(tmp_path), dest, "a cell") is None
    assert not dest.exists(), "no empty directory is left to be read as evidence"


def test_a_label_becomes_a_directory_name_that_cannot_leave_the_destination(
    tmp_path: Path,
) -> None:
    evidence = _evidence()
    dest = tmp_path / "evidence"
    label = "read_block at \"straddling\" the space's end: ../../etc"
    kept = evidence.keep(_session(tmp_path, process="x"), dest, label)
    assert kept is not None and kept.parent == dest
    assert kept.name == "read_block-at-straddling-the-space-s-end-etc"
    assert evidence.slug("///") == "cell", "a label with nothing usable still names a directory"


def test_a_long_label_keeps_a_directory_name_under_the_bound_and_still_apart(
    tmp_path: Path,
) -> None:
    evidence = _evidence()
    scratch = _session(tmp_path, process="x")
    long = "a cell whose label runs on " + "and on " * 40
    first = evidence.keep(scratch, tmp_path / "evidence", long + "first")
    second = evidence.keep(scratch, tmp_path / "evidence", long + "second")
    assert first is not None and second is not None
    assert len(first.name) <= evidence.SLUG_MAX and len(second.name) <= evidence.SLUG_MAX + 2
    assert first != second, "two long labels that start alike share a directory"


def test_two_cells_whose_labels_slug_alike_do_not_share_a_directory(tmp_path: Path) -> None:
    evidence = _evidence()
    scratch = _session(tmp_path, process="first\n")
    first = evidence.keep(scratch, tmp_path / "evidence", "a cell")
    files.log_path(scratch, "process").write_text("second\n", encoding="utf-8")
    second = evidence.keep(scratch, tmp_path / "evidence", "a  cell")
    assert first is not None and second is not None
    assert (first.name, second.name) == ("a-cell", "a-cell-2")
    assert (first / "stdout.log").read_text(encoding="utf-8") == "first\n"
    assert (second / "stdout.log").read_text(encoding="utf-8") == "second\n"


# ------------------------------------------------ the console's counts against the kept log

_KEPT = (Path(__file__).parent / "fixtures" / "console" / "c3.death-and-rerun.stdout").read_bytes()


def test_the_kept_log_of_a_death_and_a_rerun_reads_one_of_each() -> None:
    """The run that failed the old cell: its session block said one death and one rerun, and
    the log it kept shows exactly that, so the counters were right and the cell was wrong."""
    seen = _evidence().console_in_log(_KEPT)
    assert seen["thread_errors"] == 1 and seen["reruns"] == 1, seen
    assert seen["sentinels"] == 6, "the sequence's six chunks, each counted once"


def test_counts_that_agree_with_the_log_pass_and_one_off_by_one_fails() -> None:
    disagreement = _evidence().console_disagreement
    assert disagreement(_KEPT, {"thread_errors": 1, "reruns": 1, "lost": 0}) == {}
    assert disagreement(_KEPT, {"thread_errors": 0, "reruns": 1, "lost": 0}) == {
        "thread_errors": (1, 0)}
    assert disagreement(_KEPT, {"thread_errors": 1, "reruns": 2, "lost": 0}) == {"reruns": (1, 2)}
    assert disagreement(_KEPT, {}) == {"thread_errors": (1, 0), "reruns": (1, 0)}, (
        "a block that carries no count is a block of zeros: the server omits a healthy "
        "console's counts, and only a log with no sentinel proves nothing was examined")


def test_a_log_with_no_sentinel_examined_nothing() -> None:
    assert _evidence().console_in_log(b"no console here\n")["sentinels"] == 0
    assert _evidence().console_in_log(
        b'print("MAME_MCP_LUA_END#1", ok, err)\n')["sentinels"] == 0, (
        "the chunk's own source names the sentinel with no TAB, and is no end")


def test_a_death_and_a_rerun_are_told_apart() -> None:
    """Two deaths and no rerun: a rule that swapped the two counts would read one of each."""
    seen = _evidence().console_in_log(
        b"[LUA ERROR] in thread: a\n[LUA ERROR] in thread: b\nMAME_MCP_LUA_END#1\ttrue\tnil\n")
    assert (seen["thread_errors"], seen["reruns"]) == (2, 0), seen


def test_a_sentinel_a_script_printed_itself_is_no_rerun() -> None:
    """Only a chunk the log shows the server SENT counts: a script printing the sentinel's
    text twice ran once, as far as the console's reruns go."""
    sent = b'> local f, e = load("x") if f == nil then print("MAME_MCP_LUA_END#1", false, e) end\n'
    printed = b"MAME_MCP_LUA_END#1\ttrue\tnil\nMAME_MCP_LUA_END#99\t1\nMAME_MCP_LUA_END#99\t1\n"
    seen = _evidence().console_in_log(sent + printed)
    assert (seen["reruns"], seen["sentinels"]) == (0, 1), seen


def test_the_ends_are_read_in_the_order_the_console_printed_them() -> None:
    """The first end of each chunk the server sent, in the log's order: a rerun is not a second
    place, and an end a script printed itself is not the server's."""
    sent = b"".join(b'print("MAME_MCP_LUA_END#%d", false, e)\n' % n for n in (1, 2, 3))
    printed = (b"MAME_MCP_LUA_END#2\ttrue\tnil\nMAME_MCP_LUA_END#99\t1\n"
               b"MAME_MCP_LUA_END#1\ttrue\tnil\nMAME_MCP_LUA_END#2\ttrue\tnil\n")
    assert _evidence().sentinel_order(sent + printed) == [2, 1]
    assert _evidence().sentinel_order(b"no console here\n") == []


_THROTTLE_THEN_LUA = (Path(__file__).parent / "fixtures" / "console"
                      / "c3.throttle-then-lua.stdout").read_bytes()


def test_c3s_predicate_tells_a_line_a_console_command_ran_from_one_still_ahead() -> None:
    """C.3's predicate on the captured log: `lua` counted none ahead and the throttle's end came
    first, true; the same log with the count a stub that does not refresh gives, one ahead,
    false; a log where the throttle's end never printed, false; and one where it printed AFTER
    `lua`'s, false, since then the throttle's line was not what ran first."""
    ev = _evidence()
    lua = {"call": "MAME_MCP_LUA_END#2", "lines_ahead": 0}
    throttle = {"tag": "MAME_MCP_THROTTLE#1"}
    assert ev.console_ran_the_throttle_first(lua, throttle, _THROTTLE_THEN_LUA) is True
    assert ev.console_ran_the_throttle_first({**lua, "lines_ahead": 1}, throttle,
                                             _THROTTLE_THEN_LUA) is False
    cut = _THROTTLE_THEN_LUA.replace(b"MAME_MCP_LUA_END#1\t", b"")
    assert ev.console_ran_the_throttle_first(lua, throttle, cut) is False
    end = b"MAME_MCP_LUA_END#1\ttrue\tnil\n"
    swapped = _THROTTLE_THEN_LUA.replace(end, b"") + end
    assert ev.sentinel_order(swapped) == [2, 1], "the case is built: lua's end first"
    assert ev.console_ran_the_throttle_first(lua, throttle, swapped) is False


def test_c3s_predicate_answers_false_where_a_mark_or_its_end_is_missing() -> None:
    """A reply with no `call`, a mark with no number, or `lua`'s own end absent from the log is
    a cell that cannot be read, and the predicate says False rather than raising on it."""
    ev = _evidence()
    lua = {"call": "MAME_MCP_LUA_END#2", "lines_ahead": 0}
    throttle = {"tag": "MAME_MCP_THROTTLE#1"}
    assert ev.console_ran_the_throttle_first({"lines_ahead": 0}, throttle,
                                             _THROTTLE_THEN_LUA) is False
    assert ev.console_ran_the_throttle_first({**lua, "call": "MAME_MCP_LUA_END"}, throttle,
                                             _THROTTLE_THEN_LUA) is False
    assert ev.console_ran_the_throttle_first(lua, {"tag": "MAME_MCP_THROTTLE"},
                                             _THROTTLE_THEN_LUA) is False
    gone = _THROTTLE_THEN_LUA.replace(b"MAME_MCP_LUA_END#2\t", b"")
    assert 2 not in ev.sentinel_order(gone), "the case is built: lua's end is not in the log"
    assert ev.console_ran_the_throttle_first(lua, throttle, gone) is False


def test_a_healthy_console_is_judged_against_its_log_not_blocked() -> None:
    """The close reply omits a console with no failure (`carried` keeps it only when a count is
    up), so an absent block is zero failures; the cell's own proof of work is the log."""
    evidence = _evidence()
    quiet = {"thread_errors": 0, "reruns": 0, "lost": 0}
    assert evidence.console_unjudgeable(_KEPT, quiet) == ""
    assert evidence.console_unjudgeable(_KEPT, {}) == ""
    assert evidence.console_disagreement(_KEPT, {}) == {"thread_errors": (1, 0), "reruns": (1, 0)}


def test_a_log_with_no_sentinel_is_what_makes_the_cell_unjudgeable() -> None:
    why = _evidence().console_unjudgeable(b"no console here\n", {})
    assert "no console sentinel" in why
