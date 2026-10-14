"""A value, a byte offset or a pen base is a JSON integer or a `0x` string, read by
`inputs.number_arg`, and nothing else: judged at the edges of that judge, at the MCP surface (the
schema offers both, the judge decides), in a batch step (`perform`, `drive`), in the probe's own
judging, at every body (which receives the integer whatever the spelling), and in what a reply
hands back.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import test_envelope_seam  # noqa: E402
from test_gfx_layout import CIRCUS_CHARLAYOUT  # noqa: E402

import mame_block as block  # noqa: E402
import mame_envelope as menvelope  # noqa: E402
import mame_film as mfilm  # noqa: E402
import mame_gfx as mgfx  # noqa: E402
import mame_inputs as inputs  # noqa: E402
import mame_locate as mlocate  # noqa: E402
import mame_lua as mlua  # noqa: E402
import mame_palette as mpalette  # noqa: E402
import mame_ramdac as mramdac  # noqa: E402
import mame_scan as mscan  # noqa: E402
import mame_sequence as sequence  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_sweep as msweep  # noqa: E402
import mame_write as mwrite  # noqa: E402
import server as s  # noqa: E402

# ------------------------------------------------------------------------------ the judge


@pytest.mark.parametrize("given,want", [
    (0, 0), (4660, 4660), (-1, -1), ("0x1234", 0x1234), ("0X1a", 0x1A), (" 0x10 ", 0x10),
    ("0x0", 0), ("0xffffffffffffffff", 0xFFFFFFFFFFFFFFFF),
])
def test_an_integer_or_a_0x_string_is_the_integer_it_spells(given: object, want: int) -> None:
    assert inputs.number_arg("value", given) == want


@pytest.mark.parametrize("given,says", [
    ("4660", "decimal text"), ("ff", "decimal text"), ("", "decimal text"),
    ("-0x10", "decimal text"), ("0x", "starts like hex"), ("0xg", "starts like hex"),
    ("0x1_0", "starts like hex"), (True, "integer or a `0x`"), (False, "integer or a `0x`"),
    (6.0, "integer or a `0x`"), (None, "integer or a `0x`"), ([16], "integer or a `0x`"),
])
def test_decimal_text_a_bool_and_anything_else_is_refused_naming_the_argument(
    given: object, says: str,
) -> None:
    with pytest.raises(mstate.Invalid) as e:
        inputs.number_arg("pen_base", given)
    assert e.value.code == "bad_argument" and "pen_base" in str(e.value), str(e.value)
    assert says in str(e.value), str(e.value)


# ------------------------------------------------------------------- at the MCP surface

def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return test_envelope_seam._call(name, args)[1]


_VIEW = {"layout": CIRCUS_CHARLAYOUT, "palette": "palette", "tag": "gfx1"}
_LOCATE = {"layouts": [CIRCUS_CHARLAYOUT], "patch": [0, 0, 8, 8], "tag": "gfx1"}
# A transparent pixel value reaches 0x12 only under a layout deep enough to hold it.
_LOCATE_DEEP = {**_LOCATE, "layouts": [{**CIRCUS_CHARLAYOUT, "planes": 5,
                                        "planeoffset": "{ 0, 1, 2, 3, 4 }"}]}
_SWEEP = {"tag": "gfx1", "palette": "palette"}

#: Every argument the rule covers: (tool, argument) -> the other arguments a call needs, and
#: where its body takes it (the module, the function, the position in the body's own call,
#: counting the session and the scratch). An argument added to the rule joins this table.
TABLE: dict[tuple[str, str], tuple[dict[str, Any], Any, str, int]] = {
    ("set_register", "value"): ({"name": "d0"}, mwrite, "set_register", 2),
    ("scan_filter", "value"): ({}, mscan, "scan_filter", 3),
    ("gfx_film", "value"): ({"trigger": "0x400"}, mfilm, "gfx_film", 4),
    ("input", "value"): ({"port": ":P1", "field": "Coin 1"}, mlua, "input_field", 4),
    ("read_block", "offset"): ({"tag": "blitram"}, block, "read_block", 4),
    ("gfx_view", "offset"): (_VIEW, mgfx, "gfx_view", 6),
    ("gfx_view", "pen_base"): (_VIEW, mgfx, "gfx_view", 10),
    ("gfx_locate", "offset"): (_LOCATE, mlocate, "gfx_locate", 6),
    ("gfx_locate", "transparent"): (_LOCATE_DEEP, mlocate, "gfx_locate", 9),
    ("gfx_sweep", "offset"): (_SWEEP, msweep, "gfx_sweep", 4),
    ("gfx_sweep", "pen_base"): (_SWEEP, msweep, "gfx_sweep", 9),
    ("palette", "first"): ({}, mpalette, "palette", 3),
    ("palette_log", "pen"): ({"palette_port": "ramdac"}, mramdac, "palette_log", 2),
}
NUMBERS = [(tool, others, arg) for (tool, arg), (others, *_) in TABLE.items()]


def test_the_table_is_every_argument_the_server_declares_a_number() -> None:
    """The table above against the registry: an argument declared `NumberArg` that no case
    holds, or a case whose argument is declared otherwise, fails by name."""
    declared = {(op, name) for op, fn in s._step_ops().items()
                for name in inputs.number_params(fn)}
    assert declared == {(t, a) for t, _, a in NUMBERS}, declared ^ {(t, a) for t, _, a in NUMBERS}


@pytest.mark.parametrize("tool,others,arg", NUMBERS)
def test_the_published_schema_offers_an_integer_and_a_string(
    tool: str, others: dict[str, Any], arg: str,
) -> None:
    schema = next(t for t in asyncio.run(s.mcp.list_tools()) if t.name == tool).input_schema
    kinds = {k.get("type") for k in schema["properties"][arg]["anyOf"]}
    assert {"integer", "string"} <= kinds, schema["properties"][arg]


@pytest.mark.parametrize("tool,others,arg", NUMBERS)
def test_a_0x_string_passes_and_decimal_text_or_a_bool_is_refused_at_the_surface(
    tool: str, others: dict[str, Any], arg: str,
) -> None:
    """With no machine, a `0x` value reaches the session gate (`no_session`); decimal text is the
    judge's refusal naming the argument, and a bool the schema's."""
    passed = _call(tool, {**others, arg: "0x1"})
    assert passed.get("code") == "no_session", passed
    text = _call(tool, {**others, arg: "16"})
    assert text["code"] == "bad_argument" and f"{arg}='16'" in text["message"], text
    assert "decimal text is refused" in text["message"], text
    flag = _call(tool, {**others, arg: True})
    assert flag["code"] == "bad_argument" and arg in flag["message"], flag


@pytest.mark.parametrize("tool,args,says", [
    ("gfx_film", {"trigger": "0x400", "value": "0x100"}, "0..0xff"),
    ("gfx_film", {"trigger": "0x400", "length": 2, "value": "0x10000"}, "0..0xffff"),
    ("gfx_view", {"layout": CIRCUS_CHARLAYOUT, "palette": "none", "tag": "gfx1",
                  "pen_base": "0x10"}, "pen_base picks pens"),
    ("read_block", {"ref": "0x400", "offset": "0x10"}, "`offset` goes with `tag`"),
    ("gfx_locate", {"layouts": [CIRCUS_CHARLAYOUT], "patch": [0, 0, 8, 8], "ref": "0x400",
                    "count": 1, "offset": "0x1"}, "`offset` goes with `tag`"),
])
def test_the_ranges_stay_each_tools_own_whichever_spelling_carried_the_number(
    tool: str, args: dict[str, Any], says: str,
) -> None:
    """The judge answers the integer and decides nothing about it: each tool's own range and
    pairing refuse a `0x` value exactly as they refuse the integer it spells."""
    reply = _call(tool, args)
    assert reply["code"] == "bad_argument" and says in reply["message"], reply
    as_int = {k: inputs.number_arg(k, v) if k in ("value", "offset", "pen_base") else v
              for k, v in args.items()}
    assert _call(tool, as_int)["message"] == reply["message"]


@pytest.mark.parametrize("tool,args", [
    ("gfx_film", {"trigger": "0x400", "value": "0xff"}),
    ("gfx_film", {"trigger": "0x400", "length": 4, "value": "0xffffffff"}),
    ("scan_filter", {"value": "0x0"}),
])
def test_the_largest_value_a_range_holds_passes_in_hex(tool: str, args: dict[str, Any]) -> None:
    assert _call(tool, args).get("code") == "no_session"


def test_a_negative_integer_is_still_each_tools_to_refuse() -> None:
    assert "negative" in _call("set_register", {"name": "d0", "value": -1})["message"]
    assert "unsigned" in _call("scan_filter", {"value": -1})["message"]


# --------------------------------------------------------------------------- in a batch

@pytest.mark.parametrize("tool,others,arg", NUMBERS)
def test_a_step_takes_the_same_spellings_through_the_same_judge(
    tool: str, others: dict[str, Any], arg: str,
) -> None:
    """A step carrying `0x` passes the preflight, as at the surface; decimal text in the THIRD
    step refuses the list before its first step runs, naming the step and the argument."""
    good = sequence.refuse_steps([{"op": tool, **others, arg: "0x1"}], s._step_ops())
    assert good is None, good
    bad = sequence.refuse_steps([{"op": "status"}, {"op": "status"},
                                 {"op": tool, **others, arg: "16"}], s._step_ops())
    assert bad is not None and bad["code"] == "bad_argument", bad
    assert [(e["step"], e["op"]) for e in bad["errors"]] == [(2, tool)], bad
    assert f"{arg}='16'" in bad["errors"][0]["message"], bad


def test_a_steps_range_is_judged_on_the_integer_its_0x_spells() -> None:
    bad = sequence.refuse_steps([{"op": "gfx_film", "trigger": "0x400", "value": "0x100"}],
                                s._step_ops())
    assert bad is not None and "0..0xff" in bad["errors"][0]["message"], bad


def test_perform_and_drive_refuse_decimal_text_before_any_step_runs() -> None:
    out = s.perform(steps=[{"op": "set_register", "name": "d0", "value": "4660"}])
    assert out["status"] == "INVALID" and "value='4660'" in json.dumps(out), out
    out = s.drive(act=[{"op": "scan_filter", "value": "4660"}])
    assert out["status"] == "INVALID" and "value='4660'" in json.dumps(out), out


# -------------------------------------------------------------- every body gets the int


@pytest.mark.parametrize("tool,others,arg", NUMBERS)
def test_every_body_receives_the_integer_whichever_spelling_the_caller_used(
    tool: str, others: dict[str, Any], arg: str,
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _others, module, name, at = TABLE[(tool, arg)]
    seen: list[object] = []

    def body(*a: Any) -> dict[str, Any]:
        seen.append(a[at])
        return menvelope.invalid("no_session", "the body was reached")
    monkeypatch.setattr(module, name, body)
    monkeypatch.setattr(s, "_stopped", lambda _why: (object(), tmp_path))
    monkeypatch.setattr(s, "_contact", lambda: (object(), tmp_path))
    for spelled in ("0x12", 0x12):
        reply = getattr(s, tool)(**others, **{arg: spelled})
        assert reply["message"] == "the body was reached", reply
    assert seen == [0x12, 0x12] and all(type(v) is int for v in seen), seen


# ------------------------------------------------- what comes back goes back in as it came

def test_set_register_echoes_its_value_at_the_registers_width_as_it_would_take_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The value sent is shown as `readback` is, through the one formatter, so the two compare as
    text and either goes back in as a `value`."""
    from test_server import _install, _RegisterSession
    ses = _RegisterSession(bits=16)
    _install(monkeypatch, ses, tmp_path)
    for spelled in ("0x12", 0x12):
        out = s.set_register("EAX", spelled)
        assert (out["value"], out["readback"], out["verified"]) == ("0x0012", "0x0012", True), out
        assert inputs.number_arg("value", out["value"]) == 0x12 == ses.values["EAX"]


