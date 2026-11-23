# AI_HANDOFF

## 0. RESUME CHECKPOINT (2026-11-21, branch `feat/landscape-16x9`)

Read this block first; it is the exact state another agent needs.

| Fact | Value |
| --- | --- |
| GitHub identity in use | `Ayushjaiswal0001` (always run `env -u GITHUB_TOKEN gh …`) |
| Repository | `https://github.com/Ayushjaiswal0001/youtube` only — no fork, no second repo |
| Current branch | `feat/landscape-16x9`, based on `main` @ `567e63c` |
| `main` state | green CI; PR #1 merged earlier; **do not push to main** |
| PR #2 | OPEN, unmerged, 1 commit `2a810f0`, runner-install hardening. **Leave untouched until the owner approves.** |
| Workflows | `ci.yml` active; `produce.yml` active but reusable-only; the three `produce-*` are `disabled_manually` |
| Secrets | `YT_<PREFIX>_*` NOT provisioned → any `upload: true` dispatch will skip the upload with a warning |
| Tests | `python -m pytest tests -q` → **228 passed**; `python -m unittest discover -s tests` → 50 passed |
| Shorts plans | 13 plans intact (5 nexus, 5 academic, 3 natkhat), history/state untouched |
| Long-form plan | `content/longform/nexus-node.json` → `long-nexus-power-grid`, rendered (see below) |
| Publishing actions this session | **none** — no upload, no ledger write, no schedule enabled |

### Verified artifact of record (16:9)

`build/nexus-node/long-nexus-power-grid/video.mp4` — 1920x1080, h264 + aac 44.1 kHz stereo,
116.467 s, 3 494 video frames, 7 574 361 bytes, `qc_ok: true`, 52 SRT cues,
mean −29.2 dB / peak −11.4 dB, zero decode errors, no silence > 1 s.
Measured wall clock ≈ 8 min 45 s (≈ 4.5× real time) on the dev laptop.

### Known-open defects fixed in this branch

Body/caption collision; ghosting chapter cards; chapter kicker falling back to brand tag;
chapter cards firing on every line; motifs bleeding outside the plate; `find_plan` unable
to resolve a long-form plan; `load_plans_for` mixing formats.

### Audio (fixed after the first landscape render)

First mix measured **−26.53 LUFS** — inaudible next to normal YouTube content. The mix
stage now ducks the bed with `sidechaincompress` and applies a two-pass *linear*
`loudnorm` (I=−14, TP=−1.5, LRA=11) followed by an exact-duration trim/pad.
Verified on the real episode: **−14.15 LUFS, −1.24 dBTP, LRA 2.0**, audio/video length
delta 9 ms, remix 15.5 s. Tests: `tests/factory/test_audio.py` (4).

### Pull-request merge order (reviewed 2026-11-21)

| PR | Branch | Files | Mergeable | Touches `produce.yml` |
| --- | --- | --- | --- | --- |
| #2 | `fix/runner-install-robustness` | 1 (`.github/workflows/produce.yml`) | MERGEABLE | yes |
| #3 | `feat/landscape-16x9` | 14 (`factory/`, `content/`, `tests/`, docs) | MERGEABLE | **no** |

They are disjoint, so there is no conflict either way. Recommended order: **#2 first**
(it fixes the runner install that T12 needs), then **#3**. Both stay unmerged until the
owner approves.

### Conversational direction (T42)

`studio/animation/shot_plan.py` is the director. It is pure: scenes in, shot decisions out.

    plan = plan_conversation(scenes, anchors=[(name, world_x), ...])   # anchors fix the axis
    scenes = apply_plan(scenes, plan)                                  # only rewrites "auto"

`landscape_stage.render_stage_episode` runs it when any scene has `"camera": "auto"`, writes
`shot_plan.json` beside the video, and the validator's `shot_continuity` check reads that file.

Traps:

* **`medium_<name>` and `reaction_<name>` are single-subject shots.** They must be resolved before
  `plan_shot`'s relational widening loop, or they match the relational `medium` case and become
  two-shots. `_scripted_kind` calls this kind `subject_medium`; the hoisted branch has to accept that
  name.
* **A repeat is only a repeat in the same space.** Two wides either side of a location change are two
  different photographs.
* **A danda is a full stop, not a beat.** Beats are `?`/`!` at the end or an opening interjection.
  Using the danda made every Hindi line a close-up.
* **The scene cache hashes the engine source.** `engine_digest()` covers `studio/animation`,
  `studio/characters`, `studio/audio` and `content/characters`; a manual version string drifted
  within one commit. If you add a new module outside those paths that changes pixels, add the path.
