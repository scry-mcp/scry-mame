"""Each argument check written once, in the input module every tool imports: the natural-number
guard (`mame_inputs.natural`, its predicate `is_natural`) and the rectangle (`is_rectangle`), the
counts held to a range (`mame_inputs.count`), the bound on a wait
(`mame_inputs.seconds_bound`, zero taken where it means something), the regular-expression judge
(`mame_inputs.regex`, whose compiled pattern the log checks and `drive`'s hand back) and the rules
a console expression keeps (`mame_conditions.expression_fault`). A bool is an `int` to Python, so
each judge asks the type before the range, and each refusal keeps its caller's sentence."""

import inspect
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from session_doubles import refused

import mame_advance as advance
import mame_blits as mblits
import mame_conditions as conditions
import mame_envelope as menvelope
import mame_files as files
import mame_film as mfilm
import mame_inputs as inputs
import mame_locate as mlocate
import mame_mcp
import mame_running as running
import mame_screen as mscreen
import mame_sequence as sequence
import mame_state as mstate
import mame_watches as watches
import server as s

sys.path.insert(0, str(Path(__file__).resolve().parent / "live"))
from gfx_layouts import CIRCUS_CHAR  # noqa: E402


@pytest.mark.parametrize(("value", "lo", "hi", "ok"), [
    (0, 0, None, True), (5, 0, None, True), (-1, 0, None, False), (True, 0, None, False),
    (False, 0, None, False), (1.0, 0, None, True), (6.5, 0, None, False),
    (float("nan"), 0, None, False), (float("inf"), 0, None, False), ("1", 0, None, False),
    (None, 0, None, False),
    (3, 1, 3, True), (1, 1, 3, True), (4, 1, 3, False), (0, 1, 3, False),
])
def test_is_natural_is_an_int_and_not_a_bool_within_its_bounds(
        value: Any, lo: int, hi: int | None, ok: bool) -> None:
    assert inputs.is_natural(value, lo, hi) is ok


def test_natural_refuses_in_the_callers_own_words() -> None:
    with pytest.raises(mstate.Invalid) as err:
        inputs.natural("first", -1, " is not a tile number")
    assert (err.value.code, str(err.value)) == ("bad_argument", "first=-1 is not a tile number")
    with pytest.raises(mstate.Invalid, match=r"^count=9: 1\.\.8$"):
        inputs.natural("count", 9, ": 1..8", lo=1, hi=8)
    inputs.natural("count", 8, ": 1..8", lo=1, hi=8)


@pytest.mark.parametrize("seconds", [True, False, "5", None, 0, -1, 600.5])
def test_the_bound_on_a_wait_refuses_a_bool_a_string_and_a_value_outside_it(
        seconds: Any) -> None:
    with pytest.raises(mstate.Invalid, match=r"^seconds=.* is not a bound: .*more than zero"):
        inputs.seconds_bound(seconds)


def test_drive_bounds_its_wait_in_the_one_sentence() -> None:
    out = refused(r"^seconds=0 is not a bound", s.drive(act=[{"op": "status"}], expect="x",
                                                        seconds=0))
    assert out["code"] == "bad_argument", out


@pytest.mark.parametrize(("pattern", "said"), [
    (123, r"^pattern is a regular expression; got 123$"),
    ("", r"^pattern is a non-empty regular expression \('\.' for every line\)$"),
    ("(", r"^pattern='\(' does not compile: "),
])
def test_one_regex_judge_refuses_a_non_string_an_empty_one_and_one_that_does_not_compile(
        pattern: Any, said: str) -> None:
    with pytest.raises(mstate.Invalid, match=said):
        inputs.regex("pattern", pattern)


@pytest.mark.parametrize("tool", ["log", "log_wait"])
def test_an_empty_pattern_is_refused_by_the_log_readers_too(tool: str) -> None:
    """One rule for every `pattern`: empty never means every line, here as in `drive`."""
    reply = s.log(pattern="", channel="emulator") if tool == "log" else s.log_wait(
        pattern="", channel="emulator", seconds=1.0)
    assert reply["code"] == "bad_argument" and "'.' for every line" in reply["message"], reply


def test_log_refuses_a_pattern_that_is_not_a_string() -> None:
    """A pattern is judged as a string before it is compiled, by `log` as by every tool."""
    with pytest.raises(mstate.Invalid, match="is a regular expression"):
        files.check_log(123, "emulator")  # type: ignore[arg-type]


