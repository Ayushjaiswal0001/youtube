# X100 Operations Guide

**Live snapshot: 2026-11-28 00:39 IST.** Refreshed against `Ayushjaiswal0001/youtube`, GitHub Actions, the YouTube API, and the recorded workflow artifacts. This guide separates enabled automation from verified publishing.

## Current operational status

- Repository visibility is already **public**; no visibility change was needed. Main is `3fa3c981a1dbfc0248730a9a558b0d5da212948b` (PR #31). Post-merge CI run `46033672111` and security run `46033672255` passed.
- All three daily workflows are enabled in GitHub: Academic `425309827`, Natkhat `425309829`, Nexus `425309830`.
- Main contains the `:29` UTC triggers. These are trigger times; YouTube publication remains scheduled for noon, 18:00, and 20:00 IST.
- **No daily `schedule` run has been observed after PR #31 merged.** The most recent real schedule event is Academic run `46012727812`, created on pre-merge main `2ea73be` at 19:35 IST on Nov 27. Rendering and technical QC passed; the publishing policy reported `release_window_missed` and skipped credential export and upload. The late-run safety window was not weakened.
- Run `46012727812` received the scheduled wrapper inputs (`upload=true`, `release=auto`). The short and long jobs were late by 27,390s and 28,340s, respectively, exceeding the configured 90-minute grace. The policy therefore returned `ready=false` with `release_window_missed`; the reusable workflow's `ready == 1` condition skipped credential export before reading credentials, then correctly skipped identity verification and upload. This was a late scheduled event, not a missing schedule event or demonstrated credential failure. The nine expected Actions secret names exist, but their values were not inspected. Local OAuth identity checks had previously matched all three configured channels.
- At 00:20 IST on Nov 28, all three GitHub workflow IDs remained `active`; their recent run history contained no Nov 28 schedule event yet, which is expected before today's trigger times.
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

The only YouTube release with artifact evidence of an approved stored schedule is Academic Short [`CPHaFFnSkuw`](https://www.youtube.com/watch?v=CPHaFFnSkuw). Manual workflow run `45949021636` (`workflow_dispatch`, older main `4fed999`) uploaded it private and read back `publishAt=2026-11-27T06:30:00Z` (12:00 IST). YouTube now reports it public with `publishedAt=2026-11-27T06:30:21Z`; its current `publishAt` field is absent because the scheduled release completed. This proves one scheduled Shorts release, **not** scheduled automation.

The run artifact records the video ID, clear duplicate check, upload, and stored schedule. The separate local uploader ledger does not contain this ID; keep that discrepancy open until the ledger is reconciled without uploading again. A custom-thumbnail call returned YouTube 403 for this account. No thumbnail retry or credential change was made. Analytics access is limited; one view and zero likes are too small a sample to judge engagement.

At 00:22 IST on Nov 28, a read-only scan paginated each channel's full uploads playlist and matched connected channel identity. It covered 64 Academic, 64 Natkhat, and 559 Nexus videos; none currently has a future `publishAt`. Recent project uploads confirmed directly with YouTube are:

| Channel | Video ID | Title | Duration | Visibility | Current `publishAt` |
| --- | --- | --- | ---: | --- | --- |
| Academic | `CPHaFFnSkuw` | Walk After Eating | 48s | public | absent; completed schedule documented above |
| Academic | `O2YiFi0f_Ts` | Your Brain's Night Shift | 39s | private | absent |
| Natkhat | `derJO8hBnjo` | चीकू और गप्पू: हवेली की पहली रात | 33s | private | absent |
| Nexus | `ZK-AMW8Lw-U` | AI Training Data: A Forecast, Not a Countdown | 46s | public | absent |
| Nexus | `UuQKJ3jspKE` | AI Is Leaving the Chat | 39s | private | absent |

All five confirmed project uploads are under one minute; no long-form release is verified for any channel. The local uploader ledger contains the other four IDs but still omits Academic ID `CPHaFFnSkuw`. No upload or schedule has been created during this continuation.

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

PR #32 varies Pop Info and Evidence Board framing across beats, restores a safe allow-list of authored Natkhat motion and prop cues, and gives the next Haveli Short a brass-key action and rooftop-night cut. Fresh local Academic (`academic-brain-wash`, 38.233 seconds) and Nexus (`nexus-data-wall`, 45.433 seconds) renders both passed factory QC as 1080x1920 H.264/AAC Shorts. Five-frame contact sheets show changing Pop Info callouts and character-guide framing for Academic and a pinned corkboard, red-string links, magnifier, and varied evidence cards for Nexus. Their audio QC reported -14.5 LUFS/-2.46 dBTP with 0.013s AV length delta and -14.2 LUFS/-2.40 dBTP with 0.003s delta, respectively. Both are local previews.

The local Natkhat `natkhat-haveli-e4` preview is 31.667 seconds, 1080x1920 H.264/AAC, and passed factory QC. A one-second timeline contact sheet shows the brass-key action, expressive pose changes, and rooftop-night cut; all ten Hindi subtitle beats are represented, and a local Whisper base transcription recovered the key story points. Automated transcription and audio metrics do not replace a human listening pass. Characters still use simple 2D rigs. No YouTube upload or schedule was made.

## Public-repository security and usage

- GitHub reports the repository public; the merged CI/security checks passed. A high-confidence tracked-file scan found no private-key, GitHub-token, Google API-key, or OpenAI project-key patterns.
- The active GitHub account is the write-enabled repository owner `Ayushjaiswal0001`; it pushed PR #32. All nine expected per-channel Actions secret names exist. Secret values were not read or printed, and no secret, OAuth credential, permission, or production setting was changed.
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
