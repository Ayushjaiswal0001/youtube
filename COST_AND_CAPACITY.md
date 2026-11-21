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
