# TEST_RESULTS

Executed results only. Anything not executed is marked as such.

Last run: 2026-11-21 (branch `feat/landscape-16x9`, base `main` @ `567e63c`).

## 1. Automated suites

| Suite | Command | Result |
| --- | --- | --- |
| Everything | `python -m pytest tests -q` | **92 passed** |
| Uploader (no third-party deps) | `python -m unittest discover -s tests` | **50 passed** |
| Factory (plan/publish gates/deps) | `python -m pytest tests/factory -q` | **42 passed** |
| Landscape 16:9 profile | `python -m pytest tests/factory/test_landscape.py -q` | **13 passed** |
| Compile | `python -m compileall -q uploader factory studio` | clean |

CI (GitHub Actions): `ci.yml` green on `main` (`44793933361`, `44797303730`) and on the
PR #2 head `2a810f0` (`44795656327`). The `factory` job runs on the runner: PyCairo
builds, ffmpeg is installed, `doctor` passes, 42 tests pass.

## 2. Shorts renders (9:16, 1080x1920) — verified

| Episode | Duration | QC | Notes |
| --- | --- | --- | --- |
| `academic-brain-wash` | ~38 s | pass | earlier session artifact, on disk |
| `nexus-agents-leave-chat` | ~40 s | pass | earlier session artifact |
| `natkhat-haveli-e1` | 32.07 s | `qc_ok: true` | re-rendered after the studio restore |
| `natkhat-haveli-e2`, `e3` | ~32–33 s | pass | earlier session artifacts |
| `academic-post-meal-walk` | 38.36 s | `qc_ok: true` | **auto-generated plan** |
| `natkhat-haveli-e4` | 31.63 s | `qc_ok: true` | **auto-generated episode (series continuity)** |

All are 1080x1920, h264 + aac, within the 20–65 s Shorts window, with thumbnail, SRT and
`qc.json` beside them.

## 3. Long-form render (16:9, 1920x1080) — verified

Plan: `long-nexus-power-grid` — *The Real Limit on AI Is Not Chips* (332 words,
8 beats, 4 chapters, 2 sources).

```
ffprobe:
  video   h264  1920x1080  30/1
  audio   aac   44100 Hz   2 ch
  duration 116.466667 s    size 6,905,576 bytes    bit_rate 474 kb/s
factory result: duration 116.467  qc_ok true  qc_errors []  cue_count 52
```

Audio: `volumedetect` mean **−29.3 dB**, peak **−11.4 dB**; `silencedetect`
(noise −45 dB, 1 s) reported **no silence segments**, so narration runs continuously
without dead air.

Subtitles: 52 cues, first cue `00:00:00,220 --> 00:00:02,875`
"…a shortage of chips…", last cue ends inside the video. Cue wording tracks the script
verbatim, so captions are word-accurate; timing comes from Edge-TTS word boundaries.

Visual inspection: contact sheet plus individual frames at 0.5 s, 12 s, 30 s, 60 s.
Confirmed on screen — 16:9 composition (text column + diagram plate), brand chrome,
scene counter `01 / 11`, chapter kickers that keep the active chapter, chapter cards,
animated motifs (dot grid, radial clock, bars, node graph), word-synced caption with
the active word highlighted, progress rail with chapter ticks.

Defects found by inspection and fixed during this pass:

1. Body copy collided with the caption band on 3-line headlines → `_body_block` now
   fits the text between the rule and the caption, shrinking the font if needed.
2. Chapter cards were 93 % opaque, so the underlying frame ghosted through → solid fill,
   plus an oversized ghost numeral for depth.
3. Chapter kicker fell back to the brand tag between chapter starts → chapter mapping is
   now forward-filled for every line.
4. Chapter cards appeared on every line (regression from the forward-fill fix) → card
   triggers only on `chapter_starts`.
5. Dense motifs (grid/chip) bled outside the plate → motifs render on their own layer and
   are masked to the panel.

## 3b. Loudness remediation (measured)

The produced mix was far too quiet for YouTube (which normalises toward −14 LUFS):

