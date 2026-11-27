# X100 Operations Guide

**Live snapshot: 2026-11-27 23:47 IST.** Refreshed against `Ayushjaiswal0001/youtube`, GitHub Actions, the YouTube API, and the recorded workflow artifacts. This guide separates enabled automation from verified publishing.

## Current operational status

- Repository visibility is already **public**; no visibility change was needed. Main is `3fa3c981a1dbfc0248730a9a558b0d5da212948b` (PR #31). Post-merge CI run `46033672111` and security run `46033672255` passed.
- All three daily workflows are enabled in GitHub: Academic `425309827`, Natkhat `425309829`, Nexus `425309830`.
- Main contains the `:29` UTC triggers. These are trigger times; YouTube publication remains scheduled for noon, 18:00, and 20:00 IST.
- **No daily `schedule` run has been observed after PR #31 merged.** The most recent real schedule event is Academic run `46012727812`, created on pre-merge main `2ea73be` at 19:35 IST on Nov 27. Rendering and technical QC passed; the publishing policy reported `release_window_missed` and skipped credential export and upload. The late-run safety window was not weakened.
- Channel configs still have scheduled mode and `production_enabled: true`. No production gate, policy, channel setting, credential, or secret was changed during this rollout work.

## Expected next events

**Saturday, November 28, 2026** (assuming GitHub delivers each scheduled event on time):

| Channel | Workflow trigger | Intended YouTube release |
| --- | ---: | ---: |
| Academic Biohacker | 09:59 IST | 12:00 IST |
| Natkhat Toons | 15:59 IST | 18:00 IST |
| Nexus Node | 17:59 IST | 20:00 IST |

A workflow marked enabled is not proof that its next scheduled event ran. Check for `event=schedule`, `head_branch=main`, and both independent format jobs. Do not use `workflow_dispatch` as a substitute when a scheduled event is delayed; inspect the event time and release-policy decision first.

## Channel identity and YouTube evidence

The read-only identity verification returned:

| Channel | YouTube channel ID | Handle |
| --- | --- | --- |
| Academic Biohacker | `UCr8jSmLa_o2BwNh8HuyZHAQ` | `@academicbiohacker` |
| Natkhat Toons | `UC4OCY0qDwQqFnSCZw12sKxA` | `@NatkhatToons-n5` |
| Nexus Node | `UCx9O8VivWkiEylDjs5_Zzag` | `@nexusnode012` |

The only verified YouTube release is Academic Shorts video [`CPHaFFnSkuw`](https://www.youtube.com/watch?v=CPHaFFnSkuw). Manual workflow run `45949021636` (`workflow_dispatch`, older main `4fed999`) uploaded it private and read back `publishAt=2026-11-27T06:30:00Z` (12:00 IST). YouTube now reports it public with `publishedAt=2026-11-27T06:30:21Z`. This proves one scheduled Shorts release, **not** scheduled automation. No Academic long-form or Natkhat/Nexus release is verified.

The run artifact records the video ID, clear duplicate check, upload, and stored schedule. The separate local uploader ledger did not contain this ID in the last reconciliation; keep that discrepancy open until the ledger is reconciled. A custom-thumbnail call returned YouTube 403 for this account. No thumbnail retry or credential change was made. Analytics access is limited; one view and zero likes are too small a sample to judge engagement.

The last live YouTube pending-state check (Nov 27, 22:18 IST) found no unexpected pending releases. The Academic video had already published. No upload or schedule has been created during this continuation.

## Safe daily checks

From `D:\X100-youtube`:

```powershell
python -m factory.cli preflight --channel <slug> --json
python -m factory.cli plans --channel <slug>
python -m factory.cli status --channel <slug>
python -m factory.cli gate --channel <slug> --plan-id <plan>
python -m uploader.cli verify --json
python -m factory.cli pause
```

Use `pause` for the emergency stop. A pause blocks new work; it does not cancel a `publishAt` already stored at YouTube. Keep scheduled videos private until YouTube releases them at their approved time. Never print or copy OAuth credentials.

## Creative pipeline findings

A reviewed Academic Short used scene planning and passed technical QC, but its contact sheet repeated the same fixed guide, shelf, and small image window, so it read like narrated slides. The previous Natkhat Short similarly reused one dark haveli background across its five story beats. The renderer already supports scene motion and expressive character rigs, but the Hindi story adapter discarded authored movement and prop cues.

The current unmerged rollout branch changes Pop Info and Evidence Board to use three beat framings, restores a safe allow-list of supported Natkhat animation cues, and gives the next authored haveli Short a brass-key action and a rooftop-night cut. Focused tests passed (72 adapter/continuity/handoff tests; 113 content, workflow-shape, policy, QC, and integration tests). `natkhat-haveli-e4` has now been rendered locally as a 31.667-second 1080x1920 H.264/AAC Short; factory QC passed and five sampled frames were inspected. The key prop, character pose changes, and rooftop-night setting are visible. It remains a local preview; the simple 2D rigs, subjective audio review, and owner editorial approval are still limitations. No YouTube upload or schedule was made.

## Public-repository security and usage

- GitHub reports the repository public; the merged CI/security checks passed. A high-confidence tracked-file scan found no private-key, GitHub-token, Google API-key, or OpenAI project-key patterns.
- The current GitHub API identity reports `push: false`, and Actions secrets/settings endpoints are not available to it. Secret names/values were not read, printed, modified, or rotated. Do not commit credentials to work around the permission limit.
- No Actions quota, runner, or billing failure appears in the inspected run history. Changing repository visibility would not fix the observed late scheduled event; the repository is already public.

## Release verification checklist

For **each channel and each format**, record separately:

1. `schedule` event on `main` and the exact workflow run ID.
2. Both short and long-form job outcomes, including content availability and gate decision.
3. Rendered video, audio, captions, and visual contact-sheet review.
4. Correct channel identity and returned YouTube video ID.
5. YouTube read-back of title, visibility, and actual `publishAt`.
6. Upload ledger entry and duplicate check.
7. Recovery behavior, emergency pause, and any remaining channel-specific limitation.

Do not call X100 production-ready until this evidence exists for all six channel/format combinations and subsequent daily schedule events continue to run.
