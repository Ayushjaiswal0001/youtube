# IMPLEMENTATION

Three changes, all in code that already existed.

## `factory/media/english_renderer.py`

1. **`compose_frame(base, lines, t, duration, spec, brand)`** — the body of the encode loop, extracted so
   the tests measure the same pixels the encoder writes. No behaviour change on its own.
2. **`camera_scale(t)` / `apply_camera_drift(frame, t)`** — a linear push-in, `1 + min(0.060, 0.0030·t)`,
   applied as a BILINEAR centre crop. Constant velocity so it never stalls; capped so the composition
   never becomes a crop of a crop. An earlier version added a sine breath, which created a zero-velocity
   window at 3.4 s and a fresh freeze; that is removed and documented in the docstring.
3. **`_draw_motion_ring()`** — two counter-rotating dashed accent rings (24 segments each) plus six
   orbiting dots around the motif, drawn *after* the motif so the opaque motif plate cannot cover them.
   Angular rate 0.55 rad/s, constant, so it keeps moving for any duration. It sits in the empty band
   around the motif: no type and no safe margin is touched.
4. **`_sweep_band()` / `apply_light_sweep()`** — a soft band of accent light crossing the card every 6.5 s,
   two passes half a period apart so one band is always on screen. Implemented as a flat-colour masked
   paste by PIL rather than numpy arithmetic on the frame: the first version cost 60 ms a frame, the paste
   costs about 5 ms. This is the element that clears the whole-frame noise floor.
5. Base image is converted to RGB once per frame so the post passes never re-enter mode conversion.

All four are pure functions of `t` (plus the fixed spec), so the render stays deterministic and the
existing cache/idempotency semantics are untouched.

## `factory/qa/validator.py`

**`_freeze_events()` now closes a trailing freeze at the container duration** via a new
`_duration_seconds()` (`ffprobe format=duration`). This makes the gate *stricter*, not looser: it can now
report a stall that previously measured zero.

## `factory/media/music.py`

**A brick-wall limiter after normalisation** (`alimiter=limit=0.89:level=disabled`, ≈ -1.0 dBFS). With the
freeze fixed, `audio_loudness` surfaced on academic-biohacker at **-0.7 dBTP** against a -1.0 dBTP limit:
`loudnorm` targets -1.0 dBTP in linear mode, and AAC encoding overshoots it. The gate is unchanged; the mix
leaves headroom for the codec. Measured after: **-14.3 LUFS / -1.5 dBTP**.

## Regression tests — `tests/factory/test_english_motion.py` (15 tests)

- the detector still calls a repeated frame a freeze (the reproduction);
- a held card is never frozen, per English channel, through a real libx264 encode;
- every motif kind changes more than 2 % of pixels in a second;
- consecutive frames always differ, never by more than 4 grey levels (no jump, no flicker);
- the headline keeps more than 2 000 bright pixels in its safe area and its contrast does not swing more
  than 25 % between 0.5 s and 6 s;
- the camera curve starts at 1.0, never decreases, and never exceeds the cap;
- identical inputs produce byte-identical frames;
- a 16 s hold with no caption change never freezes in its last 4 s (the tail defect);
- the Hindi renderer contains no `compose_frame` / `camera_scale`, so Natkhat's pipeline is untouched.
