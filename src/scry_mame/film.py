"""`gfx_film`: the frames in which a condition held, kept inside MAME at emulation speed, and handed
back as a contact sheet, one PNG per frame (indexed when its pens fit a PLTE), a listing and an
animated PNG.

WHY INSIDE MAME. A breakpoint answers what the screen holds at ONE hit, and stopping at every hit
cannot follow a blitter that fires thousands of times a frame. So a write tap marks whether the
condition held (a write to a trigger, with a value, from a pc), a frame notifier judges the mark
at the frame's end, and only a frame that met it has its picture kept. Nothing crosses to this
server while the machine runs but the files.

WHICH FRAME A PICTURE IS, and why it is read one frame late. MAME finishes a frame's bitmap at the
start of vblank, hands it to the render texture and turns the screen's double buffer over
(`video_output_update`), all BEFORE the frame notifiers run; from a notifier, `screen:pixels()`
reads the buffer the next frame is drawn into, which still holds the frame before. So the notifier
at the end of frame N judges frame N's mark, saves the pens (the palette the display shows N with)
and, when N met the condition, reads N's bitmap at the NEXT notifier, after the next turn: read that
way the frame is MAME's own rendering of it (for a driver that draws its bitmap once a frame, as
the check below makes sure), where the read at N's own notifier is the frame before
on every frame whose picture changed. That lateness is the notifier's, and it is no evidence about
a read at a debugger stop, whose instant `docs/reference/screen.md` gives (*Which instant a
decode shows*). UNDER
FRAMESKIP the buffer turns only on a frame that drew (`screen_device::video_output_update`), and the
notifiers run before `update_frameskip`, so `skip_this_frame` at a notifier is that frame's own: a
met frame that was itself skipped drew nothing and is lost as `skipped` at once, and a pending
picture waits out the skipped frames after it and is read at the first one that drew, its file
counting how many it waited. A film frame is the span between two notifiers, named by the counter
the notifier at its end reads; each hit keeps the counter the tap read too, so a write in vblank is
not given to another frame, and a cell names the span of its listed hits' counters, which is what
joins it to a capture.

EVERY KEPT FRAME PROVES ITSELF. The indices come from the indexed screen's own chunk
(`lua/capture.lua`, verbatim), with its checks. Besides, at frame N's notifier the film
keeps `video:snapshot_pixels()`, MAME's rendering of the frame the display showed, and the kept
indices mapped through the pens saved then must equal it pixel for pixel, or the frame is
refused with its reason. A debugger redraw between the two notifiers, a driver that says it
drew nothing, and a driver that draws into the bitmap again before the read each break the lag's
law, and the check is what catches them. On circus the picture read at the next notifier is, on
some frames and on every frame skipping at level 6, no frame's rendering (nearest to the next
drawn frame's, and not equal to it), so a film of it on the bare screen refuses those frames
rather than keep a picture of no single frame. The check runs where the snapshot target renders
the bare screen, which arming measures; elsewhere every frame says it is unchecked, and
`mismatch` measures how the snapshot differs.

ITS LIFE is the session's, like the palette log's: it is not a stored declaration and a `start`
does not re-arm it, because a film spends a budget of frames and pictures from the frame it is
armed at, and a re-arm would spend it on the boot. The record, the install answer, the dump
reading and the removal are every tap's (`tap`), in a registry of this module's own.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scry_core import fresh, judges, png, prose
from scry_core import progress as mprogress
from scry_core import raster as core_raster
from scry_core import vocabulary as vocab
from scry_core.reply_contract import or_unavailable, unavailable

from scry_mame import callbacks, chunk, cpus, inputs, iotaps, lua_source, read, running, transport
from scry_mame import declarations as dec
from scry_mame import envelope as menvelope
from scry_mame import gdb_session as gs
from scry_mame import lua as mlua
from scry_mame import map as mmap
from scry_mame import mismatch as mmismatch
from scry_mame import screen as mscreen
from scry_mame import sheet as msheet
from scry_mame import space as mspace
from scry_mame import state as st
from scry_mame import tap as mtap
from scry_mame.state import STATE

REGISTRY = "MCP_FILM"
HEADER = "MCP_FILM"
FILM_ID = "film"
OWNER = "film"
LENGTHS = (1, 2, 4)
LENGTH_WHY = ": the bytes one write lands, inside one bus word"
FRAMES_DEFAULT, FRAMES_MAX = 600, 216_000     # ten seconds, and an hour, of a 60 Hz screen
KEEP_DEFAULT, KEEP_MAX = 12, 64
HITS_KEPT = 16             # the hits of one frame the listing names; the rest are counted
LOST_REASONS = ("reset", "load", "skipped")

_ARMED = re.compile(r"MCP_FILM_ARM snap_w=(\d+) snap_h=(\d+) data_width=(\d+) endianness=(\w+) "
                    r"refresh=([0-9.]+)")
_HEAD = re.compile(
    rf"^{HEADER} (\S+) seq=(\d+) frame=(-?\d+) judged=(\d+) met=(\d+) taken=(\d+) "
    r"dropped=(\d+) dropped_first=(-?\d+) dropped_last=(-?\d+) lost_reset=(\d+) lost_load=(\d+) "
    r"lost_skipped=(\d+) pending=(\d+) finished=(\d+) first=(-?\d+) last=(-?\d+) "
    r"judge_ticks=(\d+) picture_ticks=(\d+) tps=(\d+) baseline_frame=(-?\d+) "
    r"baseline_value=(-?\d+)$")
_FRAME = re.compile(r"^MCP_FILM_FRAME k=(\d+) frame=(\d+) hits=(\d+) read_at=(\d+) "
                    r"skipped=(\d+)$")
_HIT = re.compile(r"^h ([0-9a-f]+) ([0-9a-f]+) (-?\d+)$")


@dataclass(frozen=True)
class Film:
    """What a film was armed with, and what arming measured of the machine."""

    trigger: str
    trigger_addr: int
    length: int
    value: int | None
    pc: str
    pc_addr: int | None
    cpu: str | None
    frames: int
    keep: int
    crop: tuple[int, int, int, int] | None
    dir: Path
    screen: str
    width: int
    height: int
    refresh: float
    checked: bool
    check_why: str | None
    changed: bool = False          # a write meets the condition when its value differs
    space: str = "program"         # where the trigger is written: a port's is `io`
    mismatch: dict[str, Any] | None = None   # how the snapshot differs, when it does

    def shown(self, value: int) -> str:
        """A value at the trigger's width, as every reply of the film spells one: the written
        value, a hit's and the baseline."""
        return judges.hex_at_width(value, 8 * self.length)

    def fields(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "trigger": self.trigger, "trigger_addr": st.hex_addr(self.trigger_addr),
            "length": self.length,
            "value": (unavailable("no `value` was given") if self.value is None
                      else self.shown(self.value)),
            "changed": self.changed,
            "pc": self.pc or unavailable("no `pc` was given"),
            "pc_addr": (unavailable("no `pc` was given") if self.pc_addr is None
                        else st.hex_addr(self.pc_addr)),
            "cpu": self.cpu, "frames": self.frames, "keep": self.keep,
            "crop": list(self.crop) if self.crop else unavailable("no `crop`: the whole screen"),
            "film_dir": str(self.dir),
            "screen": self.screen, "checked": self.checked, "space": self.space}
        if self.check_why:
            out["why"] = self.check_why
        if self.mismatch is not None:
            out["mismatch"] = copy.deepcopy(self.mismatch)
        return out


