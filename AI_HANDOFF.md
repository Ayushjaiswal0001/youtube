# AI_HANDOFF

Instructions for any AI coding agent (or human) picking this project up. Read
`PROJECT_CONTEXT.md`, `ARCHITECTURE.md`, `DEVELOPMENT_STATUS.md`, `TASKS.md` first.
This file tells you what to do *right now*.

## 1. Where the work actually lives

- Clone: `C:\Users\DELL\AppData\Local\Temp\opencode\youtube`
- Branch: `feat/autonomous-multichannel-factory`
- Remote: `https://github.com/Ayushjaiswal0001/youtube` (public, `main` @ `a69474c`)
- Upstream `D:\animated` holds the complete `studio/` package the Hindi renderer needs.

**This directory is under `%TEMP%`.** Until it is pushed, a disk cleanup destroys the
project. Treat preservation as task zero.

## 2. Exact next development task

**T5 — restore the missing `studio/` modules, then re-render one Natkhat episode.**

Copy from `D:\animated\studio\` into the repo's `studio/`:

```
__init__.py
story_engine.py
characters/chiku.py
characters/gappu.py
characters/rig_base.py
audio/tts_engine.py
audio/sfx_library.py
audio/subtitle.py            # only if the renderer needs it
animation/camera.py
animation/effects.py
pipeline/episode.py
```

Do **not** overwrite the repo's newer versions of:

```
studio/config.py                  # portable, env-overridable paths
studio/animation/background.py    # adds haunted_haveli + village_night
studio/animation/scene_renderer.py
studio/qa/validator.py
```

Then verify:

```powershell
python -c "from studio.pipeline.episode import EpisodePipeline; print('ok')"
$env:FACTORY_BUILD_DIR = "$env:TEMP\factory-verify"
python -m factory.cli render --channel natkhat-toons --plan-id natkhat-haveli-e1 --force
python -m factory.cli qc --channel natkhat-toons --plan-id natkhat-haveli-e1
```

Expected: `qc_ok: true`, 1080x1920, h264+aac, 20–65 s. Use a scratch
`FACTORY_BUILD_DIR` so the three good existing renders in `build/` are untouched.

If the restored modules import symbols the repo's newer files no longer export
(likely candidates: `SceneRenderer.__init__`, `BackgroundRenderer.render_*`,
`TTSEngine.synthesize`), reconcile by adapting the **newer** file to keep its API, not
by rolling it back.

## 3. Then, in order

1. T3/T4 — `.gitignore` negation for `assets/**/*.wav`; confirm no secrets tracked.
2. T6 — `requirements.txt` + `ci.yml` install step.
3. T8 — `tests/factory/` (currently zero coverage outside `uploader/`).
4. T9/T10/T11 — plan generation + Natkhat series memory (this is what makes it autonomous).
5. T12–T16 — workflows, secrets, state persistence, verification.

## 4. Hard constraints — do not violate

- **Never** put a client ID, client secret, refresh token, OAuth code, or the contents of
  `D:\animated\ytcredetials.txt` into any tracked file, log, commit, or doc. Secrets go in
  GitHub Actions secrets or `~/.faceless-shorts/secrets/youtube/`.
- **Never** upload a public video, enable `allow_public_upload`, or set
  `FACTORY_ALLOW_SCHEDULE=1` without explicit human approval.
- **Never** bypass the channel-identity preflight/postcheck or the `--confirm-channel` gate.
- **Never** set Natkhat `madeForKids: false` — the channel is child-directed.
- **Never** delete or rewrite existing working code to "simplify". Extend it.
- **Never** report a test or workflow as passing without running it. If you cannot run
  it (no push rights, no secrets), say so explicitly.
- **Never** `git add -A` blindly: `build/` (large media) and secrets-adjacent files must
  stay out. Prefer explicit paths.
- Preserve git history; do not force-push `main`; make small, describable commits.

## 5. Known blockers (checked 2026-11-20)

| Blocker | Evidence |
| --- | --- |
| No push rights | `git push --dry-run` → `403 ... denied to Ayushjaiswal001`; `permissions.push: false`. Account `Ayushjaiswal001` ≠ repo owner `Ayushjaiswal0001`. |
| Hindi render broken | `ModuleNotFoundError: studio.pipeline.episode` |
| No Actions secrets | `gh api .../actions/secrets` → 403 (insufficient permission); workflows would fail at auth |
| Assets untracked | global `*.wav` in `.gitignore` |
| OAuth longevity unknown | Testing-mode refresh tokens expire after 7 days |

## 6. Commands cheat sheet

```powershell
# sanity
python -m compileall -q uploader factory studio
python -m pytest tests -q                      # 50 uploader tests
python -m factory.cli doctor
python -m factory.cli plans --channel all

# render / qc / publish (dry-run is the default)
python -m factory.cli render --channel nexus-node --plan-id nexus-small-models
python -m factory.cli qc     --channel nexus-node
python -m factory.cli publish --channel nexus-node --plan-id nexus-small-models
python -m factory.cli analytics --channel nexus-node --limit 20

# uploader (never with --execute unless approved)
python -m uploader.cli verify --channel all
python -m uploader.cli dry-run --channel natkhat-toons --video "<mp4>" --metadata examples/upload-request.example.json
python -m uploader.cli status --channel natkhat-toons
```

Real uploads additionally require `FACTORY_ALLOW_UPLOAD=1` (and
`FACTORY_ALLOW_SCHEDULE=1` for `publishAt`) plus `--execute --confirm-channel <slug>`.

Environment overrides that CI should use instead of editing code:
`FACTORY_BUILD_DIR`, `FACTORY_STATE_DIR`, `FACTORY_LOG_DIR`, `YT_SECRETS_ROOT`,
`YT_STATE_ROOT`.

## 7. What "done" looks like

A scheduled GitHub Actions run per channel, every day, that renders a video the system
planned itself, passes QC, uploads privately with a future `publishAt` in IST, verifies
the upload, records the state, and never repeats a topic or crosses channels — with the
previous run's state restored. See the completion criteria at the end of `TASKS.md`.
