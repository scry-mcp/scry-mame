"""`tests/live/live_harness.py`'s board runner, loaded by path as `evidence` is, on no machine: a
board's run is a function here, so what the runner does with each outcome is asked directly."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

LIVE = Path(__file__).parent / "live"


def _harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, background: str | None = None,
             ) -> ModuleType:
    """The harness loaded on no machine, its bench an empty directory of the test's own;
    `background` is `MAME_BACKGROUND` (None: unset, so the developer's own shell cannot decide a
    test)."""
    monkeypatch.setenv("MAME_LIVE_BENCH", str(tmp_path))
    if background is None:
        monkeypatch.delenv("MAME_BACKGROUND", raising=False)
    else:
        monkeypatch.setenv("MAME_BACKGROUND", background)
    monkeypatch.syspath_prepend(str(LIVE))
    # `bench_boards` reads its root at import: a copy another test loaded keeps another root.
    monkeypatch.delitem(sys.modules, "bench_boards", raising=False)
    spec = importlib.util.spec_from_file_location("live_harness", LIVE / "live_harness.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("value", "forced"), [(None, None), ("", None), ("1", True),
                                               ("0", False)])
def test_mame_background_reaches_every_start_of_the_run_and_a_cells_own_value_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str | None, forced: bool | None,
) -> None:
    """One switch per run, reaching the starts built from `BOOT` and the ones through `call`;
    unset, no start is handed one, so each keeps the server's own default."""
    h = _harness(monkeypatch, tmp_path, value)
    assert h.BACKGROUND is forced
    assert h.BOOT.get("background", "absent") == ("absent" if forced is None else forced)
    handed: list[dict[str, object]] = []

    def start(**kw: object) -> dict[str, object]:
        handed.append(kw)
        return {"status": "ok"}

    monkeypatch.setattr(h.s, "start", start)
    h.call("start", system="x")
    h.call("start", system="x", background="the cell's own")
    assert handed[0].get("background", "absent") == ("absent" if forced is None else forced)
    assert handed[1]["background"] == "the cell's own"


def test_a_mame_background_outside_its_words_refuses_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`true` is not `1`: a value read as false would put every start in front in silence."""
    with pytest.raises(SystemExit) as e:
        _harness(monkeypatch, tmp_path, "true")
    assert e.value.code == 3


def test_a_board_that_raises_fails_its_own_cells_and_the_next_board_still_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An exception out of a board is a FAIL of the cells it had not judged: left to the
    section, it would BLOCK every cell still open, the next boards' included, and BLOCKED is
    never counted against the run, so a crash could close a run PASSED."""
    h = _harness(monkeypatch, tmp_path)
    cells = ["judged first", "left open", "the next board's"]

    def crashes(t: list[str]) -> None:
        h.cell(t[0], True)
        raise KeyError("session")

    def runs(t: list[str]) -> None:
        h.cell(t[2], True)

    sec = h.Section("Z", "a section of two boards", cells, lambda: None)
    h.CURRENT[:] = [sec]
    h.run_boards(cells, (h.Board(crashes, (0, 1), lambda: ""), h.Board(runs, (2,), lambda: "")))
    assert sec.judged == {"judged first": "OK", "left open": "FAIL", "the next board's": "OK"}
    assert h.failures == ["left open"]


def test_a_board_that_cannot_run_here_blocks_its_cells_and_runs_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    h = _harness(monkeypatch, tmp_path)
    ran: list[str] = []
    sec = h.Section("Z", "one board missing its bench copies", ["a", "b"], lambda: None)
    h.CURRENT[:] = [sec]
    h.run_boards(["a", "b"], (h.Board(lambda t: ran.append("ran"), (0, 1),
                                      lambda: "X is not set"),))
    assert ran == [] and sec.judged == {"a": "BLOCKED", "b": "BLOCKED"} and h.failures == []