@dataclass(frozen=True)
class Cell:
    """A kept frame as the reply and the sheet show it: `rgb` is its picture, cropped."""

    k: int
    frame: int
    hits: int
    listed_hits: tuple[tuple[int, int, int], ...]    # pc, value, the counter the tap read
    file: Path
    sha256: str
    indexed: bool
    rgb: bytes

    @property
    def first_hit(self) -> tuple[int, int, int] | None:
        return self.listed_hits[0] if self.listed_hits else None

    @property
    def hit_counters(self) -> list[int] | None:
        """The listed hits' lowest and highest counter, what joins the cell to a capture's rows
        and to `gfx_blits(frame=...)`; None when it lists no hit, never the cell's frame."""
        counters = [at for _pc, _val, at in self.listed_hits]
        return [min(counters), max(counters)] if counters else None


# ------------------------------------------------------------------ the arguments

def arms(trigger: str, clear: bool) -> bool:
    """Whether a call ARMS a film, the one gesture that needs a stopped machine: it reads the
    screen once. A read and a clear answer while it runs."""
    return bool(trigger.strip()) and not clear


def check_gfx_film(trigger: str = "", length: int = 1, value: int | None = None,
                   changed: bool = False, pc: str = "", cpu: str = "",
                   frames: int = FRAMES_DEFAULT, keep: int = KEEP_DEFAULT,
                   crop: list[int] | None = None, film_dir: str = "", first: int = 0,
                   clear: bool = False, seconds: float = mlua.EVAL_WAIT_S,
                   space: str = "program", **_: Any) -> Path | None:
    """`gfx_film`'s machine-independent half: which gesture the arguments make (arm with
    `trigger`, clear with `clear`, read with neither), the arguments that gesture takes and no
    other, and their shapes. Answers the `film_dir` an arming names."""
    vocab.check_wait(seconds)
    vocab.check_bool("clear", clear)
    vocab.check_bool("changed", changed)
    arming = {"length": length != 1, "value": value is not None, "changed": changed,
              "pc": bool(pc.strip()),
              "cpu": inputs.cpu_given(cpu), "frames": frames != FRAMES_DEFAULT,
              "keep": keep != KEEP_DEFAULT, "crop": crop is not None, "film_dir": bool(film_dir),
              "space": space != "program"}
    given = sorted(k for k, v in arming.items() if v)
    if clear and (trigger.strip() or given or first):
        extra = sorted([*given, *(["trigger"] if trigger.strip() else []),
                        *(["first"] if first else [])])
        raise st.Invalid("bad_argument", f"`clear` removes the film, so {extra} would do "
                         "nothing")
    if not trigger.strip():
        if given:
            raise st.Invalid("bad_argument", f"{given} choose what a film records, so they go "
                             "with `trigger`, which arms one; without it the call reads the "
                             "film already armed")
        inputs.natural("first", first, ": the first kept frame the sheet shows, counted from 0")
        return None
    if first:
        raise st.Invalid("bad_argument", "`first` pages a film being READ; an arming call has "
                         "nothing kept yet")
    if changed and value is not None:
        raise st.Invalid("bad_argument", "`changed` and `value` are two conditions on the value "
                         "a write lands: one names it, the other asks that it moved; give one")
    inputs.check_ref(trigger, "trigger")
    vocab.one_of("space", space, mspace.SPACES)
    if space == mspace.IO:
        mspace.port(trigger, "trigger")
    if pc.strip():
        inputs.check_ref(pc, "pc")
    vocab.one_of("length", length, LENGTHS, tail=LENGTH_WHY)
    if value is not None:
        top = (1 << (8 * length)) - 1
        inputs.natural("value", value, ": what the write lands on the "
                       f"{prose.counted(length, 'trigger byte')}, 0..{top:#x}", hi=top)
    for name, got, most in (("frames", frames, FRAMES_MAX), ("keep", keep, KEEP_MAX)):
        inputs.count(name, got, most)
    if crop is not None and not inputs.is_rectangle(crop):
        raise st.Invalid("bad_argument", f"crop={crop!r} is [x, y, width, height] with a width "
                         "and a height above zero")
    return inputs.fresh_folder("film_dir", film_dir) if film_dir else None


