"""Section M of the live matrix: comments, held as declarations and shown in MAME's own pane.

On m68k-dual's two 68000s, with both cpus' symbol files and the section's own declaration store
(the harness isolates one per section). Every expected file text is written in the cell from the
literal refs, cpus and texts, with the stamps read off the store's own file, the one view the
server does not compose; the pane is read back through `disassemble` and MAME's own `comsave`.

`live_matrix.py` registers this section before H; run alone, it is the same machinery over this
section only:

    uv run python tests/live/matrix_comments.py
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from bench_boards import M68K_DUAL_SYSTEM, SUB_SYMBOLS, SYMBOLS, m68k_dual_missing
from live_harness import (
    SCRATCH,
    Board,
    boards_cover,
    boot,
    call,
    cell,
    fresh,
    ok,
    refused,
    run_boards,
    run_sections,
    said,
    section,
    visible_of,
)

MAIN, SUB = ":maincpu", ":subcpu"
# THE FILE'S HEADER AND BOUND, written here and not imported from the server, so a change to the
# server's format turns these cells red instead of moving them with it.
HEADER = "# comments v1: ref\tcpu\tcreated_at\ttext\n"
TEXT_MAX_BYTES = 237

M_TITLE = "comments: a declaration per place, MAME's pane fed from the store, one file format"
M_CELLS = [f"M{n} {text}" for n, text in enumerate([
    "an empty store lists no comment",
    "a comment by symbol on the main cpu: stored, persistent, at the table's address",
    "a comment by address on the sub cpu: canonical ref, the visible cpu unmoved",
    "disassemble on each cpu ends the commented line with its own text",
    "a second comment at one place by its hex address replaces the text and keeps the ref",
    "comment_list narrows to a cpu, and lists both without one",
    "comment_save writes the file byte for byte, sorted by cpu then ref, stamps from the store",
    "comment_save again after a delete replaces its own file and names the row it drops",
    "deleting every comment empties the list and the pane",
    "comment_load reads the file back with its own stamps",
    "comment_load lets the file win, returns the replaced row and counts the unchanged one",
    "a new start over the same symbols feeds both comments again",
    "an ini naming comment_directory cannot move MAME's comment file out of the scratch",
    "a show watch and a comment on one ref are both held, in either order",
    "a text breaking the file's rule is refused, one at the bound is stored and shown",
    "a text holding a quote is stored, not shown, and said",
    "a ref that names no place is refused; a name this build lacks is kept unresolved",
    "a delete with nothing at the place names the comments held",
    "comment_save refuses a relative dest, a file of another format and a link",
    "comment_load refuses a bad file whole, naming its line, and leaves the store",
    "on a running machine the list and the save answer, the other three are not_stopped",
])]


def _boot(**extra: Any) -> dict[str, Any]:
    return boot(symbols={MAIN: SYMBOLS, SUB: SUB_SYMBOLS}, **extra)


def _store_rows() -> list[dict[str, Any]]:
    """The comments of the store's own file, read directly: the independent view."""
    path = Path(os.environ["XDG_STATE_HOME"]) / "mame-debug" / "declarations.json"
    raw = json.loads(path.read_text())
    return [d for rows in raw.values() for d in rows if d.get("kind") == "comment"]


def _stamp(ref: str, cpu: str) -> str:
    return next((str(d["created_at"]) for d in _store_rows() if (d["ref"], d["cpu"]) == (ref, cpu)),
                f"<no stamp for {ref} on {cpu}>")


def _line(ref: str, cpu: str) -> str:
    r = call("disassemble", ref=ref, length=2, cpu=cpu)
    return str((r.get("lines") or [""])[0])


def _visible() -> str | None:
    return visible_of(call("cpu_info"))


