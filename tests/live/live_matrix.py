"""Every tool of the server against a real MAME, in every state and at every edge."""

import importlib

from live_harness import run_sections
from matrix_acceptance import register_h
from matrix_audio import register_l
from matrix_comments import register_m
from matrix_console import register_c16
from matrix_cpus import register_r
from matrix_focus import register_x_control, register_x_verdict
from matrix_inputs import register_o
from matrix_landing import register_v
from matrix_lifetime import register_p
from matrix_media import register_y
from matrix_multicpu import register_s
from matrix_palette_stamps import register_u
from matrix_presence import register_z
from matrix_stamps import register_t
from matrix_states import register_q
from matrix_traces import register_n
from matrix_watch_tick import register_w

# A section registers when its module is imported, so this order is the run's: X's control opens
# it, H and X's verdict close it.
INLINE_SECTIONS = ("matrix_tools_by_state", "matrix_edges", "matrix_pairs", "matrix_gfx_boards",
                   "matrix_manifest", "matrix_film", "matrix_cpu_info", "matrix_scan",
                   "matrix_links")

register_x_control()
for name in INLINE_SECTIONS:
    importlib.import_module(name)
register_c16()
register_l()
register_m()
register_n()
register_o()
register_p()
register_q()
register_r()
register_s()
register_t()
register_u()
register_v()
register_w()
register_y()
register_z()
register_h()
register_x_verdict()


def main() -> None:
    run_sections("LIVE MATRIX")


if __name__ == "__main__":
    main()
