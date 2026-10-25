from __future__ import annotations

from typing import Any


def program_edges(reply: dict[str, Any],
                  cpu: str) -> tuple[int, int | None, int | None]:
    """`(last, hole, space_end)` of `cpu`'s program space; the last two may be None.

    Refuses a `truncated` reply: a cut map can fake a hole."""
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
