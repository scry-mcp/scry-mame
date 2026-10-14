"""A project's graphics knowledge, `gfx.yaml`: the fleet schema this server owns, and its loader.

WHAT A PROJECT STATES. Named FORMATS, each a layout in `gfx_layout`'s own terms (`mame_layout`);
named ASSETS, a block of the machine read under a format through a palette; and draw COMMANDS,
the register block a capture reads (`mame_capture`), the write that fires it, and which bits of
which word hold each coordinate; and PALETTE PORTS, the ports a palette's pens are written
through, a RAMDAC, a latch or a sequence (`mame_ramdac`). A project states; nothing it writes
runs here.

EVIDENCE. Every entry carries `status` and `source`: `proved` (checked against the machine by
something that could have failed, which `source` names), `declared` (transcribed from a source
not checked here: a driver line, a datasheet) or `human` (a person's choice). A figure belongs
in the report or the commit that measured it, never in the manifest, where it would expire.

ROLES AND FLAGS. The server computes with a closed set of ROLES (`ROLES`), so a misspelt role is
refused rather than quietly becoming something else; anything else a project wants reported goes
under `flags`, read and shown raw, never interpreted. A field is a list of `parts`, because
hardware splits a coordinate across words: each part takes the bits of `mask` from one word, low
bit first, and places them from bit `at` of the value. A coordinate the hardware stores
reversed carries `sign: -1` (`value = -bits + add`), and a size the hardware fixes is a `const`
instead of parts. A command fires on a write to one of its words with `value`, or on a write to
`address` outside the block (the port a game copies the block to), and with no `value` every
such write fires.

REFUSED WHOLE. The first unknown key, missing key, wrong type or dangling name refuses the whole
file with the path that holds it (a misspelt `maks` is `commands.blit.fields.dest_x.parts[1].maks`):
a key silently ignored is a setting silently left at its default.
"""

from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mame_envelope as menvelope
import mame_evidence as evidence
import mame_files as files
import mame_inputs as inputs
import mame_layout as ml
import mame_prose as prose
import mame_space as mspace
import mame_state as st
import mame_watches as watches
import mame_yaml
from mame_state import STATE

SCHEMA = 1
STATUSES = ("proved", "declared", "human")
# The roles a direction or a boolean is read from: one bit each, and `asserted` says which value
# means increasing (a direction), BG or the like (`plane` is matched to its planes' `when`), or
# that the blit reads its source (`reads_source`).
ONE_BIT_ROLES = ("dest_dir_x", "dest_dir_y", "source_dir_x", "source_dir_y", "reads_source")
ROLES = ("dest_x", "dest_y", "dest_x_end", "dest_y_end", "width", "height",
         "source_x", "source_y", "source_tile", "plane", *ONE_BIT_ROLES)
SIZE_ROLES = ("width", "height")   # the roles a `const` may state
WORD_BYTES = (1, 2, 4)
VALUE_BITS = 32          # the widest value a field composes: a coordinate, a page, a flag
COMPONENTS = ("r", "g", "b")
RAMDAC_PENS = 256        # a RAMDAC's index port is a byte, so it names this many pens
PROTOCOLS = ("ramdac", "latch", "sequence")
PACKED = ("latch", "sequence")   # a whole colour in one word, never a component a write
PEN_COUNT_MAX = 1024     # Speed Fight's 10-bit index, the widest a known protocol addresses
# THE FIRST LINE OF A DRAFT (`mame_draft`), a comment: loaded like any manifest and said to be a
# draft, until the owner confirms it by deleting the line.
DRAFT_MARKER = ("# DRAFT gfx.yaml written by gfx_draft from one session's evidence: delete this "
                "line to confirm it")


class ManifestError(ValueError):
    """A manifest that is not one: the message names where."""


# ------------------------------------------------------------------ the parts of a manifest

@dataclass(frozen=True)
class Part:
    word: int
    mask: int
    at: int

    @property
    def bits(self) -> int:
        return bin(self.mask).count("1")


@dataclass(frozen=True)
class Field:
    """A value composed from bits of the block's words, times `sign`, plus `add`; with no
    parts, the constant `add` (a size the hardware fixes)."""

    name: str
    parts: tuple[Part, ...]
    add: int
    asserted: int | None
    status: str
    source: str
    sign: int = 1

    @property
    def width(self) -> int:
        return max((p.at + p.bits for p in self.parts), default=0)

    def value(self, words: list[int]) -> int:
        """The field in `words` (the block's words, in their logical order)."""
        out = 0
        for part in self.parts:
            word, bit = words[part.word], part.at
            for k in range(part.mask.bit_length()):
                if part.mask >> k & 1:
                    out |= (word >> k & 1) << bit
                    bit += 1
        return self.sign * out + self.add

    def holds(self, words: list[int]) -> bool:
        """For a one-bit role: whether its value is the `asserted` one."""
        return self.value(words) == self.asserted


