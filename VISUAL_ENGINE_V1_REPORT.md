# X100 Visual Engine v1.0 — local execution report

Status: **implemented, verified locally, committed as `44030107adf480b913b770811b02a0c60feb89a6` on
`feature/x100-visual-engine-v1`, and pushed; open for review as PR #13 against `main`. Not deployed and
not uploaded.**
Base `b87edb3` = `main` after PR #12. The sections below are the historical record of the passes that
produced this commit: they were written while the work was uncommitted, and their measurements, audit
verdicts and limitations are reported exactly as they were measured at the time.

Scope: **Nexus Node is fully integrated.** Academic Biohacker and Natkhat Toons are **compatibility
only** — they must render exactly as before, and they do (pixel-identical, see §7).

---

## 1. What was wrong

The audit in Phase A found the root cause, and implementation confirmed it: the Shorts renderer had
**no asset layer at all**. Every pixel came from `_draw_motif`, a switch over 30 motif kinds drawing
lines, rings and boxes inside a fixed 720×550 plate, one motif per narration line. A 38-second video
was therefore seven cards of type with a decorative diagram behind it, and no code path existed by
which a picture of anything could ever enter a render.

Measured on the encoded baseline (`nexus-robot-video`, 38.733 s): 8,535 unique colours in a sampled
frame, 52 % of pixels below luminance 24, ink gradient 2.23 inside the motif plate. It is a dark
type-and-geometry compositor.

## 2. What was built

```
factory/content/scene_plan.py          semantic scene planner (9 scenes from 7 narration lines)
factory/media/assets/base.py           provider interface, deliberately unimplemented
factory/media/assets/metadata.py       provenance record + licence allow-list
factory/media/assets/validators.py     file / image / record validation, aspect drift
factory/media/assets/cache.py          content-addressed SHA-256 cache (outside Git)
factory/media/assets/local.py          approved local asset library, keyword indexed
factory/media/assets/generated.py      deterministic diagrams + 12 pictograms
factory/media/assets/resolver.py       library → provider → generated, reports what it drew
factory/media/english_renderer.py      visual plate, dispatcher, plate motion, framing evidence
factory/qa/creative.py                 creative QC, thresholds, measurable checks
factory/qa/publish_gate.py             + creative_quality check for scene-planned videos only
factory/manifesting.py                 + scenes.json / creative.json in the canonical artefacts
factory/config.py                      ChannelSpec.visual_policy (opt-in per channel)
channels/nexus-node.json               visual_policy: scene_planning + allowed categories
content/creative_qc.json               published thresholds
tests/factory/test_scene_plan.py       17 tests
tests/factory/test_assets.py           33 tests
tests/factory/test_creative_qc.py      18 tests
```

### 2.1 Scene planner

Boundaries are semantic: sentence ends and clause marks are read from the **line text**, then zipped
against the TTS word timings, because the tokeniser strips punctuation (`demonstrations.` arrives as
`demonstrations`). A long clause is split at the most natural pause that does not create a sliver; a
short line is merged into its neighbour. The plan **tiles the narration exactly** — each scene starts
where the previous ended — and `narration_ms` is measured from the first spoken word to the last, so
"the scenes cover the narration" is exact rather than approximate.

The scene count is **derived, not imposed**: `allowed_scene_count(narration_ms)` with a 2–8 s band.
For `nexus-robot-video` (37.438 s of narration) that is 5–18, and the planner produced 9.

Decisions are recorded, not implied: `{"action": "split"|"merge"|"exception", "reason": ...}`.

### 2.2 Asset layer

- **Provenance is mandatory.** `AssetRecord.problem()` refuses an unknown licence, a CC-BY asset with
  no attribution text, a generated asset with no generation spec, and an external asset with neither
  a creator nor a URL.
- **The cache is content addressed**: `<root>/<channel>/<kind>/<sha256[:16]>.ext` plus a JSON
  sidecar, `x100_asset_cache/` (gitignored). Identical bytes are stored once; `verify()` re-hashes,
  so a corrupted entry is detected instead of trusted.
- **The local library** (`assets/library/<channel>/`) is the only route for a real photograph: drop a
  licensed image plus an optional sidecar (`keywords`, `license`, `creator`) and the resolver will
  prefer it over anything generated.
