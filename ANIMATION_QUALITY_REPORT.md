# Animation quality report

Living document. Append per milestone; never rewrite an earlier entry. Every claim carries the
evidence level that actually supports it: IMPLEMENTED / UNIT-TESTED / INTEGRATION-TESTED /
RENDERED / VISUALLY-INSPECTED / QC-VERIFIED / CLOUD-VERIFIED.

## 2026-11-21 - T43: world-space pickup and two-segment arm IK

### What was built

| Piece | Module | Evidence |
| --- | --- | --- |
| Two-bone analytic IK, reach clamp, joint limits, fixed pole, elbow slew | `studio/characters/ik.py` | IMPLEMENTED, RENDERED |
| Rig-measured `ArmChain` (shoulder, segment lengths, neutral hand) | `studio/characters/ik.py` | IMPLEMENTED |
| Opt-in bent-arm draw for both rigs | `chiku.py`, `gappu.py` | IMPLEMENTED, RENDERED |
| World object with box, surface, edge distance, per-grip grasp point | `studio/characters/pickup.py` | IMPLEMENTED, RENDERED |
| 10-state interaction machine with a legal-edge table and a transition log | `studio/characters/pickup.py` | IMPLEMENTED |
| 5 grip types | `studio/characters/pickup.py` | IMPLEMENTED |
| 5 demonstrations, 1920x1080, 30 fps | `tools/render_pickup_demos.py` | RENDERED, VISUALLY-INSPECTED |

Portrait regression: **78 golden frames, 0 changed, 0 new.** The bent-arm branch only runs when an
IK solution is attached, so every existing episode renders bit-identically.

### Measurements (actual wrist position, not the requested target)

| Demo | Min wrist-to-object distance | States reached | Verdict |
| --- | --- | --- | --- |
| 01 Chiku picks up from the ground | 57.0 px | APPROACHING > REACHING > **FAILED** | fails honestly |
| 02 Gappu picks up from a table | 37.5 px | APPROACHING > REACHING > **FAILED** | fails honestly |
| 03 Chiku hands to Gappu | -6.8 px | ... HOLDING > RELEASING > COMPLETE | contact |
| 04 Two hands lift a pot | 4.7 px | ... HOLDING > RELEASING > COMPLETE | contact |
| 05 Failed reach recovers | 85.8 px | APPROACHING > REACHING > recovered:COMPLETE | first attempt fails, recovery works |

The first version of the demo measured contact against the *requested* hand target and reported all
five demos as succeeding. That is the exact error the brief warns about - "never claim hand contact
merely because the object is visually close" - and it was caught by re-measuring the drawn wrist.

### Defects found (not yet fixed)

1. **A ground pickup is geometrically impossible with the current rig.** The arm reaches 83.8 px;
   the shoulder sits ~294 px above the ground plane. Measured, not guessed. Picking something up
   from the floor requires a crouch/bend (torso rotation + lowered shoulder), which the rigs support
   (`torso.local_rot`) but which no solver drives yet. This is the top defect in the animation
   system and it blocks demos 1 and 5.
2. **Props are composited behind the cast in the demo harness.** `frame_cb` draws the object before
   the rigs, so the key is hidden behind the body in every clip. The demo is not evidence of a good
   composite until the draw order is fixed (object after the cast, foreground after both).
3. **Cast framing is poor in the demos**: characters occupy a small fraction of a 1920x1080 frame,
   with a large empty floor because the demo camera is not zoomed to the action.
4. **The table does not meet the character**: it is drawn at the object's x, which is offset from
   the rig, so legs and surface read as unrelated geometry.
5. `_draw_table` and the two-hand pot are demo-local drawing code, not props in
   `studio/characters/props.py`; they must move there before an episode can use them.

### What is genuinely better

* The arm has a real elbow where it had one rigid capsule, and the joint cannot flip: the pole is a
  fixed world direction and the elbow angle is slew-limited per frame.
* A reach is now a schedule with measured phases, and an unreachable object produces FAILED instead
  of a prop that teleports into a hand.
* Contact is a number (`WorldObject.distance_to(hand)`), computed from the drawn wrist.

## Known gaps after this milestone

