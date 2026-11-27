"""The reference's `knowledge_find` example: the server's reply over its rows read unsealed, as a
live run's record (to a path, else printed)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from scry_core.knowledge.base import Base

from scry_mame.knowledge import support

ROOT = Path(__file__).resolve().parent.parent
LABEL = "tests/knowledge_example.py: the pilot's dictionaries of rows, read unsealed"


def record() -> dict[str, Any]:
    support.load = lambda fts5=None: Base(support.SOURCES, None, fts5)
    from scry_mame import server

    asks = json.loads((ROOT / "docs/reference/asks.json").read_text(encoding="utf-8"))
    call = asks["tools"]["knowledge_find"]["call"]
    return {"section": LABEL, "label": "knowledge_find", "tool": "knowledge_find", "args": call,
            "reply": server.knowledge_find(**call), "verdict": "OK"}


if __name__ == "__main__":
    line = json.dumps(record())
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(line + "\n", encoding="utf-8")
    else:
        print(line)
