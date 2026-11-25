# X100 final system architecture

Status basis: GitHub `main` at `01f3abd4078abca30eabbd6822139130121a72d7`; reviewed 2026-11-26. This describes implemented paths and their test/artifact evidence, not a promise that production workflows are enabled.

## System boundary

X100 creates a Short and a horizontal episode for each of three configured YouTube channels. GitHub Actions coordinates work; Python generates scripts, narration, artwork/video, captions, package manifests, quality checks, and (only when authorized) private YouTube uploads and scheduled releases. It uses no paid API in the documented configuration. Real scheduled public release has not yet been validated.

## Main components

| Component | Responsibility | Main files |
| --- | --- | --- |
| Channel and runtime configuration | Validates identities, language, format, profile, publication policy, paths, and release time | `channels/*.json`, `factory/config.py`, `uploader/config.py` |
| Content planning | Selects unused topic-bank entries, authored long-form plans, or Natkhat series episodes; checks availability and order | `content/topics/*.json`, `content/longform/*.json`, `content/series/natkhat-toons.json`, `factory/content/*`, `factory/cli.py` |
| Script and voice | Builds channel-language scripts, voices, word timings, descriptions, tags, and local SRT captions | `factory/content/script.py`, `factory/media/tts.py`, `factory/media/captions.py` |
| Rendering | English plate/card engine; Hindi character/stage renderer; horizontal and vertical profiles | `factory/media/*`, `studio/pipeline/*`, `studio/animation/*` |
| State and recovery | Run ledger, resumable jobs/scenes, locks, pause flags, upload history and duplicate protection | `factory/state.py`, `factory/orchestrator.py`, `factory/controls.py`, `pipeline_state/` |
| Quality and packaging | Technical QC, creative QC when supported, manifest generation, publishing gate | `factory/qa/*`, `tools/*` |
| YouTube boundary | Channel identity checks, credentials, private upload, upload ledger, schedule read-back | `factory/publisher.py`, `uploader/*` |
| CI and orchestration | Independent short/long jobs, content availability, policy checks, artifact retention and summaries | `.github/workflows/produce-*.yml`, `.github/workflows/produce.yml` |

## Production path

```text
channel policy + plan bank
          │
          ├─ availability and pause checks
          ├─ plan/script/voice
          ├─ render + captions + thumbnail
          ├─ technical QC ─ manifest ─ publishing gate
          └─ package ─ channel identity ─ private upload
                                      └─ publishAt request ─ YouTube status read-back
```

Each channel workflow starts distinct `short` and `long` jobs. A plan exhaustion is a content gap and skips downstream production; a blocked plan or failed gate is a run failure. Upload authorization combines the workflow input, channel policy, content availability, credentials, identity check, gate, and code-level environment guard. Scheduling has a separate `FACTORY_ALLOW_SCHEDULE` guard. `allow_public_upload` is false in all channel JSON files.

The file lock checks a same-host process without signaling it. POSIX uses the zero-signal PID probe; Windows uses a waitable process handle because `os.kill(pid, 0)` generates a console Ctrl+C event there. Unknown Windows process-access results keep the lock live, preferring a blocked run over stealing a possibly active lock.

After an upload with `publishAt`, `verify_schedule()` refreshes the API client and reads status back. A missing, mismatched, or unreadable release time fails closed; it is not reported as verified. The uploaded video remains private if scheduling did not take. This has been exercised with mocks; YouTube's behavior on a real scheduled activation remains unproven.

## Formats and channel-specific renderer

| Channel | Short | Horizontal path | Identity constraints |
| --- | --- | --- | --- |
| Nexus Node | English system/AI plates, 1080×1920 | English card renderer, 1920×1080 | Dark navy technical diagrams and data plates |
| Academic Biohacker | English evidence briefs, 1080×1920 | English card renderer, 1920×1080 | Evidence-first health/neuroscience; claims need specific sources and appropriate qualifications |
| Natkhat Toons | Hindi character animation, 1080×1920 | Hindi stage renderer, 1920×1080 | Chiku/Gappu continuity; made-for-kids is forced true |

Representative downloaded GitHub Actions artifacts were independently probed and decoded for both formats on all three channels. The Natkhat 16:9 sample is 64.5 seconds: technically valid for the configured horizontal render path, but too short to represent substantial long-form content.

## State transitions and recovery

The factory records job state and run history under `pipeline_state/`, and outputs under `build/<channel>/<plan>/` (the Hindi path may include a channel prefix). `resume` reuses completed work and regenerates missing/invalid render fragments. The duplicate ledger keys uploads by artifact hash, while the scheduled-release guard is scoped per plan so two formats may share a channel release instant. Cleanup is dry-run by default and excludes active or unreleased work.

## Entry points

- Operator commands and emergency controls: [X100_PRODUCTION_OPERATIONS_GUIDE.md](X100_PRODUCTION_OPERATIONS_GUIDE.md)
- Current supported limits: [X100_KNOWN_LIMITATIONS.md](X100_KNOWN_LIMITATIONS.md)
- Current release evidence and scorecard: [X100_FINAL_PRODUCTION_CLOSURE_REPORT.md](X100_FINAL_PRODUCTION_CLOSURE_REPORT.md)
- Prior implementation detail (dated historical report): [X100_POST_MERGE_PRODUCTION_READINESS_REPORT.md](X100_POST_MERGE_PRODUCTION_READINESS_REPORT.md)
