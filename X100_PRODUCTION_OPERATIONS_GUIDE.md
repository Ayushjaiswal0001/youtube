# X100 production operations guide

This guide reflects merged code at `01f3abd4078abca30eabbd6822139130121a72d7`, reviewed 2026-11-26. Publishing workflows are currently disabled. Focused test and Windows portability fixes are prepared on a branch and await branch CI and owner review. Do not treat these instructions as owner activation approval.

## Read-only preflight

```powershell
gh workflow list --all --repo Ayushjaiswal0001/youtube
python -c "from factory.controls import pause_state; print(pause_state().as_dict())"
python -m factory.cli plan status --channel all --json
python -m factory.cli plan available --channel all --format shorts --json
python -m factory.cli plan available --channel all --format long --json
python -m factory.cli publishing --channel all --json
python -m factory.cli ops --channel all --json
```

`plan available` is a no-write/no-render availability check. `publishing` resolves the release policy and may inspect local recorded upload state; it does not upload or schedule. These commands cannot establish YouTube's live pending schedule without account/API access.

## Schedule and channel matrix

GitHub cron is UTC. The two-hour offset leaves time for both independent format jobs to finish before their intended release.

| Workflow | Cron UTC | Starts IST | Release IST | Formats |
| --- | --- | --- | --- | --- |
| `nexus-node daily` | `30 12 * * *` | 18:00 | 20:00 | Short + horizontal, separate jobs |
| `academic-biohacker daily` | `30 4 * * *` | 10:00 | 12:00 | Short + horizontal, separate jobs |
| `natkhat-toons daily` | `30 10 * * *` | 16:00 | 18:00 | Short + horizontal, separate jobs |

All three were observed as `disabled_manually` using `gh workflow list --all` during this audit. Channel JSON sets `mode=scheduled`, `scheduled_upload=true`, late policy `shift`, 90-minute grace and 15-minute minimum lead; Natkhat is forced `madeForKids=true`. None permits public uploads by default.

## Workflow stages and failure meaning

Each job runs availability → plan resolution → render/resume → technical QC → manifest → publishing gate → package. Credential export, identity validation, and upload are conditional on policy, inputs, available content, credentials, and a passing gate. Scheduled upload uses `privacyStatus=private` and `publishAt`; code then reads YouTube metadata back and requires the timestamp to match. Missing/mismatched/unreadable status fails the job. Uploading private without a verified timestamp is not a successful scheduled release.

An exhausted content bank is summarized as a warning/content gap and skips downstream work. A blocked plan, rendering/QC/gate error, wrong channel identity, duplicate plan, pause, or failed schedule read-back is an operational failure and should be investigated, not manually bypassed.

## Pause, resume, and emergency stop

The CLI parser's actual supported global pause/resume forms are:

```powershell
# Global stop (writes the global PAUSED state flag)
python -m factory.cli pause

# Resume all
python -m factory.cli pause --resume

# Channel-scoped stop/resume
python -m factory.cli pause --channel nexus-node
python -m factory.cli pause --channel nexus-node --resume
```

To prevent a future workflow trigger:

```powershell
gh workflow disable "nexus-node daily" --repo Ayushjaiswal0001/youtube
```

For an incident in a running production environment, disable the relevant workflow and apply the global pause. Then inspect/cancel an in-progress Actions job if necessary. A workflow disable or pause cannot remove a `publishAt` already stored by YouTube; inspect YouTube Studio and follow account-owner permissions. Do not change OAuth grants or modify releases without owner authorization.

The CLI does **not** support `--reason` or `--clear`; do not use `pause --channel all` for the global stop. `--channel all` is a literal channel selector, while no `--channel` means global.

## Failure diagnosis and recovery

1. Inspect the Actions run summary, failed job and exact step.
2. Read the channel/plan/format, failure category and whether any upload occurred.
3. Inspect `qc.json`, `publish_gate.json`, `manifest.json`, `job.json`, `runs.jsonl`, and sanitized action logs as relevant. Never print credential material.
4. Use `python -m factory.cli ops --channel <slug>` and `python -m factory.cli status --channel <slug> --plan-id <plan>` to inspect state.
5. Use `resume` for interrupted rendering only after confirming no conflicting writer. Duplicate-upload and schedule-verification protections must remain enabled.
6. For a private upload missing the requested `publishAt`, keep it private, stop automatic retries, and hand off to the account owner. Do not claim scheduled success.

## Current content and delivery coverage

Read-only local bank audit found four unused Shorts topics each for Nexus and Academic. Natkhat has three episodes left in its active Haveli series and three in the next Jungle series, for six authored Shorts across both series; the next plan is `natkhat-haveli-e4`. There is one authored horizontal plan per channel, and all six channel/format combinations currently report a plan available. Horizontal coverage at the current daily cadence is one day per channel. Natkhat's current horizontal plan produces 64.5 seconds and needs more authored story content to support a substantive long-form cadence.

## Monitoring

For every first run verify: expected cron trigger; both independent formats; content availability; channel identity; QC, manifest and gate; private upload; video IDs; `schedule_verified=true`; matching `publishAt` on YouTube; no duplicate releases; and no unexpected immediate publication. The exact owner-controlled first activation and evidence checklist are in [X100_FINAL_ACTIVATION_HANDOVER.md](X100_FINAL_ACTIVATION_HANDOVER.md).
