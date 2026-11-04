"""The classifier's tables against MAME's own command table (fixtures/console/PROVENANCE.txt)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_cpu_focus import _patched  # noqa: E402

from scry_mame import console  # noqa: E402
from scry_mame import server as s  # noqa: E402

REGISTERED = Path(__file__).resolve().parent / "fixtures" / "console" / "commands.registered.txt"


def _registered() -> dict[str, tuple[int, str]]:
    rows = [line.split() for line in REGISTERED.read_text(encoding="ascii").splitlines()]
    assert rows and all(len(r) == 3 for r in rows), "the fixture is a table of three columns"
    return {name: (int(low), high) for name, low, high in rows}


def test_every_command_mame_registers_is_classified_and_nothing_else_is() -> None:
    names = set(_registered())
    assert names - set(console.CORE_COMMANDS) == set(), "registered, in no table"
    assert set(console.CORE_COMMANDS) - names == set(), "in a table, not registered"


@pytest.mark.parametrize("word", ["//", "/*"])
def test_the_comment_aliases_resolve_to_themselves(word: str) -> None:
    """`//` is `comadd` and `/*` is `commit` under another name (debugcmd.cpp)."""
    assert console.resolve_command(word) == word
    assert not console.mutates(f"{word} 0x400,a comment")


@pytest.mark.parametrize("command", [
    "source script.txt",
    "epset 1,1,{fill 0x100,1,1}", "ep 1,1,{g}", "epset 1,{d0==1},{d0=1}",
    "trace t.txt,0,,{g}", "traceover t.txt,:maincpu,noloop,{fill 0x100,1,1}",
    "trace t.txt,0,noloop,g", "bpset 0x400,1,g", "rpset {d1==1},g", "wpset 0,4,w,1,g",
])
def test_a_script_or_an_action_counts_as_a_write(command: str) -> None:
    assert console.mutates(command), f"{command!r} runs commands and is not marked"


@pytest.mark.parametrize("command", [
    "epset 1", "epset 1,{d0==1}", "bpset 0x400,{d0==1}", "wpset 0,4,w,{wpdata==1}",
    "trace t.txt", "trace t.txt,0,noloop", "trace off", "traceover t.txt,0",
    "suspend", "resume", "ignore", "observe",
    'input "abc"',
])
def test_a_condition_a_plain_trace_and_a_listing_are_not_writes(command: str) -> None:
    assert not console.mutates(command), f"{command!r} changes nothing and is marked"


@pytest.mark.parametrize("command", ["suspend 1", "resume :subcpu", "suspend maincpu,subcpu"])
def test_suspend_and_resume_with_a_cpu_still_write(command: str) -> None:
    assert console.mutates(command)


@pytest.mark.parametrize("command", ["ignore", "observe", "IGNORE", "obs"])
def test_a_bare_ignore_or_observe_lists_and_reads_no_cpu_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command: str,
) -> None:
    """A listing sets no cpu, so nothing is read back."""
    ses = _patched(monkeypatch, tmp_path)
    ses.commands.clear()
    out = s.debug(command=command)
    assert out["status"] == "ok" and out["mutates"] is False, out
    assert "visible_cpu" not in out and "ignored" not in out, out
    assert "?" not in ses.commands, "the live cpu is read only before a line that can move it"


def test_an_ignore_with_a_cpu_still_reads_the_cpus_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The control for the listing: the same word with a cpu sets one."""
    ses = _patched(monkeypatch, tmp_path)
    ses.live = ":subcpu"
    out = s.debug(command="ignore maincpu")
    assert "visible_cpu" in out and "ignored" in out, out


@pytest.mark.parametrize(("command", "word", "params"), [
    ("bpset 0x400,{d0==1},{g}", "bpset", ["0x400", "{d0==1}", "{g}"]),
    ('printf "a,b",pc', "printf", ['"a,b"', "pc"]),
    ("ignore", "ignore", []),
    ("  trace  t.txt , 0", "trace", ["t.txt", "0"]),
    ("print (1,2),3", "print", ["(1,2)", "3"]),
])
def test_a_command_splits_into_its_word_and_parameters_as_the_console_splits_it(
    command: str, word: str, params: list[str],
) -> None:
    """As `internal_parse_command` splits (debugcon.cpp): a `,` outside brackets ends one."""
    assert console.parameters(command) == (word, params)


def test_every_action_sits_at_the_last_parameter_its_command_registers() -> None:
    """The action is the last parameter: its index is the registered maximum less one."""
    registered = _registered()
    for name, at in console._ACTION_AT.items():
        assert int(registered[name][1]) - 1 == at, (name, at, registered[name])


@pytest.mark.parametrize("command", [
    "rpset {d1==1}", "rp {d1==1}", "traceover t.txt,0,noloop", "bpset 0x400,1,",
    "trace t.txt,0,,", "wp 0,4,w,1,",
])
def test_a_condition_alone_or_an_empty_action_is_not_a_write(command: str) -> None:
    assert not console.mutates(command), command


@pytest.mark.parametrize("command", [
    "bp 0x400,1,g", "wpd 0,4,w,1,g", "wpiset 0,4,w,1,g", "wpo 0,4,w,1,g", "rp {d1==1},g",
])
def test_an_action_on_an_alias_is_a_write(command: str) -> None:
    assert console.mutates(command), command


@pytest.mark.parametrize("command", ["epset 1,{temp0=1}", "trace t.txt,0,,{temp0=1}",
                                     "bp 0x400,1,{temp0=1}"])
def test_what_an_exception_point_or_a_trace_arms_is_evaluated_later(command: str) -> None:
    """A temp they assign is assigned at every hit, not by the line."""
    assert console.evaluated_later(command)
    assert not console.evaluated_later("print temp0=1")


@pytest.mark.parametrize(("command", "name", "reset"), [
    ("stateload c1", "stateload", False), ("sl c1", "sl", False), ("rewind", "rewind", False),
    ("rw", "rw", False), ("softreset", "softreset", True), ("hardreset", None, False),
    ("softr", "softreset", True), ("statesave c1", None, False), ("print pc", None, False),
])
def test_the_commands_that_leave_totalcycles_stale_and_which_are_resets(
    command: str, name: str | None, reset: bool,
) -> None:
    assert console.stale_counter_command(command) == name
    assert (name is not None and console.is_reset(name)) is reset


@pytest.mark.parametrize("command", ["// 0x400,d0=7", "comadd 0x400,d0=7", "/* 0x400,a=b",
                                     "commit 0x400,pc=0"])
def test_a_comments_text_is_never_evaluated_so_an_assignment_in_it_writes_nothing(
    command: str,
) -> None:
    """The text is the pane's, never evaluated."""
    assert not console.mutates(command), command


def test_an_assignment_in_a_comments_address_is_still_a_write() -> None:
    """The address IS an expression the console evaluates."""
    assert console.mutates("comadd d0=5,text")


@pytest.mark.parametrize("line", ["hardreset", "HARDRESET", "hardr", "print 1;hardreset"])
def test_a_typed_hardreset_is_refused_before_anything_is_sent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, line: str,
) -> None:
    """It kills the stub's connection, so it is refused as the `reset` tool refuses it."""
    ses = _patched(monkeypatch, tmp_path)
    ses.commands.clear()
    out = s.debug(command=line)
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert "`close`" in out["message"] and "`start`" in out["message"], out
    assert not any("hardr" in c.lower() or c.startswith("print") for c in ses.commands)
