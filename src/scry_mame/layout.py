"""The `gfx_layout` language and the decoder under it: MAME's own terms for how tiles sit in bytes.

A layout takes MAME's field names and driver macros (`RGN_FRAC(n,d)`, `STEPn(a,b)`, all in BITS),
so it transcribes from a `GFXDECODE_ENTRY` by copy and paste. `total` is not a field: `first` and
`count` choose the tiles, because the count is the caller's question and not the format's.

As `gfx_element::decode` (`src/emu/drawgfx.cpp`) finds it, tile `t`'s pixel `(x, y)` has, for
plane `p`, the bit at `t * charincrement + planeoffset[p] + yoffset[y] + xoffset[x]` from the
block's first byte, most significant bit of a byte first, and plane 0 is the MOST significant bit
of the pixel. `RGN_FRAC(n,d)` is `n/d` of the WHOLE block's length in bits, whatever `offset` says.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from scry_core import prose

from scry_mame import state as st

LAYOUT_KEYS = ("width", "height", "planes", "planeoffset", "xoffset", "yoffset", "charincrement")
PLANES_MAX = 8                 # MAME's own MAX_GFX_PLANES
SIDE_MAX = 1024                # a tile's width or height, in pixels

_TOKEN = re.compile(r"\s*(?:(0[xX][0-9a-fA-F]+|\d+)|(RGN_FRAC)|([-+*(),]))")
_STEP = re.compile(r"^\s*STEP(\d+)\s*\((.*)\)\s*$", re.S)


# A value is LINEAR in the block's length: `const + sum(coef * (bits * num // den))`. It stays in
# that form until the block's length is known, so a layout is judged before the machine is asked.

@dataclass(frozen=True)
class Value:
    const: int
    fracs: tuple[tuple[int, int, int], ...] = ()     # (num, den, coef)

    def resolve(self, bits: int | None) -> int:
        if self.fracs and bits is None:
            raise ValueError("RGN_FRAC needs a block to be a fraction of")
        return self.const + sum(coef * ((bits or 0) * num // den) for num, den, coef in self.fracs)

    def __add__(self, other: Value) -> Value:
        return Value(self.const + other.const, self.fracs + other.fracs)

    def scaled(self, k: int) -> Value:
        return Value(self.const * k, tuple((n, d, c * k) for n, d, c in self.fracs))


class LayoutError(ValueError):
    """A layout that is not one: the message names the field and what was wrong."""


def _expr(text: str, field: str) -> Value:
    """`text` as a `Value`; nesting past the interpreter's recursion limit is refused."""
    try:
        return _parsed(text, field)
    except RecursionError:
        raise LayoutError(f"{field}: {text[:24]!r}... is nested deeper than an expression is "
                          "read") from None


def _parsed(text: str, field: str) -> Value:
    tokens: list[str] = []
    pos = 0
    while pos < len(text.rstrip()):
        m = _TOKEN.match(text, pos)
        if m is None:
            raise LayoutError(f"{field}: {text!r} is not an expression MAME's layouts use at "
                              f"{text[pos:pos + 12]!r} (integers, RGN_FRAC(n,d), STEPn(a,b), "
                              "+, -, *, brackets)")
        tokens.append(m.group(1) or m.group(2) or m.group(3))
        pos = m.end()
    at = 0

    def peek() -> str | None:
        return tokens[at] if at < len(tokens) else None

    def take(want: str | None = None) -> str:
        nonlocal at
        tok = peek()
        if tok is None or (want is not None and tok != want):
            raise LayoutError(f"{field}: {text!r} is not a whole expression "
                              f"(expected {want or 'more'} at token {at})")
        at += 1
        return tok

    def factor() -> Value:
        tok = take()
        if tok == "-":
            return factor().scaled(-1)
        if tok == "(":
            inner = expr()
            take(")")
            return inner
        if tok == "RGN_FRAC":
            take("(")
            num = _int(take(), field)
            take(",")
            den = _int(take(), field)
            take(")")
            if den == 0:
                raise LayoutError(f"{field}: RGN_FRAC({num},{den}) divides by zero")
            return Value(0, ((num, den, 1),))
        return Value(_int(tok, field))

    def term() -> Value:
        v = factor()
        while peek() == "*":
            take()
            w = factor()
            if v.fracs and w.fracs:
                raise LayoutError(f"{field}: {text!r} multiplies two RGN_FRACs")
            v = w.scaled(v.const) if not v.fracs else v.scaled(w.const)
        return v

    def expr() -> Value:
        v = term()
        while peek() in ("+", "-"):
            sign = take()
            w = term()
            v = v + (w if sign == "+" else w.scaled(-1))
        return v

    if not tokens:
        raise LayoutError(f"{field}: an empty expression")
    value = expr()
    if at != len(tokens):
        raise LayoutError(f"{field}: {text!r} has something after its expression")
    return value