- **The provider interface exists and is disabled.** `DisabledProvider.enabled()` returns `False`,
  so every resolve records `provider: none is not enabled`. A fake provider in the tests proves the
  wiring works if one is ever authorised.

### 2.3 Generated diagrams

Twelve pictograms drawn from primitives — video frames, a model graph, a gripper applying force, a
two-link robot arm, a dataset stack, lattice pylons with conductors, a queue, a bolt, a clock, a book,
a person demonstrating, a cost marker — composed into seven schematics: `pipeline`, `gap`,
`comparison`, `topology`, `components`, `layers`, `timeline`, plus `cta` for the closing line.

Three rules keep them honest:

1. **The composition comes from the sentence.** Entities are extracted with a domain lexicon
   (`robot`, `video`, `model`, `action`, `data`, `grid`, `queue`, `time`, …); a sentence about a gap
   gets the gap composition, a call to action gets the CTA card.
2. **No invented magnitude.** An early version drew comparison bars, which asserted a ratio the
   narration never stated. It was replaced with two labelled tradeoff panels.
3. **No repeated composition in a row.** Two identical cards read as a bug, so a fixed ladder steps
   to the next composition that still explains the sentence.

Titles are cut on a word boundary (`short_title`), because the first pass printed
`A ROBOT ARM NEEDS THOUSANDS OF EXA` in the most prominent line on the card.

### 2.4 Dispatcher and plate

`VisualDispatcher` builds the plan once per video, resolves every scene, and pre-draws each visual.
The frame loop asks it for "the scene at time *t*" — it never re-plans per frame.

The plate is 912×640 at `(84, 716)–(996, 1330)`: the safe width **divided by the maximum camera
push-in**, so the plate cannot leave the safe area, and it stops above the caption band. The brand
row, headline, captions, progress bar and entrance wipe are the same code as before, extracted into
`_draw_chrome` / `_draw_footer` / `_draw_entrance` so the two card renderers cannot drift.

Motion inside the plate: a slow 5.5 % push-in with a lateral drift, cropped from a bilinear resize, and
a 0.30 s rise-and-fade entrance with an accent rule marking the cut. Neither file trips
`freezedetect -50dB/0.6 s` (§5).

### 2.5 Creative QC

Fourteen checks, split into failures and warnings, all computed from the render's own artefacts:

| check | what it refuses |
|---|---|
| `scenes_tile_narration` | a gap or overlap between scenes |
| `scene_count_in_derived_window` | a count outside the window derived from the narration |
| `pacing_inside_band` | a scene outside 2–8 s with no recorded reason |
| `scene_rate` | fewer than 1.5 scenes per 10 s |
| `distinct_visuals` | one visual reused across the video |
| `composition_variety` | fewer than two compositions |
| `no_repeated_composition_runs` | the same composition three times in a row |
| `every_scene_has_a_visual` | a scene that resolved to nothing |
| `rendered_category_recorded` | a scene whose rendered category was never set |
| `titles_fit_the_plate` | a title over 30 characters (warning) |
| `on_screen_text_short` | more than 8 words on screen (warning) |
| `no_caption_collisions` | caption/plate overlap on any sampled frame |
| `captions_inside_safe_area` | caption or headline overflow |
| `visual_inside_safe_area` | the plate drifting outside the safe area |

Thresholds live in `content/creative_qc.json`; the loader only accepts keys that already exist in
`DEFAULTS`, so the file can tune a number but cannot switch a check off. An empty scene list **fails**
rather than passing vacuously.

## 3. Baseline vs upgraded — measured

Same plan (`nexus-robot-video`), same TTS text, same encoder settings, same machine.

| | baseline (`HEAD`) | upgraded |
|---|---|---|
| duration | 38.733 s | 38.733 s |
| resolution / fps | 1080×1920 / 30 | 1080×1920 / 30 |
| size | 9,462,159 B | 8,492,551 B |
| SHA-256 | `45c2222…` | `2f4a936…` |
| render time | 188.8 s | 159.9 s |
| visual units | 7 (one per line) | 9 planned scenes |
| compositions | 1 motif per line, 30 kinds drawn | 6 distinct schematics (10 defined) |
| plate ink (mean) | 1.65 | 3.09 (**+87 %**) |
| plate colours (mean) | 4,195 | 8,540 (**+104 %**) |
| full-frame colours | 8,535 | 9,313 (+9 %) |
| freezes (`-50dB/0.6 s`) | 0 | 0 |
| caption collisions | 0 | 0 |
| creative QC | — (did not exist) | **PASS 16/16** |
| publishing gate | 24/24 | **25/25** |

