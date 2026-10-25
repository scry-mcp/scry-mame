"""`debug` over the console's own error answers, from `fixtures/console/refused.*.txt`."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server_support import _running  # noqa: E402
from session_doubles import captured, wplist_answer  # noqa: E402

import mame_console as console  # noqa: E402
import mame_lexer as lexer  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402

# (capture, the line sent, the command the console refused, the head of its error)
REFUSED = [
    ("refused.print-expression-subcpu", "print d@20113a:subcpu", "print d@20113a:subcpu",
     "Error in expression: d@20113a:subcpu / ^unknown symbol"),
    ("refused.print-expression-symbol", "print zzz", "print zzz",
     "Error in expression: zzz / ^unknown symbol"),
    ("refused.bp-expression-symbol", "bp zzz", "bp zzz", "Error in expression: zzz"),
    ("refused.unknown-command", "zzz 1", "zzz 1", "unknown command"),
    ("refused.bpclear-number", "bpclear 0x7", "bpclear 0x7", "Invalid breakpoint number 7"),
    ("refused.wpclear-number", "wpclear 0x9", "wpclear 0x9", "Invalid watchpoint number 9"),
    ("refused.rpclear-number", "rpclear 0x7", "rpclear 0x7", "Invalid registerpoint number 7"),
    ("refused.not-enough-params", "print", "print", "not enough parameters for command"),
    ("refused.too-many-params", "focus maincpu,subcpu,zzz", "focus maincpu,subcpu,zzz",
     "too many parameters for command"),
    ("refused.unbalanced-parens", "print {d1==", "print {d1==", "unbalanced parentheses"),
    ("refused.unbalanced-quotes", 'print "abc', 'print "abc', "unbalanced quotes"),
    ("refused.assignment-expression", "d0=", "d0=",
     "error in assignment expression: stack underflow"),
    ("refused.comparison-bare", "print d1==1234", "print d1==1234",
     "error in assignment expression: unknown symbol"),
    ("refused.wpset-type", "wpset 0x100,4,x", "wpset 0x100,4,x",
     "Invalid watchpoint type: expected r, w, or rw"),
    ("refused.loadr-missing-file", "loadr /nonexistent/nope.bin,0,4,:maincpu",
     "loadr /nonexistent/nope.bin,0,4,:maincpu", "Error opening file '/nonexistent/nope.bin'"),
    ("refused.load-missing-file", "load /nonexistent/nope.bin,0,4",
     "load /nonexistent/nope.bin,0,4", "Error opening file '/nonexistent/nope.bin'"),
]
ANSWERED = [
    ("answered.print-pc", "print pc"),
    ("answered.print-braces-false", "print {d1==7fff}"),
    ("answered.comparison-braces", "print {d1==1234}"),
    ("answered.bplist-none", "bplist"),
]


#: A refused command the console's answer does not place, as the reply spells it.
UNPINNED = {"available": False, "why": "the console's answer does not say which command it was"}

def _console(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answers: dict[str, str]) -> object:
    """A running double whose console answers the captured text for the lines named."""
    ses = _running(monkeypatch, tmp_path)
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command in answers:
            ses.commands.append(command)
            return answers[command]
        if command == "wplist":            # a refused `wpclear` re-reads the list
            return wplist_answer([])
        return real(command, timeout)

    monkeypatch.setattr(ses, "monitor", monitor)
    monkeypatch.setattr(mstate.STATE, "console_writes", 0)
    return ses


def _refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capture: str,
             line: str) -> dict[str, Any]:
    _console(monkeypatch, tmp_path, {line: captured(f"{capture}.txt")})
    out: dict[str, Any] = s.debug(command=line)
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert out["output"] == captured(f"{capture}.txt") and out["clipped"] is False
    return out


@pytest.mark.parametrize(("capture", "line", "refused", "error"), REFUSED,
                         ids=[c for c, *_ in REFUSED])
def test_each_captured_error_answer_is_a_refusal_in_the_consoles_words(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capture: str, line: str,
        refused: str, error: str) -> None:
    out = _refused(monkeypatch, tmp_path, capture, line)
    assert f"`{refused}`" in out["message"] and error in out["message"], out["message"]
    assert out["refused"] == [{"index": 0, "command": refused, "error": out["refused"][0]["error"]}]
    assert error in out["refused"][0]["error"] and out["refused_total"] == 1
    assert out["not_run"] == []


@pytest.mark.parametrize(("capture", "line"), ANSWERED, ids=[c for c, _ in ANSWERED])
def test_an_answer_that_is_not_an_error_is_ok_with_no_refusal_field(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capture: str, line: str) -> None:
    text = captured(f"{capture}.txt")
    _console(monkeypatch, tmp_path, {line: text})
    out = s.debug(command=line)
    assert out["status"] == "ok" and out["output"] == text, out
    assert "refused" not in out and "not_run" not in out and "code" not in out


def test_a_command_a_parse_error_refused_is_no_write_and_the_ones_after_it_never_ran(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`d0=` alone: the console parsed nothing, so the assignment is no write."""
    out = _refused(monkeypatch, tmp_path, "refused.assignment-expression", "d0=")
    assert out["mutates"] is False and out["session"]["altered"] is False
    assert mstate.STATE.console_writes == 0


