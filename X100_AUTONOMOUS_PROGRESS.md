# X100 Visual Engine — autonomous progress log

Local only. Nothing committed, pushed, deployed or uploaded.

## Stage A — repository safety (complete)

- Root: `C:/Users/DELL/AppData/Local/Temp/opencode/youtube`; branch `feature/x100-visual-engine-v1`;
  base `b87edb3` (= `main` after PR #12); PR #12 untouched.
- Working tree at start: clean apart from `pipeline_state/` entries written by earlier renders, which
  are restored before finishing.
- 967 tests collected at base, matching the Phase A count of 900 plus the OAuth work in PR #12.

## Stage B — baseline evidence (complete)

- `nexus-robot-video` rendered from the untouched tree: 38.733 s, 9,462,159 B,
  `sha256 45c2222…`, 188.8 s wall clock, artefacts under `x100base/base/…`.
- `factory.cli render --plan-id` could not see the plan (it only reads `content/batch_*.json`); a
  scratch driver outside the repository calls `render_episode(spec, plan=…)` instead.
- Phase A's timing claim was corrected: **7 narration lines, 37.4 s of narration**, window (5, 18) —
  not 5 lines and 45.9 s. `script.json` has no timings at all; they live in `timeline.json`.

## Stage C — implementation (complete)

| module | state |
|---|---|
| `factory/content/scene_plan.py` | complete, 17 tests |
| `factory/media/assets/{base,metadata,validators,cache,local,generated,resolver}.py` | complete, 33 tests |
| `factory/media/english_renderer.py` (chrome split, plate, dispatcher) | complete |
| `factory/qa/creative.py` + `content/creative_qc.json` | complete, 18 tests |
| `factory/qa/publish_gate.py` (creative check) | complete |
| `factory/manifesting.py` (new artefacts) | complete |
| `factory/config.py` + `channels/nexus-node.json` (opt-in) | complete |

## Stage D — test and repair loop

Repairs made during implementation, each driven by a failing measurement rather than a guess:

1. **Planner tiling over-counted by 180 ms** — summing per-line durations counted the inter-line gaps
   twice. Narration is now measured from the first spoken word to the last.
2. **A long sentence could never be split** — the cut chooser took the globally largest pause, which
   on evenly spaced words is index 1, so every attempt created a one-word sliver. It now rejects
   sliver cuts and breaks ties toward the middle.
3. **Duplicate entities** printed `VIDEO -> MODEL -> MODEL`; compositions now adapt to the entities
   they have.
4. **Comparison bars asserted a ratio** the narration never states; replaced with labelled tradeoff
   panels.
5. **Titles cut mid-word** (`… THOUSANDS OF EXA`); `short_title` now cuts on a word boundary.
6. **Pictograms invisible on the plate** — interiors filled with the same colour as the plate. Fills
   moved to the darker plate background; measured on encoded frames.
7. **Grid icon read as "A A"**; redrawn as a lattice tower with two conductors.
8. **Sync assertion compared an absolute end time against a duration**, and failed a plan that was
   exact — it now compares the plan's span, plus checks each scene against the video length.
9. **`VisualDispatcher.build` planned against `script.json`** (zeroed timings) instead of the timed
   lines, producing an empty plan that looked successful.
10. **One pre-existing test asserted a formatted source line** that gained a `dispatcher=` argument.
    The assertion was rewritten to check the invariant (encoded frame is the measured frame, plan
    reaches the encoder) — strengthened, not weakened.

Final regression: see `pytest_final.log` and §"Tests" of `VISUAL_ENGINE_V1_REPORT.md`.

## Stage E — visual quality (complete)

Four render/inspect cycles on the real encoder, each inspected on extracted frames before the next
change. Final state: 9 scenes, 6 compositions, 14/14 creative checks, 25/25 gate checks, 0 freezes, 0
caption collisions. Plate ink +88 %, plate colour count +101 % versus baseline. Full numbers in
`VISUAL_ENGINE_V1_REPORT.md` §3.

## Stage F — regression (complete)

- `python -m pytest tests -q` — see `x100new/pytest_final.log`.
- `python -m tools.capture_goldens --check` → `78 frames, 0 changed, 0 new` (rig geometry untouched).
- Channel compatibility: 12 frames × 3 channels composed with `HEAD`'s renderer and with the working
  tree → 12/12 SHA-256 identical. Academic Biohacker rendered end-to-end with its legacy card, no
  `scenes.json`, no `creative.json`.

## Stage G — documentation (complete)

`VISUAL_ENGINE_V1_REPORT.md`, `X100_AUTONOMOUS_PROGRESS.md`, `X100_AUTONOMOUS_DECISIONS.md`.

---

## Files changed (by the visual engine commit `4403010`)

New: `factory/content/scene_plan.py`, `factory/media/assets/` (8 files), `factory/qa/creative.py`,
`content/creative_qc.json`, `tests/factory/test_scene_plan.py`, `tests/factory/test_assets.py`,
`tests/factory/test_creative_qc.py`, `VISUAL_ENGINE_V1_REPORT.md`, this file and the decisions file.

Modified: `factory/media/english_renderer.py`, `factory/config.py`, `factory/qa/publish_gate.py`,
`factory/manifesting.py`, `channels/nexus-node.json`, `.gitignore`,
`tests/factory/test_cloud_gate_repairs.py` (assertion strengthened).

## Blockers

None for this scope. The ceiling that remains is **material**: no licensed photography, footage or
illustration exists in the repository, and no provider may be enabled, so every visual is a locally
drawn schematic. That is a budget decision, not an engineering gap.

## Next action for the owner

Review the diff, run the suite, watch the upgraded render, then decide whether to commit and open a
PR. The three open engineering items from Phase A (three-character scenes, hand-off interpenetration,
TTS cache by text hash) are untouched by this work.

## 2026-11-24 — defect-correction pass on the visual engine (local only)

Two read-only audits of the Phase B implementation returned **READY AFTER SPECIFIED FIXES** with four
release blockers (H1–H4) and four medium findings (M1–M4). Every one is now fixed in source with the
regression test that fails if it returns, plus one further finding found by inspecting the corrected
render.

- **H1** `orchestrator` declared neither `scenes.json` nor `creative.json`, so a fresh package failed
  its own `verify()` (*unlisted artifact on disk*) and the gate read 24/25. CI hid it by rebuilding the
  manifest first. Fixed with explicit artifact pairs; a fresh package now verifies clean **before** any
  rebuild.
- **H2** `_active_line()` returned the final line during an inter-line pause, so 32 of 1,162 frames
  carried the next line's headline and counter. Fixed to hold the preceding line; verified on the
  encoded file at all six pauses (`01…06`, never `07/FOLLOW`).
- **H3** `_draw_gap`/`_draw_topology` indexed `entities[1]` unchecked — a reachable `IndexError`
  through the diversity ladder. Fixed by a `_draw_statement` fallback plus composition filtering.
- **H4** `learning` was a `study` synonym (a **STUDY** plate for a sentence about videos) and `cost`
  was drawn as a pipeline stage. Both fixed; the audited narration now yields VIDEO and a
  single-subject statement plate.
- **M1** cross-line merges carried stale word indices and a hardcoded reason; **M2** creative QC
  ignored the plan's own duration band; **M3** added title-vs-episode and headline-vs-active-line
  warnings; **M4** stopped writing a zero-valued `visual` element into legacy `framing.json`.
- **Further:** comparison plates claimed "TWO ROUTES TO THE SAME RESULT" for sentences that compare
  nothing. Comparison now requires comparative language; a neutral `panels` composition replaces the
  claim.

Evidence: **1015 tests pass** (968 + 47 new), goldens **78 frames, 0 changed**, legacy compatibility
**12/12 identical across 3 channels**, fresh package **verify clean / creative 16/16 / gate 25/25**,
re-render 159.9 s at 38.733 s, 8,492,551 B, `2f4a936…`, plate ink +87 %, plate colours +104 %.

Committed as `44030107adf480b913b770811b02a0c60feb89a6` on `feature/x100-visual-engine-v1`, pushed, and
opened for review as PR #13 against `main`. Nothing is deployed, uploaded or scheduled: the three
production crons remain `disabled_manually` and `UPLOAD_ENABLED` is untouched.
