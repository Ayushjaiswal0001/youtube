# X100 private upload checklist

One private video per channel, validated by the owner, with nothing published and nothing scheduled.
Every step here has been exercised in a dry run or a mocked test; the only step this document cannot
promise is the one it exists for, which is the real upload.

Read §0 before touching anything.

---

## 0. Preconditions the owner must confirm

| # | precondition | how to confirm | state today |
|---|---|---|---|
| 0.1 | OAuth consent screen is **In production** (not "Testing") | Google Cloud console → APIs & Services → OAuth consent screen | **OWNER-BLOCKED** — not verifiable from here |
| 0.2 | The Desktop OAuth client is the one in use | `python -m uploader.cli consent --check-only --channel nexus-node` | not run — needs the client JSON |
| 0.3 | Nine repository secrets exist | `gh secret list` (names only) | 9 present: `YT_{NEXUS_NODE,ACADEMIC_BIOHACKER,NATKHAT_TOONS}_{CLIENT_ID,CLIENT_SECRET,REFRESH_TOKEN}` |
| 0.4 | Each refresh token is bound to exactly one channel | `python tools/check_oauth_identity.py --channel all` | **NOT VERIFIED** — requires a live token exchange |
| 0.5 | `FACTORY_ALLOW_UPLOAD=1` is set only by the upload step | `produce.yml` sets it in the upload step's `env:` | verified: `produce.yml:378` |
| 0.6 | Repository variables | `gh variable list` | 0 variables — the workflow passes everything explicitly, so none are needed |
| 0.7 | Upload switches | `produce.yml:115-117` | `UPLOAD_ENABLED=false`, `SCHEDULED_PUBLISHING_ENABLED=false`, `PUBLICATION_APPROVAL_REQUIRED=true` |

Nothing below uploads until §3 is executed, and §3 requires the owner's explicit go-ahead.

## 1. Which video to use

The safest first upload is a **Short that already passed the gate in this session**, because its QC
report, framing report and manifest are all on disk and can be compared with what YouTube receives.

| channel | recommended episode | why | fallback |
|---|---|---|---|
| Nexus Node | first unpublished `nexus-*` plan with `qc.json ok` and `gate ok` | English diagram channel, smallest file (≈8 MB), captions in English | any rendered `nexus-*` |
| Academic Biohacker | first unpublished `academic-*` plan with `qc.json ok` and `gate ok` | English, paper palette, academic pictograms | any rendered `academic-*` |
| Natkhat Toons | `natkhat-haveli-e1` | Hindi, the only engine with rigged characters, and `madeForKids` is forced here | `natkhat-haveli-e2` |

You do not need to choose by plan id: the workflow resolves the next unpublished plan itself, and
`publish` refuses anything the gate rejects.

Alternatively use the long-form episode (`long-nexus-power-grid` or `long-academic-study-protocol`,
1920×1080). The uploader now accepts both 1080p profiles — that was a real blocker fixed in PR #17 — but
the first upload should be the smaller, better-understood file.

## 2. Expected artifact for each channel

| | Nexus Node | Academic Biohacker | Natkhat Toons |
|---|---|---|---|
| channel id | `UCx9O8VivWkiEylDjs5_Zzag` | `UCr8jSmLa_o2BwNh8HuyZHAQ` | `UC4OCY0qDwQqFnSCZw12sKxA` |
| handle | `@nexusnode012` | `@academicbiohacker` | `@NatkhatToons-n5` |
| geometry | 1080×1920 | 1080×1920 | 1080×1920 |
| duration | ≈36–39 s | ≈38 s | ≈32–34 s |
| video codec | h264 / aac | h264 / aac | h264 / aac |
| loudness | −14.3 LUFS, ≤ −2.2 dBTP | −14.3 LUFS, ≤ −2.2 dBTP | similar, measured per episode |
| language | en | en | hi (Devanagari captions) |
| captions | `captions.srt`, English | `captions.srt`, English | `captions.srt`, Devanagari |
| thumbnail | `thumbnail.jpg`, 1280×720 RGB, < 2 MB | same | same |
| category | 27 (Education) | 27 (Education) | 1 (Film & Animation) |
| tags | `shorts` | `shorts` | `shorts`, `kids` |
| privacy | **private** | **private** | **private** |
| made for kids | false | false | **true, forced by the channel config** |
| `notifySubscribers` | false | false | false |

Captions are produced in the build directory but the upload request **does not** attach them: the
current implementation uploads the video and the thumbnail only. That is a real gap; if captions must be
attached, that is new work, not a configuration change.

## 3. The one command that performs the upload

Only after §0.1–§0.4 are confirmed. This is the manual workflow, one job per channel, so each job receives
only its own three secrets:

