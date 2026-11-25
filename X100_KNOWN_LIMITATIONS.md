# X100 known limitations

Verified or documented limits as of 2026-11-26. See [quality audit](X100_FINAL_QUALITY_AUDIT.md) and [activation handover](X100_FINAL_ACTIVATION_HANDOVER.md) for evidence boundaries.

## YouTube/account limits

- No real public scheduled release has been validated. The uploader now reads `publishAt` back and fails if missing or different, but the first scheduled activation is still an integration test.
- YouTube scheduled videos are expected to be private before `publishAt`; retain a stop/Studio procedure because this workflow must not assume release modification is permitted.
- Earlier observed `videos.update` permission failures mean scheduled-release edits and caption-track attachment may need additional OAuth scope. Captions in `captions.srt` or burned into frames do not prove a separate YouTube caption track exists.
- Academic Biohacker's custom thumbnail previously received HTTP 403 pending channel verification. Expect YouTube's auto-selected frame until the owner verifies the channel.
- OAuth secret values must remain unread and unlogged. Runtime account checks must use approved operations and display only status/identity outcomes.

## Content and product limits

- The current content bank has one horizontal authored plan per channel. Nexus and Academic each have four unused topic Shorts. Natkhat has six authored Shorts remaining across three Haveli and three Jungle episodes. Current plan availability can change when runs consume or reserve plans.
- At one Short plus one horizontal episode per channel per day, the authored horizontal bank covers one day per channel. Maintaining the cadence beyond that requires at least one additional authored horizontal episode per channel per additional day.
- Natkhat's available horizontal episode rendered to 64.5 seconds. Its geometry and gates pass, but it is not substantial long-form editorial content.
- Natkhat stage samples keep the same setting and use pose/dialogue changes; visual variety is more limited than the English card path.
- Some topic-bank source fields are search URLs or institution homepages rather than direct papers/reports. The Nexus evaluation plan's absolute predictive claim was softened on the current fix branch and its sources now link to a primary study and Stanford HELM; the remaining bank still needs claim-by-claim source review.
- Creative QC is not uniform across every renderer. Technical QC and publishing gates are broader, but a passing numeric gate is not a complete human review of factual correctness, art quality, age suitability, or accessibility.

## Operations/evidence limits

- GitHub Actions daily publishing workflows are disabled. No activation is authorized by this document.
- Merge-commit CI exposed a clock-dependent test failure. The local 1,451-test suite passed before the security-auditor regression tests were added; those three added tests passed separately. Final branch CI must run the complete current suite before merge.
- A Standard security review found a high-confidence shell-injection finding in the pre-fix workflow snapshot. The focused branch contains a source fix and stronger multiline workflow auditing; its security checks must pass before merge. The review snapshot predates the fix, no independent reviewer was assigned, and no OAuth values were inspected.
- Historical QC reports describe previous artifacts. Only the artifacts enumerated in the final quality audit were downloaded and independently decoded/measured in this audit.
- Rendering and TTS depend on existing runner/runtime components and service availability. The documented ₹0/month target excludes paid APIs but does not guarantee unlimited free quota, stable external services, or zero machine/energy cost.
- Current runtime pause flags, live YouTube pending schedules, and account permissions were not directly checked in this audit.