| Reading | Before | After the fix |
| --- | --- | --- |
| Integrated loudness | **−26.53 LUFS** | **−14.15 LUFS** |
| True peak | −11.44 dBTP | −1.24 dBTP (ceiling −1.5 target, ≤ −1.0 hard limit) |
| Loudness range (LRA) | 2.10 LU | 2.00 LU |
| A/V duration | video 116.4667 s / audio 116.4480 s | video 116.4667 s / audio 116.4580 s |

`factory/media/music.py` now mixes with `sidechaincompress` (bed ducked by narration)
plus a two-pass **linear** `loudnorm` to I=−14, TP=−1.5, LRA=11, then trims/pads to the
exact episode duration so sync cannot drift. Remix cost: **15.5 s**; re-muxing the
existing video with `-c:v copy` took seconds and preserved the picture bit-exactly.

Four new tests (`tests/factory/test_audio.py`) assert the target loudness, the quiet-input
lift, duration preservation and NaN-free measurement. Full suite: **96 passed**.

Not verified: subjective narration clarity by ear; ducking depth is only proven by the
loudness/duration measurements, not by a listening test.

## 3c. Lip-sync (audio-driven) — measured

Openness now comes from the narration itself (`studio/characters/lipsync.py`): ffmpeg
decodes the voice track to 16 kHz mono, a per-frame RMS envelope is normalised to the
95th percentile and smoothed with attack/release, then mapped onto the existing `Viseme`
states.

| Check | Result |
| --- | --- |
| Automated tests | **10 passed** (`tests/factory/test_lipsync.py`); suite **106 passed** |
| Rig behaviour | track-driven frames 0–5 → `mouth_open = 0.0`; frames 6–11 → `> 0.5`; values differ from the old sine |
| Silent track | all 30 frames closed, `speaking_at()` false everywhere |
| Real narration (scene 2, 5.33 s) | 160 frames, speaking ratio **0.79**, gaps visible between phrases |
| Full episode re-render | `natkhat-haveli-e1` 32.07 s, `qc_ok: true`, 10 cues, rendered through the wired path |
| Mouth-region pixel probe (0.1 s sampling) | speech-like on/off pattern in the first 16 s (wide 199 frames, shut 6, max 1153 px vs min 26 px) |

**Limitation, stated plainly:** the pixel probe uses a fixed crop, so camera pans and
pose-driven expression mouths (e.g. `excited_jump` opens the mouth while silent by design)
make it unreliable after ~16 s. Lip-sync is proven by the rig tests and the narration
envelope, not by a whole-episode per-frame mouth measurement. Visemes are also
**envelope-based, not phoneme-based** — a wide vowel and a loud consonant look the same.

## 3d. Viseme lip-sync (T31b) — measured

Edge-TTS timing was probed directly (4 calls, 3 voices). **Only `SentenceBoundary` is
emitted — no `WordBoundary` at all** for `hi-IN-MadhurNeural`, `hi-IN-SwaraNeural` or
`en-US-AndrewNeural`, including a mixed Hindi/English line. Word-level timing therefore
does not exist; viseme placement inside a sentence is a documented **proportional
approximation**, not phoneme-level.

| Check | Result |
| --- | --- |
| Unit tests | **30 passed** (`tests/factory/test_visemes.py`), full suite **136 passed** |
| Shapes implemented | closed lips, neutral rest, smile, wide (E/I), teeth (F/V, sibilants), tongue (L/D/T/N), open small (schwa), open wide (A), round (O/U), surprised |
| Scripts | Hindi Devanagari (independent vowels, matras, virama conjuncts, nukta forms, word-final schwa deletion) and Latin/English (digraphs `sh`/`ch`/`th`/`ph`, silent final `e`) |
| Hard Hindi words | क्षत्रिय, श्रृंगार, विद्यालय, अंतर्राष्ट्रीय, ज़िम्मेदारी, लड्डू, राक्षस — all map without error |
| Mixed line | "यह video बहुत अच्छा है, subscribe करो!" produces Hindi + English shapes and a pause |
| Flicker control | median filter + minimum hold (70 ms) + one-frame softened transitions; merged again after silence masking |
| Change rate | **6.2–7.1 shapes/s** per scene (speech-like; assertion bounds 1.5–12) |
| Hold times | median **100–133 ms**, minimum speaking run **67 ms** |
| Mouth active during voiced audio | **93.3 %** of voiced frames |
| Onset lag vs acoustic voice (14 voiced segments) | median **0 ms**, max **67 ms** (2 frames) |
| Boundary sidecars | `.boundaries.json` written next to cached TTS audio, reloaded on cache hit; corrupt file ignored (tested) |
| Rendered episode | `natkhat-haveli-e1`, 32.07 s, 1080×1920, 961 frames, h264+aac, `qc_ok: true`, 10 cues |
| Frame inspection | 32 crops at 1 fps across the whole episode show ≥6 distinct mouth shapes, closed rest between lines, no single-frame flicker |

