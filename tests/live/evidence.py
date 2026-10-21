"""What the live matrix keeps of a cell that FAILED: the emulator's two logs, copied out of the
session's scratch before `close` deletes it. And what a process log says the Lua console did,
read by a rule of its own, for the cell that holds the server's count up against it.

Its own module, with nothing run at import, so the offline tier can hold it: importing a live
script makes the run's scratch directory and puts the server on the path."""
from __future__ import annotations

import re
import shutil
from collections import Counter
from itertools import count
from pathlib import Path

import mame_files as files  # isort: skip -- found through the path the harness or the tests set


def slug(label: str) -> str:
    """`label` as one directory name: every run of anything but a letter, a digit or an
    underscore becomes a dash, so no separator and no `..` survives to leave the destination."""
    return re.sub(r"[^A-Za-z0-9_]+", "-", label).strip("-") or "cell"


def keep(session_scratch: Path, dest: Path, label: str) -> Path | None:
    """Copy the session's logs into a directory of their own under `dest`, named after `label`,
    and hand it back; None, and nothing created, when the session wrote neither. Two labels
    that slug alike get a directory each, so one cell's logs never overwrite another's."""
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


# THE LOG'S OWN WORDS, written here and not imported from the server: the cell that uses them
# checks the server's count, and a count checked against its own rule checks nothing. A reader
# death is the line MAME prints when the console's reader thread fails. Every chunk the server
# sends carries, in its echoed source, `print("<sentinel>#N", false, e)`, and prints the
# sentinel followed by a TAB when it runs: a chunk shown sent whose sentinel printed twice ran
# twice. A script that prints the sentinel's text itself was not sent by the server.
READER_DEATH = b"[LUA ERROR] in thread"
_SENT = re.compile(rb'print\("MAME_MCP_LUA_END#(\d+)", false, e\)')
_SENTINEL = re.compile(rb"MAME_MCP_LUA_END#(\d+)\t")


def console_in_log(stdout: bytes) -> dict[str, int]:
    """The console's reader deaths and reruns as the process log shows them, and `sentinels`,
    how many chunks the server sent that printed an end: zero means nothing was examined."""
    sent = set(_SENT.findall(stdout))
    ends = Counter(n for n in _SENTINEL.findall(stdout) if n in sent)
    return {"thread_errors": stdout.count(READER_DEATH),
            "reruns": sum(n - 1 for n in ends.values()), "sentinels": len(ends)}


def sentinel_order(stdout: bytes) -> list[int]:
    """The numbers of the chunks the server sent, in the order the console first printed each
    one's end: which line the console evaluated before which."""
    sent = set(_SENT.findall(stdout))
    order: list[int] = []
    for n in _SENTINEL.findall(stdout):
        if n in sent and int(n) not in order:
            order.append(int(n))
    return order


_SEQ = re.compile(r"#(\d+)")


def console_ran_the_throttle_first(lua: dict[str, object], throttle: dict[str, object],
                                   stdout: bytes) -> bool:
    """C.3's cell on a stub that refreshes the display after a console command: the command
    `lua` opens with (its pc read) runs the Lua console's hook, which evaluates the line a
    stopped `throttle` left in the pipe, so `lua` counts none ahead of its own; and the
    throttle's line did run, its end printed before `lua`'s. The count is what tells the two
    stubs apart: the order alone holds on either, since the pipe is read in order."""
    first, mine = (_SEQ.search(str(r.get(k) or "")) for r, k in ((throttle, "tag"), (lua, "call")))
    order = sentinel_order(stdout)
    return (lua.get("lines_ahead") == 0 and first is not None and mine is not None
            and int(first.group(1)) in order and int(mine.group(1)) in order
            and order.index(int(first.group(1))) < order.index(int(mine.group(1))))


def console_disagreement(stdout: bytes, console: dict[str, int]) -> dict[str, tuple[int, int]]:
    """Every count of `console` (the session block's) the log contradicts, as the log's figure
    beside the session's; empty when they agree. A death or a rerun is the console's business
    and the server's promise is to COUNT it, so agreement is the pass, not zero."""
    seen = console_in_log(stdout)
    return {k: (seen[k], console.get(k, -1)) for k in ("thread_errors", "reruns")
            if seen[k] != console.get(k, -1)}
