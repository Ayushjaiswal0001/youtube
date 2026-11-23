# Publishing readiness — what works, what is missing, what the owner must do

Audited by running the code, not by reading it. Nothing in this document has been executed against YouTube: there
are **0 repository secrets and 0 variables**, so no upload has been attempted and none is claimed.

## What exists (verified)

`uploader/` is a complete YouTube Data API v3 client, not a stub:

| Capability | Where | State |
|---|---|---|
| OAuth consent + refresh-token exchange | `uploader/oauth.py`, `uploader/credentials.py` | IMPLEMENTED |
| Channel-specific credentials, legacy fallback | `credentials.py` (`YT_<SLUG>_CLIENT_ID/CLIENT_SECRET/REFRESH_TOKEN`) | IMPLEMENTED |
| Resumable upload with chunk recovery | `uploader/youtube.py` (`initiate_resumable`, `upload_resumable`, 308 handling) | IMPLEMENTED |
| Channel routing and identity proof | `router.py`, `identity.py` (`channels.list(mine=true)` must return exactly one channel whose id matches the expected id) | IMPLEMENTED |
| Post-upload identity check | `identity.verify_upload_response` compares `snippet.channelId` to the channel's expected id | IMPLEMENTED |
| Duplicate prevention | `ledger.py` — file-locked ledger, `latest_for_job`, `latest_for_hash` | IMPLEMENTED |
| Retry / backoff | `retry.py` (`retry_call`), `429`/`5xx` classified retryable | IMPLEMENTED |
| Thumbnail upload | `youtube.set_thumbnail` | IMPLEMENTED |
| Processing poll | `youtube.get_video("snippet,status")` | IMPLEMENTED |
| Privacy control | `metadata.py` — every channel defaults to `private` | IMPLEMENTED |
| Kill switches | `factory/publisher.py` — `FACTORY_ALLOW_UPLOAD`, `FACTORY_ALLOW_SCHEDULE` | IMPLEMENTED |
| Credential masking | workflow `::add-mask::` per credential before use | IMPLEMENTED |
| Fail-closed readiness | missing credential ⇒ `ready=0` | IMPLEMENTED |

The upload step in `produce.yml` is gated three ways: `inputs.upload ∧ creds.ready ∧ gate.ok`. With
`UPLOAD_ENABLED=false`, `SCHEDULED_PUBLISHING_ENABLED=false` and `PUBLICATION_APPROVAL_REQUIRED=true` in the
workflow environment, the only way to upload is an explicit dispatch with `upload=true` **and** credentials
present.

## Two defects found and fixed in this session

1. **A kids channel could be built as not-for-kids.** `force_made_for_kids` was checked only inside
   `UploadRequest.validate()`, and nothing in the upload path calls `validate()` — only tests did. Demonstrated:
   `UploadRequest.from_data(natkhat_config, video, {"madeForKids": False})` was accepted and produced
   `selfDeclaredMadeForKids: false`. The declaration was safe only because one config field happened to default to
   true. It is now rejected where the request is built (`uploader/metadata.py`), and `validate()` keeps the check
   as defence in depth.
2. **A long-form episode could land exactly on the true-peak limit.** Cloud run `45137023125` encoded the academic
   long-form episode at −0.96 dBTP and failed `audio_loudness` against −1.0. `alimiter` limits sample peak, not
   true peak, and AAC adds inter-sample overshoot on the way out. The final limiter moved from `0.82` to `0.74`
   (≈ 2.6 dB sample headroom). The gate is unchanged at −1.0 dBTP and the −14 LUFS target is untouched: the mix is
   quieter at the peak, the check is not weaker. Its failure message also printed `-1.0 dBTP above -1.0` at one
   decimal for a measured −0.96, which read like a broken threshold; two decimals now.

Both are covered by tests that exercise the real path (`tests/factory/test_publish_gates.py`,
`tests/test_metadata.py`, `tests/factory/test_audio.py` — the audio test drives a hot tone through `make_bed` +
`mix_narration` and measures the encoded file).

## What is missing (owner actions, in order)

