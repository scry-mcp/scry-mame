"""The value scan (`mame_scan`), judged against MAME's own engine.

The known answer is never computed by the code under test. `fixtures/scan/` holds what a live
session captured (`PROVENANCE.txt`): the scanned range dumped at successive stops of v30
(V30, little-endian) and m68k-dual (68000, big-endian), and after each pair of stops MAME's
own `cheatlist` for every operator its console expresses, the cell compared against the value
it held when the scan opened (`cheatnextf`) or against a value. A scan opened on the first dump
and filtered on the second must keep exactly the cells, with exactly the values, MAME kept.
"""

import asyncio
import copy
import gzip
import hashlib
import re
from operator import gt, lt, ne
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import pytest
from session_doubles import captured, published
from test_server import _console, _ConsoleSession, _masked

import gdb_session as gs
import mame_read as read
import mame_scan as mscan
import mame_state as mstate
import server as s

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "scan"
BOARDS: dict[str, tuple[int, Literal["little", "big"]]] = {
    "v30": (0x0, "little"), "m68k-dual": (0x200000, "big")}
WIDTH_OF = {"ub": "byte", "uw": "word", "ud": "dword"}
#: A cell's size in bytes, by the name the tests are parametrized with.
SIZE = {"byte": 1, "word": 2, "dword": 4}
CELL = {"ub": 1, "uw": 2, "ud": 4}
# MAME's word for a comparison against the opening value, and the scan's spelling of it.
NO_VALUE = {"equal": "=", "notequal": "!", "increase": ">", "decrease": "<",
            "increaseorequal": ">=", "decreaseorequal": "<="}
WITH_VALUE = {"equal": "=", "notequal": "!", "gt": ">", "lt": "<"}


def scratch() -> Path:
    held = mstate.STATE.scratch
    assert held is not None
    return held


def dump(name: str) -> bytes:
    return gzip.decompress((FIXTURES / f"{name}.bin.gz").read_bytes())


class Board(_ConsoleSession):
    """A machine whose memory the test sets between stops. `save <file>,<addr>[:<cpu>],<len>`
    writes that slice of it to the file, as MAME's console does, and is kept in `saved` as
    (address, length); `read` serves the same bytes through any thread. It cannot step: a scan
    that moved the machine would raise."""

    def __init__(self, base: int, memory: bytes, order: str = "little") -> None:
        super().__init__(b"", replies={"cpulist": captured("cpulist.main-visible.txt"),
                                       "save": self._save})
        self.base, self.memory, self.order = base, bytearray(memory), order
        self.threads = {1: ":maincpu", 2: ":subcpu"}
        self.saved: list[tuple[int, int]] = []

    def at(self, addr: int, n: int) -> bytes:
        return bytes(self.memory[addr - self.base: addr - self.base + n])

    def _save(self, command: str) -> str:
        path, start, length = command[len("save "):].split(",")
        self.saved.append((int(start.split(":")[0], 16), int(length, 16)))
        Path(path).write_bytes(self.at(*self.saved[-1]))
        return "Data saved successfully"

    def read(self, addr: int, n: int, *, thread: int) -> bytes:
        return self.at(addr, n)

    def layout(self, thread: int) -> Any:
        return SimpleNamespace(byte_order=self.order)

    def step(self, *_: Any, **__: Any) -> Any:
        raise AssertionError("the scan stepped the machine")