**Documented limitation:** within a sentence the sequence is spread proportionally over the
sentence window (snapped to the voiced region), so a syllable can be early or late by up to
roughly one unit — median unit length ≈ 100 ms. True phoneme accuracy is not claimed and is
not obtainable from this TTS backend.

## 3e. Character schema (T30) — measured

Characters are now defined by data (`content/characters/{chiku,gappu}.json`) validated by
`studio/characters/schema.py`. Both rigs read palette, proportions, timing profile, anchor,
feature flags and mouth configuration from that file.

| Check | Result |
| --- | --- |
| Schema tests | **31 passed** (`tests/factory/test_character_schema.py`), full suite **168 passed** |
| Validation rules | missing field, unknown archetype, unsupported version, missing colour, colour outside 0..1, missing/non-numeric proportion, missing/zero timing, unknown feature, bad anchor, missing file, unknown id (lists available), invalid JSON |
| Render parity — isolated rigs | **8/8 frames byte-identical** (SHA-256) to the pre-schema goldens: Chiku idle / excited_jump / shocked_freeze / talking, Gappu idle / excited_jump / embarrassed_smile / talking |
| Render parity — episode | `natkhat-haveli-e1` re-rendered: **187/187 scene-1 frames bit-identical**, 660/961 frames identical overall, **min PSNR 49.0 dB**, none below 40 dB |
| Why 301 frames differ | all of them fall inside scenes 2–3 (frames 187–529), the two scenes whose narration MP3 was deliberately re-synthesised to restore real sentence boundaries. Audio MD5 differs (`bd31e6…` vs `85168f…`), so the *input* changed, not the drawing. Scene 1 and scenes 4–5 (untouched audio) are bit-identical |
| Data-driven construction | 3 variant characters built from modified dicts (recolour+biger head, tiny head, bigger mouth) render and **differ** from the base character — no code change needed |
| Backward compatibility | `ChikuRig(x=380, y=1450, scale=1.35)` and `GappuRig()` behave as before; legacy `COLOR_*` module constants survive, now sourced from JSON |
| Lip-sync regression | T31a envelope path and T31b timeline path both re-tested through the schema-driven rigs |

**Remaining hard-coded geometry (documented, not hidden):** tail bezier control points, hair
tuft, vest curves, whiskers, spectacles and bowtie are archetype-level drawing routines; their
*positions* come from the schema but their *shape* is code. Moving those curves into data is
T30b.

## 3f. Eyes, gaze, blinking and expressions (T32) — measured

New `studio/characters/gaze.py` (behaviour) + `studio/characters/eyes.py` (rendering), shared by
both rigs. Eyes are now driven by a per-character `FaceController` built from the scene.

| Check | Result |
| --- | --- |
| Tests | `tests/factory/test_gaze.py` **32 passed**; full suite **200 passed** |
| Legacy parity | the golden frames are still **byte-identical** — the old eye path is preserved inside `draw_eyes(state=None)` |
| Render | `natkhat-haveli-e1` re-rendered: 1080x1920, 30 fps, **961 frames**, 32.066 s, 3 459 072 B, h264+aac, QC ok, 0 errors, 81 s wall |
| Blinks | chiku **28.1/min**, gappu **20.6/min**; median interval 2.1–5.4 s; 12-frame 30 fps strip shows real eyelid travel (open → half → slit → open), not a cut |
| Gaze | chiku **41 gaze moves/min**, gappu **58/min**; a frame sampled mid-scene shows gappu's pupils rotated to his left, i.e. at chiku |
| Expressions used in the episode | chiku: excited 39 %, shy 24 %, surprised 21 %, proud 16 % · gappu: thinking 60 %, happy 24 %, suspicious 16 % |
| Eyelid geometry | aperture height by expression (chiku, 1.8x rig): neutral 71 px, surprised 75, suspicious 67, happy 61, angry 60 |
| Data-driven | blink jitter, double-blink chance, close fraction, saccade rate, travel time, micro-saccade, lash/brow width, catchlight size/offset/alpha and closed-eye curve all come from `content/characters/*.json` |

