"""Every tool's reply is judged against its declared model."""

from __future__ import annotations

import asyncio

import pytest
from scry_core import reply_schema  # noqa: E402

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


