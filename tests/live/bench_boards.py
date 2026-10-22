"""The boards the live scripts run on the bench, and why one cannot run: their copies, pinned by
`scry_core.live_bench` in the bench's own `bench.json`, one directory per board under the bench's
root, which `_root` resolves.

A BOARD IS NAMED HERE BY ITS LABEL, never by its set: what the case covers (`m68k-dual`, `v30`)
is what this tree says, and what MAME needs on disk (the set's name, its binary, its ROM files)
lives in the bench's `identity.json`, beside the manifest, and nowhere tracked. MAME cannot be
handed a set under another name, so the real identity has to exist somewhere; the bench is the
one place that already holds the real files.

A board whose identity is absent or incomplete, or whose copies are absent or off their pins, is
BLOCKED naming what is wrong and how to fix it; the free boards of mamedev.org run without a
bench.
"""

import json
import os
from pathlib import Path

from scry_core import live_bench as bench
from scry_core import verdict


def _root() -> Path:
    held = os.environ.get("MAME_LIVE_BENCH", "")
    if held:
        return Path(held).expanduser().absolute()
    return Path.home() / ".local" / "share" / "scry-bench" / "mame"


#: The bench, with the manifest of every file the live tier reads from it.
BENCH = bench.Bench(_root())
#: What each label stands for on this machine: `{label: {key: value}}`, every value a string.
IDENTITY = BENCH.root / "identity.json"

#: The keys each board's identity carries. `dir` is the board's directory under the bench; the
#: keys in `PATH_KEYS` are files inside it.
IDENTITY_KEYS: dict[str, tuple[str, ...]] = {
    # the board every live script drives: two 68000s, a RAMDAC, a blitter
    "m68k-dual": ("dir", "system", "binary", "reference_rom", "symbols", "sub_rom",
                  "sub_symbols", "blit_handler"),
    # a second 68000 board, driven by section V
    "m68k-dual-alt": ("dir", "system", "binary", "reference_rom"),
    # the V30 board with a `sequence` palette and a segment the map classes as ROM
    "v30": ("dir", "system", "binary", "rom_segment"),
    # the V30 board with an io space and a `latch` palette
    "v30-alt": ("dir", "system", "binary", "reference_rom"),
}

PATH_KEYS = frozenset({"binary", "reference_rom", "symbols", "sub_rom", "sub_symbols"})

#: What the code itself opens inside a board's directory, beyond its identity's files: names
#: that say nothing of the program, so they stay here.
ROMPATH = "run/mame_roms"
GFX_MANIFEST = "hardware/gfx.yaml"
V30_REFERENCE_ROM = "build/Game_V30.bin"
V30_SYMBOLS = "build/game_v30.map"
_OPENED: dict[str, tuple[str, ...]] = {
    "m68k-dual": (GFX_MANIFEST,),
    "m68k-dual-alt": (),
    "v30": (V30_REFERENCE_ROM, V30_SYMBOLS),
    "v30-alt": (),
}


