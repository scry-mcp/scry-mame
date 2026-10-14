"""`tests/live/live_harness.py`'s board runner, loaded by path as `evidence` is, on no machine: a
board's run is a function here, so what the runner does with each outcome is asked directly."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

LIVE = Path(__file__).parent / "live"


#: An identity of the test's own, in the bench's shape: a label's values are invented here, so
#: nothing a test asserts depends on what the developer's bench names.
IDENTITY: dict[str, dict[str, str]] = {
    "m68k-dual": {"dir": "dual", "system": "dualset", "binary": "upstream/dualmame",
                  "reference_rom": "disasm/main.bin", "symbols": "disasm/main.yaml",
                  "sub_rom": "disasm/sub.bin", "sub_symbols": "disasm/sub.yaml",
                  "blit_handler": "dual_state::blit_w"},
    "m68k-dual-alt": {"dir": "alt", "system": "altset", "binary": "upstream/altmame",
                      "reference_rom": "disasm/alt.bin"},
    "v30": {"dir": "v30dir", "system": "v30set", "binary": "upstream/v30mame",
            "rom_segment": "SEG_ROM"},
    "v30-alt": {"dir": "v30altdir", "system": "v30altset", "binary": "upstream/v30altmame",
                "reference_rom": "build/v30alt.bin"},
}


def _harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, background: str | None = None,
             identity: object = IDENTITY) -> ModuleType:
    """The harness loaded on no machine, its bench a directory of the test's own holding
    `identity` as its `identity.json` (None: no file); `background` is `MAME_BACKGROUND` (None:
    unset, so the developer's own shell cannot decide a test)."""
    monkeypatch.setenv("MAME_LIVE_BENCH", str(tmp_path))
    if identity is not None:
        (tmp_path / "identity.json").write_text(json.dumps(identity))
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
    data = b"dualmame"
    pins = [_pin(f"dual/{f}", data) for f in ("upstream/dualmame", "disasm/main.bin",
                                               "disasm/main.yaml", "disasm/sub.bin",
                                               "disasm/sub.yaml", "run/mame_roms/dualset.zip",
                                               "hardware/gfx.yaml")]
    (tmp_path / "bench.json").write_text(json.dumps(pins))
    assert tmp_path / "bench.json" == boards.BENCH_MANIFEST, "the manifest is the bench's own"
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
    assert boards.m68k_dual_missing().startswith("bench MISSING dual/")
    boards._reasons.clear()
    for pin in pins[1:]:
        (tmp_path / pin["path"]).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / pin["path"]).write_bytes(data)
    (tmp_path / "dual/upstream").mkdir(parents=True)
    (tmp_path / "dual/upstream/dualmame").write_bytes(b"X" + data[1:])
    remedy = r"MISMATCH dual/upstream/dualmame.*scry_core\.live_bench"
    with pytest.raises(h.Blocked, match=remedy):
        h.call("start", **h.BOOT)
    with pytest.raises(h.Blocked):
        h.call("start", **h.BOOT)
    assert sorted(hashed) == sorted(tmp_path / p["path"] for p in pins), (
        "a board's copies are hashed once each per run")
    assert boards.m68k_dual_missing().startswith("bench MISMATCH dual/upstream/dualmame")
    with pytest.raises(h.Blocked, match="MISMATCH dual/upstream/dualmame"):
        h.call("gfx_load", path=str(tmp_path / "dual/hardware/gfx.yaml"))
    with pytest.raises(h.Blocked, match="MISMATCH dual/upstream/dualmame"):
        h.call("start", binary="/opt/stock/mame", symbols={":maincpu": h.SYMBOLS})
    h.call("start", binary="/opt/stock/mame")
    h.call("start", binary=str(tmp_path))
    h.call("start")
    boards._reasons.clear()
    boards._pins.clear()
    (tmp_path / "dual/upstream/dualmame").write_bytes(data)
    h.call("start", **h.BOOT)
    assert started == ["/opt/stock/mame", str(tmp_path), h.BOOT["binary"]]
    assert boards.m68k_dual_missing() == ""


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


def _pin(path: str, data: bytes) -> dict[str, str]:
    return {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "source_repo": "s",
            "source_path": path, "source_commit": ""}