* The plan is advisory in one direction only: it may leave a verified artifact alone. `--force`
  re-directs.

### Orchestration, idempotency and resume (T46)

`factory.cli` verbs, and what each one is for:

* `render --channel X --plan-id Y [--format shorts|long] [--formats a,b] [--scenes 1,2] [--demo]`
  - one plan, resolved to its engine by `resolve_engine`; `--formats` renders one plan in both.
* `status` - per plan: engine, artifact, QC verdict, and the scene cache census.
* `resume` - re-render only what is missing or stale; never touch a verified artifact.
* `validate` - re-run QC against an existing artifact without rendering.
* `render-stage` - kept as an alias for a `stage` plan; it refuses any other engine.

Traps:

* **One build directory.** `orchestrator.episode_out_dir()` and
  `landscape_stage.stage_story_id()` must agree; they did not, and `status` looked in a directory
  nobody wrote to. Never reintroduce a second formula.
* **Scene keys come from `plan_scenes`.** The authored key is `n`; `plan_scenes` normalises it to
  `scene_num` / `dialogue`. Reading the authored dict directly gets `None`.
* **The scene signature is a deny-list** of render-only fields, plus stage geometry, fades and the
  *audio file hash*. Adding a scene key is automatically covered; adding a render-only field means
  adding it to `render_only`.
* **A cached scene is only reused if it probes.** State alone is not enough: an MP4 truncated by a
  kill can still carry its state file.
* **Atomic joins** write `<name>.partial.mp4` and rename. `.mp4.partial` breaks ffmpeg's muxer
  inference.
* `_log` writes to stderr, but the studio renderer prints `[Render] ...` to stdout, so
  `render --json` output has log lines before the payload.

### Landscape character stage (T41)

`python -m factory.cli render-stage --channel natkhat-toons --plan-id X [--scenes 1,2] [--demo]`
renders a 16:9 character episode from a plan in `content/longform/<channel>.json` whose entry has
`"engine": "stage"` and an explicit `scenes` list.

Traps and invariants, in the order they bit:

* **Subject boxes are measured, never predicted.** `studio/animation/silhouette.py` renders the rig
  once per (class, pose, facing), caches the alpha bounds, and treats body motion as a translation
  plus a 14% pad. The old schema formula was 62% short and framed the authored anchor instead of the
  stage; do not reintroduce a proportions-based box.
* **Stage placement comes from `stage.py`.** `stage_for(width, height)` returns a measured stage or
  raises. Portrait carries the historical constants (that is why the goldens reproduce), landscape
  carries derived ones (ground 788, slots 600/1320, zoom floor 0.62).
* **Camera style prefixes are hazardous.** `medium_pan` (portrait) and `medium_<name>` (landscape
  subject shots) share a prefix; matching the prefix naively silently retimed every portrait scene.
  `_scripted_kind` and `_style_frame` both exclude `medium_pan` explicitly now.
* **Two renderers, one engine.** `SceneRenderer(width, height, stage=, environment=, foreground=)`
  takes the aspect-specific environment; rigs, faces, gaze, lipsync, motion, interaction, props and
  camera are shared. Do not fork the frame loop for 16:9.
* **Concat must re-time frames** (`-vf fps=30`) or AAC tails push each following scene late.
* **Caption geometry is measured by QC.** The overlay's opaque rectangle is the band; drawing a
  kicker above the band made the measured band 38 px too high and reported collisions on every
  frame. Keep every caption element inside the band rectangle.
* **Aggregated framing reports must be filtered by scene number**, or a short demo inherits the
  counts of a longer earlier render.
* The episode aggregate lands in `<out>/framing.json`; per-scene reports live beside the scene MP4s.

### Props (T40)

`studio/characters/props.py`, opt-in through scene keys: `prop`, `prop_holder`, `prop_side`,
`prop_handoff_to`, `prop_handoff_side`, `prop_handoff_at` (seconds, or a fraction <= 1),
`prop_handoff_duration`.

- `hand_point(rig, side, angle=None)` composes the rig's own transform stack. There is no
  separate arm-geometry table anywhere: if an arm pose changes, this follows it. Verified against
  rendered pixels within ~2 px by `tests/factory/test_props.py`.
