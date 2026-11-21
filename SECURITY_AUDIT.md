# SECURITY AUDIT — public repository hardening

Scope: `Ayushjaiswal0001/youtube` at `feat/landscape-16x9` (public). Date 2026-11-22.
Auditor: the same agent that built the pipeline, which is a conflict of interest and is disclosed:
an independent reviewer should re-run the commands in §8 rather than trust this document.

Everything below was executed. Nothing here is a promise about the future, and the limits of what
could be checked are stated explicitly at the end.

## 1. What was scanned, and with what

| Surface | Method | Result |
| --- | --- | --- |
| Working tree (219 tracked files) | `python -m tools.secret_scan` — 14 rules covering Google OAuth (`GOCSPX-`), API keys (`AIza…`), YouTube refresh/access tokens (`1//0…`, `ya29.…`), GitHub tokens (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`), AWS keys, Slack tokens, private-key headers, OpenAI/Anthropic keys, connection strings with inline passwords, bearer headers, and keyed secret assignments | **0 findings** after annotating 4 test fixtures |
| All refs, all reachable history | `python -m tools.secret_scan --history` — walks every blob in `git rev-list --objects --all` | **4 findings, all the same fake test fixtures**; no real credential in any commit |
| Staged diff | `python -m tools.secret_scan --staged` (also a pre-commit hook) | 0 findings |
| Workflow files | `python -m tools.workflow_audit` | 0 findings after 2 fixes |
| Dependencies | `python -m pip_audit -r requirements.txt` | 67 advisories → **42 residual**, all in pillow 12.3.0 (see F5) |
| GitHub settings | `gh api` on repo, actions/permissions, branches/main/protection, rulesets, secrets, variables, environments, releases, artifacts | see §4 |
| Artifacts | Downloaded both existing artifacts and read every file | **Found**: run journal leaked the local Windows path; no credentials |
| Action logs | Inspected the credential-export step and its `::add-mask::` handling | No token is echoed; see §3 |

Gitleaks and TruffleHog are **not installed** on this machine, so the scan above is a purpose-built
scanner rather than those tools. That is a real limitation: an independent Gitleaks run is recommended
and is listed as an owner action. The scanner is not weaker by intent — it is narrower and auditable,
and CI plants a synthetic secret on every run to prove it still matches.

## 2. Findings

### F1 — Run journal published the owner's local path (fixed)

`factory/state.py` recorded absolute paths in `runs.jsonl`, which the production workflow uploads as an
artifact. Both existing artifacts contain `C:\Users\DELL\AppData\Local\Temp\opencode\youtube\build\…`,
i.e. a username and a machine layout, on a public repository.

Fixed by `portable_path()`/`_scrub()` at the single write point (`ChannelState.log_run`): project paths
become `build/<channel>/<episode>/video.mp4`, other paths reduce to the file name. Tests:
`test_journal_entry_cannot_publish_the_machine`, `test_portable_path_*`. The two existing artifacts still
contain the old text — deleting them is an owner action (§7).

### F2 — Machine paths in public documentation (fixed)

`README.md`, `PROJECT_CONTEXT.md`, `AI_HANDOFF.md` and `docs/oauth-consent.md` contained
`C:\Users\DELL\…`. Replaced with `<path-to-clone>` / `%USERPROFILE%`. Channel handles and channel IDs
were deliberately **kept**: they are public identifiers required for identity verification, and removing
them would break the uploader's `expected_channel_id` check.

`TEST_RESULTS.md` still quotes a local path once, as evidence of a historical test defect
(line 345). It was left alone on purpose: rewriting an evidence log to make a scan look cleaner is
worse than the disclosure. No credential is involved.

### F3 — Third-party actions pinned to moving tags (fixed)

`actions/checkout@v4`, `actions/setup-python@v5`, `actions/cache@{restore,save}@v4` and
`actions/upload-artifact@v4` now pin full commit SHAs resolved through the GitHub API:

| Action | Pinned commit |
| --- | --- |
| `actions/checkout` | `11d5960a326750d5838078e36cf38b85af677262` |
| `actions/setup-python` | `a26af69be951a213d495a4c3e4e4022e16d87065` |
| `actions/cache` (restore and save) | `0057852bfaa89a56745cba8c7296529d2fc39830` |
| `actions/upload-artifact` | `ea165f8d65b6e75b540449e92b4886f43607fa02` |

`sha_pinning_required` is still `false` at repository level (owner action, §7): the pinning is now
enforced by `tools/workflow_audit` in CI instead of by a setting.

### F4 — Workflow inputs interpolated into shell commands (fixed)

`produce.yml` had two `run:` blocks interpolating dispatch inputs:
`[ "${{ inputs.allow_unpublished }}" = "true" ]` and
`PREFIX=$(printf '%s' "${{ inputs.secret_prefix }}" …)`. A dispatch input is operator-supplied, not
attacker-supplied, but interpolation into a shell is the wrong pattern and one typo away from a command
injection. Both now arrive through `env:` (`ALLOW_UNPUBLISHED`, `SECRET_PREFIX`), and `CHANNEL` is
validated against the three known slugs before any step uses it as a directory or argument.

### F5 — Pillow version carried 67 advisories (fixed, 4 residual)

`pillow==12.2.0` → **`pillow==12.3.0`**: 67 → **42** advisories, all fixed only in 13.0.0. 749 tests pass and
the 78 golden frames are unchanged by the bump, so Pillow is not in the animation's visual path.
13.0.0 is not adopted because the machine's optional `rembg` package pins `pillow<13`; the residual
advisories sit in image-format parsers (PCF/BDF fonts, the bundled libopenjp2/JPEG2000, DDS and similar),
and this pipeline decodes only PNGs it rendered itself — it accepts no untrusted image input.

**Correction, disclosed:** the first version of this document said "67 → 4", because I read the tail of the
`pip-audit` output and counted the visible lines. 12.3.0 still carries **42** advisories. That is why the CI
gate is now `tools/dependency_audit.py` against `security/accepted-advisories.json`: a version ceiling for
`pillow@12.3.0` carrying the reason and the exit condition, counted and printed on every run, instead of a
number in a document that nobody re-checks.

### F6 — My own auditor produced two false positives (fixed)

First run flagged `produce.yml` for "job reads secrets but does not narrow its own permissions" (its
top-level `permissions: contents: read` already covers every job) and `security.yml` for using
`pull_request_target` — the string appeared in the comment explaining why it is *not* used. Both rules
were corrected: comments are stripped before scanning, and a workflow-level permission block now
satisfies the job-level rule. Disclosed because a security tool that fails safe workflows gets disabled,
and a security tool with a hidden false negative is worse.

### F7 — 4 fake credentials sit in test fixtures, in history (accepted, documented)

`tests/support.py` and `tests/test_oauth.py` contain `client-secret`, `refresh-token`,
`access-secret` in `ChannelCredentials(...)` call sites. They are fake, and they are annotated
`# pragma: allowlist secret`. They are also in history, and history is not being rewritten for cosmetic
value. Impact: none beyond a scanner hit; the strings are not valid credentials for any provider.

## 3. Credential handling in the workflow (no finding)

`produce.yml`, "Export channel credentials": values come from
`secrets[format('YT_{0}_CLIENT_SECRET', inputs.secret_prefix)]`, are `::add-mask::`ed, written to
`GITHUB_ENV`, and never echoed. If any of the three is missing, the step sets `ready=0` and the upload
step does not run — fail closed. The upload step requires `inputs.upload ∧ creds.ready ∧ gate.ok`, with
job-wide `UPLOAD_ENABLED=false`, `SCHEDULED_PUBLISHING_ENABLED=false`,
`PUBLICATION_APPROVAL_REQUIRED=true`. Production workflows trigger only on `schedule` and
`workflow_dispatch`; none runs code from a fork.

`secrets: inherit` is used by the three per-channel callers. That passes every repository secret into the
reusable workflow, which is broader than the minimum. It is acceptable *here* because the callee is a
workflow in the same repository that never runs on `pull_request`, but it means a future step added to
`produce.yml` could read secrets it does not need. Noted as a design trade-off rather than fixed, because
the dynamic `secrets[format(...)]` lookup exists precisely to avoid duplicating the mapping three times.

## 4. GitHub settings (as read, 2026-11-22)

| Setting | Value | Assessment |
| --- | --- | --- |
| Visibility | public | by design |
| Secret scanning (provider patterns) | **enabled** | good |
| Secret scanning push protection | **enabled** | good |
| Secret scanning non-provider patterns | disabled | could be enabled (owner) |
| Secret scanning validity checks | disabled | could be enabled (owner) |
| Dependabot alerts | **disabled** | gap: no dependency alerts (owner) |
| Dependabot security updates | **disabled** | gap (owner) |
| Default workflow token permissions | **read** | good |
| Actions allowed | `all` | broad; `sha_pinning_required: false` |
| Environments | 0 | no protection rules exist (owner) |
| Repository secrets | **0** | nothing to leak; also nothing configured |
| Repository variables | 0 | — |
| Branch protection on `main` | **none** ("Branch not protected") | gap: force-push/deletion possible (owner) |
| Rulesets | none | gap (owner) |
| Releases | 0 | — |
| Artifacts | 2, both state caches containing F1 paths | owner should delete or let expire |

Code scanning: no analysis exists. Secret scanning is on, code scanning is not.

## 5. Three-channel isolation (verified by test)

* `channels/*.json` declare three distinct `expected_channel_id` values and three distinct handles;
  `test_the_three_channels_have_distinct_identities` fails if any two collide.
* Credentials are resolved per slug from `YT_<SLUG>_CLIENT_ID|CLIENT_SECRET|REFRESH_TOKEN`;
  `test_credentials_are_read_from_the_channel_own_prefix` proves the prefixes cannot be crossed.
* A channel with no credentials raises `CredentialsError` ("no credentials available"); a partial set
  raises with only the missing key names and never the supplied value
  (`test_a_channel_without_credentials_fails_closed`).
* `verify_identity()` compares `channels.list(mine=true)` against `expected_channel_id` **and**
  `display_name`, and refuses a token that reports more than one channel
  (`test_verification_rejects_a_token_that_belongs_to_another_channel`,
  `test_verification_rejects_more_than_one_channel_on_a_token`). A successful upload to one channel
  therefore cannot authorize another: the access token is per-channel and the identity is re-checked
  after the refresh that produces it.
* `--execute` additionally requires `--confirm-channel` equal to the slug, and Natkhat Toons forces
  `madeForKids`.

## 6. Regression prevention added

| Mechanism | File | Fails when |
| --- | --- | --- |
| Tree + history + staged secret scan | `tools/secret_scan.py` | any credential pattern in code, docs or any commit |
| Scanner self-test in CI | `.github/workflows/security.yml` | a planted `GOCSPX-` secret is not detected |
| Workflow audit | `tools/workflow_audit.py` | missing permissions, unpinned action, `pull_request_target`, input in shell |
| Credential file blocking | `tools/block_credentials.py` + `.pre-commit-config.yaml` | `ytcredentials.txt`, `.env`, OAuth JSON, keys are staged |
| Dependency audit | `pip-audit` in `security.yml` | a pinned requirement has a known advisory |
| Golden-frame pre-commit hook | `.pre-commit-config.yaml` | a commit changes animation output silently |
| Tests | `tests/factory/test_security.py` (18) | scanner regressions, journal path leaks, isolation breaks |

The security workflow has `permissions: contents: read`, no secrets, and no `pull_request_target`, so a
fork cannot use it.

## 7. Owner actions

1. **Delete or expire the two artifacts** (`14658931783`, `14657666224`) — they contain pre-fix journal
   lines with the local path. No credentials in them. `gh api -X DELETE repos/Ayushjaiswal0001/youtube/actions/artifacts/<id>`
2. **Enable Dependabot alerts and security updates** (Settings → Code security), and optionally
   non-provider secret scanning patterns and validity checks.
3. **Protect `main`**: require a pull request and one approval, disallow force-push and deletion. This is
   a behavioural change for the owner's own workflow, so it is not done unilaterally.
4. **Set `sha_pinning_required=true`** if you want the platform to enforce what `workflow_audit` now
   checks.
5. **Add a branch-protection environment** for the publish job if scheduled publishing is ever enabled,
   so a human approval is required before an upload.
6. **Run Gitleaks independently** — `docker run -v "$PWD:/repo" zricethezav/gitleaks:latest detect
   --source=/repo --verbose` — as a second opinion on the scan in §1.
7. **Rotate nothing today**: no active credential was found anywhere in the repository or its history.
   If a credential is ever pasted into an issue or a commit, rotate it before anything else.

## 8. Reproduce this audit

```bash
env -u GITHUB_TOKEN python -m tools.secret_scan
env -u GITHUB_TOKEN python -m tools.secret_scan --history
python -m tools.workflow_audit
python -m tools.dependency_audit
python -m pytest tests/factory/test_security.py -q
env -u GITHUB_TOKEN gh api repos/Ayushjaiswal0001/youtube --jq .security_and_analysis
env -u GITHUB_TOKEN gh api repos/Ayushjaiswal0001/youtube/branches/main/protection
```

## 9. Verdict

| Security category | Result | Evidence |
| --- | --- | --- |
| Current repository secret scan | **PASS** | `tools.secret_scan`: 14 rules, 0 findings; 4 fixtures annotated |
| Git history scan | **PASS** | `--history` over all refs: only the 4 documented fake fixtures |
| GitHub Actions security | **PASS (hardened this pass)** | no `pull_request_target`, read-only tokens, SHA pins, inputs via `env`, `workflow_audit` clean |
| GitHub secrets and variables | **PASS** (0 secrets, 0 variables) / **UNVERIFIED** for organisation-level policy — no org permission | `gh api …/actions/secrets`, `…/actions/variables` |
| Three-channel OAuth isolation | **PASS** | 18 security tests, including two identity-mismatch rejections |
| Token leakage in logs | **PASS for the workflow as written** | `::add-mask::`, no echo, `set -x` absent; **not verified against live run logs** because no run has executed the upload path |
| Public README exposure | **PASS** | machine paths removed; public channel identifiers intentionally retained |
| GitHub artifacts and caches | **VULNERABILITY FOUND, FIXED IN CODE; 2 OLD ARTIFACTS AWAIT DELETION** | downloaded both artifacts: local paths only, no credentials |
| Dependency vulnerabilities | **PASS with 42 accepted advisories, all in pillow 12.3.0** | `tools.dependency_audit`: 0 unaccepted, 42 accepted under a documented version ceiling; any other package or version fails |
| Branch protection | **FAIL — no protection on `main`** | `gh api …/branches/main/protection` → 404 "Branch not protected"; owner action |

**Verdict: no known exposed active credential, and no privilege-escalation path found in the audited
workflows.** Two settings-level gaps remain that I cannot close without changing the owner's repository
behaviour: `main` is unprotected, and Dependabot alerts are off. Nothing was published, uploaded,
scheduled or merged during this audit, and no credential was printed.

**Scope limits.** I audited the repository, its reachable history, its workflows, its artifacts and its
settings as visible to this account. I did not audit: GitHub's own infrastructure, the owner's YouTube
and Google Cloud console configuration, the owner's workstation beyond this clone, any secret an
attacker may hold from outside this repository, or logs of runs that do not exist. Secret scanning being
enabled on GitHub means GitHub also reports provider patterns it recognises — but only for patterns it
knows, which is not the same as "this repository is clean".