# ------------------------------------------------------------------ arming

def held() -> tuple[dec.Owner, dict[str, Any]] | None:
    """The film's record, whatever cpu it was armed on."""
    return mtap.held(OWNER)




def arm(ses: gs.Session, scratch: Path, trigger: str, length: int, value: int | None,
        changed: bool, pc: str, cpu: str, frames: int, keep: int, crop: list[int] | None,
        dest_path: Path | None, seconds: float, progress: mprogress.Progress,
        space: str = "program") -> dict[str, Any]:
    """Arm the film: resolve the trigger and the writer, ask the trigger's write side, read the
    screen once (the indexed capture's checks, and whether MAME's snapshot is the bare screen),
    then send the install, which runs when the console next reads a line."""
    found = held()
    if found is not None:
        raise st.Invalid("bad_argument", "a film is already armed (on "
                         f"{found[1]['film'].trigger!r}), one per session: "
                         "`gfx_film(clear=True)` removes it, and its files stay")
    on = cpus.chosen(ses, cpu)
    if space == mspace.IO:
        iotaps.check_has_io(on)
    trig = (mspace.port(trigger, "trigger") if space == mspace.IO
            else STATE.resolve_named("trigger", trigger, on))
    pc_addr = STATE.resolve_named("pc", pc, on) if pc.strip() else None
    refused, maps_to, trig_read = mmap.write_side(ses, trig, on, space)
    if refused is not None:
        code, why = refused
        raise st.Invalid(code, f"the trigger: {why}")
    path = chunk.next_file(scratch, "screen")
    snap_path = path.with_name(path.stem + "-snap.bin")
    script = mscreen.capture_lua() + lua_source.render(
        "film-arm", call=lua_source.Code(mscreen.capture_call(path, True)), snap=str(snap_path),
        cpu=lua_source.Code(f"manager.machine.devices[{transport.lua_string(on)}]" if on
                            else "manager.machine.debugger.visible_cpu"), space=space)
    try:
        text, common = chunk.run(ses, scratch, script, seconds, progress, "film")
        cap = mscreen.captured(text, path, common)
        m = _ARMED.search(text)
        if m is None:
            chunk.no_line("film", text, common)
        snap = snap_path.read_bytes() if snap_path.is_file() else b""
    finally:
        path.unlink(missing_ok=True)
        snap_path.unlink(missing_ok=True)
    snap_w, snap_h = int(m.group(1)), int(m.group(2))
    if len(snap) != 4 * snap_w * snap_h:
        raise st.Invalid("unexpected_answer", "MAME's snapshot file holds "
                                              f"{prose.counted(len(snap), 'byte')}, "
                         f"and the {snap_w}x{snap_h} snapshot it declared is "
                         f"{4 * snap_w * snap_h}", **common)
    if mspace.crosses(trig, length, int(m.group(3))):
        raise st.Invalid("bad_argument", f"{prose.counted(length, 'byte')} at {trig:#x} cross a "
                         f"bus word of {prose.counted(int(m.group(3)) // 8, 'byte')}: a trigger is "
                         "written by one bus write",
                         **common)
    if crop is not None:
        mscreen.inside(cap, crop[0], crop[1], crop[2], crop[3], "crop", common)
    mismatch = mmismatch.measure(cap, snap, snap_w, snap_h)
    where = fresh.directory(dest_path, scratch, lambda number: f"film-{number}", "the film")
    # MADE BEFORE THE INSTALL NAMES IT, and taken away again if the install is refused, so a
    # refused arming leaves nothing behind
    with fresh.taken_back(where):
        film = Film(trigger.strip(), trig, length, value, pc.strip(), pc_addr, on, frames, keep,
                    (crop[0], crop[1], crop[2], crop[3]) if crop else None,
                    where, cap.tag, cap.width, cap.height,
                    float(m.group(5)), mismatch is None, mmismatch.why(mismatch), changed, space,
                    mismatch)
        owner: dec.Owner = (OWNER, on)
        head = film.dir / "film.txt"
        # THE FILM'S FILES ARE NOT THE TAP'S: they stay when it is removed, as the tool says,
        # and a later film writes to a directory of its own, so none of them can be read as
        # its numbers
        sent = mtap.send_tap(scratch, owner, FILM_ID,
                             install_script(film, head), REGISTRY,
                             [], addr=trig, width=length, path=head, film=film, cells={},
                             refused={}, anim_kept=-1)
    # THE INSTALL'S OWN ACCOUNT under names of its own: the chunk's account (`call`,
    # `lines_ahead`) rides beside it in the same reply
    fields = {"armed_now": True, "film": film.fields(), "trigger_maps_to": maps_to,
              "tally_id": sent["tally_id"], "installed": sent["installed"],
              "pending": sent["pending"],
              "install_call": sent["call"], "install_lines_ahead": sent["lines_ahead"],
              "note": ("the film judges from the first whole frame after the install, which "
                       "runs when the console next reads a line; read it with `gfx_film()`")}
    fields["note"] = mmap.with_unmapped_note(str(fields["note"]), maps_to, trig, space,
                                             trig_read, trigger=True)
    return running.stop_reply(ses, scratch, f"gfx_film: {common['evaluated_by']}",
                              **st.merged(fields, common))


