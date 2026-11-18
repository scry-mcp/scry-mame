"""The server's guarantees: the roster, the descriptions, the replies, the refusals."""

from __future__ import annotations

import asyncio
import json
import tomllib
from pathlib import Path
from typing import Any

import pytest
from scry_core.reply_contract import unavailable  # noqa: E402
from server_support import (  # noqa: E402
    _running,
)
from session_doubles import (  # noqa: E402
    documented,
    published,  # noqa: E402
)

from scry_mame import (
    advance,  # noqa: E402
    read,  # noqa: E402
    running,  # noqa: E402
    summaries,  # noqa: E402
)
from scry_mame import envelope as menvelope  # noqa: E402
from scry_mame import gdb_session as g  # noqa: E402
from scry_mame import mcp as mame_mcp  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402


def test_the_server_declares_instructions_and_they_name_what_a_caller_needs() -> None:
    """The `instructions` field is how the PROTOCOL hands a session the server's own contract."""
    text = s.mcp.instructions
    assert text, "the server declares no instructions at all"
    # ABSENCE, not just presence. A presence assertion cannot say "and does not ALSO claim X",
    # so it passes against a text carrying the true sentence beside the false one.
    for phrase, why in (
        ("ToolSearch", "the deferred-tools rule is the session's own, loaded every session, "
                       "and it describes the CLIENT rather than this server"),
        ("haystack", "the generic 'ask narrowly' is the session's own rule too"),
        ("byte for byte", "rom_check reads 16 bytes at one address; 'byte for byte against the "
                          "ROM' is what a caller reads as the whole image"),
        ("wall-clock", "the MAME clock rule is the session's own"),
        ("flat out", "the MAME clock rule is the session's own"),
    ):
        assert phrase not in text, f"the instructions carry {phrase!r}: {why}"
    assert "reference_rom" in text, (
        "rom_check needs the reference ROM and the server does not remember it"
    )
    assert "reference_base" in text, (
        "a caller following the instructions with a raw V30 image is otherwise refused OUTSIDE"
    )
    assert ("`memdump`, `snapshot` answer with a PATH"
            in " ".join(text.split())), "the instructions do not name the file-returning tools"
    assert "Files" in mame_mcp.ROSTER.answering_split()[0] and (
        mame_mcp.ROSTER.running_sentence() in " ".join(text.split())), (
        "a caller with the machine running would stop it before a file tool")
    assert "16 bytes" in text, "a spot check must not read as the whole image"
    assert "STOPPED" in text, (
        "rom_check is a memory read, and a read against a RUNNING machine does not come back as "
        "data: a caller told to run it after `monitor go` gets a transport error, from the one "
        "tool whose job is to say whether the instrument is honest"
    )


