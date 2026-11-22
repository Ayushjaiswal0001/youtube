# youtube

Centralized YouTube uploader for three channels. The primary safety rule is simple: **the token used for an upload must belong to the exact channel selected for that upload**.

This repository currently contains the uploader implementation and offline tests. No video has been uploaded by this code.

## Channels

| Slug | Title | Handle | Expected channel ID |
| --- | --- | --- | --- |
| `nexus-node` | Nexus Node | `@nexusnode012` | `UCx9O8VivWkiEylDjs5_Zzag` |
| `academic-biohacker` | Academic Biohacker | `@academicbiohacker` | `UCr8jSmLa_o2BwNh8HuyZHAQ` |
| `natkhat-toons` | Natkhat Toons | `@NatkhatToons-n5` | `UC4OCY0qDwQqFnSCZw12sKxA` |

Expected IDs are confirmed from public channel pages and are checked against the API during preflight. The check must also pass immediately before an upload.

## Safety model

- Independent per-channel token files, outside Git.
- Required scopes: exactly `youtube.upload` and `youtube.readonly`. Extra scopes (`youtube`, `drive`, etc.) abort the flow.
- Preflight calls `channels.list(mine=true)`, looks up the expected handle, and aborts on any ID, title, handle, or `customUrl` mismatch.
- The upload response channel ID is checked again after upload.
- Default privacy is `private`. Public uploads are disabled in all channel configs and also require `--allow-public` plus explicit approval.
- Natkhat Toons is confirmed child-directed: `madeForKids` defaults to `true` and `false` is rejected. The policy can only change by editing the channel config with approval.
- Deduplication uses the video SHA-256. Existing `uploading`, `uploaded`, or `unknown` states block a retry.
- `unknown` is a hard stop: reconcile the channel uploads playlist before retrying.
- The uploader never logs access tokens, refresh tokens, client secrets, or OAuth codes.

## Installation

Python 3.11+ is required. There are no third-party runtime dependencies.

```powershell
$repo = "<path-to-your-clone>"
Set-Location $repo
python -m compileall -q uploader tests
python -m unittest discover -s tests -v
```

## Credential sources

Priority order:

1. Environment variables: `YT_<SLUG>_CLIENT_ID`, `YT_<SLUG>_CLIENT_SECRET`, `YT_<SLUG>_REFRESH_TOKEN`.
2. Per-channel files under `%USERPROFILE%\.faceless-shorts\secrets\youtube\`.
3. Read-only fallback to the legacy credential file supplied with `--legacy-credentials`.

The legacy file is never modified by this tool. Never commit it or copy it into the repository.

## Commands

```powershell
python -m uploader.cli sources --legacy-credentials "D:\animated\ytcredetials.txt"

python -m uploader.cli scope-check --channel all `
  --legacy-credentials "D:\animated\ytcredetials.txt"

python -m uploader.cli consent --channel nexus-node `
  --legacy-credentials "D:\animated\ytcredetials.txt" --open

python -m uploader.cli verify --channel all

python -m uploader.cli dry-run --channel nexus-node `
  --video "C:\path\to\approved.mp4" `
  --title "Example Short" `
  --privacy private `
  --made-for-kids false `
  --skip-media-check

python -m uploader.cli status --channel nexus-node
python -m uploader.cli history --channel nexus-node
```

`dry-run` performs token refresh, scope validation, identity verification, metadata validation, and duplicate checks. It does not call `videos.insert`.

The `upload` command defaults to dry-run. A real upload requires all of the following:

```powershell
python -m uploader.cli upload --channel nexus-node `
  --video "C:\path\to\approved.mp4" `
  --title "Example Short" `
  --execute --confirm-channel nexus-node
```

Do not use `--execute` until the milestone review and explicit approval are complete.

## OAuth notes

- The OAuth app publishing status is not inferred by this repository. Confirm it in Google Cloud Console.
- Testing-mode refresh tokens expire after 7 days. Re-consent is required after expiry.
- Adding sensitive scopes such as `youtube.readonly` may require OAuth verification.
- Do not change the OAuth app publishing status without approval.
- The callback uses a loopback redirect. A Desktop OAuth client should accept an ephemeral `127.0.0.1` port. A Web client may require a registered redirect URI first.

## Media and metadata

Uploads must be MP4, 1080x1920, with one video stream and at least one audio stream. `ffprobe` must be available on `PATH` for the default media check. Use `--skip-media-check` only for controlled dry-runs.

Metadata can be passed as a JSON file:

```powershell
python -m uploader.cli dry-run --channel nexus-node `
  --video "C:\path\to\approved.mp4" `
  --metadata ".\examples\upload-request.example.json"
```

Fields: `title`, `description`, `tags`, `categoryId`, `privacyStatus`, `madeForKids`, `notifySubscribers`, `playlistId`.

`playlistId` is validated and recorded but is not applied yet. Adding a video to a playlist requires a broader OAuth scope, which is outside the currently approved scope set.

## Quota

Per Google Cloud project, the current YouTube Data API rules include:

- `videos.insert`: 100 calls/day in its own bucket; cost 1.
- `search.list`: 100 calls/day in its own bucket; cost 1.
- Other endpoints: 10,000 units/day.
- Quota resets at midnight Pacific Time.

All three channels share one OAuth client/project, so the 100-upload limit is shared. Three uploads per day, even simultaneous, are not quota-constrained.

## Local state

Runtime data lives outside the repository:

- Secrets: `%USERPROFILE%\.faceless-shorts\secrets\youtube\`
- Ledger/state: `%USERPROFILE%\.faceless-shorts\state\youtube\`
- Logs: `%USERPROFILE%\.faceless-shorts\logs\youtube\`

See `docs/oauth-consent.md`, `docs/uploader.md`, and `docs/test-plan.md`.

## Benchmarks and observability

    # measure a real render (wall time, peak RSS, disk, fps) and print projections
    python -m tools.benchmark --channel natkhat-toons --format shorts --label portrait-short

    # machine-readable pipeline output - stdout is now exactly one JSON document
    python -m factory.cli render --channel natkhat-toons --format long --json 2>/dev/null | jq .

    # near-camera set dressing: renders all six locations and measures occlusion of the cast
    python -m tools.render_dressing_sheet --out build/dressing

Notifications are off unless a provider is configured; `FACTORY_NOTIFY_WEBHOOK` is the only switch and
no credential is read. `FACTORY_INLINE_CUTS=0` disables cuts inside a dialogue line;
`FACTORY_SET_DRESSING=0` disables near-camera dressing.

## Security

    python -m tools.secret_scan              # working tree
    python -m tools.secret_scan --history    # every blob in every ref
    python -m tools.workflow_audit           # permissions, action pinning, dangerous triggers
    python -m tools.dependency_audit          # dependency advisories vs. the reviewed baseline

Install the pre-commit hooks once with `python -m pip install pre-commit && pre-commit install`.
The full audit, its findings and the settings that remain owner decisions are in `SECURITY_AUDIT.md`.