* T43 is **not integrated into `render_episode`**: no authored episode can request a pickup yet.
* T44 (lighting) and T45 (environment breadth) are untouched in this milestone.
* The crouch/bend solver in defect 1 is the prerequisite for every ground-level interaction.

## 2026-11-21 - T43b / T44 / T45

### T43b: body mechanics (closes T43)

| Piece | Evidence |
| --- | --- |
| `BodyPose(bend, squash)`, `solve_crouch`, `plan_crouch`, head counter-rotation | UNIT-TESTED, RENDERED, VISUALLY-INSPECTED |
| Ground pickup for both rigs | RENDERED, VISUALLY-INSPECTED, contact measured on the drawn wrist |
| Table pickup, handoff, two-hand, failed-reach recovery | RENDERED, VISUALLY-INSPECTED |

Measured contact on the drawn wrist: ground -14.0, table -20.0, handoff -3.5, two-hand -3.2,
recovery -4.2 px (negative = inside the object). All five reach COMPLETE.

The first attempt drew an 83° fold with upright legs and looked like a character lying on the floor.
Instrumenting the render found the arm reaches 83.8 px while the shoulder sits 195.8 px above the
ground, so *some* deep pose is unavoidable for this rig. Three fixes made it read correctly: prefer
squash (a knee-bend proxy) over folding, counter-rotate the head by 78% of the fold so the face stays
up, and frame the camera on the action.

**Disclosed error.** In the previous milestone I reported the shoulder as ~294 px above the ground.
It is 195.8 px. The 294 figure came from a portrait-scale measurement carried into a landscape
conversation and was never re-measured. Every conclusion drawn from it was directionally right and
numerically wrong, and the corrected number is why an 83° bend was needed rather than something
impossible outright.

Side effect of fixing the ground: raising the cast onto the floor plane raises the shoulder by 32 px,
so the ground reach needs a deeper bend (Chiku 60° -> 96°). The two-hand pot reports `crouch_ok=False`
against a 92% reach margin while still making contact, which means the margin is conservative rather
than the reach being impossible. Recorded, not hidden.

### T44: lighting and shadows

Six presets, directional shadows derived from elevation and body height, ambient and grade overlays,
and the environment accepting a preset without changing any render that does not opt in.

Measured standing -> 180 px airborne shadow offsets: daylight 8 -> 48, warm_afternoon 8 -> 114,
sunset 8 -> 296, cool_evening -8 -> -212, moonlight -8 -> -130. Opposite light directions produce
opposite shadows.

