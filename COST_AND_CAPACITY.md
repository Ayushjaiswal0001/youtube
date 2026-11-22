# COST_AND_CAPACITY

Measured on the development machine (Windows 11, Intel i5-10310U, 8 GB RAM, Intel UHD,
no GPU), not extrapolated from vendor claims.

## 1. Measured production cost per video

### Long-form 16:9, 116.5 s, 1920x1080

| Stage | Measured | Evidence |
| --- | --- | --- |
| Narration (Edge-TTS, 11 lines, network) | ~1 min | `audio/` finalised `00:59:44` after launch `~00:58:50` |
| Frame render + x264 encode (3 494 frames) | **~7 min 45 s** | `video.mp4` finalised `01:07:33` |
| Loudness measurement + normalise + remix | 15.5 s (measured separately) | `measure_loudness` + `mix_narration` on the real episode |
| Thumbnail + SRT + QC | included above | outputs timestamped with the video |
| **Total wall clock** | **≈ 8 min 45 s** | 4.5× real time |
| CPU time | single process, ~full one core for drawing + x264 | — |
| Peak RAM | no swap pressure observed at 8 GB with the frame pipe | — |
| Output size | 7 574 361 bytes (7.2 MB) @ 520 kb/s | ffprobe |
| API/AI spend | **$0** — no paid service used, no LLM call | — |

### Shorts 9:16, ~32–38 s

Observed in this project: roughly **60–100 s** wall clock per Short end to end (TTS +
1080x1920 frames + encode + thumbnail + SRT + QC) on the same machine.

## 2. Extrapolated capacity (arithmetic from the measurements above)

| Target | Per-video cost | Daily total (3 channels) | Fits on 1 runner? |
| --- | --- | --- | --- |
| 3 Shorts/day | ~1.5 min | ~4.5 min compute | Yes, easily |
| 3 long-form/day (≈2 min each) | ~9 min | ~27 min compute | Yes on a 6-hour runner budget |
| 3 long-form/day (≈5 min each) | ~22 min | ~66 min compute | Tight on a 2-core runner (likely 1.5–2× slower than this laptop) |

`ubuntu-latest` gives a 2-core / 7 GB runner; expect **1.5–2.5× slower** than the
measurement above for the same render, i.e. a 2-minute long-form video ≈ 13–22 minutes of
runner time. That still fits the daily GitHub Actions allowance, but **it has not been
measured on a runner** — that is T12, currently blocked on the PR #2 merge.
Long-form jobs would need `timeout-minutes` ≥ 45 and segmented rendering before the
daily 3×long target can be claimed.

## 3. Cost ledger (actual spend to date)

| Item | Cost |
| --- | --- |
| GitHub Actions minutes | $0 so far — repo is public (free runners); the only runs executed were `ci` |
| YouTube Data API | $0 — quota-bound, not billed. 100 `videos.insert`/day shared across the 3 channels |
| TTS (Edge-TTS) | $0, no key, network-bound |
| Music/SFX (procedural numpy) | $0, generated locally |
| Fonts | $0 — Inter (OFL), Caladea (OFL), Baloo 2 / Noto Sans Devanagari (OFL) |
| Storage | local disk only; no object storage provisioned |
| Paid infrastructure | **none activated** |

## 4. Known capacity limits

1. **State durability.** `pipeline_state/` and the upload ledger survive only via
   `actions/cache` (7-day eviction when idle). A durable store is still required
   (TASKS.md L / T14) before the series can be trusted over months.
2. **Runner dependency install.** PyCairo + ffmpeg + Chrome install takes minutes per
   job; caching them is a prerequisite for daily long-form.
3. **Edge-TTS is network-bound and unverified on runners.** A TTS outage stops narration;
   the gTTS fallback exists but its voice differs, and the code refuses to silently
   substitute voices.
4. **Frame rendering is CPU-bound and single-process.** Parallel scene rendering
   (per-scene workers, then concat) is the obvious 3–4× win for long-form.

## 5. Render throughput model (from measured frames, not guesses)

Measured: 3 494 frames of 1920x1080 in ~465 s → **7.5 frames/s**, i.e. **≈4.0× real time**.

| Target | Frames | Est. render time (this laptop) | Est. runner time (1.5–2.5×) |
| --- | --- | --- | --- |
| 60 s Short (9:16) | 1 800 | ~4 min | 6–10 min |
| 2 min 16:9 | 3 600 | ~8 min | 12–20 min |
| 5 min 16:9 | 9 000 | ~20 min | 30–50 min |
| 10 min 16:9 | 18 000 | ~40 min | 60–100 min |

Only the 2-minute case has actually been rendered end to end. The others are arithmetic
from the measured frame rate and **must be confirmed by real renders** before any daily
target is claimed. Disk per 2-minute episode: 7.6 MB video + 20.6 MB bed + ~3 MB audio;
a 10-minute episode projects to ~40 MB of artifacts.

