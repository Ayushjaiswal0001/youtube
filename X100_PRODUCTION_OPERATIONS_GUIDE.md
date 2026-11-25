# X100 production operations guide

The system as it exists on `main` (`b53a647`), in the language of running it: what it produces, how to
start it, how to stop it, what it costs, and what to check when it misbehaves. Numbers here are measured on
this machine unless the row says otherwise.

---

## 1. What this system is

Three independent YouTube channels, one Python factory, ₹0/month, no paid API and no GPU.

| channel | niche | language | look | release (IST) | made for kids |
|---|---|---|---|---|---|
| **Nexus Node** (`UCx9O8VivWkiEylDjs5_Zzag`, `@nexusnode012`) | AI, emerging tech, systems | en | dark navy `nexus` palette, diagram and data plates | 20:00 | no |
| **Academic Biohacker** (`UCr8jSmLa_o2BwNh8HuyZHAQ`, `@academicbiohacker`) | evidence-first health | en | paper palette, pictogram plates | 12:00 | no |
| **Natkhat Toons** (`UC4OCY0qDwQqFnSCZw12sKxA`, `@NatkhatToons-n5`) | Hindi kids' animation | hi | `natkhat` palette, rigged monkey and mouse | 18:00 | **yes, forced** |

Two output formats:

- **Short** — 1080×1920, 32–39 s, 30 fps, h264 + aac, burned-in caption band from `captions.srt`.
- **Long-form** — 1920×1080, 3.6 min so far, 30 fps, chapter cards plus the same narration/QC/gate chain.
  Authored long-form episodes exist for Nexus and Academic; Natkhat's long-form entry is a stage plan with
  no beats, so Natkhat long-form is **not configured**.

## 2. Daily commands

```bash
# what can be made right now, per channel and format
python -m factory.cli plans

# the next long-form episode for a channel (selection only, writes nothing)
python -m factory.cli plan new --channel academic-biohacker --format long --no-write

# produce one Short / one long-form
python -m factory.cli render --channel nexus-node --plan-id nexus-small-models
python -m factory.cli resume --channel academic-biohacker --plan-id long-academic-study-protocol --format long

# three channels at once
python -m factory.cli batch --channel all --per-channel 1

# verify what was produced, without rendering
python -m factory.cli validate --channel all
python -m factory.cli gate     --channel all
python -m factory.cli ops      --channel all

# publishing policy: what each channel may do automatically, and the release it would use right now
python -m factory.cli publishing --channel all
python -m factory.cli publishing --channel nexus-node --json

# publish (dry run by default; --execute needs FACTORY_ALLOW_UPLOAD=1 and a matching --confirm-channel)
python -m factory.cli publish --channel nexus-node --plan-id nexus-small-models
# a scheduled release additionally needs FACTORY_ALLOW_SCHEDULE=1 and resolves the time itself:
FACTORY_ALLOW_SCHEDULE=1 python -m factory.cli publish --channel nexus-node --schedule --execute \
    --confirm-channel nexus-node

# storage: report, then optionally delete only released, valid, idle builds
python -m factory.cli cleanup --channel all
python -m factory.cli cleanup --channel all --apply --keep-days 14

# stop everything, or one channel
python -m factory.cli pause --channel all
python -m factory.cli pause --channel nexus-node --clear
```

Every verb accepts `--json` and writes its machine-readable output where the workflow can archive it.

## 2.1 Publishing, and the three switches that are not switches

`produce.yml` sets `UPLOAD_ENABLED=false`, `SCHEDULED_PUBLISHING_ENABLED=false` and
`PUBLICATION_APPROVAL_REQUIRED=true`. Those three are **documentation**: no Python module reads them. The two
variables that are actually enforced are `FACTORY_ALLOW_UPLOAD` and `FACTORY_ALLOW_SCHEDULE`, and the third
enforcement point is the publishing gate. Read them together, but do not believe a switch that nothing reads —
this file says so explicitly rather than implying a guarantee.

What decides whether a video can be published automatically:

| decision | input | default |
| --- | --- | --- |
| may this channel upload without an operator? | `channels/<slug>.json` → `publishing.mode` (`manual`/`scheduled`) + `publishing.scheduled_upload` | `manual` |
| may this particular run upload? | `produce.yml` `upload` input, derived from the event by the daily workflows | `false` |
| may this run set a release time? | `produce.yml` `release` input (`auto`) **and** the channel policy, then `FACTORY_ALLOW_SCHEDULE=1` inside that step only | no |
| where does the release time come from? | `publish_time_ist` in the channel JSON, resolved by `factory/publishing.py` | channel's own |

Turning one channel off, without touching another:

```bash
python - <<'PY'
import json, pathlib
p = pathlib.Path("channels/natkhat-toons.json")
d = json.loads(p.read_text(encoding="utf-8"))
d["publishing"]["mode"] = "manual"          # or set scheduled_upload = false
p.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
PY
python -m factory.cli publishing --channel natkhat-toons     # must print mode=manual
```

Least destructive interpretation of "pause production": `factory.cli pause --channel <slug>` stops rendering
and publishing inside the code and leaves the schedule in place (so the next run is a fast no-op), while
`gh workflow disable "<slug> daily"` stops the trigger. Disabling the workflow is required if the render itself
must not run; pausing the channel is required if the release must not happen.

### Late runs

`late_run_policy` in the channel JSON decides what a run that finishes after its release time does:

- `shift` (default) — publish today, `minimum_lead_minutes` (15) from now, provided it is within
  `late_grace_minutes` (90);
- `skip` — refuse, leave the episode private, fail the run so it is seen.

Beyond the grace window both policies refuse: a seven-hour-late "today's video" is not today's video. Raise
the grace per channel if GitHub's dispatch delay turns out to be routinely longer than the window.

## 3. Where things live

| path | contents |
|---|---|
| `build/<channel>/<plan>/` | `video.mp4`, `thumbnail.jpg`, `captions.srt`, `render.json`, `qc.json`, `framing.json`, `creative.json`, `scenes.json`, `manifest.json`, `publish_gate.json`, `story.json`, `script.json`, `timeline.json`, `shot_plan.json`, `publish_plan.json` |
| `pipeline_state/jobs/<channel>_<plan>_<date>/job.json` | job state machine: `PREFLIGHT → GENERATING → PACKAGING → READY_TO_PUBLISH → UPLOADED` |
| `pipeline_state/*/runs.jsonl` | append-only run log, one JSON line per attempt |
| `.state/youtube/<channel>/ledger.jsonl` | one line per upload attempt: sha256, video id, status |
| `.secrets/youtube/<channel>.json` | OAuth material, written by `uploader.cli consent`, never committed |
| `logs/` | structured logs when `FACTORY_LOG_DIR` is set |

**Single place to look at production results:** `python -m factory.cli ops --channel all` — it prints the
job counts and one line per artifact with QC, gate and upload state. In Actions the same information is in
the run summary (the `Operational summary` step) and in the uploaded artifacts (14-day retention).

## 3.1 Release resolution, in one table

`python -m factory.cli publishing --channel <slug>` prints `next_release` and its reason; the run summary
prints the same values. The reasons are the whole contract:

| reason | meaning | published? |
| --- | --- | --- |
| `on_time` | the channel's release instant on the run's IST date | yes, at that instant |
| `too_close_to_release` | under 15 minutes away, so pushed out | yes, 15 minutes from now |
| `late_run_shifted (late by Ns …)` | the instant passed, inside the grace window | yes, 15 minutes from now |
| `release_window_missed (…)` | past the grace window, or policy `skip` | **no**, run fails |
| `release_already_scheduled (…)` | a release at or after this instant already exists for the channel | **no**, run fails |
| `already_released_this_plan_today (…)` | this plan already has a release today | **no**, run fails |
| `refused_past_release` | defensive; would have been a past instant | **no**, run fails |

Two of those deserve a sentence. `release_already_scheduled` protects a *newer* release from being overwritten
by a delayed older job. `already_released_this_plan_today` is per **plan**, not per day, because a channel
publishes a Short and a long-form episode on the same day: two plans may both release, one plan may not.

## 4. State machine

```
PREFLIGHT → GENERATING → PACKAGING → READY_TO_PUBLISH → UPLOADED
                 ↑                ↑
             resume           manifest rebuild
```

- `resume` reads the job file and continues from the last completed stage; completed scenes inside a
  render are reused, so an interrupted 50-minute long-form does not restart from zero.
- A stale lock (`pipeline_state/locks/<job>.lock` from a killed process) is reclaimed on the next run.
- `--force` re-renders from scratch; without it an existing `video.mp4` is reused and reported as
  `skipped_render: true`.
- The state cache in Actions is keyed `state-<channel>-<format>-<run_id>` and is saved with `if: always()`,
  so a failure does not lose the completed work.

Measured this session: killed 25 s into a Short, then `resume` → `READY_TO_PUBLISH`, 181 s, QC 25/25,
stale lock reclaimed.

## 5. Quality gates

Two gates, both fail-closed.

**QC (25 checks)** on every artifact: resolution, frame rate, duration, audio stream, loudness, true peak,
A/V sync, frozen frames, black frames, caption presence and language, thumbnail, manifest hashes, title
length, placeholder text, framing (a required subject outside the picture), caption collision,
shot continuity, pickup contact, and the rest.

