# PROJECT_CONTEXT

Permanent context for the Autonomous Multi-Channel YouTube Factory. Read this first.
Do not store secrets here or in any committed file.

Last audited: 2026-11-20 (repository HEAD `a69474c` + uncommitted work on
`feat/autonomous-multichannel-factory`).

## 1. Identity

| Item | Value |
| --- | --- |
| Canonical repository | `https://github.com/Ayushjaiswal0001/youtube` (**public**) |
| Canonical repository (only one allowed) | `https://github.com/Ayushjaiswal0001/youtube` (**public**). Never fork to, mirror to, or push from `Ayushjaiswal001`; that account is not this project. |
| Working clone | `C:\Users\DELL\AppData\Local\Temp\opencode\youtube` |
| Default branch | `main` @ `a69474c` |
| Development branch | `feat/autonomous-multichannel-factory` (unpushed) |
| Language | Python 3.11+ (3.12 locally), no third-party deps in `uploader/` |
| Predecessor project | `D:\animated` (Autonomous Daily Hindi Animation Studio) |

Note: `https://github.com/Ayushjaiswal001/yt-` mentioned in the handoff brief returns 404.
`Ayushjaiswal0001/youtube` is the only repository that exists and the only one this clone tracks.

## 2. Channels

| Slug | Title | Handle | Expected channel ID | Language | Publish (IST) |
| --- | --- | --- | --- | --- | --- |
| `nexus-node` | Nexus Node | `@nexusnode012` | `UCx9O8VivWkiEylDjs5_Zzag` | en | 20:00 |
| `academic-biohacker` | Academic Biohacker | `@academicbiohacker` | `UCr8jSmLa_o2BwNh8HuyZHAQ` | en | 12:00 |
| `natkhat-toons` | Natkhat Toons | `@NatkhatToons-n5` | `UC4OCY0qDwQqFnSCZw12sKxA` | hi | 18:00 |

Niche per channel lives in `channels/<slug>.json` under `factory.niche`.
`channels/<slug>.json` is also the uploader's channel config (single source of truth
for identity, metadata defaults, and factory settings).

## 3. Vision

One repository that, without human intervention, produces and publishes one video per
day per channel to YouTube, using only free/local tooling:

- Topic research → script → storyboard → visuals → TTS → music/SFX → render →
  subtitles → thumbnail → metadata → QC → upload → verification → logging.
- Runs on GitHub Actions, scheduled in Asia/Kolkata (UTC cron).
- Never publishes public content without an explicit approval gate.
- Never uploads a duplicate; never uploads to the wrong channel.

## 4. Two-layer design

1. **`uploader/`** — hardened, dependency-free YouTube layer. Owns OAuth, credential
   resolution, identity verification, dedupe ledger, retries, media/metadata validation,
   resumable upload, post-upload channel verification. 50 unit tests, CI on 3.11/3.12.
2. **`factory/`** — content layer. Turns a *plan* into a rendered video, thumbnail, SRT,
   QC report, and (optionally) an upload call through `uploader.router`.

`factory/` deliberately never talks to the YouTube API directly.

## 5. Production engines

| Engine | Used by | Status | Tech |
| --- | --- | --- | --- |
| `factory/media/english_renderer.py` | nexus-node, academic-biohacker | working (2 videos rendered) | PIL/numpy frame drawing + headless Chrome for text/overlays, ffmpeg mux |
| `factory/media/hindi_renderer.py` + `studio/` | natkhat-toons | **broken in repo copy** | PyCairo vector rigs + ffmpeg |

Narration: Edge-TTS neural voices (`en-US-AndrewNeural`, `en-US-AvaNeural`,
`hi-IN-MadhurNeural`) with gTTS fallback and word-boundary timings.

## 6. Content model (critical)

`factory` is **plan-driven**, not research-driven. A plan is a hand-authored JSON
object in `content/batch_<date>.json`:

- English plan: `id, title, topic, hook, hook_headline, hook_visual, beats[] (>=4),
  payoff, payoff_headline, cta, cta_headline, tags[], sources[] (>=2), slot`
- Hindi plan: `id, title, topic, hook, series, series_title, episode, moral, scenes[]
  (>=3, each with dialogue/speaker/poses/bg/sfx), tags[]`

`factory/config.py` exposes `ChannelSpec.queries` per channel, but **nothing consumes
it** — topic research and script authoring are not implemented.

## 7. Existing batch

`content/batch_2026-11-20.json` (`batch_id: 2026-11-20-nine-short-batch`): 3 plans per
channel, 9 total. Five are rendered, four are pending. Once these are consumed the
pipeline has no source of new plans.

## 8. Credentials

Resolution order (see `uploader/credentials.py`):

1. Environment: `YT_<SLUG_UPPER_SNAKE>_CLIENT_ID` / `..._CLIENT_SECRET` / `..._REFRESH_TOKEN`
2. Files in `%USERPROFILE%\.faceless-shorts\secrets\youtube\` (3 present locally)
3. Read-only legacy file `D:\animated\ytcredetials.txt` (never modified, never commit)

Scopes must be exactly `youtube.upload` + `youtube.readonly`. One OAuth client/project
is shared by all three channels, so the 100 `videos.insert` calls/day quota is shared
(3 uploads/day is not a constraint). Refresh tokens from a Testing-mode OAuth app
expire after 7 days.

## 9. Runtime state (outside the repo on a workstation)

| Purpose | Path |
| --- | --- |
| Secrets | `~/.faceless-shorts/secrets/youtube/` |
| Upload ledger | `~/.faceless-shorts/state/youtube/<slug>/` |
| Logs | `~/.faceless-shorts/logs/youtube/` |

Inside the repo (`FACTORY_STATE_DIR`, default `pipeline_state/`): `history.json`,
`runs.jsonl`, `series.json` (Natkhat series memory), and `studio_data/`.
This in-repo state is what must survive between CI runs.

## 10. Technical decisions already made (do not silently reverse)

- Private-by-default uploads; public requires `--allow-public` **and** the channel
  config's `allow_public_upload`, which is `false` everywhere.
- Real uploads additionally require `FACTORY_ALLOW_UPLOAD=1`; scheduled releases
  require `FACTORY_ALLOW_SCHEDULE=1`.
- `--confirm-channel <slug>` must match the selected channel exactly.
- Natkhat Toons is child-directed: `madeForKids` is forced `true`; `false` is rejected.
- Dedupe by SHA-256 of the video file; `unknown` ledger state is a hard stop.
- No third-party runtime dependency in `uploader/`; optional deps only in `factory/`.

## 11. Hardware / CI constraints

Local: Windows 11, Intel i5-10310U, 8 GB RAM, Intel UHD (no CUDA). ffmpeg and Chrome
are installed. The factory targets `ubuntu-latest` runners, which needs verified
PyCairo, Chrome, and Edge-TTS network availability (not yet proven — see
`DEVELOPMENT_STATUS.md`).
