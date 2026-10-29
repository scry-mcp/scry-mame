from __future__ import annotations

import re
import shutil
from collections import Counter
from itertools import count
from pathlib import Path

from scry_mame import files  # isort: skip -- found through the path the harness or the tests set


def slug(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "-", label).strip("-") or "cell"


def keep(session_scratch: Path, dest: Path, label: str) -> Path | None:
    """Copy the session's logs under `dest`; None when there are none."""
    logs = [path for channel in sorted(files.LOG_FILES)
            if (path := files.log_path(session_scratch, channel)).is_file()]
    if not logs:
        return None
    name = slug(label)
    kept = next(path for n in count(1)
                if not (path := dest / (name if n == 1 else f"{name}-{n}")).exists())
    kept.mkdir(parents=True)
    for log in logs:
        shutil.copy2(log, kept / log.name)
    return kept


# Written here, not imported: the server's count must not be checked against its own rule.
# Running a sent chunk prints its sentinel and a TAB.
READER_DEATH = b"[LUA ERROR] in thread"
_SENT = re.compile(rb'print\("MAME_MCP_LUA_END#(\d+)", false, e\)')
_SENTINEL = re.compile(rb"MAME_MCP_LUA_END#(\d+)\t")


def console_in_log(stdout: bytes) -> dict[str, int]:
    """Zero `sentinels` means nothing was examined."""
    sent = set(_SENT.findall(stdout))
    ends = Counter(n for n in _SENTINEL.findall(stdout) if n in sent)
    return {"thread_errors": stdout.count(READER_DEATH),
            "reruns": sum(n - 1 for n in ends.values()), "sentinels": len(ends)}


def sentinel_order(stdout: bytes) -> list[int]:
    sent = set(_SENT.findall(stdout))
    order: list[int] = []
    for n in _SENTINEL.findall(stdout):
        if n in sent and int(n) not in order:
            order.append(int(n))
    return order


_SEQ = re.compile(r"#(\d+)")


def console_ran_the_throttle_first(lua: dict[str, object], throttle: dict[str, object],
                                   stdout: bytes) -> bool:
    first, mine = (_SEQ.search(str(r.get(k) or "")) for r, k in ((throttle, "tag"), (lua, "call")))
    order = sentinel_order(stdout)
    return (lua.get("lines_ahead") == 0 and first is not None and mine is not None
            and int(first.group(1)) in order and int(mine.group(1)) in order
            and order.index(int(first.group(1))) < order.index(int(mine.group(1))))


def console_disagreement(stdout: bytes, console: dict[str, int]) -> dict[str, tuple[int, int]]:
    """Each `console` count the log contradicts, as (log, session)."""
    seen = console_in_log(stdout)
    return {k: (seen[k], console.get(k, -1)) for k in ("thread_errors", "reruns")
            if seen[k] != console.get(k, -1)}
