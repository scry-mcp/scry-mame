---
paths:
  - "demos/**"
---

# The demos are deterministic

A published demo runs on hosts of very different speed and load, so no step depends on either.
A step that needs the program to have reached a place gets there by a control, the first of
these the program offers:

1. a symbol (`run_to`), a breakpoint or a watch on a variable;
2. what the program writes about itself (`log_wait`);
3. `screen_wait` judged only at a declared stop (`on_breakpoint`, `on_watch`, with a
   `condition` to filter the firings);
4. `screen_wait` sampling frames, only when the program offers nothing above, and the demo says
   why where it does it.

`run_for` counts emulated time from a fixed start, so the same span runs the same instructions on
any host: a demo may run one and then assert what it produced (a credit counted, a frame
reached), and a screen or value that a symbol, a breakpoint or a watch could reach is reached by
that control instead.

- **What the host decides is declared volatile, each key with its true reason**: the window, a
  position in the emulator's log (Windows writes CRLF), a compressed state's size, a recording's
  digest where the platform's mix differs. A value the demo checks or shows is never hidden.
- **A picture is the same picture when its pixels are**: each host's zlib writes other bytes, so
  the committed `screen.png` is judged by its pixels and a transcript hides a picture's `bytes` and
  `sha256`. A recording that differs by platform has its own reference under the same name
  (`win32/music.wav`), its path declared a host argument so the transcript reads the same.
- **A changed demo is proved twice on each host it runs on**: the same normalised transcript both
  runs, the same pixels, and across hosts only what is declared. A second run that differs means
  the demo is not deterministic yet, never a flake to rerun.
- **A demo's loop is drawn over from the run's own timeline.** The runner writes a timeline beside the transcript: each call with the frames it spanned and the input its step sent. A step that sends input names it (`Step.events`: the keys or port fields, and on DOSBox-X the pointer and its buttons), taken from the reply and never typed by hand. A clip is drawn from the pass of the run it was recorded in, so a state load that rewinds the frames cannot show a stretch from another pass. A loop whose run wrote no timeline is refused.
- **A step waits as the rule above says, so the clip repeats.** On DOSBox-X, `send_keys` and `send_mouse` to a running guest carry the frames they went in between (`frame_before`, `frame_after`), and a moment after such a step is placed by `frame_after`.