```bash
env -u GITHUB_TOKEN gh workflow run "production (manual)" \
  --repo Ayushjaiswal0001/youtube \
  -f channel=nexus-node \
  -f format=shorts \
  -f mode=render+validate \
  -f upload=true
```

`upload=true` is the only thing that arms the upload step; the step itself is additionally gated on
`steps.creds.outputs.ready == '1' && steps.gate.outputs.ok == '1'`, and `factory.cli publish` adds
`FACTORY_ALLOW_UPLOAD=1` and `--confirm-channel <slug>` before it will upload.

To validate an episode that is already rendered in a build directory, without the workflow:

```bash
FACTORY_BUILD_DIR=<build> FACTORY_STATE_DIR=<state> \
python -m factory.cli publish --channel nexus-node --plan-id <plan>            # dry run, no upload
FACTORY_ALLOW_UPLOAD=1 python -m factory.cli publish --channel nexus-node \
  --plan-id <plan> --execute --confirm-channel nexus-node                      # real, private
```

## 4. What the API should return

A successful private upload returns a `PreparedUpload` public dict plus the ledger entry:

```json
{
  "status": "uploaded",
  "channel_slug": "nexus-node",
  "video_id": "<11-char id>",
  "privacy_status": "private",
  "made_for_kids": false,
  "upload_performed": true,
  "scheduled": false,
  "duplicate_check": "clear",
  "gate": {"ok": true, "passed": 24, "total": 24},
  "identity": {"token_channel_id": "UCx9O8VivWkiEylDjs5_Zzag", "matches": true}
}
```

Failure shapes that are safe and expected:

| result | meaning | what to do |
|---|---|---|
| `WrongChannelError` | the token belongs to a different channel than the config | stop; do not retry; fix the credentials |
| `DuplicateUploadError` | that exact sha256 is already in the ledger | expected on a repeated run; nothing to do |
| `uploading`/`unknown` | the API result was lost after the request was sent | **never blind-retry**; check Studio first |
| `failed` | the API rejected the upload | read the error; a retry is safe only for a `failed` entry |
| gate `ok: false` | the artifact failed the publishing gate | nothing was uploaded; the video stays in the build |

## 5. What YouTube Studio should show

1. Studio → the correct channel is selected in the account switcher (this is the identity check you are
   making by eye).
2. Content → the video is listed with **Visibility: Private**.
3. The title matches `script.json` `title` exactly.
4. Duration matches `render.json` `duration` to within a second.
5. Thumbnail is the generated card, not a YouTube auto-frame.
6. For Natkhat: the audience row says **"Made for kids: Yes"**, and comments are disabled as a
   consequence. If it says No, stop — `made_for_kids` did not survive.
7. Audio plays with Hindi (Natkhat) or English speech and the music bed underneath.
8. No copyright claim banner.

## 6. Verification checklist

- [ ] `gh run view <run-id> --log` shows `Export channel credentials` succeeded and
      `Verify channel identity before upload` matched the configured channel id.
- [ ] `publish.json` (artifact) has `"upload_performed": true` and `"status": "uploaded"`.
- [ ] The ledger has exactly one new `uploaded` line:
      `.state/youtube/<channel>/ledger.jsonl` (workflow) or `$YT_STATE_ROOT/<channel>/ledger.jsonl`.
- [ ] The video id in the ledger equals the video id in Studio.
- [ ] Studio shows Private, correct title, correct thumbnail, correct made-for-kids.
- [ ] Re-running the same plan uploads nothing and reports `DuplicateUploadError` /
      `duplicate_check: not clear` — this is the duplicate-prevention proof.
- [ ] `python -m uploader.cli status --channel <slug>` reports the episode as uploaded.

## 7. Rollback

1. **Delete the video in Studio** (Content → the video → Delete forever). A private upload has no audience,
   so this is safe.
2. **The ledger keeps its `uploaded` entry.** It is an append-only JSONL file and that is deliberate: it
   records what was sent to YouTube. Do not edit it to "un-upload"; a re-render produces a different
   sha256 (TTS is not deterministic), so a corrected episode uploads normally.
3. If the ledger must be reset for a channel, do it by hand, offline, with the file open:
   `.state/youtube/<channel>/ledger.jsonl` — copy it aside first, then remove only the line whose
   `video_id` you deleted. This is a manual, audited action; no command does it for you.
4. Revert any repository change with `git revert <sha>` — never `git reset --hard` on `main`.

## 8. What is still not verified, and cannot be, from here

- That the consent screen is in production.
- That the nine secrets work (they have never been used).
- That the token is bound to the right channel (unit tests cover the logic, not the live token).
- That YouTube accepts the metadata (title/description/tags/category/kids flag).
- Caption attachment, because the implementation does not attempt it.

Everything else in this checklist was executed on 2026-11-25 against real encoded artifacts, with
`upload_performed: false` every time.
