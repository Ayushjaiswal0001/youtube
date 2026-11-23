# Final acceptance matrix — six production rows

All six rows were dispatched from **`main @ 218a6d5542e30733e6739e5a93bc46bca3c26e01`** with
`mode=render+validate`, `upload=false`. Workflow: `production.yml` ("production (manual)").

Status vocabulary (not collapsed into one green tick):

- **CLOUD VERIFIED** — the workflow ran, and the artifact was downloaded and re-hashed locally.
- **CLOUD VERIFIED (run-reported)** — the workflow ran and QC/gate passed on the runner; the artifact could not be
  downloaded in this session, so the SHA-256 is the one the run reported.
- **NOT EXECUTED** — deliberately not attempted.

| # | Channel | Format | Plan | Run | Video | SHA-256 | QC | Gate | Manifest | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Nexus Node | 9:16 Short | `nexus-data-wall` | [45196341328](https://github.com/Ayushjaiswal0001/youtube/actions/runs/45196341328) | 41.966 s, 1080×1920, 30 fps, h264/aac, 10.01 MB | `d6182b01caf2e17ca46b1746d2ee1afae1c5c1fa8586e1a08df9b6cd4f129e4a` | 25/25 | 24/24 | 8/8 re-hashed | **CLOUD VERIFIED** |
| 2 | Academic Biohacker | 9:16 Short | `academic-post-meal-walk` | [45196366254](https://github.com/Ayushjaiswal0001/youtube/actions/runs/45196366254) | 38.366 s, 1080×1920, 30 fps, h264/aac, 10.15 MB | `6ca74914de66120233f15c4f7c26d7dc051dbbf0f83fd23743c94a050adf7c66` | 25/25 | 24/24 | 8/8 re-hashed | **CLOUD VERIFIED** |
| 3 | Natkhat Toons | 9:16 Hindi Short | `natkhat-haveli-e1` | [45196207861](https://github.com/Ayushjaiswal0001/youtube/actions/runs/45196207861) | 32.135 s, 1080×1920, 30 fps, h264/aac, 4.69 MB | `2fce43ec5e89c54af208bd0645cf79077778e253840af04440e82f993ed73060` | 25/25 | 24/24 | 8/8 re-hashed | **CLOUD VERIFIED** |
| 4 | Natkhat Toons | 16:9 long-form | `natkhat-haveli-stage-e1` | [45196390881](https://github.com/Ayushjaiswal0001/youtube/actions/runs/45196390881) | 64.501 s, 1920×1080, 30 fps, h264/aac, 7.98 MB | `514039ee09831006c883853874e3f58be3faa5671113afc643799d63cbfdef16` | 27/27 | 25/25 | 10/10 re-hashed | **CLOUD VERIFIED** |
| 5 | Nexus Node | 16:9 long-form | `long-nexus-power-grid` | [45196415411](https://github.com/Ayushjaiswal0001/youtube/actions/runs/45196415411) | 219.900 s, 1920×1080, 30 fps, h264/aac, 46.30 MB | `48013917bffa02e427aff85ea6e56cbba852aa1de415eac2ba9e20be6a452ed3` | 25/25 | 24/24 | gate-verified on runner | **CLOUD VERIFIED (run-reported)** |
| 6 | Academic Biohacker | 16:9 long-form | `long-academic-study-protocol` | [45196440363](https://github.com/Ayushjaiswal0001/youtube/actions/runs/45196440363) | 218.933 s, 1920×1080, 30 fps, h264/aac, 43.57 MB | `29a2c29a1b902af15c46950cf2815256c111d0a8f14764c5c29d6f45fb4508e3` | 25/25 | 24/24 | gate-verified on runner | **CLOUD VERIFIED (run-reported)** |

Rows 5 and 6 were downloaded and fully re-verified at the previous commit `9307836` (223.100 s / 218.933 s,
8/8 manifest, 24/24 gate). The only change between `9307836` and `218a6d5` is the portrait Hindi camera ratio,
which no landscape renderer reads. That is a reason to expect the same result, not evidence of it — hence the
distinct status.

## What each row proves

- **Format correctness**: 1080×1920 for Shorts, 1920×1080 for long-form, 30 fps, H.264 video, AAC audio, non-zero
  duration, all measured with `ffprobe` on the downloaded file (rows 1–4) or reported by the run's QC (rows 5–6).
- **QC on the actual file**: 25 checks for Shorts and the card renderer, 27 for the staged Hindi episode. The
  suite includes `mp4_container`, `video_stream`, `audio_stream`, `resolution`, `frame_rate`, `duration`,
  `freezedetect`, `audio_loudness` (`-14 LUFS`, `-1.0 dBTP`), `caption_clearance`, `framing`, `focus_terms`,
  `thumbnail`, `captions_srt` and the rest.
- **Manifest integrity**: every artifact listed in `manifest.json` was re-hashed against the file on disk.
- **Publishing gate**: `publish_gate.json` exists, `ok: true`, with zero blockers. The gate refuses to pass without
  QC, a verified manifest, a caption collision count, and a private-by-default upload packet.
- **Caption clearance**: `subtitle_collision_frames == 0` on all six, including the portrait Hindi Short where the
  number had never been measured before this session (see below).

## The two defects this wave found

1. **`caption_clearance` was vacuous on the portrait Hindi path.** The episode merge dropped
   `subtitle_collision_frames`, and the gate read the missing key as `int(None or 0) == 0`. Once the merge carried
   the real number and the gate failed closed, run `45182902435` reported **803 of 961 frames** with the shorter
   character's chin behind the caption capsule. Cause: pair shots centred the cast at `0.7125` of frame height —
   1368 px — while the caption capsule starts at 1358. Fixed by moving the pair target to `0.55`, verified by a
   fresh render (0 collisions, 961 frames) and by run `45196207861` in the cloud.
2. **A kids channel could be built as not-for-kids.** `force_made_for_kids` was enforced only in
   `UploadRequest.validate()`, which the upload path never calls. `madeForKids: false` on Natkhat Toons produced
   `selfDeclaredMadeForKids: false`. Now rejected at construction.

## Not proven by this matrix

- No upload has been performed. Every credential slot is empty.
- No public publishing, no scheduling.
- Notification delivery: `delivered: False` (no webhook configured).
- Rows 5–6: independent artifact re-hash still outstanding because GitHub artifact downloads failed twice
  (`HTTP 503 Egress is over the account limit`, then TCP resets). The runs are green; artifacts are retained 14 days.