@pytest.mark.parametrize(("text", "rule"), [
    ("", "empty"), ("   ", "empty"), ("a,b", "split"), ("a\nb", "split"),
    ("d0=1", "writes"), ("1;g", "writes"), ("{x}", "writes"), ("d0==1", None),
    ("w@0x400+2", None),
])
def test_one_expression_rule_set_names_the_rule_that_failed(text: str, rule: str | None) -> None:
    fault = conditions.expression_fault(text)
    assert (fault[0] if fault else None) == rule, fault


def test_a_count_held_to_a_range_refuses_a_bool_and_a_string_and_takes_a_json_number() -> None:
    """`True` is an `int` to Python and lies inside 1..N, and a string would reach a comparison:
    the count helpers judge the type first. An integral float is the JSON number a client's
    schema turns into the int, so it stays a count."""
    for value in (True, "2"):
        with pytest.raises(mstate.Invalid, match=rf"^limit is a count; got {value!r}$"):
            inputs.count("limit", value, 400)  # type: ignore[arg-type]
    with pytest.raises(mstate.Invalid, match=r"^limit=401 is outside 1\.\.400$"):
        inputs.count("limit", 401, 400)
    # ONE JUDGE, THE FLOOR ITS PARAMETER: no ceiling says "or more", and a floor of 0 takes 0.
    with pytest.raises(mstate.Invalid, match=r"^length=0 is below 1: a length counts bytes$"):
        inputs.count("length", 0, tail=": a length counts bytes")
    inputs.count("limit", 0, 400, lo=0)
    with pytest.raises(mstate.Invalid, match=r"^limit=-1 is outside 0\.\.400 rows$"):
        inputs.count("limit", -1, 400, " rows", lo=0)
    inputs.count("limit", 2.0, 400)  # type: ignore[arg-type]


def test_a_signature_crop_refuses_a_bool() -> None:
    out = s.screen_signature(crop=[0, 0, True, 8])
    assert out["status"] == "INVALID" and out["message"].startswith("crop="), out


@pytest.mark.parametrize("value", [True, False, "5"])
@pytest.mark.parametrize(("name", "judge"), [
    ("frames", lambda v: advance.check_run_for(frames=v)),
    ("milliseconds", lambda v: advance.check_run_for(milliseconds=v)),
    ("length", lambda v: watches.check_watch_add(ref="0x1000", mode="change", length=v)),
    ("seconds", lambda v: running.check_resume(seconds=v)),
    ("settle_seconds", lambda v: sequence.validate_settle(v)),
])
def test_a_count_or_a_wait_refuses_a_bool_and_a_string_naming_itself(
        name: str, judge: Any, value: Any) -> None:
    """A bool is an `int` to Python and lies inside every range from zero; a string reaches a
    comparison and raises: each guard asks the type first, in its caller's sentence."""
    with pytest.raises(mstate.Invalid, match=rf"^{name}={re.escape(repr(value))} "):
        judge(value)


def test_resume_takes_zero_as_no_deadline_and_false_as_a_mistake() -> None:
    running.check_resume(seconds=0)
    running.check_resume(seconds=0.0)
    running.check_resume(seconds=inputs.WAIT_MAX_S)
    with pytest.raises(mstate.Invalid, match=r"^seconds=False is not a bound: .*0 \(no deadline\)"):
        running.check_resume(seconds=False)


def test_the_bound_on_a_wait_can_take_zero_and_then_says_what_zero_means() -> None:
    inputs.seconds_bound(0, name="settle_seconds", zero_means="never wait")
    inputs.seconds_bound(inputs.WAIT_MAX_S, name="settle_seconds", zero_means="never wait")
    for bad in (-0.001, inputs.WAIT_MAX_S + 0.001, True, False, "0", None):
        with pytest.raises(mstate.Invalid,
                           match=r"^settle_seconds=.* is not a bound: .*0 \(never wait\) or "
                                                 r"more than zero and at most 600"):
            inputs.seconds_bound(bad, name="settle_seconds", zero_means="never wait")
    with pytest.raises(mstate.Invalid, match=r"^seconds=0 is not a bound: .*more than zero and"):
        inputs.seconds_bound(0)


