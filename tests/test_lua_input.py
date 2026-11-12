"""The Lua channel: input and the ports it reads back."""

from __future__ import annotations

from pathlib import Path

import pytest
from lua_support import (  # noqa: E402
    CONSOLE,
    _captured,
    _channel,
    _marks_of,
)
from session_doubles import refused  # noqa: E402

from scry_mame import lua  # noqa: E402
from scry_mame import server as s  # noqa: E402


def test_inputs_value_comes_back_as_the_32_bit_value_the_port_took(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """MAME's port value is unsigned and 32 bits wide, so a negative value reaches the port as its
    two's complement, and the reply says what the port took in the `0x` spelling a call takes
    back"""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = _captured(3)
    ses.marks[1] = [m.replace("#3", "#1") for m in _marks_of("MAME_MCP_INPUT#3")]
    out = s.input(port=":P1", field="Coin 1", value=-1, frames=4)
    assert out["status"] == "ok" and out["value"] == "0xffffffff", out
    # THE ROUTE, the word the DOSBox-X server uses for its own in-guest one.
    assert out["route"] == "ioport", out



def test_input_queues_the_script_and_reads_the_port_back_off_the_marks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The wrapper does not step"""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = _captured(3)
    ses.marks[1] = [m.replace("#3", "#1") for m in _marks_of("MAME_MCP_INPUT#3")]
    out = s.input(port=":P1", field="Coin 1", value=1, frames=4)
    assert out["status"] == "ok", out
    assert ses.stepped == 0, "a wrapper never single-steps"
    assert ses.stdin.getvalue().replace(b"#1", b"#3") in CONSOLE, "the chunk is the captured one"
    assert out["name"] == "Coin 1" and out["player"] == 0 and out["value"] == "0x00000001"
    assert out["mask"] == "0x00000400" and out["defvalue"] == "0x00000400"
    assert out["port_before"] == "0x0000dfff" and out["port_held"] == "0x0000dbff"
    assert out["active"] is True and out["released"] is True
    assert out["frame_set"] == 300 and out["frame_released"] == 304
    assert out["verdict"] == "ELAPSED" and out["frame_after"] - out["frame_before"] == 5
    assert out["session"]["altered"] is False, "a typed wrapper is not the raw form"
    assert list(out)[-1] == "session", "the envelope's shape survives the wrapper's fields"
    assert out["summary"] == "input :P1 'Coin 1': held 4 frames, active True, released at frame 304"


def test_input_refuses_in_the_consoles_words_when_the_field_does_not_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = _captured(4)
    out = refused("has no field No Such Field",
                  s.input(port=":P1", field="No Such Field", frames=2))
    assert out["code"] == "unknown_ref", "a field the machine lacks is a name resolving to nothing"


def test_input_cut_short_says_the_field_is_still_held_and_a_later_call_ignores_its_mark(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A run another stop cuts before the release frame leaves the field HELD and the notifier
    armed"""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1)
    ses.marks[1] = [_marks_of("MAME_MCP_INPUT#3 set")[0].replace("#3", "#1")]
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["status"] == "ok" and out["released"] is False
    assert out["active"]["available"] is False and out["port_held"]["available"] is False
    assert out["frame_release_planned"] == 304 and "still HELD" in out["note"]
    assert out["summary"] == "input :P1 'Coin 1': still HELD from frame 300, releases at 304"
    # The stale release lands in the log with the FIRST call's tag, before the second call runs.
    with open(ses.scratch / "error.log", "a") as log:
        log.write(_marks_of("MAME_MCP_INPUT#3 release")[0].replace("#3", "#1") + "\n")
    ses.answers[2] = ses.sentinel(2)
    ses.marks[2] = [_marks_of("MAME_MCP_INPUT#3 set")[0].replace("#3", "#2")]
    again = s.input(port=":P1", field="Coin 1", frames=4)
    assert again["released"] is False, "the first call's release is not the second's"


def test_input_with_no_set_mark_is_not_vouched_for_and_a_run_that_never_ticks_is_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1)
    out = refused("not proved held", s.input(port=":P1", field="Coin 1", frames=4))
    assert out["code"] == "readback_refused"
    # No answer at all (the run never emulated a frame): the script is still pending.
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.05)
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["pending"] is True and "pending" in out["summary"]


def test_input_refuses_its_arguments_before_the_pipe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    refused("one frame or more", s.input(port=":P1", field="Coin 1", frames=0))
    refused("both needed", s.input(port="", field="Coin 1"))
    assert ses.stdin.getvalue() == b""



@pytest.mark.parametrize(("error", "code"), [
    ("mcp:3: no port :P9", "unknown_ref"),
    ("mcp:5: port :P1 has no field Coin 9", "unknown_ref"),
    ("mcp:3: boom", "unexpected_answer"),
])
def test_inputs_own_script_raising_is_coded_by_what_it_raised(error: str, code: str) -> None:
    """The console prefixes the chunk's place (`mcp:N:`)"""
    assert lua.input_refusal_code(error) == code
