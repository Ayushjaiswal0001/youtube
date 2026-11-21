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

## 3i. Data-driven drawing shapes (T30b) — measured

Tail beziers, the vest panels, the hair tuft, the chest patch, the buttons, the bowtie, the
knot, the whiskers and the nose shine are now `shapes` data in `content/characters/*.json`,
interpreted by `studio/characters/shapes.py`.

| Check | Result |
| --- | --- |
| Pixel parity | `python -m tools.capture_goldens --check` → **78 frames, 0 changed, 0 new** |
| Manifest goldens | the eight original frames still reproduce byte-for-byte |
| Suite | **228 passed** |
| Validation | unknown shape kind, unknown path command, wrong argument count, non-numeric coordinate, bad `[x, y]`, wave length mismatch, colour missing from the palette and missing archetype-required shapes all raise a readable `SchemaError` |
| Still code | spectacles (lenses, glints, bridge), ear/hand/foot placement (already proportions), and the muzzle mask |

## 3j. Performance layer (T34) — measured

Reaction beats derived from the spoken line: the listener nods, recoils or widens; the
speaker bounces on a shout and tilts on a question.

| Check | Result |
| --- | --- |
| Unit tests | 33 in `tests/factory/test_performance.py`; suite **259 passed** |
| Beats in `natkhat-haveli-e1` | **23 beats** across 5 scenes; coverage 2.6 %–27.3 % of frames |
| Determinism | the same scene rendered twice is byte-identical (sha256 of the MP4) |
| Scope (frame level, codec-independent) | every frame **before** the first beat is byte-identical to the render with the layer off; frames inside a beat differ |
| Scope (video level) | with vs without, first differing frame 89 vs first beat at frame 94 — the nine frames of lead-in are x264 lookahead, which is why the frame-level test above is the authoritative check |
| Body actually moves | eye-centroid x shifts **241.3 → 218.8 px** at t=1.10 s during a recoil, and matches within 0.2 px at t=0.80 s and t=1.60 s |
| Render | `natkhat-haveli-e1` 1080×1920, 961 frames, 32.066 s, 3 581 961 B, `qc_ok: true` |
| Kill switch | `FACTORY_NO_PERFORMANCE=1` reproduces the pre-T34 frames exactly, used for the A/B |

Honest caveat: the first A/B attempt compared two build directories whose TTS caches held
**different narration MP3s** (md5 `850cab55…` vs `1c673ef3…`), so that comparison was
contaminated and discarded. The numbers above come from renders sharing one audio file.

## 3k. Camera direction and vignette (T35) — measured

The renderer used to set one of two fixed zooms and a slow sine pan, so `close_up_chiku`
zoomed the middle of the frame rather than framing Chiku, and a panned frame exposed a bare
strip where the background art ended.

| Check | Result |
| --- | --- |
| Tests | 13 in `tests/factory/test_camera.py`; suite **274 passed** |
| Close-up framing | the subject's face projects to **x = 540** (frame centre) and **y ≈ 806**; the partner projects to **x > 1180**, i.e. fully outside, checked numerically |
| Partner cropping | a close-up draws only its subject, so no half-character sliver at the edge |
| Camera maths | `project()` verified against the real cairo transform by rendering a marker and locating it (agreement within 2 px) |
| Push-in | monotonic 1.06 → 1.70 over 0.9 s; `two_shot_zoom` 1.00 → 1.13; `wide_finish` 1.12 → 1.00 |
| Pan safety | `medium_pan` stays within ±30 px and never jumps more than 1 px per frame |
| Background overscan | art drawn at 1.13× so zoom/parallax cannot expose the edge; leftmost column mean is now uniform |
| Vignette | centre pixel unchanged (255), corner 40+ levels darker, zero strength draws nothing |
| Render | `natkhat-haveli-e1` 1080×1920, 961 frames, 32.066 s, 3 495 763 B, `qc_ok: true`, full decode clean |
| Black frames | `blackdetect` finds none |

## 3l. Shorts loudness (T36) — measured

Found by measuring rather than listening: the finished Short shipped at **-24.3 LUFS**, ten LU
below reference, because only the long-form renderer normalised.

