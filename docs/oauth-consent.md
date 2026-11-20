# OAuth consent runbook

## Prerequisites

- Confirm the OAuth app publishing status in Google Cloud Console. Do not change it without approval.
- Confirm the OAuth client type:
  - Desktop app: loopback redirect with an ephemeral `127.0.0.1` port should work.
  - Web application: a redirect URI must be registered before the browser flow can complete.
- Confirm the user can select the correct Google/Brand Account for each channel.
- Confirm `D:\animated\ytcredetials.txt` remains untouched. Record its SHA-256 before and after.
- Do not request or accept incremental scopes. Consent requests `include_granted_scopes=false` and accepts only the two approved scopes.

The legacy tokens have only `youtube.upload` and cannot call `channels.list(mine=true)`. The per-channel secrets created by this runbook have both approved scopes. If a per-channel secret is missing or fails verification, re-consent.

## Required scopes

```text
https://www.googleapis.com/auth/youtube.upload
https://www.googleapis.com/auth/youtube.readonly
```

## Flow

Run one channel at a time. The consent URL forces the Google account chooser; select the matching Google/Brand Account and, if prompted, the matching YouTube channel. Add `--force` only when replacing a secret that failed scope or identity checks.

```powershell
Set-Location "C:\Users\DELL\AppData\Local\Temp\opencode\youtube"

python -m uploader.cli consent --channel nexus-node `
  --legacy-credentials "D:\animated\ytcredetials.txt" --open
```

Repeat for:

```powershell
python -m uploader.cli consent --channel academic-biohacker `
  --legacy-credentials "D:\animated\ytcredetials.txt" --open

python -m uploader.cli consent --channel natkhat-toons `
  --legacy-credentials "D:\animated\ytcredetials.txt" --open
```

The tool:

1. Generates PKCE verifier/challenge and state.
2. Starts a loopback callback server.
3. Opens the Google consent URL.
4. Exchanges the code.
5. Requires both scopes and rejects any extra scopes.
6. Calls `channels.list(mine=true)` and the handle lookup.
7. Compares the exact channel ID and title, and the handle's ID/title/custom URL.
8. Saves the refresh token only after the identity check passes.

If the account is wrong, the flow aborts and no secret file is written. Re-run with the correct account.

## Identity evidence

For each channel, retain:

- expected channel ID, title, and handle;
- token channel ID and title;
- handle lookup channel ID, title, and custom URL;
- verified timestamp;
- scopes returned by Google;
- credential source.

`python -m uploader.cli verify --channel all --json` emits this evidence without tokens or client secrets.

## Expiry and verification

- Testing-mode refresh tokens expire after 7 days.
- Sensitive-scope verification can take up to 10 days.
- If `scope-check` fails, do not attempt an upload. Re-consent.

## Callback troubleshooting

- `redirect_uri_mismatch`: the OAuth client is a Web client without a registered loopback URI. Stop and report it; do not alter app settings without approval.
- `access_denied`: the user cancelled or selected the wrong account. Re-run.
- `token has unexpected OAuth scopes`: revoke the app's access at `https://myaccount.google.com/permissions`, then re-consent with `--force`. Do not use the broad token.
- Timeout: re-run the command. No credential file is written until identity verification succeeds.
