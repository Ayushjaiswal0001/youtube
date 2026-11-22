# 01 — BASELINE AND GIT

Verified against the live repository with `env -u GITHUB_TOKEN gh`.

| Item | Value |
| --- | --- |
| Branch / HEAD | `feat/landscape-16x9` / `01d72cc` |
| Working tree | clean (0 changes) |
| `main` | `567e63c`, unprotected by this work, not modified |
| Remote | `Ayushjaiswal0001/youtube` |
| PR #2 | OPEN, MERGEABLE — runner install robustness |
| PR #3 | OPEN, MERGEABLE — the whole body of work, including `production.yml` |
| PR #4 | OPEN, MERGEABLE — Dependabot pillow 13.0.0 |
| Repository secrets | **0** (`gh secret list` → `[]`) |
| Repository variables | **0** (`gh variable list` → `[]`) |
| `production.yml` on `main` | **404 Not Found** |
| Workflows on the branch | 7: `ci`, `security`, `produce`, `production`, three per-channel producers |
| Workflow audit | 7 workflows, 0 findings (permissions, SHA pinning, no `pull_request_target`, no input-in-shell) |

## Why cloud cannot run yet

A `workflow_dispatch` workflow is only dispatchable from the branch it exists on. `production.yml` exists
only on `feat/landscape-16x9`, and GitHub will not dispatch it from a non-default branch. This is not a
configuration mistake to work around: the correct path is the one branch protection enforces — PR #3 is
reviewed and merged, then the workflow exists on `main`.

Owner action: review and merge PR #3 (see `09_OWNER_ACTIONS.md`). No merge was performed here.
