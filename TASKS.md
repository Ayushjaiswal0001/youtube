# TASKS

Prioritised. Each task lists its dependency and what "done" means in verifiable terms.
Status markers: `[ ]` todo, `[~]` in progress, `[x]` done.

## P0 — Protect what exists (do before any new feature)

- [x] **T1. Commit the uncommitted factory work** on `feat/autonomous-multichannel-factory`
  in small commits (configs, factory package, studio copy, content/assets/state, docs).
  *Done when* `git status` is clean and `git log` shows the phases.
- [ ] **T2. Restore push capability.** Blocked by permissions. Owner has ruled out
  `Ayushjaiswal001`; only `Ayushjaiswal0001/youtube` may be used.
  *Done when* one of: owner grants collaborator write access to
  `Ayushjaiswal0001/youtube`; or `Ayushjaiswal001` forks it and the branch is pushed
  to a fork; or the project moves to a repository the account can write to.
- [x] **T3. Fix asset tracking.** Add `!assets/**/*.wav` (and any needed negations).
  *Done when* `git ls-files assets` lists the music and SFX files.
- [x] **T4. Secret hygiene.** Confirm no credential file is tracked, add a
  pre-commit secret pattern check. *Done when* `git ls-files | grep -i credential` is empty
  and `D:\animated\ytcredetials.txt` stays untracked and ignored.

## P1 — Make the existing pipeline runnable (blockers for automation)

- [x] **T5. Restore the missing `studio/` modules** (`story_engine`, `characters/*`,
  `audio/*`, `animation/camera.py`, `animation/effects.py`, `pipeline/episode.py`,
  `__init__.py`) from `D:\animated\studio`, keeping the repo's newer
  `config.py`/`scene_renderer.py`/`background.py`/`qa/validator.py`.
  *Done when* `python -m factory.cli render --channel natkhat-toons --plan-id natkhat-haveli-e1 --force`
  produces a 1080x1920 MP4 with audio and `qc_ok: true`.
  *Depends on:* T1.
- [x] **T6. Add `requirements.txt`** pinned to what the code imports
  (`pycairo`, `numpy`, `pillow`, `edge-tts`, `gtts`, plus test deps) and make
  `ci.yml` install it. *Done when* CI installs and the compileall+unittest steps still pass.
- [x] **T7. Neutralise the `studio.config` monkey-patch fragility** — pass output paths
  explicitly (or set env vars before the first import) so a second render in the same
  process does not reuse stale directories. *Done when* two different channels render
  in one process.
- [x] **T8. Factory test suite** (`tests/factory/`): plan validation rejects short/long
  scripts, QC catches wrong geometry, publisher honours the three gates, SRT generation,
  state dedupe/advance. *Done when* ≥25 new tests pass in CI.

## P2 — Autonomy: stop depending on hand-written plans

- [x] **T9. Plan generation for English channels.** `factory plan new --channel X`
  that reads `spec.queries` + `pipeline_state/<slug>/history.json`, picks an unused
  topic, and writes a plan that satisfies `build_english_script` invariants
  (≥4 beats, 60–140 words, ≥2 sources). *Done when* the command emits a plan that
  renders and QCs clean with zero manual editing.
- [x] **T10. Natkhat series engine.** Series memory in `pipeline_state/natkhat-toons/series.json`
  (`active_series`, `next_episode`, `outline[]`, `finished`), scene authoring per episode,
  automatic new series after the finale, and a hard rule: never emit episode *n+1* while
  episode *n* is not `uploaded`. *Done when* three consecutive runs produce e1, e2, e3,
  correctly numbered, and a fourth run starts a new series.
- [x] **T11. Ban repeat topics permanently.** Wire `ChannelState.is_duplicate` into plan
  generation and render. *Done when* re-running plan generation never repeats a
  previously produced topic.

## P3 — GitHub Actions production

- [ ] **T12. Verify CI feasibility** for PyCairo, headless Chrome, Edge-TTS on
  `ubuntu-latest` with one throwaway `workflow_dispatch` job. *Done when* a 5-second
  test render succeeds in the runner and the log shows no network block.
- [~] **T13. Produce workflows** `produce-nexus.yml`, `produce-academic.yml`,
  `produce-natkhat.yml`: `schedule` (UTC: 14:30 / 06:30 / 12:30) + `workflow_dispatch`,
  `concurrency` group per channel, `timeout-minutes: 30`, render → QC → upload →
  verify, artifact upload (`build/**`, `qc.json`, `runs.jsonl`), retry on transient
  failure. *Done when* a manual dispatch of each workflow publishes one private video
  and the artifact contains the QC report.
- [~] **T14. Persist state between runs.** Restore/save `pipeline_state/` and
  `~/.faceless-shorts/state/youtube` via `actions/cache` and/or commit-back with
  `FACTORY_STATE_DIR`. *Done when* a second run sees the first run's history and
  continues the series.
- [ ] **T15. Provision Actions secrets** `YT_NEXUS_NODE_*`, `YT_ACADEMIC_BIOHACKER_*`,
  `YT_NATKHAT_TOONS_*`, `FACTORY_ALLOW_UPLOAD`, and verify each channel authenticates
  as its own channel ID inside the runner. *Done when* `verify --channel all` passes in
  Actions output.
- [~] **T16. Failure handling.** On failure: upload logs as artifacts, open/annotate an
  issue or send a notification, and never mark the day as produced. *Done when* a
  deliberately broken plan fails the job with diagnostics and no upload.

## P4 — Verification and hardening

- [ ] **T17. Post-upload verification** in the workflow: `videos.list` the new ID,
  assert privacy/publishAt/madeForKids/title, record it in `history.json`.
  *Done when* the run log shows the verification payload.
- [ ] **T18. Duplicate protection at workflow level:** skip the whole job when today's
  history entry already has status `uploaded`.
- [ ] **T19. OAuth longevity:** document/execute the re-consent procedure and confirm
  whether the OAuth app is in Testing mode. *Done when* a token older than 7 days
  refreshes successfully, or the re-consent cadence is documented and scheduled.
- [ ] **T20. Public-release decision.** All channels currently upload `private`.
  Turning on `publishAt` scheduling requires `FACTORY_ALLOW_SCHEDULE=1` plus human
  sign-off; changing default privacy requires editing `channels/*.json`.

## P5 — Later

- [ ] **T21. Long-form support** (1920x1080 renderer path, longer scripts, chapter SRT).
- [ ] **T22. Analytics loop** — feed view/like data back into topic selection.
- [ ] **T23. Vendor the full `faceless-shorts` skill** (`styles/` engines) or delete the
  partial vendored copy; it is currently dead weight.

## Completion criteria for "fully autonomous daily publishing"

1. Every channel produces a video from a topic the system chose itself, with no
   hand-authored plan.
2. QC passes with zero errors and the run records `status: uploaded` with a video ID.
3. The scheduled workflow runs unattended for 7 consecutive days with 1 video/channel/day.
4. No duplicate topics, no wrong-channel uploads, no shared-state loss between runs.
5. Any failure is visible (artifact + notification) and self-recovers on the next run.
