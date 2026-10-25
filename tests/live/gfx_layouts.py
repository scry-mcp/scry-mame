"""Layouts transcribed from MAME's drivers, in their own spelling.

Gridlee has no `GFXDECODE`; its layouts are implied by `gridlee_v.cpp`. `BYTES_8X8` is no driver's.
"""

from typing import Any

CIRCUS_CHAR: dict[str, Any] = {
    "name": "charlayout", "width": 8, "height": 8, "planes": 1, "planeoffset": [0],
    "xoffset": "{ 0, 1, 2, 3, 4, 5, 6, 7 }",
    "yoffset": "{ 0*8, 1*8, 2*8, 3*8, 4*8, 5*8, 6*8, 7*8 }", "charincrement": "8*8"}
GRID_SPRITE: dict[str, Any] = {
    "name": "sprite", "width": 8, "height": 16, "planes": 4, "planeoffset": "{ 0, 1, 2, 3 }",
    "xoffset": "{ STEP8(0,4) }", "yoffset": "{ STEP16(0,32) }", "charincrement": "64*8"}
GRID_FB: dict[str, Any] = {
    "name": "framebuffer", "width": 8, "height": 8, "planes": 4, "planeoffset": [0, 1, 2, 3],
    "xoffset": "{ STEP8(0,4) }", "yoffset": "{ STEP8(0,128*8) }", "charincrement": 32}
WITCH_TILE: dict[str, Any] = {
    "width": 8, "height": 8, "planes": 3, "planeoffset": "{ 0, RGN_FRAC(1,3), RGN_FRAC(2,3) }",
    "xoffset": "{ 0, 1, 2, 3, 4, 5, 6, 7 }",
    "yoffset": "{ 0*8, 1*8, 2*8, 3*8, 4*8, 5*8, 6*8, 7*8 }", "charincrement": "8*8"}
BYTES_8X8: dict[str, Any] = {
    "width": 8, "height": 8, "planes": 1, "planeoffset": [0], "xoffset": "{ STEP8(0,1) }",
    "yoffset": "{ STEP8(0,8) }", "charincrement": "8*8"}