def test_a_command_refused_while_it_ran_is_still_a_write_because_it_may_have_written(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`print d0=5,zzz` refuses `zzz` yet D0 reads 5: parameters are evaluated in order."""
    out = _refused(monkeypatch, tmp_path, "refused.print-assign-then-error", "print d0=5,zzz")
    assert out["mutates"] is True and out["session"]["altered"] is True, out
    assert out["refused"][0]["index"] == 0 and out["not_run"] == []
    assert mstate.STATE.console_writes == 1
    out = _refused(monkeypatch, tmp_path, "refused.load-missing-file",
                   "load /nonexistent/nope.bin,0,4")
    assert out["mutates"] is True and mstate.STATE.console_writes == 1


def test_an_error_in_the_middle_of_a_line_names_its_command_and_the_rest_ran(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = _refused(monkeypatch, tmp_path, "refused.semicolon-middle",
                   "print pc;print d@20113a:subcpu;print d0")
    assert "command 2 of 3, `print d@20113a:subcpu`" in out["message"], out["message"]
    assert "the rest of the line ran" in out["message"], out["message"]
    assert [r["index"] for r in out["refused"]] == [1] and out["not_run"] == []


def test_a_family_error_on_a_line_of_several_commands_is_pinned_on_the_familys_one(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`print pc;bpclear 0x7`: the error is pinned on the line's one `bp` command."""
    out = _refused(monkeypatch, tmp_path, "refused.print-then-bpclear", "print pc;bpclear 0x7")
    assert out["refused"] == [{"index": 1, "command": "bpclear 0x7",
                               "error": "Invalid breakpoint number 7"}], out["refused"]
    assert "command 2 of 2, `bpclear 0x7`" in out["message"]


def test_a_parse_error_refuses_the_line_at_its_command_and_names_what_never_ran(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = _refused(monkeypatch, tmp_path, "refused.semicolon-first", "zzz 1;print pc")
    assert "command 1 of 2, `zzz 1`: unknown command" in out["message"], out["message"]
    assert "`print pc` never ran" in out["message"], out["message"]
    assert out["not_run"] == ["print pc"] and out["refused"][0]["index"] == 0


def test_a_release_after_a_parse_error_never_ran_so_the_machine_is_not_marked_running(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ses = _console(monkeypatch, tmp_path, {"zzz 1;g": captured("refused.unknown-then-g.txt")})
    monkeypatch.setattr(mstate.STATE, "run_release", {"emulated": 1.0, "wall": 2.0})
    out = s.debug(command="zzz 1;g")
    assert out["code"] == "bad_argument" and "running" not in out, out
    assert getattr(ses, "running") is False and not mstate.STATE.console_run  # noqa: B009
    assert out["not_run"] == ["g"] and out["session"]["running"] is False
    assert mstate.STATE.run_release == {"emulated": 1.0, "wall": 2.0}, (
        "the window the release would have opened is put back, not dropped")


def test_a_pinned_parse_error_keeps_its_not_run_beside_errors_that_could_not_be_pinned(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Two `Error in expression: foo` match two commands so neither is pinned; `yyy` is."""
    line = "print foo;print foo;yyy;g"
    ses = _console(monkeypatch, tmp_path, {line: captured("refused.two-unpinned-then-parse.txt")})
    out = s.debug(command=line)
    assert out["code"] == "bad_argument" and "running" not in out, out
    assert [r["index"] for r in out["refused"]] == [UNPINNED, UNPINNED, 2], out
    assert out["refused_total"] == 3
    assert out["not_run"] == ["g"] and getattr(ses, "running") is False  # noqa: B009
    assert out["mutates"] is False


def test_a_control_counter_assigned_after_a_parse_error_is_not_noted(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    line = "zzz 1;temp0=0"
    text = captured("refused.trailing-semicolon.txt").replace(">zzz 1;", f">{line}")
    _console(monkeypatch, tmp_path, {line: text})
    monkeypatch.setitem(mstate.STATE.controls, ("hot", ":maincpu"),
                        {"addr": 0x400, "temp": 0, "index": 1, "missed": 0})
    out = s.debug(command=line)
    assert out["code"] == "bad_argument" and "assigns the counter" not in out.get("note", ""), out


def test_the_bare_comparison_is_an_expression_to_the_console_and_judged_by_mames_rule(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The console reads both as assignment expressions and its caret points at neither."""
    out = _refused(monkeypatch, tmp_path, "refused.assign-then-comparison",
                   "d1=1234;print d1==1234")
    assert out["refused"][0]["index"] == UNPINNED and "could not be told" in out["message"]
    assert out["not_run"] == [] and out["mutates"] is True and out["session"]["altered"] is True
    assert console.is_expression("print d1==1234") and not console.is_expression("print {d1==1234}")
    assert console.is_expression("do d0=1") and console.is_expression("d0++")
    assert not console.is_expression("print d0,d1=1"), "two parameters: a command"
    assert not console.is_expression('printf "a=b"'), "an `=` inside quotes is text"


def test_two_malformed_assignments_on_one_line_cannot_be_pinned(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = _refused(monkeypatch, tmp_path, "refused.assignment-two", "d0=;d1=")
    assert out["refused"][0]["index"] == UNPINNED and out["refused"][0]["command"] == UNPINNED
    assert out["not_run"] == [] and "could not be told" in out["message"]


def test_a_parse_error_on_a_line_the_console_wrapped_is_still_pinned(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The echo and the caret line come back wrapped; the caret's offset is read through it."""
    line = "print 1;" * 40 + "zzz"
    out = _refused(monkeypatch, tmp_path, "refused.long-parse-error", line)
    assert out["refused"] == [{"index": 40, "command": "zzz", "error": "unknown command"}]
    assert out["not_run"] == [] and "command 41 of 41, `zzz`" in out["message"]


def test_a_trailing_semicolon_opens_no_empty_command(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = _refused(monkeypatch, tmp_path, "refused.trailing-semicolon", "zzz 1;")
    assert out["refused"][0]["command"] == "zzz 1" and out["not_run"] == []
    assert "the console refused `zzz 1`" in out["message"], out["message"]
    assert console.console_commands("") == [""] and console.console_commands(";") == [""]


def test_an_error_that_cannot_be_pinned_names_the_line_and_counts_every_command(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """One `Invalid breakpoint number` per command and neither says which."""
    out = _refused(monkeypatch, tmp_path, "refused.bpclear-two", "bpclear 0x7;bpclear 0x8")
    assert "could not be told from the answer" in out["message"], out["message"]
    assert [r["index"] for r in out["refused"]] == [UNPINNED, UNPINNED], out
    assert out["refused_total"] == 2 and out["refused"][0]["command"] == UNPINNED


def test_the_refusal_fields_are_bounded_like_output_is() -> None:
    line = ";".join(["print zzz"] * 400)
    text = captured("refused.print-expression-symbol.txt").rstrip("\n").replace("\n\n", "\n")
    found = console.refusals(line, (text + "\n") * 400)
    assert found is not None and len(found.refused) == 400
    fields = found.fields(console.console_commands(line))
    assert len(fields["refused"]) == console.REFUSED_LISTED_MAX and fields["refused_total"] == 400
    message = console.refusal_message(line, found)
    assert "and 396 more console errors" in message and message.count("could not be told") == 4


def test_a_refused_console_step_ends_a_perform_and_a_drive_at_that_step(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bad = "print d@20113a:subcpu"
    _console(monkeypatch, tmp_path, {bad: captured("refused.print-expression-subcpu.txt")})
    out = s.perform(steps=[{"op": "debug", "command": "bplist"},
                           {"op": "debug", "command": bad},
                           {"op": "registers"}], settle_seconds=0)
    assert out["status"] == "INVALID" and out["code"] == "step_failed", out
    assert out["failed_at"] == 1 and out["steps_completed"] == 1, out
    assert out["failed"]["op"] == "debug" and out["failed"]["reply"]["code"] == "bad_argument"
    assert "Error in expression" in out["message"], out["message"]
    out = s.drive(act=[{"op": "debug", "command": bad}, {"op": "registers"}], settle_seconds=0)
    assert out["code"] == "step_failed" and out["act"]["failed_at"] == 0, out
    assert out["act"]["failed"]["reply"]["code"] == "bad_argument"


@pytest.mark.parametrize(
    ("command", "mutates"),
    [('printf "pc=%x\\n",pc', False), ('printf "--",pc', False),
     ('logerror "a=%x\\n",pc', False), ('print "d0=1"', False), ('printf "++"', False),
     ('printf "%d",d0=1', True), ("print pc,d0=1", True), ('bpset a,1,{printf "x"}', True),
     ('printf "a\\"=",d0=1', True), ('printf "a\\"=b"', False),
     ('printf "x";d0=1', True), ('printf "=";fill 100,1,1', True),
     ('printf "pc=%x', False), ('print d0=1,"x', True), ('printf "a\\\\",d0=1', False)],
    ids=lambda v: str(v),
)
def test_an_assignment_inside_a_quoted_string_is_text_and_one_outside_still_writes(
        command: str, mutates: bool) -> None:
    """The console never evaluates a quoted string; a `"` after a backslash does not close it."""
    assert console.mutates(command) is mutates, command


def test_one_quote_rule_for_the_classifier_and_the_control_note() -> None:
    """The control note and the write classifier share MAME's quote rule (`debugcon.cpp`)."""
    line = 'printf "a\\\\",temp3=1'
    assert lexer.temps_assigned(line) == set()
    assert lexer.blank_quoted(line) == 'printf "' + " " * (len(line) - 8)
    assert lexer.temps_assigned('printf "a",temp3=1') == {3}


def test_a_read_only_printf_through_debug_leaves_the_session_unaltered(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A `printf` with `=` in its format string moves neither `mutates` nor `altered`."""
    line = 'printf "pc=%x\\n",pc'
    _console(monkeypatch, tmp_path, {line: "pc=400\n"})
    out: dict[str, Any] = s.debug(command=line)
    assert out["status"] == "ok" and out["mutates"] is False, out
    assert out["session"]["altered"] is False and mstate.STATE.console_writes == 0
    out = s.perform(steps=[{"op": "debug", "command": line}, {"op": "registers"}], settle_seconds=0)
    assert out["status"] == "ok" and out["session"]["altered"] is False, out
    assert mstate.STATE.console_writes == 0


def test_the_detector_reads_only_captured_shapes_anchored_at_a_line_start() -> None:
    """An error shape inside a printed value, or an uncaptured spelling, is not a refusal."""
    assert console.refusals("print pc", "  Error in expression: x\n") is None
    assert console.refusals("print pc", "Error: unable to evaluate pc\n") is None
    assert console.refusals("print pc", "unknown command\n") is None, (
        "a parse error is the echo, the caret and the reason, not the reason alone")
    assert console.refusals("print pc", ">other\n ^\nunknown command\n") is None
    assert console.refusals("print pc", ">print pc\n ^\n") is None, "no reason line: no error"


@pytest.mark.parametrize(("word", "command"), [
    ("sl", "sl"), ("softr", "softreset"), ("fo", "fo"), ("foc", "focus"), ("gv", "gv"),
    ("GVBLANK", "gvblank"), ("wpl", "wplist"), ("s", "s"), ("st", None), ("pokew", None),
    ("", None),
])
def test_a_typed_word_resolves_to_the_command_the_console_runs(word: str,
                                                               command: str | None) -> None:
    """`internal_parse_command` (debugcon.cpp): the command itself, else its one prefix match."""
    assert console.resolve_command(word) == command


@pytest.mark.parametrize("command", ["n", "next", "o", "over", "s 3", "step", "out", "gv", "gp"])
def test_a_console_step_or_run_is_a_release_the_stub_sends_no_packet_for(command: str) -> None:
    assert console.releases(command) and console.mutates(command)


@pytest.mark.parametrize("answer", [
    "Unable to find device ':nope'", "Invalid CPU index 7", "Device :screen is not a CPU",
    "Memory space 'io' not found found for device ':maincpu'",
    "No matching memory region found for ':gfx9'",
    "Address 400 in logical space program does not map to anything",
    "Not enough parameters for format!", "Invalid offset", "Invalid screen number '3'",
    "Can't ignore all devices!", "Error in command: pokew 1,1",
])
def test_every_refusal_the_console_prints_is_one(answer: str) -> None:
    """Each is one of the console's own `printf`s (debugcon.cpp, debugcmd.cpp)."""
    line = ("bp 400,1,{pokew 1,1}" if answer.startswith("Error in command")
            else "dump 0,10,,,,:nope")
    found = console.refusals(line, answer + "\n")
    assert found is not None and [r.index for r in found.refused] == [0], found
    assert found.refused[0].error == answer and found.refused[0].stopped is False
