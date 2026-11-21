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

## 3q. Camera-aware framing (T39) - measured

The camera was a style with no idea what it was pointing at: `close_up_chiku` zoomed to 1.70
around x=380 because someone worked that out by eye once, and nothing checked that a character -
let alone the gesture they were performing - was inside the frame.

Architectural review found seven defects before any code was written:

1. Subject coordinates existed in three places (the camera module, the renderer, the rig
   constructors) while the schemas were the real source.
2. The camera was evaluated **before** the bodies were resolved, so it framed nominal anchors
   rather than where the characters actually were that frame.
3. No shot knew which characters had to be on screen.
4. The background ignored the camera zoom: characters magnified, the backdrop did not.
5. Screen shake lives inside `Camera.apply` and cannot be predicted by any analytic framing.
6. `FACE_Y` was a vertical constant that means nothing at a different aspect.
7. No framing check existed at all.

Fixes, and what each was measured against:

| Change | Evidence |
| --- | --- |
| `studio/animation/framing.py`: subject geometry from schemas, `fit_zoom`, `fits`, `plan_shot`, `FramingReport` | 35 tests |
| Camera takes a planned shot; `state_at` accepts live positions | pre/post parity: **42/42 frames identical** when no shot is planned |
| Shot semantics: a close-up must belong to the performing character; relational shots hold the whole cast | regression tests for both defects below |
| Shots reserve each required subject's full arm reach | gesture frames cropped: **0** |
| Background zooms with the camera | rendered episode inspected: scene 2's window magnifies with the close-up |
| `framing.json` per episode plus two QC gates | `framing_subjects True`, `framing_continuity True (1.07/s, limit 1.60)` |

Rendered episode (1080x1920, **963 frames**, `30/1` fps, 32.135 s, decode 0 errors,
-14.0 LUFS / -1.4 dBTP, `qc_ok: true`, 4 931 644 B):

* required-subject cropped frames: **0** - which was the point of the exercise;
* scene 2 keeps its close-up because it belongs to the speaking character, and the listener that
  shot deliberately excludes is reported as a QC warning (`gappu: 149` frames) rather than being
  passed off as a clean pass;
* peak zoom rate **1.07/s** against the 1.60/s ceiling.

Defects this work introduced and then fixed, recorded because every one was caught by
measurement rather than by reading the code:

1. `max(1.70, fit)` in the close-up branch tightened a close-up to the 2.2 zoom clamp. `fit_zoom`
   is an upper bound, so it has to be `min`.
2. A "two shot" centred the speaker and cropped his partner out of the frame entirely - a two
   shot that frames one character is not one. Relational shots now hold the whole cast.
3. `FramingReport.add` shadowed the module's `overflow()` function with a local dict.
4. `plan_shot(must_show=None)` crashed the first real render on `set(None)`.
5. The planner sized shots on the idle silhouette while the report measured the gesture, leaving
   a trailing hand just outside the frame.
6. `fit_zoom`'s MAX_ZOOM clamp could return a zoom at which the boxes did **not** fit, breaking
   its own contract; the bound is now explicit (`clamp=`).
7. Pair shots never set a vertical pan, so in a 16:9 viewport the cast sat below the bottom edge.
8. The style's vertical drift had been silenced with a `* 0.0`, and `two_shot_zoom` had lost its
   push-in because the kind's nominal zoom had become a hard cap. The plan now separates the
   requested zoom (`zoom`) from the permitted one (`limit`).

Two mistakes in verification are worth recording too: a stale `framing.json` from an earlier
build was read as if it were the new one (the render had actually aborted), and a light band in a
downscaled contact sheet looked like a background coverage bug until the same strip was cut at
full resolution. Both are reasons to check the artifact's timestamp before quoting its numbers.

Honest limits: the 16:9 renderer still draws no characters, so landscape framing is verified
geometrically and by unit tests, not by a rendered landscape episode. Screen shake is outside the
framing model. A `close_up_*` may crop a listener by design, which is a policy decision rather
than a measurement.

## 3r. Props and hand contact (T40) - measured

