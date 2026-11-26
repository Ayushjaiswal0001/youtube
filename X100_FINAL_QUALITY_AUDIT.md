# X100 final quality audit

Audit date: 2026-11-26
Repository: Ayushjaiswal0001/youtube, checkout D:\X100-youtube
Protected main: b16c4b5fd0d8cd6731d11dde40fc3a7d49b52d8f
Reliability/content candidate: 7d6ffe0 on codex/fix-joblock-ownership; not merged

This report distinguishes live GitHub evidence from local tests and preserved sample artifacts. All media listed below is local under D:\X100-youtube\audit-artifacts and remains unmodified.

## Repository, PR, and CI

PR #22, head 6c52d38ac48963f9a37d1aadd5139e0e3453d768, merged 2026-11-25 into main as b16c4b5fd0d8cd6731d11dde40fc3a7d49b52d8f. Latest main CI run 45705546332 and security run 45705546316 completed successfully on that merge SHA. CI evidence includes factory, uploader Python 3.11/3.12, workflow permission/pinning, dependency audit, Gitleaks, and secret/history scans.

A separate local candidate commit 7d6ffe0 fixes JobLock ownership and corrects authored topic source/copy. CLI push and connected GitHub-app write both returned HTTP 403, so the branch is not remote and no candidate PR/CI exists yet. PR #2 remains open on a stale base and was not modified.

## Local software checks

- Full suite: 1,469 passed, 1 skipped, 5 subtests passed in 1,054.07 seconds, Python 3.12.7 on Windows. Isolated temporary state/build/log roots were used.
- Focused lock, orchestration, and workflow regression run: 114 passed, 1 skipped in 18.97 seconds.
- After source/copy corrections, content planning, availability, lookup, creative QC, and long-form planning: 78 passed in 6.04 seconds.
- Python compilation and git diff whitespace checks passed.
- Workflow auditor: 7 workflows, 0 findings.
- Secret scanner: 14 rules, 0 findings, none at or above high.
- Gitleaks redacted working-diff scan: 0 leaks.
- Dependency audit: 0 blocking, 0 accepted, 0 findings.
- The local full suite ran before the content-only JSON correction; the focused content suite ran after that correction. Branch CI must validate the final PR tree. POSIX flock coverage is skipped locally on Windows.

## Actual video, frame, and audio checks

Seven preserved artifacts were inspected: six channel/format examples and an additional Nexus Short. FFprobe confirmed H.264 video at 30 fps, AAC stereo at 44.1 kHz, and zero audio start offset. FFmpeg fully decoded all seven with exit code 0. At blackdetect duration >=1 second and pixel threshold 0.10, no black events were found. At freezedetect threshold -60 dB and duration >=2 seconds, no freeze events were found.

| Artifact | Duration | Geometry | AAC integrated loudness | AAC true peak | SRT cues |
| --- | ---: | --- | ---: | ---: | ---: |
| Academic horizontal, long-academic-study-protocol | 218.933 s | 1920x1080 | -14.36 LUFS | -2.12 dBTP | 94 |
| Academic Short, academic-post-meal-walk | 38.366 s | 1080x1920 | -14.22 LUFS | -2.31 dBTP | 17 |
| Natkhat horizontal, natkhat-haveli-stage-e1 | 64.500 s | 1920x1080 | -14.04 LUFS | -1.44 dBTP | 21 |
| Natkhat Short, natkhat-haveli-e1 | 32.100 s | 1080x1920 | -14.02 LUFS | -1.40 dBTP | 10 |
| Nexus horizontal, long-nexus-power-grid | 214.067 s | 1920x1080 | -14.13 LUFS | -2.34 dBTP | 97 |
| Nexus Short, nexus-data-wall | 41.966 s | 1080x1920 | -14.22 LUFS | -2.55 dBTP | 18 |
| Additional Nexus Short, nexus-eval-problem | 32.667 s | 1080x1920 | -14.43 LUFS | -2.44 dBTP | 16 |

Every measured encoded AAC true peak is below the project -1 dBTP ceiling. Integrated loudness ranges from -14.43 to -14.02 LUFS. Audio and video durations differ by at most 0.035 seconds; all audio starts at 0.000 seconds. A -50 dB / 0.8-second silence scan found three 0.800–0.817 second intervals in the Natkhat horizontal audio. These may be dialogue pauses; they were not listened to. No subjective listening check was available, so voice completeness, naturalness, music balance, and abrupt audible endings are not certified.