| Check | Result |
| --- | --- |
| Before (this episode) | scene mixes measured -24.3, -28.2, -27.4, -23.2, -22.4 LUFS |
| After normalisation | -14.1, -14.7, -13.8, -14.5, -14.0 LUFS |
| Final episode | **-14.0 LUFS, -1.4 dBTP** (`loudnorm` summary on the muxed MP4) |
| Duration drift | scene audio padded to the video length; per-scene delta +0.500 s is the intended pad, episode 32.066 → 32.135 s |
| QC gate | new `audio_loudness` check; the old -24.3 LUFS output fails it, the new one passes |
| Tests | 11 in `tests/factory/test_loudness.py`; suite **285 passed** |
| True peak | loudest scene -1.5 dBTP, final -1.4 dBTP, no clipping |

## 3m. Scene transitions (T37) — measured

Scenes were hard-concatenated, so a cut between two different locations was indistinguishable
from a cut between two beats in the same place. The policy is now the editor's rule: a location
change dips to black, the same location cuts directly, the episode opens and closes on black.

| Check | Result |
| --- | --- |
| Tests | 14 in `tests/factory/test_transitions.py`; suite **299 passed** |
| Episode (one location throughout) | fades only at the two ends; no internal dip |
| Two-location demo (`haunted_haveli` → `cave_entrance`) | `blackdetect` finds black at **5.899–6.033 s**, exactly the scene boundary, plus the opening fade |
| Opening | scene 1 frame 0 measures **mean 0.0** (fully black), fade-up completes by 0.45 s |
| Closing | final episode at 32.0 s measures **mean 5.4** vs 34.7 at 31.5 s |
| No fades requested | `ffmpeg_fade_filters(0, 0, d)` returns an empty list, so nothing is added to the command |
| Clamping | fades longer than half the scene are clamped so they cannot overlap |

## 3n. Episode frame rate pinned to 30 and gated (QC) — measured

The concat step let the muxer derive the rate from input timestamps, so the delivered episode
was `avg_frame_rate = 14415/481` (**29.969**) although every scene was rendered at 30. QC never
looked at frame rate, so nothing failed.

| Check | Before | After |
| --- | --- | --- |
| `avg_frame_rate` | `14415/481` = 29.969 | **30/1** |
| `r_frame_rate` | 30/1 | 30/1 |
| Frame count | 961 | **963** (+2 from constant-frame-rate padding) |
| Duration | 32.1346 s | 32.1346 s |
| Loudness | -14.0 LUFS / -1.4 dBTP | **-14.0 LUFS / -1.4 dBTP** |
| Full decode | 0 errors | **0 errors** |
| QC checks | 18, no frame-rate gate | **19, `frame_rate True - 30.00 fps, expected 30`** |
| Duplicate frames (first 12 s, `mpdecimate`) | not measured | 359 of 360 kept, so padding is invisible |

The gate is deliberately tight (`|fps - 30| <= 0.01`). A half-frame or 0.05 tolerance would have
accepted the original 29.969 defect, and would also accept NTSC 29.97, which this engine never
intends to write.

`tests/factory/test_qc.py` (8 tests) pins the parsing: exact 30 passes, `14415/481` and
`30000/1001` fail, a `30/0` denominator is reported as unknown rather than assumed correct, and
malformed text cannot crash the gate. Suite **307 passed**.

## 3o. CI portability defect in the loudness tests — found by reading CI, fixed

Commits `03f6d0b` and `42c9c16` were reported as "CI success" in this session. **That was
wrong.** Both factory jobs failed. Reading the log (`gh run view 44830491764 --log-failed`)
showed 5 failures in `tests/factory/test_loudness.py`, all of the form
`{'before': {}, 'applied': False, 'error': 'loudness could not be measured'}`.

Root cause: my own test hard-coded `WORK = Path("C:/Users/DELL/AppData/Local/Temp/loudness-test")`.
On Linux that is a *relative* path whose first component is `C:`; ffmpeg reads `C:` as a
**protocol** prefix, fails to open the input, emits no loudnorm summary, and `measure()`
returned `{}` — which the tests then reported as a broken audio path. It passed on Windows
where the path is genuine.

