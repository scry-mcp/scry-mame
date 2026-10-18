"""A CALL CANCELLED WHILE ITS OWN REFUSAL IS BEING BUILT is cancelled in its body like any other:
the translation of a tool's errors runs inside the call (`mame_mcp._invoke`), so a cancel met
there (the survey `record_own_stop` makes polls) applies the end the tool declared and leaves the
record for the next reply."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from scry_core import cancel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_server import _running  # noqa: E402

import mame_mcp  # noqa: E402
import mame_running as running  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402


@pytest.fixture
def refusing() -> Iterator[Any]:
    def refuses(ctx: Any = None) -> dict[str, Any]:
        raise mstate.Invalid("bad_argument", "refused by its own judge")
    tool = mame_mcp.tool("refuses", summary=lambda a, r: "refused", on_cancel="stop")(refuses)
    yield tool
    s.mcp._tool_manager._tools.pop("refuses", None)
    mame_mcp._SUMMARIES.pop("refuses", None)
    mame_mcp._BODIES.pop("refuses", None)


def test_a_cancel_met_while_the_refusal_is_built_applies_the_declared_end(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, refusing: Any) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.running = True
    stops: list[str] = []
    real_record = running.record_own_stop

    def record_own_stop(name: str, *a: Any) -> None:
        if not cancel.shielding():
            raise asyncio.CancelledError       # the survey's poll met the cancel
        real_record(name, *a)

    def stop(*a: Any, **k: Any) -> dict[str, Any]:
        stops.append("stop")
        ses.running = False
        return {"status": "ok"}
    monkeypatch.setattr(running, "record_own_stop", record_own_stop)
    monkeypatch.setattr(running, "stop", stop)
    mstate.STATE.cancelled = None
    with pytest.raises(asyncio.CancelledError):
        refusing()
    record = mstate.STATE.take_cancelled()
    assert stops == ["stop"]
    assert record is not None and (record.tool, record.left) == ("refuses", "stopped")