- Loop order is now: bodies -> interaction -> `update_pose` -> hands/props -> camera (with the
  prop's box and any band lift) -> draw. Reading a hand before `update_pose` places the prop with
  last frame's arm.
- The caption band is measured from the subtitle PNG (`opaque_rect`), not from a constant. A
  held prop at hand height lands inside it; the renderer first raises the arm
  (`raise_arm_for_clearance`, searching both rotation directions because the rigs are mirrored),
  then lifts the frame by whatever remains, refusing the lift if it would crop a character.
- `occlusion` in `framing.json` records frames hidden / lifted / worst overlap, and QC gates it
  with `prop_visibility`.
- A prop is not cast: `plan_shot(extras=[box])` widens the frame for it without changing
  `shot.subjects`, so prop framing cannot quietly turn a close-up into a two-shot.

### Framing (T39)

`studio/animation/framing.py` owns geometry and shot choice; `camera.py` keeps the move.

- Subjects are built from the schemas (`subject_from_schema`). Do not reintroduce constants for
  where a character stands; `camera.subject_x()` reads the schema for exactly this reason.
- `plan_shot()` treats the script's style as a **request**: a close-up survives only if its
  subject is the character who is performing, and `medium`/`two_shot`/`wide` must hold the whole
  cast. Only widening is allowed, and a widened shot records `reason`.
- `Shot.zoom` is what the shot asks for; `Shot.limit` is the tightest zoom that still holds every
  required subject. The camera takes `min(style_zoom, limit)` so a push-in keeps moving but can
  never crop. Collapsing these two fields into one removes `two_shot_zoom`'s entire move.
- `fit_zoom()` returns an **upper bound**. `max()` against it is always a bug; use `min()`.
  `clamp=False` gives the raw geometric bound, which is what the fit guarantee refers to.
- `FramingReport` measures the frame the renderer will draw, using the same projection as
  `Camera.apply`. It is written per scene and aggregated to `framing.json` beside `video.mp4`.
  QC fails on cropped **required** subjects and warns about deliberately excluded ones.
- If a render fails with `video pipe failed` and no ffmpeg output, read the exception now
  included in the message - that path used to hide Python errors in the frame loop.
- Frame-loop order matters: bodies, then interaction resolve, then camera, then draw. The camera
  needs the resolved positions; moving it back before the bodies silently restores the "frames
  the anchor, not the character" defect.
- Environment switches: `FACTORY_CAMERA_FRAMING=0` (old camera), `FACTORY_CAMERA_ZOOM_BG=0`
  (background ignores zoom), `FACTORY_CAMERA_PAIR_LOCK=1` (force both characters into every shot;
  also triggered by a scene key `interaction: contact`).

### Interaction (T35b)

`studio/characters/interaction.py`, wired in `scene_renderer.py` once per scene
(`FACTORY_NO_INTERACTION=1` disables it).

- `resolve_separation()` keeps body centres at least **210 px** apart and is symmetric about the
  old centre of mass. `InteractionDirector.resolve()` returns the inputs **unchanged** when no
  clamp is needed; that is deliberate, because the round trip through `anchor + offset` perturbs
  `hip_x` by ulps and breaks golden-frame equality.
- Gestures are **additive**: `BodyState.arm_l_delta` / `arm_r_delta`, added by both rigs'
  `apply_body`. Never set `arm_l`/`arm_r` for a gesture -- those *replace* the pose's arms and
  turn every pose into the same T-pose.
- Direction convention, measured with a probe render: the rigs are mirrored by `facing`, so
  local +x is "in front" for both characters. **`arm_r_delta` negative is the forward pinion**;
  `arm_l_delta` slightly negative tucks the near arm. Do not "fix" the sign per character.
- `resolve()` clamps explain why the guard almost never fires: anchors are 400 px apart, the
  widest motion still leaves 400 px, so with shipped content the clamp is a guard.
- Untested in a rendered episode: facing flips (no scene puts a partner behind the other).
- Known interaction/camera conflict: a `close_up_*` camera can crop the partner out, so a
  character gestures into empty frame.

### Test portability (do not repeat this)

Never hard-code an absolute Windows path in a test. `Path("C:/Users/...")` is a *relative* path
on Linux, and ffmpeg reads `C:` as a protocol, so the file appears unopenable and code that
degrades gracefully (returning `{}`) hides the real cause. Use `tempfile.mkdtemp()`.

Related: `studio/audio/loudness.py` used `text[rfind("{") : rfind("}")+1]` to pull the loudnorm
summary out of stderr. Any trailing brace in a warning made that slice unparseable and the
measurement vanished. Use `_decode_summary()`, which finds the last `{...}` that actually
decodes, and `measure_with_diagnostics()` when you need to know why a measurement failed.

And: read `gh run list --json conclusion` for the exact SHA before calling a commit
CI-verified.

### Frame rate (T38)

The episode concat in `studio/pipeline/episode.py` now passes `-r 30 -fps_mode cfr`. Without it
the delivered MP4 was 29.969 fps (`14415/481`) while the scenes were rendered at 30, and no QC
check looked at frame rate. `factory/qa/validator.py` now emits a `frame_rate` check with a
**+/-0.01** tolerance, tight on purpose: a looser value (0.05, or a half frame) would have passed
the original defect and also passes NTSC 29.97, which this engine never writes.

If a future render fails the gate, do not widen it -- find what wrote the wrong rate.

### Transitions (T37)

`studio/animation/transitions.py` → `plan_transitions(scenes)` and `ffmpeg_fade_filters()`.

- A change of `bg` between consecutive scenes dips to black (0.22 s out, 0.22 s in); the same
  location cuts directly; scene 1 fades up from black over 0.45 s and the last scene fades down
  over 0.65 s.
- `EpisodePipeline` computes the plan once and passes `fade_in` / `fade_out` into each scene's
  data; the renderer turns them into `fade` filters on the encode command, so the frame loop is
  untouched.
- Traps: the pipeline only applies this when scenes are actually re-rendered — a resume from
  the checkpoint keeps the old, unfaded scene files. Use `--force` after changing the policy.
  Also, `build/` inside the repo and `FACTORY_BUILD_DIR` are different trees; check which one a
  render wrote before measuring an artifact (that mistake cost a false "fades not applied").

### Loudness (T36)

`studio/audio/loudness.py` → `measure()`, `normalize_file()`, `within_tolerance()`.

- `LOUDNESS_TARGET = {I: -14.0, TP: -1.5, LRA: 11.0}`; accepted publishing window is
  **-16.5 … -11.5 LUFS** with true peak ≤ -1.0 dBTP.
- `normalize_file(..., keep_duration=<video length>)` uses a *linear* gain from a measured
  pass: the duration cannot change, so A/V and lip-sync cannot drift. The pad to the scene's
  video length is deliberate and appears as a +0.5 s delta.
- The scene renderer normalises each mixed scene; `validate_episode` re-measures the finished
  MP4 as the `audio_loudness` gate. A file that cannot be measured is reported, never
  replaced with silence.

### Camera direction (T35)

`studio/animation/camera.py` → `CameraDirector(style, duration, viewport)`.

- Styles: `medium_pan` (drift + slight push), `two_shot`, `two_shot_zoom` (push-in),
  `close_up_chiku`, `close_up_gappu` (ease in to 1.70 and centre the face), `wide_finish`
  (pull-out), `action_shake`. Unknown styles fall back to `medium_pan`.
- `state_at(t)` returns `CameraFrame(zoom, pan_x, pan_y)`; `project(x, y, frame)` mirrors the
  cairo maths and is covered by a test that renders a marker and finds it.
- `subject` is `"chiku"` / `"gappu"` for close-ups; the renderer then draws **only** that
  character, because drawing the other leaves a half-body sliver at the frame edge.
- Backgrounds are drawn with a 1.13× overscan (`BackgroundRenderer.OVERSCAN`) because the
  camera pans and the parallax shift would otherwise expose the edge of the art.
- `draw_vignette()` in `effects.py` runs in screen space after the characters and before the
  subtitle band.

### Performance layer (T34)

`studio/characters/performance.py` — dialogue → beats → per-frame accents.

- `Beat(at, kind, strength)`; kinds: `nod shake lean_in recoil chuckle bounce blink widen
  point_beat`. `PerformanceTrack.accent_at(t)` returns an `Accent`.
- `Accent.on_body(BodyState)` and `Accent.on_face(EyeState)` are **additive**; an empty accent
  returns the inputs unchanged, which is what keeps the golden frames valid.
- `plan_performance(dialogue, duration, speaker, seed)`: questions widen the listener and tilt
  the speaker, `!` recoils the listener and bounces the speaker, plain statements nod, commas
  are soft beats, sentences over 4.5 s earn a weight shift. Thinned to **6 beats max** and
  **0.55 s minimum gap** after jitter.
- `FACTORY_NO_PERFORMANCE=1` disables the layer (A/B renders and emergency off switch).
- `python -m tools.report_performance <episode_dir>` prints the beat table and the share of
  frames each character is animated.
- Trap: the plan is built from `total_duration` (narration + 0.5 s), so recomputing beats with
  the narration duration alone gives different times. The QA tool reads the rendered scene
  durations for exactly this reason.

### Shape data (T30b)

`content/characters/*.json` → `shapes` → `studio/characters/shapes.py`. Five kinds:
`stroke`, `filled`, `ellipse`, `dots`, `segments`. Commands are `M/L/C/Q/Z`.

- `wave` is a per-point list of x multipliers; `x += wave[i] * wave_value` is how the tail
  swings, so keep its length equal to the path's point count (validated).
- `mirror: true` draws a second copy with every x negated — that is the vest's other panel.
- Colours are palette keys or explicit `[r, g, b, a]`.
- `REQUIRED_SHAPES` in `schema.py` lists what each archetype must define, so a missing shape
  fails at load rather than drawing nothing.
- Verification command after touching a rig or a shape:
  `python -m tools.capture_goldens --check` must print `78 frames, 0 changed`.
- Still drawn in code: spectacles and their glints, the muzzle mask, and limb capsules.

### Locomotion (T33)

`MotionController(mode, duration, seed, distance, facing).state_at(t)` returns a `BodyState`;
`rig.update_pose(..., body=state)` applies it **after** the pose. Rules that keep this sane:

- Rigs reset every animated field at the start of `update_pose`. Do not remove that reset:
  without it `apply_body` integrates and the character leaves the screen (this happened).
  If you add a field a pose can write, reset it there too.
- Motion owns translation and gait; the pose owns attitude. Arms are only overridden when
  the motion is about arms (walk, run, wave, point). Everything else keeps the pose.
- `walk_in`/`walk_out` use `facing` to decide direction, so two characters exit away from
  each other instead of through each other.
- Scene key: `chiku_motion` / `gappu_motion` (string, or list where the first is used).
  Absent = `idle` = a no-op, which is why existing scenes render unchanged.
- The golden set covers idle/excited/shocked/talking only. It does **not** cover
  `boast_proud` or `skeptical_eyebrow`, and those are exactly the poses whose output moved
  when the reset was introduced. **Adding goldens for every pose is the highest-value
  remaining T30b task.**

### Eyes, gaze and blinking (T32)

`FaceController` (in `studio/characters/gaze.py`) is built per character per scene and
answers one question per frame: *what are this character's eyes doing right now?* It owns:

- `BlinkPattern` — seeded schedule, jittered intervals (0.45–1.55x the schema period),
  double blinks, asymmetric close/open, partial blinks, and blink suppression during shock.
- `SaccadeSchedule` — scripted targets first (eye contact), idle scanning between them,
  fast eased travel (60–140 ms), micro-saccade tremor, no two identical consecutive targets.
- `EXPRESSIONS` — 13 named eye poses (neutral, happy, excited, surprised, suspicious,
  thinking, sad, angry, fear, confused, shy, proud, listening) that cross-fade over 0.35 s.
  A character may override any field per expression in its JSON `expressions` block.
- Pose names from older stories map through `expression_for_pose()`; nothing in existing
  story JSON had to change.

Rendering lives in `studio/characters/eyes.py` (`draw_eyes`, `draw_brows`). **`draw_eyes(
state=None)` is the original rendering, kept bit-for-bit** — that is why the eight golden
frames still pass. When a controller is attached (`rig.attach_face(controller)` then
`rig.face_state_at(t)` each frame) the expressive path draws an asymmetric aperture with
real eyelids, clipped pupils, dilation, catchlights and three closed-eye shapes.

Integration points that matter:
- `studio/animation/scene_renderer.py` builds the controllers, seeds them from
  `story_id + scene_num + character` (deterministic re-renders), and alternates gaze
  between the partner and away from them every ~2.1 s (speaker) / 2.8 s (listener).
  Screen-space gaze is multiplied by `rig.facing` because rigs draw mirrored.
- `studio/pipeline/episode.py` passes `story_id` into `scene_data`; without it the seed
  falls back to the episode directory name.
- `tools/report_face.py <episode_dir>` prints blinks/min, gaze moves/min, blink intervals,
  shut-frame percentage and the expression mix per scene. Use it to prove animation
  actually happened instead of eyeballing a still.

Known rough edges: pupil travel is capped at 50 % of the eye radius (uncapped it reads as a
"crazy eye"); `pupil_min` is 0.82 so shock never produces a pinprick pupil; brow offset is
clamped to ±18 px.

### Character schema (T30)

Characters are data, not modules. `content/characters/chiku.json` and `gappu.json` hold
identity, anchor, palette, proportions, timing profile, feature flags and mouth config;
`studio/characters/schema.py` validates them strictly (`SchemaError` with a readable
message) and caches the result. Both rigs read `self.schema` / `self.prop` / `self.timing`.

Rules that matter when editing:
- Palette keys listed in `REQUIRED_PALETTE`, proportions in `REQUIRED_PROPORTIONS`
  (`arm_shift`, `hand_rx`, `brow_ctrl_x`, `brow_anchor_x`, `head_draw_y`, …), timing in
  `REQUIRED_TIMING` are **all mandatory**; adding a key means adding it to that tuple.
- `Timing` owns blink (period/duration/phase), breathing (rate/phase/amplitude), sway and
  tail. Rigs must not hard-code those numbers again.
- Goldens: `tests/factory/goldens/*.png` + `manifest.json` are SHA-256 hashes of frames from
  the pre-schema rigs. `tests/factory/test_character_schema.py` re-renders them; a pixel
  change fails the suite. Re-capture them **only** for an intentional art change, and say so.
- `_save_boundaries(..., synthetic=True)` marks the invented whole-line fallback; such a
  sidecar is ignored on reload, otherwise a cached line would silently lose real sentence
  windows (this bug was found and fixed during T30).
- Archetype-level drawing that is still code: tail bezier, hair tuft, vest curves,
  whiskers, spectacles, bowtie. Positions are data; shapes are not yet (T30b).

### Viseme lip-sync (T31b)

`studio/characters/visemes.py` turns narration text into a per-frame viseme timeline;
`studio/characters/mouth.py` draws all shapes for both rigs. Rigs accept
`lipsync=<VisemeTrack>` (amplitude) **and** `timeline=<VisemeTimeline>` (shape); the scene
renderer builds both per scene. Silence always wins: envelope ≤ 0.06 forces `CLOSED`.

Key facts to keep in mind:
- **Edge-TTS emits only `SentenceBoundary`** for our voices — verified with a direct probe of
  `hi-IN-MadhurNeural`, `hi-IN-SwaraNeural`, `en-US-AndrewNeural`. Do not assume word
  timings; `tts_engine._save_boundaries()` persists whatever the service gave us.
- Sentence windows are **snapped onto the voiced region** of the envelope before the units
  are distributed, so line starts/ends align with real audio; inside a sentence the
  placement is proportional.
- `tools/report_visemes.py <episode_dir>` prints the QA table (change rate, holds,
  articulated-voiced %). Use it after any rig change.
- The mouth is now drawn by `mouth.py`; the old inline mouth code in `chiku.py`/`gappu.py`
  was removed. Add new shapes in `visemes.DEFAULT_OPEN` **and** `mouth.draw_mouth`.

### Envelope lip-sync (T31a)

`studio/characters/lipsync.py` + wiring in `chiku.py`, `gappu.py`, `scene_renderer.py`.
The rigs now take an optional `lipsync=VisemeTrack` argument; the scene renderer builds one
track per scene from `audio_data["audio_path"]`. Fallback to the old sine remains when no
track is available. **Trap:** `scene_renderer` imports modules as `studio.*`, so any new
module must be added under `studio/characters/` and imported the same way.

### Exact next actions (in order)

1. Owner approval → merge PR #2 **first**, then PR #3 (no file overlap; PR #2 touches only
   `.github/workflows/produce.yml`). Then dispatch `produce-nexus-node.yml` with
   `upload: false` to complete T12 (runner render, Edge-TTS egress, Chrome overlays).