Measurement method: twelve timestamps sampled from both encoded files with `ffmpeg`, ink = mean
absolute luminance gradient inside the plate region, colours = unique RGB triples on a half-scale
crop. Both files measured with the same script (`x100base/measure_plate.py`), which lives outside the
repository. The final render (`6f9c1ff…`) is the one measured; its file size differs from an earlier
pass only because TTS audio is non-deterministic, not because the picture changed — the plate numbers
are identical to the byte.

Frame inspection (nine timestamps, one per scene, from the encoded MP4): each cut lands on a new
schematic, the caption never overlaps the plate, the plate never touches the safe margin, and the
palette and typography are unchanged.

## 4. Performance

| stage | cost |
|---|---|
| scene planning | ~10 ms |
| resolving 9 scenes (cold, with diagram drawing) | ~1.9 s |
| resolving 9 scenes (warm cache) | ~0.2 s |
| plate compositing per frame | ~12 ms |
| whole render | 159.9 s vs 188.8 s baseline |

The render got **faster**, because a plate paste replaced the per-frame motif drawing that drew
dozens of primitives per line. Memory: nine 912×600 RGB images ≈ 1.6 MB each, held for the render.

## 5. Motion and encoding

`freezedetect=n=-50dB:d=0.6` reports **0 segments in both files**, and the previous finding still
holds: the push-in is what keeps a still card alive after h.264. The plate adds a second, larger
moving area, which is why the upgraded card measures 3.10 ink instead of 1.65 without costing
bitrate (the file is actually 10 % smaller).

## 6. Reproducing the render locally

```bash
cd <repo>
export PYTHONPATH=$PWD PYTHONIOENCODING=utf-8
export FACTORY_BUILD_DIR=/c/Users/DELL/AppData/Local/Temp/x100ship/build   # must exist
python /c/Users/DELL/AppData/Local/Temp/x100base/render_plan.py nexus-robot-video nexus-node --force
```

`factory.cli render --plan-id` cannot be used for this plan: it only reads plans from
`content/batch_*.json`, and writing one would dirty a tracked file. `render_plan.py` (outside the
repository) builds the plan from the topic bank with the same `plan_from_topic` the selector uses and
calls `render_episode`.

Artefacts written per episode now include `scenes.json` (plan + per-scene resolution + decisions) and
`creative.json` (the creative verdict). Both are in the manifest's canonical list, so they are hashed
and verified with everything else.

## 7. Channel compatibility

Academic Biohacker and Natkhat Toons have **no `visual_policy`**, so `render_english` builds no
dispatcher and takes the legacy path. Proof, not assertion:

- 12 frames composed at four timestamps for all three channels, once with `HEAD`'s renderer
  (`git archive HEAD` into a temp directory) and once with the working tree: **12/12 SHA-256
  identical**.
- A full Academic Biohacker render (`academic-post-meal-walk`, 38.366 s) after the change: no
  `scenes.json`, no `creative.json`, `story.json` still reporting its 7 legacy scenes, gate
  unaffected.

Natkhat Toons uses `hindi_renderer.py`, which was not touched; the portrait card path it shares was
verified by the same frame comparison.

**Compatibility is not deployment.** Only Nexus Node is claimed as integrated into the visual engine.

## 8. Rollback

The whole implementation is one commit, `44030107adf480b913b770811b02a0c60feb89a6` on
`feature/x100-visual-engine-v1`, so the correct full rollback is a revert:

```bash
git revert 44030107adf480b913b770811b02a0c60feb89a6
```

That keeps history linear and needs no force-push and no history rewrite. If a **partial** rollback is
wanted instead, restore the specific paths involved (never the whole tree):

```bash
git checkout 4403010^ -- path/to/file        # one file, back to its pre-PR content
```

On a branch where this work was never committed (the state this section was originally written in),
the equivalent was `git checkout -- <tracked files>` plus `git clean -fd <new files>`; the commit now
exists, so the revert above supersedes it. The cache (`x100_asset_cache/`) and any build directory are
disposable and git-ignored. `pipeline_state/` is tracked and was restored to `HEAD` after the render
runs.

