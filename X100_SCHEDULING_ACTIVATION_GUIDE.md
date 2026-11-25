# X100 scheduling activation guide

The three daily production schedules exist, are correct, and are **disabled**. This is the procedure to
turn them on, and what to check before and after. Nothing here has been executed.

---

## 1. What is configured today

| workflow | file | cron (UTC) | IST release | state | jobs |
|---|---|---|---|---|---|
| `nexus-node daily` | `produce-nexus-node.yml` | `30 14 * * *` | 20:00 | `disabled_manually` | `short` (60 min), `long` (120 min) |
| `academic-biohacker daily` | `produce-academic-biohacker.yml` | `30 6 * * *` | 12:00 | `disabled_manually` | `short` (60 min), `long` (120 min) |
| `natkhat-toons daily` | `produce-natkhat-toons.yml` | `30 12 * * *` | 18:00 | `disabled_manually` | `short` (60 min), `long` (120 min) |
| `produce` | `produce.yml` | — (reusable) | — | active | one episode per call |
| `production (manual)` | `production.yml` | — (`workflow_dispatch`) | — | active | one job per channel |
| `ci`, `security` | — | push / PR / weekly | — | active | — |

The cron is the *release* time, not a lead time: the run starts at the channel's publication minute and
publishes at `publishAt` computed from `publish_time_ist` in the channel configuration. Verified with the
same function the workflow uses:

```
publish_at_utc("2026-11-26", "20:00")  -> 2026-11-26T14:30:00Z   # nexus-node
publish_at_utc("2026-11-26", "12:00")  -> 2026-11-26T06:30:00Z   # academic-biohacker
publish_at_utc("2026-11-26", "18:00")  -> 2026-11-26T12:30:00Z   # natkhat-toons
```

**Timezone correctness:** IST is UTC+5:30 with no daylight saving, so the offset is a constant. The three
crons equal exactly the three IST release times minus 5 h 30 min, and the channel configuration holds the
IST time as the single source of truth. There is no DST step to get wrong.

## 2. Scheduling dry run (already performed, safe to repeat)

```bash
FACTORY_BUILD_DIR=<build> FACTORY_STATE_DIR=<state> \
python -m factory.cli publish --channel nexus-node --schedule --json
```

Measured on 2026-11-25 against real artifacts — all three channels returned `status: dry_run_ok`,
`upload_performed: false`, `requested_privacy: private`, `scheduled: true`, `duplicate_check: clear`:

| channel | `publish_at` returned | matches configuration |
|---|---|---|
| Nexus Node | `2026-11-25T14:30:00Z` | yes (20:00 IST) |
| Academic Biohacker | `2026-11-25T06:30:00Z` | yes (12:00 IST) |
| Natkhat Toons | `2026-11-25T12:30:00Z` | yes (18:00 IST) |

`--schedule` only *computes* a release time. A real scheduled release additionally requires
`FACTORY_ALLOW_SCHEDULE=1` and `SCHEDULED_PUBLISHING_ENABLED=true`; both are absent from every workflow, so
a scheduled publish cannot happen by accident.

## 3. What a scheduled day actually does

For one channel, at its cron minute:

1. `short` job and `long` job start **independently** — no `needs:`, separate concurrency groups
   (`produce-<channel>-<format>`), separate state-cache keys, each holding only that channel's three
   secrets.
2. Each job resolves its own plan: the Short from `content/topics/<channel>.json`, the long-form from
   `content/longform/<channel>.json` via `plan new --format long` (file order, skipping anything already
   uploaded, re-selecting a rendered-but-unpublished episode).
3. Render → QC → rebuild manifest → publishing gate → package → (upload only if `upload=true`).
4. Artifacts upload with 14-day retention; pipeline state is saved even when the job fails.
5. On failure: `Notify on failure` runs `factory.cli notify`, which currently reports
   `delivered: false` because `FACTORY_NOTIFY_WEBHOOK` is not set — the failure is visible in the run
   conclusion and in the run summary, not in your inbox.
6. On success with `upload=true`: the upload step runs only if the gate passed and the credentials are
   ready, and the ledger refuses a second upload of the same sha256.

Capacity, measured on a 4-core development machine:

| | measured |
|---|---|
| one Short | ≈166 s render (≈8–9 min for the three-channel batch including TTS and QC) |
| one long-form | 3,090 s (51 min 30 s) for a 218.9 s episode |
| 3 Shorts + 3 long-form per day | ≈**163 min** of machine time |
| budgets | 60 min per Short job, 120 min per long-form job |