def _identity() -> tuple[dict[str, dict[str, str]], str]:
    """Every label's values, and why the file cannot be read (empty when it can)."""
    remedy = (f"write {IDENTITY} beside bench.json: one object per label "
              f"({', '.join(IDENTITY_KEYS)}), each value a string")
    try:
        doc = json.loads(IDENTITY.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, f"identity ABSENT: {remedy}"
    except (OSError, ValueError) as e:
        return {}, f"identity UNREADABLE ({e}): {remedy}"
    if not isinstance(doc, dict) or not all(isinstance(v, dict) for v in doc.values()):
        return {}, f"identity NOT AN OBJECT OF OBJECTS: {remedy}"
    return doc, ""


_DOC, _DOC_WHY = _identity()


def _known(label: str, key: str = "dir") -> None:
    """A label or key the code does not declare is the code's mistake, on every host alike."""
    if key not in IDENTITY_KEYS.get(label, ()):
        raise KeyError(f"no identity key {label}.{key}: declare it in IDENTITY_KEYS")


def identity_missing(label: str) -> str:
    """Why `label`'s identity cannot be used, or empty when it carries every key as a string."""
    _known(label)
    if _DOC_WHY:
        return _DOC_WHY
    held = _DOC.get(label)
    if held is None:
        return (f"identity names no {label!r}: add it to {IDENTITY} with "
                f"{', '.join(IDENTITY_KEYS[label])}")
    for key in IDENTITY_KEYS[label]:
        if not isinstance(held.get(key), str) or not held[key]:
            return (f"identity {label}.{key} is {held.get(key)!r}, not a non-empty string: "
                    f"set it in {IDENTITY}")
    return _one_segment(label, held["dir"])


def _one_segment(label: str, directory: str) -> str:
    """A board's `dir` is one directory under the bench, which is how a path is traced back to
    its board."""
    if Path(directory).name != directory or directory in (".", ".."):
        return (f"identity {label}.dir is {directory!r}, not one directory name: set it in "
                f"{IDENTITY}")
    return ""


def value(label: str, key: str) -> str:
    """`label`'s `key`, or empty when its identity cannot be used, which its board's
    `board_missing` reports: a value read here is used only on a board that is not BLOCKED."""
    _known(label, key)
    return "" if identity_missing(label) else str(_DOC[label][key])


def board_dir(label: str) -> Path:
    """`label`'s directory on the bench; the label's own name when its identity is unusable, so a
    path built on it is one `args_missing` traces back to the label."""
    return BENCH.root / (value(label, "dir") or label)


def board_path(label: str, key: str) -> str:
    """The file `label`'s `key` names, inside its directory on the bench."""
    return str(board_dir(label) / value(label, key))


def bench_missing(prefix: str) -> str:
    """Why the copies under `prefix` (a board's directory, or one file) cannot be used, or empty
    when every one matches its pin."""
    return BENCH.missing(prefix)


def opened(label: str) -> list[str]:
    """Every file the live code opens on board `label`, relative to the bench: its identity's
    files, its set's zip on the rompath, and the ones the code names itself."""
    files = [value(label, k) for k in IDENTITY_KEYS[label] if k in PATH_KEYS]
    files += [f"{ROMPATH}/{value(label, 'system')}.zip", *_OPENED[label]]
    return [f"{value(label, 'dir')}/{f}" for f in files]


def _unpinned(label: str) -> str:
    """The first file board `label` opens that the manifest does not pin, as a reason, or empty:
    a file opened unpinned would be read unchecked, and the board would run on whatever sits
    there."""
    try:
        pinned = BENCH.pinned
    except verdict.Invalid as e:
        return f"bench {e}"
    off = next((p for p in opened(label) if p not in pinned), None)
    return "" if off is None else (
        f"board {label} opens {off}, which {BENCH.manifest} does not pin: pin it there, or "
        "name a file it pins")


def board_missing(label: str) -> str:
    """Why the board `label` cannot run here, or empty: its identity, its copies, then whether
    every file it opens is one the manifest pins."""
    return (identity_missing(label) or bench_missing(f"{value(label, 'dir')}/")
            or _unpinned(label))


def m68k_dual_missing() -> str:
    """Why the board every script drives cannot run here, or empty."""
    return board_missing("m68k-dual")


# the board every live script drives, how it proves itself against the ROM on disk, and the
# project's own graphics manifest, which its sections read.
M68K_DUAL_BINARY = board_path("m68k-dual", "binary")
M68K_DUAL_SYSTEM = value("m68k-dual", "system")
M68K_DUAL_ROMS = str(board_dir("m68k-dual") / ROMPATH)
REFERENCE_ROM = board_path("m68k-dual", "reference_rom")
SYMBOLS = board_path("m68k-dual", "symbols")
SUB_ROM = board_path("m68k-dual", "sub_rom")
SUB_SYMBOLS = board_path("m68k-dual", "sub_symbols")
MANIFEST = str(board_dir("m68k-dual") / GFX_MANIFEST)
#: The driver's handler a blit write maps to, as MAME's map names it.
BLIT_HANDLER = value("m68k-dual", "blit_handler")

# a second 68000 board, driven by section V.
M68K_DUAL_ALT_BOOT = dict(binary=board_path("m68k-dual-alt", "binary"),
                     system=value("m68k-dual-alt", "system"),
                     rompath=str(board_dir("m68k-dual-alt") / ROMPATH),
                     reference_rom=board_path("m68k-dual-alt", "reference_rom"),
                     reference_addr="0x0")


def args_missing(args: dict[str, object]) -> str:
    """Why a call taking `args` cannot be made, or empty: every argument that is a path on the
    bench (a symbol table, a manifest, a binary, the values of a dict of them) needs its board's
    identity and copies. A path off the bench is not the bench's to judge."""
    values = [v for a in args.values() for v in (a.values() if isinstance(a, dict) else [a])]
    for v in values:
        try:
            top = Path(str(v)).relative_to(BENCH.root).parts[0]
        except (ValueError, IndexError):
            continue
        label = next((lb for lb in IDENTITY_KEYS if top in (lb, value(lb, "dir"))), "")
        if why := (board_missing(label) if label else bench_missing(f"{top}/")):
            return why
    return ""
