"""What this session established about its board's graphics, in the order it was established:
every `gfx_locate` answer, every `gfx_sweep`, every choice a person made from a sweep's sheet.

WHY A LEDGER. A draft manifest (`mame_draft`) is a statement about this machine, and each entry
in it has to name what proved it. So the tools that look at the machine write down what they
saw, whole, as they answer, and the draft is derived from that record alone: the same record
gives the same draft and the same report, byte for byte.

WHY THE SESSION'S. It lives in `STATE.evidence` and goes with the machine at `close` and
`start` (`State._reset`): a match seen on another run of another build is not evidence about
this one.

SWEEP IDS. A sweep's candidates are named `s<sweep>c<candidate>` (`s1c3`), the label its sheet
prints over the cell, so the cell a person or a model looks at is the argument of the next
call: `gfx_locate(layouts=["s1c3"])`, `gfx_view(layout="s1c3")`, `gfx_draft(choose=...)`.
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

import mame_layout as ml
import mame_state as st
from mame_state import STATE

SWEEP_ID = re.compile(r"^s(\d+)c(\d+)$", re.IGNORECASE)
MATCHES_KEPT = 4096      # the matches one locate answer records; past it they are counted


def locates() -> list[dict[str, Any]]:
    return STATE.evidence["locates"]


def sweeps() -> list[dict[str, Any]]:
    return STATE.evidence["sweeps"]


def choices() -> list[dict[str, Any]]:
    return STATE.evidence["choices"]


# what names a block: a region or share and where in it, or a range of a cpu's space, whose
# `tag` is only the space's name, by its address and its cpu
SOURCE_FIELDS = ("kind", "tag", "offset", "addr", "addr_cpu")


class SourceKey(NamedTuple):
    """A block's identity as a graphics read saw it, built from that reply's `source_fields`:
    for `space` the offset is 0 and the address is in `addr`/`addr_cpu`. It is NOT a capture's
    `mame_capture.TapSource`, which says where the tap reads at run time (for `space`, at the cpu
    address): the two never meet, since the draft pairs a capture with the evidence by frame
    timing."""
    kind: str
    tag: str
    offset: int
    addr: str
    addr_cpu: str

    @classmethod
    def of(cls, src: dict[str, Any]) -> SourceKey:
        return cls(kind=src.get("kind", ""), tag=src.get("tag", ""),
                   offset=int(src.get("offset", 0)), addr=src.get("addr", ""),
                   addr_cpu=src.get("addr_cpu", ""))

    def reply(self) -> dict[str, Any]:
        """The key as a reply shows it: the address and its cpu only where there is one."""
        return {k: v for k, v in self._asdict().items() if k in self._fields[:3] or v}


def source_of(fields: dict[str, Any]) -> dict[str, Any]:
    """The block a reply read, as the evidence keeps it."""
    return {k: fields[k] for k in SOURCE_FIELDS if k in fields}


def layout_key(reply: dict[str, Any]) -> tuple[Any, ...]:
    """A resolved layout's identity: its offsets, whatever it was called."""
    return (reply["width"], reply["height"], reply["planes"], tuple(reply["planeoffset"]),
            tuple(reply["xoffset"]), tuple(reply["yoffset"]), reply["charincrement"])


def record_locate(fields: dict[str, Any], matches: list[dict[str, Any]]) -> int:
    """Keep one `gfx_locate` answer: `fields` as its reply carries them, `matches` all of them
    (the reply shows the first few). Answers its number, from 1."""
    n = len(locates()) + 1
    locates().append({
        "n": n, "frame_screen": fields["frame_screen"], "palette": fields["palette"],
        "source": source_of(fields),
        "patch": fields["patch"], "transparent": fields["transparent"], "flips": fields["flips"],
        "candidates": [row["layout"] for row in fields["candidates"]],
        # a rival that matched nothing is told apart only where every tile it has was tried
        "searched_whole": [row["tiles_searched"] == [0, row["tiles_available"]]
                           for row in fields["candidates"]],
        "matches_total": len(matches),
        "matches": [{k: m[k] for k in ("layout", "window", "tile", "flip", "base", "byte",
                                       "compared", "shape", "pen_map") if k in m}
                    for m in matches[:MATCHES_KEPT]],
    })
    return n


def record_sweep(source: dict[str, Any], palette: str, pen_base: int,
                 candidates: list[dict[str, Any]], image: dict[str, Any]) -> int:
    """Keep one sweep: its source, its candidates (`id`, `raw` layout, `what`) and its sheet."""
    n = len(sweeps()) + 1
    sweeps().append({"n": n, "source": source, "palette": palette, "pen_base": pen_base,
                     "candidates": candidates,
                     "sheet": {"path": image["path"], "sha256": image["sha256"]}})
    return n


def sweep_id(n: int, k: int) -> str:
    return f"s{n}c{k}"


def find_candidate(name: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """The sweep and the candidate a sweep id names, or None."""
    m = SWEEP_ID.match(name)
    if m is None:
        return None
    n, k = int(m.group(1)), int(m.group(2))
    if not 1 <= n <= len(sweeps()):
        return None
    sweep = sweeps()[n - 1]
    cand = next((c for c in sweep["candidates"] if c["id"] == sweep_id(n, k)), None)
    return None if cand is None else (sweep, cand)


def candidate_layout(name: str, where: str) -> ml.Layout:
    """The layout a sweep id names, carrying the id as its name; the refusal names the ids
    this session's sweeps hold."""
    found = find_candidate(name)
    if found is None:
        held = [c["id"] for s in sweeps() for c in s["candidates"]]
        raise st.Invalid("unknown_ref", f"{where}={name!r} names no candidate of this session's "
                         f"sweeps; they hold {held[:16] or 'none (run gfx_sweep first)'}"
                         + (" and more" if len(held) > 16 else ""))
    lay = ml.parse_layout(found[1]["raw"], allow_name=True, where=where)
    return ml.Layout(found[1]["id"], lay.width, lay.height, lay.planes, lay.planeoffset,
                     lay.xoffset, lay.yoffset, lay.charincrement)
