"""Which word of a captured block holds a drawn object's x, y and tile: proved against the screen.

THE TWO SIDES. A capture (`mame_capture`) keeps the block as it stood at every write to its
trigger, with the frame the write happened in. A `gfx_locate` answer whose matches all sit in ONE
window is an EVENT: on the screen of frame F, one object of a known layout sits at a known place,
and its tile is known when one tile matched there (a block that holds one image twice leaves the
place known and the tile not). Each role is tested only on the events where it is known.

THE PAIRING IS ONE TO ONE. An event of screen frame F pairs with the capture's row of frame
F - lag when that frame has exactly one row; none or several leave it unpaired, counted by
reason. "Agrees on every event" means something only when each event has one row to agree with.

A HYPOTHESIS is a unit (a word of the bus, or one byte of it), a role (`dest_x` and `dest_y`
from the match's window, `source_tile` from its tile), a sign and an `add`: it HOLDS when
`sign * unit + add` equals the role on every paired event, with at least `MIN_PAIRED` of them
and `MIN_VALUES` distinct values of the role, since a value that never moved proves nothing.
Coordinates stored reversed (`add - value`) are common, which is why the sign is part of it.

THE LAG IS ONE LAW. Every field of a draw is read in the same frame relation, so the lag is not
chosen per field: it is the lag at which both `dest_x` and `dest_y` hold, and there must be one.
None proves nothing; several (an object moving at a steady speed agrees at more than one lag)
prove nothing either, and the account says which. A role that holds only at another lag is not
assigned and is named (`elsewhere`): the block is read at the trigger, and a word the game
writes at another time of the frame is one frame off from the others.

AMBIGUITY IS REFUSED, NEVER RANKED. At the lag, a role two hypotheses hold is ambiguous, and so
is a unit holding two roles: neither is assigned. The one exception is not a ranking: a byte
and the word holding it that both hold a role with the same sign say the same thing about the
events, since the word's other bytes then held one value on every one of them (their share of
the word is what the two `add`s differ by), so the byte, the claim the evidence exercised, is
kept.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

LAGS = (0, 1, 2, 3)
SIGNS = (1, -1)
ROLES = ("dest_x", "dest_y", "source_tile")
MIN_PAIRED = 4
MIN_VALUES = 2


@dataclass(frozen=True)
class Event:
    """One object on one screen: a `gfx_locate` answer whose matches sit in one window."""

    locate: int          # the answer's number in the evidence
    frame: int
    dest_x: int
    dest_y: int
    source_tile: int | None     # None: several tiles matched the one window

    def role(self, name: str) -> int | None:
        value: int | None = getattr(self, name)
        return value


@dataclass(frozen=True)
class Unit:
    """A word of the block, or the byte of it `mask` selects."""

    word: int
    mask: int
    whole: bool
    word_bytes: int          # the bus word's width, which the `mask` text is written at

    def value(self, words: Sequence[int]) -> int:
        shift = (self.mask & -self.mask).bit_length() - 1
        return (words[self.word] & self.mask) >> shift

    def reply(self) -> dict[str, Any]:
        return {"word": self.word, "mask": f"0x{self.mask:0{2 * self.word_bytes}x}"}


@dataclass(frozen=True)
class Holds:
    unit: Unit
    role: str
    sign: int
    add: int

    def reply(self) -> dict[str, Any]:
        return {**self.unit.reply(), "role": self.role, "sign": self.sign, "add": self.add}


def units(words: int, word_bytes: int) -> list[Unit]:
    """Every word whole and, on a bus wider than a byte, each of its bytes."""
    full = (1 << 8 * word_bytes) - 1
    out = []
    for w in range(words):
        out.append(Unit(w, full, True, word_bytes))
        if word_bytes > 1:
            out += [Unit(w, 0xFF << 8 * k, False, word_bytes) for k in range(word_bytes)]
    return out


def split_words(block: bytes, word_bytes: int, endianness: str) -> list[int]:
    big = endianness == "big"
    return [int.from_bytes(block[i:i + word_bytes], "big" if big else "little")
            for i in range(0, len(block) - word_bytes + 1, word_bytes)]


def _pair(events: Iterable[Event], by_frame: dict[int, list[list[int]]], lag: int
          ) -> tuple[list[tuple[Event, list[int]]], int, int]:
    paired, no_row, several = [], 0, 0
    for ev in events:
        rows = by_frame.get(ev.frame - lag, [])
        if not rows:
            no_row += 1
        elif len(rows) > 1:
            several += 1
        else:
            paired.append((ev, rows[0]))
    return paired, no_row, several


def _holding(paired: list[tuple[Event, list[int]]], all_units: list[Unit]) -> list[Holds]:
    out: list[Holds] = []
    for role in ROLES:
        known = [(v, words) for ev, words in paired if (v := ev.role(role)) is not None]
        if len(known) < MIN_PAIRED or len({v for v, _ in known}) < MIN_VALUES:
            continue
        for unit in all_units:
            for sign in SIGNS:
                adds = {v - sign * unit.value(words) for v, words in known}
                if len(adds) == 1:
                    out.append(Holds(unit, role, sign, adds.pop()))
    return out


def _narrowest(holds: list[Holds]) -> list[Holds]:
    """Drop a whole word that says what one of its bytes already says (the module's
    exception): same role, same sign, whatever the add."""
    return [h for h in holds if not (h.unit.whole and any(
        o.unit.word == h.unit.word and not o.unit.whole and o.role == h.role
        and o.sign == h.sign for o in holds))]


Frames = dict[int, list[list[int]]]


def frames(rows: Iterable[tuple[int, bytes]], word_bytes: int, endianness: str) -> Frames:
    """A capture's rows as words, by the frame each was written in: decoded once per capture,
    whatever number of groups it is correlated with."""
    by_frame: Frames = {}
    for frame, block in rows:
        by_frame.setdefault(frame, []).append(split_words(block, word_bytes, endianness))
    return by_frame


def correlate(by_frame: Frames, events: list[Event], word_bytes: int,
              words: int) -> dict[str, Any]:
    """The account of one capture (`frames`) against one group of events: the pairing at every
    lag, the hypotheses that held, the lag chosen (or why none), and each role's verdict."""
    all_units = units(words, word_bytes)
    per_lag: dict[int, dict[str, Any]] = {}
    holding: dict[int, list[Holds]] = {}
    for lag in LAGS:
        paired, no_row, several = _pair(events, by_frame, lag)
        holding[lag] = _narrowest(_holding(paired, all_units))
        per_lag[lag] = {"paired": len(paired), "no_row": no_row, "several_rows": several,
                        "holds": [h.reply() for h in holding[lag]]}
    both = [lag for lag in LAGS
            if {"dest_x", "dest_y"} <= {h.role for h in holding[lag]}]
    out: dict[str, Any] = {"events": len(events), "lags": per_lag, "lag": None, "fields": {}}
    if len(both) != 1:
        out["why"] = ("no lag at which both dest_x and dest_y hold on every paired event"
                      if not both else
                      f"dest_x and dest_y both hold at lags {both}: the frame relation is not "
                      "settled, so no field is (events where the object changes speed settle it)")
        return out
    lag = out["lag"] = both[0]
    chosen = holding[lag]
    roles_of: dict[Unit, set[str]] = {}
    for h in chosen:
        roles_of.setdefault(h.unit, set()).add(h.role)
    for role in ROLES:
        cands = [h for h in chosen if h.role == role]
        if not cands:
            out["fields"][role] = {"status": "none"}
        elif len(cands) > 1:
            out["fields"][role] = {"status": "ambiguous", "why": "several units hold it",
                                   "holds": [h.reply() for h in cands]}
        elif len(roles_of[cands[0].unit]) > 1:
            out["fields"][role] = {"status": "ambiguous",
                                   "why": f"its unit also holds {sorted(roles_of[cands[0].unit])}",
                                   "holds": [cands[0].reply()]}
        else:
            out["fields"][role] = {"status": "proved", **cands[0].reply()}
        elsewhere = [{**h.reply(), "lag": other} for other in LAGS if other != lag
                     for h in holding[other] if h.role == role]
        if out["fields"][role]["status"] != "proved" and elsewhere:
            out["fields"][role]["elsewhere"] = elsewhere
    return out
