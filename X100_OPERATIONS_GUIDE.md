# X100 operations guide

How to run, check, recover and publish this factory without reading the source. Every command below was
executed in this session unless marked otherwise.

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
3. Owner-only: `--execute --confirm-channel <slug>` with `UPLOAD_ENABLED=true`.

Guards that hold regardless of flags:

- private by default; `--allow-public` is required for anything else;
- `made_for_kids` is forced true for `natkhat-toons`;
- a channel's token is refused unless its channel ID matches the channel config;
- a duplicate upload is refused from the local ledger;
- `--schedule` needs `SCHEDULED_PUBLISHING_ENABLED=true`.

## 7. Schedules and cloud runs

| workflow | trigger | state |
|---|---|---|
| `ci.yml` | push, PR | active |
| `security.yml` | push, PR, weekly | active |
| `produce.yml` | called by the three daily workflows | active |
| `production (manual)` | `workflow_dispatch` | active |
| `academic-biohacker daily` | cron `30 6 * * *` | **disabled_manually** |
| `natkhat-toons daily` | cron `30 12 * * *` | **disabled_manually** |
| `nexus-node daily` | cron `30 14 * * *` | **disabled_manually** |

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