A prop was a shape drawn at a hard-coded coordinate: the story mentions a brass key, the renderer
drew sparkles near (460, 1150), and nothing connected the two. An object no hand holds cannot be
picked up, carried or handed over.

What was built:

* `hand_point()` - the world position of a rig's hand, from the same transform stack the rig
  draws with. **The pixel probe agrees within 0.7-2.1 px** on both rigs and both sides.
* `PropTrack` - a prop follows a hand, crosses to the other character's hand on cue, and arcs
  upward during the crossing. Measured peak step across the crossing: 41 px/frame at 30 fps for
  a 400 px crossing in 0.5 s, which is continuous rather than a teleport.
* `raise_arm_for_clearance()` - the receiver reaches so the held prop clears the caption band.
  The raising direction is searched in both directions because the rigs are mirrored and do not
  share a sign; the smallest change that works wins.
* Camera lift - when the arm alone cannot clear the band, the frame lifts by exactly the
  shortfall, and only if every character still fits.
* `framing.json` gained `occlusion` (frames hidden, frames lifted, worst overlap, band rect) and
  QC gained a `prop_visibility` check.

Rendered demo (one scene, 231 frames, hand-off at 0.45 of the scene, `two_shot`):

| Metric | Before the clearance work | After |
| --- | --- | --- |
| Frames with the key behind the caption band | **117 / 231** | **0 / 231** |
| Frames where the camera lifted to save it | 0 | 117 |
| Required subjects cropped | 0 | 0 |

The 117 frames were not a guess: the caption band was measured from the subtitle overlay itself
(alpha bounds `(73, 1389)-(1007, 1589)`), and the key's held position genuinely falls inside it,
because a hand hangs at y ~1250-1400 on this stage.

Mistakes made and corrected, all caught by measurement:

1. The prop was positioned from a *stale* pose - the hand was read before `update_pose`, so the
   key lagged the arm by one frame. The loop now poses first, then resolves hands, then frames.
2. Occlusion was measured before the lift was applied, so the metric reported a defect that had
   already been fixed for that frame.
3. The raising sign was assumed (`left` raises negative) and was wrong for Gappu, whose mirrored
   arm raises the other way. The solver now searches both directions.
4. `contact_error()` compared the prop to the *holder's* hand, which is zero by construction. It
   takes the character to measure, which is what a pick-up has to be timed against.
5. The key was drawn the same size as a hand and read as a speck. It is now 1.6x.
6. Five of my own tests were wrong at first: the wrong palette entry for Gappu's hands, a
   `Proportions` object used as a dict, a continuity bound tighter than the crossing itself, the
   contact-error premise above, and a clearance target Gappu's arms cannot physically reach.

