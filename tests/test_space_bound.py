"""A range past the end of a cpu's program space, judged once (`read.space_bound`) for
`read_memory`, `write`, `find` and `memdump`."""

from pathlib import Path

import pytest
from server_support import _console, _ConsoleSession, _masked  # noqa: E402
from session_doubles import captured, refused  # noqa: E402

from scry_mame import read  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

MASK = 0x3FFF


class _Memory(_ConsoleSession):
    """The console double over an image that also takes writes, counting them."""

    def __init__(self, size: int) -> None:
        super().__init__(replies={
            "cpulist": captured("cpulist-main-visible.txt"),
            "save": self._save, "find": lambda cmd: "Not found\n"})
        self.memory = bytearray(size)

    def _save(self, command: str) -> str:
        path, start, length = command[len("save "):].split(",")
        at = int(start.split(":")[0], 16)
        Path(path).write_bytes(bytes(self.memory[at:at + int(length, 16)]))
        return "Data saved successfully\n"

    def read(self, addr: int, n: int, *, thread: int) -> bytes:
        return bytes(self.memory[addr:addr + n])

    def write(self, addr: int, data: bytes, *, thread: int) -> None:
        self.writes += 1
        self.memory[addr:addr + len(data)] = data


def _masked_memory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _Memory:
    ses = _Memory(2 * (MASK + 1))
    _console(monkeypatch, tmp_path, ses)
    monkeypatch.setattr(mstate.STATE, "machine_map", _masked(MASK))
    return ses


@pytest.mark.parametrize("call", [
    lambda d: s.read_memory("0x4000", length=2),
    lambda d: s.read_memory("0x3ffe", length=4),
    lambda d: s.write(ref="0x4000", data_hex="aa"),
    lambda d: s.write(ref="0x3fff", data_hex="aabb"),
    lambda d: s.find(ref="0x3ff0", length=0x11, data_hex="00"),
    lambda d: s.find(ref="0x4000", length=1, data_hex="00"),
    lambda d: s.memdump("0x3ffc", length=8, dest=str(d / "over.bin")),
    lambda d: s.memdump("0x4000", length=4, dest=str(d / "past.bin")),
], ids=["read past", "read across", "write past", "write across", "find across", "find past",
        "memdump across", "memdump past"])
def test_a_range_past_the_program_space_is_refused_naming_the_space_and_its_mask(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, call: object,
) -> None:
    ses = _masked_memory(monkeypatch, tmp_path)
    out = refused("program space", call(tmp_path))  # type: ignore[operator]
    assert out["code"] == "bad_argument" and f"{MASK:#x}" in out["message"], out
    assert ses.writes == 0 and not any(c.startswith(("save", "find")) for c in ses.commands)
    assert not list(tmp_path.glob("*.bin")), "a refused memdump leaves no file"


def test_a_range_ending_exactly_at_the_mask_is_a_range(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _masked_memory(monkeypatch, tmp_path)
    assert s.read_memory("0x3ffc", length=4)["status"] == "ok"
    written = s.write(ref="0x3fff", data_hex="aa")
    assert written["status"] == "ok" and written["verified"] is True and ses.writes == 1, written
    assert s.find(ref="0x3ff0", length=0x10, data_hex="00")["status"] == "ok"
    assert s.memdump("0x3ffc", length=4, dest=str(tmp_path / "edge.bin"))["status"] == "ok"
    assert s.read_memory("0x0", length=read.READ_MAX)["status"] == "ok", "the space's start"


def test_with_no_mask_known_the_range_is_the_consoles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _masked_memory(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "machine_map", {})
    assert s.read_memory("0x4000", length=2)["status"] == "ok"
    assert s.write(ref="0x4000", data_hex="aa")["status"] == "ok" and ses.writes == 1
    assert s.find(ref="0x3ff0", length=0x11, data_hex="00")["status"] == "ok"
    assert s.memdump("0x4000", length=4, dest=str(tmp_path / "unknown.bin"))["status"] == "ok"


def test_the_one_judge_takes_the_last_byte_and_refuses_the_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`space_bound`, asked of a cpu: a range ending at its mask is a range, one byte further is
    refused naming the last byte and the mask, and a cpu with no mask known refuses nothing."""
    monkeypatch.setattr(mstate.STATE, "machine_map", _masked(MASK))
    read.space_bound(0x3FFC, 4, ":maincpu")
    read.space_bound(MASK, 1, ":maincpu")
    for addr, length, last in ((0x3FFD, 4, "0x4000"), (0x4000, 1, "0x4000")):
        with pytest.raises(mstate.Invalid, match=f"end at {last}.*mask is 0x3fff"):
            read.space_bound(addr, length, ":maincpu")
    read.space_bound(0x4000, 1, ":subcpu")
