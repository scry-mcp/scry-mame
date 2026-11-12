"""`write(region=True)`: bytes into the memory region behind a ROM address, read back through
the cpu.

The double keeps each region the way MAME does, in the HOST's byte order per region word, and
answers `saver` and `loadr` with the console's own sentences (`fixtures/console/saver.*`,
`loadr.*`, captured on m68k-dual, whose provenance also records the known answer: with the cpu
reading `80a0` at 0x7b8, `saver` wrote `a080`, and a `loadr` of `2080` made the cpu read
`8020`). What it stores is authored from `debugcmd.cpp`'s region branches (a span clamped at
the region's end, a load no longer than its file).
"""

import re
import sys
from pathlib import Path

import pytest
from scry_core.host_program import POSIX_NAMES  # noqa: E402
from session_doubles import MAP_LATCH, MAP_ROM, captured  # noqa: E402
from test_machine import M68K_DUAL, _cached  # noqa: E402
from test_watches import _rom_under_write, _WatchSession  # noqa: E402

from scry_mame import capture  # noqa: E402
from scry_mame import gdb_session as gs  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

_REGION_CMD = re.compile(r"^(saver|loadr) ([^,]+),0x([0-9a-f]+),0x([0-9a-f]+),(\S+)$")
_SIZE = 0x100000


class _Regions:
    """m68k-dual's two program ROM regions as MAME holds them, and the console's two region
    commands over them. `order` and `width` are the regions' declared layout; `answer` stands in
    for the console's sentence when a case needs it to answer something else, `maps` for its
    `map`, and `drop` makes the stub's answer to a `loadr` that landed never arrive."""

    def __init__(self, ses: _WatchSession, order: str = "big", width: int = 2) -> None:
        self.ses, self.order, self.width = ses, order, width
        self.store = {":maincpu": bytearray(_SIZE), ":subcpu": bytearray(_SIZE)}
        self.answer: dict[str, str] = {}
        self.maps: dict[int, str] = {}
        self.drop = False
        self.refuse_reads = False
        self.cpu_write(":maincpu", 0x7B8, bytes.fromhex("80a033fc"))
        self.cpu_write(":subcpu", 0x544, bytes.fromhex("2f3c0000"))
        self.plain_read, self.plain_monitor = ses.read, ses.monitor

    def _at(self, addr: int) -> int:
        """The storage byte a cpu byte lives in: a big-endian region wider than a byte, on a
        little-endian host, keeps each word reversed."""
        reversed_ = self.order == "big" and sys.byteorder == "little"
        return addr ^ (self.width - 1) if reversed_ else addr

    def cpu_write(self, tag: str, addr: int, data: bytes) -> None:
        for k, b in enumerate(data):
            self.store[tag][self._at(addr + k)] = b

    def cpu_read(self, tag: str, addr: int, n: int) -> bytes:
        return bytes(self.store[tag][self._at(addr + k)] for k in range(n))

    def read(self, addr: int, n: int, *, thread: int) -> bytes:
        if self.refuse_reads:
            raise gs.Refused("the stub answered E01")
        if addr + n > _SIZE:
            return self.plain_read(addr, n, thread=thread)
        tag = (self.ses.threads or {}).get(thread, ":maincpu")
        return self.cpu_read(tag, addr, n)

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        if command.startswith("map ") and int(command[4:].split(":")[0], 16) in self.maps:
            self.ses.commands.append(command)
            return self.maps[int(command[4:].split(":")[0], 16)]
        m = _REGION_CMD.match(command)
        if m is None:
            return str(self.plain_monitor(command, timeout))
        self.ses.commands.append(command)
        verb, path, offset, length, tag = m.group(1), Path(m.group(2)), *(
            int(x, 16) for x in m.group(3, 4)), m.group(5)
        if verb in self.answer:
            return self.answer[verb]
        if tag not in self.store:
            return captured(f"{verb}.unknown-region.txt")
        if offset >= _SIZE:
            return captured(f"{verb}.invalid-offset.txt")
        if length <= 0 or length + offset >= _SIZE:
            length = _SIZE - offset
        if verb == "saver":
            path.write_bytes(bytes(self.store[tag][offset:offset + length]))
            return captured("saver-saved.txt")
        data = path.read_bytes()[:length]
        self.store[tag][offset:offset + len(data)] = data
        if self.drop:
            self.ses.broken = "the request ran out"
            raise gs.SessionError("no answer to the console request")
        return captured("loadr-loaded.txt").replace(
            "0x7B8 to 0x7B9", f"0x{offset:X} to 0x{offset + len(data) - 1:X}")


