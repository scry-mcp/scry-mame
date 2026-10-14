"""The boards the live scripts run on the bench, and why one cannot run: their copies, pinned by
`scry_core.live_bench` in `bench.json` beside this file, one directory per board under the bench's
root (`MAME_LIVE_BENCH`).

A board whose copies are absent or off their pins is BLOCKED naming the file; the free boards of
mamedev.org run without a bench. Every reason is hashed once per run.
"""

from pathlib import Path

from scry_core import live_bench as bench

#: The tracked manifest of every file the live tier reads from the bench.
BENCH_MANIFEST = Path(__file__).resolve().parent / "bench.json"
BENCH = bench.root("mame")
RADENDUR = BENCH / "radendur"
_reasons: dict[str, str] = {}

# radendur, the board every live script drives, how it proves itself against the ROM on disk,
# and the project's own graphics manifest, which the radendur sections read.
RADENDUR_BINARY = str(RADENDUR / "upstream/radendu")
RADENDUR_ROMS = str(RADENDUR / "run/mame_roms")
REFERENCE_ROM = str(RADENDUR / "disasm/img/radendur_maincpu.bin")
SYMBOLS = str(RADENDUR / "disasm/symbols-radendur_maincpu.yaml")
SUB_ROM = str(RADENDUR / "disasm/img/radendur_subcpu.bin")
SUB_SYMBOLS = str(RADENDUR / "disasm/symbols-radendur_subcpu.yaml")
MANIFEST = str(RADENDUR / "hardware" / "gfx.yaml")

# rltennis: a second 68000 board, driven by section V.
RLTENNIS = BENCH / "rltennis"
RLTENNIS_BOOT = dict(binary=str(RLTENNIS / "upstream/rltennis"), system="rltennis",
                     rompath=str(RLTENNIS / "run/mame_roms"),
                     reference_rom=str(RLTENNIS / "disasm/img/rltennis_maincpu.bin"),
                     reference_addr="0x0")


def bench_missing(prefix: str) -> str:
    """Why the copies under `prefix` (a board's directory, `lineup/`, or one file) cannot be
    used, or empty when every one matches its pin."""
    if prefix not in _reasons:
        _reasons[prefix] = bench.missing("mame", BENCH_MANIFEST, prefix)
    return _reasons[prefix]


def radendur_missing() -> str:
    """Why radendur, the bench board every script drives, cannot run here, or empty."""
    return bench_missing("radendur/")


def args_missing(args: dict[str, object]) -> str:
    """Why a call taking `args` cannot be made, or empty: every argument that is a path on the
    bench (a symbol table, a manifest, a binary, the values of a dict of them) needs its board's
    copies on their pins. A path off the bench is not the bench's to judge."""
    values = [v for a in args.values() for v in (a.values() if isinstance(a, dict) else [a])]
    for value in values:
        try:
            board = Path(str(value)).relative_to(BENCH).parts[0]
        except (ValueError, IndexError):
            continue
        if why := bench_missing(f"{board}/"):
            return why
    return ""
