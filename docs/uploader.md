# Uploader design

## Pipeline

```text
metadata + video
  -> validate metadata and media
  -> video SHA-256 and metadata SHA-256
  -> ledger duplicate check
  -> refresh token for the selected channel
  -> require upload + readonly scopes
  -> channels.list(mine=true) identity check
  -> handle lookup identity check
  -> [dry run stops here]
  -> ledger: uploading
  -> resumable videos.insert
  -> verify response snippet.channelId
  -> ledger: uploaded
```

The channel is explicit at every step. There is no global current account, default channel, or fallback channel.

## State machine

```text
planned -> uploading -> uploaded
                     -> failed
                     -> unknown
```

- `failed`: a non-retryable API error occurred. A new job may be started after review.
- `unknown`: the request was retryable or the connection broke. The upload may have succeeded. Do not retry until the channel uploads playlist is reconciled.
- `uploading` left behind by a crash is treated as blocking until manually reconciled.

Deduplication is intentionally stricter than the minimum: the same video SHA-256 cannot be uploaded again while a recent ledger entry is `uploading`, `uploaded`, or `unknown`. The metadata SHA-256 is also stored for audit.

## Identity rules

The token's `channels.list(mine=true)` result must match:

- expected channel ID;
- expected display title.

The expected handle lookup must match:

- expected channel ID;
- expected display title;
- expected `customUrl` when YouTube returns it.

Any mismatch aborts. After upload, the response `snippet.channelId` must match again.

## Metadata rules

- Title: 1-100 characters.
- Description: at most 5,000 characters.
- Tags: strings, at most 500 characters joined by commas.
- Category: numeric, 1-44.
- Privacy: `private`, `unlisted`, or `public`. `public` is blocked unless both the channel config and the CLI allow it.
- `madeForKids`: must be a boolean. Natkhat Toons is confirmed child-directed: it defaults to `true` and rejects `false`. Changing that policy requires an approved config change.
- `notifySubscribers`: boolean, default false.

## Media rules

- `.mp4`
- non-empty
- 1080x1920
- one video stream
- at least one audio stream

`ffprobe` from FFmpeg is required when the media check is enabled.

## Scopes and playlists

Approved scopes are exactly:

```text
youtube.upload
youtube.readonly
```

Tokens with extra scopes (`youtube`, `drive`, etc.) are rejected. The uploader records `playlistId` but does not apply it. `playlistItems.insert` needs a broader scope and is intentionally outside this implementation.

## Credentials

Sources, in priority order:

1. environment variables;
2. per-channel JSON files outside Git;
3. legacy file fallback, read-only.

The legacy file is parsed in memory. It is never copied or rewritten.

## Logging

Logs are written under the configured log root and passed through a redaction filter for:

- `client_secret`, `refresh_token`, `access_token`, `authorization`;
- `Bearer` tokens;
- Google access-token, refresh-token, and client-secret prefixes.

## Quota

Current official limits per project:

- `videos.insert`: 100/day, separate bucket, cost 1.
- `search.list`: 100/day, separate bucket, cost 1.
- Other endpoints: 10,000 units/day.
- Reset at midnight Pacific Time.

The three channels share one project, so they share the 100-upload daily limit. Three daily uploads are well within quota.
