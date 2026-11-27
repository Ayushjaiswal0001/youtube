# X100 operations guide

How to run, check, recover and publish this factory without reading the source. Commands below are
runbook examples; read their inline safety notes before use.

---

## 1. Environment

```bash
cd <repo>
export PYTHONIOENCODING=utf-8        # mandatory on Windows: plates contain ₹, Devanagari, arrows
export PYTHONPATH="$PWD"
python -m pip install -r requirements.txt
```

Absolute paths break FFmpeg on some platforms; keep `FACTORY_BUILD_DIR` and `FACTORY_ASSET_CACHE`
relative or use a Windows-style path with a drive letter, never `C:/…` inside an FFmpeg filter.

| variable | default | purpose |
|---|---|---|
| `FACTORY_BUILD_DIR` | `build/` | episode artifacts (video, captions, manifests) |
| `FACTORY_ASSET_CACHE` | `x100_asset_cache/` | generated plates and charts |
| `FACTORY_STATE_DIR` | `pipeline_state/` | job journals, locks, run history |
| `FACTORY_LOG_DIR` | `build/logs/` | structured logs |
| `FACTORY_ASSET_LIBRARY` | `assets/library/` | optional licensed stills |
| `FACTORY_NOTIFY_WEBHOOK` | unset | failure notification (a no-op when unset) |

## 2. Daily commands

```bash
# what exists
python -m factory.cli plans

# one episode, forced (re-render even if a cached build exists)
python -m factory.cli render --channel nexus-node --plan-id nexus-small-models --force

# one episode, idempotent (skips in ~5 s when the build is current)
python -m factory.cli render --channel nexus-node --plan-id nexus-small-models

# the same plan in 16:9 as well
python -m factory.cli render --channel nexus-node --plan-id nexus-small-models --formats shorts,long

# the next authored long-form episode for a channel (selection only, writes nothing)
python -m factory.cli plan new --channel academic-biohacker --format long --no-write

# render the long-form episode that selection returns
python -m factory.cli resume --channel academic-biohacker   --plan-id long-academic-study-protocol --format long

# storage report; deletion needs --apply and only ever touches released, valid, idle, old builds
python -m factory.cli cleanup --channel all
python -m factory.cli cleanup --channel all --apply --keep-days 14

# QC only, on an existing build
python -m factory.cli qc --channel nexus-node --plan-id nexus-small-models

# the publishing gate, no upload
python -m factory.cli gate --channel nexus-node --plan-id nexus-small-models

# what the uploader would send, without sending it
python -m factory.cli publish --channel nexus-node --plan-id nexus-small-models

# job state and history
python -m factory.cli status --channel nexus-node
python -m factory.cli ops
```

`publish` without `--execute` is the dry run and is the only form that should be used until the owner
authorises uploads. It prints `status: dry_run_ok`, `upload_performed: false`, the metadata payload, the
identity proof and the gate result.

## 3. Reading an episode's artifacts

Every episode directory contains:

| file | what it is |
|---|---|
| `video.mp4` | the finished video |
| `script.json` | the lines with timings |
| `scenes.json` | the scene plan, each scene's resolution, entities and plate fingerprint |
| `captions.srt` | captions from the same timeline as the audio |
| `qc.json` | 25 technical checks with the measured detail for each |
| `creative.json` | 21 creative checks (composition runs, distinct plates, figures, provenance) |
| `render.json` | duration, size, streams, renderer |
| `manifest.json` | every artifact with its sha256 |
| `thumbnail.jpg` | the thumbnail that would be uploaded |

`python tools/report_episode_qc.py` regenerates `X100_EPISODE_QC_REPORTS.md` from these files, so the
report can never drift from the artifacts.

## 4. Reading a gate failure

```
gate: False 23/24  blockers: ['creative_quality']
 FAIL creative_quality error :: 6 scenes, 6 distinct visuals, compositions=panels,statement;
      failed: ['no_repeated_composition_runs']
```

The blocker names the check and the check names the measurement. Do not lower the threshold: a repeated
composition is a real visual defect, and the fix belongs in the composition rules (this is exactly how
defects 3, 4 and 5 in the audit were found).

## 5. Recovery

The state machine journals every transition to
`$FACTORY_STATE_DIR/jobs/<channel>_<plan>_<YYYYMMDD>/journal.jsonl`, and holds a lock per plan.

**If a render dies:**

```bash
python -m factory.cli resume --channel nexus-node --plan-id <plan>
```

`resume` reclaims a stale lock (the lock records its pid and host) and continues to
`READY_TO_PUBLISH`. Verified by killing a render 22 s in and resuming it.

