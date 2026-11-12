"""Lua compared by its code."""
from __future__ import annotations

import re


def squash(text: str) -> str:
    flat = re.sub(r" ?([{}()\[\],]) ?", r"\1", re.sub(r"\s+", " ", text)).strip()
    return re.sub(r",([}\])])", r"\1", flat)


def has(script: str, piece: str) -> bool:
    return squash(piece) in squash(script)