2. Provision `YT_NEXUS_NODE_*`, `YT_ACADEMIC_BIOHACKER_*`, `YT_NATKHAT_TOONS_*` (T15).
3. Durable state: replace cache-only persistence with a real store (T14).
4. Author an Academic 16:9 plan and a Hindi 16:9 profile to close acceptance tests 5–6.
5. Build the reusable character/animation component library (§E) — landscape has motifs,
   not characters.

Instructions for any AI coding agent (or human) picking this project up. Read
`PROJECT_CONTEXT.md`, `ARCHITECTURE.md`, `DEVELOPMENT_STATUS.md`, `TASKS.md` first.
This file tells you what to do *right now*.

## 1. Where the work actually lives

- Clone: `<path-to-clone>`
- Branch: `feat/autonomous-multichannel-factory`
- Remote: `https://github.com/Ayushjaiswal0001/youtube` (public, `main` @ `a69474c`)
- Upstream `D:\animated` holds the complete `studio/` package the Hindi renderer needs.

**This directory is under `%TEMP%`.** Until it is pushed, a disk cleanup destroys the
project. Treat preservation as task zero.

## 2. Exact next development task

**T12 — prove the workflows can run before trusting them.**

Everything below (T5) is done. `produce.yml` plus the three `produce-*.yml` callers
exist but have never executed, because this clone still cannot push. The next
developer must: push the branch to `Ayushjaiswal0001/youtube` (owner-side access),
dispatch `produce-nexus-node.yml` with `upload: false`, and confirm PyCairo builds,
Chrome is found via `CHROME_PATH`, Edge-TTS reaches the network, and `QC` passes on
the runner. Only then provision secrets (T15) and enable schedules.

