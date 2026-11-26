# X100 final system architecture

Status reviewed 2026-11-26. Verified repository: Ayushjaiswal0001/youtube at D:\X100-youtube. Protected main is b16c4b5fd0d8cd6731d11dde40fc3a7d49b52d8f. PR #22 is merged. The focused reliability/content candidate is on PR #23 from `codex/fix-joblock-ownership`; source commits are 7d6ffe07c59300d52fa6d1d07d221c67d32b6c97 and 528ec22943c896a2626b4877ddaaa1f035480534. The initial CLI 403 was traced to a read-only injected token and recovered using an existing authorized keyring identity. Main remains unchanged; independent review, latest-head CI/security, merge, and owner activation remain pending.

## System boundary

X100 builds Shorts and horizontal episodes for Nexus Node, Academic Biohacker, and Natkhat Toons. Python selects authored content, generates narration and captions, renders video, applies technical/editorial gates, packages artifacts, and can request private YouTube uploads and timed releases when authorized. Actual public scheduled delivery has not been proven. The configured path has no paid API dependency; it still relies on GitHub Actions, YouTube quotas, and external runtimes.

## Components

| Area | Responsibility | Main paths |
| --- | --- | --- |
| Configuration | Channel identity, format, schedule policy, paths, language | channels/*.json, factory/config.py, uploader/config.py |
| Content | Topic banks, long plans, ordered Natkhat episodes, availability | content/topics/*.json, content/longform/*.json, content/series/*, factory/content/* |
| Script and media | Script shaping, voice, word timing, local SRT, rendering | factory/content/script.py, factory/media/*, studio/pipeline/* |
| State and recovery | Job journal, run history, plan state, pause flags, duplicate ledger | factory/state.py, factory/orchestrator.py, factory/controls.py, pipeline_state/ |
| Lock ownership | One process per channel/plan in a shared filesystem; heartbeat and recovery | factory/reliability.py |
| QC and packaging | Geometry, duration, loudness, captions, creative checks, manifest, release gate | factory/qa/*, tools/* |
| YouTube boundary | Channel identity, private upload, schedule request and metadata read-back | factory/publisher.py, uploader/* |
| CI and orchestration | Daily/manual entrypoints, per-format concurrency, security/test jobs | .github/workflows/produce.yml, production.yml, ci.yml, security.yml |

## Production path

    channel policy + plan
      -> pause and availability checks
      -> lock acquisition before shared journal changes
      -> script, voice, rendering and captions
      -> technical QC and creative checks
      -> manifest and publishing gate
      -> channel identity and private upload, only when authorized
      -> publishAt request and YouTube status read-back

A computed release time is a request value, not proof of a stored schedule. The uploader requires read-back verification in code; the audit did not perform a live YouTube upload or inspect live pending schedules.

## Ownership and concurrency

JobLock now takes an OS-held byte-range lock on a stable .guard file: flock on POSIX and LockFileEx on Windows. A unique owner token identifies each acquisition. The heartbeat writes diagnostic metadata every 30 seconds in production; heartbeat age cannot override an OS lock. Acquisition happens before the shared job journal is read or changed. The renderer checks lock health before packaging and before READY_TO_PUBLISH. False acquisition raises LockBusy without invoking the renderer or mutating the journal.

GitHub Actions serializes production jobs by channel and format and does not cancel the active render. Short and horizontal work remain independent. GitHub concurrency allows one running and one pending run per group; it is not an unbounded queue. The OS lock protects concurrent processes sharing the same filesystem. Correctness on a network filesystem depends on its lock implementation and was not separately tested.

## Channel and format paths

| Channel | Short | Horizontal |
| --- | --- | --- |
| Nexus Node | English technical cards, 1080x1920 | English cards and diagrams, 1920x1080 |
| Academic Biohacker | English evidence briefs, 1080x1920 | English evidence cards, 1920x1080 |
| Natkhat Toons | Hindi character animation, 1080x1920 | Hindi stage renderer, 1920x1080 |

Natkhat configuration forces madeForKids=true. That is a platform setting, not a full child-safety certification.

## Evidence boundary

Seven preserved local videos plus two corrected derivatives were probed and fully decoded: six channel/format examples, one additional Nexus Short, and corrected Academic post-meal and Nexus data-wall Shorts. The originals remain unchanged; corrected derivatives are local-only under `audit-artifacts/corrected-2026-11-26/`. Geometry, frame rate, encoded AAC, silence/black/freeze thresholds, and SRT timing are summarized in X100_FINAL_QUALITY_AUDIT.md. These are sampled artifacts, not proof of every future plan. Contact sheets were sampled for the derivatives; no audio listening review or live scheduled release verification was performed.

## Operations and follow-up

- Current production evidence and final verdict: X100_FINAL_PROJECT_COMPLETION_REPORT.md
- Lock design and process tests: X100_LOCK_RELIABILITY_REPORT.md
- Operator procedures and stop commands: X100_PRODUCTION_OPERATIONS_GUIDE.md
- Owner-controlled preflight and activation boundary: X100_FINAL_ACTIVATION_HANDOVER.md
- Remaining limits: X100_KNOWN_LIMITATIONS.md
- Current closure snapshot: X100_FINAL_PRODUCTION_CLOSURE_REPORT.md