@pytest.fixture
def board(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """`board(name, memory)`: that board installed as the live, stopped session."""
    def install(name: str, memory: bytes) -> Board:
        base, order = BOARDS.get(name, (0x0, "little"))
        ses = Board(base, memory, order)
        _console(monkeypatch, tmp_path, ses)
        mask = 0xFFFFFF if name == "m68k-dual" else 0xFFFFF
        monkeypatch.setattr(mstate.STATE, "machine_map", _masked(mask))
        monkeypatch.setattr(mstate.STATE, "scan", None)
        return ses
    return install


def survivors() -> set[tuple[int, int]]:
    """Every survivor of the open scan as (address, value now), whether listed or not."""
    held = mstate.STATE.scan
    assert held is not None
    return set(held.surviving())


def rows_of(name: str) -> tuple[int, str] | set[tuple[int, int]]:
    """MAME's list: the rows, or, above the size kept whole, their count and sha256."""
    if (FIXTURES / f"{name}.rows.gz").is_file():
        text = gzip.decompress((FIXTURES / f"{name}.rows.gz").read_bytes()).decode()
        return {(int(a, 16), int(v, 16)) for a, v in (ln.split() for ln in text.splitlines())}
    count, digest = (FIXTURES / f"{name}.rows.sha256").read_text().split()
    return int(count), digest


def same_as_mame(ours: set[tuple[int, int]], name: str) -> None:
    theirs = rows_of(name)
    if isinstance(theirs, set):
        assert ours == theirs, (name, sorted(ours ^ theirs)[:10])
        return
    text = "".join(f"{a:x} {v:x}\n" for a, v in sorted(ours))
    assert (len(ours), hashlib.sha256(text.encode()).hexdigest()) == theirs, name


def not_admitted(name: str, width: str) -> set[int]:
    """The cells MAME's engine did not take (a driver's write taps on m68k-dual): its list
    leaves them out, so the comparison does too."""
    f = FIXTURES / f"{name}-{width}-not-admitted.txt"
    return {int(a, 16) for a in f.read_text().split()} if f.is_file() else set()


def cases() -> list[tuple[str, str, str]]:
    return [tuple(re.fullmatch(r"(.+)-(u[bwd])-(.+)", f.name.split(".")[0]).groups())  # type: ignore[union-attr]
            for f in sorted(FIXTURES.glob("*-u?-*.rows.*"))]


def test_every_list_mame_captured_is_a_case() -> None:
    """An empty parametrize is a skip, not a red: the oracle's own count is held here, twelve
    operators at each of three widths on each of two boards."""
    found = cases()
    assert len(found) == 2 * 3 * 12, found
    assert {(n, w) for n, w, _ in found} == {(n, w) for n in BOARDS for w in CELL}


@pytest.mark.parametrize(("name", "width", "op"), cases())
def test_every_operator_keeps_what_mames_own_engine_keeps(
        board: Any, name: str, width: str, op: str) -> None:
    pair = {"ub": (1, 2), "uw": (2, 3), "ud": (3, 4)}[width]
    base, _ = BOARDS[name]
    ses = board(name, dump(f"{name}-stop{pair[0]}"))
    opened = s.scan_start(ref=f"{base:#x}", length=0x10000, cell_bytes=SIZE[WIDTH_OF[width]])
    assert opened["status"] == "ok" and opened["hits_total"] == 0x10000 // CELL[width], opened
    ses.memory[:] = dump(f"{name}-stop{pair[1]}")
    word, _, spelled = op.partition("_")
    gone = not_admitted(name, width)
    theirs = rows_of(f"{name}-{width}-{op}")
    if isinstance(theirs, set):
        assert not gone & {a for a, _ in theirs}, "a cell left out is one MAME listed"
    tried: list[tuple[str, int | None]] = []
    if not spelled:
        tried.append((NO_VALUE[word], None))
    else:
        v = int(spelled, 16)
        tried.append((WITH_VALUE[word], v))
        # MAME has no `>=` or `<=` against a value: `gt v-1` and `lt v+1` are their oracles.
        if word in ("gt", "lt"):
            tried.append((">=", v + 1) if word == "gt" else ("<=", v - 1))
    for operator, value in tried:
        s.scan_clear()
        ses.memory[:] = dump(f"{name}-stop{pair[0]}")
        s.scan_start(ref=f"{base:#x}", length=0x10000, cell_bytes=SIZE[WIDTH_OF[width]])
        ses.memory[:] = dump(f"{name}-stop{pair[1]}")
        out = s.scan_filter(operator=operator, value=value)
        assert out["status"] == "ok" and out["iterations"] == 1, out
        ours = (set() if out["closed"] else survivors())
        same_as_mame({(a, v) for a, v in ours if a not in gone}, f"{name}-{width}-{op}")
        assert not list((scratch() / "scan").iterdir()), "a range copy left behind"


def test_two_filters_compare_against_the_scan_as_opened(board: Any) -> None:
    """MAME's `cheatnextf notequal` twice over three stops, the second list the cells that
    differ from the opening at stop 3 among those that differed at stop 2: a rolling
    comparison (against stop 2) would drop the cells that changed once and stayed."""
    ses = board("m68k-dual", dump("m68k-dual-mf-stop1"))
    gone = not_admitted("m68k-dual", "ub")
    s.scan_start(ref="0x200000", length=0x10000)
    ses.memory[:] = dump("m68k-dual-mf-stop2")
    first = s.scan_filter(operator="!")
    same_as_mame({r for r in survivors() if r[0] not in gone}, "m68k-dual-mf-f1")
    ses.memory[:] = dump("m68k-dual-mf-stop3")
    second = s.scan_filter(operator="!")
    assert (first["iterations"], second["iterations"]) == (1, 2)
    same_as_mame({r for r in survivors() if r[0] not in gone}, "m68k-dual-mf-f2")


def test_a_cell_written_back_to_its_opening_value_drops_out_of_changed(board: Any) -> None:
    """This server's own semantics on a synthetic block (no engine to ask): a cell changed once
    keeps passing `!`, and written back to what it held when the scan opened it stops."""
    ses = board("v30", bytes(0x100))
    s.scan_start(ref="0x0", length=0x10)
    ses.memory[3] = 0xA5
    one = s.scan_filter(operator="!")
    assert one["hits_total"] == 1 and "survivors" not in one, "the open reply's one count"
    assert one["summary"] == "scan_filter !: 1 survivor", one["summary"]
    assert s.scan_filter(operator="!")["hits_total"] == 1, "compared with the opening, not the last"
    ses.memory[3] = 0
    out = s.scan_filter(operator="!")
    assert (out["closed"], out["hits_total"], out["iterations"]) == (True, 0, 3), out
    assert mstate.STATE.scan is None


# ---- the reply, the listing and the life of a scan ------------------------------------------


def test_a_scan_answers_its_cells_cpu_and_space_and_moves_nothing(board: Any) -> None:
    ses = board("m68k-dual", dump("m68k-dual-stop1"))
    out = s.scan_start(ref="0x200000", length=0x100, cell_bytes=2)
    assert "width" not in out, out
    assert {k: out[k] for k in ("addr", "length", "cell_bytes", "hits_total", "cpu",
                                "space")} == {
        "addr": "0x00200000", "length": 0x100, "cell_bytes": 2,
        "hits_total": 0x80, "cpu": ":maincpu", "space": "program"}, out
    assert out["summary"] == "scan_start 0x200000: 128 2-byte candidates on :maincpu", out
    assert out["session"]["altered"] is False
    shut = s.scan_filter(operator="!")
    assert {k: shut[k] for k in ("operator", "value", "iterations", "closed", "hits",
                                 "hits_total", "truncated", "cpu", "space")} == {
        "operator": "!", "value": {"available": False, "why": mscan.NO_VALUE_WHY},
        "iterations": 1, "closed": True,
        "hits": [], "hits_total": 0, "truncated": False, "cpu": ":maincpu",
        "space": "program"}, shut
    assert "survivors" not in shut and "candidates" not in out, "one key per count"
    assert shut["summary"] == "scan_filter !: 0 survivors, scan closed", shut["summary"]
    assert "listed" not in shut and shut["session"]["altered"] is False
    assert [c for c in ses.commands if not c.startswith(("save ", "cpulist"))] == []


def test_word_cells_decode_in_the_cpus_order_and_may_start_odd(board: Any) -> None:
    for name, at, want in [("m68k-dual", 0x200001, 0x1234), ("v30", 0x1, 0x3412)]:
        base, _ = BOARDS[name]
        memory = bytearray(0x100)
        ses = board(name, bytes(memory))
        s.scan_start(ref=f"{at:#x}", length=4, cell_bytes=2)
        ses.memory[at - base:at - base + 2] = b"\x12\x34"
        out = s.scan_filter(operator="=", value=want)
        assert out["hits"] == [{"addr": f"{at:#010x}", "value": f"0x{want:04x}"}], (name, out)


def test_the_listing_is_whole_up_to_the_ceiling_and_cut_whole_above(board: Any) -> None:
    ceiling = read.LOG_LIMIT_MAX
    for moved, listed in [(ceiling, True), (ceiling + 1, False)]:
        ses = board("v30", bytes(0x1000))
        s.scan_start(ref="0x0", length=0x1000)
        for i in range(moved):
            ses.memory[i] = 1
        out = s.scan_filter(operator=">")
        assert (out["hits_total"], out["truncated"], len(out["hits"])) == (
            moved, not listed, moved if listed else 0), out
        assert out["hits"] == ([{"addr": f"{i:#010x}", "value": "0x01"} for i in range(moved)]
                               if listed else [])
        s.scan_clear()


def test_a_scan_is_bound_to_its_cpu_and_survives_the_machine_until_close(
        board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The cpu the scan opened on is the one every filter reads, whatever is visible later,
    with the thread patch or without it; new bytes at the next filter are compared, not a
    reason to drop the scan; and it dies with the session's fields."""
    for threads in ({1: ":maincpu", 2: ":subcpu"}, {}):
        ses = board("m68k-dual", bytes(0x100))
        ses.threads = threads
        s.scan_start(ref="0x200000", length=0x10)
        ses.replies["cpulist"] = captured("cpulist.sub-visible.txt")
        ses.memory[:] = bytes([7]) * 0x100
        out = s.scan_filter(operator="!")
        assert out["cpu"] == ":maincpu" and out["hits_total"] == 0x10, out
        saves = [c for c in ses.commands if c.startswith("save ")]
        assert len(saves) == 2 and all("::maincpu," in c for c in saves), (threads, saves)
        s.scan_clear()
    assert s.scan_start(ref="0x200000", length=0x10, cpu="maincpu")["cpu"] == ":maincpu"
    ses.memory[:] = bytes([7]) * 0x100
    assert s.scan_filter(operator="=", value=7)["hits_total"] == 0x10
    mstate.STATE._reset()
    assert mstate.STATE.scan is None


def test_scan_clear_answers_whether_one_was_open(board: Any) -> None:
    board("v30", bytes(0x100))
    assert s.scan_clear()["cleared"] is False and "note" in s.scan_clear()
    s.scan_start(ref="0x0", length=0x10)
    assert s.scan_clear()["cleared"] is True and mstate.STATE.scan is None


@pytest.mark.parametrize(("call", "said"), [
    (lambda: s.scan_start(ref="0x0", length=0x10, cell_bytes=3), "cell_bytes"),
    (lambda: s.scan_start(ref="0x0", length=0, cell_bytes=1), "length"),
    (lambda: s.scan_start(ref="0x0", length=1, cell_bytes=2), "length"),
    (lambda: s.scan_start(ref="0x0", length=0x11, cell_bytes=4), "0x10 or 0x14"),
    (lambda: s.scan_start(ref="0x0", length=mscan.SCAN_BYTES_MAX + 1), "length"),
    (lambda: s.scan_filter(operator="~"), "operator"),
    (lambda: s.scan_filter(operator="=", value=-1), "unsigned"),
])
def test_what_needs_no_machine_is_refused_with_none(call: Any, said: str) -> None:
    """Judged before the gate: the same refusal with no session at all."""
    out = call()
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert said in out["message"], out


def test_what_the_open_scan_decides_is_refused_against_it(board: Any) -> None:
    board("v30", bytes(0x100))
    out = s.scan_filter(operator="=")
    assert out["code"] == "needs_call" and "`scan_start`" in out["message"], out
    s.scan_start(ref="0x0", length=0x10)
    again = s.scan_start(ref="0x0", length=0x10)
    assert again["code"] == "needs_call" and "`scan_clear`" in again["message"], again
    assert (again["addr"], again["cpu"], again["hits_total"]) == ("0x00000000", ":maincpu", 0x10)
    wide = s.scan_filter(operator="=", value=0x100)
    assert wide["code"] == "bad_argument" and "byte" in wide["message"], wide
    assert mstate.STATE.scan is not None and mstate.STATE.scan.iterations == 0, \
        "a refused filter leaves the scan as it was"


def test_a_range_past_the_cpus_space_is_refused_before_any_save(board: Any) -> None:
    ses = board("v30", bytes(0x100))
    out = s.scan_start(ref="0xffff8", length=0x10)
    assert out["code"] == "bad_argument" and "mask" in out["message"], out
    assert not [c for c in ses.commands if c.startswith("save ")]


def test_a_copy_path_the_console_would_cut_is_the_hosts_failure(
        board: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ses = board("v30", bytes(0x100))
    split = tmp_path / "a;b"
    split.mkdir()
    monkeypatch.setattr(mstate.STATE, "scratch", split)
    out = s.scan_start(ref="0x0", length=0x10)
    assert out["code"] == "host_failed" and "';'" in out["message"], out
    assert mstate.STATE.scan is None and not [c for c in ses.commands if c.startswith("save ")]
    assert not (split / "scan").exists(), "a refused scratch was touched"


def test_a_word_scan_on_a_cpu_with_no_byte_order_is_no_channel(board: Any) -> None:
    ses = board("v30", bytes(0x100))

    def unknown(thread: int) -> Any:
        raise gs.UnknownByteOrder("no order for this architecture")

    ses.layout = unknown
    assert s.scan_start(ref="0x0", length=0x10, cell_bytes=2)["code"] == "no_channel"
    assert s.scan_start(ref="0x0", length=0x10, cell_bytes=1)["status"] == "ok", \
        "a byte scan needs no byte order"


def test_with_no_session_every_scan_tool_says_so() -> None:
    for out in (s.scan_start(ref="0x0", length=0x10), s.scan_filter(), s.scan_clear()):
        assert out["code"] == "no_session", out


def test_a_filter_with_a_value_rewrites_no_opening(board: Any) -> None:
    """Survivors only shrink, and a valued filter leaves each cell's opening where it was: the
    next `!` still compares with the scan as opened."""
    ses = board("v30", bytes([0, 5, 9, 0]))
    s.scan_start(ref="0x0", length=3)
    ses.memory[1] = 7            # moved before the valued filter: 7 is not its opening
    assert s.scan_filter(operator=">=", value=5)["hits_total"] == 2
    ses.memory[0] = 9            # dropped already: never comes back
    ses.memory[1] = 5            # back to its opening value, so `!` drops it
    out = s.scan_filter(operator="!")
    assert out["closed"] is True and out["hits_total"] == 0, out


def test_word_and_dword_cells_are_unsigned_to_the_top_of_their_width(board: Any) -> None:
    for name, width, top in [("v30", "word", 0xFFFF), ("m68k-dual", "dword", 0xFFFFFFFF)]:
        base, _ = BOARDS[name]
        ses = board(name, bytes(0x10))
        s.scan_start(ref=f"{base:#x}", length=8, cell_bytes=SIZE[width])
        ses.memory[:CELL["uw" if width == "word" else "ud"]] = bytes([0xFF] * 4)[
            :CELL["uw" if width == "word" else "ud"]]
        out = s.scan_filter(operator="=", value=top)
        digits = 2 * SIZE[width]
        assert out["hits"] == [{"addr": f"{base:#010x}", "value": f"0x{top:0{digits}x}"}], (
            name, out)
        s.scan_clear()
        s.scan_start(ref=f"{base:#x}", length=8, cell_bytes=SIZE[width])
        wide = s.scan_filter(operator="=", value=top + 1)
        assert wide["code"] == "bad_argument", wide
        s.scan_clear()
    mscan.check_scan_start(ref="0x0", length=mscan.SCAN_BYTES_MAX)


def test_a_range_copy_that_fails_after_the_save_leaves_the_scan_as_it_was(board: Any) -> None:
    ses = board("v30", bytes(0x100))
    short = ses.replies["save"]
    ses.replies["save"] = lambda c: (Path(c[5:].split(",")[0]).write_bytes(b"x"), "ok")[1]
    out = s.scan_start(ref="0x0", length=0x10)
    assert out["status"] == "INVALID" and mstate.STATE.scan is None, out
    ses.replies["save"] = short
    real = ses.read
    ses.read = lambda addr, n, *, thread: b"\xee" * n       # the control read disagrees
    out = s.scan_start(ref="0x0", length=0x10)
    assert out["code"] == "readback_refused" and mstate.STATE.scan is None, out
    ses.read = real
    s.scan_start(ref="0x0", length=0x10)
    held = copy.deepcopy(mstate.STATE.scan)
    ses.read = lambda addr, n, *, thread: b"\xee" * n       # the control read disagrees
    out = s.scan_filter(operator="!")
    assert out["code"] == "readback_refused", out
    assert mstate.STATE.scan == held, "a refused filter changed the scan"
    assert not list((scratch() / "scan").iterdir())


def test_scan_clear_answers_on_a_running_machine_and_not_on_a_broken_one(board: Any) -> None:
    ses = board("v30", bytes(0x100))
    s.scan_start(ref="0x0", length=0x10)
    ses.running = True
    ses.poll_stop = lambda timeout=0.0: False
    assert s.scan_filter(operator="!")["code"] == "not_stopped"
    assert s.scan_clear()["cleared"] is True and mstate.STATE.scan is None
    ses.broken = "the stub closed the connection"
    assert s.scan_clear()["code"] == "session_broken"


def test_a_scan_on_a_console_that_marks_no_cpu_is_refused(board: Any) -> None:
    """Without the thread patch and with no `cpu` named, the scan's cpu is the visible one: a
    console that names none (one that lacks `cpulist`, captured) leaves a scan bound to nothing,
    which would read whichever cpu is visible at each filter."""
    ses = board("v30", bytes(0x100))
    ses.threads = {}
    ses.replies["cpulist"] = captured("rpset.unknown-command.txt").replace(
        "rpzzzset {1}", "cpulist")
    out = s.scan_start(ref="0x0", length=0x10)
    assert out["code"] == "unexpected_answer" and "`cpu`" in out["message"], out
    assert mstate.STATE.scan is None and not [c for c in ses.commands if c.startswith("save ")]


# ---- the representation, and the read narrowed to the survivors' span -------------------------


@pytest.mark.parametrize(("width", "code", "size"), [
    ("byte", "B", 1), ("word", "H", 2), ("dword", "I", 4)])
def test_an_open_scan_holds_its_values_in_the_cells_width_and_its_offsets_in_four_bytes(
        board: Any, width: str, code: str, size: int) -> None:
    board("v30", bytes(0x100))
    s.scan_start(ref="0x0", length=0x40, cell_bytes=SIZE[width])
    held = mstate.STATE.scan
    assert held is not None
    assert held.offsets.typecode == "I" and held.offsets.itemsize == 4
    for column in (held.opening, held.values):
        assert (column.typecode, column.itemsize) == (code, size), column


@pytest.mark.parametrize("name", list(BOARDS))
@pytest.mark.parametrize("width", ["word", "dword"])
def test_three_filters_read_only_the_survivors_span_and_keep_the_as_opened_answer(
        board: Any, name: str, width: str) -> None:
    """Over four real stops (`!`, then `<`, then `>`, each against the scan as opened), every
    filter saves `[first survivor, last survivor + cell)`, which is narrower than the range
    from the second on, and what survives is what a comparison with the opening dump, written
    here, keeps."""
    base, order = BOARDS[name]
    cell = {"word": 2, "dword": 4}[width]
    stops = [dump(f"{name}-stop{k}") for k in (1, 2, 3, 4)]

    def cells(block: bytes) -> list[int]:
        return [int.from_bytes(block[i:i + cell], order) for i in range(0, len(block), cell)]

    opening = cells(stops[0])
    alive = list(range(len(opening)))
    ses = board(name, stops[0])
    s.scan_start(ref=f"{base:#x}", length=0x10000, cell_bytes=SIZE[width])
    for k, (symbol, test) in enumerate([("!", ne), ("<", lt), (">", gt)], start=1):
        span = (base + alive[0] * cell, (alive[-1] + 1 - alive[0]) * cell)
        if k > 1:
            assert span[1] < 0x10000, "the case narrows nothing, so it could not be red"
        ses.memory[:] = stops[k]
        before = len(ses.saved)
        out = s.scan_filter(operator=symbol)
        assert out["status"] == "ok", out
        assert ses.saved[before:] == [span], (k, ses.saved[before:], span)
        now = cells(stops[k])
        alive = [i for i in alive if test(now[i], opening[i])]
        assert survivors() == {(base + i * cell, now[i]) for i in alive}, k
    assert alive, "the case closed the scan, so its last filter proved nothing"


@pytest.mark.parametrize(("width", "cell"), [("byte", 1), ("word", 2), ("dword", 4)])
def test_the_span_reaches_each_end_of_the_range(board: Any, width: str, cell: int) -> None:
    """Survivors on the first and the last cell read the whole range; once the first is
    written back to its opening value, the last one alone is one cell at the range's end."""
    ses = board("v30", bytes(0x100))
    last = 0x30 - cell
    s.scan_start(ref="0x10", length=0x20, cell_bytes=SIZE[width])
    ses.memory[0x10] = ses.memory[last] = 1
    s.scan_filter(operator="!")
    ses.memory[0x10] = 0
    s.scan_filter(operator="!")
    assert survivors() == {(last, 1)}
    s.scan_filter(operator="!")
    assert ses.saved == [(0x10, 0x20)] * 3 + [(last, cell)], ses.saved


def test_an_odd_word_start_narrows_on_its_own_cells(board: Any) -> None:
    """v30-alt's shape, words from an odd address: the span starts on a cell of the scan,
    never on the even address below it. A refused read of a narrowed scan leaves it whole."""
    ses = board("v30", bytes(0x10000))
    s.scan_start(ref="0x1", length=0xFFFE, cell_bytes=2)
    ses.memory[0x101:0x103] = b"\x34\x12"
    ses.memory[0x201:0x203] = b"\x78\x56"
    s.scan_filter(operator="!")
    out = s.scan_filter(operator="=", value=0x5678)
    assert out["hits"] == [{"addr": "0x00000201", "value": "0x5678"}], out
    assert ses.saved[-1] == (0x101, 0x102), ses.saved
    held = copy.deepcopy(mstate.STATE.scan)
    ses.read = lambda addr, n, *, thread: b"\xee" * n       # the control read disagrees
    assert s.scan_filter(operator="!")["code"] == "readback_refused"
    assert mstate.STATE.scan == held and ses.saved[-1] == (0x201, 2), ses.saved


def test_the_description_counts_length_in_bytes_and_offers_no_space() -> None:
    """`length` is bytes whatever the cell size, and the scan reads the program space only: a
    client that reads `length` as a count of cells halves a word scan, and one never told the
    space is fixed invents a `space` argument for an io search. The schema agrees with the text."""
    text = published("scan_start")
    assert "`length` counts BYTES whatever the cell" in text, text
    assert "no `space` argument" in text and "io ports are never scanned" in text, text
    (tool,) = [t for t in asyncio.run(s.mcp.list_tools()) if t.name == "scan_start"]
    assert "space" not in tool.input_schema["properties"], tool.input_schema