## 2b. Previously the next task (completed)

**T5 — restore the missing `studio/` modules, then re-render one Natkhat episode.**

Copy from `D:\animated\studio\` into the repo's `studio/`:

```
__init__.py
story_engine.py
characters/chiku.py
characters/gappu.py
characters/rig_base.py
audio/tts_engine.py
audio/sfx_library.py
audio/subtitle.py            # only if the renderer needs it
animation/camera.py
animation/effects.py
pipeline/episode.py
```

Do **not** overwrite the repo's newer versions of:

```
studio/config.py                  # portable, env-overridable paths
studio/animation/background.py    # adds haunted_haveli + village_night
studio/animation/scene_renderer.py
studio/qa/validator.py
```

Then verify:

```powershell
python -c "from studio.pipeline.episode import EpisodePipeline; print('ok')"
$env:FACTORY_BUILD_DIR = "$env:TEMP\factory-verify"
python -m factory.cli render --channel natkhat-toons --plan-id natkhat-haveli-e1 --force
python -m factory.cli qc --channel natkhat-toons --plan-id natkhat-haveli-e1
```

Expected: `qc_ok: true`, 1080x1920, h264+aac, 20–65 s. Use a scratch
`FACTORY_BUILD_DIR` so the three good existing renders in `build/` are untouched.

If the restored modules import symbols the repo's newer files no longer export
(likely candidates: `SceneRenderer.__init__`, `BackgroundRenderer.render_*`,
`TTSEngine.synthesize`), reconcile by adapting the **newer** file to keep its API, not
by rolling it back.

## 3. Then, in order

1. T3/T4 — `.gitignore` negation for `assets/**/*.wav`; confirm no secrets tracked.
2. T6 — `requirements.txt` + `ci.yml` install step.
3. T8 — `tests/factory/` (currently zero coverage outside `uploader/`).
4. T9/T10/T11 — plan generation + Natkhat series memory (this is what makes it autonomous).
5. T12–T16 — workflows, secrets, state persistence, verification.

## 4. Hard constraints — do not violate

- **Never** put a client ID, client secret, refresh token, OAuth code, or the contents of
  `D:\animated\ytcredetials.txt` into any tracked file, log, commit, or doc. Secrets go in
  GitHub Actions secrets or `~/.faceless-shorts/secrets/youtube/`.
- **Never** upload a public video, enable `allow_public_upload`, or set
  `FACTORY_ALLOW_SCHEDULE=1` without explicit human approval.
- **Never** bypass the channel-identity preflight/postcheck or the `--confirm-channel` gate.
- **Never** set Natkhat `madeForKids: false` — the channel is child-directed.
- **Never** delete or rewrite existing working code to "simplify". Extend it.
- **Never** report a test or workflow as passing without running it. If you cannot run
  it (no push rights, no secrets), say so explicitly.
- **Never** `git add -A` blindly: `build/` (large media) and secrets-adjacent files must
  stay out. Prefer explicit paths.
- Preserve git history; do not force-push `main`; make small, describable commits.

## 5. Known blockers (checked 2026-11-20)

| Blocker | Evidence |
| --- | --- |
| No push rights | `git push --dry-run` → `403 ... denied to Ayushjaiswal001`; `permissions.push: false`. Account `Ayushjaiswal001` ≠ repo owner `Ayushjaiswal0001`. **Owner rule: only `Ayushjaiswal0001/youtube` may be used — never fork to, mirror to, or push through `Ayushjaiswal001`.** |
| Hindi render broken | `ModuleNotFoundError: studio.pipeline.episode` |
| No Actions secrets | `gh api .../actions/secrets` → 403 (insufficient permission); workflows would fail at auth |
| Assets untracked | global `*.wav` in `.gitignore` |
| OAuth longevity unknown | Testing-mode refresh tokens expire after 7 days |

## 6. Commands cheat sheet

```powershell
# sanity
python -m compileall -q uploader factory studio
python -m pytest tests -q                      # 50 uploader tests
python -m factory.cli doctor
python -m factory.cli plans --channel all

