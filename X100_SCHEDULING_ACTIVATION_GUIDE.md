# X100 scheduling activation guide

How a video becomes public without anyone clicking "publish", what has been proven, and the exact order in
which the three channels may be switched on.

This file replaces the earlier version of itself, which described a mechanism that did not exist: the daily
workflows could not upload at all, and an upload carried no release time. Sections 1–3 describe what is now
in the repository, section 4 is the activation order, section 5 is what a day looks like afterwards, and
section 6 lists what is still unproven and why.

Owner decision implemented here: **Option A, fully automatic scheduled publishing**, `Asia/Kolkata` release
times, ₹0/month. Three channels: Nexus Node, Academic Biohacker, Natkhat Toons.

---

## 1. The three authorizations, separated

Before this change there was one switch (`upload`) and it was unreachable. Now three decisions are made in
three places, and each can refuse on its own:

| authorization | where it is decided | what stops the publication |
| --- | --- | --- |
| **render** | `factory.controls` | a paused channel produces nothing (`pause`) |
| **upload** | `produce.yml` `upload` input + `FACTORY_ALLOW_UPLOAD=1` in the CLI + a passing publishing gate | a render-only run, a missing credential, a blocked gate |
| **schedule** | `channels/<slug>.json` → `publishing` → read by the `Publishing policy` step → `--schedule` + `FACTORY_ALLOW_SCHEDULE=1` | a channel whose policy is `manual` |

A `schedule` event cannot supply `workflow_dispatch` inputs, which is why the old design could never upload.
The daily workflows now derive the request from the event:

```yaml
upload: ${{ inputs.upload || github.event_name == 'schedule' }}
release: ${{ github.event_name == 'schedule' && 'auto' || '' }}
```

and `produce.yml` then asks the channel whether it agrees:

```yaml
- name: Publishing policy (per channel)
  id: policy
  run: |
    python -m factory.cli publishing --channel "$CHANNEL" --json > publishing.json
    python tools/publishing_outputs.py publishing.json >> "$GITHUB_OUTPUT"
```

The credential export, the identity verification and the upload step all require `steps.policy.outputs.ready
== '1'`. A channel that has not opted in renders and stops, even when a workflow asks for an upload.

The channel policy shipped today:

```json
"publishing": {
  "mode": "scheduled",
  "scheduled_upload": true,
  "late_run_policy": "shift",
  "late_grace_minutes": 90,
  "minimum_lead_minutes": 15
}
```

Parsing fails closed: an unknown `mode` means `manual`, an unknown `late_run_policy` means `skip`, and
`scheduled` without a `publish_time_ist` falls back to `manual` with a warning the CLI prints.

Check it from anywhere:

```bash
python -m factory.cli publishing --channel all
python -m factory.cli publishing --channel nexus-node --json
```

Measured now (2026-11-25, 19:0x IST):

```
academic-biohacker   scheduled upload_on_schedule=True release=12:00 next=None (release_window_missed (late by 25287s, policy shift, grace 90min))
natkhat-toons        scheduled upload_on_schedule=True release=18:00 next=2026-11-25T13:46:27Z (late_run_shifted (late by 3687s, grace 90min))
nexus-node           scheduled upload_on_schedule=True release=20:00 next=2026-11-25T14:30:00Z (on_time)
```

The academic line is the late-run policy doing its job: a run at 19:00 for a 12:00 release is seven hours
late, and seven hours late is not "today's video", so it refuses to schedule rather than publishing a stale
episode at 19:15.

---

## 2. Release-time resolution (`factory/publishing.py`)

The release belongs to the **production run's IST date**, not to the moment the upload happens.

| situation | decision | reason string |
| --- | --- | --- |
| release is at least `minimum_lead_minutes` (15) away | schedule it | `on_time` |
| release is in the future but closer than the lead | schedule `now + 15 min` | `too_close_to_release` |
| release has passed, within `late_grace_minutes` (90), policy `shift` | schedule `now + 15 min` (today) | `late_run_shifted (late by Ns …)` |
| release has passed beyond the grace window | **refuse**, no upload | `release_window_missed (late by Ns …)` |
| policy `skip` and the release has passed | **refuse**, no upload | `release_window_missed` |
| the channel already has a release at or after this instant | **refuse** | `release_already_scheduled` |
| this plan already has a release today (any state but failed) | **refuse** | `already_released_this_plan_today` |
| anything that would produce a past instant | **refuse** | `refused_past_release` |