def _regions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, order: str = "big",
             dump: str = "", width: int = 2) -> tuple[_WatchSession, _Regions]:
    ses = _rom_under_write(monkeypatch, tmp_path)
    if dump:
        _cached(monkeypatch, tmp_path, dump=dump)
    ses.rom_write_unmapped |= {0x7B8, 0x7B9, 0x544, 0xFFFFE, 0xFFFFF}
    regions = _Regions(ses, order, width)
    monkeypatch.setattr(ses, "read", regions.read)
    monkeypatch.setattr(ses, "monitor", regions.monitor)
    for row in mstate.STATE.machine_map["regions"]:
        monkeypatch.setitem(row, "endianness", order)
        if row["bytewidth"] > 1:
            monkeypatch.setitem(row, "bytewidth", width)
    return ses, regions


def _sent(ses: _WatchSession, verb: str) -> list[str]:
    return [c for c in ses.commands if c.startswith(verb + " ")]


def test_a_region_write_on_m68k_dual_lands_as_the_measured_bytes_and_reads_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """KNOWN ANSWER (the provenance's): the cpu reads 8020 once the region holds 20 80."""
    ses, regions = _regions(monkeypatch, tmp_path)
    out = s.write(ref="0x7b8", data_hex="8020", region=True)
    assert out["status"] == "ok" and out["verified"] is True and out["readback"] == "8020", out
    assert (out["region"], out["region_offset"], out["cpu"]) == (
        ":maincpu", "0x000007b8", ":maincpu")
    assert bytes(regions.store[":maincpu"][0x7B8:0x7BA]) == bytes.fromhex("2080")
    assert [c.split(",", 1)[1] for c in _sent(ses, "saver") + _sent(ses, "loadr")] == [
        "0x7b8,0x2,:maincpu", "0x7b8,0x2,:maincpu"], ses.commands
    assert out["session"]["altered"] is True, out
    assert "into :maincpu at 0x000007b8" in out["summary"], out


# A BOARD WHOSE DRIVER NAMES ITS REGION RELATIVELY: the gather then writes the entry's region
# bare (`maincpu`), while the inventory's `regions` table names it in full.
_BARE_REGION = M68K_DUAL.replace("share=- region=:maincpu", "share=- region=maincpu")


def test_a_region_the_map_entry_names_bare_is_the_inventorys_region_and_is_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    assert _BARE_REGION != M68K_DUAL, "the substitution matched nothing"
    _ses, regions = _regions(monkeypatch, tmp_path, dump=_BARE_REGION)
    out = s.write(ref="0x7b8", data_hex="8020", region=True)
    assert out["status"] == "ok" and out["verified"] is True, out
    assert out["region"] == ":maincpu", "the region under the inventory's one spelling"
    assert bytes(regions.store[":maincpu"][0x7B8:0x7BA]) == bytes.fromhex("2080")


def test_a_region_kept_in_the_hosts_own_order_is_loaded_as_it_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A region whose endianness is the host's is stored as the cpu reads it: no swap."""
    _, regions = _regions(monkeypatch, tmp_path, order=sys.byteorder)
    out = s.write(ref="0x7b8", data_hex="8020", region=True)
    assert out["verified"] is True and out["readback"] == "8020", out
    assert bytes(regions.store[":maincpu"][0x7B8:0x7BA]) == bytes.fromhex("8020")