def _sha(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _m_m68k_dual(t: list[str]) -> None:
    r = _boot()
    if not ok(r):
        raise RuntimeError(f"m68k-dual did not boot: {said(r)}")
    r = call("comment_list")
    cell(t[0], ok(r) and r.get("comments") == [] and r.get("comments_total") == 0, said(r))
    found = call("symbols_find", name="irq_vblank", cpu="maincpu")
    irq = str((found.get("symbols") or [{}])[0].get("addr", ""))
    if not irq:
        raise RuntimeError(f"irq_vblank is not in the table: {said(found)}")
    r = call("comment_add", ref="irq_vblank", text="matrix main", cpu="maincpu")
    c = r.get("comment", {})
    cell(t[1], ok(r) and c.get("addr") == irq and c.get("by") == "symbol"
         and r.get("declarations", {}).get("persistent") is True
         and r.get("replaced_comments") == []
         and c.get("state") == "armed", said(r))
    before = _visible()
    r = call("comment_add", ref="0x400", text="matrix sub", cpu="subcpu")
    c = r.get("comment", {})
    cell(t[2], ok(r) and c.get("cpu") == SUB and c.get("ref") == "0x400"
         and c.get("state") == "armed" and before == _visible() == MAIN,
         f"{said(r)} / visible {before} -> {_visible()}")
    main_line, sub_line = _line(irq, "maincpu"), _line("0x400", "subcpu")
    cell(t[3], main_line.endswith(" // matrix main") and sub_line.endswith(" // matrix sub"),
         f"{main_line!r} / {sub_line!r}")
    r = call("comment_add", ref=f"{int(irq, 16):#x}", text="matrix main 2", cpu="maincpu")
    c = r.get("comment", {})
    total = call("comment_list").get("comments_total")
    line = _line(irq, "maincpu")
    cell(t[4], ok(r) and [x.get("text") for x in r.get("replaced_comments", [])] == ["matrix main"]
         and c.get("ref") == "irq_vblank" and c.get("text") == "matrix main 2" and total == 2
         and line.endswith(" // matrix main 2"), f"{said(r)} / total {total} / {line!r}")
    sub, both = call("comment_list", cpu="subcpu"), call("comment_list")
    cell(t[5], [x.get("text") for x in sub.get("comments", [])] == ["matrix sub"]
         and sub.get("cpu") == SUB and both.get("comments_total") == 2,
         f"{said(sub)} / {said(both)}")
    # ADDED AFTER irq_vblank, so the store's order is not the file's: the writer sorts.
    call("comment_add", ref="0x500", text="matrix five hundred", cpu="maincpu")
    dest = fresh(".tsv")
    r = call("comment_save", dest=dest)
    want = (HEADER + f"0x500\t{MAIN}\t{_stamp('0x500', MAIN)}\tmatrix five hundred\n"
            f"irq_vblank\t{MAIN}\t{_stamp('irq_vblank', MAIN)}\tmatrix main 2\n"
            f"0x400\t{SUB}\t{_stamp('0x400', SUB)}\tmatrix sub\n")
    # BYTES, not text: a text read folds a CR or a CRLF into the line break the format asks for
    got = Path(dest).read_bytes() if Path(dest).is_file() else None
    cell(t[6], ok(r) and r.get("comments_total") == 3 and got == want.encode(),
         f"{said(r)} / {got!r}")
    call("comment_delete", ref="0x500", cpu="maincpu")
    r = call("comment_save", dest=dest)
    cell(t[7], ok(r) and r.get("dropped_comments") == [{"ref": "0x500", "cpu": MAIN}]
         and Path(dest).read_text().count("\n") == 3, said(r))
    for ref, cpu in (("irq_vblank", "maincpu"), ("0x400", "subcpu")):
        call("comment_delete", ref=ref, cpu=cpu)
    empty, line, sub_line = call("comment_list"), _line(irq, "maincpu"), _line("0x400", "subcpu")
    cell(t[8], empty.get("comments") == [] and " // " not in line and " // " not in sub_line,
         f"{said(empty)} / {line!r} / {sub_line!r}")
    r = call("comment_load", path=dest)
    stamps = {(d["ref"], d["cpu"]): d["created_at"] for d in _store_rows()}
    in_file = {(row.split("\t")[0], row.split("\t")[1]): row.split("\t")[2]
               for row in Path(dest).read_text().splitlines()[1:]}
    cell(t[9], ok(r) and r.get("parsed") == 2 and r.get("added") == 2
         and stamps == in_file, f"{said(r)} / {stamps} vs {in_file}")
    call("comment_add", ref="irq_vblank", text="changed in the store", cpu="maincpu")
    r = call("comment_load", path=dest)
    texts = {x["ref"]: x["text"] for x in call("comment_list").get("comments", [])}
    cell(t[10], ok(r) and [x.get("text") for x in r.get("replaced_comments", [])]
         == ["changed in the store"] and r.get("unchanged") == 1
         and texts.get("irq_vblank") == "matrix main 2", f"{said(r)} / {texts}")
    call("close")
    r = _boot()
    counts = (r.get("declarations") or {}).get("comments", {})
    main_line, sub_line = _line(irq, "maincpu"), _line("0x400", "subcpu")
    cell(t[11], ok(r) and sorted(c.get("ref") for c in counts.get("rearmed", [])) == [
        "0x400", "irq_vblank"] and main_line.endswith(" // matrix main 2")
         and sub_line.endswith(" // matrix sub"), f"{counts} / {main_line!r} / {sub_line!r}")
    _edges(t, irq)
    call("close")
    _pinned(t)


def _edges(t: list[str], irq: str) -> None:
    """Cells M13-M20 on the machine M11 started, ending with every comment deleted."""
    # M13 both orders: a watch then a comment, and a comment then a watch, on one ref each
    w1 = call("watch_add", ref="0x203200", mode="show", length=2, fmt="u16")
    c1 = call("comment_add", ref="0x203200", text="after a watch", cpu="maincpu")
    c2 = call("comment_add", ref="0x203300", text="before a watch", cpu="maincpu")
    w2 = call("watch_add", ref="0x203300", mode="show", length=2, fmt="u16")
    watched = sorted(str(w.get("ref")).lower().removeprefix("0x")
                     for w in call("watch_list").get("watches", []))
    noted = sorted(x.get("ref") for x in call("comment_list").get("comments", [])
                   if x.get("ref") in ("0x203200", "0x203300"))
    cell(t[13], all(ok(x) for x in (w1, c1, c2, w2)) and watched == ["203200", "203300"]
         and noted == ["0x203200", "0x203300"],
         f"watches {watched} / comments {noted} / " + " / ".join(said(x) for x in (w1, c2)))
    call("watch_clear", all=True)
    for ref in ("0x203200", "0x203300"):
        call("comment_delete", ref=ref, cpu="maincpu")
    # M14 the text's rule, and its bound
    bad = [call("comment_add", ref="0xfade0", text=x, cpu="maincpu")
           for x in ("", "a\tb", " edge", "y" * (TEXT_MAX_BYTES + 1))]
    at = call("comment_add", ref="0x600", text="y" * TEXT_MAX_BYTES, cpu="maincpu")
    shown = _line("0x600", "maincpu").endswith(" // " + "y" * TEXT_MAX_BYTES)
    cell(t[14], all(refused(x, "bad_argument") for x in bad) and ok(at)
         and at.get("comment", {}).get("state") == "armed" and shown,
         f"{[x.get('code') for x in bad]} / {said(at)} / shown {shown}")
    call("comment_delete", ref="0x600", cpu="maincpu")
    # M15 a quote
    r = call("comment_add", ref="0x604", text='say "hi"', cpu="maincpu")
    line = _line("0x604", "maincpu")
    cell(t[15], ok(r) and r.get("comment", {}).get("state") == "unarmable" and "note" in r
         and " // " not in line, f"{said(r)} / {line!r}")
    call("comment_delete", ref="0x604", cpu="maincpu")
    # M16 refs
    seg = call("comment_add", ref="1234:5678", text="t", cpu="maincpu")
    past = call("comment_add", ref="0x1000000", text="t", cpu="maincpu")
    blank = call("comment_add", ref="a b", text="t", cpu="maincpu")
    hashed = call("comment_add", ref="#x", text="t", cpu="maincpu")
    loose = call("comment_add", ref="zzz_nowhere", text="later", cpu="maincpu")
    cell(t[16], refused(seg, "bad_argument") and refused(blank, "bad_argument")
         and refused(hashed, "bad_argument") and refused(past, "bad_argument")
         and "mask" in str(past.get("message"))
         and loose.get("comment", {}).get("state") == "unresolved",
         f"{said(past)} / {said(loose)}")
    call("comment_delete", ref="zzz_nowhere", cpu="maincpu")
    # M17 nothing there
    r = call("comment_delete", ref="0x1234", cpu="maincpu")
    cell(t[17], refused(r, "unknown_ref") and "'irq_vblank'" in str(r.get("message")), said(r))
    # M18 save's refusals
    other = Path(fresh(".tsv"))
    other.write_text("ref\tsomething else\n")
    sha = _sha(str(other))
    link = Path(fresh(".tsv"))
    link.symlink_to(SCRATCH / "nowhere.tsv")
    rel = call("comment_save", dest="relative.tsv")
    foreign = call("comment_save", dest=str(other))
    linked = call("comment_save", dest=str(link))
    cell(t[18], refused(rel, "bad_argument") and refused(foreign, "bad_argument")
         and _sha(str(other)) == sha and refused(linked, "bad_argument"),
         f"{said(rel)} / {said(foreign)} / {said(linked)}")
    # M19 load's refusals
    before = sorted((d["ref"], d["cpu"], d["text"]) for d in _store_rows())
    faults = {"wrong header": "# comments v2\n",
              "three columns": HEADER + f"x\t{MAIN}\t2026-10-02T00:00:00+00:00\n",
              "one ref twice": HEADER + f"x\t{MAIN}\t2026-10-02T00:00:00+00:00\ta\n"
                               f"x\t{MAIN}\t2026-10-02T00:00:00+00:00\tb\n",
              # one comment named twice, its address in two spellings (two comments a rebuild
              # put at one place are both loaded, so a place twice is no fault)
              "one comment twice": HEADER + f"{irq}\t{MAIN}\t2026-10-02T00:00:00+00:00\ta\n"
                                   f"0x0{irq[2:]}\t{MAIN}\t2026-10-02T00:00:00+00:00\tb\n"}
    replies = {}
    for name, body in faults.items():
        path = Path(fresh(".tsv"))
        path.write_text(body)
        replies[name] = (call("comment_load", path=str(path)), str(path))
    after = sorted((d["ref"], d["cpu"], d["text"]) for d in _store_rows())
    cell(t[19], all(refused(r, "bad_argument") and str(r.get("message", "")).startswith(p + ":")
                    for r, p in replies.values()) and before == after,
         " / ".join(f"{n}: {said(r)}" for n, (r, _p) in replies.items()))
    # M20 a running machine
    call("resume")
    lst, sav = call("comment_list"), call("comment_save", dest=fresh(".tsv"))
    add = call("comment_add", ref="0x608", text="t", cpu="maincpu")
    dele = call("comment_delete", ref="irq_vblank", cpu="maincpu")
    load = call("comment_load", path=fresh(".tsv"))
    stopped = call("stop")
    for ref, cpu in (("irq_vblank", "maincpu"), ("0x400", "subcpu")):
        call("comment_delete", ref=ref, cpu=cpu)
    left = call("comment_list").get("comments")
    # AND THE SECTION LEAVES NOTHING: every comment it made is deleted, read back empty.
    cell(t[20], ok(lst) and "running" not in lst
         and lst["session"]["running"] is True and ok(sav)
         and all(refused(x, "not_stopped") for x in (add, dele, load)) and ok(stopped)
         and left == [], " / ".join(said(x) for x in (lst, sav, add, dele, load))
         + f" / left {left}")


def _pinned(t: list[str]) -> None:
    """M12: an ini naming `comment_directory` sends MAME's file there unless the command line
    pins it, so the empty directory is the red and the scratch's file the green."""
    ini = Path(fresh("-ini"))
    target = Path(fresh("-comments"))
    ini.mkdir()
    target.mkdir()
    (ini / "mame.ini").write_text(f"joystickprovider none\ncomment_directory {target}\n")
    r = _boot(inipath=str(ini))
    if not ok(r):
        cell(t[12], False, f"m68k-dual did not boot with the ini: {said(r)}")
        return
    call("comment_add", ref="irq_vblank", text="pinned", cpu="maincpu")
    saved = call("debug", command="comsave")
    stored = Path(str(r.get("scratch_dir"))) / "comments" / f"{M68K_DUAL_SYSTEM}.cmt"
    in_scratch = stored.is_file()
    in_ini_dir = sorted(target.iterdir())
    call("comment_delete", ref="irq_vblank", cpu="maincpu")
    left = call("comment_list").get("comments")
    cell(t[12], "successfully" in str(saved.get("output")) and not in_ini_dir and in_scratch
         and left == [], f"{said(saved)} / ini dir {in_ini_dir} / scratch {in_scratch} / "
                         f"left {left}")
    call("close")


M_BOARDS = (Board(_m_m68k_dual, tuple(range(len(M_CELLS))), m68k_dual_missing),)
boards_cover("M_BOARDS", M_CELLS, M_BOARDS)


def register_m() -> None:
    """Register section M with the matrix: after every section registered before it."""
    section("M", M_TITLE, M_CELLS)(lambda: run_boards(M_CELLS, M_BOARDS))


if __name__ == "__main__":
    register_m()
    run_sections("SECTION M")