The defect this removes: the old `_next_ist_date` returned **tomorrow** as soon as the release time had
passed, so a cron at 20:00 IST that reached the upload step at 20:00:04 scheduled the episode 24 hours late.
There is now a test that sweeps every 7th minute of a day and asserts that no instant can produce a past
release, and another that runs the CLI with a release time five minutes in the past and asserts the release
lands within twenty minutes and on the same IST date.

A refusal is a **failed run**, not a silent skip: `publish` exits 2, the workflow step fails, the failure
notification fires and the job summary says which window was missed and by how long.

### The one-way door

The uploaded video is `private` with a `publishAt`. YouTube releases it at that instant. The OAuth grant the
factory holds — `youtube.upload` and `youtube.readonly` — can **insert** a video with a `publishAt`, but it
**cannot change or remove one afterwards**: changing a video's status needs `https://www.googleapis.com/auth/youtube`
(force-ssl), and the measured result of trying is

```
ApiError: HTTP 403 insufficientPermissions: Request had insufficient authentication scopes.
```

So before the first scheduled release, the owner must either accept that the release is one-way, or grant the
broader scope and re-consent (see §6.3). The same scope is what captions need, so one re-consent fixes both.

---

## 3. What has been proven, and where

| claim | how it was measured | result |
| --- | --- | --- |
| hosted hardware renders both formats | `production (manual)` on `main @ b496b07`, `upload=false` | Short: run 45623621859 success, 7.96 MB artifact, `nexus-open-weights` 35.2 s; long: run 45625058307 success, 45.59 MB artifact, `long-nexus-power-grid` 214.067 s @ 1920×1080, 18 min wall clock |
| a render-only hosted run cannot upload | all three upload steps in both runs | `skipped` ×3 in both runs |
| the publish path works against the live API | three private uploads, one per channel | video ids `UuQKJ3jspKE`, `O2YiFi0f_Ts`, `derJO8hBnjo`; all `uploadStatus: processed`, `processing: succeeded` |
| channel identity is policed per token | identity block in each upload result | `verified: true`, token channel id equals the expected id for each of the three |
| a scheduled run would be allowed to upload | `factory.cli publishing` per channel | `ready: true` for all three, `next_release` computed for Nexus (`2026-11-25T14:30:00Z`) |
| the release resolver never emits a past instant | `tests/factory/test_publishing_policy.py` (33 tests) | 33 passed |
| the workflow gates on the policy | `tests/factory/test_production_workflow_shape.py`, `test_publishing_policy.py` | 68 passed |
| the payload YouTube receives for a scheduled kids upload | `tests/factory/test_publish_gates.py` | `privacyStatus=private`, `publishAt` set, `selfDeclaredMadeForKids=true` |

Still not executed end-to-end: **an insert whose `publishAt` is honoured by YouTube**. Everything up to the
API call is tested; the API call itself is the activation event, because it cannot be undone with the current
scope.

---

## 4. Activation order (strict)

Do not skip a step, and do not enable two channels at once.

**0. Merge the pull request.** Scheduled production runs whatever is on the default branch. Enabling a cron
before the merge means running the old workflow, which cannot upload at all.

**1. Nexus Node.** Its release time is 20:00 IST and it is the channel with the most headroom.

```bash
gh workflow enable "nexus-node daily"
gh workflow run "nexus-node daily" --ref main -f episode=both -f upload=false   # optional dry run
```

Then watch. Two things must appear in the run: the `Publishing policy (per channel)` step reporting
`ready=1 … mode=scheduled`, and an `Upload (private, gated)` step that is **skipped** while `upload=false`.
If you dispatched with `-f upload=true`, the upload step runs instead and the release time is whatever
`publishing` reports — read it before you dispatch.

The first *scheduled* run is the real test: at 20:00 IST (±the dispatch delay), the Short is rendered,
uploaded private with `publishAt`, and YouTube publishes it. Verify with

```bash
python tools/report_episode_qc.py          # reads the build tree
gh api repos/Ayushjaiswal0001/youtube/actions/runs?per_page=5 --jq '.workflow_runs[] | "\(.name) \(.event) \(.conclusion)"'
```

and in the Studio: the video must show as **Scheduled** before it goes live, then as **Public** at 20:00 IST
with the custom thumbnail and `madeForKids` false.

**2. Academic Biohacker** (12:00 IST) — only after Nexus has published one scheduled video successfully.
Its channel is **not eligible for custom thumbnails yet** (see §6.2), so the video will carry YouTube's
automatic frame; that is a channel-verification problem, not a factory problem.