@dataclass(frozen=True)
class Origin:
    """Where a plane's screen origin sits in the plane: a constant, or `field * scale + add`."""

    const: int
    field: str
    scale: int

    def value(self, cmd: Command, words: list[int]) -> int:
        return self.const + (self.scale * cmd.named(self.field).value(words) if self.field else 0)


@dataclass(frozen=True)
class Plane:
    when: int | None
    name: str
    order: int
    origin_x: Origin
    origin_y: Origin
    width: int
    height: int
    page: str
    status: str
    source: str


@dataclass(frozen=True)
class Command:
    name: str
    cpu: str
    address: int
    words: int
    word_bytes: int
    fire_word: int
    fire_value: int | None     # None: every write to the trigger fires
    asset: str
    fields: dict[str, Field]
    flags: dict[str, Field]
    planes: tuple[Plane, ...]
    provenance: dict[str, tuple[str, str]]     # `block` and `fire`: (status, source)
    fire_address: int | None = None            # a trigger outside the block

    @property
    def length(self) -> int:
        return self.words * self.word_bytes

    @property
    def trigger(self) -> int:
        if self.fire_address is not None:
            return self.fire_address
        return self.address + self.fire_word * self.word_bytes

    def named(self, name: str) -> Field:
        return self.fields.get(name) or self.flags[name]


@dataclass(frozen=True)
class Asset:
    name: str
    format: str
    tag: str
    offset: int
    palette: str
    pen_base: int
    wrap: bool
    status: str
    source: str


@dataclass(frozen=True)
class Format:
    name: str
    layout: ml.Layout
    status: str
    source: str


@dataclass(frozen=True)
class PalettePort:
    """The ports a palette's pens are written through, and the `protocol` whose law places each
    write on a pen (`ramdac`, `latch`, `sequence`: REFERENCE.md, under `palette_log`), as
    `mame_ramdac` logs them. The pen is `pen_base` plus the index, below `pen_count`."""

    name: str
    palette: str
    cpu: str
    index_port: int | None
    data_port: int
    order: tuple[str, ...]
    component_bits: int
    auto_increment: bool
    pen_base: int
    status: str
    source: str
    space: str = mspace.PROGRAM
    protocol: str = "ramdac"
    pen_count: int = RAMDAC_PENS
    components_bit_reversed: bool = False
    index_flag_mask: int | None = None

    def pens(self) -> range:
        return range(self.pen_base, self.pen_base + self.pen_count)

    def packed(self) -> bool:
        return self.protocol in PACKED

    def colour_mask(self) -> int:
        """The bits of a packed word that hold the colour: a pen has one once all are seen."""
        return (1 << 3 * self.component_bits) - 1


@dataclass(frozen=True)
class Manifest:
    path: str
    sha256: str
    systems: tuple[str, ...]
    formats: dict[str, Format]
    assets: dict[str, Asset]
    commands: dict[str, Command]
    palette_ports: dict[str, PalettePort] = dataclasses.field(default_factory=dict)
    draft: bool = False
    #: The section's old name when the file still spells it so, which `gfx_load`'s reply names.
    old_section: str | None = None

    def summary(self) -> dict[str, Any]:
        """What `gfx_load` answers: every name, and how much of it is proved."""
        counts = dict.fromkeys(STATUSES, 0)
        for status in _statuses(self):
            counts[status] += 1
        return {
            "path": self.path, "sha256": self.sha256, "draft": self.draft,
            "systems": list(self.systems),
            "formats": {n: f.status for n, f in self.formats.items()},
            "assets": {n: {"format": a.format, "tag": a.tag, "palette": a.palette}
                       for n, a in self.assets.items()},
            "commands": {n: {"block": st.hex_addr(c.address), "length": c.length,
                             "trigger_addr": st.hex_addr(c.trigger),
                             "fires_with": ("any write" if c.fire_value is None
                                            else f"{c.fire_value:#x}"),
                             "asset": c.asset or st.unavailable("the command names no asset"),
                             "roles": sorted(c.fields),
                             "flags": sorted(c.flags),
                             "planes": [p.name for p in c.planes]}
                         for n, c in self.commands.items()},
            "palette_ports": {n: {"palette": r.palette, "space": r.space, "protocol": r.protocol,
                            "index_port": (st.unavailable(NO_INDEX_PORT_WHY)
                                           if r.index_port is None
                                           else st.hex_addr(r.index_port)),
                            "data_port": st.hex_addr(r.data_port),
                            "index_flag_mask": _mask(r.index_flag_mask),
                            "order": "".join(r.order), "component_bits": r.component_bits,
                            "components_bit_reversed": r.components_bit_reversed,
                            "pen_range": [r.pens().start, r.pens().stop - 1]}
                        for n, r in self.palette_ports.items()},
            "status_counts": counts,
        }


