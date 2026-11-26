# X100 final activation handover

Status date: 2026-11-26
Verified repository: Ayushjaiswal0001/youtube
Current main: b16c4b5fd0d8cd6731d11dde40fc3a7d49b52d8f
Reliability candidate: 7d6ffe07c59300d52fa6d1d07d221c67d32b6c97 plus follow-up journal-isolation fix 528ec22943c896a2626b4877ddaaa1f035480534 on codex/fix-joblock-ownership. PR #23 is open against main. The branch has been published using the already-authenticated owner keyring identity.

## Handover state

PR #22 is merged as b16c4b5. Main CI run 45705546332 and security run 45705546316 succeeded. The candidate is in PR #23; it is not merged. Initial push failed because the injected `GITHUB_TOKEN` authenticated as Ayushjaiswal001, whose repository permission is read-only (`push:false`). A separately authenticated Ayushjaiswal0001 keyring identity has `push:true`; after clearing the injected variable only inside the command process and selecting that existing account, the normal branch push succeeded. No credential was created or exposed. PR and push CI/security all passed on final source head 528ec22943c896a2626b4877ddaaa1f035480534, including Ubuntu factory coverage. Final documentation-only commits trigger new checks which must pass before merge. The repository branch protection API reports zero required approving reviews, and the accessible collaborator list contains only the PR author/owner. No independent reviewer is assigned. No production workflow was enabled or dispatched; no upload or schedule was made.

All three daily workflows are currently disabled_manually. The production (manual) workflow is active but idle. Final-source CI/security checks have completed; no production run is active. The local pause check reads paused=false. The owner CLI query returned an empty repository Actions variable list; the connected-app variables request earlier returned 403. Account-wide pause, live channel identity, and live YouTube pending schedules remain unverified. No OAuth value was read.

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

1. Open PR #23 and review its final diff. Ensure an independent maintainer with review access is assigned; the accessible collaborator list currently has only the PR author/owner. Add an eligible reviewer through repository Settings → Collaborators and teams if required, then select that person in the PR's Reviewers control. Do not self-approve.
2. Wait for every check on the latest PR head to finish successfully, especially `factory (plan + publish gates)`, `uploader (py3.11)`, `uploader (py3.12)`, and all four security jobs. Confirm the Ubuntu `tests/factory` run exercises POSIX `flock` and SIGKILL recovery.
3. Merge only through the normal GitHub PR UI after independent approval and green latest-head checks. The repository allows merge commit, squash, or rebase; use the normal repository policy. No merge was performed here.
4. Verify main contains the merge and its CI/security checks are green.
5. Review the corrected local derivatives at `audit-artifacts/corrected-2026-11-26/build/academic-biohacker/academic-post-meal-walk/` and `audit-artifacts/corrected-2026-11-26/build/nexus-node/nexus-data-wall/`. Automated media checks and sampled contact-sheet review passed; owner editorial review remains required. Do not release the preserved older files, which still contain stale copy.
6. Run a fresh read-only preflight: confirm global and channel pause state, plan availability, duplicate reservations, upload ledger, channel/account identity, policy, and pending YouTube releases. Use only approved non-secret identity/status checks. Repository Actions variables are empty; account-wide and live YouTube state remain unverified.
7. Obtain the owner's explicit activation approval. Then enable Nexus alone:

    gh workflow enable "nexus-node daily" --repo Ayushjaiswal0001/youtube

8. Observe the actual workflow. Verify each expected format, channel identity, upload outcome, video IDs, schedule_verified result, and the matching publishAt stored by YouTube. Keep private and escalate if verification fails.
9. Consider Academic only after Nexus has been independently verified. Consider Natkhat only after Academic is independently verified.

The enable command above is prepared for the owner and was not executed.

## Emergency stop

    python -m factory.cli pause
    gh workflow disable "nexus-node daily" --repo Ayushjaiswal0001/youtube

Use the corresponding disable command for another channel if it is the affected schedule. A disable does not terminate a currently running job and neither command removes a publishAt already stored at YouTube. Cancel an active Actions job and inspect YouTube Studio under owner authority when required. Resume only after the owner confirms the incident is resolved:

    python -m factory.cli pause --resume

See X100_PRODUCTION_OPERATIONS_GUIDE.md for scoped pause and recovery commands.
