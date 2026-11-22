# FINAL_LAUNCH / LAUNCH_READINESS.md

What is ready, what is not, and the exact action that changes each "not".

## Ready, verified locally

| Capability | Evidence |
| --- | --- |
| Portrait Short, 32 s | 963 frames, `qc_ok: true`, 171 s wall, fresh build dir |
| Landscape episode, 64.5 s | 1935 frames, 27/27 QC checks, 312 s wall, sha256 `bf93b056…` |
| Pickup + IK + crouch + hand-off | measured contact 2.0 px, ledger transfer, 31 tests, rendered demo |
| Continuity and ownership | `continuity.json` in every episode plus a QC gate; two defects found by tests and fixed |
| Quality gates | 27 technical checks; 24 publishing checks; the gate is enforced on `--execute` |
| Reliability | 11-state job journal, lock, preflight, atomic finalisation, resume |
| Research | `factory/cli research` — real feeds, freshness decay, dedupe, source ledger, 21 tests |
| Security | scans clean, pinning enforced, `main` protected, least-privilege secrets |

## Not ready

| Gap | Why | What changes it |
| --- | --- | --- |
| Cloud run | `produce.yml` is `workflow_call`; `production.yml` is `workflow_dispatch`, which can only dispatch from the default branch, and the default branch does not have it yet | Merge PR #3 (owner) |
| Uploads | 0 repository secrets | Owner adds `YT_<CHANNEL>_{CLIENT_ID,CLIENT_SECRET,REFRESH_TOKEN}` and confirms the OAuth app is "In production" |
| Scheduled production | 3 crons `disabled_manually` | Owner enables them after one successful manual run |
| Code scanning | No analysis configured | Owner enables default code scanning (Settings → Code security) |
| Non-provider secret patterns, validity checks | API accepts the PATCH but the flags stay off | Owner toggles them in the UI |
| 10-minute episode | Benchmark plan was incoherent (repeated pickups) and QC refused it | Author a real 10-minute plan; ≈ 49 min wall at 4.5× real time |
| Hand-off staging aesthetics | Bodies overlap (arm/body proportion) | Torso lean or a longer forearm in the character schema |

## Recommended schedule — targets, not quotas

| Channel | Shorts / week | Long-form / week | Rendering at measured rates |
| --- | --- | --- | --- |
| Nexus Node | 3–5 | 1 if quality permits | ≈ 5 × 157 s + 312 s ≈ 18 min |
| Academic Biohacker | 2–3 | 1 if quality permits | ≈ 3 × 157 s + 312 s ≈ 13 min |
| Natkhat Toons | 3–5 | 1 if quality permits | ≈ 5 × 157 s + 312 s ≈ 18 min |

About 49 minutes of rendering per week, comfortably inside a hosted runner's limit. The binding
constraint is editorial, not compute: a video whose sources are unverified or whose QC fails is not
published, and a missed slot is acceptable where a bad video is not.
