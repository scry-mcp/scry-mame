"""Live-tier boards by label; the real set names live only in the bench's `identity.json`."""

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


BENCH = bench.Bench(_root())
IDENTITY = BENCH.root / "identity.json"

IDENTITY_KEYS: dict[str, tuple[str, ...]] = {
    "m68k-dual": ("dir", "system", "binary", "reference_rom", "symbols", "sub_rom",
                  "sub_symbols", "blit_handler"),
    "m68k-dual-alt": ("dir", "system", "binary", "reference_rom"),
    "v30": ("dir", "system", "rom_segment"),
    "v30-alt": ("dir", "system", "reference_rom"),
}

#: The one MAME the free boards and the games' boards run on, the build the games are developed
#: on; the two m68k-dual labels name a `binary` of their own and run outside it.
BINARY = os.environ.get("MAME_BINARY", "")
GAME_BOARDS = ("v30", "v30-alt")

PATH_KEYS = frozenset({"binary", "reference_rom", "symbols", "sub_rom", "sub_symbols"})

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
    """Raise on a label or key the code does not declare."""
    if key not in IDENTITY_KEYS.get(label, ()):
        raise KeyError(f"no identity key {label}.{key}: declare it in IDENTITY_KEYS")


def identity_missing(label: str) -> str:
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
    """A board's `dir` is one name, which is how a path is traced back to its board."""
    if Path(directory).name != directory or directory in (".", ".."):
        return (f"identity {label}.dir is {directory!r}, not one directory name: set it in "
                f"{IDENTITY}")
    return ""


def value(label: str, key: str) -> str:
    """`label`'s `key`, or empty when its identity is unusable (`board_missing` reports it)."""
    _known(label, key)
    return "" if identity_missing(label) else str(_DOC[label][key])


def board_dir(label: str) -> Path:
    """`label`'s directory; its own name when the identity is unusable."""
    return BENCH.root / (value(label, "dir") or label)


def board_path(label: str, key: str) -> str:
    return str(board_dir(label) / value(label, key))


def bench_missing(prefix: str) -> str:
    return BENCH.missing(prefix)


def opened(label: str) -> list[str]:
    files = [value(label, k) for k in IDENTITY_KEYS[label] if k in PATH_KEYS]
    files += [f"{ROMPATH}/{value(label, 'system')}.zip", *_OPENED[label]]
    return [f"{value(label, 'dir')}/{f}" for f in files]


def _unpinned(label: str) -> str:
    """The first file `label` opens that the manifest does not pin, as a reason, or empty."""
    try:
        pinned = BENCH.pinned
    except verdict.Invalid as e:
        return f"bench {e}"
    off = next((p for p in opened(label) if p not in pinned), None)
    return "" if off is None else (
        f"board {label} opens {off}, which {BENCH.manifest} does not pin: pin it there, or "
        "name a file it pins")


def binary_missing() -> str:
    """Why `BINARY` cannot run here, or empty."""
    return "" if BINARY and Path(BINARY).is_file() else (
        "set MAME_BINARY to the MAME the boards run on, its plugins beside it")


def board_missing(label: str) -> str:
    """Why the board `label` cannot run here, or empty."""
    return (identity_missing(label) or bench_missing(f"{value(label, 'dir')}/")
            or _unpinned(label) or (binary_missing() if label in GAME_BOARDS else ""))


def m68k_dual_missing() -> str:
    return board_missing("m68k-dual")


M68K_DUAL_BINARY = board_path("m68k-dual", "binary")
M68K_DUAL_SYSTEM = value("m68k-dual", "system")
M68K_DUAL_ROMS = str(board_dir("m68k-dual") / ROMPATH)
REFERENCE_ROM = board_path("m68k-dual", "reference_rom")
SYMBOLS = board_path("m68k-dual", "symbols")
SUB_ROM = board_path("m68k-dual", "sub_rom")
SUB_SYMBOLS = board_path("m68k-dual", "sub_symbols")
MANIFEST = str(board_dir("m68k-dual") / GFX_MANIFEST)
BLIT_HANDLER = value("m68k-dual", "blit_handler")

#: An ini that turns joysticks off: a debug MAME aborts at boot while a game controller is
#: connected (`boot_failures.SDL3_JOYSTICK_NOTE`), and the bench's owner may be using one.
NO_JOYSTICK_INI = str(Path(__file__).resolve().parent / "fixtures" / "ini-no-joystick")

M68K_DUAL_ALT_BOOT = dict(binary=board_path("m68k-dual-alt", "binary"),
                     system=value("m68k-dual-alt", "system"),
                     rompath=str(board_dir("m68k-dual-alt") / ROMPATH),
                     reference_rom=board_path("m68k-dual-alt", "reference_rom"),
                     reference_addr="0x0", inipath=NO_JOYSTICK_INI)


def args_missing(args: dict[str, object]) -> str:
    """Why a call taking `args` cannot be made, or empty; paths off the bench are not judged."""
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