# ------------------------------------------------------------------ the tap and the notifier

_DUMP_OWN_FRAME = lua_source.render("film-dump-own-frame")


def install_script(film: Film, head: Path) -> str:
    """The Lua that installs the film: the write tap marking the frame, the frame notifier that
    judges it and reads a met frame's picture at the next notifier, the reset and load notifiers
    that drop what spans them, and the dumper. The indexed capture is the screen tool's own
    function, its `print` kept for the frame's file. Installing the same film again carries its
    counts across, as every tap here does, because the console reruns a chunk now and then; a
    film with another header is another film, and starts from nothing even if the removal of the
    one before never ran."""
    code = lua_source.Code
    cpu = (f"manager.machine.devices[{transport.lua_string(film.cpu)}]" if film.cpu else
           'manager.machine.debugger.visible_cpu or manager.machine.devices[":maincpu"]')
    return mtap.tap_prelude(REGISTRY) + lua_source.render(
        "film-install", id=FILM_ID, cpu=code(cpu), space=film.space, screen=film.screen,
        dir=str(film.dir), trig=code(f"{film.trigger_addr:#x}"), len=film.length,
        want=code("nil" if film.value is None else f"{film.value:#x}"),
        wpc=code("nil" if film.pc_addr is None else f"{film.pc_addr:#x}"),
        frames_max=film.frames, keep=film.keep, changed=film.changed, checkable=film.checked,
        remove_old=code(mtap.REMOVE_OLD_TAP), head=str(head), no_frame=callbacks.NO_FRAME,
        capture=code(mscreen.capture_lua()), header=HEADER, hits_kept=HITS_KEPT,
        pens=code(mscreen.FRAME_PENS_LUA),
        dumper=code(mtap.register_dumper_once(_DUMP_OWN_FRAME)),
        answer=mtap.ANSWER_PREFIX).rstrip("\n")


