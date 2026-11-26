# X100 final activation handover

Status date: 2026-11-26
Verified repository: Ayushjaiswal0001/youtube
Current main: b16c4b5fd0d8cd6731d11dde40fc3a7d49b52d8f
Reliability candidate: 7d6ffe0 on codex/fix-joblock-ownership, awaiting PR/owner review

## Handover state

PR #22 is merged as b16c4b5. Main CI run 45705546332 and security run 45705546316 succeeded. The new JobLock fix is not merged and must receive a focused PR, owner review, Ubuntu POSIX lock coverage, successful PR CI/security, and protected merge before production readiness can advance. No production workflow was enabled, dispatched, uploaded, or scheduled in this audit.

All three daily workflows are currently disabled_manually. The production (manual) workflow is active but idle. There are no Actions runs in progress. The local pause check reads paused=false; GitHub Actions variables access returned 403, so runner/account pause state is owner-dependent. No OAuth value, live channel identity, or live YouTube pending schedule was checked.

## Nexus Node: owner preflight summary

| Item | Current evidence |
| --- | --- |
| Workflow | nexus-node daily |
| Current state | disabled_manually |
| Cron | 30 12 * * * UTC |
| Next actual run | None while disabled |
| Next nominal occurrence if enabled | 2026-11-27, start 18:00 IST |
| Nominal release | 20:00 IST; calculated policy time, not verified YouTube metadata |
| Expected formats | Short and horizontal, independent jobs |
| Local isolated availability query | Short nexus-power-grid; horizontal long-nexus-power-grid |
| Pause | Local check false / none; GitHub runner state not verified |
| Duplicate protection | Local plan/hash and release guards are in code; live GitHub/YouTube duplicate state not verified |
| Upload and schedule guards | allow_public_upload=false in channel policy; workflow and code guards require explicit inputs and gate; schedule read-back is required by code |
| Account/channel identity | Not verified against live YouTube; owner-dependent |

The local availability result uses isolated temporary state and does not prove production cache, reservation, duplicate, or YouTube state. The production workflow also builds the Academic and Natkhat channels on their own schedules; do not interpret the three disabled schedules as a complete account-level pause proof.

## Required owner-controlled steps

1. Review the focused JobLock/content PR after it is opened. Confirm required reviewers, security findings, Windows and POSIX CI, and the final changed files.
2. Merge only through the protected PR process if the owner accepts the change. No merge was performed here.
3. Verify main contains the merge and its CI/security checks are green.
4. Render fresh versions of academic-post-meal-walk and nexus-data-wall from corrected copy. Review narration, frames, AAC, SRT, and release gate. The preserved older files still contain copy that should not be released.
5. Run a fresh read-only preflight: confirm global and channel pause state, plan availability, duplicate reservations, upload ledger, channel/account identity, policy, and pending YouTube releases. Use only approved non-secret identity/status checks. The current API variable read returned 403.
6. Obtain the owner's explicit activation approval. Then enable Nexus alone:

    gh workflow enable "nexus-node daily" --repo Ayushjaiswal0001/youtube

7. Observe the actual workflow. Verify each expected format, channel identity, upload outcome, video IDs, schedule_verified result, and the matching publishAt stored by YouTube. Keep private and escalate if verification fails.
8. Consider Academic only after Nexus has been independently verified. Consider Natkhat only after Academic is independently verified.

The enable command above is prepared for the owner and was not executed.

## Emergency stop

    python -m factory.cli pause
    gh workflow disable "nexus-node daily" --repo Ayushjaiswal0001/youtube

Use the corresponding disable command for another channel if it is the affected schedule. A disable does not terminate a currently running job and neither command removes a publishAt already stored at YouTube. Cancel an active Actions job and inspect YouTube Studio under owner authority when required. Resume only after the owner confirms the incident is resolved:

    python -m factory.cli pause --resume

See X100_PRODUCTION_OPERATIONS_GUIDE.md for scoped pause and recovery commands.
