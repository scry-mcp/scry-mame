"""Every tool's reply is judged against its declared model."""

from __future__ import annotations

import asyncio
from typing import get_type_hints

import pytest
from scry_core import reply_schema, roster  # noqa: E402

from scry_mame import replies  # noqa: E402
from scry_mame import server as s  # noqa: E402


def test_every_tool_publishes_each_field_as_its_value_or_unavailable() -> None:
    tools = asyncio.run(s.mcp.list_tools())
    assert tools and set(reply_schema._JUDGES) >= {t.name for t in tools}
    for t in tools:
        schema = t.output_schema
        assert schema is not None and schema["required"] == ["status"], t.name
        assert "summary" in schema["properties"], t.name
        for field in reply_schema.own_fields(replies.MODELS[t.name]):
            assert "anyOf" in schema["properties"][field], (t.name, field)


def test_a_real_tools_reply_with_a_field_its_model_does_not_name_fails() -> None:
    reply_schema.check("status", {"status": "ok", "pid": 1})
    with pytest.raises(ValueError):
        reply_schema.check("status", {"status": "ok", "pid": 1, "stray": 1})


def test_a_reply_that_carries_the_stop_the_console_left_takes_its_watches() -> None:
    """A read the console evaluates steps the machine, and the stop it leaves carries the
    readings of every watch declared: a model that does not name them refuses that reply."""
    stop = {"stop_seq", "regs", "instruction"}
    lacking = sorted(name for name, model in replies.MODELS.items()
                     if stop <= set(get_type_hints(model))
                     and "watches" not in get_type_hints(model))
    assert lacking == [], lacking


#: Words a tool's `Reply` text quotes that are no field of its reply, kept per tool so one
#: tool's allowance never hides another's missing field.
REPLY_WORDS: dict[str, tuple[str, ...]] = {
    "close": ("quit",),
    "step": ("over",),
    "snapshot": ("INVALID",),
    "screen_view": ("isolate", "pixel"),
    "audio_compare": ("peak_dbfs", "rms_dbfs", "silent", "silence_spans", "onset_s",
                      "clipping_run", "clipped"),
}


def test_every_field_a_reply_sentence_names_is_in_its_model() -> None:
    tools = asyncio.run(s.mcp.list_tools())
    wrong = reply_schema.sentence_faults(tools, replies.MODELS, REPLY_WORDS)
    assert not wrong, wrong


def test_record_answers_the_family_both_servers_declare() -> None:
    declared = set(roster.RECORD_REPLY_FIELDS)
    assert declared <= set(replies.MODELS["record"].__annotations__), declared


def test_record_speaks_the_words_scry_core_declares() -> None:
    tools = asyncio.run(s.mcp.list_tools())
    doc = next(t for t in tools if t.name == "record").description or ""
    for words in (roster.RECORD_ARGS, roster.RECORD_CUT, roster.RECORD_REPLY):
        assert words in doc, words


def test_close_always_answers_the_exit_code_as_both_servers_do() -> None:
    """An integer, or unavailable with its `why` (no session, a process not reaped)."""
    assert "exit_code" in reply_schema.own_required(replies.MODELS["close"])
    doc = next(t for t in asyncio.run(s.mcp.list_tools()) if t.name == "close").description
    assert "`exit_code`" in (doc or "")


@pytest.mark.parametrize("tool", ["disassemble", "find", "memdump", "read_memory", "scan",
                                  "write"])
def test_a_tool_that_reads_or_writes_at_a_ref_echoes_it_beside_addr(tool: str) -> None:
    """As on scry-dosbox-x: the reply says which `ref` its `addr` answers."""
    assert "ref" in reply_schema.own_fields(replies.MODELS[tool])
    doc = next(t for t in asyncio.run(s.mcp.list_tools()) if t.name == tool).description
    assert "ref" in reply_schema.reply_sentence_names(doc or ""), doc


@pytest.mark.parametrize("tool", ["run_to", "run_for", "screen_wait"])
def test_only_a_tool_that_takes_disarm_watches_lists_what_it_adds(tool: str) -> None:
    """`disarmed_watches` and `not_rearmed` are the pass's account: a reply never sends them where
    no pass was disarmed."""
    takes = "disarm_watches" in getattr(s, tool).__wrapped__.__code__.co_varnames
    fields = reply_schema.own_fields(replies.MODELS[tool])
    assert ("disarmed_watches" in fields) is takes and ("not_rearmed" in fields) is takes, tool
