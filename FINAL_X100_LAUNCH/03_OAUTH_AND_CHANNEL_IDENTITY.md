# 03 — OAUTH AND CHANNEL IDENTITY

**Status: IMPLEMENTED BUT NOT VERIFIED. BLOCKED on owner-supplied secrets.**

The implementation exists and is dependency-free: per-channel credential resolution by prefix,
`expected_channel_id` verification after the token is exchanged, redacted `__repr__`/`public_dict`, fail-closed
behaviour when a credential is absent or partial, and rejection of a token that belongs to another channel
(covered by `tests/factory/test_security.py`).

## The nine secret names the code looks for

| Channel | Secrets |
| --- | --- |
| Nexus Node | `YT_NEXUS_NODE_CLIENT_ID`, `YT_NEXUS_NODE_CLIENT_SECRET`, `YT_NEXUS_NODE_REFRESH_TOKEN` |
| Academic Biohacker | `YT_ACADEMIC_BIOHACKER_CLIENT_ID`, `YT_ACADEMIC_BIOHACKER_CLIENT_SECRET`, `YT_ACADEMIC_BIOHACKER_REFRESH_TOKEN` |
| Natkhat Toons | `YT_NATKHAT_TOONS_CLIENT_ID`, `YT_NATKHAT_TOONS_CLIENT_SECRET`, `YT_NATKHAT_TOONS_REFRESH_TOKEN` |

Current state: `gh secret list` returns **`[]`**. No OAuth exchange, no token refresh, and no channel
identity check has ever run against the real API, so no claim of authenticated identity is made for any
channel.

Owner actions: create the OAuth client, run `python -m uploader.cli consent --channel <slug>` once per
channel, store the nine secrets, and confirm the OAuth consent screen is **In production** — in Testing
mode refresh tokens expire after 7 days, which would silently break an unattended schedule.
