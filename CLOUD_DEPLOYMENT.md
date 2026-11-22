# Cloud deployment

Status: **prepared, not executed.** No GitHub-hosted runner has produced a video yet. This document
records exactly what exists, what it needs, and what is blocking the first real run.

## What runs where

| Stage | Local | GitHub-hosted runner |
| --- | --- | --- |
| Plan / script / story | yes | yes (same CLI) |
| Portrait 9:16 render | yes | not yet executed |
| Landscape 16:9 render | yes | not yet executed |
| QC + publishing gate | yes | not yet executed (CI runs the unit tests only) |
| Upload | gated, never executed in CI | not yet executed; 0 repository secrets configured |

The same entry point is used in both places:

    python -m factory.cli preflight --channel <channel>
    python -m factory.cli resume    --channel <channel> [--plan-id <id>] [--format shorts|long]
    python -m factory.cli validate  --channel <channel> [--plan-id <id>]
    python -m factory.cli gate      --channel <channel> [--plan-id <id>]
    python -m factory.cli ops       --channel <channel>

There is no runner-specific code path. The workflow calls those commands and nothing else.

## Workflows

| File | Trigger | Purpose |
| --- | --- | --- |
| `ci.yml` | push, PR | uploader + factory test suites on Linux |
| `produce.yml` | `workflow_call` | one channel: preflight → resume/render → QC → gate → manifest → (upload) |
| `production.yml` | `workflow_dispatch` | manual interface: channel, mode, plan, format, upload |
| `produce-<channel>.yml` | `schedule` (disabled), `workflow_dispatch` | per-channel daily entry point |

All three `produce-<channel>.yml` schedules are currently **disabled_manually** (`gh workflow list
--all` reports `disabled_manually` for all three), so nothing runs on a timer. They were disabled by
the owner, not by this work, and must stay that way until publishing is authorized.

`produce.yml` enforces the stage boundaries in YAML *and* in code:
`UPLOAD_ENABLED=false`, `SCHEDULED_PUBLISHING_ENABLED=false`, `PUBLICATION_APPROVAL_REQUIRED=true` are
set job-wide; the upload step needs `inputs.upload`, existing secrets, and a passing publishing gate.

## What the first cloud run needs

1. **A workflow on the default branch.** `workflow_dispatch` only dispatches from `main`:

       HTTP 404: workflow production.yml not found on the default branch
       (https://api.github.com/repos/Ayushjaiswal0001/youtube/actions/workflows/production.yml)

   Reproduced on 2026-11-21 from `feat/landscape-16x9`. This is the hard blocker: the workflows exist
   only on the feature branch, so no dispatch is possible until PR #3 (and #2) are merged by the owner.
2. **Channel secrets**, if uploads are ever wanted. `gh api repos/.../actions/secrets` reports
   `total_count: 0` - no `YT_*` secret exists. Uploads are therefore impossible today, which is the
   intended state.
3. **OAuth app publishing status.** Not verifiable from here; see SECURITY_AND_DEPLOYMENT.md.

## Runner-side assumptions that remain unproven

These are the things a real run would test, and none of them has been tested:

* PyCairo builds from source against the runner's `libcairo2-dev`.
* Edge-TTS can reach its endpoint from a runner IP.
* The Devanagari font loads and shapes correctly on Ubuntu (preflight checks loadability, not shaping).
* Headless Chrome canvas capture works (only needed by the portrait card renderer).
* A long-form 16:9 render fits inside `timeout-minutes: 60`. Locally a 64.5 s episode takes 250-278 s
  on an i5-10310U; a runner is typically 1.5-2.5x slower, which is still inside the limit, but that is
  an extrapolation, not a measurement.

## Local substitution until then

Everything above runs locally against the same commands, with the same state layout:

    export FACTORY_BUILD_DIR=<dir>/build FACTORY_STATE_DIR=<dir>/state
    python -m factory.cli preflight --channel natkhat-toons
    python -m factory.cli render --channel natkhat-toons --plan-id <plan> --format long
    python -m factory.cli gate   --channel natkhat-toons --plan-id <plan>
    python -m factory.cli ops    --channel natkhat-toons
