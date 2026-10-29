"""A schema-refused argument still answers in this server's envelope."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from typing import Annotated, Any, get_args, get_origin

import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError
from pydantic import TypeAdapter, ValidationError

from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402


def _call(name: str, args: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    res = asyncio.run(s.mcp.call_tool(name, args))
    text = "".join(c.text for c in res.content if getattr(c, "text", None))
    return res, json.loads(text)


def test_a_wrong_typed_argument_answers_the_envelope_and_not_the_sdks_text() -> None:
    res, reply = _call("run_for", {"frames": [1, 2, 3]})
    assert res.is_error is not True, "a refusal is a reply, as every other refusal here is"
    assert reply["status"] == "INVALID" and reply["code"] == "bad_argument", reply
    assert reply["summary"].startswith("run_for: INVALID (bad_argument)"), reply["summary"]
    assert "frames" in reply["message"] and "integer" in reply["message"], reply["message"]
    assert "pydantic" not in reply["message"] and "errors.pydantic.dev" not in reply["message"]
    assert list(reply)[-1] == "session", list(reply)


def test_the_tools_own_refusal_still_flows_through_the_seam_unchanged() -> None:
    _res, reply = _call("read_memory", {"ref": "0", "length": 0})
    assert reply["code"] == "bad_argument" and list(reply)[-1] == "session", reply


@pytest.mark.parametrize("defect", [
    AttributeError("a real defect"),
    # Same cause as a schema refusal; the SDK's wrapper is what tells them apart.
    pytest.param(None, id="a-validation-error-of-the-body"),
])
def test_a_genuine_defect_is_not_dressed_up_as_a_refusal(defect: Exception | None) -> None:
    """An exception out of a tool body keeps the SDK's error path."""

    async def boom() -> dict[str, Any]:
        if defect is None:
            TypeAdapter(int).validate_python("a real defect")
        raise defect or AssertionError("unreachable")

    s.mcp._tool_manager.add_tool(boom)
    try:
        with pytest.raises(UnexpectedToolError) as raised:
            asyncio.run(s.mcp.call_tool("boom", {}))
    finally:
        s.mcp._tool_manager._tools.pop("boom", None)
    # The SDK keeps a crash's text off the wire and hangs it on the cause.
    assert "a real defect" not in str(raised.value), raised.value
    assert isinstance(raised.value.__cause__, (type(defect) if defect else ValidationError)), \
        raised.value.__cause__
    assert "a real defect" in str(raised.value.__cause__)


# The seam sits outside `tool()`'s wrapper, hence outside `LOCK`; the refusal ends the call
# (`State.end_call`), which clears `found_stop_last`, the one-time account of a stop the
# machine reached on its own.


def _lock_held_elsewhere() -> tuple[threading.Thread, threading.Event, list[float]]:
    """Hold `LOCK` on another thread: it is an `RLock`, so the same thread proves nothing."""
    held, let_go = threading.Event(), threading.Event()
    released_at: list[float] = []

    def holder() -> None:
        with mstate.LOCK:
            held.set()
            let_go.wait(5.0)
            released_at.append(time.monotonic())

    keeper = threading.Thread(target=holder, daemon=True)
    keeper.start()
    assert held.wait(5.0), "the holder never got the lock, so nothing below is a measurement"
    return keeper, let_go, released_at


def test_the_schema_refusal_is_built_under_the_session_lock() -> None:
    """The refusal waits for the machine like every other call."""
    keeper, let_go, _released = _lock_held_elsewhere()
    done = threading.Event()
    box: list[tuple[Any, dict[str, Any]]] = []

    def refuse() -> None:
        try:
            box.append(_call("run_for", {"frames": [1, 2, 3]}))
        finally:
            done.set()

    caller = threading.Thread(target=refuse, daemon=True)
    caller.start()
    assert not done.wait(0.3), "the refusal was built while another call held the machine"
    let_go.set()
    assert done.wait(5.0), "and it goes through once the lock is free"
    keeper.join(5.0)
    caller.join(5.0)
    _res, reply = box[0]
    assert reply["status"] == "INVALID" and reply["code"] == "bad_argument", reply
    assert list(reply)[-1] == "session", list(reply)


