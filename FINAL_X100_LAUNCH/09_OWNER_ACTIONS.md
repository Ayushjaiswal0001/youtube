# 09 — OWNER ACTIONS

Nothing below was performed by this session, and nothing below can be performed without owner rights.

1. **Merge PR #3** (`feat/landscape-16x9` into `main`). Required before any cloud run: `production.yml`
   returns 404 on `main`. GitHub: open PR #3, then "Merge pull request". PR #4 (pillow 13.0.0) is
   independent and can be merged or closed afterwards.
2. **Create the Google OAuth client and consent screen**, then for each channel run
   `python -m uploader.cli consent --channel <slug>` locally and store the nine secrets
   (`YT_<PREFIX>_CLIENT_ID`, `_CLIENT_SECRET`, `_REFRESH_TOKEN`). Set the consent screen to **In production**;
   in Testing mode refresh tokens expire after 7 days and an unattended schedule would break silently.
3. **Approve the first cloud run** after the merge:
   `gh workflow run production.yml --ref main -f channel=natkhat-toons -f mode=render+validate -f upload=false`,
   then repeat for `nexus-node` and `academic-biohacker`.
4. **Approve one private upload per channel** (Stage B). Until then `UPLOAD_ENABLED=false`,
   `SCHEDULED_PUBLISHING_ENABLED=false` and `PUBLICATION_APPROVAL_REQUIRED=true` stay as they are.
5. **Configure a notification webhook** if failure alerts are wanted: `FACTORY_NOTIFY_WEBHOOK`. Without it
   notifications are a silent no-op, and delivery stays unverified.
6. **Enable the two secret-scanning toggles and code scanning** in Settings, Code security. The API accepts
   the request but the flags stay disabled with this account.
7. **Approve schedule activation**, and only after items 1 to 5 pass. Three crons are `disabled_manually`.
8. **Never** paste a client secret, refresh token or authorization code into chat, an issue, or a commit.
   The repository is public.
