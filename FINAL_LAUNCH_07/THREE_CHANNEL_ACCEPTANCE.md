# THREE-CHANNEL LOCAL ACCEPTANCE (measured, fresh build directories)

Every run: `python -m factory.cli render --channel <slug> --format <shorts|long> --json` with a fresh
`FACTORY_BUILD_DIR` and `FACTORY_STATE_DIR` under `C:/Users/DELL/AppData/Local/Temp/acc7b/<channel>/`.

| Channel / format | Duration | Frames | Wall | QC | Failed checks | sha256 (16) |
| --- | --- | --- | --- | --- | --- | --- |
| Nexus Node, shorts | 39.966 s | 959 | 186 s | **PASS** | none | `8f60cf7fc6ecc4c7` |
| Academic Biohacker, shorts | 38.233 s | 917 | 202 s | **PASS** | none | `c703817c3af1f2a6` |
| Natkhat Toons, shorts | 32.135 s | 963 | 150 s | **PASS** | none | `8d724eaee7317cb5` |
| Natkhat Toons, long | 64.501 s | 1935 | 287 s | **PASS (27/27)** | none | `c31d8d18b8529f8e` |

Artifact paths (all under the temporary acceptance root, not in the repository):

- `acc7b/nexus-node/build/nexus-node/nexus-agents-leave-chat/video.mp4`
- `acc7b/academic-biohacker/build/academic-biohacker/academic-brain-wash/video.mp4`
- `acc7b/natkhat-toons/build/natkhat-toons/natkhat-toons_natkhat-haveli-e1/video.mp4`
- `acc7b/natkhat-long/build/natkhat-toons/<episode>/video.mp4`

Encoding: H.264 `yuv420p`, AAC 192 kbps stereo; 1 080 x 1 920 at 24 fps for the portrait Shorts,
1 920 x 1 080 for the landscape episode.

## Frozen frames across the four artifacts

| Stage | Nexus | Academic | Natkhat short | Natkhat long |
| --- | --- | --- | --- | --- |
| Before this directive | 1.5 s @ 18.3 s | 2.2 s @ 6.2 s | none | none |
| After the first partial fix | 2.0 s @ 38.0 s | 2.3 s @ 35.9 s | none | none |
| After the complete fix | **none** | **none** | none | none |

`audio_loudness` after the limiter: -14.3 LUFS, -1.5 dBTP on both English channels (academic measured
-0.7 dBTP before the limiter, against a -1.0 dBTP limit).

## Visual inspection

Frames were extracted at the previously failing timestamps and around the tail, then looked at directly:

- `nexus-node` @ 18.6 s: robot card, headline "FROM CHAT TO WORK" fully legible inside its safe area, two
  concentric dashed rings at clearly different angles, caption readable.
- `nexus-node` @ 39.4 s (the tail that used to freeze): end card "FOLLOW NEXUS NODE / 01", rings at new
  angles and the orbit dots moved - visibly different from 18.6 s.
- `academic-biohacker` @ 6.5 s and 37.8 s: same treatment, no smear, no clipping, subtitle clear.

The motion is a slow push-in (never more than 6 %), two counter-rotating accent rings, and a light sweep.
It reads as motion graphics rather than a stall, and the type stays sharp.

## Research re-check (same day)

`python -m factory.cli research --channel academic-biohacker --limit 3 --date 2026-11-22 --json` returned
**3 candidates, 0 errors, 3 sources** (`arxiv-lg`, `arxiv-qbio`, `nature-news`). The previous
"0 candidates, 1 source error" was a **transient feed failure**, recorded and skipped by design rather than
fatal - not a scoring defect. Nexus Node returns 3 candidates from 4 sources.

Open editorial finding, not fixed: the top academic-biohacker candidate scored 0.62 and is a Nature
astronomy story. The relevance floor is too permissive for a learning-science channel. Recorded as a defect
rather than papered over with a weaker filter.