def test_every_tool_has_a_live_case_calling_it_through_the_server() -> None:
    """A tool with no live case is a tool whose green means nothing."""
    import ast

    live = Path(__file__).parent / "live" / "live_check.py"
    called: set[str] = set()
    for node in ast.walk(ast.parse(live.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "s"):
            called.add(node.func.attr)
    registered = {t.name for t in s.mcp._tool_manager.list_tools()}
    missing = sorted(registered - called)
    assert not missing, (
        f"these tools have no live case that CALLS them through the server: {missing}")


def test_a_batch_is_refused_whole_before_any_step_runs_even_with_no_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """NOTHING IN A STEP NEEDS A MACHINE TO BE WRONG."""
    mstate.STATE.kill()
    for later in ({"op": "memdump", "ref": "0x0", "length": 8, "dest": "relative.bin"},
                  {"op": "snapshot", "dest": "relative.png"},
                  {"op": "record", "frames": 2, "dest": "relative.avi"},
                  {"op": "audio_record", "frames": 2, "dest": "relative.wav"}):
        out = s.perform(steps=[{"op": "status"}, later])
        assert out["code"] == "bad_argument", (later, out)
        assert (out["ran"] == []
                and out["steps_completed"] == 0), "a step ran before the list was refused"
        assert out["failed_at"] == 1, out
        assert "must be an absolute path" in out["errors"][0]["message"], out["errors"][0]


def test_a_refusal_that_moved_nothing_records_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The other side of `record_own_stop`."""
    _running(monkeypatch, tmp_path)

    def must_not_survey(*_: Any) -> dict[str, Any]:
        raise AssertionError("a refusal that moved nothing surveyed the machine")

    monkeypatch.setattr(running, "survey", must_not_survey)
    refused_ = s.read_block(tag="main cpu")
    assert refused_["code"] == "bad_argument", refused_
    assert mstate.STATE.last_stop["seq"] == 1 and mstate.STATE.last_stop["cause"] == "start"


def test_the_sdk_injects_the_context_and_the_schema_does_not_show_it() -> None:
    """`ctx` is found by its type through the wrapper."""
    for name in ("run_to", "run_for", "resume", "log_wait"):
        tool = s.mcp._tool_manager.get_tool(name)
        assert tool is not None and tool.context_kwarg == "ctx", name
        assert "ctx" not in tool.parameters.get("properties", {}), name
    for name in ("step", "stop", "registers"):
        tool = s.mcp._tool_manager.get_tool(name)
        assert tool is not None and tool.context_kwarg is None, name


def test_the_session_block_says_whether_the_machine_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    assert menvelope.session_block()["running"] is False
    ses.go()
    assert menvelope.session_block()["running"] is True
    assert list(menvelope.session_block()) == ["alive", "running", "altered", "omitted",
                                                       "how"]
    assert list(menvelope.session_block(True)) == ["alive", "running", "altered",
                                                   "altering_writes", "console"]


def test_the_live_interlock_is_declared_in_the_package() -> None:
    """The live tier of this package is a script and pytest collects none of it today."""
    here = Path(__file__).resolve().parent.parent
    mine = tomllib.loads((here / "pyproject.toml").read_text(encoding="utf-8"))
    section = mine.get("tool", {}).get("pytest", {}).get("ini_options", {})
    assert "not live" in section.get("addopts", ""), (
        "this package does not deselect the live tier by itself")
    assert any(m.startswith("live:") for m in section.get("markers", [])), section


def test_an_invalid_summary_is_cut_at_a_word_and_says_so() -> None:
    """The summary is one line a person reads without the JSON, so a long refusal is cut there."""
    message = "the write side of 0x4a0 is unmapped: " + "a change watch there can never fire " * 6
    line = mame_mcp.BOUNDARY.line("watch_add", {}, {"status": "INVALID", "code": "bad_argument",
                                        "message": message})
    head = "watch_add: INVALID (bad_argument), "
    assert line.startswith(head), line
    shown = line.removeprefix(head)
    assert shown.endswith("...") and len(shown) <= 124, shown
    kept = shown.removesuffix("...")
    assert message.startswith(kept) and message[len(kept)] == " ", "cut at a word, never inside one"
    short = mame_mcp.BOUNDARY.line("x", {}, {"status": "INVALID", "code": "c", "message": "short"})
    assert short == "x: INVALID (c), short"


def test_the_docstrings_name_what_the_replies_carry_and_what_by_accepts() -> None:
    """`start` answers `symbols_typed` beside `symbols`."""
    assert "`symbols_typed`" in documented("start")
    (tool,) = [t for t in asyncio.run(s.mcp.list_tools()) if t.name == "breakpoint_at"]
    assert tool.input_schema["properties"]["by"]["enum"] == ["auto", "symbol", "address"]
    assert "never an expression" in published("breakpoint_at")


def test_each_reason_a_run_has_no_cycles_is_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """`cycles` unavailable names which of the three it is."""
    def refused(_ses: object, _names: list[str]) -> list[int]:
        raise g.SessionError("the console refused `print totalcycles`")

    assert "no baseline" in str(advance._span(None, None, None, None))  # type: ignore[arg-type]
    assert "each cpu keeps its own" in str(
        advance._span(None, 100, ":maincpu", ":subcpu"))  # type: ignore[arg-type]
    monkeypatch.setattr(read, "print_values", refused)
    assert advance._span(None, 100, ":maincpu", ":maincpu") == unavailable(  # type: ignore[arg-type]
        "`totalcycles` could not be read after the run: the console refused `print totalcycles`")


def test_a_broken_sessions_refusal_carries_the_reason_as_a_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.broken = "the stub sent nonsense"
    out = s.registers()
    assert out["code"] == "session_broken" and out["broken"] == "the stub sent nonsense"




@pytest.mark.parametrize(("name", "args", "reply", "expected"), [
    ("memdump", {"ref": "0x0"}, {"bytes": 32, "path": "/p"}, "memdump 0x0: 32 bytes to /p"),
    ("disassemble", {"ref": "0x0"}, {"lines": ["a", "b", "c"], "addr": "0x0"},
     "disassemble 0x0: 3 lines at 0x0"),
    ("snapshot", {}, {"bytes": 448, "path": "/p"}, "snapshot: 448 bytes at /p"),
    ("write", {"ref": "0x2031fc"}, {"bytes_written": 4, "verified": True},
     "write 0x2031fc: 4 bytes, verified True"),
    ("run_to", {"ref": "0x4a0"}, {"verdict": "TARGET", "control_hits": 3},
     "run_to 0x4a0: TARGET, control counted 3"),
    ("debug", {"command": "help"}, {"mutates": False, "clipped": False}, "debug 'help'"),
    ("debug", {"command": "poke"}, {"mutates": True, "clipped": True, "output_chars": 9000},
     "debug 'poke', mutates, 9000 chars to a file"),
    ("rom_check", {}, {"rom_check": "OK", "query_s": 0.0011, "cpu": ":maincpu"},
     "rom_check :maincpu: OK, 1.1 ms per query"),
    ("state_write", {"method": "save"}, {"name": "s1", "bytes": 100, "frame": 7},
     "state_write save: s1, 100 bytes at frame 7"),
    ("log_wait", {"channel": "emulator", "pattern": "x"},
     {"verdict": "TARGET", "already": False, "waited_s": 1.5},
     "log_wait emulator /x/: matched after 1.5 s"),
    ("log_wait", {"channel": "emulator", "pattern": "x"},
     {"verdict": "TARGET", "already": True, "waited_s": 0.0},
     "log_wait emulator /x/: matched already there"),
    ("log_wait", {"channel": "emulator", "pattern": "x"},
     {"verdict": "TIMEOUT", "waited_s": 2.0, "arrived_during": 3},
     "log_wait emulator /x/: TIMEOUT, no match in 2.0 s, 3 lines arrived"),
    ("resume", {"seconds": 0}, {}, "resume: running, no wait asked"),
    ("resume", {"seconds": 2.0}, {"verdict": "TIMEOUT", "waited_s": 2.0},
     "resume: TIMEOUT, still running after 2.0 s"),
    ("resume", {"seconds": 2.0}, {"verdict": "OTHER_STOP", "pc": "0x000004a0", "cause": "b"},
     "resume: OTHER_STOP at pc 0x000004a0 (b)"),
    ("perform", {}, {"steps_completed": 2, "verdict": "TIMEOUT"},
     "perform: 2 steps completed, TIMEOUT"),
    ("drive", {}, {"verify": {"checked": True, "seen": False, "verdict": "TIMEOUT"}},
     "drive: no reaction seen (TIMEOUT)"),
    ("drive", {}, {"act": {"verdict": "TIMEOUT"}, "verify": {"available": False}},
     "drive: input TIMEOUT, reaction could not be checked"),
    ("drive", {}, {"verify": {"checked": False}}, "drive: sent, reaction not checked"),
    ("registers", {}, {"regs": {"D0": "0", "D1": "1"}}, "registers: 2 registers"),
    ("registers", {}, {"regs": {"D0": "0"}, "superseded": True},
     "registers: 1 register, from the last stop"),
    ("breakpoint_at", {"ref": "0x4a0"}, {"armed": True, "while_running": True, "addr": "0x4a0"},
     "breakpoint_at 0x4a0: armed at 0x4a0 while running"),
    ("breakpoint_at", {"ref": "0x4a0"}, {"armed": True, "while_running": False, "addr": "0x4a0"},
     "breakpoint_at 0x4a0: armed at 0x4a0"),
    ("declaration_list", {"kind": "regpoint"},
     {"regpoints": [{"state": "armed"}, {"state": "armed"}, {"state": "gone"}]},
     "declaration_list regpoint: 3 regpoints (2 armed)"),
    ("regpoint_add", {}, {"ref": "d1==1", "armed": True, "while_running": True, "index": 1},
     "regpoint_add d1==1: armed, index 1 while running"),
    ("regpoint_add", {}, {"ref": "d1==1", "armed": True, "while_running": False, "index": 1},
     "regpoint_add d1==1: armed, index 1"),
    ("declaration_list", {"kind": "watch"},
     {"watches": [{"state": "armed"}, {"state": "armed"}, {"state": "evaluated"}]},
     "declaration_list watch: 3 watches (2 armed)"),
    ("declaration_list", {"kind": "watch"},
     {"watches": [{"state": "tallied"}, {"state": "captured"}, {"state": "evaluated"},
                  {"state": "no_dump_yet", "installed": True},
                  {"state": "no_dump_yet", "installed": False, "pending": True}]},
     "declaration_list watch: 5 watches (3 armed)"),
    ("step", {"count": 5}, {"instructions_completed": 2, "mode": "into", "pc": "0x000004a0"},
     "step 2 into: pc 0x000004a0"),
    ("watch_add", {"ref": "x"}, {"mode": "expr", "state": "evaluated", "reading": {"hex": "0x1"}},
     "watch_add x: expr watch evaluated, 0x1"),
    ("run_for", {"milliseconds": 100},
     {"verdict": "ELAPSED", "frame_before": 0, "frame_after": 5},
     "run_for 100 ms: ELAPSED, frame 0 to 5"),
    ("machine_map", {}, {"counts": {"cpus": 2}, "truncated": False}, "machine_map: 2 cpus"),
    ("machine_map", {}, {"counts": {"cpus": 2}, "truncated": True},
     "machine_map: 2 cpus, some sections cut (see `counts`)"),
])
def test_the_summary_line_of_each_tool_says_what_came_back(
    name: str, args: dict[str, Any], reply: dict[str, Any], expected: str,
) -> None:
    """One line per tool, in the tool's own words."""
    assert mame_mcp.BOUNDARY.line(name, args, {"status": "ok", **reply}) == expected


def test_a_refusal_is_clipped_for_the_summary_line_at_a_word_and_never_inside_one() -> None:
    """The ceiling is where a line stops being a line."""
    assert summaries.clipped("a" * 120) == "a" * 120
    assert summaries.clipped("a" * 121) == "a" * 120 + "..."
    assert summaries.clipped("a" * 100 + " " + "b" * 30) == "a" * 100 + "..."
    assert summaries.clipped(" " + "b" * 130) == " " + "b" * 119 + "..."
    assert summaries.clipped("a b" + "c" * 130) == "a..."
    assert summaries.clipped("a" * 121 + " b") == "a" * 120 + "..."


def test_the_schemas_refusal_carries_its_body_as_structured_content_too() -> None:
    """The seam answers the client twice, as text and as the structured half a typed client
    reads: the same body in both, or one of the two halves says nothing."""
    result = asyncio.run(s.mcp.call_tool("read_memory", {"ref": 5, "length": 16}))
    body = result.structured_content
    assert body is not None and body["status"] == "INVALID" and body["code"] == "bad_argument"
    assert body["summary"].startswith("read_memory: INVALID (bad_argument)")
    assert json.loads(result.content[0].text) == body


def test_a_steps_unknown_argument_is_refused_naming_the_ones_its_tool_takes() -> None:
    out = s.perform(steps=[{"op": "run_for", "frame": 3}])
    assert out["status"] == "INVALID" and "got an unexpected keyword argument 'frame'" in (
        out["message"]), out
    assert "`takes` names `run_for`'s" in out["message"], out["message"]
    takes = out["errors"][0]["takes"]
    assert "frames" in takes and "milliseconds" in takes and "ctx" not in takes, takes