**If a build directory is corrupt:** re-render with `--force`. Nothing in `build/` is a source of truth;
`content/`, `channels/` and `pipeline_state/` are.

**If a lock is held by a live process:** do not delete it; find the pid in
`$FACTORY_STATE_DIR/locks/<channel>_<plan>.lock` and stop that process first.

## 6. Publishing

The safest order, and the only order that should be used:

1. `python -m factory.cli publish --channel <slug> --plan-id <plan>` — dry run, read the payload.
2. `python -m factory.cli gate --channel <slug> --plan-id <plan>` — confirm `24/24` (en) or `23/23` (hi).
3. Owner-only: `--execute --confirm-channel <slug>` with `FACTORY_ALLOW_UPLOAD=1`; scheduled releases also require `FACTORY_ALLOW_SCHEDULE=1`.

Guards that hold regardless of flags:

- private by default; `--allow-public` is required for anything else;
- `made_for_kids` is forced true for `natkhat-toons`;
- a channel's token is refused unless its channel ID matches the channel config;
- a duplicate upload is refused from the local ledger;
- `--schedule` needs `FACTORY_ALLOW_SCHEDULE=1`; the reusable GitHub workflow independently keeps `UPLOAD_ENABLED` and `SCHEDULED_PUBLISHING_ENABLED` as wrapper gates.

## 7. Schedules and cloud runs

| workflow | trigger | jobs | state |
|---|---|---|---|
| `ci.yml` | push, PR | `uploader`, `factory` | active |
| `security.yml` | push, PR, weekly | `secrets`, `gitleaks`, `dependencies`, `workflow-audit` | active |
| `produce.yml` | called by the others | `produce` (one episode) | active |
| `production (manual)` | `workflow_dispatch` | one job per channel | active |
| `academic-biohacker daily` | cron `29 4 * * *` (09:59 IST start, 12:00 release) | `short` (60 min), `long` (120 min) | **active** |
| `natkhat-toons daily` | cron `29 10 * * *` (15:59 IST start, 18:00 release) | `short` (60 min), `long` (120 min) | **active** |
| `nexus-node daily` | cron `29 12 * * *` (17:59 IST start, 20:00 release) | `short` (60 min), `long` (120 min) | **active** |

GitHub Actions currently reports all three daily workflows as active (enabled). Each channel's publishing
policy and production gate still determine whether a scheduled run may upload.

### Verified operational snapshot — 2026-11-28 00:39 IST

PR #31 is merged as `3fa3c981a1dbfc0248730a9a558b0d5da212948b`. Main CI run `46033672111` and security run
`46033672255` passed. A read-only YouTube check verified all three channel identities and fully scanned
their uploads playlists; no future `publishAt` schedule was present. Existing video IDs and current API
visibility are recorded in `X100_FINAL_PROJECT_COMPLETION_REPORT.md`, section O.

No post-merge scheduled event has run yet as of 00:39 IST. The next expected triggers are Saturday,
November 28: Academic 09:59 IST, Natkhat 15:59 IST, and Nexus 17:59 IST. The latest earlier scheduled
event was Academic run `46012727812` on pre-merge main SHA `2ea73be1568a4cbaa188fa6abce06607010ecb7f`;
it started at 19:35 IST. If a new schedule is delayed, inspect its event, branch, workflow, job logs, and
publishing decision before taking action. Do not manually dispatch as a replacement.

The scheduled wrapper sent the correct inputs (`upload=true`, `release=auto`). Short and long policy
checks were late by 27,390s and 28,340s, beyond the configured 90-minute grace, and returned
`release_window_missed` with `ready=false`. The reusable workflow only exports channel credentials when
policy readiness is true, so credential export was skipped before reading a credential value; identity
verification and upload were then skipped. This is a late GitHub scheduled event and correct fail-closed
behavior, not missing schedule inputs or demonstrated credential failure. All nine expected Actions
secret names exist; values were not read. Local OAuth identity checks matched all three channels. No gate
or late-run policy was weakened.

The repository is already public. The active GitHub account is the write-enabled owner `Ayushjaiswal0001`
and it merged PR #32 normally. No credential value, OAuth secret, production gate, or repository permission was
changed during this continuation.

### Verified operational snapshot — 2026-11-28 01:07 IST

PR #32 merged to `main` at 01:01:19 IST as `b752bf74a897582e207ca5332bc47effd85a53a6`. Post-merge
main CI run `46057283954` and security run `46057283946` passed. GitHub still reports the three daily
workflows as active: Academic `425309827` (`29 4 * * *`, 09:59 IST), Natkhat `425309829`
(`29 10 * * *`, 15:59 IST), and Nexus `425309830` (`29 12 * * *`, 17:59 IST). Intended release times
remain 12:00, 18:00, and 20:00 IST.

