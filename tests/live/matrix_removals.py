"""Section K's removal cells: a removal handed back unrun is lost, never resent."""

from pathlib import Path
from typing import Any

from live_harness import blocked, call, cell, ok, said
from reader_fault import reader_fault, reader_fault_counts

from scry_mame import capture as mcapture
from scry_mame import tally as mtally

# Present in a removal line and absent from an install line (`tap.remove_script`).
REMOVAL_LINE = "T.items[id] = nil"

K_REMOVALS = [
    "a removal handed back with no death is lost at the next list, and never resent",
    "a removal whose reader dies holding it is lost the same way, and never resent",
    "a range declared again while its removal is held reads no count of the removed tap, then "
    "counts from nothing",
]


def k_removals(t: list[str], refs: tuple[str, str, str], length: int) -> None:
    """`K_REMOVALS` on a stopped machine; `refs[2]` must be written at least once a frame."""
    def tid(ref: str) -> str:
        return f"{int(ref, 16):x}_{length}"

    def item(r: dict[str, Any], ref: str) -> dict[str, Any]:
        """`ref`'s tap whole: a stop's row is its count alone, installed/pending is the list's."""
        listed = call("declaration_list", kind="watch").get("watches") or []
        return next((w for w in listed if w.get("tally_id") == tid(ref)), {})

    def log() -> bytes:
        return Path(str(call("status").get("stdout_path"))).read_bytes()

    def tallied(ref: str) -> dict[str, Any]:
        added = call("watch_add", ref=ref, mode="count", length=length)
        call("step")
        return item(call("run_for", frames=3, seconds=5.0), ref) if ok(added) else {}

    for k, (ref, loud) in enumerate(((refs[0], False), (refs[1], True))):
        before = tallied(ref)
        planted = reader_fault(REMOVAL_LINE, kills=1, loud=loud)
        mark = len(log())
        cleared = call("declaration_clear", kind="watch", ref=ref)
        for _ in range(3):
            call("step")
        fired = reader_fault_counts()[0]
        # A latched row stays listed for the session, so filter by tally id.
        rows = [r for r in call("declaration_list",
                                kind="watch")["session"].get("tallies_not_removed") or []
                if r.get("tally_id") == tid(ref)]
        waiting = [r.get("tally_id") for r in call("status").get("tallies_pending_removal") or []]
        echoes = log()[mark:].count(REMOVAL_LINE.encode())
        cell(t[k], before.get("installed") is True and ok(planted) and ok(cleared)
             and fired == 1 and [(r.get("tally_id"), r.get("state")) for r in rows]
             == [(tid(ref), "lost")] and tid(ref) not in waiting and echoes == 1,
             f"before {before.get('state')}; fired {fired}; not removed {rows}; pending "
             f"{waiting}; removal echoes {echoes}")

    # The held removal lets the dumper rewrite the range's file while the tap is still
    # registered; the range is then declared again behind it.
    ref = refs[2]
    old = tallied(ref)
    planted = reader_fault(REMOVAL_LINE, lag=3)
    call("declaration_clear", kind="watch", ref=ref)
    call("run_for", frames=1, seconds=5.0)
    again = call("watch_add", ref=ref, mode="count", length=length)
    pending = item(call("run_for", frames=1, seconds=5.0), ref)
    after: dict[str, Any] = {}
    for _ in range(6):
        after = item(call("run_for", frames=1, seconds=5.0), ref)
        if after.get("installed") is True:
            break
    _fired, _lagged, held = reader_fault_counts()
    total = old.get("total")
    cell(t[2], old.get("state") == "tallied" and isinstance(total, int) and total > 0
         and ok(planted)
         and ok(again) and held >= 1
         and pending.get("pending") is True and pending.get("installed") is False
         and "total" not in pending and after.get("installed") is True
         and isinstance(after.get("total"), int) and after["total"] < total,
         f"old {old.get('state')} total {total}; held {held} frames; while pending "
         f"{pending.get('installed'), pending.get('state'), pending.get('total')}; installed "
         f"{after.get('installed'), after.get('state'), after.get('total')}")
    call("declaration_clear", kind="watch", all=True)


K_CAPTURE_LEFTOVER = ("a capture declared again after its removal ran reads no row the removed "
                      "one left on disk")


def k_capture_leftover(t: str, ref: str, trigger: str) -> None:
    """The rows file of a capture declared again after its removal ran starts at row 1."""
    args = {"ref": ref, "mode": "capture", "fmt": "u16[2]", "trigger": trigger}
    first = call("watch_add", **args)
    scratch = Path(str(call("status").get("scratch_dir")))
    rows_path = mcapture.paths(scratch, str(first.get("tally_id")))[1]

    def rows() -> list[str]:
        return rows_path.read_text().splitlines() if rows_path.exists() else []

    for _ in range(10):
        call("run_for", frames=2, seconds=10.0)
        if len(rows()) >= 3:
            break
    planted = reader_fault(REMOVAL_LINE, lag=3)
    call("declaration_clear", kind="watch", ref=ref)
    for _ in range(5):
        call("run_for", frames=1, seconds=10.0)
    left = rows()
    again = call("watch_add", **args)
    call("step")
    call("step")
    call("run_for", frames=2, seconds=10.0)
    numbers = [ln.split()[1] for ln in rows()]
    cell(t, ok(planted) and ok(again) and len(left) > 0 and numbers[:1] == ["1"]
         and numbers == [str(n) for n in range(1, len(numbers) + 1)],
         f"rows the removed capture left {[ln.split()[1] for ln in left]}; the new capture's "
         f"row numbers {numbers}")
    call("declaration_clear", kind="watch", ref=ref)


K_REDECLARE_LIVE = ("a range declared again over its live tap lists that tap's dump while the "
                    "new install is pending, never no_dump_yet")


def k_redeclare_live(t: str, ref: str, length: int) -> None:
    """Declared again with no removal, the listing before the new install answers reads the live
    tap's dump.

    The reader fault's lag holds the install: without it a queued line runs at the next console
    command (REFERENCE.md, *The console*) and the pending window would not exist."""
    def item(r: dict[str, Any]) -> dict[str, Any]:
        """`ref`'s tap whole, as in `k_removals`."""
        listed = call("declaration_list", kind="watch").get("watches") or []
        return next((w for w in listed if w.get("ref") == ref), {})

    first = call("watch_add", ref=ref, mode="count", length=length)
    call("step")
    tallied = item(call("run_for", frames=3, seconds=10.0))
    planted = reader_fault(mtally.dump_path(Path(), str(first.get('tally_id'))).name, lag=1)
    again = call("watch_add", ref=ref, mode="count", length=length)
    listed = item(call("declaration_list", kind="watch"))
    after = item(call("run_for", frames=2, seconds=10.0))
    if not (ok(first) and ok(planted) and "planted" in str(planted.get("output"))):
        blocked(t, f"the reader fault was not planted, so no install was held: {said(planted)}")
        call("declaration_clear", kind="watch", ref=ref)
        return
    cell(t, tallied.get("state") == "tallied" and ok(again)
         and again.get("pending") is True and again.get("installed") is False
         and listed.get("pending") is True and listed.get("installed") is False
         and listed.get("state") == "tallied"
         and int(listed.get("total", -1)) >= int(tallied.get("total", 0)) > 0
         and after.get("installed") is True,
         f"tallied {tallied.get('state')} {tallied.get('total')}; listed while pending "
         f"{listed.get('installed')} {listed.get('state')} {listed.get('total')}; after two "
         f"frames {after.get('installed')}")
    call("declaration_clear", kind="watch", ref=ref)
