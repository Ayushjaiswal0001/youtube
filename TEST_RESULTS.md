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

## 4. Not yet executed

| Test | Status |
| --- | --- |
| Render on a GitHub Actions runner | **Not executed** — `produce-*` workflows are disabled; PR #2 (installer hardening) is unmerged |
| Edge-TTS network egress from a runner | **Not proven** |
| Chrome-driven overlays on a runner | **Not proven** (Chrome is present; the renderer has not driven it there) |
| Controlled YouTube upload of a produced video | **Not executed** — no secrets provisioned, uploads remain private/off |
| Persistence across workflow termination | **Not executed** (cache wiring exists, never ran) |
| Retry/recovery drill | **Not executed** |
