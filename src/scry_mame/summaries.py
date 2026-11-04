"""THE ONE LINE EVERY REPLY OPENS WITH, one function per tool.

The MCP client paints a call's tool name, its arguments and its reply and nothing else, so two
calls of one tool are told apart only by what is IN the reply: the `summary`, written for a
person, in the tool's own words. Under `perform(summaries=True)` it is also all an earlier step
keeps, which is why a read carries its datum on the line and a count carries its tail.

EACH TOOL NAMES ITS OWN at registration (`server.tool(..., summary=...)`), and the argument is
required: a tool registered without one fails at import, where a central `match` let a new tool
fall through to "<name>: ok" in silence. A refusal's line is the envelope's (`refusal`), the same
for every tool, and never reaches these.

Every function takes the call's arguments as the caller gave them, defaults applied, and the
reply the tool built, and returns one line.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from scry_core import prose, screen_map, session_block
from scry_core import reply_contract as contract

from scry_mame import callbacks

#: A tool's summary: the call's arguments (defaults applied) and its reply, to one line.
Summary = Callable[[dict[str, Any], dict[str, Any]], str]

#: A refusal's line, the cut of its prose and of a read's bytes: scry-core's, alike on both.
clipped, refusal, hex_clipped = prose.clipped, prose.refusal, prose.hex_clipped


def _on_off(value: object) -> str:
    return "on" if value else "off"


def _frame_clause(lead: str, frame: object) -> str:
    """`lead` and the frame, or nothing when no frame was read (an `unavailable` in its place):
    "frame None" reads as a frame the machine never had."""
    return f"{lead}{frame}" if isinstance(frame, int) else ""


# ------------------------------------------------------------------------------ session

def start(args: dict[str, Any], reply: dict[str, Any]) -> str:
    back = reply["declarations"].get("rearm", {}).get("rearmed", [])
    # NAMED, not counted: a re-armed stop from an earlier session cuts the first `run_to` of
    # this one, and a count in the JSON was read past twice. THE MACHINE'S SHAPE AT A GLANCE,
    # counts only: `machine_map` is where the rows are.
    shape = _sections({part: reply["machine"][part]
                       for part in ("cpus", "screens", "rom_files", "regions", "shares")})
    return (f"start {reply['system']} on {reply['binary']} ({reply['binary_origin']}): "
            f"rom_check {reply['rom_check']}, "
            f"{prose.counted(reply['symbols_total'], 'symbol')}, pc {reply['pc']}"
            + (f", machine: {shape}" if shape else "")
            + (f", {prose.counted(len(back), 'declaration')} re-armed: "
               + ", ".join(f"{b['ref']}" + (f" on {b['cpu']}" if isinstance(b["cpu"], str) else "")
                           for b in back) if back else "")
            + (f", {prose.counted(n, 'comment')} re-placed"
               if (n := len(reply["declarations"].get("comments", {}).get("rearmed", [])))
               else "")
            + (f", after {prose.counted(n, 'relaunch', 'relaunches')}"
               if (n := len(reply["start_retries"])) else ""))


def close(args: dict[str, Any], reply: dict[str, Any]) -> str:
    if not reply["closed"]:
        return session_block.NO_SESSION_CLOSE
    when = {"quit": "quit", "died": "the emulator had already exited",
            "exited": "exited without writing its state",
            "killed": "killed after the grace period"}[reply["ended_by"]]
    code = reply["exit_code"]
    left = ", last words left out (see `omitted`)" if reply.get("omitted") else ""
    if isinstance(code, dict):
        return f"close: {when}, reap failed, no exit code{left}"
    return f"close: {when}, exit code {code}{left}"


def cpu_focus(args: dict[str, Any], reply: dict[str, Any]) -> str:
    moved = "ran" if reply["machine_ran"] else "nothing ran"
    now, was = (v if isinstance(v, str) else "unread" for v in (reply["cpu"], reply["was"]))
    return f"cpu_focus: {now} visible, was {was}, {moved} ({reply['via']})"


def status(args: dict[str, Any], reply: dict[str, Any]) -> str:
    # A LIVE SESSION'S REPLY NAMES ITS SYSTEM, and a `pc` that is unavailable means running:
    # `alive` and `running` are the session block's, added after this.
    if "system" not in reply:
        return (session_block.NO_SESSION_STATUS if "exit_code" not in reply
                else f"status: MAME {prose.ended_by(reply['exit_code'])}, `close` it")
    last = (reply.get("last_stop") or {}).get("pc")
    if reply.get("broken"):
        return f"status: {reply['system']} alive, BROKEN, last stop at pc {last}"
    if isinstance(reply.get("pc"), dict):
        return f"status: {reply['system']} RUNNING, last stop at pc {last}"
    return f"status: {reply['system']} alive at pc {reply['pc']}"


def rom_check(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return (f"rom_check {reply['cpu']}: {reply['rom_check']}, "
            f"{reply['query_s'] * 1000:g} ms per query")


# ------------------------------------------------------------------------------ advance

def run_to(args: dict[str, Any], reply: dict[str, Any]) -> str:
    named = f"run_to {screen_map.run_to_named(args, reply)}: {reply['verdict']}"
    if "frames" in reply:
        return f"{named} after {prose.counted(reply['frames'], 'frame')}"
    return f"{named}, control counted {reply['control_hits']}"


def run_for(args: dict[str, Any], reply: dict[str, Any]) -> str:
    # The unit that DECIDED the run, never the default of the other one: "0 ms" on a run asked
    # in frames read as a run that went nowhere.
    asked = (f"{prose.counted(args['frames'], 'frame')}" if args.get("frames")
             else f"{args['milliseconds']} ms")
    if isinstance(reply["frame_before"], dict) and isinstance(reply.get("emulated_before_s"),
                                                              float):
        return (f"run_for {asked}: {reply['verdict']}, emulated {reply['emulated_before_s']:.6f} "
                f"s to {reply['emulated_after_s']:.6f} s")
    return (f"run_for {asked}: {reply['verdict']}, frame {reply['frame_before']} to "
            f"{reply['frame_after']}")


def step(args: dict[str, Any], reply: dict[str, Any]) -> str:
    # WHAT RAN, not what was asked: a step cut short by a stop on another cpu completed fewer.
    return f"step {reply['instructions_completed']} {reply['mode']}: pc {reply['pc']}"


def resume(args: dict[str, Any], reply: dict[str, Any]) -> str:
    if not args["seconds"]:
        return "resume: running, no wait asked"
    if reply["verdict"] == contract.OTHER_STOP:
        return f"resume: OTHER_STOP at pc {reply['pc']} ({reply['cause']})"
    return f"resume: TIMEOUT, still running after {reply['waited_s']} s"


def stop(args: dict[str, Any], reply: dict[str, Any]) -> str:
    if not reply["interrupted"]:
        return "stop: was already stopped"
    return f"stop: interrupted at pc {reply['pc']}{_frame_clause(', frame ', reply['frame'])}"


# ------------------------------------------------------------------------- declarations

def breakpoint_at(args: dict[str, Any], reply: dict[str, Any]) -> str:
    if not reply["armed"]:
        return f"breakpoint_at {args['ref']}: stored, {reply['state']}"
    now = " while running" if reply["while_running"] else ""
    return f"breakpoint_at {args['ref']}: armed at {reply['addr']}{now}"


def regpoint_add(args: dict[str, Any], reply: dict[str, Any]) -> str:
    if not reply["armed"]:
        return f"regpoint_add {reply['ref']}: stored, {reply['state']}"
    now = " while running" if reply["while_running"] else ""
    return f"regpoint_add {reply['ref']}: armed, index {reply['index']}{now}"


def watch_add(args: dict[str, Any], reply: dict[str, Any]) -> str:
    what = f"{reply['mode']} watch {reply['state']}"
    if reply["mode"] == "expr":
        hexed = (reply.get("reading") or {}).get("hex")
        value = f", {hexed}" if hexed is not None else ""
        return f"watch_add {args['ref']}: {what}{value}"
    where = f" at {reply['addr']}" if "addr" in reply else ""
    return f"watch_add {args['ref']}: {what}{where}, {prose.counted(reply['length'], 'byte')}"


# The states of a row whose stop or tap is installed: a watchpoint or breakpoint `armed`, a count's
# tap `tallied`, a capture's `captured`, and a tap installed with no dump read yet. A show or expr
# watch is `evaluated`, and arms nothing.
ARMED_STATES = ("armed", "tallied", "captured")


def _is_armed(row: dict[str, Any]) -> bool:
    return row["state"] in ARMED_STATES or (row["state"] == "no_dump_yet"
                                            and row.get("installed") is True)


def _armed(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if _is_armed(row))


#: Each kind's reply field, in the order a list of every kind names them.
DECLARATION_ROWS = {"breakpoint": "breakpoints", "regpoint": "regpoints", "watch": "watches"}


def declaration_list(args: dict[str, Any], reply: dict[str, Any]) -> str:
    """How many of each kind are declared and armed, and the taps whose callbacks raised: their
    census is not the whole one, and a summary read alone must not pass for a clean list."""
    said = []
    kind_of = {key: kind for kind, key in DECLARATION_ROWS.items()}
    for key in DECLARATION_ROWS.values():
        if key in reply:
            rows = reply[key]
            raised = sum(1 for row in rows if (row.get("callback_errors") or {}).get("count"))
            said.append(f"{prose.counted(len(rows), kind_of[key], key)} ({_armed(rows)} armed"
                        + (f", {raised} with callback errors" if raised else "") + ")")
    kind = f" {args['kind']}" if args.get("kind") else ""
    return f"declaration_list{kind}: " + ", ".join(said)


def declaration_clear(args: dict[str, Any], reply: dict[str, Any]) -> str:
    """What the store dropped and what the debugger let go, and the taps whose removal was
    sent, which an io tap is all of."""
    taps = len(reply.get("tallies_removed", []))
    removed = f", {prose.counted(taps, 'tap')} removed" if taps else ""
    return (f"declaration_clear {args['kind']} {args['ref'] or 'all'}: "
            f"{reply['declarations_cleared']} cleared, {len(reply['disarmed'])} disarmed{removed}")


# --------------------------------------------------------------------------------- comments

def _where(row: dict[str, Any]) -> str:
    """A comment row's cpu and place: its address, or `unresolved` for a name this build lacks."""
    return f"{row['cpu'] if isinstance(row['cpu'], str) else '-'} {row.get('addr', 'unresolved')}"


