"""The addresses the live matrix probes at the program space's edges, from a `machine_map`
reply ALONE.

Its own module, with nothing run at import, so the offline tier can hold the derivation to the
reply: importing a live script makes the run's scratch directory and puts the server on the
path."""
from __future__ import annotations

from typing import Any


def program_edges(reply: dict[str, Any],
                  cpu: str) -> tuple[int, int | None, int | None]:
    """`(last, hole, space_end)` of `cpu`'s program space: the last mapped byte, the first
    address between two map entries that no entry covers, None when the map leaves none, and
    the space's last address, None when no `spaces` row of the reply carries an
    `address_mask` for it. `cpu` is the full tag, as
    the reply spells it. A reply that says it was `truncated` is refused: a section cut at the
    reply's cap can end before the entry that fills a gap, so a hole derived from it may be a
    mapped address under the wrong name, and its last entry need not be the map's."""
    if reply.get("truncated"):
        raise LookupError("the `machine_map` reply is `truncated`, so its address map is a "
                          "fragment and no edge is derived from it")
    spans = sorted((int(e["start"], 16), int(e["end"], 16)) for e in reply["address_map"]
                   if (e["cpu"], e["space"]) == (cpu, "program"))
    if not spans:
        raise LookupError(f"the `machine_map` reply carries no program entry for {cpu}")
    last = max(end for _, end in spans)
    hole = next((end + 1 for (_, end), (nxt, _) in zip(spans, spans[1:], strict=False)
                 if nxt > end + 1), None)
    masks = [int(row["address_mask"], 16) for row in reply["spaces"]
             if (row["cpu"], row["space"]) == (cpu, "program") and "address_mask" in row]
    return last, hole, masks[0] if masks else None
