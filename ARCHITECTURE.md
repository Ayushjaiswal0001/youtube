# ARCHITECTURE

## 1. Layer map

```
channels/<slug>.json ──┬─> factory/config.py (ChannelSpec)  ──> renderers, QA, publisher
                       └─> uploader/config.py (ChannelConfig) ──> router, identity, metadata
content/batch_<date>.json ──> factory/content/script.py (build_*_script) ──> Script
```

`factory/publisher.py` is the only bridge into `uploader/`. Nothing else in `factory/`
may import the API layer.

## 2. Module inventory (uncommitted state)

| Module | LOC | Role |
| --- | --- | --- |
| `uploader/cli.py` | 386 | operator CLI: `sources, scope-check, consent, verify, dry-run, upload, status, history` |
| `uploader/router.py` | 324 | per-channel dispatch; refuses mismatch; wraps ledger + identity |
| `uploader/oauth.py` | 308 | loopback consent flow, refresh, scope enforcement |
| `uploader/credentials.py` | 295 | env → files → legacy resolution, never logs secrets |
| `uploader/ledger.py` | 279 | dedupe + state machine (`uploading/uploaded/failed/unknown`) |
| `uploader/metadata.py` | 342 | title/description/tag/playlist validation, length limits |
| `uploader/identity.py` | 132 | `channels.list(mine=true)` handle/ID preflight and postcheck |
| `uploader/youtube.py` | 241 | `videos.insert` resumable upload + `videos.list` stats |
| `uploader/http.py` / `retry.py` / `errors.py` / `logging.py` | 298 | transport, backoff, typed errors, secret-safe logging |
| `factory/config.py` | 221 | paths, palettes, `ChannelSpec`, strict config validation |
| `factory/orchestrator.py` | 205 | `render_episode`: plan → video + thumbnail + SRT + QC + state |
| `factory/cli.py` | 263 | `plans, render, qc, publish, analytics, batch, doctor` |
| `factory/content/script.py` | 302 | plan → `Script` (validates beats, word count 60–140, ≥2 sources) |
| `factory/content/models.py` | 144 | `Script`, `ScriptLine`, `Narration`, `WordTiming` |
| `factory/media/english_renderer.py` | 675 | PIL/numpy + Chrome frame engine, ffmpeg mux |
| `factory/media/hindi_renderer.py` | 153 | Natkhat wrapper: overlays + `studio.pipeline.episode` |
| `factory/media/hindi_text.py` | 280 | Devanagari overlay PNGs via headless Chrome |
| `factory/media/tts.py` | 239 | Edge-TTS per line + word boundaries, gTTS fallback |
| `factory/media/music.py` | 138 | procedural bed + narration mix (numpy) |
| `factory/media/captions.py` | 135 | `timeline.json` → SRT |
| `factory/media/thumbnail.py` | 262 | frame grab + title overlay, 1280x720 |
| `factory/qa/validator.py` | 234 | geometry, codec, duration, loudness, title/tags/desc, thumbnail, SRT |
| `factory/state.py` | 163 | `history.json`, `runs.jsonl`, `series.json`, series advance |
| `factory/publisher.py` | 165 | `build_upload_data`, `publish_episode`, `analytics_for` |
| `studio/*` (partial) | 4 files | PyCairo rig/background/scene engine for Hindi |

## 3. Render pipeline (per episode)

```
plan ──build_english_script / build_hindi_script──> Script
        │
        ├─ english: synthesize_script (Edge-TTS per line) ─> render_english ──> video.mp4 + timeline.json
        └─ hindi  : render_story_overlays (Chrome PNGs)
                    └─ studio.pipeline.EpisodePipeline().produce_episode(story)
                       └─ copy ─> video.mp4, timeline.json
        │
        ├─ thumbnail.py      ──> thumbnail.jpg (1280x720)
        ├─ captions.py       ──> captions.srt
        ├─ qa/validator.py   ──> qc.json (errors block publish)
        └─ state.ChannelState ─> history.json + runs.jsonl
```

Output layout: `build/<slug>/<plan_id>/` (English) and
`build/<slug>/<slug>_<plan_id>/` (Hindi), both under `FACTORY_BUILD_DIR`.

## 4. Publish pipeline

```
factory.publish_episode
  ├ gate: FACTORY_ALLOW_UPLOAD (execute)
  ├ gate: FACTORY_ALLOW_SCHEDULE (publishAt)
  ├ gate: --confirm-channel == spec.slug
  ├ build_upload_data: title/desc/tags/category/madeForKids/privacy/publishAt
  └ uploader.ChannelRouter.upload(slug, video, data, execute, confirm_channel, allow_public)
       ├ CredentialManager.resolve(slug)        # env -> file -> legacy
       ├ scope assert (youtube.upload, youtube.readonly only)
       ├ IdentityAssertion.preflight            # channels.list(mine=true) vs expected ID/handle
       ├ Ledger.check (sha256 dedupe)
       ├ videos.insert (resumable)              # private unless allow_public
       ├ IdentityAssertion.postcheck            # response channelId must match
       └ Ledger.mark(uploaded, video_id)
```

## 5. State persistence

| Store | Location | Survives CI? |
| --- | --- | --- |
| `pipeline_state/<slug>/history.json` | repo | only if committed back or cached |
| `pipeline_state/<slug>/series.json` | repo | same — **required** for Natkhat continuity |
| `pipeline_state/<slug>/runs.jsonl` | repo (append-only) | same |
| upload ledger | `~/.faceless-shorts/state/...` | no — needs `YT_STATE_ROOT` override in CI |
| `build/` artifacts | repo (gitignored) | no — intended for Actions artifacts |

`factory/config.py` already honours `FACTORY_BUILD_DIR`, `FACTORY_STATE_DIR`,
`FACTORY_LOG_DIR`, `YT_SECRETS_ROOT`, `YT_STATE_ROOT` — CI wiring should use these
rather than editing code.

## 6. GitHub Actions architecture (target)

```
.github/workflows/
  ci.yml                    # exists: compileall + unittest on 3.11/3.12
  produce-nexus.yml         # cron 14:30 UTC (20:00 IST)  -> render, QC, upload, verify
  produce-academic.yml      # cron 06:30 UTC (12:00 IST)
  produce-natkhat.yml       # cron 12:30 UTC (18:00 IST)
  keepalive.yml             # (optional) refresh OAuth before 7-day expiry
```

Each produce workflow: `workflow_dispatch` + `schedule` + `concurrency` lock +
`timeout-minutes` + retry wrapper + artifact upload (`build/`, `qc.json`,
`runs.jsonl`) + state commit-back or cache restore/save + failure notification.

Cron must be UTC. IST publish times map to `publishAt` (RFC3339 with `+05:30`), which
requires the video to be uploaded as `private` with a future `publishAt` — already
implemented in `publisher.build_upload_data`.

## 7. Known architectural gaps

1. No topic research / script authoring stage — the pipeline cannot generate a plan.
2. No series generator for Natkhat — episodes exist only as pre-written plans.
3. No workflow files beyond `ci.yml`; no `requirements.txt`.
4. No test coverage for anything in `factory/` (50 tests cover `uploader/` only).
5. `studio/` in the repository is an incomplete 4-file copy of `D:\animated\studio`.
6. `hindi_renderer` mutates `studio.config` module attributes and relies on
   `studio.pipeline.episode` being imported *after* that mutation — fragile.