Honest limits: the arm solver returns 0 when the band is out of reach (Gappu's arms are short),
so the camera lift carries those frames; a producer would prefer to stage the hand-off higher.
The key artwork is legible at the receiving hand but small in the giving hand - an art-polish
follow-up, not a wiring one.

**Correction (T41).** I first wrote here that a prop-free episode re-rendered imperceptibly because
of the loop reorder. That was wrong. The reorder is not the cause: `--force` deleted the studio
intermediate tree, which *includes the recorded dialogue*, so every render re-synthesised the lines
through Edge-TTS. That service does not return the same bytes for the same text twice, the visemes
come from the audio envelope, and so the mouths - and about a third of the frames - moved a little
on every render. The delta (637 of 962 frames identical, worst PSNR 47.9 dB) was TTS jitter, and
it had been quietly polluting every comparison since the first render of this milestone.

Fixed in `factory/media/hindi_renderer.py`: a forced re-render now keeps `*.mp3` and
`*.boundaries.json` and discards only derived artifacts (`FACTORY_FRESH_AUDIO=1` asks for a fresh
dub). Two consecutive forced renders of the same episode now produce the **same sha256**
(`56b61c786a3a57e4f84a8ec3d18223955383bf782e121de7ca0ee565f834043a`), which is the property every
before/after claim in this file depends on.

## 3s. Landscape character rendering (T41) - measured

Before T41 the 16:9 renderer drew editorial cards: a text column, a diagram plate, a caption band.
Chiku and Gappu existed only in 9:16. `/factory/cli render-stage` now drives the *same* animation
engine on a landscape stage, so viseme lip-sync, blinks, gaze, locomotion, performance beats,
two-body interaction, props and hand-offs, camera direction and framing verification all work in
16:9 without a second implementation of any of them.

A landscape character is not a stretched portrait character: the rigs stand at the same scale with
the same art on a 16:9 floor, and the frame's extra width becomes environment.

### Artifacts actually rendered and inspected

| Artifact | Resolution | FPS | Frames | Duration | Bytes | Decode | QC | Required crops | Face/band collisions |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Complete episode (12 scenes) | 1920x1080 | 30/1 | 1935 | 64.500 s | 9 147 275 | clean | 24/24 | 0 | 0 |
| Dialogue cut (11 scenes) | 1920x1080 | 30/1 | 1729 | 57.633 s | 7 977 561 | clean | 24/24 | 0 | 0 |
| Interaction demo (6 scenes) | 1920x1080 | 30/1 | 947 | 31.567 s | 4 484 977 | clean | 24/24 | 0 | 0 |

* episode sha256 `ac3a85d3e13937da41690881016ae25d897592002a3d04a1b7c7de763599d57e`
* dialogue cut sha256 `3c70ae14afc6b54c2d29158e02bf9c225a5c79d204cce75d858fce097a3360e9`
* interaction demo sha256 `1a558414f44a4a4fddd783cac5ccf792b67ea0ab1df5927f58e51d256276a397`

Measured properties:

| Property | Result |
| --- | --- |
| Loudness (EBU R128) | -14.04 LUFS integrated, -1.5 dBTP true peak, LRA 3.9 |
| A/V start offset | 0.000 s on both streams |
| A/V length delta | 1 ms (video 64.500 s, audio 64.501 s) |
| Peak zoom rate | 0.93/s against a 1.60 limit |
| Shot escalation | scenes 3, 8, 11 widened from a subject medium to a relational medium, with the reason recorded |
| Render wall time | 268 s for 64.5 s of 1080p (≈4.15x real time) |
| Golden portrait frames | 78 frames, 0 changed, 0 new |
| Portrait regression | frame-identical: 963/963 frames match the pre-T41 render (`0fac3ab3...`) |

Frames were inspected, not only measured: a 2x2 contact sheet from each artifact, plus close-ups of
the caption band, the title card and the foreground layer. Five composition defects were found that
way and fixed (title card over the cast's heads, foreground foliage across the caption band,
foreground blades crowding the text, an over-tall caption band, and a kicker drawn above the band so
the measured band rectangle started 38 px too high).

### Defects found by measurement, not by reading

1. **The subject box was wrong by 62%.** `subject_from_schema` predicted Chiku at 278 world units
   tall when his drawn silhouette is 335, and Gappu at 101 against 265. Every framing measurement
   since T39 was measured against that box, including the "0 required subjects cropped" claim.
   Fixed by *measuring* the rig (`studio/animation/silhouette.py`): one cached render per
   (class, pose, facing), then the drawn alpha bounds. The box is asserted to contain the drawn
   character in every pose.
2. **The framing read the authored anchor, not the stage.** A character restaged for 16:9 was
   framed where its JSON file said it lived. `subject_from_rig` reads the rig.
3. **`medium_pan` was swallowed by a new `medium_` prefix branch** in the camera, so every portrait
   scene using it jumped from zoom ~1.01 to 1.30 (PSNR 19.81 against the previous render). Caught
   by comparing frames, fixed, and the portrait pipeline is now frame-identical again.
4. **Concat delivered 29.93 fps.** Each scene's AAC stream is slightly longer than its video, so the
   next scene started 0.023 s late and the container duration stopped being frames/30. Twelve scenes
   would have accumulated about a third of a second of A/V drift. Fixed with `-vf fps=30` on the
   join, and there is now a test that reproduces the defect with two synthetic scenes.
5. **`--force` deleted the recorded dialogue**, so every render re-synthesised speech through
   Edge-TTS and about a third of the frames changed by a barely visible amount - twice reported at
   T39/T40 as an unexplained side effect of whatever I had just changed. Both attributions were
   wrong. Fixed in the previous commit; two consecutive forced renders now hash identically.
6. **Caption collision was measured on the wrong rectangle and the wrong body part.** The kicker was
   drawn above the band, so the band rectangle started 38 px too high; and the check measured the
   whole silhouette, so a close-up (whose torso legitimately sits behind the band) reported every
   frame. It now measures the face against the band the viewer actually sees.
7. **The episode aggregate mixed stale reports**: a 6-scene demo inherited collision counts from
   scenes of an earlier 12-scene render. The aggregate is now filtered to this episode's scenes.

### Honest limits

* The mid-ground (trees, ruins) is still barely legible against the ridge behind it; the environment
  reads as sky, ridge, floor and foreground, which is four layers of the five designed.
* A close-up reserves the character's full gesture reach, so `close_up` lands at 1.62 rather than a
  tighter framing. A close-up is exactly the shot where cropping the gesture is acceptable.
* Foreground foliage is confined to the outer 12% of the frame; it does not yet occlude the cast,
  so the "characters inside the scene" depth cue is only partly realised.
* Only one location (`haunted_haveli`) has been rendered end to end, although six are defined.
* The stage engine is **not** wired into the publish orchestrator: `factory/orchestrator.py` still
  routes Hindi episodes through the Shorts pipeline. Landscape character episodes are produced by
  `factory/cli render-stage`, which runs the same QC gate.

## 3t. One orchestrator for every engine (T46) - measured

`render-stage` was a parallel pipeline: its own thumbnail call, its own subtitle build, its own QC
call, its own state handling, and its own idea of where an episode's build directory lives. T46
collapses that into `orchestrator.render_episode`, which resolves the engine from the plan and then
does the same post-render work for every format.

    engine = resolve_engine(spec, plan)   # "stage" | "shorts" | "cards"

| Engine | Profile | Renderer |
| --- | --- | --- |
| `shorts` | 1080x1920 9:16 | character engine (series-bible / topic-bank plans) |
| `stage` | 1920x1080 16:9 | character engine on the landscape stage |
| `cards` | 1920x1080 16:9 | editorial card renderer (diagrams, no cast) |

### Idempotency, measured on the real 12-scene episode

| Run | Command | Rendered scenes | Reused | Wall | sha256 |
| --- | --- | --- | --- | --- | --- |
| full | `render --format long` | 12 | 0 | 250 s | `363df065fea2b03ed406d8ce8dba9a0088ee8c5426152e7c01a52acbd649ba0a` |
| re-run | `render --format long` | 0 | 12 | 16 s | `363df065...` (identical) |
| recovery | `resume` after deleting `video.mp4`, `qc.json` and scene 7 | 1 | 11 | 59 s | `363df065...` (identical) |

The recovery case is the one that matters: one deleted scene and a missing output were restored in
59 s instead of 250 s, and the reassembled episode is byte-identical to the uninterrupted render.
`status` reported `resume (1 missing, 0 stale)` before the run and `done` after it.

An earlier accident demonstrates the atomic-finalization property independently: a failed join left
the previously verified `video.mp4` untouched and intact, and the next run reused it.

### Defects this work found

1. **Two formulas for one build directory.** `orchestrator.episode_out_dir` produced
   `<slug>_<plan>` while the stage module produced `<slug>_render-stage-<plan>`, so `status`
   reported twelve missing scenes for an episode whose twelve scenes were on disk. One function
   (`stage_story_id`) now serves both.
2. **`status` read the wrong scene key** (`scene["scene"]` when the authored key is `"n"`), which
   is what made the count look like twelve missing scenes even after the paths agreed. It now asks
   `plan_scenes`, which owns the schema.
3. **The cache signature allow-list missed the poses** (`"pose"` listed, `chiku_pose`/`gappu_pose`
   authored), so changing a pose would have reused a scene drawn with the previous pose. It is a
   deny-list of render-only fields now, so a new scene key is covered by default.
4. **The narration take was not part of the signature.** Visemes come from the audio envelope, so a
   fresh dub with identical text changes the mouths; `FACTORY_FRESH_AUDIO=1` could have reused
   scenes lip-synced to the previous take. The audio file hash is now in the signature.
5. **The atomic partial file had no usable extension.** `.mp4.partial` gives ffmpeg no muxer to
   infer, so the join failed with "Invalid argument" *after* every scene had rendered. `.partial.mp4`
   keeps the container and the rename.
6. **Inferring the engine from a `scenes` key mis-routed a Short.** The existing 9:16 plans carry a
   `scenes` key too; a stage plan now has to say so.

### Honest limits

* The `--json` payload of a stage render is preceded by the studio's `[Render]` progress lines on
  stdout, because the renderer prints there. A JSON consumer must take the last array in the stream.
  This predates T46 and affects the Shorts pipeline the same way.
* The portrait pipeline is unchanged, not merely similar: `0fac3ab3...` and 963/963 frames
  identical to the pre-T46 render.
* Landscape episodes are now *reachable* through the factory orchestrator, but the publish
  orchestrator still only publishes what `publish` is told about; no landscape episode has been
  uploaded and none should be until the owner decides the channel strategy.

## 3u. Conversational cinematography (T42) - rendered and inspected

The 16:9 episode named a camera per scene and some of them named the wrong character: scene 11 had
Gappu speaking over a `medium_chiku`, a medium shot of the listener while the speaker's mouth was off
screen. Five consecutive scenes in the middle of the conversation were all `two_shot`, so a
two-hander had no reverse coverage at all.

`studio/animation/shot_plan.py` now derives the shot from the conversation - line ownership, the
listener, the location, and what the previous cut framed - and a scene whose camera is `"auto"` takes
its framing from that plan. All twelve scenes of the Haveli episode are now directed.

### The edit that resulted

| Scene | Speaker | Shot | Reason |
| --- | --- | --- | --- |
| 1 | narrator | wide_establishing | episode_open |
| 2 | chiku | medium_chiku | speaker_medium |
| 3 | gappu | medium_gappu | speaker_medium |
| 4 | chiku | close_up_chiku | punctuated_turn |
| 5 | narrator | two_shot | narrator_watching_both |
| 6 | gappu | medium_gappu | speaker_medium |
| 7 | chiku | medium_chiku | speaker_medium |
| 8 | gappu | medium_gappu | speaker_medium |
| 9 | narrator | two_shot | narrator_watching_both |
| 10 | chiku | close_up_chiku | punctuated_turn |
| 11 | gappu | medium_gappu | speaker_medium |
| 12 | narrator | two_shot | narrator_watching_both |

That is classic shot/reverse-shot: the frame changes sides because the *speaker* changed, not
because a counter flipped. Re-ordering two lines re-orders the shots, and inserting a narrator beat
changes the coverage of the lines around it - both asserted in tests.

### Evidence

| Property | Result |
| --- | --- |
| Directed shots | 12, 0 continuity violations |
| QC | 25 checks (new `shot_continuity` gate), 24/24 pass earlier + the new gate |
| Cropped required subjects | 0 |
| Face/caption collisions | 0 |
| Episode | 1920x1080, 30/1, 1935 frames, 64.500 s, sha256 `cb38d2c5...` |
| Portrait regression | `0fac3ab3...`, 963/963 frames identical |
| Tests | 519 (30 new shot-plan tests) |
| Golden frames | 78 frames, 0 changed, 0 new |

Frames were inspected: a 2x3 contact sheet of the first six scenes, and scene 11 on its own to
confirm the original defect is gone (Gappu is centred and large while his line plays).

### Defects found while doing this

1. **`medium_<name>` was a two-shot.** `plan_shot` handled single-subject styles only inside its
   widening loop, where `medium_<name>` matched the *relational* `medium` case first and was
   "widened from subject_medium to medium" - framing both characters. That is what the T41 runs
   reported as escalation on scenes 3, 8 and 11, and it is why a "medium of Gappu" still showed Chiku
   large. Subject shots are now resolved before the relational loop.
2. **The episode's own wide was being discarded.** The repeat guard keyed on the camera name only, so
   a location change that legitimately cut from one wide to another was overwritten. It compares the
   location too now.
3. **A danda is not a beat.** Treating the Devanagari full stop as punctuation made every Hindi line
   "punctuated", which turned all twelve scenes into close-ups. A beat is a question, an exclamation
   at the end, or an opening interjection ("अरे!", "देखा?"), which is where Hindi puts the emphasis.
4. **The cache signature was a manual string, and I forgot to bump it.** A framing fix re-rendered
   nothing, reused twelve stale scenes and reported success. The signature now hashes the engine's
   own source (`studio/animation`, `studio/characters`, `studio/audio`, `content/characters`), so it
   cannot be forgotten.

### Honest limits

* Shot/reverse-shot happens *between* scenes because a scene is one line. There are no cuts inside a
  line yet, so a long speech cannot cut to a reaction in the middle of itself.
* Eyeline is enforced as axis continuity (each character keeps its side, and no framing is allowed to
  name a non-participant), not as head-turn geometry; gaze targets are unchanged from T32.
* Three-character scenes are not supported: `screen_sides` handles any number of anchors, but the
  camera has no three-shot vocabulary and the planner's listener model assumes a pair.
* The director chooses among the camera styles that exist. It does not invent new moves.

## 3v. Reliability, publishing gate and cloud readiness (T49) - measured

| Property | Result |
| --- | --- |
| Tests | 582 (63 new: 38 reliability, 25 publishing gate) |
| Golden frames | 78 frames, 0 changed, 0 new |
| Gate on a real 32 s portrait artifact | 22/23 before packaging, 23/24 after, **24/24** once the manifest existed |
| Job journal on that run | ends `READY_TO_PUBLISH` with the video sha256 and duration |
| Duplicate run | second `JobLock.acquire()` returns False; the context manager raises `LockBusy` |
| Stale lock | a lock with a dead pid is detected and taken over |
| Kill on timeout | `run_process(..., timeout=0.5)` on a 30 s child raises `TimeoutError` |
| Resume | (T46) 1 scene re-rendered, 11 reused, byte-identical episode in 59 s |
| Cloud runner | **not executed** - `HTTP 404: workflow production.yml not found on the default branch` |

Defects found while building this:

1. **An undeclared `psutil` import.** The dependency test caught it; rather than add a dependency,
   available RAM now comes from `/proc/meminfo` (Linux) or `GlobalMemoryStatusEx` (Windows).
2. **The gate crashed on a file with no video stream** (`video_streams[0]` on an empty list) instead
   of returning a verdict.
3. **The gate looked for a check name the renderer never emits** (`black_frames`), which made a
   missing check read as a blocker.
4. **The state machine refused a legal resumed path** (`PREFLIGHT -> RENDERING`); the skip edges are
   now part of the table rather than an exception in the caller.
5. **A manifest step in the workflow contained a dead Python block** that did nothing; removed.

## 3w. Interaction, lighting, grounding and locations (T43b/T44/T45) - measured

| Area | Result |
| --- | --- |
| Full suite | **631 passed** (49 new: 32 IK/pickup, 12 lighting, 5 grounding) |
| Golden frames | 78 frames, 0 changed, 0 new |
| Interaction demos | 5 clips, 1920x1080, 30/1 CFR, 90-126 frames each |
| Contact (drawn wrist) | ground -14.0, table -20.0, handoff -3.5, two-hand -3.2, recovery -4.2 px |
| Crouch solution | Chiku 96 deg / 0.72 squash, Gappu 115 deg (both reach the floor) |
| Shadow offsets | standing -> 180 px airborne: 8 -> 48 (day), 8 -> 296 (sunset), -8 -> -212 (cool evening) |
| Ground contact | 0.0 px error for both rigs after the fix; was 32 px (Chiku) and 22 px (Gappu) |
| Foreground occlusion | 0.0 in all six locations (not achieved) |
| Locations rendered | 6 of 6, contact sheet inspected |

## 3x. World-space pickup in production (T43 integration) - measured

| Property | Result |
| --- | --- |
| Full suite | **648 passed** (17 new in `test_pickup_integration.py`) |
| Golden frames | 78 frames, 0 changed, 0 new |
| Production render | `render --scenes 3 --force` on the real Natkhat plan, 1920x1080, 30/1, 5.97 s |
| Pickup report | states APPROACHING -> REACHING -> CONTACT -> GRIPPING -> HOLDING -> RELEASING -> COMPLETE |
| Measured contact | **-13.93 px** on the drawn wrist (inside the object) |
| Claimed contact without touch | 0 frames |
| Reachability | shoulder-to-surface 57.4 px vs 83.8 px arm; bend 79.2 deg |
| QC gate | `pickup_contact` passes; only the single-scene duration check fails, as expected for a proof render |

Defects found by doing the integration rather than asserting it:

1. `plan_scenes()` dropped the `pickup` and `lighting` keys, so both features were unreachable from an
   authored plan. A render succeeded, reused a cached scene, and looked plausible while doing nothing.
2. `UnboundLocalError: pickup_frame` - the framing box read a variable produced later in the frame
   loop. Caught only by a forced render; the fast path had reused a cached scene.
3. The released object returned to its original floor position at COMPLETE - a visible teleport that
   also contradicted the story beat.
4. `reachable` was measured against the object's exact grasp *centre*, so a pickup whose hand was
   14 px inside the object was declared unreachable and failed its own QC gate.
5. A `table_height` authored as a fraction (0.62) passed validation, because a range check on world
   coordinates cannot distinguish it. Now bounded by the character's own shoulder and feet.

## 3y. Ownership, continuity, near-camera depth (T43B / T47 / T45b / T45c)

| Property | Result |
| --- | --- |
| Full suite | **701 passed** (17 set-dressing, 36 ownership/continuity, 17 pickup integration new this pass) |
| Golden frames | 78 frames, 0 changed, 0 new |
| Full 12-scene episode | 64.5 s, 1920x1080, `qc_ok: true`, **27/27 checks pass** |
| Continuity | 0 errors, 0 warnings, 2 info across 12 scenes |
| Ownership chain | brass_key: floor -> chiku (pickup, scene 3) -> gappu (hand-off, scene 6), carried at the end |
| Foreground occlusion | **18.5 % of Chiku, 7.0 % of Gappu**, **0.0 of either face**, all six locations |
| Previous foreground occlusion | **0.0** in all six locations |
| Render time | 292 s wall for 64.5 s / 1935 frames (4.5x real time) - dressing costs ~14 % |

Defects found and fixed in this pass, including two of my own:

1. **A frozen episode.** The occlusion probe reused the local name `surface`, which is the scene's
   frame buffer, so every encoded frame was a static character mask. The QC `frozen_frames` check
   caught it (63.7 s frozen at 0.5 s); frame-hash sampling did not, because codec noise made the
   sampled hashes differ. Verified fixed by measuring mean pixel difference over 2 s: **0.0 before,
   8.85 after**. This is the single most valuable thing the gate has caught so far.
2. A hand-off destination was read as a conflict, reporting every legitimate hand-off as an error.
3. The pickup released the key at COMPLETE while scene 6 declared a hand-off from the same hand;
   ownership is now modelled, and the pickup carries (`keep: true`).
4. The first set-dressing pass filled silhouettes with near-black and covered 45 % of the cast - a
   screenshot inspection rejected it. Rebuilt from the location palette; occlusion now 18.5 % / 7.0 %
   with no face coverage, measured on drawn pixels.
5. A "foreground stays below 0.68 of frame height" test was a proxy for "does not cover a face". It
   failed a clump that covered nobody and would have passed an object covering a short character's
   face. Replaced with a measured head-band occlusion check.

## 3z. In-line cuts, observability, and measured benchmarks (T42b / T49d / T50)

| Property | Result |
| --- | --- |
| Full suite | **731 passed** (15 observability, 15 in-line cut/camera) |
| Golden frames | 78 frames, 0 changed, 0 new |
| Portrait Short, measured | 32.13 s video / 963 frames: **156.95 s wall (4.88x real time, 6.14 fps)**, peak RSS **117.8 MB**, disk **23.6 MB**, `qc_ok: true` |
| Landscape episode, measured | 64.50 s video / 1935 frames: **292 s wall (4.5x real time, 6.6 fps)**, `qc_ok: true`, 27/27 checks |
| Projections (labelled, not measured) | 60 s -> 293 s; 300 s -> 1465 s; 600 s -> 2930 s wall |
| In-line cuts | 4 of 12 authored scenes get one; portrait Short gets 2 |
| `--json` output | verified end-to-end with `json.loads` on real stdout; progress now goes to stderr |

Defects found in this pass:

1. **A regression the gate caught.** In-line cuts restart the camera, and `framing_continuity` read
   that discontinuity as a zoom racing at **1.64/s** against a 1.60 limit, so the portrait Short went
   from passing to failing. The metric now ignores the frame on which a cut lands and records cuts
   separately; measured zoom rate returned to **1.07/s**. The limit itself was not changed.
2. `CameraDirector.cut_to` changed the style for *all* times, so a scene that cut at 4 s opened on its
   second shot. Cuts are now a schedule (`shot_at(t)` returns the style in effect, and its start).
3. `?` and `!` beat detection read the punctuation-stripped word, so a question inside a line could
   never produce a reaction shot.
4. Peak memory was reported as `None` on Windows: `GetCurrentProcess()` was not declared with
   `restype = HANDLE`, so the memory call rejected the handle. Now measured.

**Disclosed change to the portrait path:** the portrait Short's bytes changed
(`3406082b4bb0baec... -> 07d07da243a93a77...`, 963 frames, same duration) because it now receives
in-line cuts. Set dressing does **not** apply to portrait (`width > height` guard) and the 78 golden
pose frames are unchanged. `FACTORY_INLINE_CUTS=0` restores the previous look exactly.

## 4. Not yet executed

| Test | Status |
| --- | --- |
| Render on a GitHub Actions runner | **Not executed** — `produce-*` workflows are disabled; PR #2 (installer hardening) is unmerged |
| Edge-TTS network egress from a runner | **Not proven** |
| Chrome-driven overlays on a runner | **Not proven** (Chrome is present; the renderer has not driven it there) |
| Controlled YouTube upload of a produced video | **Not executed** — no secrets provisioned, uploads remain private/off |
| Persistence across workflow termination | **Not executed** (cache wiring exists, never ran) |
| Retry/recovery drill | **Not executed** |

## 3aa. Security hardening (X100 final phase)

| Check | Result |
| --- | --- |
| `python -m tools.secret_scan` (tree) | 0 findings, 14 rules |
| `python -m tools.secret_scan --history` (all refs) | 4 findings, all the documented fake fixtures |
| `python -m tools.workflow_audit` | 0 findings over 7 workflows |
| `python -m tools.dependency_audit` | 0 unaccepted, 42 accepted under a documented pillow 12.3.0 ceiling |
| `pytest tests/factory/test_security.py` | 18 passed |
| Full suite | **749 passed** |
| Golden frames | 78 frames, 0 changed, 0 new |

Defects found, including two in the tools written for this audit:

1. The run journal recorded absolute paths, and the production workflow uploads it as an artifact on a
   public repository - both existing artifacts contain the owner's `C:\Users\...` path. Fixed at the
   single write point; the two old artifacts need owner deletion.
2. `produce.yml` interpolated dispatch inputs (`allow_unpublished`, `secret_prefix`) into `run:` blocks;
   both now arrive through `env`, and the channel slug is validated against the three known slugs.
3. Third-party actions were pinned to moving major tags; now pinned to commits resolved through the API.
4. `pillow==12.2.0` carried 67 advisories; 12.3.0 carries **42** - my first report said 4 because I read
   the tail of the audit output instead of counting. The bump still changes no pixel (goldens prove it),
   and the remainder is now a counted, documented ceiling in `security/accepted-advisories.json` that CI
   enforces.
5. My history scan deduped findings by `(rule, line)` instead of `(rule, file, line)`, which could report
   a clean history by collapsing a finding in one file with a different file's line number. Fixed and
   re-run.
6. My workflow auditor flagged a workflow for the word `pull_request_target` inside the comment that
   explains why it is not used, and flagged `produce.yml` for a job-level permission gap its top-level
   block already closed. Both rules corrected.
