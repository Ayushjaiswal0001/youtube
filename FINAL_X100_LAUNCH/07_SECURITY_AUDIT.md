# 07 — SECURITY AUDIT (public repository)

| Surface | Tool / method | Result |
| --- | --- | --- |
| Working tree | `tools/secret_scan` (14 rules) | 0 findings |
| Staged diff | `tools/secret_scan --staged` | 0 findings before the commit |
| Full history | `tools/secret_scan --history`, Gitleaks 8.30.1 | 0 findings each |
| Workflows | `tools/workflow_audit` | 7 workflows, 0 findings |
| Dependencies | `tools/dependency_audit` | 0 unaccepted, 0 accepted (pillow 13.0.0) |
| Repository secrets | `gh secret list` | 0 |
| Repository variables | `gh variable list` | 0 |
| Published artifacts | `gh api .../actions/artifacts` | 0 |

Positive properties carried from earlier passes: `secrets: inherit` removed so each caller passes only its
own three credentials; actions SHA-pinned with `# vX.Y.Z` comments; `sha_pinning_required: true`; no
`pull_request_target`; `main` protected with one approval and three required checks; uploads gated on
`inputs.upload` and `creds.ready` and `gate.ok`; channel credentials isolated by prefix with an
`expected_channel_id` check; `::add-mask::` on every credential.

Open items, unchanged and all owner-side: two secret-scanning toggles (non-provider patterns, validity
checks) cannot be enabled through the API with this account, and no code-scanning analysis exists.

No credential value appears anywhere in this directory.