## 9. Known limitations

- **No third-party imagery exists**, by design and by budget (₹0/month, no provider, no downloads).
  Every visual is a locally drawn schematic. A footage or photo layer only appears once the owner
  supplies licensed files in `assets/library/<channel>/`.
- **Category coverage is diagrams only** for Nexus Node: `coverage_category` reports `diagram` for all
  nine scenes, honestly, because that is what was drawn.
- **`dataviz` is planned but not rendered as charts.** The planner can classify a scene as dataviz;
  the generator has no chart composition, and drawing one would require numbers the narration does
  not assert.
- **Pictograms are geometric**, not illustrated characters. They read at phone scale but they are not
  stock photography and do not pretend to be.
- **The CTA card** is intentionally plain: rings, an arrow, three beats.
- **Scene planning is tuned on one plan.** Nine scenes for 37 s of narration is inside the derived
  window, but the split logic has been exercised on a single script plus synthetic cases.

## 10. Where this leaves the directive

Delivered: planner, asset layer, cache, generators, dispatcher, renderer integration, sync assertion,
technical QC (unchanged), creative QC, gate integration, configurable thresholds, tests, a real
upgraded render, measured before/after, channel compatibility proof, rollback.

Not delivered, and not claimed: any external asset acquisition, any paid service, any deployment or
upload.

Delivery status, as of this revision: committed as `44030107adf480b913b770811b02a0c60feb89a6`, pushed
to `origin/feature/x100-visual-engine-v1`, opened as PR #13 against `main`. Still not merged, not
deployed, and nothing is uploaded.

## 11. Defect-correction pass (independent audit findings H1–H4, M1–M4)

Two read-only audits of the implementation above returned **READY AFTER SPECIFIED FIXES** with four
release blockers. All four, and all four medium findings, are now fixed in source, each with the test
that fails if it comes back. No threshold was loosened and no test was weakened to reach this state.

### High

| | defect | fix | regression test |
|---|---|---|---|
| **H1** | `factory/orchestrator.py` built its artifact dict by deriving names from `optional.replace(".json","")`, so `scenes.json` and `creative.json` were written to disk but never declared. `manifesting.verify()` then reported *unlisted artifact on disk* and the gate failed 24/25 with `blockers: ['manifest']`. CI only passed because the workflow happens to run `factory.cli manifest` (which rebuilds the manifest) before the gate. | explicit `(name, filename)` pairs including `scene_plan`/`scenes.json` and `creative_qc`/`creative.json`, matching `CANONICAL`. The `.replace()` derivation also silently shadowed `video.json`; that is gone. | `test_audit_corrections.py::TestH1ProductionManifest` (4 tests), including a **negative control** that leaves the same files on disk but out of the manifest and asserts `verify()` complains |
| **H2** | `_active_line()` returned `lines[-1]` inside an inter-line pause, so for 6 gaps × 180 ms (32 of 1,162 frames, 2.8 %) the card showed the *next* line's headline and counter over the previous line's plate. Pre-existing at `HEAD`. | gaps return the **preceding** line and its index; only after the final line's end does the final line remain active. | `TestH2ActiveLine` (6 tests): every gap at four offsets, the post-roll case, inside-line case, pre-roll case, and headline-counter co-derivation |
| **H3** | `_draw_gap` and `_draw_topology` indexed `entities[1]` unconditionally. `spec_for(narration="That is the whole point.")` reachable through the diversity ladder produced `IndexError: list index out of range` and killed the render. | `<2` entities falls back to `_draw_statement` inside all three two-subject drawers, and the selection step refuses `NEEDS_TWO` compositions (and skips them on the ladder) when fewer than two *stageable* entities exist. | `TestH3SingleEntity` (7 tests): every composition with 0/1/2/3 entities, the exact reachable ladder path, and a forced-variant belt-and-braces case |
| **H4** | Two semantic errors. `study` listed `learning` as a synonym, so "learning from videos" drew a **STUDY** plate for a word the narration never says. And `cost` (a property) was drawn as a pipeline **stage**, rendering "DEMOS → COST → DATA" for a sentence about slow demonstrations. | synonym list corrected; `ATTRIBUTE_ENTITIES = {cost, time}` can never be a pipeline stage; a sentence that only states a property becomes a single-subject `statement` plate. Plural-tolerant entity matching (`videos` → `video`) added while fixing it. | `TestH4SemanticCorrectness` (7 tests) built from the audited narration itself, plus a no-invented-numbers invariant |