@pytest.mark.parametrize(("value", "zero_means", "floor"), [
    (True, "", "more than zero"),
    (False, "no deadline", "0 (no deadline) or more than zero"),
    ("5", "", "more than zero"),
    (None, "never wait", "0 (never wait) or more than zero"),
    (float("nan"), "", "more than zero"),
    (float("nan"), "no deadline", "0 (no deadline) or more than zero"),
    (-1, "no deadline", "0 (no deadline) or more than zero"),
    (0, "", "more than zero"),
    (inputs.WAIT_MAX_S + 0.5, "", "more than zero"),
    (float("inf"), "no deadline", "0 (no deadline) or more than zero"),
])
def test_the_bound_on_a_wait_says_what_every_value_it_refuses_is_not(
        value: Any, zero_means: str, floor: str) -> None:
    """The refusal is a sentence the refused value fails: a bool is an `int` to Python, `True`
    inside every range and `False` inside one that takes zero, so the sentence names the type
    before the range."""
    with pytest.raises(mstate.Invalid) as err:
        inputs.seconds_bound(value, zero_means=zero_means)
    assert str(err.value) == (f"seconds={value!r} is not a bound: a number of seconds, never a "
                              f"bool, {floor} and at most {inputs.WAIT_MAX_S}")


def test_the_log_checks_and_drive_hand_back_the_patterns_they_compiled() -> None:
    """The regex a check judged is the one the tool searches with, handed back compiled."""
    rx = files.check_log("a+", "emulator")
    assert isinstance(rx, re.Pattern) and rx.pattern == "a+"
    rx = files.check_log_wait(".", "emulator")
    assert isinstance(rx, re.Pattern) and rx.pattern == "."
    pattern, expect = sequence.check_drive([{"op": "status"}], "x+", None, "b", 40)
    assert (pattern.pattern, expect.pattern if expect else None) == ("b", "x+")
    assert sequence.check_drive([{"op": "status"}], "", None, ".", 40)[1] is None


@pytest.mark.parametrize(("value", "ok"), [
    ([0, 0, 1, 1], True), ((2, 3, 4, 5), True), ([0, 0, 0, 8], False), ([0, 0, 8, 0], False),
    ([-1, 0, 1, 1], False), ([0, 0, 1], False), ([0, 0, 1, 1, 1], False),
    ([True, 0, 1, 1], False), ([0, 0, 1.5, 1], False), ([0, 0, 1.0, 1], True), ("abcd", False),
    (5, False),
    (None, False),
])
def test_a_rectangle_is_four_naturals_with_a_width_and_a_height_above_zero(
        value: Any, ok: bool) -> None:
    assert inputs.is_rectangle(value) is ok


@pytest.mark.parametrize("rect", ["abcd", 5, [0, 0, 1], [0, 0, 0, 8], [True, 0, 1, 1]])
@pytest.mark.parametrize(("named", "judge"), [
    ("crop", lambda r: mscreen.check_screen_view(mode="render", crop=r)),
    ("crop", lambda r: mfilm.check_gfx_film(trigger="0x70001e", crop=r)),
    ("area", lambda r: mblits.check_gfx_blits(draw_command="blit", area=r)),
    ("patch", lambda r: mlocate.check_gfx_locate(layouts=[CIRCUS_CHAR], patch=r, tag="gfx1")),
])
def test_every_rectangle_is_one_rule_said_in_its_callers_words(
        named: str, judge: Any, rect: Any) -> None:
    with pytest.raises(mstate.Invalid, match=rf"^{named}=.* is \[x, y, width, height\]"):
        judge(rect)


COUNT_JUDGES = [
    ("natural", lambda v: inputs.natural("count", v, " is not a count")),
    ("count", lambda v: inputs.count("count", v, 400)),
    ("count with no ceiling", lambda v: inputs.count("count", v)),
]


@pytest.mark.parametrize(("judge", "check"), COUNT_JUDGES, ids=[j for j, _ in COUNT_JUDGES])
def test_every_count_judge_takes_an_integral_float_and_refuses_the_rest(
        judge: str, check: Any) -> None:
    """One rule in every judge of a count: `6.0` is exactly the integer 6, which is what a
    client's schema delivers as the int, so a direct call is judged as the wire is; a fractional
    float counts nothing, and neither does `nan` or an infinity, none of which is integral."""
    check(6.0)
    check(6)
    for value in (6.5, float("nan"), float("inf"), float("-inf"), True, "6"):
        with pytest.raises(mstate.Invalid) as err:
            check(value)
        assert err.value.code == "bad_argument" and "count" in str(err.value), (judge, value)


