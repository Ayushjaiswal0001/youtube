# Operations runbook

## Daily, hands-off (once the crons are re-enabled)

Nothing to do. Each channel's workflow runs preflight, resumes or renders, validates, gates and
packages. If QC or the gate fails, the run fails and `GITHUB_STEP_SUMMARY` says which check failed.

## Daily, by hand (today's mode)

    python -m factory.cli ops                       # what is running, ready, blocked
    python -m factory.cli preflight --channel X     # is this machine able to finish the job?
    python -m factory.cli resume  --channel X --plan-id Y [--format long]
    python -m factory.cli gate    --channel X --plan-id Y
    python -m factory.cli publish --channel X --plan-id Y            # dry run, prints the verdict
    python -m factory.cli publish --channel X --plan-id Y --execute \
        --confirm-channel X                                          # needs FACTORY_ALLOW_UPLOAD=1

## Reading a failure

| Symptom | Where to look | Usual cause |
| --- | --- | --- |
| `preflight failed: disk:build` | preflight output | the build root has less than the reserve free |
| `lock ... is held by another job` | `pipeline_state/locks/` | a concurrent run, or a lock left by a killed run (stale after 900 s) |
| `QC failed` | `build/<channel>/<episode>/qc.json` | a real render defect; the failing check names it |
| `publishing gate BLOCKED` | `build/<channel>/<episode>/publish_gate.json` | manifest missing, framing evidence missing, or media measured wrong |
| `no scenes matched` | stderr | a `--scenes` filter that selects nothing |
| `TTS` errors | stderr, `studio/intermediate/` | no network, or a voice name the engine does not know |

## Job states

`QUEUED → PREFLIGHT → GENERATING → RENDERING → VALIDATING → PACKAGING → READY_TO_PUBLISH →
PUBLISHING → PUBLISHED`, with `FAILED` and `RECOVERABLE` reachable from any active state. Records live
in `pipeline_state/jobs/<channel>_<plan>_<date>/journal.jsonl` with an atomic `job.json` snapshot.

## Publishing

Never publish from a render. The sequence is render → QC → gate → (approval) → upload, and the gate is
enforced inside `publish_episode`, not only in the workflow. `FACTORY_ALLOW_UPLOAD=1` and
`--confirm-channel <slug>` are both required; scheduling additionally needs `FACTORY_ALLOW_SCHEDULE=1`.
