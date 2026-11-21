# PRODUCTION_READINESS

Status rubric: **VERIFIED** (executed and inspected) · **PARTIALLY VERIFIED** ·
**IMPLEMENTED BUT UNTESTED** · **BLOCKED** · **NOT IMPLEMENTED**.

Snapshot: 2026-11-21, branch `feat/landscape-16x9` (base `main` @ `567e63c`).

### Character animation capability (after T30/T31/T32/T33)

| Capability | Status | Evidence |
| --- | --- | --- |
| Character definitions as data | VERIFIED | two JSON files, strict validation, 31 schema tests, 8 byte-identical golden frames |
| Per-pose drawing pinned | VERIFIED | 78-frame pose golden set (`tools/capture_goldens.py`) |
| Audio-driven mouth amplitude | VERIFIED | envelope from narration, 0.06 silence gate, 10 lipsync tests |
| Viseme mouth shapes with timing | PARTIALLY VERIFIED | sentence-window approximation; placement is proportional, not phoneme-accurate |
| Eyelids, blinks, saccades, gaze, expressions | VERIFIED locally | 32 tests, 28/20 blinks per minute, gaze moves measured, blink strip inspected |
| Loudness on the Shorts path | VERIFIED locally | -24.3 → -14.0 LUFS, -1.4 dBTP, QC gate added |
| Reaction beats from dialogue (nods, recoils, bounces) | VERIFIED locally | 33 tests, 23 beats measured, eye-centroid shift 22 px during a recoil, kill switch |
| Body locomotion (16 motions) | VERIFIED locally | 25 tests, real 5-scene demo render inspected |
| Characters in the 16:9 renderer | NOT IMPLEMENTED | long-form draws diagrams/cards only |
| Character-to-character interaction (grab, hand-off, group) | NOT IMPLEMENTED | proximity is staged by positions only |
| Speech-driven body gestures | NOT IMPLEMENTED | gestures are scene-authored, not derived from dialogue |

Nothing here is production-verified: no scheduled job has run on GitHub with these commits,
and no upload has been made since the earlier verified uploads.


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

## 3. Character animation audit (evidence-based)

`studio/characters/rig_base.py` is a real rig foundation: `JointNode` world matrices,
Cairo draw primitives (ellipse, capsule), easing functions (`ease_in_out_quad`,
`spring_overshoot`, `ease_out_bounce`) and a `Viseme` enum. `ChikuRig.update_pose()` drives
`blink_t`, `eyebrow_tilt`, `eyebrow_y`, `viseme`, `mouth_open`.

| Capability | Status | Evidence |
| --- | --- | --- |
| Reusable rigs | **PARTIAL** | One class per character (`ChikuRig`, `GappuRig`); no shared parameter schema, no data-driven character definitions |
| Facial expressions | **PARTIAL** | Pose presets, no expression blend tree or FACS-style channels |
| Eye + eyebrow movement | **PARTIAL** | `blink_t` cycles on a 3.2 s timer, `eyebrow_tilt`/`eyebrow_y` are settable; no saccades, no gaze targets |
| Mouth shapes / lip-sync | **VERIFIED for envelope + viseme timing** | `lipsync.py` (envelope) + `visemes.py` (text→viseme, 9 shapes, Hindi + English, min-hold/median/coarticulation). Rendered episode: 6.2–7.1 shape changes/s, onset lag median 0 ms / max 67 ms, 93.3 % mouth activity during voiced audio. **Word/phoneme timing unavailable** from Edge-TTS (verified: sentence boundaries only), so in-sentence placement is proportional |
| Body gestures | **PARTIAL** | Pose presets only (`update_pose(pose, t, …)`), no procedural arm IK |
| Walk / run cycles | **NOT FOUND** | no locomotion module in `studio/` |
| Emotional reactions | **PARTIAL** | pose + easing primitives exist; no reaction library, no anticipation/settle |
| Character interactions | **NOT FOUND** | no two-character blocking or eye-line system |
| Animated environments | **PARTIAL** | `studio/background.py` + repo scene backgrounds; no layered parallax rig |
| Appearance consistency | **VERIFIED (4 episodes)** | same rig across `natkhat-haveli-e1…e4`, reviewed in frames; no automated metric |
| Characters in 16:9 long-form | **NOT IMPLEMENTED** | `grep -cE "draw_(face|eye|mouth|character)" factory/media/landscape_renderer.py` → **0** |

The directive's §E target (professional 2D character animation) is therefore **not met**;
today's landscape output is motion graphics, and Natkhat's mouth movement is a sine wave.

## 4. Publishing-readiness audit