#: A palette port's `index_port` when its protocol has none.
NO_INDEX_PORT_WHY = "this protocol takes no index port"


def _mask(value: int | None) -> str | dict[str, Any]:
    return (st.unavailable("only a latch's index word carries a flag") if value is None
            else f"{value:#x}")


def _statuses(man: Manifest) -> list[str]:
    out = [f.status for f in man.formats.values()] + [a.status for a in man.assets.values()]
    out += [r.status for r in man.palette_ports.values()]
    for cmd in man.commands.values():
        out += [s for s, _ in cmd.provenance.values()]
        out += [f.status for f in (*cmd.fields.values(), *cmd.flags.values())]
        out += [p.status for p in cmd.planes]
    return out


# ------------------------------------------------------------------ the checks, by shape

def _obj(raw: Any, path: str, required: tuple[str, ...], optional: tuple[str, ...] = ()
         ) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ManifestError(f"{path} is a mapping with {list(required + optional)}")
    unknown = [k for k in raw if k not in required + optional]
    if unknown:
        raise ManifestError(f"{path}.{unknown[0]}: an unknown key; {path} takes "
                            f"{list(required + optional)}")
    missing = [k for k in required if k not in raw]
    if missing:
        raise ManifestError(f"{path}: {missing[0]!r} is missing; {path} needs {list(required)}")
    return raw


def _int(raw: Any, path: str, lo: int | None = None, hi: int | None = None) -> int:
    # A manifest key's own error, naming its path in the file, not an argument's refusal.
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ManifestError(f"{path} is an integer; got {raw!r}")
    if (lo is not None and raw < lo) or (hi is not None and raw > hi):
        raise ManifestError(f"{path}={raw} is outside {lo}..{hi if hi is not None else ''}")
    return raw


