"""The console plumbing written once: the session's latch and drain, the wait for rest, the wait for
a file, the scratch numberers, and where a lane sits in a bus word. Each is the one copy every
caller now goes through, so each is pinned here directly rather than only through its callers.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gdb_session as g  # noqa: E402
import mame_advance as advance  # noqa: E402
import mame_files as files  # noqa: E402
import mame_space as mspace  # noqa: E402
import mame_state as mstate  # noqa: E402


def test_a_latch_keeps_the_first_reason() -> None:
    """What fails after a session broke is its consequence: the first reason stands."""
    ses = g.Session()
    ses.latch("the stub answered nonsense")
    ses.latch("a later read failed")
    assert ses.broken == "the stub answered nonsense"


class _Receiving(g.Session):
    def __init__(self, raises: BaseException) -> None:
        super().__init__()
        self.raises = raises
        self.received: list[float | None] = []

    def _receive(self, timeout: float | None = None) -> str:
        self.received.append(timeout)
        raise self.raises


def test_the_drain_listens_for_its_bound_and_swallows_only_a_session_error() -> None:
    quiet = _Receiving(g.SessionError("nothing came"))
    quiet.drain_stop_reply()
    assert quiet.received == [g.STOP_REPLY_DRAIN_S]
    with pytest.raises(ValueError):
        _Receiving(ValueError("not the channel's")).drain_stop_reply()


def _answers(*results: Any) -> tuple[list[int], Any]:
    calls: list[int] = []

    def check() -> Any:
        calls.append(1)
        return results[min(len(calls), len(results)) - 1]
    return calls, check


def test_a_count_of_zero_is_an_answer_and_returns_at_once() -> None:
    calls, check = _answers(0)
    assert files.wait_for(check, 5.0, 0.0) == 0 and len(calls) == 1


def test_a_late_answer_is_waited_for_and_none_or_false_is_not_one() -> None:
    calls, check = _answers(None, False, "here")
    assert files.wait_for(check, 5.0, 0.0) == "here" and len(calls) == 3


def test_at_the_bound_the_last_answer_comes_back() -> None:
    calls, check = _answers(False)
    assert files.wait_for(check, 0.0, 0.0) is False and len(calls) == 1


@pytest.mark.parametrize("sleep_first", [False, True])
def test_the_wait_for_rest_sleeps_on_the_side_it_is_told(
        monkeypatch: pytest.MonkeyPatch, sleep_first: bool) -> None:
    """After an interrupt the gap comes BEFORE each read; otherwise after it. Three equal reads
    end the wait, and every read stays in `readings`."""
    events: list[str] = []
    monkeypatch.setattr("mame_advance.time.sleep", lambda s: events.append("sleep"))
    values = iter([1, 2, 2, 2])

    def read() -> int:
        events.append("read")
        return next(values)
    readings: list[int] = []
    assert advance.wait_for_rest(readings, read, 5.0, sleep_first=sleep_first)
    assert readings == [1, 2, 2, 2]
    assert events == (["sleep", "read"] * 4 if sleep_first
                      else ["read", "sleep"] * 3 + ["read"])


def test_the_wait_for_rest_answers_false_at_its_bound_with_what_it_read() -> None:
    values = iter(range(100))
    readings: list[int] = []
    assert not advance.wait_for_rest(readings, lambda: next(values), 0.0)
    assert readings == [0]


def test_each_kind_of_scratch_file_counts_on_its_own() -> None:
    state = mstate.STATE
    assert [state.next_number("snapshots"), state.next_number("snapshots"),
            state.next_number("recordings")] == [1, 2, 1]


def test_the_first_free_name_skips_the_ones_taken(tmp_path: Path) -> None:
    for n in (1, 2):
        (tmp_path / f"shot-{n}.png").write_bytes(b"")
    assert files.first_free(tmp_path, lambda n: f"shot-{n}.png") == tmp_path / "shot-3.png"


@pytest.mark.parametrize("data_width", [16, 32, 64])
@pytest.mark.parametrize("endianness", ["big", "little"])
def test_every_lane_of_a_bus_word_is_found_where_its_bytes_are(
        data_width: int, endianness: str) -> None:
    """Against the bytes themselves: a word whose byte at each ADDRESS is distinct, packed in the
    bus's order, must give back `word[at:at+width]` for every lane and width."""
    nb = data_width // 8
    word = bytes(range(0x11, 0x11 + nb))
    data = int.from_bytes(word, "big" if endianness == "big" else "little")
    for width in range(1, nb + 1):
        for at in range(nb - width + 1):
            shift = mspace.lane_shift(at, width, data_width, endianness)
            want = int.from_bytes(word[at:at + width], "big" if endianness == "big" else "little")
            assert (data >> shift) & ((1 << 8 * width) - 1) == want, (width, at)