# ------------------------------------------------------------------ what the film wrote

def parse_film_header(text: str) -> dict[str, Any] | None:
    """The film's header as the dumper wrote it, or None when it is not a whole one. `total` is
    the frames judged, the number `tap.read_tap` reports a tap by."""
    whole = callbacks.read_whole(text, _HEAD, with_body=False)
    if whole is None:
        return None
    m, _, errors = whole
    names = ("id", "seq", "frame", "judged", "met", "taken", "dropped", "dropped_first",
             "dropped_last", "lost_reset", "lost_load", "lost_skipped", "pending", "finished",
             "first", "last", "judge_ticks", "picture_ticks", "tps", "baseline_frame",
             "baseline_value")
    out: dict[str, Any] = {k: (g if k == "id" else int(g))
                           for k, g in zip(names, m.groups(), strict=True)}
    out.update(errors)
    out["total"] = out["judged"]
    return out


@dataclass(frozen=True)
class FrameMeta:
    k: int
    frame: int
    hits: int
    read_at: int
    skipped: int               # the frames the picture waited out, skipped, before it was read
    listed: tuple[tuple[int, int, int], ...]
    said: str


def parse_frame(text: str) -> FrameMeta | None:
    """A kept frame's own file, or None when it is not a whole one."""
    lines = text.splitlines()
    if len(lines) < 3 or lines[-1] != "end" or not lines[-2].startswith("said "):
        return None
    m = _FRAME.match(lines[0])
    if m is None:
        return None
    listed = []
    for ln in lines[1:-2]:
        h = _HIT.match(ln)
        if h is None:
            return None
        listed.append((int(h.group(1), 16), int(h.group(2), 16), int(h.group(3))))
    return FrameMeta(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)),
                     int(m.group(5)), tuple(listed), lines[-2][len("said "):])


def convert(film: Film, base: Path) -> Cell:
    """The kept frame whose files start at `base` (`frame-K`) as its PNG, checked, its raw files
    gone after; a check that fails raises `st.Invalid` naming it, and no PNG is written."""
    try:
        meta = parse_frame(base.with_suffix(".txt").read_text(encoding="utf-8",
                                                               errors="replace"))
        if meta is None:
            raise st.Invalid("unexpected_answer", f"{base.name}.txt is not a whole frame file")
        if meta.said.startswith("MCP_FILM_ERROR"):
            raise st.Invalid("unexpected_answer", f"the capture raised: {meta.said[15:]}")
        mscreen.check_read_on_time(meta.frame, meta.read_at, meta.skipped)
        cap = mscreen.captured(meta.said, base.with_suffix(".bin"), {})
        mscreen.check_same_size(cap, meta.frame, film.width, film.height, "film")
        pens = list(array("I", base.with_suffix(".pens").read_bytes()))
        if cap.indices is not None and len(pens) != len(cap.pens):
            raise st.Invalid("unexpected_answer", f"{prose.counted(len(pens), 'pen')} "
                             f"{prose.agrees(len(pens), 'was', 'were')} saved "
                             f"at frame {meta.frame} and the screen has {len(cap.pens)}")
        if film.checked:
            _against_snapshot(cap, pens, base.with_suffix(".snap").read_bytes(), meta.frame,
                              meta.read_at)
        return _cell(film, meta, cap, pens, base)
    finally:
        for suffix in (".bin", ".pens", ".snap", ".txt"):
            base.with_suffix(suffix).unlink(missing_ok=True)


