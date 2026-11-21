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
