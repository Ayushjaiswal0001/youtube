# Final completion acceptance — shorts repaired, long-form gate implemented, cloud still gated on a merge

Branch `fix/cloud-gate-blockers`, head `4de71bc` plus the long-form commit that adds this file. `main` is at
`43e87e5`. All local evidence below was produced on this branch; nothing here is cloud evidence.

## PR #5 — owner merge decision

| Item | Value |
| --- | --- |
| PR | https://github.com/Ayushjaiswal0001/youtube/pull/5 |
| Head SHA | `4de71bc11fb54ae2baf8a2e4a0a8094280fad49c` (+1 commit for long-form) |
| State | OPEN, MERGEABLE, mergeStateStatus CLEAN, `mergedAt: null` |
| Checks | 14/14 SUCCESS (uploader py3.11 ×2, py3.12 ×2, secret scan ×2, factory plan+publish gates ×2, gitleaks ×2, dependency audit ×2, workflow permissions/pinning ×2) |
| Files changed | 9 in the first commit (3 factory modules, 1 workflow, 2 test files, 1 report, `factory/manifesting.py`), then long-form: `factory/{cli,ops,orchestrator}.py`, `factory/content/script.py`, `factory/media/landscape_stage.py`, 1 new test file, this report |
| Secrets / paths | No credential, no absolute path, no build output, no generated video in the diff. Verified by `gh pr diff 5` grep for `C:\Users`, `/home/runner`, and token prefixes: no match |
| Branch protection | required checks `uploader (py3.11)`, `uploader (py3.12)`, `secret scan (tree, staged, history)`; force-push disabled, deletions disabled, `enforce_admins: false`, required approving reviews: 0 |

**Safe for owner merge: yes.** The one risk is scope: the long-form repair is stacked on this branch so the
owner merges once and gets both fixes. If you prefer a separate review, say so and I will split it before you
merge — the long-form commit touches no file that the shorts repair touched.

## Long-form schema — root cause and fix

The render path always dispatched by engine. `orchestrator.render_episode` sends a `stage` plan to
`landscape_stage.render_stage_episode`, which normalises `scenes[].line` through `plan_scenes`. The **read**
path did not: `factory/cli.py::_script_for` called `build_hindi_script` for every Hindi channel regardless of
engine, and that builder requires `scenes[].dialogue`. So `validate`, `manifest` and `gate` rejected a
landscape episode that had already rendered and passed its own 27/27 QC.

Fix, in that order:

1. `orchestrator.build_script(spec, plan)` — one dispatcher next to `resolve_engine`, which already owned the
   knowledge of which engine a plan needs: `stage` → `landscape_stage.build_script`, Hindi → 
   `build_hindi_script`, otherwise `build_english_script`. `_script_for` and the two inline call sites use it.
2. `landscape_stage.build_script` now records what it preserved: `metadata = {plan_id, engine: "stage",
   chapters, slot, director, scenes}`. Chapters, beat order, speaker, camera, lighting, pickup and sfx survive
   normalisation instead of being dropped.
3. Scene text is type-checked, not stringified: a non-string `dialogue` or `line` is an error in both builders
   (`str({"a": 1})` used to pass the old truthiness check and become caption text).
4. `orchestrator.plan_specs()` (was `_plan_specs`) is public, and `ops.cmd_gate` iterates **both** composition
   profiles. Before this, `gate --channel natkhat-toons` returned `[]` while a rendered landscape episode with
   its video, QC report and manifest sat on disk.

No threshold moved: long-form duration contract is still 60-900 s, resolution 1920x1080, and the gate is
25 checks for the landscape profile versus 24 for the shorts profile.

## Long-form local acceptance (fresh build directory, real render)

`FACTORY_BUILD_DIR=.../lf1/build python -m factory.cli render --channel natkhat-toons --format long
--plan-id natkhat-haveli-stage-e1`, then `validate --format long`, `manifest --format long`, `gate`.

| Item | Value |
| --- | --- |
| Plan | `natkhat-haveli-stage-e1` (12 scenes), source `43e87e5` content |
| Duration / picture | 64.501 s, 1920x1080, 30 fps, h264 + aac 44.1 kHz stereo |
| Size | 7.96 MB |
| sha256 | `cb0f4bac0b64fc19d4b97bdcbfa790976a12b3a57167ed489332deb1431fc6d5` |
| Render wall time | 467 s (12 scenes, full render, no cache reuse) |
| QC | **27/27**, `failures: []` |
| Manifest | **10 artifacts**, `problems: []`, verifies |
| Publishing gate | **25/25**, `blockers: []` |
| Frames inspected | 8.0 s and 40.0 s: Chiku in the night haveli, moon and mountains, Devanagari caption band clear of the character, no clipping |

