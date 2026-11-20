# DEVELOPMENT_STATUS

Audited 2026-11-20 against HEAD `a69474c` plus uncommitted work in
`feat/autonomous-multichannel-factory`. Every claim below was verified by running the
code, not by reading commit messages.

## Verdict

| Area | State |
| --- | --- |
| Uploader (`uploader/`) | **Production-grade, tested, live-verified** |
| English render (nexus, academic) | **Working** — 2 of 6 plans rendered |
| Hindi render (natkhat) | **Fixed** — studio restored, 4 episodes render + QC clean |
| Factory test suite | **Present** — 27 plan/publish-gate tests |
| GitHub Actions production | **Written, never executed** (`produce.yml` + 3 callers) |
| Autonomous topic/script generation | **Working** — `factory plan new`, topic banks, series engine |
| Natkhat series continuity | **Half** — state helpers exist, no generator wired |
| Repo hygiene / preservation | **At risk** — all factory work uncommitted, unpushable |

## Verified working

- `python -m compileall -q uploader factory studio` → exit 0.
- `python -m pytest tests -q` → **50 passed** (uploader only).
- `python -m factory.cli doctor` → ffmpeg OK, ffprobe OK, Chrome OK, fonts OK,
  build_root OK, 3 channel configs OK.
- `python -m factory.cli plans` → 9 plans, 5 rendered / 4 pending.
- Rendered artifacts on disk: `academic-brain-wash` (2.84 MB),
  `nexus-agents-leave-chat` (2.16 MB), `natkhat-haveli-e1/e2/e3` (3.49/3.66/3.49 MB),
  each with `thumbnail.jpg`, `captions.srt`, `timeline.json`, `qc.json`
  (all QC `ok: true`, durations 32–40 s).
- Uploader live private uploads recorded in `~/.faceless-shorts/state/youtube/*/ledger.jsonl`:
  `nexus-node → eSZvxaRVYk8`, `academic-biohacker → bN2A2Zsmobk`,
  `natkhat-toons → v2G0TitayD0` (one earlier `failed` attempt for nexus, retried).
- CI (`ci.yml`) passed on 3.11 and 3.12 at `a69474c`.

## Added since the first audit (all verified locally)

| Item | Evidence |
| --- | --- |
| `studio/` completion | 11 modules restored; `render --channel natkhat-toons --plan-id natkhat-haveli-e1` → 32.07 s, `qc_ok: true` |
| Thumbnail fonts | `Inter-Black`, `Inter-ExtraBold`, `Caladea-Bold` restored; regenerated thumbnails byte-identical to originals |
| Plan generation | `factory plan new --channel X`, `factory plan status`; banks in `content/topics/*.json` (6 topics per English channel) |
| Generated English plan | `academic-post-meal-walk` rendered: 38.36 s, 17 cues, `qc_ok: true`, 2.52 MB |
| Natkhat series engine | `content/series/natkhat-toons.json` (haveli e4–e6, then `natkhat-jungle` e1–e3); `natkhat-haveli-e4` rendered: 31.63 s, `qc_ok: true` |
| Continuity rule | Out-of-order planning raises `PlanGenerationError` ("episode natkhat-haveli-e3 is not in history, not uploaded"); unit-tested |
| Batch merging | `load_plans_for` merges every `batch_*.json`, oldest first, dedupes by id |
| Studio path binding | `_load_pipeline` purges `studio*` modules so two renders in one process use their own dirs; unit-tested |
| Tests | 77 total pass (`python -m pytest tests -q`): 50 uploader + 27 factory |
| Dependencies | `requirements.txt` (numpy, pillow, edge-tts, gTTS, pycairo) |
| CI | `ci.yml` now has an `uploader` job and a `factory` job (libcairo2-dev + requirements + 27 tests + CLI smoke) |
| Workflows | `.github/workflows/produce.yml` (reusable) + `produce-nexus-node|academic-biohacker|natkhat-toons.yml` (cron 14:30 / 06:30 / 12:30 UTC) |

## Partially implemented

| Item | What exists | What is missing |
| --- | --- | --- |
| `studio/` in repo | `config.py`, `qa/validator.py`, `animation/background.py` (incl. new `haunted_haveli` + `village_night`), `animation/scene_renderer.py` | **9 modules**: `story_engine.py`, `characters/{chiku,gappu,rig_base}.py`, `audio/{tts_engine,sfx_library}.py`, `animation/{camera,effects}.py`, `pipeline/episode.py`, `__init__.py`. Only compiled `.pyc` files remain. |
| Natkhat continuity | `ChannelState.series/next_episode/advance_series` | Not called by any command; no `series.json` on disk; episode numbers come from the static batch |
| Publish path | `publish_episode`, gates, router | Never exercised end-to-end from the factory CLI (no dry-run output recorded) |
| Thumbnail | `thumbnail.py` + QC check | Exists and works for rendered episodes |
| `skills/faceless-shorts` | Vendored subset (scripts, library, reference, tests) | `styles/` (the six engines) not vendored; nothing imports it (`SKILL_ROOT` unused) |
| Analytics | `analytics_for` + `videos_stats` | Untested against the live API |

## Completely missing

1. `requirements.txt` / `pyproject.toml` — imports `numpy`, `PIL`, `edge-tts`, `cairo`,
   `gtts`; `ci.yml` installs nothing.