# render / qc / publish (dry-run is the default)
python -m factory.cli render --channel nexus-node --plan-id nexus-small-models
python -m factory.cli qc     --channel nexus-node
python -m factory.cli publish --channel nexus-node --plan-id nexus-small-models
python -m factory.cli analytics --channel nexus-node --limit 20

# uploader (never with --execute unless approved)
python -m uploader.cli verify --channel all
python -m uploader.cli dry-run --channel natkhat-toons --video "<mp4>" --metadata examples/upload-request.example.json
python -m uploader.cli status --channel natkhat-toons
```

Real uploads additionally require `FACTORY_ALLOW_UPLOAD=1` (and
`FACTORY_ALLOW_SCHEDULE=1` for `publishAt`) plus `--execute --confirm-channel <slug>`.

Environment overrides that CI should use instead of editing code:
`FACTORY_BUILD_DIR`, `FACTORY_STATE_DIR`, `FACTORY_LOG_DIR`, `YT_SECRETS_ROOT`,
`YT_STATE_ROOT`.

## 7. What "done" looks like

A scheduled GitHub Actions run per channel, every day, that renders a video the system
planned itself, passes QC, uploads privately with a future `publishAt` in IST, verifies
the upload, records the state, and never repeats a topic or crosses channels — with the
previous run's state restored. See the completion criteria at the end of `TASKS.md`.

## Security traps found in the X100 final audit (2026-11-22)

- **A clean working tree says nothing about history.** The tree and `git log` can both look clean while a
  credential from an old commit still works. `python -m tools.secret_scan --history` walks every blob in
  every ref and takes about 75 s; run it before claiming anything about credentials.
- **The run journal is published.** `pipeline_state/<channel>/runs.jsonl` is uploaded as a CI artifact,
  so anything machine-specific written there ends up on a public page. It passes through
  `factory.state._scrub()`; add new path-shaped keys to that scrubber or they will leak the local user.
- **Scan your scanner.** CI plants a synthetic `GOCSPX-` secret and requires a hit, because a scanner
  that has stopped matching still exits 0 - the most dangerous kind of green.
- **Annotate fixture credentials, do not delete them**: `# pragma: allowlist secret` on the line, and
  build probe values by concatenation so the probe file itself stays clean.