@pytest.mark.parametrize(("ref", "data", "span", "word"), [
    ("0x7b9", "20", "0x7b8,0x2", "8020"),
    ("0x7b9", "2033fd", "0x7b8,0x4", "802033fd"),
], ids=["one-odd-byte", "straddling"])
def test_an_unaligned_region_write_is_widened_to_whole_words_and_keeps_its_neighbours(
    ref: str, data: str, span: str, word: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Widened to the words it touches (`region.write`), each neighbour put back."""
    ses, regions = _regions(monkeypatch, tmp_path)
    out = s.write(ref=ref, data_hex=data, region=True)
    assert out["verified"] is True and out["region_offset"] == "0x000007b9", out
    assert regions.cpu_read(":maincpu", 0x7B8, len(word) // 2).hex() == word
    assert _sent(ses, "loadr")[0].endswith(f",{span},:maincpu"), ses.commands


def test_a_region_write_on_the_sub_cpu_goes_into_the_sub_cpus_region(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses, regions = _regions(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    out = s.write(ref="0x544", data_hex="4e71", cpu="subcpu", region=True)
    assert (out["region"], out["region_offset"], out["cpu"]) == (
        ":subcpu", "0x00000544", ":subcpu")
    assert out["verified"] is True and regions.cpu_read(":subcpu", 0x544, 2).hex() == "4e71"
    assert regions.cpu_read(":maincpu", 0x544, 2) == bytes(2), "the main cpu's region moved"


_NO_REGION_LINE = M68K_DUAL.replace(
    "REGION :maincpu size=1048576 bytewidth=2 endianness=big\n", "")
_SMALL_REGION = M68K_DUAL.replace("REGION :maincpu size=1048576 ", "REGION :maincpu size=1024 ")
_MASKED = M68K_DUAL.replace("start=0 end=fffff mirror=0 mask=0 share=- region=:maincpu",
                           "start=0 end=fffff mirror=0 mask=fffff share=- region=:maincpu")


@pytest.mark.parametrize(("ref", "data", "dump", "said"), [
    ("0x200000", "1234", "", "answers ram at 0x200000, and no region in the cached address map "
     "backs it, so there is no region offset to write at; a write without `region` reaches it"),
    ("0x300000", "1234", "", "answers rom at 0x300000, and no region in the cached address map"),
    ("0xfffff", "1234", "", "run past the map entry's end at 0xfffff"),
    ("0x7b8", "8020", _NO_REGION_LINE, "is not in the inventory `start` gathered"),
    ("0x7b8", "8020", _SMALL_REGION, "run past the end of :maincpu (0x400 bytes)"),
    ("0x7b8", "8020", _MASKED, "masks its addresses, so the offset is not computed here, so there "
     "is no region offset"),
], ids=["ram", "unbacked-rom", "past-entry", "no-layout", "past-region", "masked"])
def test_a_region_write_that_cannot_be_placed_is_refused_before_anything_is_sent(
    ref: str, data: str, dump: str, said: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    assert dump != M68K_DUAL, "the anchor matched nothing"
    ses, _ = _regions(monkeypatch, tmp_path, dump=dump)
    ses.rom_write_unmapped.add(0x300000)
    out = s.write(ref=ref, data_hex=data, region=True)
    assert out["code"] == "bad_argument" and said in out["message"], out
    assert not _sent(ses, "saver") and not _sent(ses, "loadr"), ses.commands
    assert out["session"]["altered"] is False, out


@POSIX_NAMES
def test_a_scratch_path_the_console_would_split_is_refused_before_saver(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses, _ = _regions(monkeypatch, tmp_path)
    for name in ("a,b", 'a"b', "a b", "a;b", "a(b"):
        split = tmp_path / name
        split.mkdir()
        monkeypatch.setattr(mstate.STATE, "scratch", split)
        out = s.write(ref="0x7b8", data_hex="8020", region=True)
        assert out["code"] == "host_failed" and f"holds {name[1]!r}" in out["message"], (name, out)
    assert not _sent(ses, "saver") and out["session"]["altered"] is False, ses.commands


@pytest.mark.parametrize(("verb", "answer", "altered"), [
    ("saver", captured("saver-invalid-offset.txt"), False),
    ("saver", captured("saver-unknown-region.txt"), False),
    ("saver", captured("saver-unwritable.txt"), False),
    ("loadr", captured("loadr-short-file.txt"), True),
    ("loadr", captured("loadr-invalid-offset.txt"), True),
    ("loadr", captured("loadr-unknown-region.txt"), True),
], ids=["saver-offset", "saver-region", "saver-unwritable", "loadr-short", "loadr-offset",
        "loadr-region"])
def test_a_region_command_that_does_not_answer_its_success_is_unexpected(
    verb: str, answer: str, altered: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Only the success sentence with the whole span says the span moved, even beside the file
    an earlier region write left in the scratch; a `loadr` that was sent counts as a write
    whatever it answered."""
    ses, regions = _regions(monkeypatch, tmp_path)
    (tmp_path / "region.bin").write_bytes(bytes.fromhex("a080"))
    regions.answer[verb] = answer
    out = s.write(ref="0x7b8", data_hex="8020", region=True)
    assert out["code"] == "unexpected_answer" and answer.strip() in out["message"], out
    assert bool(_sent(ses, "loadr")) is (verb == "loadr"), ses.commands
    assert out["session"]["altered"] is altered, out


def test_a_saver_clamped_at_the_regions_end_loads_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A clamped `saver` still says `Data saved successfully` (captured): the file's size is
    what tells the span short."""
    ses, regions = _regions(monkeypatch, tmp_path)
    real = regions.monitor

    def short(command: str, timeout: float = 10.0) -> str:
        said = real(command, timeout)
        if command.startswith("saver "):
            path = Path(command.split(" ", 1)[1].split(",", 1)[0])
            path.write_bytes(path.read_bytes()[:1])
        return said

    monkeypatch.setattr(ses, "monitor", short)
    out = s.write(ref="0x7b8", data_hex="8020", region=True)
    assert out["code"] == "readback_refused" and "1 byte came out of `saver` where 2" in out[
        "message"], out
    assert not _sent(ses, "loadr") and out["session"]["altered"] is False, ses.commands


def test_a_plain_rom_write_never_goes_to_the_region_on_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses, regions = _regions(monkeypatch, tmp_path)
    out = s.write(ref="0x7b8", data_hex="8020")
    assert out["verified"] is False and out["target"] == "rom", out
    assert "`region=True` writes them there" in out["note"], out
    assert not _sent(ses, "saver") and not _sent(ses, "loadr"), ses.commands
    assert regions.cpu_read(":maincpu", 0x7B8, 2).hex() == "80a0"


def test_a_perform_step_carries_region_and_refuses_it_untyped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A `perform` step carries raw JSON, where a string would be truthy: the list's own check
    types it against the tool's signature, with nothing run; typed, the step writes."""
    ses, regions = _regions(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "write", "ref": "0x7b8", "data_hex": "8020", "region": "yes"}])
    assert out["status"] == "INVALID" and "region is true or false" in str(out["errors"]), out
    assert not _sent(ses, "saver"), ses.commands
    out = s.perform(steps=[{"op": "write", "ref": "0x7b8", "data_hex": "8020", "region": True}])
    assert out["steps_completed"] == 1 and out["ran"][0]["reply"]["region"] == ":maincpu", out
    assert regions.cpu_read(":maincpu", 0x7B8, 2).hex() == "8020"


