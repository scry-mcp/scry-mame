"""`series_capture`: frames of the screen kept inside MAME at emulation speed, by a frame notifier,
and written as a `scry-series/1` series (`scry_core.series`): PNGs and one manifest, no picture in
the reply.

WHICH FRAME A PICTURE IS, and in which colours. The notifier at the end of frame N reads the
counter N, but `screen:pixels()` there reads the buffer the next frame is drawn into, which still
holds frame N - 1 (`film` says why). So a wanted frame is marked at its own
notifier, its pens saved there (the palette the display shows N with), and its bitmap read at the
next notifier that drew, as the film reads its frames: indices then, mapped through the pens saved
at N, so a palette that moves during N + 1 does not repaint N. What the series calls frame N is
MAME's own rendering of N, numbered by the counter `run_for(frames=...)` counts, and each frame's
file says when it was read, which is checked. A wanted frame that was itself skipped (frameskip)
drew nothing and is listed `lost`, never filled in; one that came out of the run neither kept nor
lost is refused by number.

THE RUN is `run_for` by frames, to `RUN_TAIL` past the last frame, so its notifier develops it;
the machine stops there, and the reply carries that stop. The notifier only reads (the pen
encoding of the capture is put back and proven inside its chunk), so the run alters nothing; it
is removed before the reply on every path where the machine is known to be stopped.
"""

from __future__ import annotations

import contextlib
import re
from array import array
from pathlib import Path
from typing import Any

from scry_core import fresh, judges, png, raster, series
from scry_core import progress as mprogress
from scry_core import reply_contract as contract
from scry_core import vocabulary as vocab
from scry_core.prose import counted

from scry_mame import advance, chunk, inputs, read, transport
from scry_mame import gdb_session as gs
from scry_mame import palette as mpalette
from scry_mame import screen as mscreen
from scry_mame import state as st
from scry_mame.state import STATE

#: The run's frames past the last one asked: one for its notifier to read it at, one more for a
#: stop that landed inside the frame the run began in.
RUN_TAIL = 2
#: What a series' frame numbers count here: the emulated frame counter `run_for` counts.
FRAME_SOURCE = "frame_number"
#: The run's wall-clock bound by default: a series runs the machine, as `run_for` does.
SECONDS_DEFAULT = 60.0
_ARMED = re.compile(r"MCP_SERIES_ARMED frame=(\d+) w=(\d+) h=(\d+)")
_NO_SCREEN = "MCP_SERIES_NO_SCREEN"
_DONE = re.compile(r"MCP_SERIES_DONE kept=(\d+) lost=(\S*) errors=(\d+) first_error=(.*)$",
                   re.MULTILINE)
_FRAME = re.compile(r"frame=(\d+) read_at=(\d+) skipped=(\d+)\n")
_ERROR = "MCP_SERIES_ERROR "
#: The console's channel takes a chunk this long at most, and the frame list rides in it.
CONSOLE_CHARS = transport.SCRIPT_MAX
#: The text of the console's accounts a reply that read chunks carries.
CONSOLE_ACCOUNT = ("thread_errors", "console_reruns", "resent")


def check_series_capture(at_frames: list[int] | None = None, first: int | None = None,
                         last: int | None = None, step: int = 1, crop: list[int] | None = None,
                         dest: str = "", seconds: float = SECONDS_DEFAULT, **_: Any) -> None:
    """`series_capture`'s machine-independent half: the frames, the crop's shape, the bound and
    a `dest` that is a new directory."""
    series.frame_list(at_frames, first, last, step)
    if crop is not None:
        judges.rect("crop", crop)
    vocab.check_wait(seconds)
    if dest:
        inputs.fresh_folder("dest", dest)


ARM_LUA = """MCP_SERIES = MCP_SERIES or {}
if MCP_SERIES.sub ~= nil then MCP_SERIES.sub:unsubscribe() MCP_SERIES.sub = nil end
MCP_SERIES = nil
local dir = %(dir)s
local wanted, last = {}, %(last)d
%(wanted)s
local v = manager.machine.video
local scr = nil
for _, s in pairs(manager.machine.screens) do scr = s break end
if scr == nil then print("MCP_SERIES_NO_SCREEN") return end
local t = {pend = nil, kept = 0, lost = {}, done = false, errors = 0, first_error = ""}
local said = ""
local print = function(s) said = s end
%(capture)s
local function put(path, data)
  local f = assert(io.open(path, "wb"))
  f:write(data) f:close()
end
%(pens)s
t.sub = emu.add_machine_frame_notifier(function()
  if t.done then return end
  local ok, err = pcall(function()
    local fr = scr:frame_number()
    local drew = not v.skip_this_frame
    if t.pend ~= nil then
      if drew then
        said = ""
        local base = dir .. "/raw-" .. t.pend.frame
        local got, why = pcall(mcp_capture, base .. ".bin", true)
        if not got then said = "MCP_SERIES_ERROR " .. tostring(why) end
        put(base .. ".pens", t.pend.pens)
        put(base .. ".txt", string.format("frame=%%d read_at=%%d skipped=%%d\\n", t.pend.frame,
          fr, t.pend.skipped) .. said)
        t.kept, t.pend = t.kept + 1, nil
      else
        t.pend.skipped = t.pend.skipped + 1
      end
    end
    if wanted[fr] then
      if drew then t.pend = {frame = fr, pens = pens(), skipped = 0}
      else t.lost[#t.lost + 1] = tostring(fr) end
    end
    if fr >= last and t.pend == nil then t.done = true end
  end)
  if not ok then
    t.errors = t.errors + 1
    if t.first_error == "" then t.first_error = tostring(err) end
  end
end)
MCP_SERIES = t
_G.print(string.format("MCP_SERIES_ARMED frame=%%d w=%%d h=%%d", scr:frame_number(), scr.width,
  scr.height))"""