2. `.github/workflows/produce-*.yml` — no scheduled production, no manual dispatch,
   no concurrency lock, no artifacts, no state persistence.
3. Topic research and script generation for any channel.
4. Natkhat series generator (new series after `finale`, per-scene authoring).
5. Tests for `factory/` and `studio/`.
6. Publish-side integration test with a fake API (router is tested; publisher is not).
7. Secret provisioning in GitHub Actions (`YT_<SLUG>_*`, `FACTORY_ALLOW_*`).
8. Failure notification / retry policy at workflow level.
9. Long-form (`format: "long"`) production — `VIDEO_SIZES["long"]` exists, no renderer
   or plan supports it.

## Broken

1. **Hindi render is dead in this repository.**
   `from studio.pipeline.episode import EpisodePipeline` →
   `ModuleNotFoundError: No module named 'studio.pipeline.episode'`.
   `factory.cli render --channel natkhat-toons --force` cannot succeed until the
   studio modules are restored.
2. **Cannot push.** `git push --dry-run origin feat/autonomous-multichannel-factory` →
   `403 Permission to Ayushjaiswal0001/youtube.git denied to Ayushjaiswal001`.
   `gh api repos/Ayushjaiswal0001/youtube` reports `permissions.push: false`.
   Six days of work exists in one directory under `%TEMP%` only.
   Owner constraint: `Ayushjaiswal0001/youtube` is the **only** repository that may be
   used — no fork, mirror, or push through `Ayushjaiswal001`. Work stays local until
   owner-side access exists.

3. **Assets are gitignored.** `.gitignore` has global `*.wav`, so
   `assets/music/whimsical_bgm.wav` and `assets/sfx/*.wav` can never be committed
   without a negation rule — the renderers need them.
4. Two of the four `studio/` files that do exist are **newer and different** from the
   `D:\animated` versions (portable `config.py`, extra backgrounds), so restoring the
   missing modules is a targeted copy, not a wholesale overwrite.

## Unverified risks

| The three `produce-*.yml` workflows have never run | Cron may fail on the first real day | One manual dispatch with `upload: false` |
| Topic banks hold 6 topics per English channel; haveli 3 + jungle 3 episodes | ~6 days of autonomy, then `plan new` stops with a clear "exhausted" error | Extend `content/topics/` and `content/series/` |
| Risk | Impact | How to settle it |
| --- | --- | --- |
| PyCairo + headless Chrome + Edge-TTS on `ubuntu-latest` | Hindi render may be impossible in CI | One throwaway workflow run |
| Edge-TTS requires outbound network; no SLA | English render fails on runner egress block | Same run |
| Testing-mode OAuth refresh tokens expire in 7 days | All three channels stop publishing | Check OAuth app status; add keepalive/re-consent |
| 100 `videos.insert`/day shared across channels | Fine at 3/day, breaks if a backfill loop is added | Keep batch uploads ≤ 90/day |
| GitHub Actions `schedule` skips/lags | "Daily" is best-effort | Publish schedule via `publishAt`, verify after |
| Public repository | Any accidental secret commit is permanent | Pre-commit secret scan; secrets only via Actions |

## Testing status summary

| Suite | Command | Result |
| --- | --- | --- |
| Uploader unit tests | `python -m pytest tests -q` | 50 passed |
| Factory unit tests | — | none exist |
| Factory smoke | `python -m factory.cli doctor` / `plans` | pass |
| English render | `render --channel nexus-node --plan-id ...` | pass (already rendered) |
| Hindi render | `render --channel natkhat-toons --plan-id natkhat-haveli-e1 --force` | pass (32.07 s, qc_ok) |
| Generated-plan render | English + Hindi, generated by `plan new` | pass (38.36 s / 31.63 s, qc_ok) |
| Factory tests | `python -m pytest tests/factory -q` | 27 passed |
| Workflows | dispatch `produce-*.yml` | **never executed** |
| Publish dry-run | `publish --channel <slug>` | not yet run |
| Workflow execution | — | no production workflow exists |
| Live upload | uploader CLI (private) | 3 succeeded |

## 2026-11-21 — long-form 16:9 engine and plan/format fixes

Added on `feat/landscape-16x9`:

- `factory/media/landscape_renderer.py` — native 1920x1080 composition profile: text
  column + diagram plate, animated motifs (nodes, bars, flow, grid, radial), chapter
  cards with ghost numerals, word-synced caption band, progress rail with chapter ticks.
- `content/longform/nexus-node.json` — *The Real Limit on AI Is Not Chips*, 332 words,
  8 beats, 4 chapters, 2 sources.
- Long-form script contract in `factory/content/script.py` (300–1800 words, ≥6 beats,
  chapters in metadata) and format-aware `load_plans_for` (shorts plans and long plans no
  longer mix).
- `find_plan` resolves plans across both composition profiles; `render`/`plans` accept
  `--format long`.
- 13 new tests (`tests/factory/test_landscape.py`); suite is now **92 passed**.

Verified render: 1920x1080, 116.467 s, h264+aac, `qc_ok: true`, 52 cues, −29.2 dB mean,
7.57 MB, ≈8 min 45 s of wall clock. Inspected on a 12-frame contact sheet and individual
frames; five composition defects were found and fixed during that inspection.

Not verified: any runner execution of this pipeline, Edge-TTS egress on a runner, and
upload of a long-form video.