def _int(tok: str, field: str) -> int:
    try:
        return int(tok, 0)
    except ValueError:
        raise LayoutError(f"{field}: {tok!r} is not an integer") from None


def _scalar(raw: Any, field: str) -> Value:
    if isinstance(raw, bool):
        raise LayoutError(f"{field}: {raw!r} is not a number")
    if isinstance(raw, int):
        return Value(raw)
    if isinstance(raw, str):
        return _expr(raw, field)
    raise LayoutError(f"{field}: {raw!r} is neither an integer nor an expression")


def _split(text: str) -> list[str]:
    """A driver-style list, `{ STEP8(0,1), 64, RGN_FRAC(1,2) }`, split at top-level commas."""
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1]
    out: list[str] = []
    cur: list[str] = []
    depth = 0
    for ch in text:
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
            continue
        depth += (ch == "(") - (ch == ")")
        cur.append(ch)
    out.append("".join(cur))
    return [item for item in (s.strip() for s in out) if item]


def _items(raw: Any, field: str) -> list[Value]:
    """A list field, as a JSON list or a braced string; `STEPn(a,b)` expands to its `n` terms."""
    if isinstance(raw, str):
        raw = _split(raw)
    if not isinstance(raw, list):
        raise LayoutError(f"{field}: {raw!r} is neither a list nor a braced string")
    out: list[Value] = []
    for item in raw:
        m = _STEP.match(item) if isinstance(item, str) else None
        if m is None:
            out.append(_scalar(item, field))
            continue
        n = int(m.group(1))
        if n not in (2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048):
            raise LayoutError(f"{field}: STEP{n} is not one of MAME's STEP macros")
        args = _split(m.group(2))
        if len(args) != 2:
            raise LayoutError(f"{field}: {item!r} takes two arguments, a start and a step")
        start, step = _expr(args[0], field), _expr(args[1], field)
        out.extend(start + step.scaled(i) for i in range(n))
    return out


@dataclass(frozen=True)
class Layout:
    """A layout as stated, each value still linear in the block's length."""

    name: str
    width: Value
    height: Value
    planes: Value
    planeoffset: tuple[Value, ...]
    xoffset: tuple[Value, ...]
    yoffset: tuple[Value, ...]
    charincrement: Value

    @property
    def needs_block(self) -> bool:
        return any(v.fracs for v in (self.width, self.height, self.planes, self.charincrement,
                                     *self.planeoffset, *self.xoffset, *self.yoffset))


@dataclass(frozen=True)
class Resolved:
    """A layout with its values in bits, for a block of known length."""

    name: str
    width: int
    height: int
    planes: int
    planeoffset: tuple[int, ...]
    xoffset: tuple[int, ...]
    yoffset: tuple[int, ...]
    charincrement: int

    def as_reply(self) -> dict[str, Any]:
        return {"name": self.name, "width": self.width, "height": self.height,
                "planes": self.planes, "planeoffset": list(self.planeoffset),
                "xoffset": list(self.xoffset), "yoffset": list(self.yoffset),
                "charincrement": self.charincrement}

    def tile_bits(self) -> tuple[int, int]:
        """The lowest and highest bit tile 0 touches, relative to the block's `offset`: the sums
        of each list's extremes, since the three are chosen independently."""
        lists = (self.planeoffset, self.yoffset, self.xoffset)
        return sum(min(v) for v in lists), sum(max(v) for v in lists)

    @cached_property
    def pixel_bits(self) -> tuple[tuple[tuple[int, int], ...], ...]:
        """Per pixel, row-major, each plane's (bit relative to the tile start, weight)."""
        weights = [1 << (self.planes - 1 - p) for p in range(self.planes)]
        return tuple(tuple((po + yo + xo, wt) for po, wt in zip(self.planeoffset, weights,
                                                                strict=True))
                     for yo in self.yoffset for xo in self.xoffset)


