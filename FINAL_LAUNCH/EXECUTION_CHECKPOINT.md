# Execution checkpoint — X100 master directive

Updated: 2026-11-23 (after the six-row cloud wave on `218a6d5`)

This file is the recovery point. If the session is interrupted, read this first, then `git status` and
`git log --oneline -5`, and resume from the last row marked complete.

## Current state

| Item | Value |
|---|---|
| Branch | `fix/hindi-framing-caption-clearance` (merged work), working tree clean apart from probe scratch |
| `main` | `218a6d5542e30733e6739e5a93bc46bca3c26e01` |
| Merged this session | #7 (16:9 coverage), #8 (made-for-kids + peak headroom), #9 (caption clearance measured), #10 (portrait composition) |
| Open PRs | #2 `fix/runner-install-robustness` (owner), #4 dependabot |
| Secrets / variables | 0 / 0 |
| Schedules | `academic-biohacker daily`, `natkhat-toons daily`, `nexus-node daily` — all `disabled_manually` |
| Uploads | none attempted. `UPLOAD_ENABLED=false`, `SCHEDULED_PUBLISHING_ENABLED=false`, `PUBLICATION_APPROVAL_REQUIRED=true` |

## Completed phases

| Phase | What was done | Evidence |
|---|---|---|
| P0 audit | Re-read state from Git, Actions, secrets, schedules rather than reports. | `gh run list`, `gh secret list`, `gh api .../workflows` |
| P1 blockers | Plan-lookup errors, gate profiles, pause at the render choke point, `pipefail`, null-safe report, made-for-kids enforcement, true-peak headroom, portrait caption clearance. | PRs #6, #8, #9, #10 |
| P2 cloud production | Six rows dispatched from `main` @ `218a6d5`, all `completed success`. | Runs 45196207861, 45196341328, 45196366254, 45196390881, 45196415411, 45196440363 |
| P2 verification | Four artifacts downloaded and re-hashed locally (three Shorts + Natkhat 16:9); two long-form artifacts could not be downloaded (GitHub egress/network failures) and are evidenced from the run log only. | `FINAL_LAUNCH/FINAL_ACCEPTANCE_MATRIX.md` |
| P3 upload | Upload path audited end to end; two defects fixed. Live upload NOT EXECUTED — no `YT_*` credentials exist. | `FINAL_LAUNCH/PUBLISHING_READINESS.md` |
| P4 public publishing | Not started, correctly. Requires owner approval after P3. | — |
| P5 schedules | Not enabled. Blocked on P3 + owner approval. | workflow states above |

## Tests and checks at this checkpoint

| Check | Result |
|---|---|
| `pytest tests` | 865 passed |
| `pytest tests/factory` (after the composition fix) | 815 passed |
| `python -m tools.capture_goldens --check` | 78 frames, 0 changed, 0 new |
| `python -m tools.workflow_audit` | 7 workflows, 0 findings |
| `python -m tools.dependency_audit` | 0 unaccepted |
| `python -m tools.secret_scan` | 0 findings, staged and full tree |

## Known blockers

1. **YouTube credentials** — zero `YT_*` secrets. Every channel needs `CLIENT_ID`, `CLIENT_SECRET`,
   `REFRESH_TOKEN`. Owner action; the runbook is in `PUBLISHING_READINESS.md`.
2. **nexus-long and academic-long artifact re-hash** — GitHub artifact downloads failed twice for these two
   runs (`HTTP 503 Egress is over the account limit`, then TCP resets). The videos themselves passed QC and the
   gate on the runner. Retry the download later; the runs are green and the artifacts are retained 14 days.
3. **Notification delivery** — no `FACTORY_NOTIFY_WEBHOOK`, so `NullNotifier` reports `delivered: False`.
4. **Plan coverage / quality items** — three-character scenes, eyeline geometry, Natkhat portrait hash drift,
   hand-off body interpenetration, caption font floor. Not required for the first upload; see `TASKS.md`.

## Next exact commands

To re-verify the long-form rows once artifact downloads work:

```
env -u GITHUB_TOKEN gh run download 45196415411 -D <dir>/nexus_long
env -u GITHUB_TOKEN gh run download 45196440363 -D <dir>/academic_long
```

To complete P3 after the owner adds credentials (one channel first):

```
env -u GITHUB_TOKEN gh workflow run production.yml --ref main \
  -f channel=nexus-node -f plan_id=nexus-data-wall \
  -f mode=render+validate+upload -f upload=true
```

Then poll the run and confirm the private video, its channel and its metadata before repeating for the other two
channels.

## Rule for the next session

Do not re-run a completed render to satisfy a documentation gap. Read the run log, then the artifact. Only
re-render when the code changed.