| Area | Status | Evidence |
| --- | --- | --- |
| OAuth per channel | **IMPLEMENTED** | `uploader/credentials.py` reads `YT_<PREFIX>_*` (client id/secret/refresh token), `oauth.py` refreshes, `ScopeError`/`OAuthError` are typed failures |
| Channel identity check | **VERIFIED** | `WrongChannelError` + `--confirm-channel` comparison; 3 live uploads verified the right channels in an earlier session |
| Duplicate prevention | **VERIFIED** | `ledger.py` stores `video_sha256`/`metadata_sha256`, `assert_no_duplicate()`, `DuplicateUploadError` stops repeats |
| Unknown state hard stop | **VERIFIED** | `UploadStateUnknown` exists for a lost response, so the run stops instead of re-uploading |
| Transient-error retry | **IMPLEMENTED, PARTIALLY VERIFIED** | `uploader/retry.py::retry_call(attempts=3, retry_after)` used by `router.py`; `youtube.py` marks 429/5xx `retryable=True`, handles resumable `308`. No test forces a 500 and asserts the retry actually fires |
| Quota handling | **RISK** | no `quotaExceeded` mapping found in `errors.py`; if all three channels share one Google Cloud project, the 100 uploads/day quota is shared (3/day is fine, but a retry storm is not) |
| Refresh-token longevity | **UNKNOWN — owner action** | in OAuth "Testing" mode refresh tokens expire after 7 days; status of the three credentials is unverified. Must be "In production" or refreshed by a human |
| Secrets in Actions | **BLOCKED** | `YT_<PREFIX>_*` not provisioned; `gh api …/actions/secrets` returns 403 for the token in use |
| Scheduling / public release | **DISABLED BY DESIGN** | `FACTORY_ALLOW_UPLOAD`, `FACTORY_ALLOW_SCHEDULE`, private-by-default, Natkhat `madeForKids` forced |

## 5. Honest assessment

The factory can produce and inspect real videos locally, for both aspect ratios, with
passing technical QC. It cannot yet run unattended in the cloud: the production workflows
have never completed a dispatch, the renderer has never been exercised on a runner, and
there is no durable state beyond Actions cache.

Visual quality is "clean motion graphics" for Nexus/Academic. It is **not** the expressive
2D character animation described in §E of the directive: Natkhat has procedural rigs, but
landscape long-form has no characters at all, and there is no squash/stretch, anticipation
or reaction-shot library.

## Frame rate and container conformance

| Item | Status | Evidence |
| --- | --- | --- |
| Delivered frame rate is exactly 30 | VERIFIED | `avg_frame_rate = 30/1` after `-r 30 -fps_mode cfr`; was 29.969 |
| Frame rate is gated by QC | VERIFIED | `frame_rate True - 30.00 fps, expected 30`; 19/19 checks pass |
| Full decode of the delivered file | VERIFIED | `ffmpeg -v error -i video.mp4 -f null -` produced no output |
| Frame-rate stability across scenes | PARTIALLY VERIFIED | one 5-scene episode measured; 1 duplicate frame in the first 12 s |

## Two-character interaction

| Item | Status | Evidence |
| --- | --- | --- |
| Bodies cannot overlap | VERIFIED (unit) / guard only | clamp to 210 px, symmetric; not reached by shipped motions |
| Speaker gestures toward partner | RENDER-VERIFIED | probe render of both rigs; rendered episode inspected at gesture peaks |
| Listener reacts | RENDER-VERIFIED | lean/tilt layer visible in rendered episode |
| Facing flips when a partner is behind | IMPLEMENTED BUT UNTESTED | unit tests only; no scene exercises it |
| Gesture survives a close-up camera | NOT IMPLEMENTED | camera plan can crop the partner out |
| Hand-off / object contact | NOT IMPLEMENTED | not started |

## Camera and framing

| Item | Status | Evidence |
| --- | --- | --- |
| Subject geometry from one source (schemas) | VERIFIED | 35 framing tests; pre/post camera parity 42/42 frames |
| Planned shots keep required subjects in frame | VERIFIED | 0 required-subject cropped frames across the rendered episode |
| Gestures never cropped | VERIFIED | shots reserve full arm reach; 0 gesture frames cropped |
| Automatic wide/medium/close-up choice | VERIFIED | escalation unit-tested; the natkhat episode keeps its scripted shots because all of them are valid |
| Close-up points at the performing character | VERIFIED | regression test; a mismatch widens the shot |
| Abrupt zoom jumps prevented | VERIFIED | peak 1.07/s vs 1.60/s ceiling; QC gate `framing_continuity` |
| Background magnifies with the camera | VERIFIED | rendered episode inspected; scene 2's window scales with the close-up |
| 9:16 composition | VERIFIED | rendered episode |
| 16:9 composition | GEOMETRY VERIFIED, NOT RENDERED | fit/shot tests at 1920x1080; the landscape renderer draws no characters yet |
| Screen shake inside the framing model | NOT IMPLEMENTED | shake is applied in `Camera.apply` after planning |
| Object-aware co-visibility (hand-off) | PARTIAL | `interaction: contact` scene key forces a pair shot; no object tracking |