Two defects found in the first sheet and fixed: the standing contact shadow was invisible (an 8 px
offset hid it behind the character's own feet), and the airborne tile was cropped because the camera
was framed for a standing character only.

### T45: six locations

All six render with a distinct identity (jungle clearing, forest path, riverbank, haunted haveli,
cave entrance, village night) with the cast inside them. Per-location measurements are in
`build/locations/locations.json`.

**Defect found and fixed:** the cast stood 32 px *through* the floor in every landscape render,
because a rig's anchor is not its feet. `studio/animation/grounding.py` measures the drawn silhouette
once per rig and places the feet exactly on the ground plane (`ground_error` now 0.0 for both rigs at
every ground height). Chiku's offset is 32 px, Gappu's 22 px.

**Defect found and not fixed:** the near-camera layer never occludes a character - measured
foreground occlusion is 0.0 in all six locations. It is a bottom strip of grass, so "foreground depth"
in T45's sense is not achieved yet.

**Defect found and not fixed:** compositing by world depth is not sufficient for furniture. In the
table demo the cup sits on the table in front of the character but sorts behind him, because its
screen y is higher. Depth-aware layering needs explicit layer groups, not one y comparison.

## 2026-11-21 - T43 pickup, in production

The pickup system existed and no episode could ask for it. That is the gap this closes: a scene
declares `"pickup": {"object", "grip", "holder", "offset", "surface"}`, and the renderer bends the
body, solves the arm, moves the object only once the hand arrives, reports what happened, and gates on
it.

Evidence: production render of scene 3 of `natkhat-haveli-stage-e1` through `factory.cli render
--scenes 3 --force` - 179 frames, 1920x1080, 30/1. Contact **-13.93 px** on the drawn wrist, every
state reached, 0 frames of claimed contact without touch, bend 79.2 degrees, shoulder-to-surface
57.4 px against an 83.8 px arm. Frames inspected: the character bends with his face up, the key
follows the hand, and it stays released where it was put down.

Five defects were found by doing this rather than by reasoning about it, and all five are recorded in
TEST_RESULTS 3x. The two most instructive:

* the plan normaliser silently dropped `pickup`, so the feature was unreachable from content and the
  render "succeeded" by reusing a cached scene;
* reachability was measured against the object's centre, so a pickup that demonstrably worked was
  declared unreachable by its own QC gate. A measurement of the wrong quantity is worse than no
  measurement, because it produces a confident wrong answer.

Remaining: a pickup is authored on one scene of one episode. Multi-object scenes, pickups that
combine with a hand-off in the same scene, and table-height furniture drawn as real set pieces are
still outstanding.

## 2026-11-21 - The set can get in the way (T45b / T45c) and the story can contradict itself (T47)

| Defect | Severity | Reproduction | Evidence | Root cause | Fix | Retest |
| --- | --- | --- | --- | --- | --- | --- |
| Episode shipped as a still image | critical | render the 12-scene plan | QC `frozen_frames`: 63.7 s frozen at 0.5 s; mean pixel difference over 2 s = **0.0** | the occlusion probe rebound `surface`, the scene's frame buffer | renamed the probe locals; mean difference now **8.85** | full episode `qc_ok: true`, 27/27 |
| Foreground occluded nothing | high | render six locations | measured occlusion **0.0** of both characters in all six | foliage was confined to the outer 12 % of the frame | set dresser places objects on the world plane and in the near layer | **18.5 % / 7.0 %**, faces **0.0 %** |
| Near scenery read as a hole in the frame | high | inspect the dressing sheet | black blobs over 45 % of the cast | silhouettes filled with near-black | colours taken from each location's palette, plus a shaft highlight | inspected; bushes and trunk read as objects |
| Hand-off reported as a conflict | medium | validate the episode plan | `handoff_target_mismatch` on a correct scene | the destination was compared as if it were a second holder | end owner is the declared destination | 0 errors on the real plan |
| Object in hand with no way to be in hand | medium | continuity of scenes 3 and 6 | scene 3 released the key, scene 6 handed it off | ownership was not modelled at all | `keep: true` carry + ownership ledger | chain verified: floor -> chiku -> gappu |
| A test that measured a proxy | medium | run the dressing tests | a clump covering nobody failed; an object covering a face would have passed | frame-height threshold instead of face coverage | head-band occlusion measured on drawn pixels | tests assert `< 2 %` of the head band |

Measured cost: the dressing adds ~14 % to render time (250-278 s -> 292 s for the same 64.5 s episode).

## 2026-11-22 — hand-off inside one scene, and what the render showed (T43B)

Implemented: `PickupScene` accepts `handoff_to`, plans a meeting point, walks both characters toward
each other, solves both arms toward that point, and transfers ownership only when the two *drawn*
wrists are measurably together. The transfer is recorded in a scene-local `OwnershipLedger`
(register → claim on measured contact → transfer), and episode QC now fails a scene that declares a
hand-off which never completed (`pickup_contact`), alongside the existing claimed-contact check.

Rendered evidence (`tools/render_handoff_demo.py`, 7 s, 210 frames, production stage and environment):
contact between the two drawn hands **2.0 px**, `transferred: true`, ledger holder `gappu`, and the
brass key visible in the hand at transfer. Frames inspected at full resolution.

**Defect, disclosed: the two characters interpenetrate during the hand-off.** With the shoulders 98 px
apart (the distance at which 78 % of the smaller arm's reach meets in the middle) the drawn bodies, which
are 150–200 px wide, overlap — Chiku occludes most of Gappu and the giver's forearm crosses in front of
the receiver's chest. This is a proportion limit of the rigs, not a tunable staging choice: raising the
separation to 92 % of reach requires 1.06 of the receiver's reach, so the hand-off becomes physically
impossible (the demo refuses to render it, by design). The fix is a torso lean during the hand-off, or a
longer forearm in the character schema; neither is done here. Everything else about the beat is correct:
the key is held, carried, and passed at a measured 2 px, and it does not teleport.
