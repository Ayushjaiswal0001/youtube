# X100 known limitations

Snapshot date: 2026-11-26. This file supersedes older status snapshots that described PR #22 as open. Main is b16c4b5fd0d8cd6731d11dde40fc3a7d49b52d8f; JobLock and editorial corrections are on candidate commit 7d6ffe0 and are not merged.

## Reliability and release limits

- Main has not yet received the final JobLock single-owner repair. The candidate exists only in the local branch because both CLI and connected GitHub write calls returned HTTP 403. It needs authorized publication, an independent review, POSIX CI, successful final PR CI/security, and a protected merge.
- Local Windows LockFileEx coverage passed. POSIX flock coverage was skipped locally and must run on Ubuntu CI.
- No physical machine reboot or cross-host shared-filesystem lock test was performed. Network-filesystem correctness depends on its locking semantics.
- Corrupt legacy metadata with uncertain owner state fails closed and may require owner investigation.
- Exact lock contention latency and crash-recovery time were not measured.
- The current manual production workflow is enabled, although idle. The three daily channel workflows are disabled. No workflow was dispatched in this audit.

## YouTube/account limits

- No real YouTube upload or stored publishAt read-back was performed. A successful dry-run/render is not a scheduled release.
- The historical manual production run 45625058307 skipped upload steps.
- Account identity and pending schedules were not checked. The channel JSONs do not establish live account ownership. GitHub variables API access returned 403; runner-level pause and channel/account status remain owner-dependent.
- OAuth secret values and grants were not read or changed.
- Local SRT files and burned-in subtitles do not establish separate YouTube caption tracks. Prior reports documented a custom-thumbnail verification restriction for Academic Biohacker; the owner should verify its current status before relying on custom thumbnails.

## Media/editorial limits

- Seven preserved sample videos passed full FFmpeg decode, specified black/freeze checks, numeric encoded AAC loudness/true-peak checks, and local SRT structural/timing checks.
- No subjective listening check was available. Three sub-0.82-second silence intervals were detected in one Natkhat horizontal sample and were not auditioned.
- The seven preserved originals had five frames sampled per artifact; the two corrected derivatives had seven-panel contact sheets sampled. Neither check is a complete frame-by-frame visual review.
- The preserved Academic post-meal Short still contains a supplement comparison, and the preserved Nexus data-wall Short presents a conditional forecast too categorically. Corrected derivatives exist under `audit-artifacts/corrected-2026-11-26/build/` and passed automated checks plus sampled contact-sheet review. Do not release the preserved versions; owner editorial review of the derivatives remains pending.
- Natkhat samples are child-oriented animation in a haunted setting, but no formal child-safety certification was performed.
- One horizontal plan exists per channel. Current 64.5-second Natkhat horizontal sample is a short story, not substantial long-form coverage.
- Current unused topic bank: 2 Academic Shorts, 4 Nexus Shorts, 6 Natkhat Shorts. At one Short and one horizontal per channel per day, a seven-day unique bank needs Academic +5 Shorts/+6 horizontal plans, Nexus +3/+6, Natkhat +1/+6; Natkhat also needs a longer authored story. This is a minimum coverage calculation, not generated content.

## Performance, cost, and service limits

- Historical render measurements fit the current 60-minute Short and 120-minute horizontal workflow budgets, but were made on different runs: 16m31 render/resume in manual run 45625058307 versus a separate 3,008-second 11-beat horizontal measurement.
- Peak CPU and per-render memory, exact recovery time, and exact lock contention latency were not measured. The 133,280,859-byte total is the size of seven preserved sample trees; the two corrected MP4s total 19,688,365 bytes.
- The ₹0/month target excludes paid APIs, but does not promise unlimited free GitHub Actions/YouTube quota, uninterrupted external services, or zero machine and energy cost.