def test_a_films_value_and_its_hits_come_back_written_0x_at_the_triggers_width(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from test_film import _serve_arm, _session
    ses = _session(monkeypatch, tmp_path)
    _serve_arm(ses, "m68k-dual")
    out = s.gfx_film(trigger="0x70001e", length=2, value="0x00ff", keep=3, frames=12)
    assert out["film"]["value"] == "0x00ff", out["film"]
    assert inputs.number_arg("value", out["film"]["value"]) == 0xFF


@pytest.mark.parametrize("length,want", [(1, "0x01"), (2, "0x0001"), (4, "0x00000001")])
def test_a_films_hit_and_baseline_are_shown_at_the_triggers_width(
    length: int, want: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A small value is padded to the trigger's own width, in the one spelling the film's value
    has, and goes back in as the same integer."""
    import dataclasses

    from test_film import _armed
    film = dataclasses.replace(_armed(monkeypatch, tmp_path)["film"], length=length)
    hit = mfilm._hit(0x21AC, 1, 899, film, None)["value"]
    base = mfilm._baseline({"baseline_frame": 899, "baseline_value": 1}, film)["baseline_value"]
    shown = dataclasses.replace(film, value=1).fields()["value"]
    assert hit == base == shown == want, (hit, base, shown)
    assert inputs.number_arg("value", want) == 1


# ------------------------------------------------------------------- the review's cases

@pytest.mark.parametrize("given", [None, True, 6.0, "0x", "-0x1", "16", [1]])
@pytest.mark.parametrize("tool,others,arg", NUMBERS)
def test_every_step_spelling_the_judge_refuses_is_refused_before_any_step_runs(
    tool: str, others: dict[str, Any], arg: str, given: object,
) -> None:
    """A step after a harmless one, carrying what no tool takes: the list is refused whole with
    the argument named, never run up to it. `None` is the absence only of an optional number."""
    optional = (tool, arg) in {("scan_filter", "value"), ("gfx_film", "value"),
                               ("palette_log", "pen"), ("gfx_locate", "transparent")}
    assert inputs.number_params(s._step_ops()[tool])[arg] is optional
    bad = sequence.refuse_steps([{"op": "status"}, {"op": tool, **others, arg: given}],
                                s._step_ops())
    if given is None and optional:
        assert bad is None, bad
        return
    assert bad is not None and [(e["step"], e["op"]) for e in bad["errors"]] == [(1, tool)], bad
    assert arg in bad["errors"][0]["message"], bad


def test_a_number_past_64_bits_is_refused_in_either_spelling() -> None:
    """Every number here is a value or an offset MAME's debugger holds in 64 bits; past that a
    `0x` string could spell an integer no reply or script can print."""
    assert inputs.number_arg("value", "0x" + "f" * 16) == (1 << 64) - 1
    assert inputs.number_arg("value", -(1 << 64) + 1) == -(1 << 64) + 1
    assert inputs.number_arg("value", "0x" + "0" * 40 + "1") == 1
    for wide in ("0x1" + "0" * 16, 1 << 64, -(1 << 64), "0x" + "f" * 3600):
        with pytest.raises(mstate.Invalid) as e:
            inputs.number_arg("value", wide)
        assert "64 bits" in str(e.value), str(e.value)


@pytest.mark.parametrize("given", ["-0x10", "+0x10", "0X", "0Xg"])
def test_a_sign_or_a_bare_0x_is_refused_in_words_that_fit_it(given: str) -> None:
    with pytest.raises(mstate.Invalid) as e:
        inputs.number_arg("offset", given)
    assert "without `0x`" not in str(e.value), str(e.value)
    assert "offset" in str(e.value)


def test_the_probe_judges_a_number_as_the_tool_reads_it() -> None:
    """The probe asks the server's own check about a call it never makes: a `0x` answer is
    judged on the integer it spells, decimal text refused as the tool refuses it."""
    import server
    server.probe_check("set_register", {}, {"name": "d0", "value": "0x2f00", "cpu": ""})
    with pytest.raises(mstate.Invalid, match="value='4660'"):
        server.probe_check("set_register", {}, {"name": "d0", "value": "4660", "cpu": ""})
    with pytest.raises(mstate.Invalid, match="0..0xff"):
        server.probe_check("gfx_film", {}, {"trigger": "0x400", "value": "0x100"})


@pytest.mark.parametrize("tool,others,arg", [
    ("palette", {}, "first"), ("palette_log", {"palette_port": "ramdac"}, "pen"),
    ("gfx_view", _VIEW, "pen_base"), ("gfx_sweep", _SWEEP, "pen_base"),
])
def test_every_pen_argument_is_judged_in_one_sentence(
    tool: str, others: dict[str, Any], arg: str,
) -> None:
    """One pen judge (`inputs.pen`), whatever the tool: `0x` is read as a pen is everywhere, and
    a number that is no pen is refused in the same words."""
    out = _call(tool, {**others, arg: -1})
    assert out.get("code") == "bad_argument", out
    assert out["message"] == f"{arg}=-1 is not a pen number", out


@pytest.mark.parametrize("call", [
    lambda d: s.memdump(ref="0x0", length=0, dest=d),
    lambda d: s.find(ref="0x0", length=0, data_hex="00"),
])
def test_a_zero_length_is_one_refusal_wherever_a_length_counts_bytes(
    call: Any, tmp_path: Path,
) -> None:
    out = call(str(tmp_path / "d.bin"))
    assert out.get("code") == "bad_argument", out
    assert out["message"] == "length=0 is below 1: a length counts bytes", out
