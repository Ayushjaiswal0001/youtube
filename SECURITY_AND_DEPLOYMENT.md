# SECURITY_AND_DEPLOYMENT

Facts only. Every claim here is something that was executed or observed, with the
command or run that proves it.

## 1. GitHub identity and ownership

| Rule | Status |
| --- | --- |
| Only `Ayushjaiswal0001` may act | **Verified** — `env -u GITHUB_TOKEN gh api user --jq .login` → `Ayushjaiswal0001` |
| Only `Ayushjaiswal0001/youtube` may be used | **Verified** — single remote, no fork, no mirror, no second repo |
| No force-push, no history rewrite | Honoured — every push in this project has been a fast-forward or a merge commit |
| All work via branches + PRs | PR #1 (merged, pre-dates the approval rule), PR #2 (open), landscape work on `feat/landscape-16x9` |
| No merges without owner approval | Active since the rule was set; PR #2 remains unmerged |

**Environment hazard:** the shell exports `GITHUB_TOKEN` bound to a *different* account
(`Ayushjaiswal001`). `gh` prefers that variable over its own keyring, which is exactly
what produced the original `403 Permission … denied to Ayushjaiswal001`. Every GitHub
command in this project therefore runs as `env -u GITHUB_TOKEN gh …`.

## 2. Credential handling

| Control | Implementation |
| --- | --- |
| Secrets never in Git | `.gitignore` blocks `.env*`, `secrets/`, `credentials/`, `ytcredentials.txt`, `ytcredetials.txt`, `.secrets/`, `.state/`; `git ls-files` contains no credential material |
| Secrets never printed | `uploader/logging.py` redacts tokens; `ChannelCredentials.__repr__` prints `<redacted>` for id/secret/refresh; no command in this project echoes a token |
| Resolution order | `YT_<SLUG_UPPER_SNAKE>_{CLIENT_ID,CLIENT_SECRET,REFRESH_TOKEN}` → `~/.faceless-shorts/secrets/youtube/<slug>.json` → legacy file (read-only) |
| Scope discipline | Exactly `youtube.upload` + `youtube.readonly`; any extra scope aborts the flow |
| CI credentials | Written to `$GITHUB_ENV` from repository secrets inside the job; a missing secret skips the upload with a warning instead of failing |
| Local secret directory | `~/.faceless-shorts/secrets/youtube/` holds 3 per-channel files (contents never inspected or printed) |

## 3. Publishing safety interlocks

| Gate | Behaviour |
| --- | --- |
| `--execute` | Default is dry-run; a real upload requires the flag |
| `FACTORY_ALLOW_UPLOAD=1` | Required in addition to `--execute` |
| `FACTORY_ALLOW_SCHEDULE=1` | Required for any `publishAt` release |
| `--confirm-channel <slug>` | Must equal the selected channel |
| Channel identity | `channels.list(mine=true)` before the upload *and* response-channel check after |
| Privacy | Hard-coded `private` unless the channel config allows public, and no channel does |
| `madeForKids` | Forced `true` for `natkhat-toons`; cannot be set false from config |
| Dedupe | SHA-256 ledger; `uploading`/`uploaded`/`unknown` block a retry |

Cron schedules pass no inputs, so `upload` defaults to `false`: a scheduled run can never
publish. Only an explicit `workflow_dispatch` with `upload: true` can, and that still
needs `FACTORY_ALLOW_UPLOAD`.

## 4. GitHub Actions deployment state

| Workflow | State | Note |
| --- | --- | --- |
| `ci.yml` | **active, green** | uploader (3.11/3.12, no third-party deps) + factory (libcairo2-dev, ffmpeg, requirements, 42 tests, CLI smoke) |
| `produce.yml` | active (reusable only) | no `on: schedule`; cannot fire by itself |
| `produce-nexus-node.yml` | **disabled manually** | would fire 14:30 UTC |
| `produce-academic-biohacker.yml` | **disabled manually** | would fire 06:30 UTC |
| `produce-natkhat-toons.yml` | **disabled manually** | would fire 12:30 UTC |

Re-enable only after T12 (runner validation) and T15 (secrets) pass, and only with
owner approval: `gh workflow enable produce-<channel>.yml`.

## 5. Runner hardening (branch `fix/runner-install-robustness`, PR #2)

The first production dispatch stalled 13 m 11 s inside `apt-get update` with zero
repository output — no acquire timeout, no step limit. The fix bounds everything:

- `-o Acquire::Retries=3`, `Acquire::http/https::Timeout=20`, `Acquire::ForceIPv4=true`,
  `DPkg::Lock::Timeout=60`, `DEBIAN_FRONTEND=noninteractive`.
- Step timeouts: 10 min install, 10 min pip, 5 min environment check, 30 min render.
- `ffmpeg`/`ffprobe` installed only when `command -v` fails (the runner image does not
  ship them).
- Tool probes wrapped in `timeout 30` so a broken Chrome fails fast.

## 6. Known open security/deployment items

| Item | Status |
| --- | --- |
| Actions secrets `YT_NEXUS_NODE_*`, `YT_ACADEMIC_BIOHACKER_*`, `YT_NATKHAT_TOONS_*` | **Not provisioned** — needs owner action in repo settings |
| OAuth app publishing status (Testing vs Production) | **Unknown** — Testing-mode refresh tokens expire after 7 days; must be confirmed by the owner |
| Third-party workers / paid infrastructure | **None used.** No service is activated |
| Repository visibility | Public. Any accidental secret commit would be permanent, hence the ignore rules and the dependency/secret test guard |