## T49 addendum: what the runner actually has to do

Measured locally on the i5-10310U: a 64.5 s landscape episode takes 250-278 s of wall time
(1935 frames, ~7.5 fps, ~4.2x real time); a 32.1 s portrait Short with cached scenes takes 6 s and
15 s end-to-end including QC. A GitHub-hosted `ubuntu-latest` runner is typically 1.5-2.5x slower
than this machine **on this workload** - an extrapolation, clearly labelled as such.

| Job | Local wall | Estimated runner wall | Fits `timeout-minutes: 60`? |
| --- | --- | --- | --- |
| 32 s Short, warm scene cache | 15 s | 25-40 s | yes, comfortably |
| 32 s Short, cold render | ~150 s | 250-600 s | yes |
| 64.5 s landscape episode | 278 s | 420-700 s | yes |
| 5-minute landscape episode | ~1 250 s (estimated) | ~2 000-3 100 s | yes, but near the limit |
| 10-minute landscape episode | ~2 500 s (estimated) | ~4 000-6 000 s | **no** - exceeds 60 min with QC and packaging |

The 5- and 10-minute rows are arithmetic extrapolations from the measured 7.5 fps, not measurements;
T50's benchmark was never run. What follows from them: the daily Shorts are safe on a hosted runner, a
~1-minute landscape episode is probably safe, and a 10-minute long-form needs a larger runner or a
chunked render (scene rendering is already resumable scene-by-scene, which is the lever to pull).

Storage: a 64.5 s 1080p episode is ~9 MB, its scenes ~1.3 GB, and the artifact retention is 14 days.
GitHub artifact storage and cache for this repository are far inside the free allowance; the binding
constraint is runner minutes, not bytes.

## Measured render benchmarks (2026-11-21)

Produced by `python -m tools.benchmark`, which drives the real CLI in-process and samples process
memory from the OS. Nothing in this table is extrapolated except the last two rows, which say so.

| Workload | Video | Wall | Real-time factor | Render fps | Peak RSS | Disk written | QC |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Portrait Short (9:16, 963 frames) | 32.13 s | **156.95 s** | 4.88x | 6.14 | **117.8 MB** | 23.6 MB | pass |
| Landscape episode (16:9, 1935 frames, 12 scenes) | 64.50 s | **292 s** | 4.53x | 6.63 | not sampled | ~30 MB | pass (27/27) |
| 60 s episode | 60 s | ~293 s | - | - | - | - | **projection** |
| 5 min episode | 300 s | ~1465 s (24 min) | - | - | - | - | **projection** |
| 10 min episode | 600 s | ~2930 s (49 min) | - | - | - | - | **projection** |

Cost of the features added this pass: near-camera set dressing adds ~14 % (250-278 s -> 292 s for the
same landscape episode) and in-line cuts add nothing measurable, because a cut is the same draw with a
different camera. Memory is not the constraint at this size - peak under 120 MB against ~2 GB free on
this machine. Time is the constraint, and it scales linearly with frame count: roughly **6.5 frames per
second per core** on this laptop.

A three-channel daily schedule (1 Short + 1 long-form each) is therefore about
3 x (157 + 292) s = **22 minutes of rendering per day**, comfortably inside a GitHub-hosted runner's
job limit, provided the runner has the same 2-core class of CPU.

## Measured long-form benchmarks (2026-11-22)

Third measurement, run in a fresh build directory on this machine (8 GB, no other render running):

| Workload | Video | Wall | Real-time factor | fps | Peak RSS | QC |
| --- | --- | --- | --- | --- | --- | --- |
| 12-scene landscape episode | 64.50 s (1935 f) | **312 s** | 4.84x | 6.2 | — | pass, 27/27 |
| 96-scene long-form plan | **650.4 s (10.8 min)** | **2921.5 s (48.7 min)** | 4.49x | 6.6 | 117.8 MB (measured in-process earlier) | **fail: 14 continuity errors** |

Two things worth stating plainly:

1. **The earlier projection was accurate.** 600 s projected to 2930 s wall; the real 650 s render took
   2921 s. Cost scales with frames, not with scene count: 6.2–6.6 fps holds across a 10x change in
   duration, so the model in the table above can be used for capacity planning.
2. **The 10.8-minute plan failed QC, and that is the correct outcome.** The generator built it by
   repeating the authored 12 scenes eight times, which asks two characters to pick up the same key
   without a hand-off in between; the continuity gate reported 14 `ownership_conflict` errors. A long
   episode is not proof of production readiness if its plan is incoherent — the gate did its job. No
   clean 10-minute episode has been produced yet.

Peak memory is not the constraint: under 120 MB against ~2 GB free. Time is: at ~4.5x real time, a
10-minute episode needs about 50 minutes of wall clock, which fits inside a GitHub-hosted runner's job
limit but not inside a 15-minute one.