def test_every_value_a_board_boots_on_comes_from_the_benchs_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The tracked code names a board by its label; the set, the binary and every file it opens
    are the identity's, joined to the board's directory on the bench."""
    h = _harness(monkeypatch, tmp_path)
    boards = sys.modules["bench_boards"]
    assert h.BOOT["system"] == "dualset"
    assert h.BOOT["binary"] == str(tmp_path / "dual/upstream/dualmame")
    dual = tmp_path / "dual"
    held = (h.BOOT["reference_rom"], h.BOOT["rompath"], boards.SYMBOLS, boards.SUB_ROM,
            boards.SUB_SYMBOLS, boards.MANIFEST, boards.BLIT_HANDLER)
    assert held == (str(dual / "disasm/main.bin"), str(dual / "run/mame_roms"),
                    str(dual / "disasm/main.yaml"), str(dual / "disasm/sub.bin"),
                    str(dual / "disasm/sub.yaml"), str(dual / "hardware/gfx.yaml"),
                    "dual_state::blit_w")
    alt = tmp_path / "alt"
    alt_boot = boards.M68K_DUAL_ALT_BOOT
    assert alt_boot == {
        "binary": str(alt / "upstream/altmame"), "system": "altset",
        "rompath": str(alt / "run/mame_roms"), "reference_rom": str(alt / "disasm/alt.bin"),
        "reference_addr": "0x0"}
    assert boards.board_dir("v30") == tmp_path / "v30dir"
    assert boards.opened("v30") == ["v30dir/upstream/v30mame", "v30dir/run/mame_roms/v30set.zip",
                                    "v30dir/build/Game_V30.bin", "v30dir/build/game_v30.map"]
    assert boards.opened("v30-alt") == ["v30altdir/upstream/v30altmame",
                                        "v30altdir/build/v30alt.bin",
                                        "v30altdir/run/mame_roms/v30altset.zip"]


def test_a_label_or_key_the_code_does_not_declare_is_its_mistake_on_every_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """With no identity at all a misspelt label must not pass for one the bench lacks."""
    _harness(monkeypatch, tmp_path, identity=None)
    boards = sys.modules["bench_boards"]
    with pytest.raises(KeyError, match="v3O"):
        boards.board_missing("v3O")
    with pytest.raises(KeyError, match=r"v30\.reference_rom"):
        boards.value("v30", "reference_rom")


@pytest.mark.parametrize(("identity", "why"), [
    (None, r"identity ABSENT: write .*identity\.json beside bench\.json"),
    ("{", r"identity UNREADABLE .*: write .*identity\.json"),
    ([], r"identity NOT AN OBJECT OF OBJECTS: write"),
    ({k: v for k, v in IDENTITY.items() if k != "m68k-dual"},
     r"identity names no 'm68k-dual': add it to .*identity\.json with dir, system"),
    ({**IDENTITY, "m68k-dual": {k: v for k, v in IDENTITY["m68k-dual"].items() if k != "system"}},
     r"identity m68k-dual\.system is None, not a non-empty string: set it in"),
    ({**IDENTITY, "m68k-dual": {**IDENTITY["m68k-dual"], "binary": 7}},
     r"identity m68k-dual\.binary is 7, not a non-empty string"),
    ({**IDENTITY, "m68k-dual": {**IDENTITY["m68k-dual"], "dir": ""}},
     r"identity m68k-dual\.dir is '', not a non-empty string"),
    ({**IDENTITY, "m68k-dual": "dual"}, r"identity NOT AN OBJECT OF OBJECTS: write"),
    ({**IDENTITY, "m68k-dual": {**IDENTITY["m68k-dual"], "dir": "boards/dual"}},
     r"identity m68k-dual\.dir is 'boards/dual', not one directory name"),
    ({**IDENTITY, "m68k-dual": {**IDENTITY["m68k-dual"], "dir": ".."}},
     r"identity m68k-dual\.dir is '\.\.', not one directory name"),
])
def test_an_identity_that_cannot_name_a_board_blocks_it_with_the_remedy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, identity: object, why: str,
) -> None:
    """A missing file, a missing key and a wrong type each BLOCK the board naming what to write
    where; nothing boots on a value the identity did not give, and the start through the
    harness is refused with the same reason rather than made on a guessed path."""
    if isinstance(identity, str):
        (tmp_path / "identity.json").write_text(identity)
        identity = None
    h = _harness(monkeypatch, tmp_path, identity=identity)
    boards = sys.modules["bench_boards"]
    (tmp_path / "bench.json").write_text(json.dumps([_pin("dual/upstream/dualmame", b"x")]))
    monkeypatch.setattr(h.s, "start", lambda **kw: pytest.fail(f"a blocked board started: {kw}"))
    assert re.match(why, boards.m68k_dual_missing()), boards.m68k_dual_missing()
    with pytest.raises(h.Blocked, match=why):
        h.call("start", **h.BOOT)


@pytest.mark.parametrize(("label", "key"), [(lb, k) for lb, ks in IDENTITY.items() for k in ks])
def test_every_key_of_every_label_is_required(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, label: str, key: str,
) -> None:
    held = {lb: dict(v) for lb, v in IDENTITY.items()}
    del held[label][key]
    _harness(monkeypatch, tmp_path, identity=held)
    boards = sys.modules["bench_boards"]
    assert boards.board_missing(label) == (
        f"identity {label}.{key} is None, not a non-empty string: set it in "
        f"{tmp_path / 'identity.json'}")
    assert boards.value(label, "dir") == ""


def test_a_path_under_a_boards_directory_is_judged_as_that_board(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`args_missing` traces a path on the bench to the label whose `dir` holds it, so its
    identity and its pins are judged, not just the copies under the directory; a directory no
    label owns is judged by its copies."""
    h = _harness(monkeypatch, tmp_path)
    data = b"alt"
    pins = [_pin("alt/upstream/altmame", data), _pin("loose/x.bin", data)]
    for pin in pins:
        (tmp_path / pin["path"]).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / pin["path"]).write_bytes(data)
    (tmp_path / "bench.json").write_text(json.dumps(pins))
    boards = sys.modules["bench_boards"]
    assert boards.args_missing({"binary": str(tmp_path / "alt/upstream/altmame")}).startswith(
        "board m68k-dual-alt opens alt/disasm/alt.bin, which")
    assert boards.args_missing({"symbols": str(tmp_path / "loose/x.bin")}) == ""
    assert boards.args_missing({"symbols": str(tmp_path / "gone/x.bin")}).startswith("bench ")
    _ = h