Each video has a local UTF-8 SRT. All seven parsed with no malformed blocks, no overlapping cues, and the last cue ends before video end. Maximum displayed line length is 46 characters for English samples and 38 for Natkhat. Five representative frames per video were sampled from preserved contact sheets; no obvious crop, text overflow, missing asset, or subtitle-band placement defect was seen. This is a sample check, not complete frame-by-frame review. Academic horizontal cards have dense small text in places. Natkhat uses a deliberately dark haunted setting and repeated stage backgrounds. No child-safety certification was performed. Burned-in captions and local SRT do not establish the presence of YouTube caption tracks.

The seven videos total 133,280,859 bytes. A machine snapshot during the audit showed 7.88 GiB total RAM and 1.70 GiB free, and D: had 24.04 GiB free of 30.66 GiB. This is a host-capacity snapshot, not a measured per-render peak. Peak CPU/RAM, exact contention latency, and exact crash-recovery time were not measured.

## Editorial and source audit

The candidate updates the topic bank and matching batch copies with direct evidence and narrower claims:

- Post-meal walking: a 10-person acute crossover trial and a 41-person type 2 diabetes timing trial; no supplement comparison or treatment promise.
- Circadian light: direct studies of bright morning light in a defined delayed-sleep-phase group and melanopic evening display exposure in 72 healthy men; no universal ten-minute result or blanket filter claim.
- Sitting breaks: a 24-person type 2 diabetes activity-break trial and a separate negative result in healthy sedentary men with central obesity; no universal two-minute schedule.
- Open weights: model-card documentation and Stanford HELM; no unsupported claim that open models follow closed models by a fixed number of months.
- On-device inference: current MLPerf Mobile and model-compression documentation; removes unqualified privacy and hardware-throughput promises.
- Data-centre power: IEA plus a direct 2026 Berkeley Lab grid-connection report; the constraint is described as region- and project-dependent.
- Robot video: direct 2025 preprint, explicitly scoped as one research result rather than a general capability.
- Data-wall forecast: a direct 2024 analysis and related preprint; projections are identified as conditional estimates.

Two preserved videos predate the copy/source corrections and were not rewritten: academic-post-meal-walk retains the supplement contrast, and nexus-data-wall has a title/hook that states a forecast as a present shortage. Neither should be released without a fresh render from corrected copy and another editorial check. This audit does not alter or delete the preserved audit artifacts.

## Channel and content coverage

All six channel/format combinations returned an available plan in an isolated read-only query. The current content bank remains short:

| Channel | Unused Short topics | Authored horizontal plans | Editorial/capacity note |
| --- | ---: | ---: | --- |
| Academic Biohacker | 2 | 1 | Minimum +5 Shorts and +6 horizontal plans for seven unique daily pairs |
| Nexus Node | 4 | 1 | Minimum +3 Shorts and +6 horizontal plans for seven unique daily pairs |
| Natkhat Toons | 6 across Haveli and Jungle | 1 | Minimum +1 Short and +6 horizontal plans; current horizontal sample is only 64.5 seconds and needs a substantial authored story |

These are arithmetic minimums for a seven-day bank at one Short plus one horizontal episode daily; no additional content was generated. Available local work does not prove that GitHub or YouTube state has no reservation, duplicate, or pending release.

## Publishing and operational verification

At the time of the audit, all three daily workflows were disabled_manually; the manual production workflow was active but idle. No Actions runs were in progress. Main CI/security evidence is historical to the verified main SHA; the new candidate PR has not yet run. The local pause check returned paused=false, scope=none. A GitHub Actions variables API read returned 403, so runner/account pause state is owner-dependent.

Historical manual production run 45625058307 completed render/resume in about 16m31 and the full job in about 17m56; its upload steps were skipped. A separate prior measurement recorded 3,008 seconds for an 11-beat horizontal render. These are different measurements. Configured job budgets are 60 minutes for Shorts and 120 minutes for horizontal videos. No video was uploaded or scheduled in this audit. No YouTube live channel identity, stored publishAt, or pending-release read-back was performed.

## Limitations and verdict

The local samples pass the numeric geometry/audio/caption checks above, but subjective audio review, full-resolution frame review, child-safety certification, every-plan editorial review, and YouTube live schedule proof remain absent. The authored bank cannot support the current daily two-format cadence beyond a small number of days. JobLock is fixed only on candidate commit 7d6ffe0; protected main still needs review, merge, and green CI.

See X100_FINAL_PROJECT_COMPLETION_REPORT.md for the A-T completion report and X100_FINAL_ACTIVATION_HANDOVER.md for the owner-controlled next steps.