- **`secrets: inherit`** in the three per-channel callers passes every repository secret into
  `produce.yml`. Acceptable today only because nothing there triggers on `pull_request`; keep it that way.
- `env -u GITHUB_TOKEN` for every `gh` call remains mandatory - the ambient token is a different account.

## Trap: a local render is not a read-only operation

`factory.cli render` and `factory.cli plan new` consume the tracked batch ledger: `content/batch_2026-11-*.json`
is rewritten, and an older batch can be **deleted** from the working tree. Two full-suite runs failed with
`PlanGenerationError: topic bank exhausted` because of this, and were green again after
`git checkout HEAD -- content/`.

Before any commit, run `git status --porcelain content/` and restore it. Never assume a local plan run left the
repository unchanged.

---

## 2026-11-23 — six-row cloud matrix, and the two defects that wave exposed

`main` is `218a6d5`. Six production rows dispatched from it, all green:
`45196207861` (natkhat short), `45196341328` (nexus short), `45196366254` (academic short),
`45196390881` (natkhat 16:9), `45196415411` (nexus long), `45196440363` (academic long).
Four artifacts downloaded and re-hashed locally; the two long-form downloads failed on GitHub's egress limit and
are evidenced from the run logs only. Full detail: `FINAL_LAUNCH/FINAL_ACCEPTANCE_MATRIX.md`.

Three things worth remembering from this wave:

1. **`int(None or 0) == 0` is how a gate lies.** The portrait Hindi episode merge never summed
   `subtitle_collision_frames`, so `caption_clearance` passed on a measurement that had not been made. With the
   merge fixed and the gate failing closed, the same episode reported 803 of 961 frames of chin-behind-caption.
   The composition, not the check, was wrong: pair shots centred the cast at 0.7125 of frame height (1368 px) and
   the caption capsule starts at 1358. Target is now 0.55, with `PORTRAIT_CAPTION_BAND_TOP` and a geometry test.
2. **Enforcement that lives only in `validate()` is enforcement that does not run.** `force_made_for_kids` was
   checked there and the upload path never calls it. It is now checked where the request is built.
3. **Sample peak is not true peak.** `alimiter=0.82` plus AAC inter-sample overshoot put an episode at −0.96 dBTP
   against a −1.0 gate. The limiter is 0.74; the gate is unchanged.

Publishing is audited but not executed: zero `YT_*` secrets, three schedules `disabled_manually`, notifications
`delivered: False`. The owner runbook is `FINAL_LAUNCH/PUBLISHING_READINESS.md`; the recovery point is
`FINAL_LAUNCH/EXECUTION_CHECKPOINT.md`.
