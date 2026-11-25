# X100 final release report

Date: 2026-11-25
Repository: `Ayushjaiswal0001/youtube`
Base `main`: `5e330d50067d59c29e79384f2c09c501db1a389b` (merge of PR #16)
Branch: `feature/x100-operations-hardening` (7 commits)

This report states what was measured, not what was intended. Anything not measured in this session is
labelled **not measured** rather than assumed.

---

## 1. What changed in this release

Seven commits, on top of `5e330d5`. Five of the seven exist because a pipeline was **run** and did
something wrong; each carries a regression test.

| commit | change | what running the pipeline showed |
|---|---|---|
| `94098c1` | each channel workflow runs a `short` job (60 min) and a `long` job (120 min), with no `needs:` between them; `produce.yml` takes `timeout_minutes`, keys concurrency and the state cache on the format, and tells the plan selector which bank to read; `plan new --format long` selects from the authored long-form bank; `production (manual)` is one job per channel with its own secrets | the bottleneck was structural: one job, one timeout, one queue, and a measured 16:9 episode took 3,090 s against a 60-minute budget |
| `f4c3383` | `skipped_render` is captured before the render instead of after it | three fresh renders in one batch all reported `skipped_render: true` |
| `3fdebf4` | `factory.cli cleanup`: dry run by default, deleting only builds that are released, QC-clean, gate-clean, complete, idle and older than the keep window | nothing ever removed a build directory, and local disk is the whole storage budget |
| `48b034f` | `build_script` adopts the plan's declared `format`, and a plan walk without `--format` covers both banks | `validate` on a 16:9 plan failed with "627 words, shorts allows 140" |
| `ce18339` | the uploader accepts both 1080p profiles the factory renders, and `publish` resolves the profile from the plan | `publish` on a 16:9 episode failed with "video must be 1080x1920, got 1920x1080" |
| `cf74fe1` | a second co-mention composition (`stacked`) joins the anti-repetition ladder | `academic-brain-wash` opened with three sentences naming two things, so the run was panels ×3, creative QC failed and the gate would have blocked it |
| `75e8484` | `cropped_frames` means pixels outside the frame; the margin band is reported separately as `near_edge_frames` | `natkhat-haveli-e2` failed the gate with "140 required subjects cropped" on frames whose measured overflow was 0.0 px |

No engine was rebuilt, no gate threshold was loosened, no channel configuration, schedule, secret or
publishing flag was changed. `75e8484` is the only change that touches a gate, and it separates two
conditions rather than relaxing one: a subject outside the picture still fails, and the number that was
previously invisible now appears as a warning (§16.7).

## 2. Workflow timeout and job separation

| question | answer |
|---|---|
| What was the bottleneck? | One job rendered whichever format the channel asked for, with a single 60-minute timeout. A measured 16:9 episode took 3,090 s (51 min 30 s), leaving nine minutes of headroom on this machine, and the three-minute Short queued behind it. |
| What is it now? | Two independent jobs per channel: `short` (`format: shorts`, 60 min) and `long` (`format: long`, 120 min). |
| How is isolation enforced? | Concurrency group `produce-<channel>-<format>`; state-cache key `state-<channel>-<format>-<run_id>`; one `format` input per job; the plan selector is told which bank to read. |
| Is the Short still fast? | Yes: 526 s for three Shorts in one batch, ≈166 s each. |
| Does a long-form failure block the Short? | No: separate jobs, separate conclusions, no `needs:`. The workflow-shape tests assert this (`tests/factory/test_production_workflow_shape.py`, 35 tests). |
| Does a timeout report against the right job? | Yes: each job carries its own budget, so a hung 16:9 render is reported against the `long` job. |
| Artifacts | Both jobs upload their own; the state cache key includes the format, so a long-form run cannot restore a Short's state. |
| Duplicate prevention | A rendered-but-unpublished plan is re-selected, so a failed upload resumes the validated video; the upload ledger refuses a second upload of the same sha256. |

Headroom: 3,090 s used of 7,200 s. A hosted runner doing this single-threaded Cairo work at half this
machine's speed would take ≈103 min, inside the 120-minute budget. **Not verified on hosted hardware** —
the number is an extrapolation, and the extrapolation is why the budget was doubled rather than tuned to
the measurement.

## 3. Three-channel production results

Six Shorts rendered in two batches in a clean build directory (`x100ops/build`), plus one long-form and
one recovery build, on the branch.

| channel | plan | video | size | QC | creative QC | gate |
|---|---|---|---|---|---|---|
| Nexus Node | `nexus-agents-leave-chat` | 38.638 s | 8,017,184 B | 25/25 ok | ok (2 warnings) | 25/25 |
| Nexus Node | `nexus-small-models` | 35.758 s | 8,020,560 B | 25/25 ok | ok (1 warning) | 25/25 |
| Academic Biohacker | `academic-brain-wash` | 38.230 s | 8,171,333 B | 25/25 ok | ok | 25/25 |
| Academic Biohacker | `academic-morning-light` | 38.446 s | 8,253,376 B | 25/25 ok | ok | 25/25 |
| Natkhat Toons | `natkhat-haveli-e1` | 32.135 s | 5,018,086 B | 25/25 ok | not run (§16.4) | 24/24 |
| Natkhat Toons | `natkhat-haveli-e2` | 33.989 s | 5,273,414 B | 25/25 ok | not run (§16.4) | 24/24 |
| Academic Biohacker (16:9) | `long-academic-study-protocol` | 218.926 s | 43,556,899 B | 25/25 ok | not run | 24/24 |

```
python -m factory.cli batch --channel all --per-channel 1     # batch 1: WALL 526 s
python -m factory.cli batch --channel all --per-channel 1     # batch 2: WALL 511 s
python -m factory.cli gate --channel all                      # six episodes, exit 0, no blockers
```

The second batch rendered the *next* plan per channel (`academic-morning-light`, `natkhat-haveli-e2`,
`nexus-small-models`), which is the duplicate behaviour the cadence needs: a repeated run advances, it does
not re-publish.

## 4. Per-episode measurements

Generated from the artifacts themselves by `tools/report_episode_qc.py` — see
`X100_EPISODE_QC_REPORTS.md`. It now discovers episodes in the build directory instead of reading a
hand-written list, after a hard-coded list silently omitted an episode rendered in an earlier session.

Every episode: 25 technical checks pass, 0 failures. Creative QC (shorts engine only): 21 checks, no
errors. Two warnings remain, both recorded rather than suppressed:

| episode | warning | meaning |
|---|---|---|
| `nexus-agents-leave-chat` | `title_matches_narration`, `dataviz_delivered` | the on-screen title shares no content word with the narration, and no chart was drawn because no sentence states a figure |
| `nexus-small-models` | `dataviz_delivered` | same, no stated figure |
| `natkhat-haveli-e1`, `-e2` | `framing_off_shot_characters` | the close-up deliberately excludes the listener (154 frames on `-e2`) |
| `natkhat-haveli-e2` | `framing_margin` | a required subject sat inside the safe margin on 140 frames, inside the picture the whole time |

## 5. Animation inspection

Frames were extracted from the encoded videos and read, not inferred from logs.

| channel | what the frames show | frozen-frame scan |
|---|---|---|
| Natkhat Toons | two rigged characters, blinking eyes and varying mouth shapes, one close-up shot, consistent haveli background across all five scenes | 0 events at −50 dB over 32.1 s |
| Nexus Node | diagram plates with camera push-in/drift, one composition per scene, captions legible over the plate | 0 events |
| Academic Biohacker | paper-palette plates with the academic pictograms; `academic-brain-wash` now runs panels → stacked → panels instead of four identical rings | 0 events |

Plate animation is still camera motion over a redrawn plate; object-level animation inside a diagram is
not implemented (§16.1).

The `-e2` framing question was settled by measuring drawn pixels, not by trusting the report: sampling all
204 frames at 6 fps and testing for the characters' colours at the left and right edge, the mouse's colour
never reaches an edge and the monkey's does on 2 frames of 204 (its raised arm, inside the frame). Nothing
is cut off, which is what `75e8484` now records correctly.

## 6. Long-form

| item | value |
|---|---|
| plan selected by `plan new --format long` | `long-academic-study-protocol` (first unpublished in the authored bank) |
| render wall clock | 3,090 s (51 min 30 s) — 14.1× the episode's own 218.9 s |
| output | 218.926 s, 43,556,899 B, 1920×1080, h264 + aac, 30.000 fps |
| QC | 25/25 ok, 0 failures |
| gate | 24/24, no blockers |
| upload dry run | `dry_run_ok`, `upload_performed: false`, `private`, duplicate check `clear` |
| subtitle/audio | −14.2 LUFS, −2.11 dBTP, A/V start delta 0 ms, length delta 11 ms |

### 6.1 Long-form pipeline result

Rendered through exactly the steps the `long` job runs — `resume --format long` (which plans, narrates,
renders, packages), then `validate`, `manifest`, `gate`, `publish` without `--execute`:

```
resume --format long   → RESUME_WALL 3090 s, job state READY_TO_PUBLISH
validate               → exit 0, qc_ok true, 25 checks
manifest               → exit 0
gate                   → exit 0, 24/24, blockers []
publish                → exit 0, dry_run_ok, no upload
```

Two defects were found by running it, and both are fixed in this branch:

1. `validate` refused the plan as "627 words, shorts allows 140" because the read path used the channel's
   native profile and ignored the format the plan declares (`48b034f`).
2. `publish` refused the encoded video with "video must be 1080x1920, got 1920x1080" because the uploader
   hard-coded the portrait geometry (`ce18339`). Without these two fixes the long-form half of the nightly
   cadence could render, pass QC and pass the gate, and then be unpublishable.

## 7. Audio and subtitle measurements

| check | how it is measured | result |
|---|---|---|
| integrated loudness | EBU R128 on the encoded file | −14.2 LUFS (long-form) and −14.3 LUFS (Shorts), target −14 |
| true peak | EBU R128 on the encoded file | −2.11 dBTP (long-form), −2.25 dBTP (Shorts), gate −1.0 |
| audio/video sync | stream start and length deltas | start 0 ms, length 11 ms |
| subtitle sync | captions come from the same timeline as the audio | 10–17 cues per Short, one per script line |
| subtitle language | Devanagari for Natkhat, English for the others | matches the channel's `language` |
| dead air / frozen frames | `freezedetect` at −50 dB | 0 events on every episode |

## 8. Full test results

```
python -m pytest tests -q
1387 passed, 5 subtests passed in 1034.56s (0:17:14)
```

### 8.1 Test suite

1,387 tests on `fcce00b`. Grown by 31 in this branch: `test_production_workflow_shape.py` (35),
`test_longform_planning.py` (17), `test_skipped_render_flag.py` (2), `test_housekeeping.py` (12),
`test_read_side_formats.py` (7), `test_upload_geometry.py` (6 unittest cases, 5 sub-cases), plus the framing
report split (2) — minus one test rewritten for the two-bank plan walk. No test was deleted, skipped or
loosened; the two tests that changed expectations changed because the behaviour they pinned was the bug
(`test_a_plan_walk_without_a_request_covers_every_plan` now expects both banks).

Two of these tests were only made to *run* in CI after CI rejected them — reported here rather than
quietly fixed, because the first push was red:

| CI finding | fix |
|---|---|
| the uploader job runs `python -m unittest discover -s tests` with no third-party packages, so importing `pytest` failed the job at collection | `test_upload_geometry.py` rewritten as `unittest` |
| that job installs no system packages, so `ffprobe` is absent and `probe_media` refused before reaching the geometry rule | the availability check and the probe are both stubbed |
| the factory job installs `requirements.txt` plus `pytest` only, so the workflow-shape tests could not `import yaml` | `pyyaml==6.0.2` installed alongside `pytest` — the alternative was replacing a YAML parser with regexes, which is a weaker test, not a smaller one |

## 9. CI

Branch protection requires `uploader (py3.11)`, `uploader (py3.12)` and
`secret scan (tree, staged, history)`. This branch adds no required context and changes no protection.

### 9.1 Check runs

Read from `gh api repos/Ayushjaiswal0001/youtube/commits/fcce00b/check-runs` — the code commit, since a
report cannot contain the check-runs of the commit that contains it:

| check | result |
|---|---|
| `uploader (py3.11)` | completed success |
| `uploader (py3.12)` | completed success |
| `secret scan (tree, staged, history)` | completed success |
| `gitleaks (independent scanner)` | completed success |
| `factory (plan + publish gates)` | completed success |
| `dependency audit` | completed success |
| `workflow permissions and pinning` | completed success |

7 of 7 green. The first two pushes were red — the uploader job caught a `pytest` import and then a missing
`ffprobe` in a job that installs neither, and the factory job caught a missing `yaml`. Those are the only
CI iterations; the fixes are in §8.1. PR #17 is `MERGEABLE` / `CLEAN`, with no auto-merge and no review
decision, and `main` is unchanged at `5e330d5`.

## 10. Batch throughput against the target

Target: 3 Shorts + 3 long-form per day.

| item | measured | basis |
|---|---|---|
| 3 Shorts | 526 s (8 min 46 s) | `batch --channel all --per-channel 1` wall clock |
| 1 long-form | 3,090 s (51 min 30 s) | single 16:9 render, §6 |
| 3 long-form | 9,270 s (154 min 30 s) | 3 × the measured single render |
| total per day | 9,796 s ≈ **163 min** of machine time | sum of the above |

That is one machine working 2.7 hours a day; the three long-form jobs are independent, so with runners in
parallel the wall-clock cadence is one 51-minute long-form plus three 3-minute Shorts. The 120-minute
budget gives 2.3× headroom on the measured long-form render.

## 11. Idempotency and recovery

| experiment | result |
|---|---|
| repeated render of an existing plan | 7 s, `skipped_render: true`, identical sha256 |
| repeated batch run | rendered the **next** plan per channel (§3), no duplicate episode, no re-upload |
| fresh render | `skipped_render: false` — the flag now reports what happened |
| SIGKILL mid-render, then `resume` | recovered to `READY_TO_PUBLISH`, stale lock reclaimed, QC 25/25 |
| cleanup dry run | 8 entries, 0 deletable, 83.4 MiB, every entry kept with a reason |

### 11.1 Idempotency and recovery results

Interruption test, run on this branch: `render --channel academic-biohacker --plan-id academic-gut-brain`
was killed 25 s in. The job file was left in state `GENERATING` and the lock file
`academic-biohacker_academic-gut-brain.lock` was left behind, which is exactly the crash a runner
cancellation leaves. `resume` then completed the episode in 181 s:

```
job state            READY_TO_PUBLISH
lock files remaining none (stale lock reclaimed)
video                38.662 s, 8,455,487 B
QC                   25/25 ok
```

Idempotency: `render --plan-id nexus-small-models` on an existing build took 7 s, reported
`skipped_render: true`, and returned the same sha256 as the render that produced it.

## 12. Upload dry-run

Per channel, on the acceptance build, `publish --schedule` without `--execute`:

| channel | status | upload performed | duplicate check | privacy | made for kids | publishAt |
|---|---|---|---|---|---|---|
| Nexus Node | `dry_run_ok` | false | clear | private | false | `2026-11-25T14:30:00Z` |
| Academic Biohacker | `dry_run_ok` | false | clear | private | false | `2026-11-25T06:30:00Z` |
| Natkhat Toons | `dry_run_ok` | false | clear | private | **true (forced)** | `2026-11-25T12:30:00Z` |

Each returned `scheduled: true` with the channel's configured release time and `upload_performed: false`,
and each recomputed its own gate before packaging (24/24, 24/24, 23/23 — the publish gate carries the
checks that matter to an upload, which is one fewer than the render gate).

Upload readiness is also exercised by mocked tests: duplicate hash blocked, wrong channel aborts before
upload, retryable API error marks the attempt `unknown` (never a blind retry that could double-publish),
non-retryable error marks `failed`, no OAuth token ever appears in a result object.

The upload path itself has never run against YouTube (§16.5).

## 13. Scheduling dry-run

Scheduled release requires `FACTORY_ALLOW_SCHEDULE=1` at execute time, so a scheduled publish cannot happen
by accident, and the three daily crons remain `disabled_manually`. The computed `publishAt` values above
match the channel configuration exactly (20:00, 12:00 and 18:00 IST).

## 14. Security audit

| check | command | result |
|---|---|---|
| secret scan (tree) | `python tools/secret_scan.py` | 14 rules, 0 findings |
| secret scan (history) | `python tools/secret_scan.py --history` | 14 rules, 0 findings |
| dependency audit | `python tools/dependency_audit.py` | 0 unaccepted, 0 reviewed-and-accepted |
| workflow audit | `python tools/workflow_audit.py` | 7 workflows, 0 findings |
| diff review | `git diff main...HEAD` | 22 files: three workflow files, `factory/` (cli, plans, housekeeping, validator), `studio/` (framing, episode merge), `uploader/metadata.py`, `tools/report_episode_qc.py`, tests, docs. No secret, no OAuth change, no channel configuration, no schedule, no dependency |

### 14.1 Security results

All four sweeps clean on the final commit. The diff introduces no network call on any render path, no new
runtime dependency (`requirements.txt` untouched), and no new credential read. `python
tools/workflow_audit.py` was re-run after every workflow edit and reported 0 findings each time — including
after the one-line CI change that installs `pyyaml==6.0.2` for the workflow-shape tests.

## 15. Cost

| item | cost |
|---|---|
| GitHub Actions | ₹0 — public repository, standard-runner minutes unmetered |
| rendering | ₹0 — local Python + FFmpeg + Cairo, no GPU, no paid API |
| assets | ₹0 — generated plates, procedural music bed, no stock library |
| storage | local disk only; `factory.cli cleanup` bounds it |

## 16. Known limitations

1. **Diagram plates animate by camera motion only.** The content of a plate does not animate (no growing
   bars, no lighting nodes). This is the largest remaining visual gap and is unchanged by this release.
2. **Natkhat wide shots are near-static**; secondary motion exists but is subtle, and there is one close-up
   per episode.
3. **Charts only appear when a script states a numeric figure**, and the topic banks state none, so real
   episodes draw no chart.
4. **Creative QC covers only the shorts engine.** Natkhat and the 16:9 card renderer carry the 25 technical
   checks and no creative verdict.
5. **The upload path has never executed.** Its correctness rests on mocked tests and on three dry runs.
6. **Long-form banks hold one authored episode per channel.** When it is uploaded, the nightly long job
   stops with "author the next long-form episode" — a loud stop, not a silent repeat.
7. **`framing_margin` is a new warning, not a gate.** 140 frames of `natkhat-haveli-e2` sit inside the safe
   margin. The staging is tight; nothing is cut. Fixing it means either widening the wide shot or letting
   the camera follow a walking character, which changes composed frames and is left as an owner decision.

## 17. Owner actions still required

1. Enable the three daily workflows when ready — they are `disabled_manually` and this branch does not
   change that.
2. Authorise the private upload validation: consent screen **In production**, then a `workflow_dispatch` of
   one channel with `upload=true`, or of `production (manual)`.
3. Decide whether the topic banks should state figures; that is what would make charts appear.
4. Author further long-form episodes before the bank runs dry.
5. Merge or close PR #2 and PR #4; set `FACTORY_NOTIFY_WEBHOOK` if failure notification is wanted.
6. Keep or widen the 120-minute long-form budget after the first hosted run reports its real duration.

## 18. Verdict

**ENGINEERING COMPLETE — AWAITING PRIVATE UPLOAD AUTHORIZATION.**

Every item on the definition of done was executed and measured here except the one that cannot be: a real
upload. Three channels produce independently (six Shorts, two of each channel, plus a long-form and a
recovery build); both formats render, validate, gate and dry-run publish; the long-form path is proven end
to end after two blocking defects were found by running it; the timeout bottleneck is removed and the
capacity measured; idempotency, interruption and recovery are verified; the full suite passes; the security
sweeps are clean; and no scheduled publish, upload, secret change or cron activation happened.
