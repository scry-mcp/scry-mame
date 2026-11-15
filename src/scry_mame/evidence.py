"""The session's record of its board's graphics: every `gfx_locate`, `gfx_sweep` and choice.

The draft manifest is derived from this record alone. It lives in `STATE.evidence` so a reset
drops it: a match from another build is not evidence about this one.

A sweep's candidates are named `s<sweep>c<candidate>` (`s1c3`), the label its sheet prints, so a
cell can be passed straight to the next call (`gfx_locate(layouts=["s1c3"])`).
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

from scry_mame import layout as ml
from scry_mame import state as st
from scry_mame.state import STATE

SWEEP_ID = re.compile(r"^s(\d+)c(\d+)$", re.IGNORECASE)
MATCHES_KEPT = 4096      # the matches one locate answer records; past it they are counted


def locates() -> list[dict[str, Any]]:
    return STATE.evidence["locates"]


def sweeps() -> list[dict[str, Any]]:
    return STATE.evidence["sweeps"]


def choices() -> list[dict[str, Any]]:
    return STATE.evidence["choices"]


# a `space` block is named by address and cpu: its `tag` is only the space's name
SOURCE_FIELDS = ("kind", "tag", "offset", "addr", "addr_cpu")


class SourceKey(NamedTuple):
    """A block's identity as a graphics read saw it; not a capture's `TapSource`, which says where
    the tap reads at run time."""
    kind: str
    tag: str
    offset: int
    addr: str
    addr_cpu: str

    @classmethod
    def of(cls, src: dict[str, Any]) -> SourceKey:
        return cls(kind=src.get("kind", ""), tag=src.get("tag", ""),
                   offset=int(str(src.get("offset", 0)), 0), addr=src.get("addr", ""),
                   addr_cpu=src.get("addr_cpu", ""))

    def reply(self) -> dict[str, Any]:
        """The key as a reply shows it, address and cpu only where set."""
        shown = {**self._asdict(), "offset": st.hex_addr(self.offset)}
        return {k: v for k, v in shown.items() if k in self._fields[:3] or v}


def source_of(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: fields[k] for k in SOURCE_FIELDS if k in fields}


def layout_key(reply: dict[str, Any]) -> tuple[Any, ...]:
    """A resolved layout's identity, whatever it was called."""
    return (reply["width"], reply["height"], reply["planes"], tuple(reply["planeoffset"]),
            tuple(reply["xoffset"]), tuple(reply["yoffset"]), reply["charincrement"])


def record_locate(fields: dict[str, Any], matches: list[dict[str, Any]]) -> int:
    """Keep one `gfx_locate` answer, with all its `matches`; answers its number, from 1."""
    n = len(locates()) + 1
    locates().append({
        "n": n, "frame_screen": fields["frame_screen"], "palette": fields["palette"],
        "source": source_of(fields),
        "patch": fields["patch"], "transparent": fields["transparent"], "flips": fields["flips"],
        "candidates": [row["layout"] for row in fields["candidates"]],
        # a rival that matched nothing counts only if every tile it has was tried
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
    """Keep one sweep and its sheet; answers its number."""
    n = len(sweeps()) + 1
    sweeps().append({"n": n, "source": source, "palette": palette, "pen_base": pen_base,
                     "candidates": candidates,
                     "sheet": {"path": image["path"], "sha256": image["sha256"]}})
    return n


def sweep_id(n: int, k: int) -> str:
    return f"s{n}c{k}"


def find_candidate(name: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
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
    """The layout a sweep id names, carrying the id as its name."""
    found = find_candidate(name)
    if found is None:
        held = [c["id"] for s in sweeps() for c in s["candidates"]]
        raise st.Invalid("unknown_ref", f"{where}={name!r} names no candidate of this session's "
                         f"sweeps; they hold {held[:16] or 'none (run gfx_sweep first)'}"
                         + (" and more" if len(held) > 16 else ""))
    lay = ml.parse_layout(found[1]["raw"], allow_name=True, where=where)
    return ml.Layout(found[1]["id"], lay.width, lay.height, lay.planes, lay.planeoffset,
                     lay.xoffset, lay.yoffset, lay.charincrement)