**3. Natkhat Toons** (18:00 IST) — last. Kids content, so `madeForKids` is forced true and the upload is
rejected by the uploader if that flag is ever false. The pilot confirmed the API stores
`madeForKids: true`, `selfDeclaredMadeForKids: true`.

**Emergency stop, any time:**

```bash
gh workflow disable "nexus-node daily"
python -m factory.cli pause --channel all --reason "owner stop"
```

`pause` stops rendering and publishing inside the code; disabling the workflow stops the trigger. Do both if
a release has already been scheduled, because the workflow can no longer stop it — only the Studio can.

---

## 5. What a scheduled day looks like

For each enabled channel, at its cron minute:

1. `short` job and `long` job start in parallel (separate budgets: 60 and 120 minutes, separate concurrency
   groups, separate state-cache keys).
2. `plan new` selects the next episode (research-driven for Nexus and Academic; series-driven for Natkhat).
3. `resume` renders only what is missing; the build is complete only when both `video.mp4` and `timeline.json`
   exist, so a killed encode is re-rendered rather than reused.
4. QC (25 technical checks) → manifest rebuild → publishing gate. A blocked gate fails the job and nothing is
   uploaded.
5. `Publishing policy` reports `ready`, `mode`, and the release instant it would use.
6. Upload (private) with `publishAt` = that instant; thumbnail applied when the channel allows it.
7. Job summary records plan, QC, gate, sha256, policy, release mode, release instant and its reason.
8. On failure: the summary says which channel, which format, which release mode and the run URL, and
   `factory.cli notify` posts to `FACTORY_NOTIFY_WEBHOOK` if it is configured.

Six videos a day in total (3 Shorts + 3 long-form) once all three channels are enabled. Two jobs per channel
also means a long-form failure does not stop the Short.

---

## 6. What is still unproven

**6.1 An honoured `publishAt`.** Covered in §2 and §3. This is the activation event itself.

**6.2 Custom thumbnails on Academic Biohacker.** The pilot upload returned
`HTTP 403 forbidden: The authenticated user doesn't have permissions to upload and set custom video
thumbnails`, and the upload still completed with `thumbnail_applied: false`. Nexus Node and Natkhat Toons
accepted theirs. Fix: verify the channel at <https://www.youtube.com/verify> (phone verification unlocks
custom thumbnails), then re-run one upload.

**6.3 Post-upload correction, and captions.** `youtube.update` returns `403 insufficientPermissions` with the
current grant, so a scheduled release cannot be moved, and `captions.insert` is not permitted either. All
three pilot videos report `contentDetails.caption: false`: the factory writes `captions.srt` for every episode
but has no scope to attach it. One re-consent with
`https://www.googleapis.com/auth/youtube` (force-ssl) fixes both; it must be done by the owner, and it
invalidates nothing else.

**6.4 The two-job daily workflow on hosted hardware.** `production (manual)` proves `produce.yml` renders both
formats on a runner, but the *two-job* shape lives in the daily workflows, and a disabled workflow cannot be
dispatched (`422 Cannot trigger a 'workflow_dispatch' on a disabled workflow`). Its first real execution is
step 1 of §4; watch the first run rather than assuming it.

**6.5 GitHub's own dispatch delay.** Crons are UTC and GitHub may delay a scheduled run by minutes. A run that
starts before the release instant and finishes after it is handled (`too_close_to_release`,
`late_run_shifted`); a run delayed beyond 90 minutes is refused rather than published late. If delays turn out
to be routinely longer than that, raise `late_grace_minutes` per channel — the value is in the channel JSON,
not in the code.

---

## 7. Files involved

| file | role |
| --- | --- |
| `factory/publishing.py` | policy parsing, release resolution, duplicate-slot lookup |
| `factory/config.py` | reads the `publishing` block into `ChannelSpec.publishing` |
| `channels/*.json` | the per-channel consent |
| `factory/cli.py` | `publishing` verb; `publish --schedule` uses the resolver; refuses a past `--publish-date` |
| `tools/publishing_outputs.py` | turns the CLI payload into workflow step outputs |
| `.github/workflows/produce.yml` | policy step, `release` input, upload gate, `--schedule` only for `auto` |
| `.github/workflows/produce-*.yml` | derive `upload` and `release` from the event |
| `.github/workflows/production.yml` | `release` input so the path can be exercised by hand |
| `tests/factory/test_publishing_policy.py` | 33 tests: policy, resolver, duplicate slots, CLI wiring, workflow shape |
