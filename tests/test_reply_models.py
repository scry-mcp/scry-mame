"""Every tool's reply is judged against its declared model (`scry_core.reply_schema`): each tool
has one, the published schema names its fields and constrains none, and a reply with a field its
model does not name fails the battery."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scry_core import reply_schema  # noqa: E402

import mame_docs as docs  # noqa: E402
import mame_replies as replies  # noqa: E402
import server as s  # noqa: E402


def test_every_tool_publishes_its_models_field_names_and_no_constraint() -> None:
    tools = asyncio.run(s.mcp.list_tools())
    assert tools and set(reply_schema._JUDGES) >= {t.name for t in tools}
    for t in tools:
        schema = t.output_schema
        assert schema is not None and schema["required"] == ["status"], t.name
        assert "summary" in schema["properties"] and all(
            spec == {} for spec in schema["properties"].values()), t.name


def test_a_real_tools_reply_with_a_field_its_model_does_not_name_fails() -> None:
    reply_schema.check("status", {"status": "ok", "pid": 1})
    with pytest.raises(ValueError):
        reply_schema.check("status", {"status": "ok", "pid": 1, "stray": 1})


ROWS = ("ref", "by", "created_at", "origin", "inherited", "age_s", "addr", "state")

#: What each tool's `Reply` paragraphs quote that is no field of its reply: a row's own field,
#: a value it holds, a console command or a register, BY TOOL, so a word allowed for one tool
#: never hides a field another tool's model lacks. A name in neither its model nor its row here
#: fails; a word kept here that its tool no longer quotes fails too.
REPLY_WORDS: dict[str, tuple[str, ...]] = {
    "close": ("quit",),
    "cpu_info": ("cpulist", "visible", "ignored", "suspended", "declarations"),
    "run_to": ("ok",),
    "breakpoint_at": ("bplist",),
    "breakpoint_list": (*ROWS, "role", "condition", "condition_typed", "hits_since_armed"),
    "breakpoint_clear": ("bpclear", "ok"),
    "regpoint_add": ("rplist", "rpset"),
    "regpoint_list": (*ROWS, "condition", "role", "stale", "aliased"),
    "regpoint_clear": ("rpclear", "ok"),
    "comment_list": (*ROWS, "text"),
    "watch_list": (*ROWS, "mode", "length", "fmt", "wplist", "why"),
    "watch_clear": ("ok",),
    "symbols_find": ("map", "unknown"),
    "registers": ("A6", "A7", "SR", "USP"),
    "disassemble": ("bases",),
    "scan_start": ("save",),
    "memdump": ("save",),
    "palette": ("indirect",),
    "debug": ("altered", "source", "suspend", "ignore", "observe", "hardreset"),
}


def test_every_field_a_reply_sentence_names_is_in_its_model() -> None:
    tools = asyncio.run(s.mcp.list_tools())
    names = {t.name for t in tools}
    wrong: dict[str, Any] = {}
    for t in tools:
        doc, model = t.description or "", replies.MODELS[t.name]
        allowed = set(REPLY_WORDS.get(t.name, ()))
        if not reply_schema.reply_sentence_names(doc) and reply_schema.own_fields(model):
            wrong[t.name] = "its description names no field of its reply"
        elif miss := reply_schema.unmodelled(
                doc, model, names | set(t.input_schema.get("properties", {})) | allowed):
            wrong[t.name] = miss
        elif unused := sorted(allowed - set(reply_schema.reply_sentence_names(doc))):
            wrong[t.name] = f"allowed and no longer quoted: {unused}"
    assert not wrong, wrong


def test_every_tool_that_answers_with_a_stop_s_survey_names_its_fields() -> None:
    """The survey's fields reach a description through `STOP_FIELDS`, after a colon the
    sentence check reads as a list's: each is held to the model of every tool that quotes it."""
    fields = reply_schema.reply_sentence_names("Reply: " + docs.STOP_FIELDS.split(":", 1)[1])
    assert len(fields) > 5, fields
    quoting = [t for t in asyncio.run(s.mcp.list_tools())
               if docs.STOP_FIELDS in (t.description or "")]
    assert len(quoting) > 5, [t.name for t in quoting]
    held = {t.name: set(reply_schema.own_fields(replies.MODELS[t.name])) for t in quoting}
    lacks = {name: sorted(set(fields) - got) for name, got in held.items() if set(fields) - got}
    assert not lacks, lacks