@pytest.mark.parametrize("value", [True, "8", 5, [True, 1], [1, "2"], [1, 2, 3], None])
@pytest.mark.parametrize(("name", "judge"), [
    ("crop", lambda v: s.screen_signature(crop=v)),
    ("point", lambda v: s.screen_view(mode="pixel", point=v)),
])
def test_a_list_of_naturals_is_one_rule_and_never_a_type_error(
        name: str, judge: Any, value: Any) -> None:
    """`crop` and `point` are lists of naturals, judged by one predicate: a number, a string or
    a list of the wrong length is refused in the caller's sentence, never a `TypeError` from
    `len()` on what was not a list."""
    if value is None and name == "crop":
        return                  # no crop is the whole screen, an answer and not a refusal
    out = judge(value)
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert f"`{name}`" in out["message"] or f"{name}=" in out["message"], out["message"]


@pytest.mark.parametrize("value", [True, "1", 5, [True], [-1], [3.0], ["16"]])
def test_the_isolate_pens_refuse_what_is_not_a_list_of_pens(value: Any) -> None:
    """The list is judged as a list, and each item as every pen is: `pens[0]` named."""
    out = s.screen_view(mode="isolate", pens=value)
    assert out["status"] == "INVALID" and out["message"].startswith("pens"), out
    if isinstance(value, list):
        assert out["message"].startswith("pens[0]"), out


@pytest.mark.parametrize("value", [False, True, "0"])
def test_an_expr_watch_refuses_a_length_that_is_not_a_count(value: Any) -> None:
    """An expr watch takes no length, and a length that is not a count is refused as one, so
    `length=False` is never read as no length."""
    with pytest.raises(mstate.Invalid, match=rf"^length={re.escape(repr(value))} "):
        watches.check_watch_add(ref="1+1", mode="expr", length=value)


@pytest.mark.parametrize("value", [True, "4"])
@pytest.mark.parametrize(("name", "judge"), [
    ("frames", lambda v: s.input(port=":IN0", field="Coin 1", frames=v)),
    ("frames", lambda v: s.record(frames=v)),
    ("frames", lambda v: s.audio_record(frames=v)),
])
def test_a_held_or_recorded_frame_count_refuses_a_bool_and_a_string(
        name: str, judge: Any, value: Any) -> None:
    out = judge(value)
    assert out["status"] == "INVALID" and out["message"] == f"{name} is a count; got {value!r}", out


def _annotation(tool: str, arg: str) -> str:
    """`arg`'s annotation as the tool wrapper reads it: the source's text."""
    ann = inspect.signature(getattr(s, tool)).parameters[arg].annotation
    assert isinstance(ann, str), ann
    return ann


@pytest.mark.parametrize(("annotation", "bare"), [
    ("int", "int"),
    ("Annotated[int, inputs.vocabulary(mfilm.LENGTHS)]", "int"),
    ("list[Annotated[int, inputs.bounds(1, ml.PLANES_MAX)]] | None", "list[int] | None"),
    ("list[list[Annotated[int, inputs.vocabulary(msweep.SIDES)]]] | None",
     "list[list[int]] | None"),
    ("Annotated[str, inputs.vocabulary((\"\", *launch.DISPLAYS))]", "str"),
])
def test_an_annotation_is_read_as_the_type_its_schema_half_wraps(
        annotation: str, bare: str) -> None:
    assert inputs.unannotated(annotation) == bare


def test_a_count_published_with_a_schema_half_still_reaches_its_body_as_an_int() -> None:
    """A count whose annotation carries its schema half (`Annotated[int, ...]`, or a list of
    them) is still a count to the wrapper: `length=2.0` is the length 2, never a float that a
    shift downstream refuses with a TypeError."""
    assert inputs.integral_counts(2.0, _annotation("gfx_film", "length")) == 2
    assert type(inputs.integral_counts(2.0, _annotation("gfx_film", "length"))) is int
    planes = inputs.integral_counts([4.0, 8.0], _annotation("gfx_sweep", "planes"))
    assert planes == [4, 8] and all(type(v) is int for v in planes), planes
    sizes = inputs.integral_counts([[8.0, 16.0]], _annotation("gfx_sweep", "sizes"))
    assert sizes == [[8, 16]] and all(type(v) is int for v in sizes[0]), (
        "a list of lists of counts, at every depth: `range(8.0)` downstream is a TypeError")
    out = s.gfx_film(trigger="0x70001e", length=2.0, value=1)
    assert out["code"] == "no_session", out