def _against_snapshot(cap: mscreen.Capture, pens: list[int], snap: bytes, frame: int,
                      read_at: int) -> None:
    """The kept picture, read at frame `read_at`, in the colours of the frame's own pens, against
    MAME's rendering of that frame, pixel for pixel."""
    if len(snap) != 4 * cap.width * cap.height:
        raise st.Invalid("readback_refused", f"frame {frame} has no snapshot of the screen's size "
                         f"({prose.counted(len(snap), 'byte')}) to be checked against")
    if cap.indices is None:
        shown = [c & mmismatch.RGB for c in cap.colours]
    else:
        lut = [p & mmismatch.RGB for p in pens]
        shown = [lut[i] for i in cap.indices]
    apart = len(mmismatch.differing(shown, mmismatch.colours(snap)))
    if apart:
        raise st.Invalid("readback_refused", f"frame {frame}'s picture, read at frame {read_at}, "
                         f"differs from MAME's rendering of frame {frame} on "
                         f"{prose.counted(apart, 'pixel')}: the bitmap read then is not the one "
                         "the display showed for that frame (one of: the driver drew into it "
                         "again before it was read, a debugger redraw came between the two "
                         "notifiers, or the driver drew nothing)")


def _cell(film: Film, meta: FrameMeta, cap: mscreen.Capture, pens: list[int],
          base: Path) -> Cell:
    x, y, w, h = film.crop or (0, 0, cap.width, cap.height)
    if cap.indices is None:
        raster = mscreen.colour_crop(cap, x, y, w, h)
    else:
        own = mscreen.Capture(cap.tag, cap.width, cap.height, meta.frame, cap.palette,
                              cap.colours, cap.indices, pens)
        raster = mscreen.raster(own, own.window(x, y, w, h), x, y, w, h, None)
    data = png.encode(raster)
    target = base.with_suffix(".png")
    target.write_bytes(data)
    STATE.record_image(target)
    return Cell(meta.k, meta.frame, meta.hits, meta.listed, target,
                hashlib.sha256(data).hexdigest(), raster.palette is not None,
                core_raster.rgb(raster))


# ------------------------------------------------------------------ the sheet and the animation

def labels(cell: Cell, film: Film) -> tuple[str, str]:
    """A cell's two label lines: its frame and how many writes met the condition in it, then the
    first of them, its pc and the value it landed."""
    if cell.first_hit is None:
        return (f"FRAME {cell.frame}  HITS {cell.hits}", "")
    pc, val, _at = cell.first_hit
    return (f"FRAME {cell.frame}  HITS {cell.hits}",
            f"PC {pc:X}  ={val:0{film.length * 2}X}")


def picture_size(film: Film) -> tuple[int, int]:
    """A kept picture's width and height: the crop's, else the screen's."""
    return (film.crop[2], film.crop[3]) if film.crop else (film.width, film.height)


def sheet_layout(film: Film, cells: list[Cell]) -> msheet.Layout:
    """The layout every page of the film's sheet shares, its cells as wide as the widest label of
    every kept frame."""
    return msheet.layout(picture_size(film), [labels(c, film) for c in cells])


def animation(film: Film, cells: list[Cell]) -> dict[str, Any]:
    """Every kept frame as an APNG, one frame of the screen each, written beside the frames and
    never attached: the model sees a still, a person plays it."""
    pw, ph = picture_size(film)
    rate = round(film.refresh * 1000)
    delay = (1000, rate) if 0 < rate <= 0xFFFF else (1, max(round(film.refresh), 1))
    data = png.encode_animation([png.Raster(pw, ph, c.rgb) for c in cells], delay)
    target = film.dir / "film-anim.png"
    target.write_bytes(data)
    return {"path": str(target), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "frames": len(cells), "frame_period_s": st.measured_s(delay[0] / delay[1])}