**Limitations (stated, not hidden):** gaze is a 2D plane model with a fixed small convergence
term — there is no depth/vergence target; blink intervals are seeded jitter, not a biological
distribution; eyebrow offset is clamped to ±18 px so a pose + expression cannot climb into the
hairline; the 0.05 convergence constant is an artistic choice, not a measurement.

## 3g. Locomotion and body mechanics (T33) — measured

`studio/characters/locomotion.py` turns one of sixteen named motions into a per-frame
`BodyState` (hip offset, jump offset, lean, leg and arm angles, head tilt, squash), applied
on top of the pose by both rigs.

| Check | Result |
| --- | --- |
| Tests | `tests/factory/test_locomotion.py` **25 passed**; full suite **225 passed** |
| Motions | idle, walk, walk_in, walk_out, run, run_in, jump, land, turn, lean, sit, stand_up, wave, point, shake_head, nod |
| Gait | walk period measured at **1.05 s** (±0.08) with legs in antiphase for >55 % of frames; run has larger stride and lean |
| Jump | leaves the ground (peak −120 px), anticipates with a squash below 0.95, stretches above 1.0 in the air, settles on landing |
| Jump-in / jump-out | `walk_in` starts 300 px off-stage and arrives exactly at the anchor; `walk_out` leaves *away* from the partner (fixed after the first demo render had them walk through each other) |
| Real render | `motion-demo` episode produced end to end through `EpisodePipeline`: **695 video frames, 23.20 s, 1080x1920, h264+aac, 2 700 512 B**, 5 scenes, 69 s wall |
| Inspected frames | walk-in from the left, walk-in from the right, pointing, airborne jump, and a two-character exit where each leaves in the opposite direction |
| Composition | pose + motion + lip-sync + eyes all active in the same frame (asserted in tests and visible in the demo) |

**Bug found and fixed during this milestone:** `apply_body` added motion to the previous
frame's pose values, so any pose that did not explicitly reset a limb accumulated motion —
the first demo render had Gappu drifting into the sky. Rigs now reset the animated fields
each frame before posing. Consequence measured honestly: the natkhat episode re-render is
bit-identical for scene 1 but differs in scenes 2–5 (PSNR ≥48.4 dB, background pixels
identical, i.e. no camera change). Those poses (`boast_proud`, `skeptical_eyebrow`) are not
covered by the golden set, which is a real gap in the goldens, not a rendering defect.

## 3h. Per-pose goldens (T30b, partial) — measured

The four-pose golden set could not see a change to `boast_proud` or `skeptical_eyebrow`,
which is how the T33 state reset slipped past the suite.

- `tools/capture_goldens.py` renders **78 frames**: 13 story poses × 3 timestamps ×
  (silent, talking) for both characters, and records SHA-256 in
  `tests/factory/goldens/poses.json`.
- `tests/factory/test_pose_goldens.py` (3 tests) re-renders and compares, checks every pose
  is covered and that the manifest has no orphans. Suite total: **228 passed**.
- This pins the drawing of every pose the story engine can request, so the next refactor
  cannot change one silently.

## 4. Not yet executed

| Test | Status |
| --- | --- |
| Render on a GitHub Actions runner | **Not executed** — `produce-*` workflows are disabled; PR #2 (installer hardening) is unmerged |
| Edge-TTS network egress from a runner | **Not proven** |
| Chrome-driven overlays on a runner | **Not proven** (Chrome is present; the renderer has not driven it there) |
| Controlled YouTube upload of a produced video | **Not executed** — no secrets provisioned, uploads remain private/off |
| Persistence across workflow termination | **Not executed** (cache wiring exists, never ran) |
| Retry/recovery drill | **Not executed** |
