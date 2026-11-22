# 02 — CLOUD PRODUCTION

**Status: BLOCKED.** No cloud production run has ever executed. There is no run ID to report because there
is no run.

What is verified about the workflow *definition* (static, not execution):

- `production.yml` is `workflow_dispatch` with explicit inputs (`channel`, `mode`, `upload`) and no
  `push`/`pull_request` trigger, so untrusted code cannot reach it.
- Dispatch inputs reach shells through `env`, and the channel slug is validated against the three known
  slugs before use.
- Permissions are least-privilege; third-party actions are SHA-pinned; `sha_pinning_required: true` is set
  at repository level.
- `tools/workflow_audit.py`: 0 findings over 7 workflows.

What is **not** verified: runner provisioning, dependency install on a hosted runner, research in cloud,
rendering, QC, artifact upload, manifest hashes, cleanup, and failure notification. Every one of those is
`IMPLEMENTED BUT NOT VERIFIED`, and the honest reason is the 404 in `01_BASELINE_AND_GIT.md`.

Local measurements stand in as the only capacity evidence: three portrait Shorts in 150-202 s each and one
64.5 s landscape episode in 287 s, all QC-passing, peak RSS 117.8 MB.
