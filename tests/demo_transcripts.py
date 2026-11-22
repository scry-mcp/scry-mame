"""The committed runs of the demos read back, standing in for an emulator."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scry_core import timeline
from scry_core.demo import Demo, Reply, counted

ENTRY = re.compile(r"^\*\*\d+\. `(?P<tool>\w+)`\*\*: (?P<verdict>OK|FAIL|INVALID) "
                   r"(?P<step>.+?): ", re.MULTILINE)
FENCE = re.compile(r"```json\n(.*?)\n```", re.DOTALL)


@dataclass(frozen=True)
class Entry:
    step: str
    tool: str
    args: dict[str, Any]
    reply: Reply


def read(transcript: Path) -> list[Entry]:
    """Every step of a committed run, in order."""
    text = transcript.read_text(encoding="utf-8")
    found = list(ENTRY.finditer(text))
    entries = []
    for here, after in zip(found, [*found[1:], None], strict=True):
        blocks = FENCE.findall(text[here.end():after.start() if after else len(text)])
        assert len(blocks) == 2, f"step {here['step']} holds {len(blocks)} json blocks, not 2"
        entries.append(Entry(here["step"], here["tool"], json.loads(blocks[0]),
                             Reply(json.loads(blocks[1]))))
    return entries


def timeline_of(demo: Demo, transcript: Path) -> dict[str, Any]:
    """The timeline `demo`'s steps would write for the committed run, validated by the writer."""
    steps = {step.name: step for step in demo.steps}
    builder = timeline.Builder(demo.name)
    for entry in read(transcript):
        step = steps[entry.step]
        fired = step.events(entry.args, entry.reply) if step.events is not None else ()
        builder.add(entry.step, entry.tool, entry.args, str(entry.reply["status"]),
                    counted(entry.reply), fired)
    return timeline.loads(builder.dumps())
