# BASELINE — X100 directive 07

Starting SHA `510be8f` on `feat/landscape-16x9`, tree clean, `main` at `567e63c`, remote
`Ayushjaiswal0001/youtube`. Five `FINAL_LAUNCH/` reports present and consistent with the repository:
796 tests, goldens 78, emergency stop and notification in place, publication flags closed, three crons
`disabled_manually`, 0 repository secrets.

## Reconnaissance findings (before any edit)

- The QC gate measured freezes with `ffmpeg freezedetect=n=-50dB:d=1.5`.
- `_freeze_events()` appended a segment only when it saw `freeze_end`. A freeze that runs to the end of
  the file emits `freeze_start` and no `freeze_end`, so **a renderer that stalls on the last line and keeps
  writing the same frame measured as 0.00 s of freeze**. The gate was blind to the most likely failure mode.
- The English card renderer (`factory/media/english_renderer.py`) had motion in exactly one place: the
  `network` motif's radius pulse, and an 8 px progress bar. `chip`, `screen`, `robot`, `shield`, `sandbox`
  and `sword`-shaped motifs are drawn from constants and never change with `t`. On a card held for one
  narration line the only changing pixels were the caption's active-word highlight and that progress bar.
- Natkhat Toons uses a different pipeline (`hindi_renderer` / character stage) and passed QC; its goldens
  are the contract that protects it.

## Difference from the previous report

The previous acceptance report said the freeze was "static cards held too long" and named
`frozen_frames` as the only failure. That was accurate but incomplete: it did not notice that the
detector ignored freezes running to EOF, and it did not notice the audio true-peak failure, which only
appeared once the freeze stopped masking it.