**Publishing gate (23–25 checks)** re-measures what matters to a release: the artifact hash, the geometry a
channel accepts (both 1080p profiles are valid; a cropped or upscaled file is refused), the title and
description against the channel rules, `madeForKids` for Natkhat, the thumbnail, duplicate upload, and the
creative verdict when a scene plan exists.

Findings are classified: an **error** blocks, a **warning** is reported and does not block. Warnings
currently emitted in normal production:

| warning | meaning |
|---|---|
| `framing_margin` | a required subject sat inside the safe margin but inside the picture |
| `framing_off_shot_characters` | a close-up deliberately excluded the listener |
| `title_matches_narration` | the on-screen title shares no content word with the narration |
| `dataviz_delivered` | no chart was drawn because no sentence states a number |

## 6. Uploads

Uploads are off by default at three independent layers:

1. every workflow sets `UPLOAD_ENABLED=false`, `SCHEDULED_PUBLISHING_ENABLED=false`,
   `PUBLICATION_APPROVAL_REQUIRED=true`;
2. the upload step runs only if `inputs.upload && creds.ready && gate.ok`;
3. `factory.cli publish` needs `FACTORY_ALLOW_UPLOAD=1` and `--execute --confirm-channel <slug>`; the
   uploader refuses a privacy status other than private unless `--allow-public` is passed *and* the channel
   configuration permits it (`allow_public_upload: false` on all three).

Before any upload, the token is exchanged, its channel identity is compared with `expected_channel_id`, and
a mismatch aborts with `WrongChannelError` before a byte is sent. After upload the response's channel id is
verified again. A lost response marks the ledger `unknown`, which blocks a blind retry.

See `X100_PRIVATE_UPLOAD_CHECKLIST.md` for the owner procedure.

## 7. Schedules

Three daily workflows, each with two independent jobs:

| channel workflow | cron (UTC) | IST | jobs |
|---|---|---|---|
| `nexus-node daily` | `30 14 * * *` | 20:00 | `short` 60 min, `long` 120 min |
| `academic-biohacker daily` | `30 6 * * *` | 12:00 | `short` 60 min, `long` 120 min |
| `natkhat-toons daily` | `30 12 * * *` | 18:00 | `short` 60 min, `long` 120 min |

All three are currently `disabled_manually`. Activation procedure: `X100_SCHEDULING_ACTIVATION_GUIDE.md`.

## 8. Capacity, measured

| item | measured |
|---|---|
| one Short | 32–39 s of video, ≈166 s of wall clock on a warm cache |
| three Shorts in one batch | 526 s (8 min 46 s) |
| one long-form | 218.9 s of video, 3,090 s (51 min 30 s) of wall clock |
| 3 Shorts + 3 long-form | ≈163 min of machine time per day |
| budgets | 60 min per Short job, 120 min per long-form job (2.3× the measured long-form) |
| disk per Short | ≈11 MB of build artifacts |
| disk per long-form | ≈50 MB of build artifacts |
| artifact retention | 14 days in Actions |

## 9. Cost

₹0/month. Public repository, standard GitHub-hosted runners, local rendering with FFmpeg + Cairo, generated
plates, procedural music, edge-tts and gTTS for voices. No paid API, no GPU, no storage service, no
database.

## 10. What to do when something breaks

| symptom | first thing to check |
|---|---|
| job stuck in `GENERATING` | `pipeline_state/jobs/*/job.json`; then `resume` |
| "stale lock" | a killed run; `resume` reclaims it, or delete the lock file |
| QC error | `build/<channel>/<plan>/qc.json` — the failing check names its measurement |
| gate blocker | `publish_gate.json` — blockers list, then `framing.json` or `creative.json` |
| "no plan left" | author the next plan in `content/topics/<channel>.json` or `content/longform/<channel>.json` |
| long-form job times out | raise `timeout_minutes` for the `long` job (it is a workflow input) |
| upload skipped | `steps.creds.outputs.ready` — a missing or expired secret, or the consent screen in Testing |
| duplicate upload error | expected: that sha256 is already in the ledger |
| disk filling | `cleanup --channel all` to see what is deletable, then `--apply` |
| two runs interleaved | should be impossible: the concurrency group is per channel and format |

## 11. Known limitations

1. Diagram plates animate by camera motion only; the content of a plate does not animate.
2. Natkhat wide shots are near-static; one close-up per episode.
3. Charts appear only when a sentence states a number, and the topic banks state none.
4. Creative QC covers the shorts engine only; Natkhat and the 16:9 renderer carry the technical checks.
5. Captions are generated but not attached to an upload.
6. Long-form banks hold one authored episode per channel.
7. The upload path has never run against YouTube.
8. No failure notification until `FACTORY_NOTIFY_WEBHOOK` is set.
