# X100 post-merge production readiness report

Date: 2026-11-25 (late evening IST)
Repository: `Ayushjaiswal0001/youtube`
`main` verified: `f252ef687b48135cfa59fbefec9aac3fd3791a25` — merge of PR #20, 2026-11-25T14:44:06Z
Work for this report: branch `fix/post-merge-production-readiness`, three commits, four defects fixed
**Verdict: `READY WITH DOCUMENTED LIMITATIONS`** (§K)

---

## A. Executive summary

**What works.** The merged system renders, validates, gates, packages and uploads real episodes for all three
channels in both formats: 9:16 Shorts at 1080×1920 and 16:9 episodes at 1920×1080, English and Hindi, with
per-channel visual identities intact. Publishing authorization is per channel and enforced at three separate
points. Three private uploads are live on the three real channels. Main-branch CI is 7/7 green.

**What this pass fixed.** Four production defects, all found by *running* the merged code rather than reading it:

| # | defect | effect before the fix | fix |
| --- | --- | --- | --- |
| 1 | release duplicate guard was channel-wide | the Short's release blocked the long-form's → one video a day per channel instead of two | guard is per plan (`factory/publishing.py`), slugified comparison |
| 2 | every cron fired **at** its release instant | `on_time` was unreachable; every video published late (long-form measured ~65 min late); the declared IST release times were never met | crons start two hours earlier: `30 12` / `30 4` / `30 10` UTC |
| 3 | a scheduled upload was never read back | an upload with no `publishAt` was reported as a scheduled release | `verify_schedule()` reads `videos.list` back and fails the run on a mismatch |
| 4 | content exhaustion and fresh-channel ordering | long-form job red every day from day 2; the third channel could not start at all | `PlanGenerationError.kind`, `factory.cli plan available`, workflow warning-and-skip; ordering guard no longer demands episodes the factory never produced |

**What does not work yet, and cannot be made to work here.** Three limits are account-side, not code-side: custom
thumbnails are refused on Academic Biohacker until the channel is verified; captions cannot be attached and a
scheduled release cannot be re-timed with the current OAuth scopes; and the content bank holds exactly one
long-form episode per channel, so the long-form half of the daily cadence stops after one day per channel until
more episodes are authored.

**Is it production-ready?** For controlled activation of the Shorts + long-form cadence, yes, with those
limitations documented and the first release treated as a one-way door (§J).

---

## B. Main branch verification

| item | value |
| --- | --- |
| PR #20 (`feature/x100-scheduled-publishing`) | **MERGED** 2026-11-25T14:44:06Z |
| merge commit / current `main` | `f252ef687b48135cfa59fbefec9aac3fd3791a25` |
| PR #19 (handover docs) | MERGED 2026-11-25T14:44:08Z |
| CI on `f252ef6` | **7/7 green** — `uploader (py3.11)`, `uploader (py3.12)`, `secret scan (tree, staged, history)`, `factory (plan + publish gates)`, `dependency audit`, `gitleaks`, `workflow permissions and pinning` |
| branch protection | required contexts: the three above; 0 required reviews; force-push disabled; admins not enforced — untouched |
| local checkout | `main` at `f252ef6`, clean; work on `fix/post-merge-production-readiness` |
| repository secrets | 9 present, checked **by name only**; 0 repository variables |
| secret values read/printed/rotated | none |

---

## C. Channel readiness matrix