# ------------------------------------------------------------------ reading and clearing

def _hit(pc: int, val: int, at: int, film: Film, cpu: str | None) -> dict[str, Any]:
    return read.add_symbol({"pc": st.hex_addr(pc), "value": film.shown(val), "counter": at},
                           pc, cpu)


#: A kept frame's first hit's `pc` and `value` when it lists none.
NO_HIT_WHY = "the frame lists no hit"


def _cell_fields(cell: Cell, film: Film) -> dict[str, Any]:
    nothing = unavailable(NO_HIT_WHY)
    first: dict[str, Any] = {"pc": nothing, "value": nothing}
    if cell.first_hit is not None:
        first = {k: v for k, v in _hit(*cell.first_hit, film, film.cpu).items()
                 if k != "counter"}
    return {"k": cell.k, "frame": cell.frame, "hits_in_frame": cell.hits,
            "hit_counters": or_unavailable(cell.hit_counters, NO_HIT_WHY), **first,
            "path": str(cell.file)}


def _collect(rec: dict[str, Any], film: Film, taken: int) -> None:
    """Convert every kept frame the film wrote since the last read."""
    cells: dict[int, Cell] = rec["cells"]
    refused: dict[int, dict[str, Any]] = rec["refused"]
    for k in range(1, taken + 1):
        base = film.dir / f"frame-{k}"
        if k in cells or k in refused or not base.with_suffix(".txt").is_file():
            continue
        try:
            cells[k] = convert(film, base)
        except (st.Invalid, OSError, ValueError) as e:
            refused[k] = {"k": k, "code": getattr(e, "code", "unexpected_answer"),
                          "why": str(e)}


def _listing(rec: dict[str, Any], film: Film, head: dict[str, Any]) -> Path:
    """`film.json`: the film, every kept frame with its file and hits, the refused ones."""
    cells: dict[int, Cell] = rec["cells"]
    doc = {"film": film.fields(), "judged": head["judged"], "met": head["met"],
           "frames": [{"k": c.k, "frame": c.frame, "hit_counters": c.hit_counters,
                       "file": c.file.name, "sha256": c.sha256,
                       "indexed": c.indexed, "checked": film.checked, "hits_in_frame": c.hits,
                       "listed_hits": [_hit(*h, film, film.cpu) for h in c.listed_hits]}
                      for c in sorted(cells.values(), key=lambda c: c.k)],
           "refused": [rec["refused"][k] for k in sorted(rec["refused"])]}
    target = film.dir / "film.json"
    target.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return target


def _counts(head: dict[str, Any], rec: dict[str, Any]) -> dict[str, Any]:
    tps = head["tps"] or 1
    out: dict[str, Any] = {
        "state": "finished" if head["finished"] else "judging",
        "judged": head["judged"],
        "judged_frames": ([head["first"], head["last"]] if head["judged"]
                          else unavailable("no frame was judged yet")),
        "met": head["met"], "kept": len(rec["cells"]), "refused": len(rec["refused"]),
        "dropped_total": head["dropped"],
        # the first and last frame dropped, as `judged_frames` spans the judged ones
        "dropped_frames": ([head["dropped_first"], head["dropped_last"]] if head["dropped"]
                           else unavailable("no frame was dropped")),
        "lost": {r: head[f"lost_{r}"] for r in LOST_REASONS if head[f"lost_{r}"]},
        "pending_picture": bool(head["pending"]),
        "cost": {"judge_s_per_frame": st.measured_s(head["judge_ticks"] / tps
                                                    / max(head["judged"], 1)),
                 "picture_s_per_frame": st.measured_s(head["picture_ticks"] / tps
                                                      / max(head["taken"], 1)),
                 "measured_by": "osd_ticks inside the frame notifier; the tap's cost per write "
                                "is not in it"}}
    return out


def _baseline(head: dict[str, Any], film: Film) -> dict[str, Any]:
    """Where a `changed` film's comparison started: its first write, which met nothing; both
    null before any write."""
    if head["baseline_frame"] < 0:
        before = unavailable("no write has landed yet, so there is no baseline")
        return {"frame_baseline": before, "baseline_value": before}
    return {"frame_baseline": head["baseline_frame"],
            "baseline_value": film.shown(head["baseline_value"])}


