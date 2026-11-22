# FINAL_LAUNCH / BASELINE_AUDIT.md

Verified 2026-11-22, before any change in this assignment. Nothing here is carried over from an earlier
report without re-checking it.

## Repository

| Fact | Value | How it was verified |
| --- | --- | --- |
| Branch | `feat/landscape-16x9` | `git branch --show-current` |
| HEAD at start | `b16e7f6` | `git log -1` |
| Working tree | clean | `git status --porcelain` (0 lines) |
| Remote | `https://github.com/Ayushjaiswal0001/youtube.git` | `git remote -v` |
| Identity | `Ayushjaiswal0001` | `gh api user --jq .login` with `env -u GITHUB_TOKEN` |
| `main` | `567e63c` | `git log origin/main -1` |
| Divergence | 0 ahead / 0 behind | `git rev-list --left-right --count FETCH_HEAD...HEAD` |

## Pull requests

| PR | State | Mergeable |
| --- | --- | --- |
| #1 | MERGED | — |
| #2 runner install robustness | OPEN | MERGEABLE |
| #3 native 16:9 engine (the principal work) | OPEN | MERGEABLE |
| #4 Dependabot pillow 13.0.0 | OPEN | MERGEABLE (redundant once #3 lands) |

## What exists, re-verified rather than assumed

- **Channels**: `channels/{nexus-node,academic-biohacker,natkhat-toons}.json`, each with its own
  `expected_channel_id`, handle, language, format, palette, voice and publish time.
- **Planning**: topic bank plus series bible; `plan new --channel` enforces series order and avoids
  duplicates against production history.
- **Script and metadata**: English and Hindi builders, descriptions with sources and tags, story packet.
- **Rendering**: `resolve_engine` picks the portrait renderer or the landscape stage; both are driven
  from the same CLI and produce a `framing.json`, `qc.json` and manifest.
- **Animation engine**: camera and in-line cuts, shot plan, framing, continuity, ownership, pickup + IK +
  crouch, lighting presets, set dressing with measured occlusion, world-depth compositing.
- **QC**: 27 technical checks on a 64.5 s episode (continuity, pickup contact, framing continuity, audio
  loudness, frozen frames) and 24 publishing-gate checks enforced on `--execute`.
- **Reliability**: 11-state job journal, lock, preflight, retry classification, atomic media
  finalisation, resume; JSONL job log and resource monitor.
- **Publishing**: dependency-free uploader with per-channel credential prefixes, identity verification
  against `expected_channel_id`, and a SHA-256 dedupe ledger.
- **Cloud**: reusable `produce.yml`, three per-channel callers whose crons are **disabled**,
  `production.yml` (`workflow_dispatch` only), `security.yml`, `ci.yml`.
- **Security**: secret scanning and push protection on, Dependabot on, SHA pinning required, `main`
  protected, local scanner + Gitleaks config + workflow auditor + dependency auditor + credential
  blocker.

## Missing at the start of this assignment

1. **No research engine.** Topics came only from hand-authored banks; nothing fetched a source, scored
   freshness or relevance, or deduplicated against what had already been produced.
2. **No source ledger** for claims, so "where did this come from" had no answer beyond memory.
3. **No `FINAL_LAUNCH/` documentation set**, including this audit.

## Inherited defects, unchanged here

- Hand-off staging overlaps the two drawn bodies (arm length against body width) —
  `ANIMATION_QUALITY_REPORT.md`.
- Three-character scenes and their eyeline geometry are not implemented.
- No clean 10-minute episode: the 650 s benchmark failed QC because its plan repeated pickups.
- Cloud execution has never run, no upload has ever happened, 0 repository secrets.

## Baseline measurements

767 tests passed, 78 golden frames unchanged, secret scan 0/0, Gitleaks 0/0, dependency audit 0/0,
workflow audit 0 findings over 8 workflows, artifacts 0, crons 3× `disabled_manually`.
