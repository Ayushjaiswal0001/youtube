# Post-merge cloud acceptance

Baseline: `main` @ **`6f20b90336e3a7c9b0ad880012dd22ec6760fc7e`**, the merge commit of PR #5, 2026-11-22T21:13:11Z.
Every run below was dispatched with `upload=false`. Nothing was uploaded, published or scheduled.

## 1. Baseline audit

| Item | Value |
| --- | --- |
| `main` | `6f20b90336e3a7c9b0ad880012dd22ec6760fc7e` (PR #5 merged, `b6e76df` head) |
| Workflows at `main` | `ci`, `security`, `produce` (reusable), `production` (manual), three daily channel workflows `disabled_manually` |
| `production.yml` inputs | `channel` (choice: nexus-node / academic-biohacker / natkhat-toons), `mode` (render+validate / render / validate), `plan_id` (string), `format` ("" / shorts / long), `upload` (boolean, default **false**) |
| Repository secrets | **0** — `gh secret list` empty |
| Repository variables | **0** |
| Schedules | all three channel workflows `disabled_manually`; no cron is active |
| `gh auth` | account `Ayushjaiswal0001`, scopes `gist, read:org, repo, workflow` |
| Latest run before this wave | `45045980024` on `43e87e5` (the failed run that PR #5 repaired) |

## 2. Dispatch — the plan ids in the directive do not exist in the repository

Two of the four requested plan ids were never committed. `plan new` created them in the local build that
named them, and `content/` is the only source the runner has:

```
content/batch_2026-11-20.json
  nexus-node     -> nexus-agents-leave-chat, nexus-small-models, nexus-ai-memory-cost,
                    nexus-data-wall, nexus-on-device
  academic-biohacker -> …, academic-post-meal-walk, …
  natkhat-toons  -> natkhat-haveli-e1, natkhat-haveli-e2, natkhat-haveli-e3
content/longform/   -> natkhat-toons.json (natkhat-haveli-stage-e1), nexus-node.json
```

`nexus-power-grid` exists only as a *topic* (`content/topics/nexus-node.json`) and `natkhat-haveli-e4` does not
exist anywhere. Both were dispatched as requested, both failed, and the failure mode was itself a defect —
see §8. They were then re-dispatched with plan ids that exist. No content was added to make a run pass.

| # | Run | Channel | Plan | Dispatch |
| --- | --- | --- | --- | --- |
| 1 | [45071096194](https://github.com/Ayushjaiswal0001/youtube/actions/runs/45071096194) | nexus-node | `nexus-power-grid` | `--ref main -f mode=render+validate -f upload=false` |
| 2 | [45071111024](https://github.com/Ayushjaiswal0001/youtube/actions/runs/45071111024) | academic-biohacker | `academic-post-meal-walk` | same |
| 3 | [45071125280](https://github.com/Ayushjaiswal0001/youtube/actions/runs/45071125280) | natkhat-toons | `natkhat-haveli-e4` | same |
| 4 | [45071139345](https://github.com/Ayushjaiswal0001/youtube/actions/runs/45071139345) | natkhat-toons | `natkhat-haveli-stage-e1` | `+ -f format=long` |
| 5 | [45071520031](https://github.com/Ayushjaiswal0001/youtube/actions/runs/45071520031) | nexus-node | `nexus-data-wall` | re-dispatch |
| 6 | [45071525421](https://github.com/Ayushjaiswal0001/youtube/actions/runs/45071525421) | natkhat-toons | `natkhat-haveli-e1` | re-dispatch |
| 7 | [45076319335](https://github.com/Ayushjaiswal0001/youtube/actions/runs/45076319335) | academic-biohacker | `academic-post-meal-walk` | `--ref fix/plan-lookup-and-gate-profiles` @ `802033c` |

Run 7 is on the fix branch on purpose: `main` cannot pass an academic gate at all (§8, cause 2). Runs 1–6 are
on `main` @ `6f20b90`.

## 3. Results

| # | Channel | Plan | Format | Result |
| --- | --- | --- | --- | --- |
| 1 | nexus-node | `nexus-power-grid` | short | **FAILED** — Quality assurance (plan not in repo) |
| 2 | academic-biohacker | `academic-post-meal-walk` | short | **FAILED** — Publishing gate (QC had passed) |
| 3 | natkhat-toons | `natkhat-haveli-e4` | short | **FAILED** — Quality assurance (plan not in repo) |
| 4 | natkhat-toons | `natkhat-haveli-stage-e1` | long | **PASSED** |
| 5 | nexus-node | `nexus-data-wall` | short | **PASSED** |
| 6 | natkhat-toons | `natkhat-haveli-e1` | short | **PASSED** |
| 7 | academic-biohacker | `academic-post-meal-walk` | short | **PASSED** (on the fix branch) |

## 4. Artefacts — downloaded, probed, hashed

All four produced episodes were downloaded with `gh run download` and probed with `ffprobe`; hashes are of the
downloaded bytes.

| Run | Episode | Duration | Picture | Audio | Size | sha256 |
| --- | --- | --- | --- | --- | --- | --- |
| 5 | `nexus-data-wall` | 38.266 s | 1080×1920, 30 fps, h264 | aac 44.1 kHz stereo | 9.26 MB | `0c550e6882ca5fd0cbaa1363d000425dc7c76bc9fd9725b607ef577bd4006a46` |
| 7 | `academic-post-meal-walk` | 38.366 s | 1080×1920, 30 fps, h264 | aac 44.1 kHz stereo | 10.14 MB | `6d8ef98ed2032ca39521c2aa972aa240eece8a6eb50d9fd5c2bbe10f6d70509f` |
| 6 | `natkhat-haveli-e1` | 32.135 s | 1080×1920, 30 fps, h264 | aac 44.1 kHz stereo | 4.32 MB | `edd1c633d2eea88636759cd162e826903ec5033bad7a9f22db207db2a2ef8904` |
| 4 | `natkhat-haveli-stage-e1` | 64.501 s | 1920×1080, 30 fps, h264 | aac 44.1 kHz stereo | 7.97 MB | `488caf5c91f75767a6768bd1973384bd4abd413f4365fb9f36a4d7c65ad547cd` |

Shorts are 1080×1920 and the long-form episode is 1920×1080, as required. Audio decodes on all four.

## 5. QC, manifest and gate, per run

| Run | QC | Manifest | Gate |
| --- | --- | --- | --- |
| 5 `nexus-data-wall` | **25/25**, 0 failures | 8 entries; 5 verified from the artefact (see §7) | **24/24**, 0 blockers |
| 7 `academic-post-meal-walk` | **25/25**, 0 failures | 8 entries; **8 verified**, 0 missing, 0 mismatched | **24/24**, 0 blockers |
| 6 `natkhat-haveli-e1` | **25/25**, 0 failures | 8 entries; 5 verified | **24/24**, 0 blockers |
| 4 `natkhat-haveli-stage-e1` | **27/27**, 0 failures | 10 entries; 5 verified | **25/25**, 0 blockers |

Manifest verification space: `video`, `thumbnail`, `captions`, `qc_report`, `timeline`, `script`, `story`,
`framing` for the shorts package; `+ shot_plan`, `continuity` for long-form. Every hash that was downloaded
matched its recorded `sha256` **and** byte count. Runs 4, 5 and 6 were produced before the artefact-upload
repair, so their `timeline`, `script` and `story` entries (and `shot_plan`/`continuity` for run 4) existed only
inside the runner: the artefact could not prove them. Run 7 carries the repaired upload list and verifies 8/8.

## 6. Frame inspection

Frames were extracted from every episode and looked at, not summarised from QC.

- **Run 5, Nexus Node short**: 7 numbered cards ("THE NEXT SHORTAGE", "TRILLIONS OF WORDS", "SUPPLY
  TIGHTENING", "THREE WORKAROUNDS", "QUALITY BEATS VOLUME", "FOLLOW"), counter-rotating dashed rings and a
  per-card icon, karaoke caption window ("Compute The next", "Large models are", …) inside the band, channel
  handle and progress bar at the bottom. No frozen card, no clipped text, no oversized glyph.
- **Run 7, Academic Biohacker short**: "MUSCLE AS A SINK", card 03/07, cell icon with red/teal motion rings on
  the light palette, caption "a transporter that" clear of the card, handle and progress bar correct.
- **Run 6, Natkhat Toons short**: Gappu on the haveli barrel at night, Devanagari caption inside the band,
  no collision with the character.
- **Run 4, Natkhat Toons long-form**: Chiku against the moonlit haveli at 20 s and 55 s, 16:9 framing with the
  chapter label above the caption band; composition matches the local render of the same plan.

## 7. Failures and what was repaired

Full forensic detail: `FINAL_LAUNCH/CLOUD_RUN_2_FORENSIC_REPAIR.md`. Repairs are in **PR #6**,
https://github.com/Ayushjaiswal0001/youtube/pull/6 (`fix/plan-lookup-and-gate-profiles`, head `802033c`,
MERGEABLE, CLEAN, 14/14 checks SUCCESS).

1. **A requested plan that is not in the repository was an empty success.** `resume --plan-id <missing>` printed
   `[]` and exited 0; `validate` exited 1 with "no rendered artifacts found"; the workflow's QC step then died
   with `IndexError: list index out of range`. Now one plan walk (`_iter_requested_plans`) serves `resume`,
   `validate` and `manifest`, raising `plan 'X' is not in this repository; known plans: …`, and the QC step
   names the plan instead of crashing.
2. **The gate could not survive a channel with no landscape plan.** Run 2 rendered the academic Short, passed
   QC 25/25 and then died with `ValueError: no long plans for channel 'academic-biohacker'` — my own regression
   from `b6e76df`. The gate now skips an empty profile and prints `no plans to gate for: <channel>/<format>`.
   This is the only reason run 7 had to be dispatched from the branch.
3. **Hashed artefacts were not downloadable.** `timeline`, `script`, `story`, `shot_plan`, `continuity` and
   `publish_gate` are now uploaded, which is why run 7 verifies 8/8 instead of 5/8.
4. **The emergency stop did not stop the pipeline's render.** `FACTORY_PAUSED=1` + `resume` started TTS and
   created a build directory; only the local `render` verb was guarded. The guard now sits in
   `orchestrator.render_episode`, the choke point every producing path uses. Verified: global flag stops all
   three channels, per-channel flag stops only that channel, one channel paused leaves the others rendering,
   `python -m factory.cli pause --channel X` writes `PAUSED_X` and `pause --channel X --resume` clears it, and
   `notify` reports `delivered: False / NullNotifier` when no webhook is configured.
5. **A re-run of a finished episode crashed before rendering.** `pipeline_state` is cached across runs and
   `build/` is not, so run 7's first attempt restored a journal saying `READY_TO_PUBLISH` and raised
   `READY_TO_PUBLISH -> QUEUED is not a legal transition`. The rewind is now recorded (`RECOVERABLE` → `QUEUED`)
   and a `PUBLISHED` episode still refuses without `--force`.
6. **The workflow masked command failures.** `cmd | tee file` reports `tee`'s exit status, so a failing
   `resume` looked like a passing step and the next step failed instead. Every such step now sets
   `set -o pipefail`.

## 8. Tests

- **863 passed** (was 858 before this wave), 0 failed. New this wave: `tests/factory/test_plan_lookup_errors.py`
  (7), three pause/rewind tests in `tests/factory/test_controls.py`, and the empty-report guard exercised
  through the workflow change.
- Golden frames: **78 checked, 0 changed, 0 new**.
- Workflow audit: 7 workflows, 0 findings. Dependency audit: 0 unaccepted, 0 reviewed-and-accepted.

## 9. Security

- **No credentials printed.** Grep over the complete logs of the failed and passing runs for `gho_`, `ghp_`,
  `AIza` and `refresh_token`: no match. Zero repository secrets, so no credential was exported at all
  (`::add-mask::` count 0, as expected when `creds.ready == 0`).
- **No local paths in published artefacts.** Scanned every uploaded JSON for `C:\Users`, `C:/Users` and
  `/Users/DELL`: **0 matches**. Runner paths (`/home/runner/…`) appear in QC and manifest records and are not
  sensitive.
- **Least privilege.** `production.yml` and `produce.yml` declare `permissions: contents: read`; the upload job
  passes only its own three secrets.
- **Publishing stays closed.** `UPLOAD_ENABLED=false`, `SCHEDULED_PUBLISHING_ENABLED=false`,
  `PUBLICATION_APPROVAL_REQUIRED=true`; upload requires `inputs.upload ∧ creds.ready ∧ gate.ok`, and with zero
  secrets `creds.ready` is 0.
- **Schedules.** Three channel crons remain `disabled_manually`. No cron was enabled.

## 10. Not claimed

- **No upload, no private upload, no public publishing, no scheduling, no visibility change.** Every dispatch
  carried `upload=false` and the upload steps were skipped in all seven runs.
- **Academic Biohacker has never passed a gate on `main`.** It passed on the fix branch only. Until PR #6 is
  merged and the four runs are repeated from `main`, this row is pre-merge evidence, not acceptance.
- **Nexus Node and Academic Biohacker have no long-form plan**, so the "three channels × two formats" matrix
  cannot be filled at all; only Natkhat Toons has a landscape episode.

## 11. Remaining owner actions

1. **Merge PR #6.** It is the only thing standing between this wave and full four-row acceptance on `main`.
2. Re-run the four acceptance dispatches from `main` after the merge:
   ```
   gh workflow run production.yml --ref main -f channel=nexus-node        -f plan_id=nexus-data-wall        -f upload=false
   gh workflow run production.yml --ref main -f channel=academic-biohacker -f plan_id=academic-post-meal-walk -f upload=false
   gh workflow run production.yml --ref main -f channel=natkhat-toons      -f plan_id=natkhat-haveli-e1      -f upload=false
   gh workflow run production.yml --ref main -f channel=natkhat-toons -f format=long -f plan_id=natkhat-haveli-stage-e1 -f upload=false
   ```
   (`nexus-power-grid` and `natkhat-haveli-e4` are not in the repository. If those specific episodes are wanted,
   commit them to `content/` first — `plan new` output is not committed automatically.)
3. Decide whether Nexus Node and Academic Biohacker should get landscape plans (`content/longform/<channel>.json`),
   since without them two-thirds of the long-form matrix is unbuildable.
4. YouTube work stays parked behind an explicit approval: OAuth client with consent screen **In production**,
   `python -m uploader.cli consent --channel <slug>` per channel, the nine `YT_*` secrets, then one private
   upload per channel as Stage B.
5. Optional hardening: set `FACTORY_NOTIFY_WEBHOOK` (notifications currently report
   `delivered: False / NullNotifier`), and the two secret-scanning toggles plus code scanning remain
   owner-blocked API settings.

## 12. Verdict

**PARTIAL CLOUD ACCEPTANCE.**

Four episode productions completed in the cloud and were verified from their downloaded artefacts: Nexus Node
and Natkhat Toons Shorts and Natkhat Toons long-form on `main` @ `6f20b90`, and Academic Biohacker Short on the
fix branch @ `802033c`. Every one passed QC (25/25, 25/25, 27/27, 25/25), every gate reported zero blockers
(24/24, 24/24, 25/25, 24/24), and every hash that was downloadable matched its manifest entry.

It is not full acceptance for two reasons that are stated rather than papered over: the Academic row has not run
on `main` because the gate crash it depends on is fixed only on PR #6, and the plan ids the directive named for
Nexus Node and Natkhat Toons do not exist in the repository, so those rows were accepted with the committed
plans that do. Merging PR #6 and repeating the four dispatches closes the first; committing the missing plans
would close the second.
