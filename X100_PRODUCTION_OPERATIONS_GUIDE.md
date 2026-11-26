# X100 production operations guide

Reviewed 2026-11-26. Repository: Ayushjaiswal0001/youtube at D:\X100-youtube. Main is b16c4b5fd0d8cd6731d11dde40fc3a7d49b52d8f. The JobLock/content candidate is 7d6ffe0 on codex/fix-joblock-ownership and is not merged. This guide does not authorize workflow activation.

## Current workflow state

Read-only GitHub checks found:

- academic-biohacker daily: disabled_manually
- natkhat-toons daily: disabled_manually
- nexus-node daily: disabled_manually
- production (manual): active, idle
- produce, CI, security: active
- Actions runs in progress: none

A disabled schedule has no actual next run. If enabled, the next nominal daily occurrence is 2026-11-27. The local pause file reads paused=false, scope=none. GitHub Actions variables access returned 403, so runner-level/global account pause remains owner-dependent.

## Read-only preflight

Use these commands from the X100 checkout. Do not pass secrets or print environment values.

    gh workflow list --all --repo Ayushjaiswal0001/youtube
    python -c "from factory.controls import pause_state; print(pause_state().as_dict())"
    python -m factory.cli plan available --channel all --format shorts
    python -m factory.cli plan available --channel all --format long
    python -m factory.cli publishing --channel all --json
    python -m factory.cli ops --channel all --json

Plan availability is no-render and no-upload. Publishing and ops report local policy/ledger state; they do not prove live YouTube metadata. A fresh activation preflight must verify channel identity and pending releases through an approved non-secret status operation.

## Schedule and expected release windows

Cron is UTC. The scheduled workflow starts each channel two hours before its configured release and creates independent Short and horizontal jobs.

| Daily workflow | Cron UTC | Nominal start IST | Nominal release IST | Formats |
| --- | --- | --- | --- | --- |
| nexus-node daily | 30 12 * * * | 18:00 | 20:00 | Short and horizontal |
| academic-biohacker daily | 30 4 * * * | 10:00 | 12:00 | Short and horizontal |
| natkhat-toons daily | 30 10 * * * | 16:00 | 18:00 | Short and horizontal |

These are configured times, not proof that a run occurred or YouTube stored publishAt. The channel JSON policies use scheduled mode, scheduled_upload=true, late policy shift, 90-minute grace, 15-minute minimum lead, and allow_public_upload=false. Natkhat is forced madeForKids=true.

## Rendering and publishing gates

The production path checks pause and content availability, takes the channel/plan JobLock before modifying the journal, renders and validates, writes a manifest, and applies the publishing gate. Upload requires explicit workflow and channel policy authorization, matching channel identity, and a passing gate. Scheduling additionally requires the schedule guard and YouTube status read-back. Missing, mismatched, or unreadable publishAt must fail closed. A computed release time or private upload without matching read-back is not scheduled-release success.

Production concurrency is grouped by channel and format and does not cancel the active job. A Short and horizontal job can proceed separately. GitHub concurrency has one running and one pending slot per group; it is not a durable unbounded FIFO.

## Safe owner activation sequence

Do not activate until the local JobLock branch has been published by an authorized identity, its focused PR is reviewed and merged, final PR CI/security and main CI pass, and a fresh owner-controlled account preflight passes. The attempted push and connected GitHub write API both returned HTTP 403 in this audit. Review the corrected Academic and Nexus derivatives under `audit-artifacts/corrected-2026-11-26/build/academic-biohacker/academic-post-meal-walk/` and `audit-artifacts/corrected-2026-11-26/build/nexus-node/nexus-data-wall/` before either is release-eligible; the preserved originals contain stale copy. Then follow X100_FINAL_ACTIVATION_HANDOVER.md. Nexus is first; activate one channel only, verify actual YouTube metadata, and consider the next channel only after that evidence.

After the owner has approved Nexus, the exact enable command is:

    gh workflow enable "nexus-node daily" --repo Ayushjaiswal0001/youtube

To disable it:

    gh workflow disable "nexus-node daily" --repo Ayushjaiswal0001/youtube

These commands are listed for owner use only. Neither was executed in this audit.

## Pause, resume, and emergency stop

The supported global stop command is:

    python -m factory.cli pause

Global resume:

    python -m factory.cli pause --resume

Channel-scoped stop/resume:

    python -m factory.cli pause --channel nexus-node
    python -m factory.cli pause --channel nexus-node --resume

During an incident, disable the relevant scheduled workflow and apply the global pause in the runtime whose state directory the workflow actually reads. Cancel an in-progress Actions job if necessary. Workflow disable and pause do not remove a publishAt already stored by YouTube. Inspect YouTube Studio and use owner-approved controls for an already scheduled video. Do not change OAuth scopes or credentials.

## Failure and recovery procedure

1. Inspect the exact workflow run, job, and failed step.
2. Determine channel, plan, format, whether rendering or upload began, and whether YouTube returned a video ID.
3. Inspect sanitized qc.json, publish_gate.json, manifest.json, job.json, and runs.jsonl as appropriate. Do not read or print OAuth values.
4. Confirm no competing writer. JobLock uses an OS lock; do not manually delete .guard files or force stale metadata.
5. Resume interrupted rendering only after confirming plan/journal state and a clear owner. An already published plan must not be regenerated for upload without explicit duplicate review.
6. If a private upload lacks a verified schedule, leave it private, stop retries, and hand it to the account owner. Do not claim release success.

## Current content capacity

The current authored bank contains 2 unused Academic Shorts, 4 Nexus Shorts, and 6 Natkhat Shorts across Haveli and Jungle, plus one horizontal plan per channel. All six format combinations report a locally available plan in an isolated query. A daily run consumes one Short and one horizontal plan per channel. Seven days of unique daily pairs require, at minimum, Academic +5 Shorts and +6 horizontal plans, Nexus +3 and +6, Natkhat +1 and +6. The current Natkhat horizontal is 64.5 seconds and needs a substantial authored story. This is not content generation authorization.