def _str(raw: Any, path: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ManifestError(f"{path} is a non-empty string; got {raw!r}")
    return raw


def _bool(raw: Any, path: str) -> bool:
    if not isinstance(raw, bool):
        raise ManifestError(f"{path} is true or false; got {raw!r}")
    return raw


def _mapping(raw: Any, path: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ManifestError(f"{path} is a mapping of names")
    return raw


def _provenance(raw: dict[str, Any], path: str) -> tuple[str, str]:
    return _one_of(raw["status"], f"{path}.status", STATUSES), _str(raw["source"],
                                                                      f"{path}.source")


# ------------------------------------------------------------------ the sections

def _format(name: str, raw: Any, path: str) -> Format:
    obj = _obj(raw, path, ("layout", "status", "source"))
    try:
        lay = ml.parse_layout(obj["layout"], where=f"{path}.layout")
    except ml.LayoutError as e:
        raise ManifestError(str(e)) from None
    return Format(name, dataclasses.replace(lay, name=name), *_provenance(obj, path))


def _asset(name: str, raw: Any, path: str, formats: dict[str, Format]) -> Asset:
    obj = _obj(raw, path, ("format", "tag", "palette", "status", "source"),
               ("offset", "pen_base", "wrap"))
    fmt = _str(obj["format"], f"{path}.format")
    if fmt not in formats:
        raise ManifestError(f"{path}.format={fmt!r} names no format; the formats are "
                            f"{sorted(formats)}")
    return Asset(name, fmt, _str(obj["tag"], f"{path}.tag"),
                 _int(obj.get("offset", 0), f"{path}.offset", 0),
                 _str(obj["palette"], f"{path}.palette"),
                 _int(obj.get("pen_base", 0), f"{path}.pen_base", 0),
                 _bool(obj.get("wrap", False), f"{path}.wrap"), *_provenance(obj, path))


def _const(name: str, obj: dict[str, Any], path: str) -> Field:
    """A size the hardware fixes: `const` alone, no parts to read."""
    extra = sorted(set(obj) - {"const", "status", "source"})
    if extra:
        raise ManifestError(f"{path}.{extra[0]}: a `const` size reads no bits, so it takes no "
                            "`parts`, `add` or `sign`")
    return Field(name, (), _int(obj["const"], f"{path}.const", 1, 1 << 16), None,
                 *_provenance(obj, path))


def _field(name: str, raw: Any, path: str, words: int, word_bits: int, role: bool) -> Field:
    one_bit = role and name in ONE_BIT_ROLES
    size = role and name in SIZE_ROLES
    obj = _obj(raw, path, ("status", "source"),
               ("parts", "add", "asserted") if one_bit
               else ("parts", "add", "sign") + (("const",) if size else ()))
    if "const" in obj:
        return _const(name, obj, path)
    if "parts" not in obj:
        raise ManifestError(f"{path}: 'parts' is missing; a field reads bits of the block's words"
                            + (" (a size the hardware fixes is a `const`)" if size else ""))
    sign = _int(obj.get("sign", 1), f"{path}.sign")
    if sign not in (1, -1):
        raise ManifestError(f"{path}.sign={sign}: 1, or -1 for a value stored reversed")
    if one_bit and "asserted" not in obj:
        raise ManifestError(f"{path}: {'asserted'!r} is missing; a one-bit role says which value "
                            "(0 or 1) means it holds")
    raw_parts = obj["parts"]
    if not isinstance(raw_parts, list) or not raw_parts:
        raise ManifestError(f"{path}.parts is a list of one or more {{word, mask, at}}")
    parts: list[Part] = []
    taken: set[int] = set()
    seen: set[tuple[int, int]] = set()
    for i, rp in enumerate(raw_parts):
        where = f"{path}.parts[{i}]"
        po = _obj(rp, where, ("word", "mask"), ("at",))
        part = Part(_int(po["word"], f"{where}.word", 0, words - 1),
                    _int(po["mask"], f"{where}.mask", 1, (1 << word_bits) - 1),
                    _int(po.get("at", 0), f"{where}.at", 0, VALUE_BITS - 1))
        if part.at + part.bits > VALUE_BITS:
            raise ManifestError(f"{where} places bits up to bit {part.at + part.bits - 1} of the "
                                f"value, past the {VALUE_BITS} a coordinate or a flag holds")
        value_bits = set(range(part.at, part.at + part.bits))
        if value_bits & taken:
            raise ManifestError(f"{where} places bits of the value another part already holds")
        word_bits_used = {(part.word, k) for k in range(word_bits) if part.mask >> k & 1}
        if word_bits_used & seen:
            raise ManifestError(f"{where} reads a bit of word {part.word} another part reads")
        taken |= value_bits
        seen |= word_bits_used
        parts.append(part)
    field = Field(name, tuple(parts), _int(obj.get("add", 0), f"{path}.add"),
                  None, *_provenance(obj, path), sign=sign)
    if one_bit:
        if field.width != 1 or len(parts) != 1:
            raise ManifestError(f"{path} is a one-bit role, and its parts hold {field.width} bits")
        if field.add:
            raise ManifestError(f"{path}.add: a one-bit role is matched to `asserted`, not added "
                                "to")
        field = dataclasses.replace(field, asserted=_int(obj["asserted"], f"{path}.asserted",
                                                         0, 1))
    return field


def _origin(raw: Any, path: str, names: set[str]) -> Origin:
    if isinstance(raw, int) and not isinstance(raw, bool):
        return Origin(raw, "", 0)
    obj = _obj(raw, path, ("field",), ("scale", "add"))
    name = _str(obj["field"], f"{path}.field")
    if name not in names:
        raise ManifestError(f"{path}.field={name!r} names no field or flag of this command that "
                            f"holds a number (a one-bit role holds a truth); it has "
                            f"{sorted(names)}")
    return Origin(_int(obj.get("add", 0), f"{path}.add"), name,
                  _int(obj.get("scale", 1), f"{path}.scale"))


def _planes(raw: Any, path: str, fields: dict[str, Field], names: set[str]) -> tuple[Plane, ...]:
    if not isinstance(raw, list) or not raw:
        raise ManifestError(f"{path} is a list of one or more planes")
    planes: list[Plane] = []
    for i, rp in enumerate(raw):
        where = f"{path}[{i}]"
        obj = _obj(rp, where, ("name", "width", "height", "status", "source"),
                   ("when", "order", "origin_x", "origin_y", "page"))
        when = _int(obj["when"], f"{where}.when") if "when" in obj else None
        if when is not None and "plane" in fields:
            role = fields["plane"]
            # a role stored reversed (`sign: -1`) holds add - (2^width - 1)..add
            reach = role.sign * ((1 << role.width) - 1)
            low, high = role.add + min(0, reach), role.add + max(0, reach)
            if not low <= when <= high:
                raise ManifestError(f"{where}.when={when}: the `plane` role holds "
                                    f"{low}..{high}, so this plane could never be picked")
        if (when is None) == ("plane" in fields):
            raise ManifestError(f"{where}: " + (
                "`when` is the value of the `plane` role that picks this plane, and the command "
                "declares that role" if when is None else
                "`when` picks a plane by the `plane` role, which this command does not declare"))
        page = _str(obj["page"], f"{where}.page") if "page" in obj else ""
        if page and page not in names:
            raise ManifestError(f"{where}.page={page!r} names no field or flag of this command "
                                "that holds a number")
        planes.append(Plane(when, _str(obj["name"], f"{where}.name"),
                            _int(obj.get("order", 0), f"{where}.order"),
                            _origin(obj.get("origin_x", 0), f"{where}.origin_x", names),
                            _origin(obj.get("origin_y", 0), f"{where}.origin_y", names),
                            _int(obj["width"], f"{where}.width", 1, 1 << 16),
                            _int(obj["height"], f"{where}.height", 1, 1 << 16),
                            page, *_provenance(obj, where)))
    if "plane" not in fields and len(planes) != 1:
        raise ManifestError(f"{path}: several planes need the `plane` role to pick between them")
    whens = [p.when for p in planes]
    if len(set(whens)) != len(whens) or len({p.name for p in planes}) != len(planes):
        raise ManifestError(f"{path}: two planes share a `when` or a `name`")
    return tuple(planes)


def _command(name: str, raw: Any, path: str, assets: dict[str, Asset]) -> Command:
    obj = _obj(raw, path, ("block", "fire", "fields"), ("asset", "flags", "planes"))
    block = _obj(obj["block"], f"{path}.block", ("address", "words", "word_bytes", "status",
                                                 "source"), ("cpu",))
    word_bytes = _int(block["word_bytes"], f"{path}.block.word_bytes")
    if word_bytes not in WORD_BYTES:
        raise ManifestError(f"{path}.block.word_bytes={word_bytes}: one of {list(WORD_BYTES)}")
    words = _int(block["words"], f"{path}.block.words", 1)
    if words * word_bytes > watches.SHOW_WATCH_MAX:
        raise ManifestError(f"{path}.block is {prose.counted(words * word_bytes, 'byte')}, past "
                            f"the {watches.SHOW_WATCH_MAX} a capture holds")
    fire = _fire(obj["fire"], f"{path}.fire", words)
    word_bits = 8 * word_bytes
    fields_raw = _mapping(obj["fields"], f"{path}.fields")
    for role in fields_raw:
        if role not in ROLES:
            raise ManifestError(f"{path}.fields.{role}: not a role; the roles are {list(ROLES)}, "
                                "and anything else a project wants shown goes under `flags`")
    fields = {r: _field(r, v, f"{path}.fields.{r}", words, word_bits, True)
              for r, v in fields_raw.items()}
    flags = {f: _field(f, v, f"{path}.flags.{f}", words, word_bits, False)
             for f, v in _mapping(obj.get("flags", {}), f"{path}.flags").items()}
    both = sorted(set(fields) & set(flags))
    if both:
        raise ManifestError(f"{path}.flags.{both[0]}: a flag may not take a role's name")
    for need in ("dest_x", "dest_y"):
        if need not in fields:
            raise ManifestError(f"{path}.fields: the role {need!r} is missing; a box starts there")
    ends = {"dest_x_end", "dest_y_end"} & set(fields)
    sizes = {"width", "height"} & set(fields)
    if not ((len(ends) == 2) ^ (len(sizes) == 2)) or (ends and sizes):
        raise ManifestError(f"{path}.fields: the box's extent is `dest_x_end` and `dest_y_end` "
                            "(inclusive) or `width` and `height`, one pair and not both")
    asset = _str(obj["asset"], f"{path}.asset") if "asset" in obj else ""
    if asset and asset not in assets:
        raise ManifestError(f"{path}.asset={asset!r} names no asset; the assets are "
                            f"{sorted(assets)}")
    # what an origin or a page may read: a number, never a one-bit role's truth
    names = {n for n in fields if n not in ONE_BIT_ROLES} | set(flags)
    planes = (_planes(obj["planes"], f"{path}.planes", fields, names) if "planes" in obj else ())
    if "plane" in fields and not planes:
        raise ManifestError(f"{path}: the `plane` role picks among `planes`, and there are none")
    return Command(name, str(block.get("cpu", "")), _int(block["address"], f"{path}.block.address",
                                                         0),
                   words, word_bytes, fire.get("word", 0),
                   (_int(fire["value"], f"{path}.fire.value", 0, (1 << word_bits) - 1)
                    if "value" in fire else None), asset,
                   fields, flags, planes,
                   {"block": _provenance(block, f"{path}.block"),
                    "fire": _provenance(fire, f"{path}.fire")},
                   _int(fire["address"], f"{path}.fire.address", 0) if "address" in fire
                   else None)


def _fire(raw: Any, path: str, words: int) -> dict[str, Any]:
    """`fire`: a `word` of the block or an `address` outside it, and the `value` that fires, or
    none when every write does."""
    fire = _obj(raw, path, ("status", "source"), ("word", "address", "value"))
    if ("word" in fire) == ("address" in fire):
        raise ManifestError(f"{path}: `word` (the block's word a write fires on) or `address` (a "
                            "trigger outside the block), one of the two")
    if "word" in fire:
        _int(fire["word"], f"{path}.word", 0, words - 1)
        if "value" not in fire:
            raise ManifestError(f"{path}: 'value' is missing; a word of the block is written "
                                "with the values the command carries, so only one fires")
    return fire


def _one_of(raw: Any, path: str, allowed: tuple[str, ...]) -> str:
    if raw not in allowed:
        raise ManifestError(f"{path}={raw!r}: one of {list(allowed)}")
    return str(raw)


def _palette_port(name: str, raw: Any, path: str) -> PalettePort:
    obj = _obj(raw, path, ("palette", "data_port", "order", "component_bits", "auto_increment",
                           "status", "source"),
               ("cpu", "pen_base", "index_port", "space", "protocol", "pen_count",
                "components_bit_reversed", "index_flag_mask"))
    protocol = _one_of(obj.get("protocol", "ramdac"), f"{path}.protocol", PROTOCOLS)
    space = _one_of(obj.get("space", mspace.PROGRAM), f"{path}.space", mspace.SPACES)
    data_port = _int(obj["data_port"], f"{path}.data_port", 0)
    # A latch may take its index on the data port alone; the other two need a port of their own
    if "index_port" not in obj and protocol != "latch":
        raise ManifestError(f"{path}: protocol {protocol!r} needs `index_port`, the port its "
                            "index is written to" + (" (a write there sends the offset back to 0)"
                                                     if protocol == "sequence" else ""))
    index_port = _int(obj["index_port"], f"{path}.index_port", 0) if "index_port" in obj else None
    if index_port == data_port:
        raise ManifestError(f"{path}: the index port and the data port are one address; the "
                            "index is taken on one and the colour on the other (a latch with "
                            "no index port of its own leaves `index_port` out)")
    order = obj["order"]
    if not isinstance(order, list) or sorted(map(str, order)) != sorted(COMPONENTS):
        raise ManifestError(f"{path}.order={order!r}: the order the data port takes the "
                            f"components in, each of {list(COMPONENTS)} once")
    # a byte RAMDAC's count is the default; the packed protocols' indexes are their own
    pen_count = _int(obj.get("pen_count", RAMDAC_PENS), f"{path}.pen_count", 1, PEN_COUNT_MAX)
    if pen_count & (pen_count - 1):
        raise ManifestError(f"{path}.pen_count={pen_count}: a power of two, since the index "
                            "wraps at it")
    if protocol == "ramdac" and pen_count != RAMDAC_PENS:
        raise ManifestError(f"{path}.pen_count={pen_count}: a RAMDAC's index is a byte, so it "
                            f"names {RAMDAC_PENS} pens")
    reversed_ = _bool(obj.get("components_bit_reversed", False),
                      f"{path}.components_bit_reversed")
    if reversed_ and protocol not in PACKED:
        raise ManifestError(f"{path}.components_bit_reversed: only a packed colour (protocols "
                            f"{list(PACKED)}) is read bit-reversed; a RAMDAC takes each "
                            "component as written")
    flag = None
    if "index_flag_mask" in obj:
        if protocol != "latch":
            raise ManifestError(f"{path}.index_flag_mask: the flag of a latch's index word; "
                                f"protocol {protocol!r} has none")
        flag = _int(obj["index_flag_mask"], f"{path}.index_flag_mask", 1)
        colour = (1 << 3 * _int(obj["component_bits"], f"{path}.component_bits", 1, 8)) - 1
        if flag & colour:
            raise ManifestError(f"{path}.index_flag_mask={flag:#x} shares bits {flag & colour:#x} "
                                f"with the colour's {colour:#x}: a colour with them set would be "
                                "read as an index")
    elif protocol == "latch":
        raise ManifestError(f"{path}: a latch needs `index_flag_mask`, the bits that make a word "
                            "on its data port an index rather than a colour")
    return PalettePort(name, _str(obj["palette"], f"{path}.palette"),
                  _str(obj["cpu"], f"{path}.cpu") if "cpu" in obj else "",
                  index_port, data_port, tuple(order),
                  _int(obj["component_bits"], f"{path}.component_bits", 1, 8),
                  _bool(obj["auto_increment"], f"{path}.auto_increment"),
                  _int(obj.get("pen_base", 0), f"{path}.pen_base", 0), *_provenance(obj, path),
                  space, protocol, pen_count, reversed_, flag)


# THE PALETTE PORTS SECTION, and its old name read as an alias: a file that spells it the old
# way loads as written and the reply names the section to move to; one that spells both is
# refused, since two sections would be two answers to one question.
PALETTE_PORTS, PALETTE_PORTS_OLD = "palette_ports", "ramdacs"


def _palette_ports(raw: Any, section: str) -> dict[str, PalettePort]:
    """The `palette_ports` section, as the file spells it (`section`): two on one palette may not
    set the same pens, or a pen would have two logs and the question of who set it two
    answers."""
    out = {n: _palette_port(n, v, f"{section}.{n}") for n, v in _mapping(raw, section).items()}
    seen: list[PalettePort] = []
    for r in out.values():
        other = next((o for o in seen if st.bare_tag(o.palette) == st.bare_tag(r.palette)
                      and set(o.pens()) & set(r.pens())), None)
        if other is not None:
            raise ManifestError(f"{section}.{r.name}: its pens {r.pen_base}.."
                                f"{r.pens().stop - 1} of palette {r.palette!r} overlap "
                                f"those of {section}.{other.name}")
        seen.append(r)
    return out


def parse(raw: Any, path: str, sha256: str) -> Manifest:
    """A manifest from the document `raw`, judged whole."""
    top = _obj(raw, "gfx.yaml", ("schema", "systems"),
               ("formats", "assets", "commands", PALETTE_PORTS, PALETTE_PORTS_OLD))
    if PALETTE_PORTS in top and PALETTE_PORTS_OLD in top:
        raise ManifestError(f"`{PALETTE_PORTS}` and `{PALETTE_PORTS_OLD}` are one section under "
                            f"two names (`{PALETTE_PORTS_OLD}` is the old one): keep "
                            f"`{PALETTE_PORTS}` alone")
    section = PALETTE_PORTS_OLD if PALETTE_PORTS_OLD in top else PALETTE_PORTS
    if _int(top["schema"], "schema") != SCHEMA:
        raise ManifestError(f"schema={top['schema']!r}: this server reads schema {SCHEMA}")
    systems = top["systems"]
    if not isinstance(systems, list) or not systems:
        raise ManifestError("systems is a list of the MAME systems this manifest describes")
    formats = {n: _format(n, v, f"formats.{n}")
               for n, v in _mapping(top.get("formats", {}), "formats").items()}
    assets = {n: _asset(n, v, f"assets.{n}", formats)
              for n, v in _mapping(top.get("assets", {}), "assets").items()}
    commands = {n: _command(n, v, f"commands.{n}", assets)
                for n, v in _mapping(top.get("commands", {}), "commands").items()}
    return Manifest(path, sha256, tuple(_str(s, f"systems[{i}]") for i, s in enumerate(systems)),
                    formats, assets, commands, _palette_ports(top.get(section, {}), section),
                    old_section=PALETTE_PORTS_OLD if section == PALETTE_PORTS_OLD else None)


def read(path: str) -> Manifest:
    """The manifest at `path` (absolute, `check_gfx_load`), read and judged whole, as a refusal
    the reply contract knows. A refusal names the manifest that stays loaded, since a failed edit
    unloads nothing."""
    still = {"still_loaded": _still_loaded()}
    inputs.input_file("path", path, "manifest", **still)
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        raise files.unreadable("manifest", path, e, **still) from None
    try:
        text = data.decode("utf-8")
        man = parse(mame_yaml.loads(text), path, hashlib.sha256(data).hexdigest())
        return dataclasses.replace(man, draft=text.split("\n", 1)[0] == DRAFT_MARKER)
    except UnicodeDecodeError as e:
        raise files.not_utf8(path, e, **still) from None
    except (mame_yaml.YamlError, ManifestError) as e:
        raise st.Invalid("bad_argument", f"{path}: {e}; nothing was loaded from it",
                         **still) from None


# ------------------------------------------------------------------ the tool

def _still_loaded() -> str | dict[str, Any]:
    """The manifest a refusal leaves loaded, which every refusal names: a failed load unloads
    nothing."""
    return (STATE.manifest.path if STATE.manifest
            else st.unavailable("no manifest was loaded in this session"))


def check_gfx_load(path: str = "", **_: Any) -> None:
    """`gfx_load`'s machine-independent half: the path's shape. The file is read by the tool,
    which reads it before it asks for the session, so a bad file is refused as one either way."""
    inputs.absolute("path", path, still_loaded=_still_loaded())


def gfx_load(path: str) -> dict[str, Any]:
    """The body of the `gfx_load` tool: the manifest, for THIS board, held for the session."""
    check_gfx_load(path)
    man = read(path)
    st.refuse_broken(STATE.alive())
    if STATE.system not in man.systems:
        raise st.Invalid("bad_argument", f"{path} describes {list(man.systems)}, and this session "
                         f"runs {STATE.system!r}", systems=list(man.systems),
                         system=STATE.system,
                         still_loaded=_still_loaded())
    replaced = (STATE.manifest.path if STATE.manifest else
                st.unavailable("no manifest was loaded in this session before this one"))
    STATE.manifest = man
    old = ({"note": f"{path} spells its palette ports section `{PALETTE_PORTS_OLD}`, read as "
                    f"`{PALETTE_PORTS}`, the name to move it to"} if man.old_section else {})
    return menvelope.envelope({"loaded": True, "replaced_path": replaced, **man.summary(), **old})


def loaded() -> Manifest:
    """The manifest this session loaded, or the refusal that names `gfx_load`."""
    if STATE.manifest is None:
        raise st.Invalid("needs_call", "no manifest is loaded: `gfx_load` the project's "
                         "gfx.yaml first")
    return STATE.manifest


def command(name: str) -> Command:
    """The loaded manifest's command `name`, or the refusal naming the ones it has."""
    man = loaded()
    if name not in man.commands:
        raise st.Invalid("unknown_ref", f"draw command {name!r} is not in {man.path}; it has "
                         f"{sorted(man.commands)}", commands=sorted(man.commands))
    return man.commands[name]


def palette_port(name: str) -> PalettePort:
    """The loaded manifest's palette port `name`, or the refusal naming the ones it has."""
    man = loaded()
    if name not in man.palette_ports:
        raise st.Invalid("unknown_ref", f"palette_port={name!r} is not in {man.path}; it has "
                         f"{sorted(man.palette_ports)}", palette_ports=sorted(man.palette_ports))
    return man.palette_ports[name]


def layout_arg(raw: Any, where: str = "layout", resolve: bool = True) -> ml.Layout | None:
    """A tool's layout argument: a layout object as `gfx_view` takes one, or a STRING naming a
    format of the loaded manifest or a sweep's candidate (`named_layout`), which carries its
    name into the reply. Before the session
    gate (`resolve` false) a name is judged by its shape only and answers None: which formats
    exist is the loaded manifest's, which is the session's."""
    if not isinstance(raw, str):
        return ml.check_layout(raw, allow_name=True, where=where)
    if not raw or any(c.isspace() for c in raw):
        raise st.Invalid("bad_argument", f"{where}={raw!r}: a layout object, or the name of a "
                         "format of the loaded manifest or of a sweep's candidate (`s1c3`)")
    return named_layout(raw, where) if resolve else None


def named_layout(name: str, where: str = "layout") -> ml.Layout:
    """A layout named by a string: a format of the loaded manifest, else a candidate of this
    session's sweeps by its id (`s1c3`, `mame_evidence`), else the manifest's refusal."""
    man = STATE.manifest
    if (man is None or name not in man.formats) and evidence.SWEEP_ID.match(name):
        return evidence.candidate_layout(name, where)
    return format_layout(name, where)


def format_layout(name: str, where: str = "layout") -> ml.Layout:
    """The loaded manifest's format `name` as a layout, for a tool that takes one by name under
    the argument `where`."""
    man = loaded()
    if name not in man.formats:
        raise st.Invalid("unknown_ref", f"{where}={name!r} names no format of {man.path}; it has "
                         f"{sorted(man.formats)}", formats=sorted(man.formats))
    return man.formats[name].layout