def test_every_body_behind_a_tool_receives_an_integral_float_as_the_int_it_equals(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The judges take `6.0` as the count 6; the tool wrapper hands the body the int, a scalar
    count and every count of a list alike, so `range()` or a `%x` downstream never meets a
    float. A fractional float is left as it came, for its judge to refuse."""
    seen: dict[str, Any] = {}
    for tool in ("step", "screen_view"):
        monkeypatch.setitem(mame_mcp.BOUNDARY.summaries, tool, lambda args, reply: "the body ran")
    monkeypatch.setattr(s, "stopped", lambda what: (None, None))
    monkeypatch.setattr(advance, "step", lambda ses, scratch, count, mode, cpu: seen.update(
        count=count) or menvelope.envelope({}))
    monkeypatch.setattr(mscreen, "screen_view", lambda *a, **k: seen.update(point=a[4]) or (
        menvelope.envelope({})))
    s.step(count=2.0)
    assert seen["count"] == 2 and type(seen["count"]) is int, seen
    s.screen_view(mode="pixel", point=[3.0, 4.0])
    assert seen["point"] == [3, 4] and all(type(v) is int for v in seen["point"]), seen
    assert inputs.integral_counts(2.5, "int") == 2.5
    assert inputs.integral_counts(True, "int") is True
    assert inputs.integral_counts([1.0, "x"], "list[int] | None") == [1, "x"]
    assert inputs.integral_counts(3.0, "float") == 3.0 and type(
        inputs.integral_counts(3.0, "float")) is float


def test_every_default_a_check_holds_is_its_tools() -> None:
    """A default is the tool's signature's: a batch step's preflight fills what the step left out
    from it (`sequence.refuse_steps`). The check keeps its own copy because its module calls it
    with only some arguments, positionally; where both hold one they are held equal here, so a
    change in one place and not the other goes red by name."""
    import mame_args as margs

    compared, drifted = 0, []
    for tool, check in margs.BY_TOOL.items():
        offered = inspect.signature(inspect.unwrap(getattr(s, tool))).parameters
        for name, p in inspect.signature(check).parameters.items():
            if name not in offered or p.kind is p.VAR_KEYWORD:
                continue
            mine, theirs = p.default, offered[name].default
            if p.empty in (mine, theirs):
                continue                # one side has none: the step carries it, or the fill does
            compared += 1
            if mine != theirs:
                drifted.append(f"{tool}.{name}: tool {theirs!r} vs check {mine!r}")
    assert compared > 100, f"compared {compared} defaults, so the walk examined almost nothing"
    assert not drifted, drifted


def test_the_isolate_pens_written_0x_reach_the_body_as_the_ints_they_spell(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Every pen takes `0x`, each of a list's too: the wrapper reads them, and the body is handed
    the integers."""
    seen: dict[str, Any] = {}
    monkeypatch.setitem(mame_mcp.BOUNDARY.summaries, "screen_view",
                        lambda args, reply: "the body ran")
    monkeypatch.setattr(s, "stopped", lambda what: (None, None))
    monkeypatch.setattr(mscreen, "screen_view", lambda *a, **k: seen.update(pens=a[3]) or (
        menvelope.envelope({})))
    s.screen_view(mode="isolate", pens=["0x31", 50])
    assert seen["pens"] == [0x31, 50] and all(type(v) is int for v in seen["pens"]), seen


def test_a_step_that_leaves_an_argument_out_is_judged_with_the_tools_default(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The preflight fills what a step left out from the TOOL's signature, so the check judges
    the call the step will make even where the check's own default says something else."""
    seen: dict[str, Any] = {}

    def check(length: int = 999, ref: str = "", **_: Any) -> None:
        seen["length"] = length

    monkeypatch.setitem(sequence.BY_OP, "read_memory", check)
    assert sequence.refuse_steps([{"op": "read_memory", "ref": "0x0"}], s._step_ops()) is None
    assert seen["length"] == inspect.signature(s.read_memory).parameters["length"].default, seen