## 4. Pre-activation checklist

Do these in order; each is a fact you can see.

- [ ] `main` is the commit you believe it is: `git rev-parse main` = `b53a647`.
- [ ] CI is green on `main` (7 check-runs: `uploader (py3.11)`, `uploader (py3.12)`,
      `secret scan`, `gitleaks`, `factory`, `dependency audit`, `workflow permissions`).
- [ ] One manual run per channel has completed with `upload=false` (proves the workflow works on hosted
      hardware, where the long-form render has never run).
- [ ] The long-form render fits 120 min on a hosted runner. If the first hosted long-form job times out,
      raise `timeout_minutes` for that job — it is an input, not a constant.
- [ ] The upload switch decision is made explicitly: `upload=false` means "produce, do not publish", which
      is a perfectly good way to run the pipeline for a few days.
- [ ] You are content that a failed run is silent unless you look at Actions (no webhook today).
- [ ] For Natkhat: `made_for_kids` is forced true by the channel configuration, and category 1 is
      *Film & Animation*.

## 5. The one command per channel

```bash
# nexus-node, 20:00 IST
env -u GITHUB_TOKEN gh workflow enable "nexus-node daily" --repo Ayushjaiswal0001/youtube
# academic-biohacker, 12:00 IST
env -u GITHUB_TOKEN gh workflow enable "academic-biohacker daily" --repo Ayushjaiswal0001/youtube
# natkhat-toons, 18:00 IST
env -u GITHUB_TOKEN gh workflow enable "natkhat-toons daily" --repo Ayushjaiswal0001/youtube
```

Enable one channel first and watch it for a day. The three workflows are independent, so a bad cadence on
one channel does not touch the others.

To stop everything immediately:

```bash
for w in "nexus-node daily" "academic-biohacker daily" "natkhat-toons daily"; do
  env -u GITHUB_TOKEN gh workflow disable "$w" --repo Ayushjaiswal0001/youtube
done
```

There is also a per-channel pause file the workflow checks before it renders (`factory.controls.pause_state`
via `Emergency stop check`), which stops a channel without touching its schedule.

## 6. Post-activation verification (first 24 hours)

- [ ] Each workflow shows one run at its cron minute, and the run's jobs are `short` and `long`.
- [ ] Both jobs reached a conclusion independently — one failing does not mark the other failed.
- [ ] The run summary contains the per-episode table (plan, QC, gate, sha256, upload requested/performed).
- [ ] Artifacts are downloadable for 14 days and include `video.mp4`, `qc.json`, `manifest.json`,
      `captions.srt`, `thumbnail.jpg`, `framing.json`, `story.json`, `script.json`, `timeline.json`,
      `shot_plan.json`, `continuity.json`, `publish_gate.json`, `runs.jsonl`.
- [ ] `pipeline_state` cache was restored at the start and saved at the end, including on failure.
- [ ] The next day, the Short job picks a **different** plan (no repeat), and the long-form job either
      picks the next authored episode or stops loudly with "author the next long-form episode".
- [ ] If `upload=true`: exactly one new `uploaded` line per channel per day in the ledger, and nothing
      published publicly.

## 7. Known ways this schedule can fail, and what each looks like

| symptom | cause | response |
|---|---|---|
| long job times out at 120 min | hosted runner slower than measured | raise `timeout_minutes` for the `long` job |
| long job fails with "author the next long-form episode" | the authored bank has one episode per channel | author the next plan; the Short job is unaffected |
| upstream run fails at `Research` | network/TTS dependency | re-run; the state cache keeps completed scenes |
| upload step skipped, `creds.ready != 1` | missing/expired secret | rotate the secret; nothing was uploaded |
| `DuplicateUploadError` | same plan re-published | expected; the ledger is doing its job |
| two runs of the same channel at once | concurrency group | the second queues, it does not interleave |
| Natkhat upload rejected for made-for-kids | configuration drift | check `channels/natkhat-toons.json` `defaults.made_for_kids` is `true` |

## 8. What has not been verified

- No workflow has ever run on a hosted runner in this mission; all measurements are local.
- No cron has ever fired.
- No upload or scheduled release has ever happened.
- Notification delivery is a no-op until `FACTORY_NOTIFY_WEBHOOK` is set.