def add_comment(args: dict[str, Any], reply: dict[str, Any]) -> str:
    kept = "persistent" if reply["declarations"]["persistent"] else "dies at close"
    return f"{reply['comment']['ref']} at {_where(reply['comment'])}, stored, {kept}"


def _filtered_on(reply: dict[str, Any]) -> str:
    """The cpu a list tool's reply was narrowed to, or "" when it names none (its `cpu` is then
    unavailable, saying the rows are every cpu's)."""
    cpu = reply.get("cpu")
    return cpu if isinstance(cpu, str) else ""


def comment_list(args: dict[str, Any], reply: dict[str, Any]) -> str:
    on = f" on {_filtered_on(reply)}" if _filtered_on(reply) else ""
    return f"comment_list: {prose.counted(reply['comments_total'], 'comment')}{on}"


def delete_comment(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return f"{args['ref']} at {_where(reply['deleted'])} deleted"


def save_comments(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return f"{prose.counted(reply['comments_total'], 'comment')} to {reply['path']}"


def load_comments(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return (f"{reply['parsed']} read, {reply['added']} added, "
            f"{reply['replaced_total']} replaced")


# --------------------------------------------------------------------------------- read

def symbols_find(args: dict[str, Any], reply: dict[str, Any]) -> str:
    if "delta" in reply:
        return f"symbols_find {reply['linear']}: {reply['name']} + {reply['delta']}"
    n = reply["symbols_total"]
    return f"symbols_find {args['name']}: {prose.counted(n, 'match', 'matches')}"


def cpu_info(args: dict[str, Any], reply: dict[str, Any]) -> str:
    # A named cpu's own row, never a verdict on the rows the filter left out.
    rows = reply["cpus"]
    if _filtered_on(reply):
        seen = rows[0]["visible"]
        word = ("visible" if seen is True else "not visible" if seen is False
                else "visibility unread")
        return f"cpu_info of {reply['cpu']}: {word}"
    shown = next((row["cpu"] for row in rows if row["visible"] is True), None)
    return (f"cpu_info: {prose.counted(len(rows), 'cpu')}, "
            f"{f'{shown} visible' if shown else 'the visible cpu unread'}")


#: A machine section's count as a summary says it: the noun of one row, and its plural where
#: adding `s` is not English.
SECTION_NOUNS: dict[str, tuple[str, str | None]] = {
    "cpus": ("cpu", None), "spaces": ("space", None),
    "address_map": ("address map entry", "address map entries"), "regions": ("region", None),
    "shares": ("share", None), "screens": ("screen", None), "rom_files": ("ROM file", None),
    "symbol_coverage": ("symbol class", "symbol classes"),
}


def _sections(counts: dict[str, int]) -> str:
    """The board's shape on one line: each section counted, its noun in its number."""
    return ", ".join(prose.counted(n, *SECTION_NOUNS.get(part, (part, part)))
                     for part, n in counts.items() if n)


def machine_map(args: dict[str, Any], reply: dict[str, Any]) -> str:
    # THE SHAPE OF THE BOARD ON THE LINE, from the FULL counts, so a cut section still says
    # how much there is.
    shape = _sections(reply["counts"])
    cut = ", some sections cut (see `counts`)" if reply["truncated"] else ""
    left = reply.get("omitted") or []
    out = f", left out: {', '.join(left)} (see `omitted`)" if left else ""
    of = f" of {_filtered_on(reply)}" if _filtered_on(reply) else ""
    return f"machine_map{of}: {shape or 'nothing this gather recognised'}{cut}{out}"


def read_memory(args: dict[str, Any], reply: dict[str, Any]) -> str:
    # THE DATUM RIDES ON THE LINE: under `perform(summaries=True)` the summary is all a read
    # step keeps, and a read that answered no bytes there was a step spent for nothing.
    return (f"read_memory {args['ref']}: {prose.counted(reply['length'], 'byte')} at "
            f"{reply['addr']}: {hex_clipped(reply['hex'])}")


def read_block(args: dict[str, Any], reply: dict[str, Any]) -> str:
    asked = f"{args['ref']} in " if args.get("ref") else ""
    return (f"read_block {asked}{reply['kind']} {reply['tag']}: "
            f"{prose.counted(reply['length'], 'byte')} at offset {reply['offset']:#x} of "
            f"{reply['size']:#x}: {hex_clipped(reply['hex'])}")


def registers(args: dict[str, Any], reply: dict[str, Any]) -> str:
    older = ", from the last stop" if reply.get("superseded") else ""
    if reply["regs"].get("available") is False:
        return f"registers: none read{older}: {reply['regs']['why']}"
    return f"registers: {prose.counted(len(reply['regs']), 'register')}{older}"


def disassemble(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return (f"disassemble {args['ref']}: {prose.counted(len(reply['lines']), 'line')} at "
            f"{reply['addr']}")


def find(args: dict[str, Any], reply: dict[str, Any]) -> str:
    where = (reply["symbol_class"] if "symbol_class" in reply
             else f"{reply['length']:#x} bytes at {args['ref']}")
    return (f"find {str(args['data_hex']).lower()} in {where}: "
            f"{prose.counted(reply['hits_total'], 'hit')}")


def start_scan(args: dict[str, Any], reply: dict[str, Any]) -> str:
    cells = f"{reply['cell_bytes']}-byte candidate"
    return f"{args['ref']}, {prose.counted(reply['hits_total'], cells)} on {reply['cpu']}"


def filter_scan(args: dict[str, Any], reply: dict[str, Any]) -> str:
    value = f" {reply['value']}" if isinstance(reply["value"], str) else ""
    closed = ", scan closed" if reply["closed"] else ""
    return (f"{reply['operator']}{value}, "
            f"{prose.counted(reply['hits_total'], 'survivor')}{closed}")


def clear_scan(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return "cleared" if reply["cleared"] else "nothing was open"


def history(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return f"history: {prose.counted(len(reply['lines']), 'instruction')} of {reply['asked']} asked"


# -------------------------------------------------------------------------------- write

def write(args: dict[str, Any], reply: dict[str, Any]) -> str:
    into = (f" into {reply['region']} at {reply['region_offset']:#x}"
            if args.get("region") else "")
    return (f"write {args['ref']}: {prose.counted(reply['bytes_written'], 'byte')}{into}, verified "
            f"{reply['verified']}")


def set_register(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return (f"set_register {reply['register']} = {reply['value']}, verified "
            f"{reply['verified']}")


def reset(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return (f"reset: {reply['kind']} applied"
            f"{_frame_clause(' at frame ', reply['frame_at_reset'])}, pc {reply['pc']} "
            f"verified {reply['verified']}")


# -------------------------------------------------------------------------------- files

def memdump(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return f"memdump {args['ref']}: {prose.counted(reply['bytes'], 'byte')} to {reply['path']}"


def snapshot(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return f"snapshot: {prose.counted(reply['bytes'], 'byte')} at {reply['path']}"



def palette(args: dict[str, Any], reply: dict[str, Any]) -> str:
    last = reply["first"] + reply["count"] - 1
    more = f" of {reply['entries']}" + (", more after" if last + 1 < reply["entries"] else "")
    return (f"palette {reply['palette']}: pens {reply['first']:#x}..{last:#x}{more}; "
            f"{prose.picture(reply)}")


def screen_view(args: dict[str, Any], reply: dict[str, Any]) -> str:
    head = f"screen_view {reply['mode']} {reply['screen']} frame {reply['frame_screen']}"
    if reply["mode"] == "pixel":
        pixel = f"{head}: ({reply['x']}, {reply['y']}) is pen {reply['pen']:#x} {reply['color']}"
        by = reply.get("set_by")
        if not by or by.get("available") is False:
            # THE WHY IS SAID: "no logged write" alone reads a log never armed, or one whose
            # callbacks raised, as a pen nobody wrote
            why = (by or {}).get("why") or "nothing says why"
            return f"{pixel}; no logged write to it: {why}; {prose.picture(reply)}"
        last = by["last"]
        agrees = ("" if by["agrees"] is True else ", NOT the colour it has now"
                  if by["agrees"] is False else ", incomplete")
        return (f"{pixel}; last set by a {last['written_by']} write at pc {last['pc']}, frame "
                f"{last['frame']}{agrees}; {prose.picture(reply)}")
    if reply["mode"] == "histogram":
        return f"{head}: {reply['pens_used']} of {prose.counted(reply['entries'], 'pen')} used"
    shown = (f", {prose.counted(reply['pixels'], 'pixel')} of pens {reply['pens']}"
             if reply["mode"] == "isolate" else "")
    read = "indices" if reply["screen_indexed"] else "colours"
    return f"{head} from {read}{shown}; {prose.picture(reply)}"


def gfx_view(args: dict[str, Any], reply: dict[str, Any]) -> str:
    lay = reply["layout"]
    last = reply["first"] + reply["count"] - 1
    return (f"gfx_view {reply['kind']} {reply['tag']}: tiles {reply['first']}..{last} of "
            f"{reply['tiles_available']}, {lay['width']}x{lay['height']}x{lay['planes']}, "
            f"palette {reply['palette']}; {prose.picture(reply)}")


def gfx_locate(args: dict[str, Any], reply: dict[str, Any]) -> str:
    head = f"gfx_locate {reply['kind']} {reply['tag']} for patch {reply['patch']}"
    if not reply["matched"]:
        near = reply.get("nearest")
        closest = (f", nearest tile {near['tile']} off by {near['disagree']} of {near['of']}"
                   if near and "tile" in near else "")
        return f"{head}: no match{closest}"
    first = reply["matches"][0]
    more = " (ambiguous)" if reply["ambiguous"] else ""
    read = ("through a pen map" if isinstance(first["base"], dict)
            else f"base {first['base']:#x}")
    return (f"{head}: {prose.counted(reply['matches_total'], 'match', 'matches')}{more}, first "
            f"{first['layout']} tile "
            f"{first['tile']} flip {first['flip']} {read}")


def gfx_sweep(args: dict[str, Any], reply: dict[str, Any]) -> str:
    cands = reply["candidates"]
    shown = sum(1 for c in cands if c["shown"])
    ids = f"{cands[0]['id']}..{cands[-1]['id']}" if len(cands) > 1 else cands[0]["id"]
    return (f"gfx_sweep {reply['kind']} {reply['tag']}: sweep {reply['sweep']}, "
            f"{prose.counted(len(cands), 'candidate')} {ids}, {shown} drawn; "
            f"{prose.picture(reply)}")


def gfx_draft(args: dict[str, Any], reply: dict[str, Any]) -> str:
    fmts = reply["formats"]
    by_status = ", ".join(f"{sum(1 for v in fmts.values() if v == s)} {s}"
                          for s in ("proved", "human") if any(v == s for v in fmts.values()))
    return (f"gfx_draft {reply['manifest']['path']}: {prose.counted(len(fmts), 'format')}"
            + (f" ({by_status})" if by_status else "")
            + f", {prose.counted(len(reply['asset_names']), 'asset')}, "
              f"{prose.counted(len(reply['command_fields']), 'command')}"
            + (f"; {len(reply['not_proved']) + reply.get('not_proved_more', 0)} not proved"
               if reply["not_proved"] else ""))


def series_capture(args: dict[str, Any], reply: dict[str, Any]) -> str:
    lost = sum(b - a + 1 for a, b in reply["lost"])
    tail = f", {prose.counted(lost, 'frame')} lost" if lost else ""
    return (f"series_capture: {prose.counted(reply['count'], 'frame')} {reply['first']}.."
            f"{reply['last']}, {reply['distinct']} distinct{tail}, manifest {reply['manifest']}")


def screen_signature(args: dict[str, Any], reply: dict[str, Any]) -> str:
    x, y, w, h = reply["crop"]
    return f"screen_signature {w}x{h} at [{x}, {y}]: {reply['signature']}"


# The screen maps' lines are scry-core's, alike on both servers.
screen_map_find = screen_map.find_line


def log(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return (f"log {args['channel']} /{args['pattern']}/: {len(reply['lines'])} of "
            f"{prose.counted(reply['lines_total'], 'line')}")


def log_wait(args: dict[str, Any], reply: dict[str, Any]) -> str:
    if reply["verdict"] == contract.TIMEOUT:
        return (f"log_wait {args['channel']} /{args['pattern']}/: TIMEOUT, no match in "
                f"{reply['waited_s']} s, {prose.counted(reply['arrived_during'], 'line')} arrived")
    when = "already there" if reply["already"] else f"after {reply['waited_s']} s"
    return f"log_wait {args['channel']} /{args['pattern']}/: matched {when}"


# THE ORDER THE LINE NAMES THE KNOWN KINDS IN; a tool that writes a new kind adds it here. A
# kind not listed is still counted, after these in the order first seen, so the parts sum.
CAPTURE_KINDS = ("avi", "png", "image", "wav", "trace")


def captures(args: dict[str, Any], reply: dict[str, Any]) -> str:
    kinds = [c["kind"] for c in reply["captures"]]
    order = [k for k in CAPTURE_KINDS if k in kinds]
    order += [k for k in dict.fromkeys(kinds) if k not in CAPTURE_KINDS]
    by_kind = ", ".join(f"{kinds.count(k)} {k}" for k in order)
    return f"captures: {prose.counted(len(kinds), 'file')}" + (f", {by_kind}" if by_kind else "")


# -------------------------------------------------------------------------- sequences

def perform(args: dict[str, Any], reply: dict[str, Any]) -> str:
    # THE COUNT AND THE TAIL ON THE LINE: `ok` told two lists apart by nothing, and under
    # `summaries=True` a nested list's line is all its caller keeps.
    done = f"{prose.counted(reply['steps_completed'], 'step')} completed"
    if reply.get("verdict"):
        done += f", {reply['verdict']}"
    if "stopped" in reply:
        return (f"perform: {done}, stopped at pc {reply['stopped']['pc']} "
                f"({reply['stopped']['cause']})")
    if reply.get("still_running"):
        return f"perform: {done}, still running"
    if "until_frame" in reply:
        reached = _frame_clause("frame ", reply["frame_reached"]) or "no frame read"
        return f"perform: {done}, {reached} of {reply['until_frame']}"
    return f"perform: {done}"


def drive(args: dict[str, Any], reply: dict[str, Any]) -> str:
    verify = reply.get("verify") or {}
    act = reply.get("act") or {}
    if act.get("verdict") == contract.TIMEOUT:
        return "drive: act TIMEOUT, nothing verified"
    seen = (f"effect seen, {verify['verdict']}" if verify.get("seen") else
            f"effect not seen, {verify['verdict']}" if verify.get("checked")
            else "no expectation")
    return f"drive: {seen}"


def debug(args: dict[str, Any], reply: dict[str, Any]) -> str:
    mutates = ", mutates" if reply["mutates"] else ""
    clipped_to = (f", {prose.counted(reply['output_chars'], 'char')} to a file" if reply["clipped"]
                  else "")
    return f"debug {args['command']!r}{mutates}{clipped_to}"


# ----------------------------------------------------------------------------- the Lua channel

def lua(args: dict[str, Any], reply: dict[str, Any]) -> str:
    chars = reply["output_chars"] if reply["clipped"] else len(reply["output"])
    to_file = ", to a file" if reply["clipped"] else ""
    return (f"lua: {prose.counted(chars, 'char')} back{to_file}, pc {reply['pc']} after "
            f"{reply['evaluated_by']}")


# A wrapper's script given up on: its note counts the frames the run spent, so this never says
# that none ran.
PENDING_SCRIPT = "still pending, its script not evaluated yet, though frames may have run (`note`)"


def input(args: dict[str, Any], reply: dict[str, Any]) -> str:  # noqa: A001 - the tool's name
    head = f"input {args['port']} {args['field']!r}"
    if reply.get("pending"):
        return f"{head}: {PENDING_SCRIPT}"
    if not reply["released"]:
        return (f"{head}: still HELD from frame {reply['frame_set']}, releases at "
                f"{reply['frame_release_planned']}")
    return (f"{head}: held {prose.counted(reply['frames'], 'frame')}, active {reply['active']}, "
            f"released at frame {reply['frame_released']}")


def trace(args: dict[str, Any], reply: dict[str, Any]) -> str:
    asked = (f"{prose.counted(args['frames'], 'frame')}" if args.get("frames")
             else f"{args['milliseconds']} ms")
    t = reply["trace"]
    return (f"trace {t['cpu']} {asked}: {prose.counted(t['addresses'], 'address', 'addresses')} "
            f"in {prose.counted(t['symbols_total'], 'symbol')}, "
            f"{prose.counted(t['bytes'], 'byte')}")


def _unfinished(tool: str, reply: dict[str, Any]) -> str | None:
    """A bounded recording's line when it has no file yet: its script never evaluated, its
    notifier not yet called, or the recording begun and not ended. None when it ended."""
    if reply.get("pending"):
        return f"{tool}: {PENDING_SCRIPT}"
    if not reply["began"]:
        return (f"{tool}: NOT begun, begins at frame {reply['frame_begin_planned']}, ends at "
                f"{reply['frame_end_planned']}")
    if not reply["ended"]:
        return (f"{tool}: still OPEN from frame {reply['frame_begin']}, ends at "
                f"{reply['frame_end_planned']}")
    return None


def record(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return (_unfinished("record", reply) or
            f"record: {prose.counted(reply['avi_frames'], 'frame')}, "
            f"{prose.counted(reply['bytes'], 'byte')} at {reply['path']}")


def audio_record(args: dict[str, Any], reply: dict[str, Any]) -> str:
    unfinished = _unfinished("audio_record", reply)
    if unfinished is not None:
        return unfinished
    silent = ", silent" if reply["sample_min"] == reply["sample_max"] else ""
    return (f"audio_record: {prose.counted(reply['samples'], 'sample')} at "
            f"{reply['sample_rate_hz']} Hz x {reply['channels']}{silent} at {reply['path']}")


def throttle(args: dict[str, Any], reply: dict[str, Any]) -> str:
    if reply["pending"]:
        return f"throttle {_on_off(reply['on'])}: pending until the console next reads a line"
    return f"throttle {_on_off(reply['on'])}: applied at frame {reply['frame']}"


def save_state(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return (f"{reply['name']}, "
            f"{prose.counted(reply['bytes'], 'byte')}{_frame_clause(' at frame ', reply['frame'])}")


def _datum(value: Any) -> str:
    """A reply's datum as a summary says it: `unavailable` where it could not be read, its
    reason left to the reply (`unavailable`)."""
    return "unavailable" if isinstance(value, dict) and value.get("available") is False else str(
        value)


def load_state(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return (f"{reply['name']}, rom_check {_datum(reply['rom_check'])}, verified "
            f"{_datum(reply['verified'])}{_frame_clause(', frame ', reply['frame'])}, pc "
            f"{reply['pc']}")


def state_list(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return (f"state_list: {prose.counted(len(reply['states']), 'state')} in "
            f"{reply['state_dir']}")


def gfx_load(args: dict[str, Any], reply: dict[str, Any]) -> str:
    counts = reply["status_counts"]
    proved = f"{counts['proved']} proved, {counts['declared']} declared, {counts['human']} human"
    return (f"gfx_load {reply['path']}: {prose.counted(len(reply['formats']), 'format')}, "
            f"{prose.counted(len(reply['assets']), 'asset')}, "
            f"{prose.counted(len(reply['commands']), 'command')}, "
            f"{prose.counted(len(reply['palette_ports']), 'palette port')}; {proved}")


def _raised(reply: dict[str, Any]) -> str:
    """The clause a census's line ends with when its callbacks raised: the census it reports is
    short of what happened."""
    clause = callbacks.said(reply.get("callback_errors"))
    return f"; {clause}" if clause else ""


def palette_log(args: dict[str, Any], reply: dict[str, Any]) -> str:
    head = f"palette_log {reply['palette_port']}"
    if "cleared" in reply:
        return f"{head}: " + ("cleared" if reply["cleared"] else "no log was armed")
    if reply.get("armed_now"):
        return f"{head}: armed, installed when the console next reads a line"
    if "writes_total" not in reply:
        return f"{head}: {reply.get('state', 'nothing on disk')}"
    older = " (superseded)" if reply.get("superseded") else ""
    return (f"{head}{_frame_clause(' as of frame ', reply['frame_as_of'])}{older}: "
            f"{prose.counted(reply['writes_total'], 'data write')}, "
            f"pens {', '.join(reply['pens_written']) or 'none'} written, "
            f"{prose.counted(reply['rows_kept'], 'row')} kept, {reply['overflow_rows']} past the "
            f"cap{_raised(reply)}")


def gfx_film(args: dict[str, Any], reply: dict[str, Any]) -> str:
    if "cleared" in reply:
        return "gfx_film: " + ("cleared, its files kept" if reply["cleared"]
                               else "no film was armed")
    film = reply.get("film") or reply
    head = f"gfx_film on {film['trigger']}"
    if reply.get("armed_now"):
        return f"{head}: armed, installed when the console next reads a line"
    if "judged" not in reply:
        return f"{head}: {reply.get('state', 'nothing on disk')}"
    older = " (superseded)" if reply.get("superseded") else ""
    counts = (f"{reply['state']}{older}, {reply['judged']} judged, {reply['met']} met, "
              f"{reply['kept']} kept")
    if "image" not in reply:
        return f"{head}: {counts}{_raised(reply)}"
    return f"{head}: {counts}; {prose.picture(reply)}{_raised(reply)}"


def gfx_blits(args: dict[str, Any], reply: dict[str, Any]) -> str:
    head = f"gfx_blits {reply['draw_command']} frame {reply['frame_blit']}"
    # A PAGE THAT IS NOT THE WHOLE LIST SAYS WHICH IT IS, so two pages of one frame read apart
    listed = reply.get("listed")
    page = (f", listed {listed['first']}..{listed['first'] + listed['count'] - 1}"
            if listed and listed["count"] < listed["of"] else "")
    if "area" in reply:
        top = reply["topmost"]
        last = f", topmost #{top['index']} pc {top['pc']}" if "index" in top else ""
        return (f"{head}: {reply['covering']} of {prose.counted(reply['blits_in_frame'], 'blit')} "
                f"{prose.agrees(reply['covering'], 'covers', 'cover')} {reply['area']}{last}"
                f"{page}; {prose.picture(reply)}{_raised(reply)}")
    return (f"{head}: {prose.counted(reply['blits_in_frame'], 'blit')} by "
            f"{prose.counted(len(reply['legend']), 'writer')}{page}; {prose.picture(reply)}"
            f"{_raised(reply)}")


def gfx_blit_source(args: dict[str, Any], reply: dict[str, Any]) -> str:
    r = reply["rect"]
    return (f"gfx_blit_source {reply['draw_command']} frame {reply['frame_blit']} "
            f"#{reply['index']} pc {reply['blit_pc']}: {reply['asset']} tile {r['tile']} "
            f"({r['x']}, {r['y']}) {r['width']}x{r['height']}; {prose.picture(reply)}")
