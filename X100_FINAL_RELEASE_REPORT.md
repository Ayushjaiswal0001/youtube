# X100 final release report

Date: 2026-11-25
Repository: `Ayushjaiswal0001/youtube`
`main` at the start of this mission: `b53a647fc159ef760591efa4183b43c83dc51ef4` (merge of PR #17)
`main` at the end: unchanged — this mission merged nothing.
Engineering changes: **two** (PR #18), both for defects found by running production; everything else is
verification and documentation.

**Verdict: `FULLY OPERATIONAL — AWAITING OWNER AUTHORIZATION`** (§18).

---

## 1. Verified merged state

Read from GitHub during this mission, not from earlier reports.

| item | value |
|---|---|
| PR #15 (visual engine v1.1 implementation) | **MERGED**, 2026-11-24T20:35:04Z |
| PR #16 (three-channel visual integration) | **MERGED**, 2026-11-25T03:36:08Z |
| PR #17 (operations hardening) | **MERGED**, 2026-11-25T07:46:46Z |
| `main` | `b53a647`, a merge commit, working tree clean |
| required checks on `main` | `uploader (py3.11)`, `uploader (py3.12)`, `secret scan (tree, staged, history)` |
| branch protection | those three contexts, 0 required reviews, no force-push, admins not enforced |
| check-runs on `b53a647` | 7 workflows green (the `factory` job was still finishing when read, and went green) |
| workflows active | `ci`, `produce`, `production (manual)`, `security` |
| workflows disabled | `academic-biohacker daily`, `natkhat-toons daily`, `nexus-node daily` — all `disabled_manually` |
| crons as configured | nexus `30 14 * * *` (20:00 IST), academic `30 6 * * *` (12:00 IST), natkhat `30 12 * * *` (18:00 IST) |
| upload switches | `UPLOAD_ENABLED=false`, `SCHEDULED_PUBLISHING_ENABLED=false`, `PUBLICATION_APPROVAL_REQUIRED=true` in `produce.yml` |
| OAuth structure | Desktop client; `uploader/{oauth,credentials,identity,ledger,router,metadata,youtube}.py`; per-channel credential files at `YT_SECRETS_ROOT`, per-channel ledger at `YT_STATE_ROOT`; 9 repository secrets, 0 variables |

Channel configuration, read from `channels/*.json`:

| channel | channel id | handle | language | format | voice | palette | release | made for kids | public allowed |
|---|---|---|---|---|---|---|---|---|---|
| Nexus Node | `UCx9O8VivWkiEylDjs5_Zzag` | `@nexusnode012` | en | shorts | `en-US-AndrewNeural` | nexus | 20:00 IST | false | no |
| Academic Biohacker | `UCr8jSmLa_o2BwNh8HuyZHAQ` | `@academicbiohacker` | en | shorts | `en-US-AvaNeural` | academic | 12:00 IST | false | no |
| Natkhat Toons | `UC4OCY0qDwQqFnSCZw12sKxA` | `@NatkhatToons-n5` | hi | shorts | `hi-IN-MadhurNeural` | natkhat | 18:00 IST | **true** | no |

Visual policy: Nexus `planning=true, categories=(diagram, dataviz, motion_graphics)`; Academic
`planning=true, categories=(diagram, dataviz)`; Natkhat `planning=false` (its own studio renderer).

## 2. Engineering freeze

Held, with one exception.

| rule | status |
|---|---|
| no rebuild of the visual engine or renderer | held |
| no speculative features | held |
| creative QC thresholds unchanged | held |
| channel identities unchanged | held |
| no paid services | held |
| no unrelated refactor | held |
| fix only a confirmed production-blocking defect | **two fixes, PR #18** |

**Defect 1 — recovery.** A render killed during the encode could never be resumed. `_render_english`
treated the presence of a `video.mp4` as "episode finished", so a truncated file from a killed run made
`resume` fail for ever with `missing timeline` — the state a cancelled CI job leaves routinely, and the only
escape was `--force`, which discards every completed scene. Found by killing a real render at 40 s; fixed by
asking whether the build is *complete* (video **and** its timeline); verified by repeating the kill on both
the English and Hindi engines (169 s and 125 s to `READY_TO_PUBLISH`).

**Defect 2 — delivered audio.** A fresh render failed QC with `true peak -0.23 dBTP above -1.0`. The peak
guard measures the AAC file `mix_narration` writes and tightens its limiter until *that* file passes; the
renderers then muxed it with `-c:a aac`, a second encode of an already-encoded file, which adds inter-sample
overshoot *after* the measurement. The guard was approving a file the pipeline did not ship. Both card
renderers now copy the audio, so the measured file is the delivered file; verified on a real episode
(`mixed.m4a` −2.49 dBTP → delivered video −2.49 dBTP, QC `audio_loudness` ok) and quantified on a control
mux (−2.49 → −2.46 dBTP from one re-encode).

Nothing else in `factory/`, `studio/`, `uploader/` or `.github/workflows/` was touched.

## 3. Three channels, verified from artifacts

Seven episodes were produced on this machine from the merged code. Full per-episode tables:
`X100_EPISODE_QC_REPORTS.md`; mission summary: `X100_FINAL_QC_SUMMARY.md`.

| channel | Shorts | long-form | visual quality | animation | audio | subtitles | metadata | thumbnail | gate |
|---|---|---|---|---|---|---|---|---|---|
| Nexus Node | `nexus-agents-leave-chat` 38.6 s, QC 25/25 | `long-nexus-power-grid` 214.1 s @1920×1080, QC 25/25 | six distinct compositions, captions legible, brand band correct | 0 frozen runs, 0 identical frames, mean Δ 2.01 | −14.0 LUFS, −2.4 dBTP | 1,228 B / 17 cues, English | title ≤100 chars, category 27, tags `shorts` | 1280×720 | 25/25 (render), 23/23 (publish) |
| Academic Biohacker | `academic-brain-wash` 38.2 s, QC 25/25 | `long-academic-study-protocol` 218.9 s @1920×1080, QC 25/25 | paper palette, pictograms, `panels → stacked → panels → statement → statement → gap → cta`, 7/7 distinct plates | 0 frozen runs, mean Δ 1.95 | −14.4 LUFS, −2.3 dBTP | 1,119 B / 16 cues, English | as above | 1280×720 | 25/25, 23/23 |
| Natkhat Toons | `natkhat-haveli-e1` 32.1 s, QC 25/25 | **not configured**: the long-form bank holds a stage plan with 0 beats | two rigged characters, haveli continuity across 5 scenes, one close-up | 0 frozen runs, mean Δ 3.27 in the character zone, changing mouths and arms | −14.1 LUFS, −1.4 dBTP | 1,081 B / 15 cues, **Devanagari** | category 1, tags `shorts`, `kids`, `made_for_kids: true` forced | 1280×720 | 24/24 |

A second, independent Short per channel was produced during recovery testing
(`academic-cool-to-sleep`, `natkhat-haveli-e2`), both reaching `READY_TO_PUBLISH` with QC 25/25.

Scientific accuracy safeguards for Academic (verified as behaviour, not configuration): a chart may only
draw a number the narration states (`figure_is_stated` passes on every plate), an entity lexicon rather
than free-text keywords decides what is drawn, a subject the sentence does not name is not drawn, and a
stated property forces the composition to draw it. No economic or medical claim appears in a chart that
the script did not state.

## 4. Daily capacity

| item | measured |
|---|---|
| one Short (uncontended, warm cache) | ≈166 s wall for 32–39 s of video |
| three Shorts in one batch | 526 s (8 min 46 s) |
| one long-form, run alone | 3,090 s (51 min 30 s) for a 214–219 s episode |
| two long-form renders + a 29-minute test suite concurrently | ≈5,270 s each, i.e. contention roughly doubles the wall clock |
| 3 Shorts + 3 long-form | ≈163 min of machine time per day |
| budgets in production | 60 min per Short job, 120 min per long-form job |
| long-form headroom | 2.3× the measured solo render |
| disk per Short | ≈11 MB of build artifacts |
| disk per long-form | ≈50 MB of build artifacts |
| artifact retention | 14 days |

Final batch in this mission: three channels, one Short each, produced in a clean build directory, all
three `qc_ok`, all three gates clean, 0 failures, 0 retries.

The retry, idempotency and recovery behaviour of that cadence is verified in §6.

## 5. Upload readiness

| question | evidence | result |
|---|---|---|
| does each channel map to the right account? | live token exchange + `mine=true` per channel, compared with `expected_channel_id` and handle | **verified**: `UCx9O8VivWkiEylDjs5_Zzag` / "Nexus Node", `UCr8jSmLa_o2BwNh8HuyZHAQ` / "Academic Biohacker", `UC4OCY0qDwQqFnSCZw12sKxA` / "Natkhat Toons", `verified: true` on all three |
| is the correct format accepted? | uploader geometry rule | both 1080p profiles accepted (9:16 and 16:9); every other geometry refused with the allowed set named |
| is metadata valid? | `UploadRequest.validate` + publish gate on real artifacts | title length, category, tags, privacy, `madeForKids`, languages — all pass |
| does thumbnail preparation work? | `thumbnail.jpg` 1280×720 RGB in every build, checked by the gate | pass |
| does upload state persist? | `ledger.jsonl` per channel, append-only, written under a file lock | exercised by tests; guarded by `assert_no_duplicate` before any token exchange |
| are duplicate uploads prevented? | synthetic ledger entry for a real sha256 → `DuplicateUploadError` before any network call | **verified offline** |
| are retries safe? | a lost response marks the entry `unknown`, which blocks a blind retry; only `failed` is retryable | covered by `uploader` tests |
| is private mode supported? | `privacy: private` on all three dry runs; `--allow-public` refused by channel config | verified |
| are failures reported? | `WrongChannelError`, `DuplicateUploadError`, `UploadStateUnknown`, gate blockers, `PermissionError` for each disabled switch | verified by triggering four of them |

Nothing was uploaded. The upload path has still never run against YouTube, and the nine repository secrets
have never been used — the live identity check above used the local credential files, which is a different
store from the secrets the workflow exports.

## 6. Recovery, idempotency, duplicate prevention

| experiment | result |
|---|---|
| re-render a finished episode | 10 s, `skipped_render: true`, identical sha256 |
| fresh render, audio true peak | delivered video measured −2.49 dBTP = the mixed file the guard approved (−2.49); before the fix the delivered file could sit ~1 dB higher and fail QC |
| kill 40 s in, mid-encode, then `resume` | before PR #18: permanent `missing timeline`; after: 169 s → `READY_TO_PUBLISH`, QC 25/25 |
| kill 55 s in, mid-scene, then `resume` | 125 s → `READY_TO_PUBLISH`, scenes reused |
| stale lock from the killed process | reclaimed, no manual cleanup |
| duplicate sha256 in the ledger | `DuplicateUploadError` before any network call |
| cleanup over unreleased builds | 3 entries, 0 deletable, each kept with a reason |
| `resume` without `--plan-id` | renders **every** plan for the channel in both profiles — correct for "finish the catalogue", dangerous as a recovery command; the workflows always pass `--plan-id` |
| `validate` after packaging | rewrites `qc.json`, which invalidates the manifest hash; rebuilding the manifest restores the gate (23/23). The workflow already orders "Rebuild manifest after QC", so production is unaffected |

## 7. Scheduling readiness

| check | result |
|---|---|
| three crons configured and correct | yes, and equal to the three IST release times minus 5 h 30 min |
| timezone | IST is UTC+5:30 with no DST; `publish_at_utc` is a constant offset |
| schedule dry run, three channels | `dry_run_ok`, `scheduled: true`, `upload_performed: false`, publishAt `14:30Z` / `06:30Z` / `12:30Z` |
| roll-forward | a release time already past rolls to the next day (`academic` returned `2026-11-26T06:30:00Z`) |
| Short and long separated | two independent jobs, separate concurrency groups and state-cache keys, no `needs:` |
| production→upload dependency | the upload step is gated on `inputs.upload && creds.ready && gate.ok`, plus `FACTORY_ALLOW_UPLOAD` inside the CLI |
| duplicate prevention across days | the plan selector skips uploaded episodes; the ledger refuses a repeated sha256 |
| failure notification | `factory.cli notify` reports `delivered: false` (`NullNotifier`) until `FACTORY_NOTIFY_WEBHOOK` is set |
| activation | not performed; one command per channel documented in `X100_SCHEDULING_ACTIVATION_GUIDE.md` |

## 8. Monitoring

Existing reporting is sufficient, so no dashboard was built:

- `python -m factory.cli ops --channel all` — job state per episode (`READY_TO_PUBLISH`, attempts, error),
  artifacts with QC/gate/manifest/bytes, uploads, recent history, blockers.
- `tools/report_episode_qc.py` — now emits every field an operator needs per episode, read from the
  artifacts: channel, episode id, job id and state, upload attempts, rendered-at, artifact path, sha256,
  bytes, duration, resolution, frame rate, codecs, integrated loudness, true peak, subtitle presence and
  cue count, creative QC verdict, publishing gate, upload state, retry state. It accepts several build
  trees at once (`FACTORY_BUILD_DIR` separated by `;`) so Shorts, long-form and recovery builds land in a
  single report.
- The workflow's `Operational summary` step writes the same essentials into the run summary, and the
  artifacts (including `qc.json`, `publish_gate.json`, `manifest.json`, `runs.jsonl`, `job.json`) are
  uploaded with 14-day retention.

Single place to look: `X100_EPISODE_QC_REPORTS.md` (generated) for artifacts, plus the Actions run summary
for the state of the run that produced them.

## 9. Security and budget

| check | command | result |
|---|---|---|
| secret scan, working tree | `python tools/secret_scan.py` | 14 rules, 0 findings |
| secret scan, history | `python tools/secret_scan.py --history` | 14 rules, 0 findings |
| dependency audit | `python tools/dependency_audit.py` | 0 unaccepted, 0 accepted advisories |
| workflow audit | `python tools/workflow_audit.py` | 7 workflows, 0 findings |
| secrets printed | — | none; only names were read (`gh secret list`) |
| OAuth configuration | — | unchanged; no consent flow started, no secret written or rotated |
| unintended workflow changes | `git diff` | none; `.github/workflows/` untouched in this mission |
| unsafe artifact deletion | `cleanup` | dry run only, 0 of 3 entries deletable |
| accidental publishing | — | no upload, no schedule, no public request; all switches off |
| cost | — | ₹0: public repo, standard runners, local rendering, no paid API, no GPU |

## 10. Regression results

| check | result |
|---|---|
| full test suite, `main` (`b53a647`) | **1,387 passed, 5 subtests**, 29 min 24 s (run while two long-form renders and a batch competed for four cores) |
| full test suite, fix branch (PR #18) | **1,394 passed, 5 subtests** in 18 min (the final run is recorded in the PR) |
| recovery tests | `tests/factory/test_interrupted_render_recovery.py` (5) |
| delivered-audio tests | `tests/factory/test_delivered_audio.py` (2) |
| pose goldens | 3 passed |
| three-channel compatibility | 7 episodes across 3 channels, 2 formats, 2 languages |
| Shorts production | 5 Shorts produced, 25/25 QC each |
| long-form production | 2 episodes, 1920×1080, 25/25 QC, 24/24 gate, publish dry run clean |
| batch execution | `batch --channel all --per-channel 1` → 3 episodes, 0 failures |
| idempotency | re-render 10 s, unchanged sha256 |
| interruption recovery | 2 kills, 2 successful resumes (after the PR #18 fix) |
| upload dry run | 3 channels + 2 long-form, `dry_run_ok`, no upload |
| scheduling dry run | 3 channels, correct publishAt |
| security scans | 4 sweeps clean |

No test was weakened, skipped or deleted. Two fixtures were corrected to describe a real artifact (a
"verified" build always carries its timeline), and one source assertion was updated where it pinned the
expression that *was* the defect — both recorded in PR #18.

## 11. Authorization boundary

Performed: inspection, local production, workflow validation, one confirmed-defect fix, documentation, a
pull request, dry runs.

Not performed: no push to `main`, no merge, no OAuth flow, no secret read or change, no upload, no
scheduled release, no public publishing, no cron activation, no spend, no branch-protection change.

## 12. Handover documents

1. `X100_FINAL_RELEASE_REPORT.md` — this file
2. `X100_PRODUCTION_OPERATIONS_GUIDE.md` — commands, layout, state machine, gates, capacity, failure table
3. `X100_PRIVATE_UPLOAD_CHECKLIST.md` — one private upload per channel, step by step, with rollback
4. `X100_SCHEDULING_ACTIVATION_GUIDE.md` — the three crons, the one command each, what to check after
5. `X100_FINAL_QC_SUMMARY.md` — what the artifacts prove, and what no gate covers
6. `X100_EPISODE_QC_REPORTS.md` — the generated per-episode evidence

## 13. Definition of completion

| requirement | evidence |
|---|---|
| three independent channel workflows | 3 workflow files, each with a Short and a long-form job, independent concurrency and secrets |
| reliable Shorts and long-form rendering | 5 Shorts + 2 long-form episodes produced; long-form path also proven at the publish gate |
| genuine animation appropriate to each channel | frames read, motion measured (§3 of the QC summary) |
| correct audio and subtitle sync | −14 LUFS band, ≤ −1.4 dBTP, A/V deltas measured by QC, captions from the same timeline |
| quality gates | QC 25/25 on all seven; gate 23–25 checks; publish gate recomputed |
| batch production | 3-channel batch, 0 failures |
| idempotency | 10 s re-render, identical hash |
| failure recovery | 2 kills recovered, 1 of them only after PR #18 |
| upload readiness | identity verified live per channel; every guard exercised; no upload performed |
| scheduling readiness | dry runs correct; activation documented, not executed |
| measured daily capacity | ≈163 min/day; budgets 2.3× the measured long-form |
| operational documentation | six documents |
| no unauthorized external actions | §11 |

## 14. Verdict

**`FULLY OPERATIONAL — AWAITING OWNER AUTHORIZATION`.**

The system produces, verifies, gates and packages episodes for all three channels in both configured
formats, on a cadence whose cost is measured and whose failure modes were exercised rather than assumed.
What remains is exactly the set of actions that require the owner: a real private upload, the consent
screen, the nine repository secrets (never used), and turning the three crons on.

Owner actions, in the order they matter:

1. **Private upload test** — `X100_PRIVATE_UPLOAD_CHECKLIST.md` §0.1–§0.4, then one channel.
2. **Scheduling activation** — `X100_SCHEDULING_ACTIVATION_GUIDE.md` §4–§5, one channel first.
3. Set `FACTORY_NOTIFY_WEBHOOK` if a silent failure is unacceptable.
4. Author the next long-form episodes; Nexus and Academic each have one, Natkhat has none.
5. Decide whether the topic banks should state figures — that is what would make charts appear.