Fixes
- `tests/factory/test_loudness.py` uses `tempfile.mkdtemp()`; it is the only file in the repo
  that contained an absolute Windows path (checked with `grep -rn "C:/Users\|D:/" --include=*.py`).
- `studio/audio/loudness.py`: the summary parser now matches candidate `{...}` objects and takes
  the last one that actually decodes (`_decode_summary`), instead of slicing from the last `{`
  to the last `}`, which any trailing brace in a warning destroyed. New
  `measure_with_diagnostics()` returns the reason a measurement failed, so a silent `{}` cannot
  masquerade as a code fault again.
- 6 new parsing/diagnostic tests; suite **313 passed** locally.

Process change: a commit is only "CI-verified" after `gh run list --json conclusion` is read for
that exact SHA. Local green is not evidence about the runner.

## 3p. Character-to-character interaction (T35b) — measured

Two rigs animated *near* each other, never *with* each other: nothing prevented overlap, and a
speaker's emphasis never reached the listener.

`studio/characters/interaction.py` adds three things, all translation/angle addition:

| Capability | Status | Evidence |
| --- | --- | --- |
| Separation guard (min 210 px between body centres) | IMPLEMENTED, unit-tested, guard only | `close anchors: gap 210.0px`; with current anchors (380/780) the closest motion still leaves 400 px, so it never engages in shipped content |
| Forward-arm gesture (speaker reaches toward the partner) | VERIFIED VISUALLY | probe render of 4 delta combinations on both rigs; additive `arm_r_delta=-0.85, arm_l_delta=-0.30` puts the forward pinion out and the near arm tucked |
| Listener reaction (lean + head tilt) | VERIFIED VISUALLY | same probe / rendered episode |
| Facing tracker with hysteresis | IMPLEMENTED, unit-tested, not exercised | no shipped scene puts a partner behind the other, so no flip occurs |
| Identity path | VERIFIED | `idle/walk_in/walk_out/jump: bit-identical frames 180/180` |

Mistakes made and corrected while building this, recorded because they are the useful part:

1. The first version set **absolute** arm angles (`arm_l = arm_r = 0.85`). Rendered frames
   showed a T-pose, and the reach pointed **away** from the partner. Arms are now an **additive**
   delta (`arm_l_delta` / `arm_r_delta` on `BodyState`), so a gesture composes with the pose
   instead of erasing it.
2. The sign was **guessed**. A probe render settled it: the rigs are mirrored by `facing`, so
   local +x is "in front" for both, and a negative right-arm delta is the forward pinion. The
   proof is the mirrored pair: chiku points screen-right, gappu points screen-left, each at its
   partner.
3. `resolve()` round-tripped `anchor + offset -> anchor`, perturbing `hip_x` by ulps on frames
   that needed no clamp. It now returns the inputs unchanged, which is what keeps "no interaction
   means bit-identical" true.
4. A pairwise 3-body `separate()` helper was written, measured, and found to **under-separate**
   (265 vs 450 against a 210 gap). The cast is exactly two characters, so it was deleted rather
   than shipped wrong; the test now asserts it does not exist.

Episode re-rendered at this HEAD: 1080x1920, **963 frames**, `avg_frame_rate 30/1`, full decode
0 errors, **-14.0 LUFS / -1.4 dBTP**, `qc_ok: true`, 246 gesture frames planned across 5 scenes.
Golden frames still reproduce exactly: `78 frames, 0 changed, 0 new`. Suite **350 passed**.

Known limitation: the gesture is aimed at the partner, but a `close_up_*` camera can crop the
partner out, leaving a character reaching into empty frame. Camera and gesture planning are not
yet aware of each other.

## 4. Not yet executed

| Test | Status |
| --- | --- |
| Render on a GitHub Actions runner | **Not executed** — `produce-*` workflows are disabled; PR #2 (installer hardening) is unmerged |
| Edge-TTS network egress from a runner | **Not proven** |
| Chrome-driven overlays on a runner | **Not proven** (Chrome is present; the renderer has not driven it there) |
| Controlled YouTube upload of a produced video | **Not executed** — no secrets provisioned, uploads remain private/off |
| Persistence across workflow termination | **Not executed** (cache wiring exists, never ran) |
| Retry/recovery drill | **Not executed** |