## Props and object interaction

| Item | Status | Evidence |
| --- | --- | --- |
| Hand position matches the drawn hand | VERIFIED | pixel probe within 0.7-2.1 px, both rigs, both sides |
| Prop follows the holding hand | VERIFIED | 28 prop tests; rendered hand-off demo |
| Hand-off crosses continuously | VERIFIED | peak 41 px/frame over a 400 px / 0.5 s crossing |
| Prop is framed by the camera | VERIFIED | shot widened for the prop; 0 cropped frames in the demo |
| Held prop clear of the caption band | VERIFIED (measurable) | 117 -> 0 occluded frames; QC `prop_visibility` |
| Arm-only clearance when the band is unreachable | NOT SOLVED | solver returns 0; camera lift compensates |
| Pick-up from a world position | NOT IMPLEMENTED | `contact_error` exists for timing it |
| Object-specific grips / two-handed props | NOT IMPLEMENTED | one grip offset, right/left only |

## Landscape (16:9) character production

| Item | Status | Evidence |
| --- | --- | --- |
| Native 16:9 character rendering | VERIFIED | 1920x1080, 30/1, three artifacts rendered and inspected |
| Identity preserved (no stretching) | VERIFIED | same rigs, same scale, same art as 9:16 |
| Viseme lip-sync in 16:9 | VERIFIED | mouths change per frame in inspected frames |
| Blink, gaze, locomotion, performance beats | VERIFIED | shared engine; framing reports show gesture frames |
| Two-character interaction and hand-off | VERIFIED | prop track + interaction plan run in the stage renderer |
| Character-aware framing | VERIFIED | 0 cropped required subjects; escalations logged per scene |
| Landscape camera vocabulary | PARTIAL | establishing, tracking, subject-medium, reaction, hold exist; cut-to-cut eyeline matching does not |
| Multi-layer environment, parallax, atmosphere | VERIFIED | sky, ridge x2, mid scenery, haze, ground, motes, foreground |
| Contact shadows and lighting | PARTIAL | soft contact shadow + moon glow + rim light; no directional cast shadows |
| Caption and title overlays | VERIFIED | QC measures the band; 0 face collisions |
| QC coverage for landscape | VERIFIED | 24 checks including frame_rate, av_sync, frozen_frames, subtitle_collision, prop_visibility |
| Portrait regression safety | VERIFIED | frame-identical (963/963) to the pre-T41 render |
| Wired into the publish orchestrator | NOT IMPLEMENTED | `render-stage` is a separate command |

## Production orchestration (T46)

| Item | Status | Evidence |
| --- | --- | --- |
| One pipeline for 9:16, 16:9 stage and 16:9 cards | VERIFIED | `resolve_engine` + one post-render path; three engines resolved correctly on real plans |
| Shared thumbnails/subtitles/QC/state | VERIFIED | `render-stage` is now an alias; no duplicate post-render code |
| Idempotent re-run | VERIFIED | second run: 0 rendered, 12 reused, 16 s, identical sha256 |
| Interrupted-render recovery | VERIFIED | deleted scene + output restored by `resume`: 1 rendered, 11 reused, identical sha256 |
| Atomic artifact finalization | VERIFIED | failed join left the previous verified video intact; partial file removed |
| Scene-level state with input signatures | VERIFIED | 34 orchestration tests; signature covers poses, fades, stage, audio take |
| Reproducibility across a cache invalidation | VERIFIED | full re-render after the signature change reproduced the same sha256 |
| Portrait regression | VERIFIED | `0fac3ab3...`, 963/963 frames identical |
| Disk-space / memory guards, locking, retry policy | NOT IMPLEMENTED | T49 |
| Landscape episodes in the publish path | NOT IMPLEMENTED | `publish` untouched |

## Conversational cinematography (T42)

| Item | Status | Evidence |
| --- | --- | --- |
| Shots derived from dialogue ownership | VERIFIED | 30 tests; re-ordering lines re-orders shots |
| Shot/reverse-shot across a conversation | VERIFIED | Haveli episode alternates medium_chiku/medium_gappu by speaker |
| Listener never framed while the speaker talks | VERIFIED | QC gate + rendered scene 11 inspected |
| Reverse coverage of long speaker runs | VERIFIED | validator flags a run with one subject |
| Location change cuts wide | VERIFIED | rule + test |
| Episode opens on the space | VERIFIED | rule + test |
| Axis of action (screen side) | PARTIAL | sides are fixed from stage anchors and validated; head-turn geometry is not modelled |
| Close-ups earned, not sprayed | VERIFIED | tenure + beat + density rules, all tested |
| Cuts inside a line | NOT IMPLEMENTED | one camera per scene |
| Three-character scenes | NOT IMPLEMENTED | no three-shot vocabulary |

