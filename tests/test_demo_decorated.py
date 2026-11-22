"""A MAME demo's decorated loop (`demos/decorated.py`): the layers a demo declares, the timeline's
pass each clip is drawn from, the run's own timeline required, and Pillow and numpy kept out of
everything but the making of a loop. A committed run stands in for an emulator."""

from __future__ import annotations

import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from demo_transcripts import timeline_of  # noqa: E402
from scry_core import demo as core
from scry_core import motion, timeline
from scry_core.demo import Demo, Moment, Reply, Run, Step
from scry_core.overlay import Layer
from scry_core.verdict import EXIT_INVALID, EXIT_PASS, Invalid

from demos import decorated
from demos.gridlee import demo as gridlee
from demos.lineup import demo as lineup
from demos.speedf import demo as speedf
from demos.starfire import demo as starfire

ROOT = Path(__file__).resolve().parents[1]
DEMOS = {"gridlee": gridlee, "lineup": lineup, "speedf": speedf, "starfire": starfire}
SIZE = (320, 240)
BOX = motion.Box(0, 0, 32, 24, (32, 24))
RATE = Fraction(60)
GREY = bytes([0x40, 0x40, 0x40])


def _step(name: str, tool: str) -> Step:
    return Step(name, tool, {}, lambda reply, run: "")


def _demo(moments: int = 2) -> Demo:
    """Two recordings of the same frames: the second after a state load rewound the machine."""
    return Demo(name="t", root=ROOT, server=["x"], alt="a grey screen",
                steps=[_step("start", "start"), _step("film A", "record"),
                       _step("load", "state_write"), _step("film B", "record")],
                moments=[Moment("start", "film A", "A is filmed."),
                         Moment("load", "film B", "B is filmed.")][:moments])


def _timeline() -> dict[str, Any]:
    made = timeline.Builder("t")
    made.add("start", "start", {}, "ok", (None, 100))
    made.add("film A", "record", {"dest": "a.avi"}, "ok", (100, 160))
    made.add("load", "state_write", {"method": "load"}, "ok", (160, 100))
    made.add("film B", "record", {"dest": "b.avi"}, "ok", (100, 160))
    return timeline.loads(made.dumps())


def _run() -> Run:
    return Run(dir=ROOT, replies={"film A": Reply({"frame_begin": 100}),
                                  "film B": Reply({"frame_begin": 100})})


def _pictures(frames: int = 30) -> list[motion.Picture]:
    return [motion.Picture(*SIZE, GREY * (SIZE[0] * SIZE[1]), 17) for _ in range(frames)]


def _draw(n: int, document: dict[str, Any] | None = None, demo: Demo | None = None,
          layers: tuple[Layer, ...] = ("calls", "keys")) -> list[bytes]:
    each = decorated.decorator(demo or _demo(), _run(), document or _timeline(), layers)
    return [p.rgb for p in each(n, range(30), _pictures(), RATE, BOX)]


def test_a_clip_is_drawn_from_the_pass_of_the_run_it_was_recorded_in() -> None:
    first, second = _draw(0), _draw(1)
    assert first != second
    one_pass = timeline.Builder("t")
    one_pass.add("start", "start", {}, "ok", (None, 100))
    one_pass.add("film A", "record", {"dest": "a.avi"}, "ok", (100, 160))
    assert first == _draw(0, timeline.loads(one_pass.dumps()), _demo(moments=1))


def test_a_moment_whose_step_the_timeline_does_not_hold_is_refused() -> None:
    gone = {**_timeline(), "calls": _timeline()["calls"][:1]}
    with pytest.raises(Invalid, match="holds no call of step 'film A'"):
        _draw(0, gone)


def test_a_clip_decorated_twice_is_the_same_bytes() -> None:
    assert _draw(0) == _draw(0)


def test_a_moment_that_is_no_recording_cannot_be_placed_in_the_timeline() -> None:
    odd = Demo(name="t", root=ROOT, server=["x"], alt="a", steps=[_step("a", "start"),
                                                                    _step("b", "run_for")])
    with pytest.raises(Invalid, match="not a `record` step"):
        decorated.decorator(Demo(**{**odd.__dict__, "moments": [Moment("a", "b", "B.")],
                                    "video": lambda run: ROOT}), Run(dir=ROOT, replies={
                                        "b": Reply({"frame_begin": 1})}), _timeline(),
                            ("calls",))


def test_a_recording_that_says_no_frame_it_began_at_is_refused() -> None:
    run = Run(dir=ROOT, replies={"film A": Reply({}), "film B": Reply({"frame_begin": 100})})
    with pytest.raises(Invalid, match="the frame it began at"):
        decorated.decorator(_demo(), run, _timeline(), ("calls",))


@pytest.mark.parametrize(("layer", "said"), [
    ("pointer", "MAME has no pointer"), ("pause", "no pause mark"), ("record", "no record mark"),
    ("edge", "declares `calls` and `keys`")])