## Acceptance matrix

| Channel | Format | Local QC | Local gate | Cloud QC | Cloud gate |
| --- | --- | --- | --- | --- | --- |
| Nexus Node | Short | 25/25 PASS | 24/24 PASS | **not run** | **not run** |
| Academic Biohacker | Short | 25/25 PASS | 24/24 PASS | **not run** | **not run** |
| Natkhat Toons | Short | 25/25 PASS | 24/24 PASS | **not run** | **not run** |
| Nexus Node | Long | **no plan** | — | — | — |
| Academic Biohacker | Long | **no plan** | — | — | — |
| Natkhat Toons | Long | 27/27 PASS | 25/25 PASS | **not run** | **not run** |

Short artefacts (rendered on this branch's renderer, `english_renderer.py` unchanged since):

| Artefact | Duration | sha256 (32) | QC | Manifest | Gate |
| --- | --- | --- | --- | --- | --- |
| nexus-node `nexus-robot-video` | 39.566 s | `267cd7f354d399db775034def71868ee` | 25/25 | 8 artifacts ✓ | 24/24 |
| academic-biohacker `academic-post-meal-walk` | 38.366 s | `fc5bcd0046fa8336f50c37de30cbfd1d` | 25/25 | 8 artifacts ✓ | 24/24 |
| natkhat-toons `natkhat-haveli-e4` | 31.667 s | `f1745f347e3dd81cc4210cb1cc1bac5f` | 25/25 | 8 artifacts ✓ | 24/24 |

## Product gaps, stated rather than filled

- **No landscape plan exists for Nexus Node or Academic Biohacker.** `content/longform/` contains only
  `natkhat-toons.json`. The engine is format-agnostic and the card renderer would need a 16:9 profile for
  those channels; today there is nothing to render, so those two rows cannot pass.
- **Cloud**: `production.yml` cannot be dispatched from a feature branch, and PR #5 is unmerged, so no cloud
  run exists for this repair. Six of six cloud cells are unverified.

## Tests

- New `tests/factory/test_longform_schema.py` — 16 tests: landscape plan with `line` builds; portrait plan
  with `dialogue` builds; the dispatcher does not send a portrait plan to the landscape builder; missing,
  blank, non-string and absent scene text are rejected for both schemas; chapters, beats, camera, lighting and
  pickup survive normalisation; captions and moral preserved; `plan_specs` covers both profiles; a long-form
  package with a real 61 s 1920x1080 encode verifies and passes the full gate; a missing manifest entry and a
  stale manifest are reported; cropped composition blocks the long-form package.
- Full suite: **851 passed** (was 835). Golden frames: **78 checked, 0 changed, 0 new**. Workflow audit 0
  findings over 7 workflows. Dependency audit 0 unaccepted.

## Trap worth recording

Running `factory.cli render` or `plan new` locally **consumes the tracked batch ledger**
(`content/batch_2026-11-*.json` is rewritten and older batches are deleted). Two full-suite runs failed with
"topic bank exhausted" because of it, and were green again after `git checkout HEAD -- content/`. Restore
those files before committing, and never treat a local plan run as a read-only operation.

## Owner actions

1. **Merge PR #5** (it now carries both repairs). Everything cloud-side is blocked behind this.
2. After the merge, dispatch and hand back the run IDs:
   `gh workflow run production.yml --ref main -f channel=nexus-node -f plan_id=nexus-power-grid -f upload=false`
   then the same for `academic-biohacker` / `academic-post-meal-walk` and `natkhat-toons` /
   `natkhat-haveli-e4`, and one `-f format=long` run for `natkhat-haveli-stage-e1`.
3. Uploads, public publishing and all three schedules stay disabled until a private upload has been verified
   per channel.

## Verdict

**LOCAL VERIFIED.** Six local acceptance rows are as complete as the product allows (four pass, two have no
plan), the long-form gate path is implemented and green, and no cloud claim is made: the repair has not been
run on a runner, because it cannot be until PR #5 merges.
