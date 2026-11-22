# Cloud run #1 — forensic repair of the three publishing-gate blockers

Run `45045980024` (workflow `production.yml`, `main` @ `43e87e5`, channel `nexus-node`, plan
`nexus-power-grid`) failed at the publishing-gate step, 20/23. This file records the evidence, the root cause
of each blocker, the repair, and what is still unproven.

## Evidence preserved

- `gh run download 45045980024` → `nexus-node-45045980024` (9.5 MB): `gate.json`, `qc-step.json`,
  `build/nexus-node/nexus-power-grid/{video.mp4,qc.json,manifest.json,captions.srt,thumbnail.jpg}`,
  `pipeline_state/`, `preflight.json`, `doctor.json`, `ops.txt`, `resume.json`.
- The failed step's log was read with `gh run view 45045980024 --log-failed`.
- Nothing from that run was overwritten; the artifact is the only copy and was not re-uploaded or edited.

## Blocker 1 — `asset_story`: "story.json"

**Cause.** The gate requires `story.json` in the episode directory for every channel. Only
`factory/media/hindi_renderer.py` and `factory/media/landscape_stage.py` wrote one. The English card renderer
(`factory/media/english_renderer.py`), which produces all Nexus Node and Academic Biohacker Shorts, wrote
`script.json`, `timeline.json` and `render.json` — and no story report. The gate was right; the renderer was
incomplete for the format that was actually being produced.

**Repair.** `render_english` now writes `story.json`: the narrative record for the plan it rendered, one entry
per line with headline, text, start, end, motif and palette, plus a provenance block stating that the visuals
are generated in-process from primitives, naming the three fonts, and pointing at the synthesised music bed
and the TTS provider recorded in `script.json`. Nothing in it is inferred from a file it did not render.

## Blocker 2 — `framing`: "framing.json missing: composition unverified"

**Cause.** Same shape as blocker 1: the composition report existed only for the character pipeline.

**Repair.** `render_english` now measures composition while it encodes, on the frames it is writing, and
writes `framing.json` with `cropped_required_frames`, `subtitle_collision_frames`, the safe area, the sample
count and stride, per-element maxima and up to 120 samples with timestamps.

Getting the measurement right took four corrections, each found by measuring rather than reasoning:

| Attempt | Measurement that killed it |
| --- | --- |
| "brighter than 170" | on Academic's light palette the whole background counted as ink: 192 falsely cropped frames |
| "further than 45 grey levels from the band median" | caught soft background shading instead of type: 12 px false overflow |
| pixel edges inside each band | caught the plate's decorative arcs crossing the band: 20-39 false collisions |
| **rectangles returned by the draw calls** (final) | exact; the draw call is the ground truth for what it drew |

Two real layout defects surfaced while doing this, and both are fixed in the renderer rather than in the gate:

- **Caption capsule outside the safe margin.** It was sized against a fixed 930 px of type, so with 34 px of
  padding either side a long line put the capsule at x=54 against a 56 px margin; then it was sized against
  `textlength(text)`, which is not the drawn width — the drawn width is the sum of word advances plus spaces,
  which left 8 px of overflow on captions with many words. The capsule is now sized from the advances it is
  about to draw, with 8 px of clearance.
- **The entrance wipe crossed the caption.** The sweep ran to the bottom of the card, passing through the
  caption band for the first frames of every line. It now stops above the band.
- **The camera push-in moved content outside the margin.** The push-in scales everything by up to 1.06 about
  the centre, so a caption laid out to the safe width lands ~25 px outside it. Layout now targets the safe
  width divided by the maximum push-in (`LAYOUT_HALF_WIDTH`), and the report measures the pushed-in result
  against the real safe area.

## Blocker 3 — `manifest`: "6 artifacts, hash mismatch: ['qc_report']"

**Cause.** Ordering, not hashing. The render wrote `manifest.json` at `16:53:08`, hashing the `qc.json` it had
just produced; the workflow's own "Quality assurance" step then re-ran validation and rewrote `qc.json` at
`16:53:11`. The gate compared the manifest against the newer file. Measured on the artifact: recorded
`95feb46c…`, actual `e45a47c2…`, same 3 518 bytes — a size check would have called it intact.

The old gate also only hashed entries that existed, so a manifest that listed `timeline.json` and
`script.json` passed even though neither file was in the uploaded package.

**Repair.**