def test_a_layer_that_does_not_exist_for_a_mame_demo_is_refused(layer: Layer, said: str) -> None:
    with pytest.raises(ValueError, match=said):
        decorated.declared(("calls", layer))


@pytest.mark.parametrize("name", sorted(DEMOS))
def test_a_demo_declares_the_layers_its_run_has_something_to_draw_for(name: str) -> None:
    module = DEMOS[name]
    decorated.declared(module.LAYERS)
    document = timeline_of(module.DEMO, ROOT / "demos" / name / "TRANSCRIPT.md")
    pressed = any(call["events"] for call in document["calls"])
    assert ("keys" in module.LAYERS) == pressed
    assert "calls" in module.LAYERS


def test_a_loop_is_made_only_with_the_pillow_the_decorate_extra_brings(
        monkeypatch: pytest.MonkeyPatch) -> None:
    import scry_core
    monkeypatch.delattr(scry_core, "decorate", raising=False)
    monkeypatch.setitem(sys.modules, "scry_core.decorate", None)
    with pytest.raises(Invalid, match="`decorate` extra"):
        decorated.decorator(_demo(), _run(), _timeline(), ("calls",))


def test_a_missing_extra_refuses_the_update_before_the_emulator_runs(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
        ) -> None:
    import scry_core
    handed = _seams(monkeypatch, wrote=True)
    ran: list[bool] = []

    def execute(*args: Any) -> int:
        ran.append(True)
        return EXIT_PASS

    monkeypatch.setattr(core, "execute", execute)
    monkeypatch.delattr(scry_core, "decorate", raising=False)
    monkeypatch.setitem(sys.modules, "scry_core.decorate", None)
    code = decorated.main(_demo(), ("calls",), ["--transcript", str(tmp_path / "t.md"),
                                                "--update-readme"])
    assert (code, ran, handed) == (EXIT_INVALID, [], [])
    assert "`decorate` extra" in capsys.readouterr().out


@pytest.mark.parametrize("name", sorted(DEMOS))
def test_every_moment_of_a_demo_ends_at_a_step_its_committed_run_holds(name: str) -> None:
    module = DEMOS[name]
    document = timeline_of(module.DEMO, ROOT / "demos" / name / "TRANSCRIPT.md")
    shown = decorated.passes(document, module.DEMO)
    assert [one["calls"][-1]["step"] for one in shown] == [m.until for m in module.DEMO.moments]
    tools = {step.name: step.tool for step in module.DEMO.steps}
    assert [tools[m.until] for m in module.DEMO.moments] == ["record"] * len(module.DEMO.moments)


def test_the_server_and_the_demo_runner_load_neither_pillow_nor_numpy() -> None:
    loaded = "print(sorted({'PIL', 'numpy'} & set(sys.modules)))"
    probe = f"import sys; sys.path.insert(0, {str(ROOT)!r}); import scry_mame.server, " \
            f"scry_core.demo, demos.decorated; {loaded}"
    control = f"import sys, scry_core.decorate; {loaded}"
    ran = [subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                          check=False) for code in (probe, control)]
    assert [(r.returncode, r.stdout.strip()) for r in ran] == [
        (0, "[]"), (0, "['PIL', 'numpy']")], [r.stderr for r in ran]


def _seams(monkeypatch: pytest.MonkeyPatch, wrote: bool) -> list[Any]:
    """A runner of the test's own that makes the loop as `execute` does, with a `build` that
    says what it was handed."""
    handed: list[Any] = []

    def build(cuts: Any, work: Path, decorate: Any = None) -> motion.Built:
        handed.append(decorate)
        return motion.Built(b"", (), True, BOX)

    def execute(demo: Demo, run: Run, transcript: Path, update_readme: bool = False) -> int:
        run.replies.update(_run().replies)
        if wrote:
            core._beside(transcript).timeline.write_text(  # noqa: SLF001
                _json(_timeline()), encoding="utf-8")
        motion.build([], run.dir)
        return EXIT_PASS

    monkeypatch.setattr(motion, "build", build)
    monkeypatch.setattr(core, "execute", execute)
    return handed


def _json(document: dict[str, Any]) -> str:
    import json
    return json.dumps(document)


def test_the_loop_is_built_with_the_decorator_and_the_runner_is_put_back(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    handed = _seams(monkeypatch, wrote=True)
    built, ran = motion.build, core.execute
    code = decorated.main(_demo(), ("calls",), ["--transcript", str(tmp_path / "t.md")])
    assert (code, len(handed), callable(handed[0])) == (EXIT_PASS, 1, True)
    assert (motion.build, core.execute) == (built, ran)


def test_a_loop_with_no_timeline_beside_its_run_is_refused(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
        ) -> None:
    handed = _seams(monkeypatch, wrote=False)
    code = decorated.main(_demo(), ("calls",), ["--transcript", str(tmp_path / "t.md")])
    assert (code, handed) == (EXIT_INVALID, [])
    assert "the run wrote no timeline" in capsys.readouterr().out
