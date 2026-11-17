"""`tests/live/live_harness.py`'s board runner, loaded by path as `evidence` is, on no machine: a
board's run is a function here, so what the runner does with each outcome is asked directly."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from scry_core import live_host  # noqa: E402

from scry_mame import server  # noqa: E402,F401 -- registers the tools and imports the boundary the shape guard wraps

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
    "v30": {"dir": "v30dir", "system": "v30set", "rom_segment": "SEG_ROM"},
    "v30-alt": {"dir": "v30altdir", "system": "v30altset", "reference_rom": "build/v30alt.bin"},
}


def _point(module: ModuleType, monkeypatch: pytest.MonkeyPatch, run: live_host.LiveRun,
           tmp_path: Path) -> None:
    """One host for the module's `RUN` and for the ledger's: a case that replaced only one of
    the two would write through one object and empty the scratch through the other."""
    monkeypatch.setattr(module, "RUN", run)
    module.LEDGER.host = run
    module.LEDGER.scratch = run.scratch
    module.LEDGER.transcript = tmp_path / "scratch" / "transcript.jsonl"
    module.LEDGER.evidence = tmp_path / "scratch" / "evidence"
    monkeypatch.setattr(module, "SCRATCH", tmp_path / "scratch")
    monkeypatch.setattr(module, "TRANSCRIPT", tmp_path / "scratch" / "transcript.jsonl")
    monkeypatch.setattr(module, "EVIDENCE", tmp_path / "scratch" / "evidence")


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
    # ITS SCRATCH IS THE TEST'S: a unit case that writes a transcript or evidence would otherwise
    # leave a `mame-live-matrix-*` directory in the host's temporary directory.
    _point(module, monkeypatch, live_host.LiveRun(tmp_path / "scratch", job=False), tmp_path)
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
        return {"summary": "start", "status": "ok", "session": {}}

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

    sec = h.Section("Z", "a section of two boards", [h.Cell(c) for c in cells],
                    lambda: None)
    h.LEDGER.current = sec
    h.run_boards(cells, (h.Board(crashes, (0, 1), lambda: ""), h.Board(runs, (2,), lambda: "")))
    assert sec.judged == {"judged first": "OK", "left open": "FAIL", "the next board's": "OK"}
    assert h.failures == ["left open"]


def test_a_board_that_cannot_run_here_blocks_its_cells_and_runs_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    h = _harness(monkeypatch, tmp_path)
    ran: list[str] = []
    sec = h.Section("Z", "one board missing its bench copies",
                    [h.Cell("a"), h.Cell("b")], lambda: None)
    h.LEDGER.current = sec
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
    assert tmp_path / "bench.json" == boards.BENCH.manifest, "the manifest is the bench's own"
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
    monkeypatch.setattr(boards, "BENCH", boards.bench.Bench(boards.BENCH.root))
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
    monkeypatch.setattr(boards, "BENCH", boards.bench.Bench(boards.BENCH.root))
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

    sec = h.Section("Z", "a board refused half-way",
                    [h.Cell("judged"), h.Cell("open")], lambda: None)
    h.LEDGER.current = sec
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
        "reference_addr": "0x0", "inipath": boards.NO_JOYSTICK_INI}
    assert boards.board_dir("v30") == tmp_path / "v30dir"
    assert boards.opened("v30") == ["v30dir/run/mame_roms/v30set.zip",
                                    "v30dir/build/Game_V30.bin", "v30dir/build/game_v30.map"]
    assert boards.opened("v30-alt") == ["v30altdir/build/v30alt.bin",
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


@pytest.mark.parametrize("label", ["v30", "v30-alt"])
def test_a_game_board_runs_on_mame_binary_and_is_blocked_without_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, label: str,
) -> None:
    """The games' boards carry no binary of their own: they run on the one MAME, and without it
    they are BLOCKED naming MAME_BINARY, never started on some other build."""
    mame = tmp_path / "shared" / "mame"
    mame.parent.mkdir()
    mame.write_bytes(b"")
    for held, why in ((None, "set MAME_BINARY"), (str(tmp_path / "absent"), "set MAME_BINARY"),
                      (str(mame), "")):
        if held is None:
            monkeypatch.delenv("MAME_BINARY", raising=False)
        else:
            monkeypatch.setenv("MAME_BINARY", held)
        _harness(monkeypatch, tmp_path)
        boards = sys.modules["bench_boards"]
        monkeypatch.setattr(boards, "bench_missing", lambda prefix: "")
        monkeypatch.setattr(boards, "_unpinned", lambda board: "")
        binary, missing = boards.BINARY, boards.board_missing(label)
        assert binary == (held or "")
        assert missing.startswith(why) if why else missing == ""


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
    monkeypatch.setattr(boards, "BENCH", boards.bench.Bench(boards.BENCH.root))
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


def _matrix_function(name: str, module: str = "matrix_manifest", **names: object) -> object:
    """One function of a matrix module, compiled alone (the module boots boards on import) with
    `names` as its globals."""
    import ast
    from typing import Any
    tree = ast.parse((LIVE / f"{module}.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    space: dict[str, Any] = {"Any": Any, **names}
    # A name no file has: compiled under the matrix's own path, coverage would count the whole
    # matrix, which only a live run executes.
    exec(compile(ast.Module(body=[node], type_ignores=[]), f"<{module}.{name}>", "exec"),
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


def test_the_bench_root_is_the_variable_only_and_the_manifest_lives_in_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """This repository resolves its own bench and hands the directory to `scry_core.live_bench`,
    which knows no server: `MAME_LIVE_BENCH` (a `~` expanded, a relative path made absolute), and
    no path of its own when the variable is unset."""
    _harness(monkeypatch, tmp_path)
    boards = sys.modules["bench_boards"]
    assert boards.BENCH.root == tmp_path
    assert tmp_path / "bench.json" == boards.BENCH.manifest
    monkeypatch.delenv("MAME_LIVE_BENCH")
    assert boards._root() is None
    monkeypatch.setenv("MAME_LIVE_BENCH", "~/b")
    assert boards._root() == Path.home() / "b"
    monkeypatch.setenv("MAME_LIVE_BENCH", "relative")
    assert boards._root() == Path.cwd() / "relative"
    assert boards.bench_missing("dual/").endswith(
        f"`python -m scry_core.live_bench check --bench {tmp_path}`"), "the remedy names --bench"


def test_with_no_bench_named_every_board_is_refused_naming_the_variable(tmp_path: Path) -> None:
    """Unset, no board resolves to a directory of the developer's: each says to set the variable."""
    env = {k: v for k, v in os.environ.items() if k != "MAME_LIVE_BENCH"}
    probe = ("import bench_boards as b; "
             "print(b.board_missing('m68k-dual')); print(b.bench_missing('v30/')); "
             "import os; print(os.environ.get('MAME_LIVE_BENCH', 'unset'))")
    done = subprocess.run([sys.executable, "-c", probe], cwd=LIVE,
                          env={**env, "TMPDIR": str(tmp_path)}, capture_output=True, text=True,
                          check=False)
    assert done.returncode == 0, done.stderr
    board, prefix, exported = done.stdout.splitlines()
    assert board == prefix == "MAME_LIVE_BENCH is not set: name the bench directory with it"
    assert exported == "unset"


