# X100 automation rollout status — 2026-11-26

This is a live-state addendum to the older handover notes. It records the checks completed on 26 November
2026 and separates GitHub's current settings from the staged configuration prepared in this checkout.

## GitHub Actions

The repository's read-only Actions listing shows all three daily workflows as **active**:

| Workflow | State | UTC schedule |
| --- | --- | --- |
| Nexus Node daily | active | `30 12 * * *` |
| Academic Biohacker daily | active | `30 4 * * *` |
| Natkhat Toons daily | active | `30 10 * * *` |

No run was queued or in progress at the time of the check. The authenticated GitHub CLI received HTTP 403
when asked to disable a workflow, and could not read repository Actions variables. The connected browser
control was unavailable. Therefore the remote workflow toggles and emergency-stop variables were not
changed or verified. A local configuration change does not affect GitHub until its PR is merged.

## YouTube preflight

Fresh OAuth identity checks matched the configured YouTube channel IDs for Nexus Node, Academic Biohacker,
and Natkhat Toons. A read-only YouTube API scan of each channel's latest 50 uploads found no video with a
future `publishAt` value.

Nexus Node video `ZK-AMW8Lw-U` (“AI Training Data: A Forecast, Not a Countdown”) is public. YouTube reports
`publishedAt=2026-11-26T14:30:10Z` and no current `publishAt`, which is expected after release. The local
factory history record at `audit-artifacts/nafay-style-pass/state-v2/nexus-node/history.json` records
`publish_at=2026-11-26T14:30:00Z`. The matching stored release time and YouTube publication time confirm
that the Nexus release completed at the intended 20:00 IST window. No second Nexus release is pending.

The uploader ledger records the recent Academic upload as `O2YiFi0f_Ts` and Natkhat upload as
`derJO8hBnjo`; both remain private. Local ops reports no running jobs, failed factory jobs, or artifacts
ready to publish.

## Staged production gate

The proposed channel configuration sets `production_enabled=true` for Nexus Node and Academic Biohacker,
and `production_enabled=false` for Natkhat Toons. The reusable workflow checks that gate immediately after
checkout and before dependency installation, planning, rendering, credential export, upload, or scheduling.
The local `pause_state` and publishing-policy reports also honor it. This permits the verified Nexus and
next Academic stages while keeping Natkhat held until its turn. It takes effect on GitHub only after the
proposed code change is merged.

The GitHub daily workflows themselves remain active. Anyone needing them fully disabled before the code
change is merged must use an account with Actions administration rights to disable them in GitHub.

## Project checks

- Focused uploader, ledger, ops, workflow, publishing-policy, animation, and activation-gate checks: **98
  passed**.
- Full local suite before the final activation-gate adjustment: **1,474 passed, 1 skipped, 3 failed**.
  Two failures came from tests that assumed Natkhat was enabled; they were updated to isolate the
  production guard, and the final focused subset now passes. The remaining full-suite failure was the
  existing end-to-end Academic render test, which could not resolve `translate.google.com` for its gTTS
  fallback in this environment. The complete suite was not rerun after the final gate adjustment.
- The updated Natkhat cinematic-folktale frame was visually inspected. Audio playback of the corrected
  Academic and Nexus videos was not available through the desktop playback control in this session, so no
  subjective listening sign-off is recorded.