def test_the_wait_for_the_lock_is_off_the_event_loop() -> None:
    """A plain `with LOCK:` in the coroutine deadlocks; a turning loop proves a worker waits."""
    keeper, let_go, released_at = _lock_held_elsewhere()
    ticked_at: list[float] = []

    async def scenario() -> Any:
        pending = asyncio.create_task(s.mcp.call_tool("run_for", {"frames": [1, 2, 3]}))
        for _ in range(5):
            await asyncio.sleep(0.02)
            ticked_at.append(time.monotonic())
        let_go.set()
        return await pending

    res = asyncio.run(scenario())
    keeper.join(5.0)
    assert res.is_error is not True
    assert ticked_at and released_at, (ticked_at, released_at)
    assert ticked_at[0] < released_at[0], (
        "the event loop stopped turning while the refusal waited for the lock")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))


# The SDK builds argument models lax (coerces, drops unknown names, parses JSON strings); the
# server swaps in a strict model and turns that rescue off.


def test_the_sdk_hooks_the_strict_arguments_ride_on_still_exist() -> None:
    """An SDK that moves the hooks the strict swap rides on fails here, not silently lax."""
    import inspect as _inspect

    from mcp.server.mcpserver.utilities.func_metadata import FuncMetadata

    assert "arg_model" in FuncMetadata.model_fields
    source = _inspect.getsource(FuncMetadata.validate_arguments)
    assert "self.pre_parse_json(" in source and "self.arg_model.model_validate(" in source
    for t in s.mcp._tool_manager.list_tools():
        config = t.fn_metadata.arg_model.model_config
        assert config.get("strict") is True and config.get("extra") == "forbid", t.name
    published = asyncio.run(s.mcp.list_tools())
    assert published and all(
        t.input_schema.get("additionalProperties") is False for t in published), [
        t.name for t in published if t.input_schema.get("additionalProperties") is not False]


@pytest.mark.parametrize("name,args,names", [
    ("read_memory", {"ref": "400", "bogus": 1}, "bogus"),
    ("read_memory", {"ref": "400", "length": "16"}, "length"),
    ("perform", {"steps": '[{"op": "status"}]'}, "steps"),
])
def test_a_wrong_type_an_encoded_list_and_an_unknown_name_are_refused(
    name: str, args: dict[str, Any], names: str,
) -> None:
    _res, reply = _call(name, args)
    assert reply["status"] == "INVALID" and reply["code"] == "bad_argument", reply
    assert reply["message"].startswith("refused by the schema") and names in reply["message"], \
        reply["message"]


_SAMPLE: dict[Any, Any] = {str: "0", int: 2, float: 1.0, bool: False, dict[str, Any]: {},
                           dict[str, Any] | str: {}, list[dict[str, Any] | str]: [{}],
                           list[int]: [0, 0, 8, 8], list[list[int]]: [[0, 0, 8, 8]]}


def test_every_tool_that_takes_ctx_still_accepts_a_valid_call() -> None:
    """`ctx` is injected outside the model, which forbids unknown names, so it must pass."""
    import inspect as _inspect

    seen = []
    for t in s.mcp._tool_manager.list_tools():
        params = _inspect.signature(t.fn, eval_str=True).parameters
        if "ctx" not in params:
            continue
        args: dict[str, Any] = {}
        for p in params.values():
            if p.name == "ctx" or p.default is not _inspect.Parameter.empty:
                continue
            ann = get_args(p.annotation)[0] if get_origin(p.annotation) is Annotated \
                else p.annotation
            args[p.name] = _SAMPLE.get(ann, [{"op": "status"}])
        _res, reply = _call(t.name, args)
        assert not reply.get("message", "").startswith("refused by the schema"), (t.name, reply)
        seen.append(t.name)
    assert len(seen) >= 5, f"too few ctx tools found to mean anything: {seen}"