- `factory/manifesting.py` — one definition of the package: the canonical artifact list, `collect_artifacts`,
  `rebuild` (re-hash, atomic write, preserve render metadata, refresh the QC record) and `verify`.
- `factory.cli manifest` — a verb the workflow runs *after* its QC step, so the manifest describes the final
  bytes.
- `produce.yml` — a "Rebuild manifest after QC" step between QC and the gate.
- The gate now calls `manifesting.verify`, which reports three distinct failures: a file that changed after it
  was hashed, a file the manifest claims but that is missing, and an artifact on disk the manifest never saw —
  the last of which is how this run failed while looking like a hash bug. It also refuses a manifest that
  predates the QC report it describes.

No threshold was relaxed anywhere. The manifest check got stricter: a package with unlisted artifacts or a
missing artifact now fails, and a stale manifest fails with a message that says so.

## Local acceptance (fresh build directories, real renders)

| Artifact | Duration | Picture | Codec | Size | sha256 (first 32) | QC | Manifest | Gate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| nexus-node `nexus-robot-video` | 39.566 s | 1080x1920 30 fps | h264/aac | 9.17 MB | `267cd7f354d399db775034def71868ee` | 25/25 PASS | 8 artifacts, verifies | **24/24 PASS** |
| academic-biohacker `academic-post-meal-walk` | 38.366 s | 1080x1920 30 fps | h264/aac | 10.15 MB | `fc5bcd0046fa8336f50c37de30cbfd1d` | 25/25 PASS | 8 artifacts, verifies | **24/24 PASS** |
| natkhat-toons `natkhat-haveli-e4` (Short) | 31.667 s | 1080x1920 30 fps | h264/aac | 4.38 MB | `f1745f347e3dd81cc4210cb1cc1bac5f` | 25/25 PASS | 8 artifacts, verifies | **24/24 PASS** |
| natkhat-toons `natkhat-haveli-stage-e1` (landscape) | 64.501 s | 1920x1080 30 fps | h264/aac | 7.87 MB | `190209589d61a7fb0a8e36fcb2030884` | 27/27 PASS | n/a (see below) | not runnable (see below) |

Render wall time on this machine: 173-246 s per Short, 286 s for the 64.5 s landscape episode.

Frame-by-frame inspection of the repaired Nexus Node Short at 19.6 s: headline "SEEING IS NOT DOING" inside
its margins, caption capsule "action a video" comfortably inside the safe area, no clipped type, no
character or arc behind the caption.

## Tests

- `tests/factory/test_cloud_gate_repairs.py` — 14 tests: a finalised package verifies and passes the full gate
  (23/23 on a real encoded 1080x1920 30 fps 21 s file with normalised audio, not a mock); a missing story
  report is still a blocker; cropped composition is still a blocker; a caption over a subject is still a
  blocker; a missing framing report is still a blocker; editing the QC report after packaging fails
  verification; rebuilding restores it; a manifest that predates QC is reported; an unlisted artifact is
  reported; a manifest entry with no file is reported; the caption capsule fits the safe width; a clipped
  rectangle measures as clipped; the layout accounts for the push-in; the measured frame is the encoded frame.
- `tests/factory/test_publish_gate.py` — the existing "complete package passes" fixture built a one-entry
  manifest, which the old gate accepted and the new one does not. The fixture now packages through
  `manifesting.rebuild`; the test asserts the same thing it always did, against a genuinely complete package.
- Full suite: **835 passed**, golden frames **78 checked, 0 changed, 0 new**. Workflow audit 0 findings over 7
  workflows; dependency audit 0 unaccepted.

## What is still not proven

1. **A cloud run of this repair.** `main` is protected; this change is on `fix/cloud-gate-blockers` and needs
   review and merge before `production.yml` can be dispatched again. No cloud evidence exists for it.
2. **Long-form through the gate.** `factory.cli validate --format long` fails for the landscape plan because
   `build_hindi_script` requires `scenes[].dialogue` and the landscape schema uses `scenes[].line`. The
   landscape *render* passes its own QC 27/27, but `validate`, `manifest` and `gate` cannot be run for that
   format until the loader accepts the landscape schema. Newly found; not fixed here.
3. **Residual caption sizing on very long single words.** The capsule is reduced to a 44 px floor; a word
   wider than the layout width at that size would still overflow. No caption in any render so far reaches it.

## Verdict

**PARTIAL.** All three blockers are fixed and locally verified on all three channels, and the local factory is
green. The cloud run that would prove it cannot be dispatched until this branch merges, so no cloud success is
claimed.