No post-merge scheduled event had appeared in the checked run history; these Nov 28 triggers are still
ahead. The latest read-only YouTube playlist scan was at 00:22 IST and found no future `publishAt` values.
No production workflow was dispatched, no video was uploaded or scheduled, and no channel publishing
setting or gate was changed. PR #32 changed creative content/rendering/tests and handover documentation;
it did not change workflow YAML, channel publishing settings, secrets, or release policy.

PR #32's fresh local Academic render (`academic-brain-wash`, 38.233s) and Nexus render
(`nexus-data-wall`, 45.433s) passed factory QC as 1080x1920 H.264/AAC Shorts. Contact sheets show varied
Pop Info character-guide/callout frames and an Evidence Board with pinned cards, red-string connections,
a scanning magnifier, and varied framing. Audio QC reported -14.5 LUFS/-2.46 dBTP with 0.013s AV length
delta for Academic, and -14.2 LUFS/-2.40 dBTP with 0.003s delta for Nexus. The local Natkhat
`natkhat-haveli-e4` render is 31.667s, passed factory QC, and its one-second timeline sheet shows the
brass-key action, expressive poses, and rooftop-night cut. Whisper base recovered the key Hindi story
points from its narration and subtitles. These are local-only previews; no upload or schedule was made.
Automated transcription/measurements do not replace a human listening pass, and characters use simple 2D
rigs.

Each channel's nightly workflow runs **two independent jobs**: a Short (format `shorts`, 60-minute budget)
and a long-form episode (format `long`, 120-minute budget). They share nothing but the channel: separate
concurrency groups (`produce-<channel>-<format>`), separate state-cache keys, no `needs:` between them, so
a slow or failing long-form render never blocks the Short. Measured on the development machine:
Short ≈166 s; long-form 3,090 s (51 min 30 s) for `long-academic-study-protocol` and 3,008 s
(50 min 8 s) for `long-nexus-power-grid`. That is why the two budgets differ, and the 120-minute
budget is 2.3× the measured render.

A long-form run picks its episode from `content/longform/<channel>.json` through
`plan new --format long`: file order, skipping anything already uploaded, re-selecting a rendered but
unpublished episode so a failed upload resumes the validated video instead of rendering another.

The manual workflow has one job per channel, so each job receives only that channel's three secrets. It
is not a substitute for verifying scheduled automation. A manual run that may upload is owner-authorized
only; never use one to replace a delayed schedule:

```bash
env -u GITHUB_TOKEN gh workflow run "production (manual)"   --repo Ayushjaiswal0001/youtube   -f channel=natkhat-toons -f format=long -f mode=render+validate -f upload=true
```

To run one channel in the cloud without waiting for the cron:

```bash
env -u GITHUB_TOKEN gh workflow run "production (manual)" \
  --repo Ayushjaiswal0001/youtube \
  -f channel=nexus-node -f mode=render+validate -f upload=false
```

Never run `gh` with the ambient `GITHUB_TOKEN` on this machine: it is bound to a different account.
Always `env -u GITHUB_TOKEN gh …`.

## 8. Troubleshooting

| symptom | cause | action |
|---|---|---|
| `plan '<x>' not found` | the id is not in this channel's `content/batch_*.json` or topic bank | `python -m factory.cli plans` |
| `UnicodeDecodeError` on `₹` in `tools/secret_scan.py --staged` | known Windows bug in staged-diff reading | use the tree scan; CI's gitleaks covers the staged case |
| `creative_quality` blocked | a composition repeat or a figure that is not stated | read the check detail; never edit the threshold |
| `audio_loudness` fails | encoded true peak above −1.0 dBTP | the peak guard now retries automatically; if it still fails, inspect `audio/narration.*` |
| a render sits in `GENERATING` for a long time | long-form card render is slow (≈4.4 s per output second) | check `video_work/` growth before assuming a hang |
| stale lock after a crash | process killed | `resume` reclaims it |

## 9. What not to do

- Do not push to `main`, force-push, or rewrite history.
- Do not enable the daily crons or scheduled publishing without the owner.
- Do not print, copy or rotate the `YT_*` secrets.
- Do not raise a QC threshold to make an episode pass. Fix the episode or fix the rule.
- Do not run `git add .`; stage explicit paths so `pipeline_state/` never sneaks in.
- Do not trust a chip in a log: read `qc.json`, `creative.json` and the frames.