def test_a_start_on_the_bench_is_blocked_naming_the_file_that_is_absent_or_wrong(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A bench board boots only on copies that match their pins: one byte off and the start is
    never made, the reason naming the file and the tool that fills it; a binary off the bench
    is not the bench's to judge; and a board's copies are hashed once per run."""
    h = _harness(monkeypatch, tmp_path)
    boards = sys.modules["bench_boards"]
    data = b"radendu"
    pins = [{"path": "radendur/upstream/radendu", "sha256": hashlib.sha256(data).hexdigest(),
             "source_repo": "tch-blitter", "source_path": "upstream/radendu",
             "source_commit": ""}]
    (tmp_path / "bench.json").write_text(json.dumps(pins))
    monkeypatch.setattr(boards, "BENCH_MANIFEST", tmp_path / "bench.json")
    hashed: list[Path] = []
    real_digest = boards.bench.digest
    def digest(path: Path) -> str:
        hashed.append(path)
        return str(real_digest(path))

    monkeypatch.setattr(boards.bench, "digest", digest)
    started: list[object] = []

    def start(**kw: object) -> dict[str, object]:
        started.append(kw["binary"])
        return {}

    monkeypatch.setattr(h.s, "start", start)
    assert boards.radendur_missing().startswith("bench MISSING radendur/upstream/radendu")
    boards._reasons.clear()
    (tmp_path / "radendur/upstream").mkdir(parents=True)
    (tmp_path / "radendur/upstream/radendu").write_bytes(b"X" + data[1:])
    remedy = r"MISMATCH radendur/upstream/radendu.*scry_core\.live_bench"
    with pytest.raises(h.Blocked, match=remedy):
        h.call("start", **h.BOOT)
    with pytest.raises(h.Blocked):
        h.call("start", **h.BOOT)
    assert len(hashed) == 1, "a board's copies are hashed once per run"
    assert boards.radendur_missing().startswith("bench MISMATCH radendur/upstream/radendu")
    with pytest.raises(h.Blocked, match="MISMATCH radendur/upstream/radendu"):
        h.call("gfx_load", path=str(tmp_path / "radendur/hardware/gfx.yaml"))
    with pytest.raises(h.Blocked, match="MISMATCH radendur/upstream/radendu"):
        h.call("start", binary="/opt/stock/mame", symbols={":maincpu": h.SYMBOLS})
    h.call("start", binary="/opt/stock/mame")
    h.call("start", binary=str(tmp_path))
    h.call("start")
    boards._reasons.clear()
    (tmp_path / "radendur/upstream/radendu").write_bytes(data)
    h.call("start", **h.BOOT)
    assert started == ["/opt/stock/mame", str(tmp_path), h.BOOT["binary"]]
    assert boards.radendur_missing() == ""


def test_a_board_whose_call_is_refused_blocks_its_open_cells_and_fails_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A call the matrix refuses inside a board (a bench copy gone wrong, a wait past the
    ceiling) leaves the cells it did not reach BLOCKED: they could not run, which is no FAIL."""
    h = _harness(monkeypatch, tmp_path)

    def refused(t: list[str]) -> None:
        h.cell(t[0], True)
        raise h.Blocked("bench MISSING x")

    sec = h.Section("Z", "a board refused half-way", ["judged", "open"], lambda: None)
    h.CURRENT[:] = [sec]
    h.run_boards(["judged", "open"], (h.Board(refused, (0, 1), lambda: ""),))
    assert sec.judged == {"judged": "OK", "open": "BLOCKED"} and h.failures == []


def test_every_path_a_bench_board_boots_on_is_pinned_in_the_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A path the harness opens on the bench that the manifest does not pin would be read
    unchecked, and its board would run on whatever sits there."""
    h = _harness(monkeypatch, tmp_path)
    boards = sys.modules["bench_boards"]
    pinned = {e.path for e in boards.bench.load(boards.BENCH_MANIFEST)}
    held = [h.BOOT["binary"], h.BOOT["reference_rom"], boards.SYMBOLS, boards.SUB_ROM,
            boards.SUB_SYMBOLS, boards.MANIFEST]
    assert {str(Path(p).relative_to(boards.BENCH)) for p in held} <= pinned
    assert all(any(e.startswith(f"{board}/upstream/mame") for e in pinned)
               for board in ("lineup", "speedf"))
    assert {"lineup/build/Game_V30.bin", "lineup/build/game_v30.map",
            "lineup/run/mame_roms/lineup.zip", "speedf/build/speedf_v30.bin",
            "speedf/run/mame_roms/speedf.zip", "radendur/run/mame_roms/radendur.zip"} <= pinned


def _matrix_function(name: str) -> object:
    """One function of `live_matrix.py`, compiled alone: the module boots boards on import."""
    import ast
    from typing import Any
    tree = ast.parse((LIVE / "live_matrix.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    space: dict[str, Any] = {"Any": Any}
    # A name no file has: compiled under the matrix's own path, coverage would count the whole
    # matrix, which only a live run executes.
    exec(compile(ast.Module(body=[node], type_ignores=[]), f"<live_matrix.{name}>", "exec"),
         space)
    return space[name]


@pytest.mark.parametrize("rows,want", [
    # each pen's newest row decides: pen 3's newest is an `r`, so its earlier `b` does not count
    ([{"n": 1, "pen": 3, "component": "b", "color": "#102030"},
      {"n": 2, "pen": 3, "component": "r", "color": "#112030"}], None),
    ([{"n": 1, "pen": 4, "component": "b", "color": "#202020"}], None),          # red == blue
    ([{"n": 1, "pen": 5, "component": "b", "color": "#102030"},
      {"n": 2, "pen": 6, "component": "b", "color": "#302010"}], 6),            # the newest
    ([{"n": 2, "pen": 7, "component": "b", "color": "#302010"},
      {"n": 1, "pen": 8, "component": "b", "color": "#102030"}], 7),            # whatever order
    ([{"n": 3, "index": 9}, {"n": 1, "pen": 9, "component": "b", "color": None},
      {"n": 2, "pen": 1, "component": "b", "color": "#0a0b0c"}], 1),            # no pen, no colour
    ([], None),
])
def test_block_f_takes_the_newest_pen_completed_with_red_and_blue_apart(
    rows: list[dict[str, object]], want: int | None,
) -> None:
    pick = _matrix_function("_completed_pen_red_blue_apart")
    assert pick({"rows": rows}) == want  # type: ignore[operator]