### Medium

| | defect | fix |
|---|---|---|
| **M1** | A cross-line merge kept the pre-merge word-index space (decision at 8,660 ms, deviation at 8,880 ms, scene at 9,100 ms) and stamped a hardcoded *"single continuous idea"* reason. | merged scenes record `merged_lines` and `word_range: None`; `_best_cut` refuses to cut inside a merged piece; a merge that would exceed `max_scene_ms` is refused with a `keep_separate` decision; deviation reasons are derived from the decisions that were actually taken |
| **M2** | Creative QC judged pacing against global defaults even when the plan declared its own band. | the plan's `min_scene_ms`/`max_scene_ms` win when present (`band_source` is recorded); config file and code defaults still apply when the plan is silent |
| **M3** | Nothing checked that a plate's title belonged to the video at all. | `title_matches_narration` and `headline_matches_active_line`, both **warnings** (a warning never blocks a gate) |
| **M4** | Legacy renders wrote a zero-valued `visual` element into `framing.json`, reporting a measurement that was never taken. | the element is emitted only when a dispatcher exists, so its presence means a plate was drawn and measured |

M3's first version compared a title with its own scene's words and flagged 2 of 9 scenes on the real
render — "WATCH AND LEARN" and "THE DATA PROBLEM", both legitimate paraphrases. It now compares
against the **whole episode's** vocabulary, which still catches the audited defect (a plate naming
something the video never mentions) and does not cry wolf about paraphrase.

### One further finding, fixed in the same pass

The render inspection that followed the H4 fix showed two plates reading **"ROBOT vs DATA / TWO ROUTES
TO THE SAME RESULT"** under a sentence that states a quantity ("needs thousands of examples"). That is
the same class of error H4 was about — an invented relationship — so it is fixed here rather than
deferred:

- `comparison` now requires comparative language (`more`, `less`, `than`, `vs`, `twice`, …).
- A new neutral composition, **`panels`**, draws two things the sentence mentions side by side: no
  "vs" badge, no connecting arrow, footer *"WHAT THE SENTENCE MENTIONS"*.
- The comparison footer no longer claims two routes lead to one result; it says
  *"WHAT THE SENTENCE CONTRASTS"*.

That makes **10 defined compositions**, 6 of them used in this video.

### Evidence for the corrected build

| | result |
|---|---|
| `python -m pytest tests -q` | **1015 passed** (12 m 43 s) — 968 before this pass, +47 new |
| `python -m tools.capture_goldens --check` | **78 frames, 0 changed, 0 new** |
| legacy compatibility, 12 frames × 3 channels, `HEAD` vs working tree | **12/12 SHA-256 identical** |
| `manifesting.verify()` on the fresh package, **before** any `cli manifest` rebuild | **clean**, 10 artifacts including `scene_plan` + `creative_qc` |
| creative QC | **16/16**, no warnings |
| publishing gate on the same package | **25/25**, no blockers |
| scene plan | 9 scenes, `problems: []`, `duration_deviation: none` |
| frames changed by H2 | 32 of 1,162 (6 gaps × 0.18 s × 30 fps) |

Visual inspection of the encoded file (`x100inspect/`): all six inter-line pauses show the preceding
line's headline and its counter (01…06 with WATCH AND LEARN … VIDEO IS THE NEW MANUAL, never 07/FOLLOW);
the s01 plate reads ROBOT → DEMOS → VIDEO with no STUDY; s03 is a single-subject statement with a COST
pill instead of cost-as-stage; s02 and s06 are neutral panels.

### Remaining limitations, restated honestly

- The `timeline` composition draws an axis, which is a mild chronological metaphor. For s08 ("the
  future of robot training…") it is justified by the word *future*, but a stricter rule — timeline
  only when the sentence states an order — is not implemented.
- `panels` and `statement` are honest but plainly schematic. They assert nothing false and show
  nothing photographed.
- Everything in §9 still stands: no third-party imagery, diagrams only, pictograms are geometric,
  planning has been tuned on one plan plus synthetic cases.