FINISH_LUA = """local t = MCP_SERIES or {}
if t.sub ~= nil then t.sub:unsubscribe() t.sub = nil end
MCP_SERIES = nil
print(string.format("MCP_SERIES_DONE kept=%d lost=%s errors=%d first_error=%s", t.kept or 0,
  table.concat(t.lost or {}, ","), t.errors or 0, (t.first_error or ""):gsub("\\n", " ")))"""


def wanted_lua(at_frames: list[int] | None, first: int | None, last: int | None,
               step: int) -> str:
    """The Lua that fills `wanted`: a loop for a range, so a thousand frames cost one line, and
    the list itself otherwise."""
    if at_frames is None:
        return f"for f = {first}, {last}, {step} do wanted[f] = true end"
    return ("for _, f in ipairs({" + ",".join(map(str, at_frames)) + "}) do wanted[f] = true end")


def arm_script(folder: Path, at_frames: list[int] | None, first: int | None, last: int | None,
               step: int, wanted: list[int]) -> str:
    """The arming chunk, refused before it is sent when the frame list would not fit in one
    console line, which only a long `at_frames` list can do."""
    script = ARM_LUA % {"dir": transport.lua_string(str(folder)), "last": wanted[-1],
                        "wanted": wanted_lua(at_frames, first, last, step),
                        "capture": mscreen.capture_lua(), "pens": mscreen.FRAME_PENS_LUA}
    if len(script) > CONSOLE_CHARS:
        raise st.Invalid("bad_argument", f"a list of {len(wanted)} frames does not fit in one "
                         f"console line ({len(script)} of {CONSOLE_CHARS} characters): name an "
                         "evenly spaced series as `first`, `last` and `step`, which costs one "
                         "line whatever its length")
    return script


def series_capture(ses: gs.Session, scratch: Path, at_frames: list[int] | None, first: int | None,
                   last: int | None, step: int, crop: list[int] | None, dest: str,
                   seconds: float, progress: mprogress.Progress = mprogress.no_progress
                   ) -> dict[str, Any]:
    """The body of the `series_capture` tool."""
    check_series_capture(at_frames, first, last, step, crop, dest, seconds)
    wanted = series.frame_list(at_frames, first, last, step)
    now = read.frame(ses)
    if wanted[0] <= now:
        raise st.Invalid("bad_argument", f"frame {wanted[0]} is not ahead of the machine, which "
                         f"is at frame {now}: a series records frames still to come")
    folder = fresh.directory(inputs.fresh_folder("dest", dest) if dest else None,
                             scratch / "series", lambda n: f"series-{n}", "the series")
    with fresh.taken_back(folder):
        script = arm_script(folder, at_frames, first, last, step, wanted)
        reply = _captured(ses, scratch, folder, bool(dest), wanted, crop, script, seconds,
                          progress)
    if reply.get("status") != "ok":           # the run's own refusal: no series came of it
        fresh.remove_dir(folder)
        return reply
    for raw in folder.glob("raw-*"):
        raw.unlink(missing_ok=True)
    return reply


