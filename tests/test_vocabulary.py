"""The reply vocabulary of a reason: `note` is a reply's (or a sub-object's) note, one string built
by one helper; `why` is a row's or a field's reason; a datum that could not be read is
`{"available": false, "why": ...}`. Pinned here on the helpers every site goes through."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from scry_core.reply_contract import unavailable  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mame_mcp  # noqa: E402
import mame_state as mstate  # noqa: E402
import server  # noqa: E402,F401 -- registers the tools whose summaries are read here


def test_notes_join_the_parts_said_in_order_and_once() -> None:
    assert mstate.join_notes("a", None, "", "b", "a") == "a; b"
    assert mstate.join_notes(None, "") is None


def test_a_note_is_added_after_the_one_the_reply_already_carries() -> None:
    reply: dict[str, object] = {"x": 1}
    assert mstate.add_note(reply, None) is reply and reply == {"x": 1}, "nothing said, no key"
    mstate.add_note(reply, "first")
    mstate.add_note(reply, "second", "first")
    assert reply == {"x": 1, "note": "first; second"}


def test_an_unread_datum_is_unavailable_with_its_reason() -> None:
    assert unavailable("the stub refused") == {"available": False,
                                                      "why": "the stub refused"}
    with pytest.raises(TypeError, match="says why"):
        unavailable(" ")


def test_merged_fields_join_their_notes_and_keep_their_order() -> None:
    out = mstate.merged({"a": 1, "note": "tool"}, {"b": 2}, {"c": 3, "note": "console"})
    assert out == {"a": 1, "note": "tool; console", "b": 2, "c": 3}
    assert list(out) == ["a", "note", "b", "c"]
    assert mstate.merged({"b": 2}, {"note": "only"}) == {"b": 2, "note": "only"}


def test_merged_fields_refuse_any_other_key_said_twice() -> None:
    """Only a note has a reason to be said by two sources: any other key twice is two answers to
    one question, a programmer's error raised where it is written, as a repeated keyword was."""
    with pytest.raises(TypeError, match="'call'"):
        mstate.merged({"call": "a"}, {"call": "b"})


def test_a_refusal_read_off_an_answer_keeps_its_own_note_beside_the_consoles() -> None:
    """`console_said` adds the console's account to a refusal raised inside it: its `note`
    joins the refusal's own, and the refusal's other fields win."""
    import mame_lua as mlua
    import mame_transport as transport

    answer = transport.Answer("", True, "nil", thread_errors=1)
    with pytest.raises(mstate.Invalid) as e, mlua.console_said(answer, 0):
        raise mstate.Invalid("bad_argument", "x", note="the tool's", thread_errors=7)
    assert e.value.fields["thread_errors"] == 7, "the refusal's own field wins"
    note = e.value.fields["note"]
    assert note.startswith(transport.console_did(answer, 0)["note"]), note
    assert note.endswith("; the tool's"), note


def test_a_captured_block_its_format_cannot_decode_is_unavailable_with_why() -> None:
    """The row keeps its bytes and its writer; the decoded `block` says why it is not there."""
    import mame_capture as capture

    row = capture.row_fields(capture.Row(1, 7, 0, 0, 0x400, 0x12, 0xFF, b"\x01"), "u32", 4, 16,
                             "big", None)
    assert row["raw_hex"] == "01" and row["block"]["available"] is False, row
    assert (row["data"], row["mask"]) == ("0x0012", "0x00ff"), "at the bus's width, `0x` text"
    assert row["block"]["why"], row


def test_a_span_is_spelled_to_the_tenth_and_a_measured_time_to_the_microsecond() -> None:
    assert mstate.spent_s(2.46) == 2.5 and mstate.spent_s(0.04) == 0.0
    assert mstate.measured_s(1.23456789) == 1.234568 and mstate.measured_s(None) is None


@pytest.mark.parametrize(("claims", "said"), [(1, "1 raw `lua` call was declared"),
                                              (2, "2 raw `lua` calls were declared")])
def test_the_sessions_note_counts_its_read_only_claims_in_their_number(
        monkeypatch: pytest.MonkeyPatch, claims: int, said: str) -> None:
    """The verb agrees with the count as the noun does (`prose.agrees`), at one and at more."""
    import mame_envelope as menvelope

    monkeypatch.setattr(mstate.STATE, "ses", None)
    monkeypatch.setattr(mstate.STATE, "lua_read_only_claims", claims)
    assert said in menvelope.session_block()["note"]


@pytest.mark.parametrize(("frames", "t", "said"), [
    (1, {"cpu": ":maincpu", "addresses": 1, "symbols_total": 1, "bytes": 1},
     "trace :maincpu 1 frame: 1 address in 1 symbol, 1 byte"),
    (2, {"cpu": ":maincpu", "addresses": 3, "symbols_total": 2, "bytes": 40},
     "trace :maincpu 2 frames: 3 addresses in 2 symbols, 40 bytes"),
])
def test_a_trace_summary_says_each_count_in_its_number(
        frames: int, t: dict[str, object], said: str) -> None:
    assert mame_mcp.BOUNDARY.line("trace", {"frames": frames}, {"status": "ok", "trace": t}) == said