def _imported(module: str, tmp_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    """`module` imported in a fresh interpreter from the live tier, its temporary directory
    `tmp_path`, with no setting of the developer's shell deciding the answer."""
    clean = {k: v for k, v in os.environ.items() if k != "MAME_BACKGROUND"}
    return subprocess.run([sys.executable, "-c", f"import {module}"], cwd=LIVE,
                          env={**clean, "TMPDIR": str(tmp_path), **env}, capture_output=True,
                          text=True, check=False)


def test_every_start_built_from_the_bench_names_no_joystick_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A debug MAME aborts at boot while a game controller is connected, which the owner of
    the bench may be using: every start the bench builds reads an ini that turns joysticks off."""
    h = _harness(monkeypatch, tmp_path)
    alt = sys.modules["bench_boards"].M68K_DUAL_ALT_BOOT
    for ini in (h.BOOT.get("inipath"), alt.get("inipath"), h.no_joystick_ini()):
        text = (Path(str(ini)) / "mame.ini").read_text() if ini else ""
        assert "joystickprovider none" in text, ini


def test_importing_the_harness_makes_no_directory(tmp_path: Path) -> None:
    """Every file that imports the harness (this suite among them) leaves no scratch
    directory behind; the run makes its scratch when it first writes there, and an import
    writes nothing."""
    done = _imported("live_harness", tmp_path)
    assert done.returncode == 0, done.stderr[-2000:]
    assert list(tmp_path.iterdir()) == [], list(tmp_path.iterdir())


def test_the_matrix_imports_on_a_host_whose_bench_is_empty(tmp_path: Path) -> None:
    """A stranger's clone has no bench: the boards that need it are BLOCKED by the run, never a
    matrix that cannot be imported at all."""
    done = _imported("live_matrix", tmp_path / "t", MAME_LIVE_BENCH=str(tmp_path / "bench"))
    assert done.returncode == 0, done.stderr[-2000:]


# ================================================================ run_sections, with no machine


def _sections(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **env: str) -> ModuleType:
    """The harness ready to run sections of the test's own: its scratch under `tmp_path`, no
    machine to close, no declaration store moved, no signal handler left on this process, and
    the run's variables as given (unset otherwise)."""
    h = _harness(monkeypatch, tmp_path)
    monkeypatch.setattr(h, "ensure_closed", lambda: None)
    monkeypatch.setattr(h, "isolate_state", lambda _prefix: "")
    monkeypatch.setattr(h.signal, "signal", lambda *_a: None)
    # The run's end is called by the case, never left on this process's exit (`registered`
    # keeps what it would have been); the host is one that answers the canary; what the run sets
    # in the environment is undone with the case.
    registered: list[object] = []
    monkeypatch.setattr(h.atexit, "register", registered.append)
    monkeypatch.setattr(h, "registered", registered, raising=False)
    monkeypatch.setattr(h, "_canary_argv", lambda: ["mame", "board"])
    monkeypatch.setattr(live_host, "canary", lambda _argv: "")
    for var in (h.SECTIONS_VAR, h.JOBS_VAR, h.SUMMARY_VAR, live_host.LEDGER_VAR,
                live_host.SCRATCH_VAR):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    _point(h, monkeypatch, live_host.LiveRun(tmp_path / "scratch", job=h.SUMMARY_VAR in env),
           tmp_path)
    return h


def _launched(h: ModuleType) -> None:
    """What a section's server does at its spawn: one launch in the ledger the run named, of a
    pid long gone, so the end check has something to examine and finds it not alive."""
    if (ledger := live_host.EmulatorLedger.from_environment()) is not None:
        ledger.record(99999999, "mamed")


def _exit_of(h: ModuleType) -> object:
    with pytest.raises(SystemExit) as stop:
        h.run_sections("TEST")
    return stop.value.code


def _three(h: ModuleType) -> None:
    """A section that passes, one that raises half-way, and one that forgets a cell."""
    def passes() -> None:
        _launched(h)
        h.cell("a1", True)
    h.section("A", "passes", ["a1"])(passes)

    def half() -> None:
        h.cell("b1", True)
        raise RuntimeError("the stub hung")
    h.section("B", "raises", ["b1", "b2"])(half)
    h.section("C", "forgets", ["c1", "c2"])(lambda: h.cell("c1", True))


def _watch(h: ModuleType, *, beside: bool) -> None:
    """A control section, an optional one beside it, and a verdict that spans their run."""
    def control() -> None:
        _launched(h)
        h.cell("x-control", True)
    h.section("X", "control", ["x-control"], alone=True, opens=True)(control)
    if beside:
        h.section("A", "beside", ["a1"])(lambda: h.cell("a1", True))
    h.section("X", "verdict", ["x-verdict"], alone=True, spans=True)(
        lambda: h.blocked("x-verdict", "too little ran"))


def test_a_verdict_with_no_section_beside_it_is_named_when_the_run_is_planned(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    h = _sections(monkeypatch, tmp_path, MAME_LIVE_JOBS="1")
    _watch(h, beside=False)
    assert _exit_of(h) == h.EXIT_PASS, "naming a cell it cannot judge does not refuse the run"
    out = capsys.readouterr().out.splitlines()
    planned = next(i for i, line in enumerate(out) if line.startswith("PLANNED"))
    assert out[planned + 1].startswith("cannot be judged in this selection: x-verdict"), out
    assert not [x for x in out if x.startswith("cannot be judged") and "a1" in x]


def test_the_real_focus_verdict_is_registered_as_one_that_spans_the_run(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Dropping `spans` from the real section X would leave a verdict that cannot be judged named
    by no one, with every unit case green."""
    h = _sections(monkeypatch, tmp_path, MAME_LIVE_JOBS="1")
    monkeypatch.syspath_prepend(str(Path(__file__).parent / "live"))
    h.LEDGER.sections.clear()
    focus = importlib.import_module("matrix_focus")
    monkeypatch.setattr(focus, "section", h.section)
    focus.register_x_verdict()
    [verdict] = h.LEDGER.sections
    assert verdict.block == "X" and verdict.spans
    assert [label for label, _ in h.cannot_be_judged([verdict])] == verdict.labels


def test_a_verdict_with_a_section_beside_it_is_not_named(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    h = _sections(monkeypatch, tmp_path, MAME_LIVE_JOBS="1")
    _watch(h, beside=True)
    _exit_of(h)
    assert "cannot be judged" not in capsys.readouterr().out


def test_a_section_that_raises_fails_what_it_left_open_and_the_next_one_still_runs(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    """BLOCKED never counts against the run, so a section that raised cannot close it PASSED: its
    first open cell is the FAIL and the cells after it BLOCKED. A cell a section simply never
    reached is BLOCKED here, which is a section that stopped short, not one that crashed."""
    h = _sections(monkeypatch, tmp_path, MAME_LIVE_JOBS="1")
    _three(h)
    assert _exit_of(h) == h.EXIT_FAIL
    out = capsys.readouterr().out
    assert "jobs: 1, every section in this process" in out
    assert "PLANNED 5 RUN 4 OK 3 FAIL 1 BLOCKED 1" in out
    assert h.failures == ["b2"] and h.FAIL_WHY["b2"].startswith(
        "section aborted: RuntimeError: the stub hung")
    assert dict(h.BLOCKED) == {"c2": "never reached: the section ended without judging it"}


def test_a_blocked_row_outside_any_section_is_a_row_and_a_tally_not_a_crash(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    """`live_check.py` runs no sections, and its game demos are BLOCKED by name when a game's
    romset is not named."""
    h = _harness(monkeypatch, tmp_path)
    assert h.LEDGER.current is None
    h.blocked("the game demo", "set GAME_ROMS to the directory")
    assert "BLOCKED" in capsys.readouterr().out
    assert h.BLOCKED == [("the game demo", "set GAME_ROMS to the directory")]
    assert h.TALLY["BLOCKED"] == 1


def test_the_verdict_of_a_run_with_no_sections_lists_its_blocked_rows_after_the_failures(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    """`live_check.py` runs no sections: its game demos block by name, then `finish` speaks."""
    h = _sections(monkeypatch, tmp_path)
    _launched(h)
    h.check("a thing that fails", False)
    h.blocked("the game demo", "set GAME_ROMS to the directory")
    with pytest.raises(SystemExit):
        h.finish("LIVE CHECK")
    out = capsys.readouterr().out.splitlines()
    failed = next(i for i, line in enumerate(out) if line.startswith("1 check failed"))
    listed = [i for i, line in enumerate(out) if "the game demo" in line and i > failed]
    assert len(listed) == 1 and out[-1].startswith("==> LIVE CHECK FAILED"), out


def test_a_matrix_run_prints_each_blocked_row_in_its_recap_once(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    """Once where the cell is blocked and once in the recap, so the verdict is read beside every
    reason it rests on."""
    h = _sections(monkeypatch, tmp_path, MAME_LIVE_JOBS="1")

    def blocks() -> None:
        _launched(h)
        h.cell("b1", True)
        h.blocked("b2", "the stub hung")

    h.section("B", "blocks half-way", ["b1", "b2"])(blocks)
    h.section("C", "forgets", ["c1", "c2"])(lambda: h.cell("c1", True))
    _exit_of(h)
    out = capsys.readouterr().out.splitlines()
    for why in ("stub hung", "never reached"):
        assert len([x for x in out if x.startswith("  BLOCKED") and why in x]) == 2, out


def test_a_run_that_is_a_job_declares_every_cell_it_planned(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    summary = tmp_path / "summary.json"
    h = _sections(monkeypatch, tmp_path, MAME_LIVE_SUMMARY=str(summary))
    _three(h)
    h.section("D", "fails", ["d1"])(lambda: h.cell("d1", False, "it said no"))
    assert _exit_of(h) == h.EXIT_FAIL
    got = h.live_pool.read_summary(summary)
    assert got.outcomes == {"a1": "OK", "b1": "OK", "b2": "FAIL", "c1": "OK",
                            "c2": "BLOCKED", "d1": "FAIL"}
    assert got.reasons["d1"] == "it said no" and "RuntimeError" in got.reasons["b2"]


@pytest.mark.parametrize(("env", "plan", "code", "said"), [
    ({"MAME_LIVE_SECTIONS": "AZ"}, [("A", ["a1"])], 3, "names no section ['Z']"),
    ({"MAME_LIVE_JOBS": "0"}, [("A", ["a1"])], 2, "is not a job count"),
    ({"MAME_LIVE_JOBS": "two"}, [("A", ["a1"])], 2, "is not a job count"),
    ({"MAME_LIVE_JOBS": "1"}, [("A", ["a1"]), ("B", ["a1"])], 3, "names these cells twice"),
    ({"MAME_LIVE_JOBS": "1"}, [("A", ["a1"])], 3, "no cell ran"),
])
def test_a_run_that_cannot_give_a_verdict_says_so_and_exits_apart(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
        env: dict[str, str], plan: list[tuple[str, list[str]]], code: int, said: str) -> None:
    h = _sections(monkeypatch, tmp_path, **env)
    for letter, labels in plan:
        h.section(letter, letter, labels)(lambda: None)
    assert _exit_of(h) == code
    assert said in capsys.readouterr().out


def test_a_pooled_run_adopts_each_job_s_cells_and_runs_the_alone_ones_here(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    h = _sections(monkeypatch, tmp_path, MAME_LIVE_JOBS="2")
    lp = h.live_pool
    order: list[str] = []
    h.section("X", "opens the run", ["x1"], alone=True, opens=True)(lambda: order.append("X"))
    h.section("A", "pooled", ["a1", "a2"])(lambda: order.append("A"))
    h.section("B", "pooled", ["b1"])(lambda: order.append("B"))
    (tmp_path / f"{h.SCRATCH_PREFIX}A").mkdir()
    (tmp_path / f"{h.SCRATCH_PREFIX}B").mkdir()
    child = tmp_path / f"{h.SCRATCH_PREFIX}A" / "transcript.jsonl"
    child.write_text('{"from": "a job"}\n')

    def run_pool(jobs: list[object], workers: int, out: Path, var: str,
                 on_done: object) -> object:
        order.append("pool")
        assert workers == 2 and var == h.SUMMARY_VAR
        assert [(j.name, dict(j.env), j.planned) for j in jobs] == [  # type: ignore[attr-defined]
            ("A", {h.SECTIONS_VAR: "A", h.JOBS_VAR: "1", **h.RUN.job_env("A")}, ("a1", "a2")),
            ("B", {h.SECTIONS_VAR: "B", h.JOBS_VAR: "1", **h.RUN.job_env("B")}, ("b1",))]
        a = lp.JobResult(jobs[0], 1, out / "A.log", 1.0, lp.Summary(
            ("a1", "a2"), {"a1": "OK", "a2": "FAIL"}, {"a2": "no"}, str(child), 1.0))
        b = lp.JobResult(jobs[1], 7, out / "B.log", 1.0, lp.Summary(
            ("b1",), {"b1": "BLOCKED"}, {"b1": "no bench"},
            str(tmp_path / f"{h.SCRATCH_PREFIX}B" / "gone"), 1.0))
        for r in (a, b):
            on_done(r)  # type: ignore[operator]
        return lp.PoolResult([a, b], "", {"a1": "OK", "a2": "FAIL", "b1": "BLOCKED"},
                             {"a2": "no", "b1": "no bench"})
    monkeypatch.setattr(lp, "run_pool", run_pool)
    assert _exit_of(h) == h.EXIT_FAIL
    out = capsys.readouterr().out
    assert order == ["X", "pool"], "the alone section runs here, the pooled ones as jobs"
    assert "[A] OK 1 FAIL 1 BLOCKED 0" in out and "[B] OK 0 FAIL 0 BLOCKED 1" in out
    assert any("JOB B EXITED 7, WHICH ITS SUMMARY DOES NOT EXPLAIN" in f for f in h.failures)
    assert "a2" in h.failures and dict(h.BLOCKED)["b1"] == "no bench"
    assert '{"from": "a job"}' in (tmp_path / "scratch" / "transcript.jsonl").read_text()


def test_a_pool_that_cannot_be_believed_makes_the_run_invalid_and_keeps_its_scratch(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    h = _sections(monkeypatch, tmp_path, MAME_LIVE_JOBS="4")
    h.section("A", "pooled", ["a1"])(lambda: None)
    h.section("B", "pooled", ["b1"])(lambda: None)
    lp = h.live_pool
    monkeypatch.setattr(lp, "run_pool", lambda *_a, **_k: lp.PoolResult(
        [], "a job declared a cell it never planned", {"a1": "OK", "b1": "OK"}))
    with pytest.raises(SystemExit) as stop:
        h.run_sections("TEST")
    out = capsys.readouterr().out.rstrip().splitlines()
    assert stop.value.code == h.EXIT_INVALID
    assert out[-2:] == [f"kept: {tmp_path / 'scratch'}",
                        "==> TEST INVALID: a job declared a cell it never planned"]


def test_one_pooled_letter_is_no_pool_and_runs_here(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    h = _sections(monkeypatch, tmp_path, MAME_LIVE_JOBS="4")

    def alone() -> None:
        _launched(h)
        h.cell("a1", True)
    h.section("A", "alone in the pool", ["a1"])(alone)
    monkeypatch.setattr(h.live_pool, "run_pool", lambda *_a, **_k: pytest.fail("pooled"))
    assert _exit_of(h) == h.EXIT_PASS


def test_a_signal_that_ends_the_run_is_an_exit_its_children_see(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    h = _sections(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as stop:
        h._leave(15, None)
    assert stop.value.code == 128 + 15


# ======================================================== the run on its host and its scratch


def _ended(h: ModuleType, *, invalid: bool = False) -> object:
    """`run_sections`' exit code, then what the process's exit would run (`registered`)."""
    with pytest.raises(SystemExit) as stop:
        h.run_sections("TEST")
    for f in h.registered:
        f()
    return stop.value.code


def test_a_run_registers_its_end_for_every_way_out(monkeypatch: pytest.MonkeyPatch,
                                                   tmp_path: Path) -> None:
    h = _sections(monkeypatch, tmp_path, MAME_LIVE_JOBS="1")
    h.section("A", "passes", ["a1"])(lambda: h.cell("a1", True))
    _ended(h)
    assert h.registered == [h._unfinished]


def test_a_green_run_removes_its_scratch_and_its_jobs(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    h = _sections(monkeypatch, tmp_path, MAME_LIVE_JOBS="2")
    lp = h.live_pool
    h.section("A", "pooled", ["a1"])(lambda: None)
    h.section("B", "pooled", ["b1"])(lambda: None)
    handed: list[str] = []

    def run_pool(jobs: list[object], *_a: object, **_k: object) -> object:
        for j in jobs:
            scratch = Path(j.env[live_host.SCRATCH_VAR])  # type: ignore[attr-defined]
            scratch.mkdir(parents=True)
            handed.append(str(scratch))
        _launched(h)
        return lp.PoolResult([], "", {"a1": "OK", "b1": "OK"}, {})
    monkeypatch.setattr(lp, "run_pool", run_pool)
    assert _ended(h) == h.EXIT_PASS
    assert all(Path(x).parent.parent == tmp_path / "scratch" for x in handed) and len(handed) == 2
    assert "scratch removed, the transcript with it" in capsys.readouterr().out
    assert sorted(p.name for p in tmp_path.iterdir()) == ["identity.json"]


def test_a_red_run_keeps_its_scratch_and_names_it_as_its_last_word_but_the_verdict(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    h = _sections(monkeypatch, tmp_path, MAME_LIVE_JOBS="1")
    h.section("C", "fails here", ["c1"])(lambda: h.cell("c1", False))
    assert _ended(h) == h.EXIT_FAIL
    out = capsys.readouterr().out.rstrip().splitlines()
    assert out[-2:] == [f"kept: {tmp_path / 'scratch'}", "==> TEST FAILED"]


def test_a_pooled_job_leaves_its_scratch_to_the_run_that_adopts_it_and_proves_nothing(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    h = _sections(monkeypatch, tmp_path, MAME_LIVE_SUMMARY=str(tmp_path / "summary.json"))
    monkeypatch.setenv(live_host.LEDGER_VAR, str(tmp_path / "the parents.tsv"))
    monkeypatch.setattr(live_host, "canary", lambda _argv: pytest.fail("a second canary"))
    monkeypatch.setattr(live_host.EmulatorLedger, "reap", lambda _s: pytest.fail("reaped"))
    h.section("A", "passes", ["a1"])(lambda: h.cell("a1", True))
    h.scratch()
    assert _ended(h) == h.EXIT_PASS
    out = capsys.readouterr().out
    assert "scratch removed" not in out and "kept:" not in out
    assert (tmp_path / "scratch").is_dir()


@pytest.mark.parametrize("plan", [[("A", ["a1"]), ("B", ["a1"])], [("A", ["a1"])]],
                         ids=["a cell planned twice", "no cell ran"])
def test_a_run_that_ends_invalid_keeps_its_scratch_and_says_invalid_last(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
        plan: list[tuple[str, list[str]]]) -> None:
    h = _sections(monkeypatch, tmp_path, MAME_LIVE_JOBS="1")
    for letter, labels in plan:
        h.section(letter, letter, labels)(lambda: None)
    assert _ended(h) == h.EXIT_INVALID
    out = capsys.readouterr().out.rstrip().splitlines()
    assert out[-2] == f"kept: {tmp_path / 'scratch'}" \
        and out[-1].startswith("==> TEST INVALID: ")


def test_a_run_that_breaks_or_is_signalled_keeps_its_scratch_and_names_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    h = _sections(monkeypatch, tmp_path, MAME_LIVE_JOBS="1")

    def signalled() -> None:
        h._leave(15, None)
    h.section("A", "signalled", ["a1"])(signalled)
    assert _ended(h) == 128 + 15
    assert f"kept: {tmp_path / 'scratch'}" in capsys.readouterr().out


def test_a_host_that_cannot_start_mame_refuses_the_run_before_any_section_and_makes_nothing(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    h = _sections(monkeypatch, tmp_path, MAME_LIVE_JOBS="1")
    ran: list[str] = []
    h.section("A", "would start", ["a1"])(lambda: ran.append("A"))
    monkeypatch.setattr(live_host, "canary", lambda _argv: "mamed did not return")
    assert _ended(h) == h.EXIT_INVALID
    assert ran == [] and not (tmp_path / "scratch").exists()
    assert "INVALID: host canary: mamed did not return" in capsys.readouterr().err


def test_invalid_ends_the_run_itself_so_its_verdict_is_the_last_word(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    h = _sections(monkeypatch, tmp_path)
    h.scratch()
    with pytest.raises(SystemExit) as stop:
        h.invalid("the bench is off its pins")
    said = capsys.readouterr()
    assert stop.value.code == h.EXIT_INVALID and h.RUN.finished
    assert said.out.rstrip().endswith(f"kept: {tmp_path / 'scratch'}")
    assert said.err == "INVALID: the bench is off its pins\n"


def test_a_section_letter_that_names_none_launches_no_canary(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    h = _sections(monkeypatch, tmp_path, MAME_LIVE_SECTIONS="Z")
    h.section("A", "a", ["a1"])(lambda: None)
    monkeypatch.setattr(live_host, "canary", lambda _argv: pytest.fail("a canary launched"))
    assert _ended(h) == h.EXIT_INVALID


def test_the_canary_is_the_first_boot_s_board_or_the_free_circus_or_none(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    h = _harness(monkeypatch, tmp_path)
    monkeypatch.setattr(h, "m68k_dual_missing", lambda: "")
    board = h._canary_argv()
    assert board[:4] == [str(h.BOOT["binary"]), str(h.BOOT["system"]), "-rompath",
                         str(h.BOOT["rompath"])] and "-joystickprovider" not in board
    monkeypatch.setattr(h, "m68k_dual_missing", lambda: "no bench")
    monkeypatch.setattr(h, "free_boards_missing", lambda: "")
    circus = h._canary_argv()
    assert circus[1] == "circus" and circus[4:6] == ["-joystickprovider", "none"]
    monkeypatch.setattr(h, "free_boards_missing", lambda: "no free boards")
    assert h._canary_argv() is None


def test_an_emulator_that_outlived_the_run_fails_it_by_name_beside_the_verdict(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    h = _sections(monkeypatch, tmp_path, MAME_LIVE_JOBS="1")
    h.section("A", "passes", ["a1"])(lambda: h.cell("a1", True))
    order: list[str] = []
    monkeypatch.setattr(h.STATE, "kill", lambda: order.append("kill"))

    def reap(_self: object) -> object:
        order.append("reap")
        return live_host.Leftovers(2, 2, ((41, "U"),))
    monkeypatch.setattr(live_host.EmulatorLedger, "reap", reap)
    assert _ended(h) == h.EXIT_FAIL
    out = capsys.readouterr().out
    assert order == ["kill", "reap"]
    assert "FAIL  2 emulators outlived the run" in out and "pid 41 state U" in out
    assert out.rstrip().endswith("==> TEST FAILED")
    assert os.environ[live_host.LEDGER_VAR] == str(
        tmp_path / "scratch" / live_host.LEDGER_NAME)


class _Runs:
    """A scripted `run_for`: each leg's reply in turn, on a clock the leg advances by its own
    `spent` seconds, so a bound that ran out is told apart from a quick answer."""

    def __init__(self, replies: list[tuple[dict[str, object], float]]) -> None:
        self.replies, self.now = list(replies), 0.0
        self.asked: list[object] = []

    def call(self, tool: str, **kw: object) -> dict[str, object]:
        assert tool == "run_for" and set(kw) == {"frames", "seconds"}
        self.asked.append(kw["frames"])
        reply, spent = self.replies.pop(0)
        self.now += spent
        return reply

    def clock(self) -> float:
        return self.now


def _reply(**body: object) -> dict[str, object]:
    """A reply in the envelope every one keeps: `summary` first, `session` last."""
    return {"summary": "s", **body, "session": {}}


def _elapsed(before: int, after: int) -> dict[str, object]:
    return _reply(status="ok", verdict="ELAPSED", frame_before=before, frame_after=after)


def _short(before: int, after: int, message: str) -> dict[str, object]:
    return _reply(status="INVALID", code="not_settled", frame_before=before, frame_after=after,
                  message=message)


def _run_frames(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, frames: int,
                replies: list[tuple[dict[str, object], float]],
                **kw: int) -> tuple[_Runs, dict[str, object] | BaseException]:
    h = _harness(monkeypatch, tmp_path)
    runs = _Runs(replies)
    monkeypatch.setattr(h, "call", runs.call)
    monkeypatch.setattr(h.time, "monotonic", runs.clock)
    try:
        return runs, h.run_frames(frames, **kw)
    except h.Blocked as e:
        return runs, e


def test_a_frame_run_goes_in_legs_and_the_next_asks_what_the_counter_left(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runs, got = _run_frames(monkeypatch, tmp_path, 700, [
        (_elapsed(3, 303), 5.0), (_elapsed(303, 608), 5.0), (_elapsed(608, 703), 2.0)])
    assert runs.asked == [300, 300, 95]           # the overshoot to 608 is not run again
    assert got == _elapsed(608, 703)


def test_a_leg_its_bound_cut_short_is_blocked_naming_what_it_reached(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runs, got = _run_frames(monkeypatch, tmp_path, 600, [
        (_elapsed(0, 300), 5.0), (_short(300, 485, "reached 485 of the 600 asked for"), 10.0)])
    assert isinstance(got, BaseException) and runs.asked == [300, 300]
    assert "reached frame 485 of 600 in 10.0 s" in str(got) and "speed" in str(got)


@pytest.mark.parametrize("reply, spent", [
    # every frame landed and the counter still moves: the server's defect, not the host's
    (_short(0, 300, "reached 300 of the 300 asked for and still moves"), 4.0),
    # a session that failed quickly, short of the frames: no bound ran out
    (_short(0, 120, "the session failed before its landing was confirmed"), 2.0),
    # the bound ran out with the counter standing still: no load explains no frame at all
    (_short(5, 5, "reached 5 of the 305 asked for"), 10.0),
    (_reply(status="ok", verdict="OTHER_STOP", frame_before=0, frame_after=40), 1.0),
    (_reply(status="INVALID", code="bad_argument", message="no"), 0.0),
])
def test_any_other_answer_is_the_cells_to_judge_and_no_later_leg_is_sent(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, reply: dict[str, object],
        spent: float) -> None:
    runs, got = _run_frames(monkeypatch, tmp_path, 600, [(reply, spent)])
    assert got == reply and runs.asked == [300]


def test_a_leg_of_no_frames_is_refused_before_anything_is_asked(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="leg"):
        _run_frames(monkeypatch, tmp_path, 5, [], leg_frames=0)


def test_the_leg_follows_the_caller_and_no_run_of_nothing_is_asked(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runs, _ = _run_frames(monkeypatch, tmp_path, 200, [(_elapsed(0, 100), 1.0),
                                                       (_elapsed(100, 200), 1.0)], leg_frames=100)
    assert runs.asked == [100, 100]


def test_a_run_of_no_frame_is_refused_before_any_call(monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one frame"):
        _run_frames(monkeypatch, tmp_path, 0, [])


def _focus_section(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    """Section X's module, on the harness `_harness` loads, on no machine."""
    _harness(monkeypatch, tmp_path)
    monkeypatch.delitem(sys.modules, "matrix_focus", raising=False)
    spec = importlib.util.spec_from_file_location("matrix_focus", LIVE / "matrix_focus.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_focus_gate_names_a_held_boards_binary_and_skips_one_the_bench_lacks(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    x = _focus_section(monkeypatch, tmp_path)
    monkeypatch.setattr(x.bench_boards, "board_missing",
                        lambda board: "" if board == "m68k-dual-alt" else "copies ABSENT")
    names = x._names()
    assert "altmame" in names and "dualmame" not in names


def test_a_bench_defect_reaching_the_focus_gates_names_is_raised_never_dropped(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A binary dropped from the names in silence would let the verdict read CLEAN over it."""
    x = _focus_section(monkeypatch, tmp_path)
    monkeypatch.setattr(x, "BENCH_BOARDS", ("no-such-board",))
    with pytest.raises(KeyError, match="no-such-board"):
        x._names()


def test_no_cell_names_its_missing_file_by_a_posix_literal() -> None:
    """`/nonexistent/x` has no drive, so Windows refuses it as a relative path before the case
    the cell judges; the matrix builds it with the host's own anchor."""
    import ast

    tree = ast.parse((LIVE / "matrix_tools_by_state.py").read_text(encoding="utf-8"))
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and n.value.startswith("/nonexistent")]
    assert tree.body and literals == []


def test_open_files_says_it_could_not_when_the_host_has_no_lsof(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A host without `lsof` (Windows) must reach the cell's BLOCKED path, not abort the section."""
    def absent(*a: object, **k: object) -> None:
        raise FileNotFoundError(2, "The system cannot find the file specified")

    monkeypatch.setattr(subprocess, "run", absent)
    open_files = _matrix_function("open_files", "matrix_pairs", subprocess=subprocess)
    assert callable(open_files) and open_files(123) is None


def test_a_free_board_boots_the_bundle_only_when_the_run_asks_for_the_app_route(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`MAME_LIVE_BUNDLE` names the `.app` a free board starts; a board naming its own build
    keeps it, and a run that does not ask for the route boots `MAME_BINARY` as before."""
    monkeypatch.setenv("MAME_LIVE_BUNDLE", str(tmp_path.parent / "Probe.app"))
    h = _harness(monkeypatch, tmp_path)
    handed: list[dict[str, object]] = []

    def start(**kw: object) -> dict[str, object]:
        handed.append(kw)
        return {"summary": "start", "status": "ok", "session": {}}

    def stub(module: ModuleType) -> None:
        monkeypatch.setattr(module.s, "start", start)
        monkeypatch.setattr(module, "free_image", lambda *a, **k: tmp_path.parent / "img.bin")

    stub(h)
    h.free_boot("circus", ["9004a.1a"], "0x1000")
    h.free_boot("circus", ["9004a.1a"], "0x1000", binary="/elsewhere/mame")
    assert handed[0]["binary"] == str(tmp_path.parent / "Probe.app")
    assert handed[1]["binary"] == "/elsewhere/mame"
    # The control: a run that does not prove the app route is unchanged.
    monkeypatch.delenv("MAME_LIVE_BUNDLE", raising=False)
    plain = tmp_path / "plain"
    plain.mkdir()
    h2 = _harness(monkeypatch, plain)
    handed.clear()
    stub(h2)
    h2.free_boot("circus", ["9004a.1a"], "0x1000")
    # No binary in the call: the `free` recipe names `MAME_BINARY`, and only the app route or
    # a caller's own binary overrides it.
    assert "binary" not in handed[0], handed[0]