def _captured(ses: gs.Session, scratch: Path, folder: Path, kept: bool, wanted: list[int],
              crop: list[int] | None, script: str, seconds: float,
              progress: mprogress.Progress) -> dict[str, Any]:
    try:
        text, common = chunk.run(ses, scratch, script, seconds, progress, "series")
        if _NO_SCREEN in text:
            raise st.Invalid("no_channel", "this machine has no screen, so it has no frames to "
                             "keep", **common)
        m = _ARMED.search(text)
        if m is None:
            chunk.no_line("series arming", text, common)
        width, height = int(m.group(2)), int(m.group(3))
        area = [0, 0, width, height] if crop is None else list(crop)
        mscreen.on_screen(width, height, area[0], area[1], area[2], area[3], "crop", common)
    except BaseException:
        _finish_quietly(ses, scratch, seconds, progress)
        raise
    try:
        run = advance.run_for(ses, scratch, 0, seconds, progress,
                              frames=wanted[-1] - int(m.group(1)) + RUN_TAIL)
    except BaseException:
        _finish_quietly(ses, scratch, seconds, progress)
        raise
    if getattr(ses, "running", False):
        # A RUN THAT MAY STILL BE MOVING is answered as `run_for` answered it, and nothing is
        # sent to its console: the notifier stays armed until the next `series_capture` takes
        # it down, or `close` takes the machine.
        return st.merged(run, {"note": "the series notifier is still armed: the next "
                               "series_capture removes it, or close does"})
    done = _finish(ses, scratch, seconds, progress)
    if run.get("status") != "ok":
        return run
    if run.get("verdict") != contract.ELAPSED:
        raise st.Invalid("cut_by_other_stop", f"the run stopped with verdict {run.get('verdict')} "
                         f"({run.get('cause')}) before the last frame was read: no series is "
                         "written from part of one", frame_after=run.get("frame_after"))
    if done["errors"]:
        raise st.Invalid("unexpected_answer", f"the series notifier raised "
                         f"{counted(int(done['errors']), 'time')}, first: {done['first_error']}")
    lost = sorted(int(f) for f in done["lost"].split(",") if f)
    kept_frames = [f for f in wanted if (folder / f"raw-{f}.txt").exists()]
    signed = {frame: _develop(folder, frame, width, height, area, common)
              for frame in kept_frames}
    missing = sorted(set(wanted) - set(kept_frames) - set(lost))
    if missing:
        raise st.Invalid("unexpected_answer",
                         f"{counted(len(missing), 'wanted frame')} came out of the run neither "
                         f"kept nor lost (first {missing[:8]}): the run ended before their "
                         "picture was read")
    if not kept_frames:
        raise st.Invalid("no_progress", "the run reached the last frame and every wanted frame "
                         "was skipped by frameskip, so none was drawn")
    reply = series.write_manifest(folder, "mame", FRAME_SOURCE, crop, kept_frames, signed)
    for frame in kept_frames:
        STATE.record_image(folder / series.frame_name(frame))
    body = {k: v for k, v in run.items() if k not in ("summary", "session")}
    account = {k: common[k] for k in CONSOLE_ACCOUNT if k in common}
    # MERGED, never spread: a field `run_for` and the series both said would otherwise be
    # overwritten in silence
    return st.merged(body, reply, {"crop": area, "lost": series.runs(lost)},
                     series.tail(len(wanted), kept, FRAME_SOURCE), account)


def _develop(folder: Path, frame: int, width: int, height: int, area: list[int],
             common: dict[str, Any]) -> str:
    """Frame `frame`'s dump as its PNG, in the colours of the pens saved at its own end, its
    reading checked: read at the next frame that drew, of the armed size, and a capture the
    chunk did not refuse (`mscreen.captured`, which names the refusal). Answers the picture's
    signature, which the manifest takes rather than decoding the file back."""
    base = folder / f"raw-{frame}"
    text = base.with_suffix(".txt").read_text(encoding="utf-8", errors="replace")
    head = _FRAME.match(text)
    said = text[head.end():] if head is not None else ""
    if head is None:
        raise st.Invalid("unexpected_answer", f"frame {frame}'s file is not whole: {text[:80]!r}")
    if said.startswith(_ERROR):
        raise st.Invalid("unexpected_answer", f"the capture of frame {frame} raised: "
                         f"{said[len(_ERROR):].strip()}")
    mscreen.check_read_on_time(frame, int(head.group(2)), int(head.group(3)))
    cap = mscreen.captured(said, base.with_suffix(".bin"), common)
    mscreen.check_same_size(cap, frame, width, height, "series")
    x, y, w, h = area
    if cap.indices is None:
        picture = mscreen.colour_crop(cap, x, y, w, h)
    else:
        pens = array("I", base.with_suffix(".pens").read_bytes())
        if len(pens) != len(cap.pens):
            raise st.Invalid("unexpected_answer", f"{len(pens)} pens were saved at frame {frame} "
                             f"and the screen has {len(cap.pens)}")
        rgb = mpalette.rgb_bytes(pens)
        lut = [rgb[3 * i:3 * i + 3] for i in range(len(pens))]
        picture = png.Raster(w, h, b"".join(lut[i] for i in cap.window(x, y, w, h)))
    fresh.create(folder / series.frame_name(frame), png.encode(picture), "the frame")
    return raster.picture_signature(picture)


def _finish(ses: gs.Session, scratch: Path, seconds: float,
            progress: mprogress.Progress) -> dict[str, Any]:
    """Remove the notifier and read what it did."""
    text, common = chunk.run(ses, scratch, FINISH_LUA, seconds, progress, "series finish")
    m = _DONE.search(text)
    if m is None:
        chunk.no_line("series finish", text, common)
    return {"kept": int(m.group(1)), "lost": m.group(2), "errors": int(m.group(3)),
            "first_error": m.group(4)}


def _finish_quietly(ses: gs.Session, scratch: Path, seconds: float,
                    progress: mprogress.Progress) -> None:
    """`_finish` on the way out of a call that is already failing: its own failure is not the
    one the caller is told, and an unarmed notifier answers it with zeros."""
    if getattr(ses, "running", False):
        return
    with contextlib.suppress(st.Invalid, gs.SessionError):
        _finish(ses, scratch, seconds, progress)