def test_a_file_the_identity_names_that_the_manifest_does_not_pin_blocks_the_board(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A path the harness opens on the bench that the manifest does not pin would be read
    unchecked, and its board would run on whatever sits there."""
    h = _harness(monkeypatch, tmp_path)
    boards = sys.modules["bench_boards"]
    data = b"alt"
    pins = [_pin("alt/upstream/altmame", data), _pin("alt/run/mame_roms/altset.zip", data)]
    for pin in pins:
        (tmp_path / pin["path"]).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / pin["path"]).write_bytes(data)
    (tmp_path / "bench.json").write_text(json.dumps(pins))
    assert boards.board_missing("m68k-dual-alt") == (
        f"board m68k-dual-alt opens alt/disasm/alt.bin, which {tmp_path / 'bench.json'} does "
        "not pin: pin it there, or name a file it pins")
    boards._reasons.clear()
    boards._pins.clear()
    pins.append(_pin("alt/disasm/alt.bin", data))
    (tmp_path / "alt/disasm").mkdir()
    (tmp_path / "alt/disasm/alt.bin").write_bytes(data)
    (tmp_path / "bench.json").write_text(json.dumps(pins))
    assert boards.board_missing("m68k-dual-alt") == ""
    _ = h


def test_a_bench_with_no_manifest_says_it_is_kept_only_there(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`fill` and `check` both read the manifest, so neither can be the remedy for its absence."""
    _harness(monkeypatch, tmp_path)
    boards = sys.modules["bench_boards"]
    assert boards.m68k_dual_missing().startswith(
        f"bench manifest ABSENT: {tmp_path / 'bench.json'} pins every copy and is kept only in "
        "the bench")


def test_the_pin_check_on_a_manifest_that_is_not_one_is_a_reason_and_never_a_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`board_missing` judges the copies first, which already refuses such a manifest; the pin
    check, asked alone, says the same thing rather than raising."""
    _harness(monkeypatch, tmp_path)
    boards = sys.modules["bench_boards"]
    (tmp_path / "bench.json").write_text("[]")
    assert boards._unpinned("v30").startswith(f"bench {tmp_path / 'bench.json'} names no file")


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