def parse_layout(raw: Any, allow_name: bool = False, where: str = "layout") -> Layout:
    """`raw` as a `Layout`: exactly MAME's fields (plus `name` if `allow_name`), counts matching."""
    if not isinstance(raw, dict):
        raise LayoutError(f"{where} is an object with the fields {list(LAYOUT_KEYS)}")
    allowed = set(LAYOUT_KEYS) | ({"name"} if allow_name else set())
    unknown = sorted(set(raw) - allowed)
    missing = [k for k in LAYOUT_KEYS if k not in raw]
    if unknown or missing:
        raise LayoutError(f"{where}: unknown {unknown}, missing {missing}; the fields are "
                          f"MAME's gfx_layout's, {list(LAYOUT_KEYS)} (`total` is `first` and "
                          "`count` here)")
    lay = Layout(str(raw.get("name", "")),
                 _scalar(raw["width"], f"{where}.width"), _scalar(raw["height"], f"{where}.height"),
                 _scalar(raw["planes"], f"{where}.planes"),
                 tuple(_items(raw["planeoffset"], f"{where}.planeoffset")),
                 tuple(_items(raw["xoffset"], f"{where}.xoffset")),
                 tuple(_items(raw["yoffset"], f"{where}.yoffset")),
                 _scalar(raw["charincrement"], f"{where}.charincrement"))
    for name in ("width", "height", "planes"):
        if getattr(lay, name).fracs:
            raise LayoutError(f"{where}.{name} is a count, not a fraction of the block")
    width, height, planes = lay.width.const, lay.height.const, lay.planes.const
    if not 1 <= width <= SIDE_MAX or not 1 <= height <= SIDE_MAX:
        raise LayoutError(f"{where}: {width}x{height} is outside 1..{SIDE_MAX} a side")
    if not 1 <= planes <= PLANES_MAX:
        raise LayoutError(f"{where}.planes={planes} is outside MAME's 1..{PLANES_MAX}")
    for name, want in (("planeoffset", planes), ("xoffset", width), ("yoffset", height)):
        got = len(getattr(lay, name))
        if got != want:
            raise LayoutError(f"{where}.{name} has {prose.counted(got, 'entry', 'entries')} and "
                              f"needs {want}, one per "
                              f"{'plane' if name == 'planeoffset' else 'pixel'}")
    return lay


def resolve(lay: Layout, bits: int | None) -> Resolved:
    """`lay` for a block of `bits` bits (None for a cpu-space range), refused below zero.
    A charincrement of 0 is MAME's too: every tile is the same bits, so `available` says one."""
    def r(v: Value) -> int:
        return v.resolve(bits)

    out = Resolved(lay.name, r(lay.width), r(lay.height), r(lay.planes),
                   tuple(map(r, lay.planeoffset)), tuple(map(r, lay.xoffset)),
                   tuple(map(r, lay.yoffset)), r(lay.charincrement))
    if min(out.planeoffset + out.xoffset + out.yoffset) < 0:
        raise LayoutError(f"{lay.name or 'layout'}: an offset resolves below zero")
    if out.charincrement < 0:
        raise LayoutError(f"{lay.name or 'layout'}: charincrement resolves below zero")
    return out


def check_layout(raw: Any, allow_name: bool = False, where: str = "layout") -> Layout:
    """`parse_layout`, refusing as `bad_argument`."""
    try:
        return parse_layout(raw, allow_name, where)
    except LayoutError as e:
        raise st.Invalid("bad_argument", str(e)) from None


def available(res: Resolved, block_bits: int, offset: int) -> int:
    """How many whole tiles fit in the block from byte `offset`."""
    _, hi = res.tile_bits()
    room = block_bits - offset * 8 - hi - 1
    if room < 0:
        return 0
    return 1 if res.charincrement == 0 else room // res.charincrement + 1


def decode(res: Resolved, data: bytes, offset: int, tile: int) -> list[int]:
    """Tile `tile` as `width * height` pixel values, row-major, as MAME decodes it."""
    base = offset * 8 + tile * res.charincrement
    out = []
    for pixel in res.pixel_bits:
        v = 0
        for rel, weight in pixel:
            b = base + rel
            if data[b >> 3] & (0x80 >> (b & 7)):
                v |= weight
        out.append(v)
    return out