def read_film(scratch: Path, first: int) -> dict[str, Any]:
    """The film as it stands: its counts, the page of kept frames from `first` as a contact sheet,
    the listing and the animation."""
    found = held()
    if found is None:
        raise st.Invalid("needs_call", "no film is armed in this session: "
                         "`gfx_film(trigger=...)` arms one")
    owner, rec = found
    film: Film = rec["film"]
    item, head = mtap.read_tap(scratch, owner, st.stopped_frame(), False, parse_film_header,
                               "filmed")
    item.pop("addr", None)
    item.pop("total", None)
    fields: dict[str, Any] = {"film": film.fields(), **item}
    if head is None:
        return menvelope.envelope(fields)
    _collect(rec, film, head["taken"])
    fields.update(_counts(head, rec))
    if film.changed:
        fields.update(_baseline(head, film))
    fields["listing_path"] = str(_listing(rec, film, head))
    cells = sorted(rec["cells"].values(), key=lambda c: c.k)
    if rec["refused"]:
        fields["refused_frames"] = [rec["refused"][k] for k in sorted(rec["refused"])]
    if not cells:
        if first:
            raise st.Invalid("bad_argument", f"first={first}: the film has kept no frame")
        raised = callbacks.said(callbacks.reply(head), "the film's")
        tail = f"; but {raised}, so frames that met it may not have been marked" if raised else ""
        if head["judged"]:
            fields["nothing_kept"] = (
                f"no picture kept: {head['met']} of the {prose.counted(head['judged'], 'frame')} "
                f"judged ({head['first']}..{head['last']}) met the condition"
                + ("" if head["finished"] else ", and the film is still judging") + tail)
        elif raised:
            # a notifier that raises before it judges leaves no frame judged at all
            fields["nothing_kept"] = f"no picture kept and no frame judged{tail}"
        return menvelope.envelope(fields)
    if first >= len(cells):
        raise st.Invalid("bad_argument",
                         f"first={first} is past the {prose.counted(len(cells), 'kept frame')}")
    lay = sheet_layout(film, cells)
    cols, rows = msheet.page_shape(lay, len(cells) - first)
    page = cells[first:first + cols * rows]
    fields["cells"] = [_cell_fields(c, film) for c in page]
    fields["listed"] = {"first": first, "count": len(page), "of": len(cells)}
    if first + len(page) < len(cells):
        fields["next_first"] = first + len(page)
    # THE SHEET IS THE FILM'S OWN and is drawn again on every read, as the frames it lists grow,
    # so the one before is taken away first: the exclusive write refuses a file already there.
    composed = msheet.compose(lay, [(labels(c, film), c.rgb) for c in page])
    sheet = film.dir / f"sheet-{first}.png"
    sheet.unlink(missing_ok=True)
    fields["image"] = st.publish(composed, 0, sheet, scratch, "sheet")
    if rec["anim_kept"] != len(cells):
        rec["animation"] = animation(film, cells)
        rec["anim_kept"] = len(cells)
    fields["animation"] = rec["animation"]
    return menvelope.envelope(fields)


def clear_film(scratch: Path) -> dict[str, Any]:
    """Remove the film's tap and notifiers; its files stay where they were written."""
    found = held()
    if found is None:
        return menvelope.envelope({"cleared": False, "note": "no film was armed in this session"})
    owner, rec = found
    film: Film = rec["film"]
    removed = mtap.send_remove(scratch, owner)
    return menvelope.envelope({"cleared": True, "film": film.fields(), **(removed or {}),
                               "files_kept": str(film.dir)})


def gfx_film(ses: gs.Session, scratch: Path, trigger: str, length: int, value: int | None,
             changed: bool, pc: str, cpu: str, frames: int, keep: int,
             crop: list[int] | None, film_dir: str, first: int, clear: bool, seconds: float,
             progress: mprogress.Progress = mprogress.no_progress,
             space: str = "program") -> dict[str, Any]:
    """The body of the `gfx_film` tool: arm, read or clear, as the arguments say."""
    dest_path = check_gfx_film(trigger, length, value, changed, pc, cpu, frames, keep, crop,
                               film_dir, first, clear, seconds, space)
    if clear:
        return clear_film(scratch)
    if not trigger.strip():
        return read_film(scratch, first)
    return arm(ses, scratch, trigger, length, value, changed, pc, cpu, frames, keep, crop,
               dest_path, seconds, progress, space)