**1. Create one Google Cloud OAuth client** (Web application type) with the YouTube Data API v3 enabled, consent
screen **In production** (Testing-mode refresh tokens expire in 7 days — that is a trap for a scheduler).

**2. Mint one refresh token per channel**, on the machine that owns the browser session:

```
python -m uploader.cli consent --channel nexus-node
python -m uploader.cli consent --channel academic-biohacker
python -m uploader.cli consent --channel natkhat-toons
```

The account signed in during consent **must own the channel**, because `identity.verify_identity` requires
`channels.list(mine=true)` to return exactly one channel and that channel's id to match:

| Channel | Expected channel id |
|---|---|
| `nexus-node` | `UCx9O8VivWkiEylDjs5_Zzag` |
| `academic-biohacker` | `UCr8jSmLa_o2BwNh8HuyZHAQ` |
| `natkhat-toons` | `UC4OCY0qDwQqFnSCZw12sKxA` |

**3. Add nine repository secrets** (Settings → Secrets and variables → Actions):

```
YT_NEXUS_NODE_CLIENT_ID        YT_NEXUS_NODE_CLIENT_SECRET        YT_NEXUS_NODE_REFRESH_TOKEN
YT_ACADEMIC_BIOHACKER_CLIENT_ID YT_ACADEMIC_BIOHACKER_CLIENT_SECRET YT_ACADEMIC_BIOHACKER_REFRESH_TOKEN
YT_NATKHAT_TOONS_CLIENT_ID     YT_NATKHAT_TOONS_CLIENT_SECRET     YT_NATKHAT_TOONS_REFRESH_TOKEN
```

Add them as secrets, never as variables, and never in a file that reaches the repository. Do not paste them into a
chat.

**4. First private upload — one channel only.** Nexus Node first, because it is a general-audience channel:

```
env -u GITHUB_TOKEN gh workflow run production.yml --ref main \
  -f channel=nexus-node -f plan_id=nexus-data-wall \
  -f mode=render+validate+upload -f upload=true
```

Then verify, from the run log and the ledger: the video id and URL, `privacyStatus=private`, the channel id, the
title and description, and that YouTube reports the video as processed. Repeat for the other two channels only
after that row is clean.

**5. Public publishing: not authorised, not implemented as a default.** It requires an explicit decision from the
owner per video (or a documented policy), and it is the point where a QC failure becomes publicly visible. Keep
`privacyStatus=private` until then.

## Schedules

Three daily workflows exist and are **`disabled_manually`**: `nexus-node daily`, `academic-biohacker daily`,
`natkhat-toons daily`. `production (manual)` is active, so nothing runs on its own.

Do not enable them before: (a) one private upload per channel has been verified, (b) the plan selector is pinned to
a specific plan id rather than a wildcard, (c) the failure notification path actually delivers, and (d) the owner
approves. A schedule that fires into an empty credential slot produces one failed run per day and no video.

## Notifications

Without `FACTORY_NOTIFY_WEBHOOK`, `factory/observability.py` uses `NullNotifier` and every notification reports
`delivered: False`. An unreachable webhook also reports `delivered: False` and does not raise. Operational failure
notification is therefore **NOT OPERATIONAL** until a webhook (or equivalent) is configured; the webhook URL must be
a repository secret.

## Residual risks

| Risk | Consequence | Mitigation |
|---|---|---|
| Testing-mode OAuth | Refresh token expires after 7 days | Publish the consent screen before enabling schedules |
| Wrong Google account at consent | Upload lands on the wrong channel | `verify_identity` refuses unless exactly one channel matches the expected id |
| Duplicate upload after a rerun | Two copies of one episode | `ledger.latest_for_hash` / `latest_for_job`, and `resume` refuses a `PUBLISHED` episode without `--force` |
| Quota | 6 uploads/day at ~1600 units each is ~10k of the 10k daily units | 3 Shorts + 1 long-form per week per channel is far inside quota; do not schedule hourly |
| `madeForKids` regression | Children's channel misdeclared | Enforced at request construction, with a test |
