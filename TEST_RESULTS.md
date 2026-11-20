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

## 4. Not yet executed

| Test | Status |
| --- | --- |
| Render on a GitHub Actions runner | **Not executed** — `produce-*` workflows are disabled; PR #2 (installer hardening) is unmerged |
| Edge-TTS network egress from a runner | **Not proven** |
| Chrome-driven overlays on a runner | **Not proven** (Chrome is present; the renderer has not driven it there) |
| Controlled YouTube upload of a produced video | **Not executed** — no secrets provisioned, uploads remain private/off |
| Persistence across workflow termination | **Not executed** (cache wiring exists, never ran) |
| Retry/recovery drill | **Not executed** |
