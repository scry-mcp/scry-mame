"""What `scry_core.probe` judges with this server's own surface: the task set and its captures,
the server's pre-gate check, and the texts the client delivers.

The engine itself is the core's and is judged there on frozen surfaces; what needs the real server
(its whole roster, its own `check`, every task as real runs answered it) is judged here.
`captured/mame/` holds every task as real runs answered it, one file per task.
"""

import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from scry_core import probe
from scry_core.client_cap import over_the_cap

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mcp_probe"

# At collection: `servers.load` says why.
probe.configure(ROOT / "mcp_probe" / "servers.py", ROOT / "mcp_probe" / "tasks")
SURFACE = probe.load_surface("mame")


def _tasks() -> list[dict[str, Any]]:
    text = (FIXTURES / "tasks" / "mame.json").read_text()
    doc: dict[str, list[dict[str, Any]]] = json.loads(text)
    return doc["tasks"]


def _narrowed() -> probe.Surface:
    """The real surface, narrowed to the tools the fixture tasks name: real descriptions, real
    signatures, the server's real `check`."""
    names = {probe.on_tool(t) for t in _tasks()}
    tools = {n: t for n, t in SURFACE.tools.items() if n in names}
    return dataclasses.replace(SURFACE, tools=tools)


def _judge(task_id: str, line: str) -> probe.Verdict:
    task = next(t for t in _tasks() if t["id"] == task_id)
    return probe.judge(_narrowed(), task, probe.parse(line, [task_id])[task_id])


def test_the_tasks_cover_the_server(capsys: pytest.CaptureFixture[str]) -> None:
    assert probe.check(("mame",)) == probe.EXIT_PASS, capsys.readouterr().out


def test_every_task_is_captured_and_judged_as_it_was() -> None:
    """Every task of the server, at the size a real run answers: each task's capture, judged
    again against the whole surface and the server's own check, gives back the verdicts
    recorded when it ran, and a task with no capture is named."""
    assert probe.capture_problems("mame", probe.CAPTURED_ROOT / "mame",
                                  probe.TASKS_DIR / "mame.json") == []


def test_the_servers_own_check_takes_a_right_call() -> None:
    line = 'M1: {"tool": "read_memory", "args": {"ref": "PlayerX", "length": 6}}'
    assert _judge("M1", line).right


def test_the_mame_check_receives_the_defaults_the_tool_would_pass() -> None:
    task = {"id": "M1", "prompt": "p", "tool": "read_memory", "args": {"ref": "PlayerX"},
            "allow": ["length"]}
    for length, right in [(1024, True), (1025, False), (0, False)]:
        line = f'M1: {{"tool": "read_memory", "args": {{"ref": "PlayerX", "length": {length}}}}}'
        assert probe.judge(_narrowed(), task, probe.parse(line, ["M1"])["M1"]).right is right


def test_a_task_whose_right_answer_the_server_refuses_is_refused() -> None:
    task = {"id": "M1", "prompt": "p", "tool": "read_memory",
            "args": {"ref": "PlayerX", "length": {"any_of": [0, 6]}}}
    problems = probe.task_problems(_narrowed(), [task])
    assert problems == ["mame task M1: its own expected call is refused: the server's check "
                        "refuses it: length=0 is outside 1..1024: for more bytes use `memdump`, "
                        "which writes them to a file instead of into the reply"]


@pytest.mark.parametrize(("boot_lua", "said"), [
    ("emu.print('booted')", "boot_lua=\"emu.print('booted')\" must be an ABSOLUTE path"),
    ("~/harness.lua", "boot_lua='~/harness.lua' must be an ABSOLUTE path (a `~` path"),
])
def test_a_start_whose_expected_boot_lua_is_not_a_path_is_refused(boot_lua: str, said: str) -> None:
    """`start` is judged by `launch.start`'s own half, the shape of its paths: inline Lua where
    the harness FILE goes, or a `~` nothing expands, is a call the server refuses, so a task
    expecting it is refused too."""
    task = {"id": "M1", "prompt": "p", "tool": "start",
            "args": {"binary": "/b/mame", "system": "m68k-dual", "rompath": "/r",
                     "reference_rom": "/r/rom.bin", "boot_lua": boot_lua}}
    (problem,) = probe.task_problems(SURFACE, [task])
    assert problem.startswith("mame task M1: its own expected call is refused: the server's "
                              "check refuses it: "), problem
    assert said in problem, problem


def test_a_start_with_absolute_paths_is_judged_by_shape_not_by_what_is_on_disk() -> None:
    """The control: paths no machine holds are taken, because whether a file is there is the
    host's, never the probe's."""
    task = {"id": "M1", "prompt": "p", "tool": "start",
            "args": {"binary": "/no/such/mame", "system": "m68k-dual", "rompath": "/no/roms",
                     "reference_rom": "/no/rom.bin", "boot_lua": "/no/harness.lua",
                     "symbols": {"maincpu": "/no/a.map"}}}
    assert probe.task_problems(SURFACE, [task]) == []


def test_every_instructions_and_tool_description_fits_the_client_cap() -> None:
    from mcp_probe import servers

    over = [line for name, module in servers.load().items()
            for line in over_the_cap(name, module.mcp)]
    assert servers.load()["mame"] is probe._modules()["mame"], "the cap measured another copy"
    if over:
        pytest.fail("\n".join(over), pytrace=False)