| | **Nexus Node** | **Academic Biohacker** | **Natkhat Toons** |
| --- | --- | --- | --- |
| channel id (live, verified) | `UCx9O8VivWkiEylDjs5_Zzag` | `UCr8jSmLa_o2BwNh8HuyZHAQ` | `UC4OCY0qDwQqFnSCZw12sKxA` |
| published videos (live API) | 549 | 58 | 62 |
| workflow file | `produce-nexus-node.yml` | `produce-academic-biohacker.yml` | `produce-natkhat-toons.yml` |
| workflow state | **disabled_manually** | **disabled_manually** | **disabled_manually** |
| cron (UTC) | `30 12 * * *` | `30 4 * * *` | `30 10 * * *` |
| starts / release (IST) | 18:00 → **20:00** | 10:00 → **12:00** | 16:00 → **18:00** |
| timezone handling | `IST = UTC+5:30`, no DST; release resolved from the run's IST date | same | same |
| publishing policy | `scheduled`, `upload_on_schedule`, `shift`, 90 min grace, 15 min lead | same | same |
| upload authorization | `inputs.upload` ∧ content available ∧ (release≠auto ∨ policy ready) ∧ creds ∧ gate, plus `FACTORY_ALLOW_UPLOAD` in code | same | same |
| schedule authorization | `release: auto` ∧ channel policy ∧ `FACTORY_ALLOW_SCHEDULE` (one step only) | same | same |
| Shorts | research-fed topic bank, unbounded | research-fed, unbounded | 6 authored series episodes, then a content gap |
| long-form | 1 plan, **renders + gates** (214.067 s @1920×1080) | 1 plan, **renders + gates** (218.926 s) | 1 plan, **renders + gates** (64.501 s) — new today |
| audio | −14.0 LUFS / −2.4 dBTP | −14.4 / −2.3 dBTP | −14.0 / −1.44 dBTP |
| subtitles | generated (17 cues, en) | generated (16 cues, en) | generated (21 cues, hi) |
| thumbnail | applied on upload | **403 refused by YouTube** (channel not verified) | applied |
| captions on YouTube | **not attached** (no scope) | **not attached** | **not attached** |
| recovery | kill mid-encode → `resume` re-renders the fragment (PR #18) | same | same |
| duplicate release | per plan, per IST day; sha256 ledger; `newer>candidate` refusal | same | same |
| failure notification | job summary + `FACTORY_NOTIFY_WEBHOOK` (unset → no-op) | same | same |
| can a scheduled release occur today? | **yes, once enabled** (one-way door) | **yes, once enabled** (thumbnail will be YouTube's auto frame) | **yes, once enabled** (`madeForKids` forced true) |
| evidence level | uploaded privately + hosted render + policy resolved | uploaded privately + hosted render | uploaded privately + 16:9 render + gate |

Evidence levels used throughout: *implemented* → *unit tested* → *executed locally* → *executed in GitHub
Actions* → *executed against the live YouTube API* → *executed as a public scheduled release*. **The last level
has not been reached by any channel**, and nothing in this report claims it.

---

## D. Pipeline validation

### D.1 Shorts (all three channels)

| step | evidence |
| --- | --- |
| plan generation | research-fed for Nexus/Academic (`plan new` in hosted runs 45623621859); series-driven for Natkhat (`natkhat-haveli-e4` resolved after the ordering fix) |
| script, voice | `[TTS] 01..08` lines in hosted logs; per-channel neural voices unchanged |
| visual selection, animation | 1,302→1,451-test suite, framing measured in pixels, creative QC |
| audio | −14.0 to −14.4 LUFS, true peak ≤ −1.44 dBTP, gate at −1.0 |
| subtitles | `captions.srt` per build, cue counts 16–21 |
| QC | 25/25 on every produced Short |
| upload + scheduling | proven privately (§E); scheduling decision unit-tested and resolver-verified on a runner |

### D.2 Long-form (all three channels)

| channel | rendering | duration | resolution | QC | gate | evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Nexus Node | `long-nexus-power-grid` | 214.067 s | 1920×1080 | 25/25 | 24/24 | local + **hosted run 45625058307** (18 min, 45,593,259 B) |
| Academic Biohacker | `long-academic-study-protocol` | 218.926 s | 1920×1080 | 25/25 | 24/24 | local |
| Natkhat Toons | `natkhat-haveli-stage-e1` | **64.501 s** | **1920×1080** | **27/27** | 25/25 | **rendered today**, 8,351,725 B, 12 scenes, −14.0 LUFS / −1.44 dBTP, 21 cues |

Natkhat's 16:9 episode is the first Hindi long-form this project has produced: frames inspected, not just the
exit code — the characters, the haveli background, the Devanagari caption band and the channel watermark are all
correct, and no subject is cropped. It is 64.5 s because the bank holds 12 short scenes; Nexus and Academic are
214 s and 219 s.

### D.3 Recovery and idempotency (inherited from PR #18, re-verified by the suite)

A build is complete only when `video.mp4` **and** `timeline.json` exist; a killed encode is re-rendered rather
than reused; a stale lock is reclaimed; the ledger refuses a repeated sha256; `cleanup` is dry-run by default and
kept all 16 entries in the live dry run (`no qc.json`, `no video.mp4`, `no manifest` — each kept with a reason).

---

## E. Publishing validation

### E.1 Authorization chain, verified in the workflow file (not only in tests)

`produce.yml`, production job, in order: `Content availability` → `Resolve the plan` → `Resume or render` →
`Quality assurance` → `Rebuild manifest after QC` → `Publishing gate` → `Package manifest` → `Publishing policy
(per channel)` → `Export channel credentials` → `Verify channel identity before upload` → `Upload (private,
gated)`.

```yaml
# upload
if: ${{ inputs.upload && steps.content.outputs.available == '1'
        && (inputs.release != 'auto' || steps.policy.outputs.ready == '1')
        && steps.creds.outputs.ready == '1' && steps.gate.outputs.ok == '1' }}
env:
  FACTORY_ALLOW_UPLOAD: "1"
  FACTORY_ALLOW_SCHEDULE: ${{ inputs.release == 'auto' && '1' || '0' }}
```

* upload authorization is checked **before** a credential is exported;
* schedule authorization is separate (`release: auto` **and** channel policy **and** the step-local flag);
* a render-only run cannot reach the upload step, and a day with no content cannot reach a credential;
* `--schedule` is passed only when `release == 'auto'`.

### E.2 Release-time behaviour (resolver, measured)

| situation | result |
| --- | --- |
| run at its cron instant (2 h before release) | `on_time` at the declared IST instant — new behaviour, was `late_run_shifted` |
| run 4 min after the release (old cron) | `late_run_shifted`, today, `now + 15 min` — **not** tomorrow |
| release under the 15-min lead | `too_close_to_release`, pushed out |
| run beyond the 90-min grace | `release_window_missed` → **refuse, run fails** |
| this plan already has a release at/after the instant | `release_already_scheduled` → refuse |
| this plan already released today | `already_released_this_plan_today` → refuse |
| the *other* format of the same channel scheduled the same instant | **allowed** (was refused before this pass) |

No instant of the day can produce a past `publishAt`: a sweep over every 7th minute asserts it.

### E.3 Live API evidence (private pilots, 2026-11-25)

| channel | video id | privacy | `publishAt` | made for kids | processing | geometry |
| --- | --- | --- | --- | --- | --- | --- |
| Nexus Node | `UuQKJ3jspKE` | private | none | false | processed | 1080×1920 @30 |
| Academic Biohacker | `O2YiFi0f_Ts` | private | none | false | processed | 1080×1920 @30 |
| Natkhat Toons | `derJO8hBnjo` | private | none | **true** | processed | 1080×1920 @30 |

Each carried `identity.verified: true` with `token_channel_id == expected_channel_id`, `duplicate_check: clear`,
`upload_performed: true`. No video was made public and no `publishAt` was set on any of them.

**A `publishAt` has never been sent to YouTube.** That is now the single unverified link in the chain, and it is
deliberately left to the first activation run: with the current grant it is a one-way door (§F.3).

---

## F. Permission limitations

### F.1 Academic Biohacker custom thumbnails — **account-side, not code**

```
ApiError: HTTP 403 forbidden: The authenticated user doesn't have permissions to upload and set custom video thumbnails.
```

Nexus Node and Natkhat Toons accepted theirs in the same minute with the same scope, so this is channel
eligibility (YouTube's phone verification), not scopes. The implementation already behaves correctly: the
thumbnail failure is recorded (`thumbnail_applied: false`, `thumbnail_error`), it is **not** retried, and the
upload proceeds — a poster frame is not worth losing the video over. Owner action: verify the channel at
<https://www.youtube.com/verify>, then re-upload one video.

### F.2 Captions — **scope-side**

All three pilots report `contentDetails.caption: false`. The factory writes `captions.srt` for every episode and
never attaches it, because `captions.insert` needs `https://www.googleapis.com/auth/youtube` (force-ssl). The
current grant is `youtube.upload` + `youtube.readonly`. Nothing in the code claims otherwise. Owner action: a
re-consent that adds the `youtube` scope; the exact user action is "run the existing consent flow again for the
Desktop client and approve the broader scope", and no credential value is touched by that.

### F.3 Scheduled-video modification — **scope-side, and why the first release is a one-way door**

`videos.update` returns `403 insufficientPermissions` with the current grant. The chain can therefore *create* a
release but never *move* or *clear* one. Consequences, and how the system is built around them:

1. the release instant is decided **before** the call (resolver) and verified **after** it (read-back);
2. a mismatch fails the run loudly instead of reporting success;
3. the first scaffolded run must be watched, with the pause commands ready **before** the instant (§J);
4. correcting a release requires YouTube Studio, or a re-consented token.

---

## G. Test results

| command | result |
| --- | --- |
| `python -m pytest tests -q` (full suite, this branch) | **1,451 passed, 5 subtests passed in 1165.01 s (0:19:25)** |
| `python -m pytest tests -q` (merged `main`, before this branch) | 1,428 passed, 5 subtests (1143.15 s) |
| new tests | `tests/factory/test_content_availability.py` +16; `test_publishing_policy.py` +3 (sibling-format release, plan-id lookup, cron-before-release); `test_publish_gates.py` +3 (schedule read-back: verified / never stored / different instant); `test_plan_factory.py` +1 (fresh channel starts) |
| assertions tightened | 2 workflow-shape assertions gained the new conjuncts; 1 fixture corrected because it pinned the defect it was meant to prevent |
| weakened / skipped / deleted | **none** |
| `python tools/secret_scan.py` | 14 rules, 0 findings |
| `python tools/dependency_audit.py` | 0 unaccepted, 0 accepted advisories |
| `python tools/workflow_audit.py` | 7 workflows, 0 findings |
| `python -m compileall factory studio tools tests` | clean |

Note on the corrected fixture: `test_out_of_order_episode_is_blocked` used to rely on `natkhat-haveli-e3` being
*absent from history* — precisely the condition that made a fresh channel unable to start. It now sets up the
case that must still block (episode 4 rendered, not uploaded) and the new test covers the fresh channel. PR #18
set the same precedent for two fixtures.

---

## H. Changes made

Branch `fix/post-merge-production-readiness`, three commits, 19 files, proposed as PR (owner merges; nothing was
pushed to `main`, no force-push, no branch-protection change).

| commit | subject | files |
| --- | --- | --- |
| `6114e34` | fix: the release guard is per plan, and every cron starts before its release | `factory/publishing.py`, `factory/cli.py`, 3 channel workflows, `produce.yml`, `tools/publishing_outputs.py`, 2 test files |
| `0fe25c2` | fix: a scheduled release is verified, not assumed | `factory/publisher.py`, `tests/factory/test_publish_gates.py` |
| `8e7b239` | fix: a content gap is a warning, and a fresh series channel can start | `factory/content/plans.py`, `factory/cli.py`, `tools/content_outputs.py`, `produce.yml`, 2 test files |
| (docs) | docs: the post-merge production picture | `X100_SCHEDULING_ACTIVATION_GUIDE.md`, `X100_PRODUCTION_OPERATIONS_GUIDE.md`, `X100_FINAL_QC_SUMMARY.md`, `X100_FINAL_RELEASE_REPORT.md`, this report |

Production behaviour changed deliberately, and only here:

1. crons now start 2 h before the release (three lines per workflow, documented in §C/§E);
2. duplicate-release protection is per plan;
3. a scheduled upload is read back and can fail the run;
4. a day with no content is green-with-warning instead of red;
5. the ordered-series guard ignores episodes the factory never produced.

Nothing else in the renderer, the QC thresholds, the gates, the channel identities or the visual policy was
touched.

---

## I. Remaining manual actions

Only these genuinely need the account owner:

1. **Merge the PR** for this pass (CI must be green first).
2. **Enable `nexus-node daily`** and watch its first run (§J). This is the first real scheduled release and the
   first execution of the two-job daily workflow on hosted hardware.
3. **Verify the Academic Biohacker channel** at <https://www.youtube.com/verify> to unlock custom thumbnails.
4. **Re-consent with the `youtube` scope** if captions or re-timed releases are wanted (one action, fixes both).
5. **Author more long-form episodes**: one per channel exists; the daily long-form cadence stops after one day
   per channel and says so in the run summary.
6. **Author more Natkhat series episodes**: six remain (2 series × 3); after that the Shorts bank is exhausted.
7. Optionally set `FACTORY_NOTIFY_WEBHOOK` so a silent failure is not silent.
8. Close or merge the stale PRs #2 and #4.

---

## J. Activation instructions

### J.0 Preflight (Stage A/B for Nexus Node) — run before enabling

```bash
# 1. the code that will run
gh api repos/Ayushjaiswal0001/youtube/commits/main --jq '.sha'          # expect the merge of this PR

# 2. CI on that exact sha
SHA=$(gh api repos/Ayushjaiswal0001/youtube/commits/main --jq '.sha')
gh api repos/Ayushjaiswal0001/youtube/commits/$SHA/check-runs --jq '.check_runs[] | "\(.name): \(.conclusion)"'

# 3. the workflow and its cron
gh workflow list --repo Ayushjaiswal0001/youtube | grep "nexus-node daily"   # expect disabled_manually
grep -A2 'schedule:' .github/workflows/produce-nexus-node.yml                 # expect 30 12 * * * UTC = 18:00 IST

# 4. the policy and the release it would schedule
python -m factory.cli publishing --channel nexus-node --json                  # expect mode=scheduled, ready=true

# 5. secrets exist (names only) and nothing else is queued
gh secret list --repo Ayushjaiswal0001/youtube --json name --jq '.[].name'
python -m factory.cli ops --channel nexus-node | head -30

# 6. nothing is paused
ls pipeline_state/nexus-node/paused 2>/dev/null || echo "not paused"
```

**Preflight result (measured 2026-11-25 21:06 IST):** workflow disabled ✓, cron `30 12 * * *` ✓, policy
`scheduled`/`ready` ✓, nine secrets present ✓, no release pending ✓, not paused ✓. Next Nexus run: **2026-11-26
18:00 IST**, release **2026-11-26 20:00 IST**.

**What the first Nexus run will do:** at 18:00 IST the Short job and the long job start in parallel; both plan
the next episode, render it (Short ≈4 min, long ≈18–50 min), QC 25/25, rebuild the manifest, gate, then upload
**privately** with `publishAt = 2026-11-26T14:30:00Z` (20:00 IST) and read the release time back. At 20:00 IST
YouTube makes both public. This cannot be undone from here: see §F.3.

### J.1 Enable, monitor, pause

```bash
# enable exactly one channel
gh workflow enable "nexus-node daily" --repo Ayushjaiswal0001/youtube

# watch the run it creates tomorrow at 18:00 IST
gh run list --repo Ayushjaiswal0001/youtube --workflow "nexus-node daily" --limit 5
gh run watch <run-id> --repo Ayushjaiswal0001/youtube

# what the run did (the summary also carries these rows)
gh run view <run-id> --repo Ayushjaiswal0001/youtube

# STOPS - both must be ready before the release instant
gh workflow disable "nexus-node daily" --repo Ayushjaiswal0001/youtube   # no new runs
python -m factory.cli pause --channel all --reason "owner stop"           # nothing renders or publishes
python -m factory.cli pause --channel nexus-node --clear                  # resume afterwards
```

`gh workflow disable` stops the trigger; `factory.cli pause` stops the run. Neither can recall a `publishAt`
that has already been set — for that, Studio, or the re-consented token in §F.3.

### J.2 Verify the first scheduled release (Stage C)

```bash
# 1. the run's own verdict
gh run view <run-id> --log | grep -E "release scheduled|schedule_verified|upload performed|publishAt"

# 2. the video as YouTube sees it
python -c "from factory.publisher import make_router; api=make_router().refresh_api('nexus-node'); \
s=api.get_video('<video_id>', parts='status')['status']; print(s['privacyStatus'], s.get('publishAt'), s['uploadStatus'])"
#    before 20:00 IST -> private with publishAt 2026-11-26T14:30:00Z
#    after  20:00 IST -> public, publishAt retained

# 3. no duplicate
python -m factory.cli ops --channel nexus-node | grep -i upload
```

Only if all three hold, mark Nexus Node production-validated.

### J.3 Then, and not before

Academic Biohacker (release 12:00 IST, cron 10:00 IST) — after Nexus has published one scheduled video, and with
the thumbnail limitation acknowledged. Then Natkhat Toons (release 18:00 IST, cron 16:00 IST), where
`madeForKids` is forced true by the uploader. One channel at a time, one verified release apart.

### J.4 Recovering a failed run

| symptom | cause | action |
| --- | --- | --- |
| `release_window_missed` | run finished >90 min after the release | re-run the workflow by hand (`gh workflow run`) while inside the window; otherwise the episode waits for tomorrow and stays private |
| `release_already_scheduled` / `already_released_this_plan_today` | duplicate protection | correct behaviour: nothing is uploaded |
| gate blocked | QC/manifest/metadata | read `gate.json` in the run artifacts; nothing was uploaded |
| `no content available` warning | bank exhausted | author the next episode |
| killed mid-encode | interruption | re-run: `resume` reuses completed scenes and re-renders only the fragment |
| `uploaded but the release was not applied` | YouTube did not keep `publishAt` | the video is private; set the time in Studio (or re-consent per §F.3) |

---

## K. Final verdict

**`READY WITH DOCUMENTED LIMITATIONS`.**

The engineering is done and verified by running it: four real defects found and fixed, 1,451 tests green, main
CI 7/7, three live private uploads, all three channels able to produce and gate both formats, and the publishing
chain now authorized, resolved, and read back. What remains is not code:

1. **A `publishAt` has never been honoured by YouTube** — the first activation run is the test, and it is a
   one-way door under the current grant.
2. **Custom thumbnails are unavailable on Academic Biohacker** until the channel is verified.
3. **Captions are never attached and a release cannot be re-timed** until the OAuth grant includes
   `https://www.googleapis.com/auth/youtube`.
4. **The content bank holds one long-form episode per channel** (and six Natkhat Shorts), so the daily long-form
   cadence stops after one day per channel; the run now says so instead of going red.

None of those is a reason to withhold activation of Nexus Node; each is a reason not to switch on three channels
at once, and to watch the first release rather than assume it.
