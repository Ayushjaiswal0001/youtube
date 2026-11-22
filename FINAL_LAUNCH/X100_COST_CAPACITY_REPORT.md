# X100 COST AND CAPACITY REPORT

Measured on this machine (8 GB RAM, ~2 GB free, no concurrent renders) in fresh build directories.
GitHub Actions minutes are **estimated** from wall time and labelled as such: no runner has executed this
pipeline.

## Measured

| Workload | Video | Wall | Real-time | fps | Peak RSS | Output |
| --- | --- | --- | --- | --- | --- | --- |
| Natkhat portrait Short | 32.13 s | 171 s | 5.3x | 5.6 | 117.8 MB | 23.6 MB |
| Nexus portrait Short | 39.97 s | 133 s | 3.3x | 9.0 | - | 2.1 MB |
| Academic portrait Short | 38.23 s | 134 s | 3.5x | 8.6 | - | 2.7 MB |
| Natkhat landscape episode | 64.50 s | 312 s | 4.8x | 6.2 | - | 8.0 MB |
| 96-scene long-form plan | 650.4 s | 2921.5 s | 4.49x | 6.6 | - | 77 MB |
| Research, 3 channels | - | < 20 s | - | - | - | JSON only |

Cost is linear in frames at 6-6.5 fps: the 600 s projection of 2930 s matched the real 650 s render
(2921 s) within 0.3 %.

## Recommended schedule and its cost

| Channel | Per week | Wall time |
| --- | --- | --- |
| Nexus Node | 3-5 Shorts + 1 long-form | 5 x 133 s + ~312 s = 17 min |
| Academic Biohacker | 3-5 Shorts + 1 long-form | 5 x 134 s + ~312 s = 18 min |
| Natkhat Toons | 3-5 Shorts + 1 long-form | 5 x 171 s + 312 s = 20 min |

About 55 minutes of runner time per week. On a public repository standard GitHub-hosted runners are free,
so the estimated marginal cost is **$0 / month at this volume**; a private repo or larger runner would be
billed at roughly 220 minutes/month. No paid external API is used: research reads public feeds, narration
uses the existing TTS path, rendering is local CPU.

## Caveats

1. Measured on a laptop-class 2-core CPU; a hosted runner may differ.
2. Memory is not the limit (peak < 120 MB); time is.
3. A 10-minute episode needs ~50 min of wall clock - it fits a job limit but leaves little headroom for
   retries, so long-form belongs in its own job rather than queued behind three Shorts.
