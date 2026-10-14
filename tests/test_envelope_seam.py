"""A wrong-typed argument is refused by the schema before the tool runs, and the refusal still
arrives in this server's envelope: `summary`, `status: INVALID`, `code: bad_argument`, a
`message` naming the argument, `session` last. ONE seam in the dispatch and no validation of
our own: the schema keeps judging the type, the seam only gives the refusal the shape every
other refusal has, so a caller reads one shape and not two."""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import threading
import time
from typing import Annotated, Any, get_args, get_origin

import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError
from pydantic import TypeAdapter, ValidationError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import server as s  # noqa: E402


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
    # A body's own validation failing is a defect too, though its cause is the type the
    # schema's refusal carries: what tells them apart is the SDK's wrapper, not the cause.
    pytest.param(None, id="a-validation-error-of-the-body"),
])
def test_a_genuine_defect_is_not_dressed_up_as_a_refusal(defect: Exception | None) -> None:
    """The seam translates the SCHEMA's refusal only: an exception out of a tool body keeps
    the SDK's error path, so a broken instrument is never read as a clean refusal."""

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
    # The SDK keeps a crash's own text off the wire and hangs it on the cause, so the defect is
    # found there and nowhere in the message: a client reads the generic line, the log the cause.
    assert "a real defect" not in str(raised.value), raised.value
    assert isinstance(raised.value.__cause__, (type(defect) if defect else ValidationError)), \
        raised.value.__cause__
    assert "a real defect" in str(raised.value.__cause__)


# ------------------------------------------- and the refusal is built over the ONE machine
#
# THE SEAM IS OUTSIDE `tool()`'s WRAPPER, so it is outside the `_LOCK` that wrapper holds. That
# would be a torn read on its own; what makes it a write is that building the reply ends in
# `mame_envelope.envelope`, which CLEARS `found_stop_last` -- the one-time account of a stop the
# machine reached on its own. A call the schema refused could take that account away from the
# call that was building the reply meant to carry it.


def _lock_held_elsewhere() -> tuple[threading.Thread, threading.Event, list[float]]:
    """A thread that takes `_LOCK` and holds it until told to let go, with the moment it did.
    ANOTHER thread is the point: `_LOCK` is an `RLock`, so a hold taken on the same thread
    would prove nothing about a second call."""
    held, let_go = threading.Event(), threading.Event()
    released_at: list[float] = []

    def holder() -> None:
        with s._LOCK:
            held.set()
            let_go.wait(5.0)
            released_at.append(time.monotonic())

    keeper = threading.Thread(target=holder, daemon=True)
    keeper.start()
    assert held.wait(5.0), "the holder never got the lock, so nothing below is a measurement"
    return keeper, let_go, released_at


def test_the_schema_refusal_is_built_under_the_session_lock() -> None:
    """It WAITS for the machine like every other call, instead of reading the state group and
    clearing the stop account beside one that is mid-reply."""
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
    """AND IT CANNOT BE A PLAIN `with _LOCK:` IN THE COROUTINE, which is why this case exists
    beside the one above. Every tool body here is synchronous, so the SDK runs it on a worker
    thread (`anyio.to_thread.run_sync`) and it is that thread which holds the lock; a bounded
    wait reports its progress through `_progress`, which reaches the event loop from the
    worker with `anyio.from_thread.run`. A loop parked in `_LOCK.acquire()` never runs that
    callback, so the worker never finishes and never releases the lock, and the loop never
    gets it: both sides wait for ever. The wait therefore goes to a worker thread too, and
    what proves it is the loop still turning while the refusal is pending."""
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


# ------------------------------------------------------------ strict arguments at the surface
#
# The SDK builds each tool's argument model LAX: a convertible type is coerced, an unknown
# name dropped, and a JSON string parsed into the list or object it spells before the model
# sees it. The contract says a wrong type or an unknown name is REFUSED, so the server swaps
# in a strict model and turns that rescue off; these cases hold the swap to the SDK it rides.


def test_the_sdk_hooks_the_strict_arguments_ride_on_still_exist() -> None:
    """The swap reads three things off the SDK: a tool's `fn_metadata`, its `arg_model`, and
    `validate_arguments` going through `pre_parse_json` before the model. An SDK that moves
    any of them fails HERE, by name, instead of leaving the surface lax in silence."""
    import inspect as _inspect

    from mcp.server.mcpserver.utilities.func_metadata import FuncMetadata

    assert "arg_model" in FuncMetadata.model_fields
    source = _inspect.getsource(FuncMetadata.validate_arguments)
    assert "self.pre_parse_json(" in source and "self.arg_model.model_validate(" in source
    for t in s.mcp._tool_manager.list_tools():
        config = t.fn_metadata.arg_model.model_config
        assert config.get("strict") is True and config.get("extra") == "forbid", t.name
    # And what a client is TOLD is what is enforced: the published schema closes too.
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
                           list[int]: [0, 0, 8, 8]}


def test_every_tool_that_takes_ctx_still_accepts_a_valid_call() -> None:
    """THE INJECTED-ARGUMENT HAZARD: `ctx` is handed in by the SDK and kept out of the model,
    so a model that forbids unknown names must still let every such tool through. With no
    machine a valid call is the tool's own answer, never the schema's refusal."""
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
            # A closed vocabulary's `Annotated[str, ...]` is sampled as the scalar it wraps.
            ann = get_args(p.annotation)[0] if get_origin(p.annotation) is Annotated \
                else p.annotation
            args[p.name] = _SAMPLE.get(ann, [{"op": "status"}])
        _res, reply = _call(t.name, args)
        assert not reply.get("message", "").startswith("refused by the schema"), (t.name, reply)
        seen.append(t.name)
    assert len(seen) >= 5, f"too few ctx tools found to mean anything: {seen}"
