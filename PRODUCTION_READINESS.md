# PRODUCTION_READINESS

Status rubric: **VERIFIED** (executed and inspected) · **PARTIALLY VERIFIED** ·
**IMPLEMENTED BUT UNTESTED** · **BLOCKED** · **NOT IMPLEMENTED**.

Snapshot: 2026-11-21, branch `feat/landscape-16x9` (base `main` @ `567e63c`).

## 1. Subsystem status

| Subsystem | Status | Evidence / gap |
| --- | --- | --- |
| YouTube uploader (OAuth, identity, ledger, dedupe) | **VERIFIED** | 50 unit tests, 3 live private uploads in an earlier session, channel pre/post checks |
| Publishing safety gates | **VERIFIED** | 5 gate tests: default dry-run, `FACTORY_ALLOW_UPLOAD`, `FACTORY_ALLOW_SCHEDULE`, `--confirm-channel`, private-by-default |
| Shorts pipeline 9:16 | **VERIFIED** | 9 Shorts rendered (incl. one auto-generated plan and one auto-generated episode), each `qc_ok: true` |
| Natkhat studio (PyCairo rigs, TTS, subtitles) | **VERIFIED** | `natkhat-haveli-e1` 32.07 s and `-e4` 31.63 s, 1080x1920, audio present |
| Long-form pipeline 16:9 | **PARTIALLY VERIFIED** | One real 116.5 s render inspected on 12 frames + contact sheet. Quality is motion-graphics grade, not character animation |
| Plan generation (topic banks) | **VERIFIED** | `factory plan new`, 6 topics/channel, duplicate + exhaustion guards tested |
| Natkhat series continuity | **VERIFIED** | Order guard raises on unpublished predecessor; rollover to `natkhat-jungle` unit-tested |
| Audio mixing / narration | **VERIFIED** (locally) | −14.15 LUFS / −1.24 dBTP / LRA 2.0 after the loudness fix, sidechain ducking, duration preserved to 9 ms, 4 CI tests |
| Subtitles | **VERIFIED** (locally) | 52 cues, word-accurate text, timings from Edge-TTS word boundaries |
| Technical QC gate | **VERIFIED** | geometry, codec, duration, loudness, title/tags/description, thumbnail, SRT checks; failures block publish |
| Visual/editorial QC | **PARTIALLY VERIFIED** | Human frame inspection only; no automated visual scoring, no character-consistency metric |
| Research + script engine | **PARTIALLY VERIFIED** | Deterministic authored banks with sources; no live research/fact-check stage |
| GitHub Actions production | **BLOCKED** | `produce-*` disabled; PR #2 (installer hardening) unmerged; never dispatched successfully |
| Runner dependencies (PyCairo/ffmpeg/Chrome) | **PARTIALLY VERIFIED** | CI factory job proves PyCairo + ffmpeg + tests on the runner; full render never ran there |
| Edge-TTS on the runner | **UNVERIFIED** | package installs; network egress never exercised |
| YouTube secrets in Actions | **BLOCKED** | `YT_<PREFIX>_*` not provisioned; needs owner |
| Durable state (beyond Actions cache) | **NOT IMPLEMENTED** | Cache-only today; 7-day eviction risk |
| Central job orchestrator with checkpoints | **PARTIALLY VERIFIED** | Per-episode checkpoints exist inside `studio`; no job table / resume-from-stage across workflow restarts |
| Monitoring dashboard | **NOT IMPLEMENTED** | `analytics_for` can read view counts; no report/dashboard |
| 16:9 + 9:16 shared animation framework | **PARTIALLY VERIFIED** | Shared primitives + two composition profiles; not yet a component library (no character rig in landscape) |

## 2. Acceptance-test scorecard (directive §S)

| # | Test | Result |
| --- | --- | --- |
| 1 | Nexus Short | VERIFIED (earlier artifact) |
| 2 | Academic Short | VERIFIED (`academic-post-meal-walk`, auto-planned) |
| 3 | Natkhat Hindi Short | VERIFIED (`natkhat-haveli-e4`, auto-planned) |
| 4 | Nexus 16:9 | **VERIFIED** (`long-nexus-power-grid`) |
| 5 | Academic 16:9 | NOT IMPLEMENTED (no long plan authored yet) |
| 6 | Natkhat 16:9 | NOT IMPLEMENTED (Hindi long-form composition absent) |
| 7 | Frames/contact sheets inspected | VERIFIED (9:16 and 16:9) |
| 8 | Audio quality | VERIFIED locally — EBU R128 measured at −14.15 LUFS, 4 automated tests |
| 9 | Subtitles | VERIFIED locally |
| 10 | Character consistency | PARTIALLY VERIFIED (same rigs across 4 Natkhat episodes; no metric) |
| 11–15 | Runner deps (Edge-TTS, Chrome, ffmpeg, PyCairo) | PARTIALLY VERIFIED — PyCairo/ffmpeg/Chrome install provable in logs, full render not |
| 16 | Persistence after termination | NOT EXECUTED |
| 17 | Retry/recovery drill | NOT EXECUTED |
| 18 | Duplicate-upload prevention | VERIFIED by unit test, not by a live duplicate attempt |
| 19 | Channel authentication | VERIFIED earlier (3 private uploads), not in Actions |
| 20 | Controlled upload after authorization | NOT EXECUTED — needs owner approval |

## 3. Honest assessment

The factory can produce and inspect real videos locally, for both aspect ratios, with
passing technical QC. It cannot yet run unattended in the cloud: the production workflows
have never completed a dispatch, the renderer has never been exercised on a runner, and
there is no durable state beyond Actions cache.

Visual quality is "clean motion graphics" for Nexus/Academic. It is **not** the expressive
2D character animation described in §E of the directive: Natkhat has procedural rigs, but
landscape long-form has no characters at all, and there is no squash/stretch, anticipation
or reaction-shot library.
