# ROOT CAUSE — why the English cards froze

## 1. The card had no motion of its own

`_draw_scene()` composed a card from constants: kicker, counter, headline, motif, caption, handle,
progress bar. `_draw_motif()` animated only for `kind == "network"`; for `chip`, `robot`, `shield`,
`sandbox` and `screen` the geometry was fixed. Two things moved: the caption's active-word highlight
(changes only when a word changes) and the progress bar (an 8 px tall rectangle, 1 080 px wide, at most).

Measured before the fix, on a held `shield` card: the picture was identical between consecutive frames
apart from a handful of pixels.

## 2. `freezedetect` is a whole-frame measurement

The gate compares frames over the whole 1 080 × 1 920 area with a -50 dB noise tolerance. -50 dB on 8-bit
is a mean absolute difference of about **0.8 grey levels**. A rotating ring of 36 arcs changes ~20 000
pixels out of 2 073 600: that is 0.45 grey levels on average, which the detector still calls a freeze. This
number, not the visual design, set the size of the fix.

## 3. The detector discarded a freeze that never ends

`_freeze_events()` only recorded `(start, end - start)` when `freeze_end` arrived. A stall that lasts until
the file ends emits only `freeze_start`. Consequences:

- the previous acceptance run's freezes at 18.3 s and 6.2 s were *mid-video* stalls, which is why they
  were caught at all;
- a video frozen from t to EOF reported **0.00 s** and passed.

This was found by the first regression test written for this assignment (`test_the_detector_still_calls_a_repeated_frame_a_freeze`), which encoded six seconds of a byte-identical frame and got `[]` back.

## 4. Partial fixes and what each measurement showed

| Attempt | Measurement | Verdict |
| --- | --- | --- |
| Linear push-in, 0.0012/s + sine "breath" | academic froze 1.5 s at 3.4 s: the breath's derivative cancelled the ramp | failed, and taught that a stall is any zero-velocity window |
| Linear push-in only, 0.003/s, capped at 6 % | tail froze 2.0 s at 38.0 s (cap reached at 20 s) | failed |
| + rotating accent ring (drawn before the motif) | only 0.28 grey levels of change - the motif plate painted over it | failed silently |
| + ring drawn on top | 0.45 grey levels a second: still under the 0.8 floor | failed |
| + broad light sweep, two passes half a period apart | no freeze in a 22 s hold, 128 ms/frame | **passes** |