# A region entry whose write side is a HANDLER, derived from the captured ROM answer by putting
# the captured latch's handler on its write line: MAME refuses a region entry that writes to
# memory, so what backs the address decides, whatever its write side does.
_MAP_ROM_WITH_HANDLER = MAP_ROM.replace(
    "  Write: 000400 logical program == 000400 physical program -> unmapped",
    "  Write: 000400 logical program == 000400 physical program -> "
    + MAP_LATCH.split("Write: ", 1)[1].split("-> ", 1)[1].rstrip("\n"))


def test_a_region_entry_with_a_write_handler_is_written_in_its_region(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    assert _MAP_ROM_WITH_HANDLER != MAP_ROM and "latch_w" in _MAP_ROM_WITH_HANDLER
    ses, regions = _regions(monkeypatch, tmp_path)
    regions.maps[0x7B8] = _MAP_ROM_WITH_HANDLER
    out = s.write(ref="0x7b8", data_hex="8020", region=True)
    assert out["status"] == "ok" and out["verified"] is True and out["region"] == ":maincpu", out
    assert regions.cpu_read(":maincpu", 0x7B8, 2).hex() == "8020"


def test_a_region_kept_in_32_bit_words_is_swapped_and_widened_by_four(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The word is the region's own width: a 32-bit big-endian region on a little-endian host
    keeps each four bytes reversed, and two bytes are widened to the four around them."""
    ses, regions = _regions(monkeypatch, tmp_path, width=4)
    out = s.write(ref="0x7b8", data_hex="8020", region=True)
    assert out["verified"] is True and out["readback"] == "8020", out
    assert bytes(regions.store[":maincpu"][0x7B8:0x7BC]) == bytes.fromhex("fc332080")
    assert _sent(ses, "loadr")[0].endswith(",0x7b8,0x4,:maincpu"), ses.commands


def test_a_region_write_that_does_not_read_back_says_so_and_explains_nothing_more(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`verified: false` after a load names where the bytes went and adds no ROM explanation:
    the region WAS the explanation's own advice."""
    _, regions = _regions(monkeypatch, tmp_path)
    monkeypatch.setattr(regions, "cpu_read", lambda tag, addr, n: bytes.fromhex("80a0"))
    out = s.write(ref="0x7b8", data_hex="8020", region=True)
    assert out["status"] == "ok" and out["verified"] is False and out["region"] == ":maincpu"
    assert "target" not in out and "note" not in out, out


def test_a_plain_rom_write_the_region_could_not_take_does_not_point_at_region(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Two bytes from the region's last byte are refused with `region=True`, so the plain
    write's note does not offer it."""
    _regions(monkeypatch, tmp_path)
    out = s.write(ref="0xfffff", data_hex="a55a")
    assert out["target"] == "rom" and out["region_offset"] == "0x000fffff", out
    assert "`region=True`" not in out["note"], out
    out = s.write(ref="0xffffe", data_hex="a55a")
    assert "`region=True` writes them there" in out["note"], out


def test_a_loadr_whose_answer_never_arrives_still_marks_the_session_altered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The request ran out after the file reached the region: the latched reply must not
    say the machine is untouched."""
    ses, regions = _regions(monkeypatch, tmp_path)
    regions.drop = True
    out = s.write(ref="0x7b8", data_hex="8020", region=True)
    assert out["code"] == "session_broken" and out["session"]["altered"] is True, out
    assert _sent(ses, "loadr"), ses.commands


def test_a_region_write_whose_read_back_is_refused_still_names_where_it_landed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _, regions = _regions(monkeypatch, tmp_path)
    regions.refuse_reads = True
    out = s.write(ref="0x7b8", data_hex="8020", region=True)
    assert out["code"] == "readback_refused" and out["session"]["altered"] is True, out
    assert (out["region"], out["region_offset"], out["bytes_written"]) == (":maincpu", "0x000007b8",
                                                                           2), out


def test_a_region_write_names_the_captures_whose_block_it_patched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A capture whose block a region backs reads it inside its tap, off the bus, and a region
    write lands there off the bus too: nothing in the capture's rows says the table changed
    between two of them. The write says it, naming each capture whose block it overlaps, and
    no capture whose block lies elsewhere or in another region."""
    _regions(monkeypatch, tmp_path)
    monkeypatch.setitem(mstate.STATE.tallies, ("lut", ":maincpu"),
                        {"source": capture.TapSource("region", ":maincpu", 0x7B0), "width": 16,
                         "trigger": 0x7FE})
    monkeypatch.setitem(mstate.STATE.tallies, ("far", ":maincpu"),
                        {"source": capture.TapSource("region", ":maincpu", 0x900), "width": 16,
                         "trigger": 0x7FE})
    monkeypatch.setitem(mstate.STATE.tallies, ("other", ":subcpu"),
                        {"source": capture.TapSource("region", ":subcpu", 0x7B0), "width": 16,
                         "trigger": 0x7FE})
    monkeypatch.setitem(mstate.STATE.tallies, ("count", ":maincpu"), {"width": 4})
    out = s.write(ref="0x7b8", data_hex="8020", region=True)
    assert out["status"] == "ok", out
    assert out["captures_reading_it"] == [{"ref": "lut", "cpu": ":maincpu"}], out
    out = s.write(ref="0x7a0", data_hex="8020", region=True)
    assert "captures_reading_it" not in out, "a block the write does not reach is not named"
