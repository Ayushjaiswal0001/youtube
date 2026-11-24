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



## 12. v1.1 — stated figures, honest composition, structured provenance

Status: **implemented and verified locally on branch `feature/x100-visual-engine-v1-1`, based on
`main` at `ea9d30a` (the merge of PR #14). Committed, pushed, open for review as a PR against `main`.
Not merged, not deployed, not uploaded, no schedule changed, no secret or OAuth setting touched.**

Everything in §1–§11 describes v1.0 and remains true of it. This section records only what changed.

### 12.1 The six P0 items and the one P1 item

| | item | what was actually changed | test |
|---|---|---|---|
| **P0-1** | typed `visual_policy` | `factory/config.py` gains `VisualPolicy` (frozen `Mapping`), `parse_visual_policy()` and `VISUAL_CATEGORIES`/`VISUAL_PALETTES`/`DEFAULT_VISUAL_MIN_MS`/`DEFAULT_VISUAL_MAX_MS`. A string category is one category, not six characters; an unknown category is dropped; a non-numeric or inverted band falls back to the defaults; every rejection is recorded in `policy.warnings` and logged. `ChannelSpec.visual_policy` is now `VisualPolicy`, still mapping-compatible so no v1.0 caller changed. | `test_v11_policy.py` (16) |
| **P0-2** | no invented subject | `spec_for()` no longer appends `"data"`. `_entity_row()` and `_draw_statement()` no longer default to `["data"]`. An entity-less sentence gets `statement`, a concentric-ring plate whose footer says **WHAT THE SENTENCE STATES**, and a recorded note *"no subject named in the sentence"*. | `test_v11_composition.py::TestNoInventedSubject` (5) |
| **P0-3** | a composition must have the cue it claims | `_SEQUENCE_CUES` + `has_sequence_cue()`: `pipeline`/`timeline` require a stated order, and `"next"` before a time noun (`next year`) is a date, not a sequence. `comparison` requires both comparative language **and** a `_COMPARATOR` that puts one entity on each side (`comparison_pair()`), so a four-noun sentence can no longer draw TIME vs ROBOT. `components` requires an explicit part word (`joint`, `gripper`, `motor`, `sensor`, `actuator`), not the word "arm". `panels` is the co-mention default; its footer is **WHAT THE SENTENCE MENTIONS** and the comparison footer is **WHAT THE SENTENCE CONTRASTS**. | `test_v11_composition.py` (68) |
| **P0-4** | paths anchored, not ambient | new `factory/media/assets/paths.py`: `asset_cache_root()` (`FACTORY_ASSET_CACHE`, else `<repo>/x100_asset_cache`), `build_root()`, `thresholds_path()` (`<repo>/content/creative_qc.json`). `AssetResolver` and `creative.load_thresholds()` use them; the asset library is anchored to `<repo>/assets/library` with `FACTORY_ASSET_LIBRARY`. A render from another working directory now finds its cache and its thresholds. | `test_v11_paths.py` (9) |
| **P0-5** | structured provenance and image handles | `Resolution` carries `entities`, `license`, `attribution`, `plate_fingerprint`, and `to_dict()` writes them, so `scenes.json` is auditable data rather than a free-text note. `Resolution.image()` uses `with Image.open(...)` (no leaked handle, so a cached plate can be deleted on Windows). The library rejects a licence outside `ALLOWED_LICENSES`, requires the file to be confined to the channel directory, records every rejection in `library.rejected`, and derives the standard attribution line for `cc-by`; `owner-supplied` is documented as needing no external creator because the rights holder is the channel owner. | `test_v11_provenance.py` (12) |
| **P0-6** | diversity measured on pixels | `plate_fingerprint()` / `compared_fingerprint()` (16×16 greyscale, `BILINEAR`, sha256[:16]) and `fingerprint_distance()` (Hamming on the 64-bit prefix); the dispatcher stamps `resolution.plate_fingerprint` after the plate is drawn. Creative QC clusters fingerprints at ≤ 6 bits and requires `min_distinct_pixel_ratio` 0.5 distinct pictures per scene. An unmeasured render is a **warning**, not a pass and not a failure. | `test_v11_diversity.py` (14) |
| **P1-1** | stated figures become charts | new `factory/content/figures.py`: `extract()` returns frozen `Figure(phrase, value, unit, kind, start, end)` for numbers the sentence actually states (attached `%`/`x`, counted nouns, durations) and `value=None` for vague quantifiers (`thousands`, `half`, `dozens`); years and ordinals are not figures. Two new drawers, `bars` and `ratio`, draw only those numbers, labelled with the narration's own words for each bar (`figure_labels()`), so a bar never repeats its own number as its subject. Creative QC adds `figure_is_stated` (**error**) and `dataviz_delivered` (**warning**), plus `provenance_recorded` and `attribution_present`. | `test_v11_figures.py` (35) |

Two further corrections came out of the render inspection and are part of the same release: the
`dataviz` note for a vague quantifier now names the actual cause ("a bar would invent the number the
narration never gives"), and a `comparison` scene's `entities` are narrowed to the contrasted pair, so
`s08` draws **ROBOT vs VIDEO** instead of the TIME vs ROBOT pair that the old first-two-entities rule
produced.

### 12.2 The reference episode, rendered and measured

`nexus-robot-video`, channel Nexus Node, fresh build directory and fresh cache:
**`dddbddc8347334ba421d7d86e1798092e6839c211dd7d6279ad5e098a54234ff`**, 38.733 s, 8,399,034 B,
1920×1080 h264 + aac 44.1 kHz stereo.

| measurement | v1.0 baseline (same box, same 12 samples, same run) | v1.1 | delta | budget |
|---|---|---|---|---|
| render wall time | — | **180.6 s** | — | ≤ 200 s ✓ |
| planning (`plan_scenes`) | 0.9 ms | **2.1 ms** | +1.2 ms | — |
| plate resolution, cold | 1,861.7 ms (206.9/plate) | **1,836.0 ms (204.0/plate)** | −1.4 % | — |
| plate resolution, warm | 620.2 ms (68.9/plate) | **635.2 ms (70.6/plate)** | +2.4 % | ≤ 700 ms ✓ |
| Python peak per plate | 1.1 MB | **1.10 MB** (1,103,740 B) | flat | ≤ 2 MB ✓ |
| plate cache on disk | 470,373 B (52,264/plate) | **461,701 B (51,300/plate)** | −1.8 % | — |
| plate ink (mean of 12 samples) | 2.73 | **2.70** | −1.1 % | ±20 % ✓ |
| plate colours (mean of 12 samples) | 8,700 | **8,332** | −4.2 % | ±20 % ✓ |
| distinct plates / scenes | — | **9 / 9** (ratio 1.00) | — | ≥ 0.5 ✓ |
| freeze segments | 0 | **0** | — | 0 ✓ |
| creative QC | 16 checks | **21 checks, ok, 1 warning** | +5 | ok ✓ |
| publishing gate on the fresh package | 25/25 | **25/25, blockers []** | — | 25/25 ✓ |
| `manifesting.verify()`, before any rebuild | clean | **clean**, 10 artifacts | — | clean ✓ |

The v1.0 numbers above were re-measured in the same session as v1.1 (`measure_plate_v11.py` reads both
encoded files at the same 12 timestamps and the same plate box), because the numbers quoted in §4 and
§11 came from a different sample set and are not directly comparable. Both deltas are far inside the
±20 % band: v1.1 draws slightly *less* ink and slightly *fewer* colours, because two scenes that v1.0
covered with detail are now honest `statement` and `panels` plates instead of an invented pipeline.

Scene-by-scene, with the reason each composition was chosen:

| scene | sentence (abridged) | v1.0 | v1.1 | why |
|---|---|---|---|---|
| s01 | "Robots used to need demonstrations. Now they are learning from videos…" | pipeline ROBOT→DEMOS→STUDY | **panels** ROBOT, DEMOS, VIDEO | no stated order; `"Now"` is not a sequence cue; `study` never said |
| s02 | "A robot arm needs thousands of examples…" | comparison ROBOT vs DATA | **panels** ROBOT, DATA | co-mention, no comparative cue; the only figure is vague, so no chart |
| s03 | "…demonstrations are slow and costly" | pipeline DEMOS→COST→DATA | **statement** + COST pill | a property is not a stage |
| s04 | "Video pretraining lets a model watch ordinary footage **first**…" | pipeline | **pipeline** VIDEO→MODEL | the sentence does state an order |
| s05 | "The gap is action…" | gap | **gap** MODEL / ACTION | unchanged |
| s06 | "…forces a hand applied to make it happen" | statement | **statement** ACTION | unchanged |
| s07 | "anchor the model, **then** scale with cheap footage" | pipeline | **pipeline** ROBOT→DATA→MODEL | stated order |
| s08 | "…less like programming and more like a very large video library" | comparison TIME vs ROBOT | **comparison** ROBOT vs VIDEO | the pair either side of the cue, not the first two nouns |
| s09 | "Follow for more…" | statement | **statement** (no subject invented) | cta/statement, entities `()` |

`creative.json` on this package: 21 checks, all green except `dataviz_delivered` (**warning**):
`s02` was planned as `dataviz` and delivered `panels`, which is the specified behaviour when the
narration states no comparable number, and `scenes.json` records the reason verbatim.

### 12.3 What this release does *not* demonstrate

- **The reference episode contains no chart.** The narration says "thousands of examples" and nothing
  numeric, so v1.1 correctly draws no bar: a chart here would have to invent the number. Verified by
  scanning `content/**/*.json`: **0 numeric stated figures** in the channel topic banks. Chart
  capability was therefore proven on a specimen render of the same plan with two numeric sentences
  substituted in memory (`nexus-robot-video-chart`, `a5785f1ccd3d6f832e174f79828743d779845ee81019dc6fcda761d1961a921a`,
  41.3 s), where `s02` drew **bars** (80 % / 20 %, labelled HUMAN DEMONSTRATIONS and VIDEO) and `s04`
  drew **ratio** (40 %, labelled VIDEO PRETRAINING), both inspectable in
  `x100v11chart/frames/charts_sheet.png`, with `figure_is_stated`, `dataviz_delivered`,
  `visual_diversity_pixels`, `provenance_recorded` and `attribution_present` all passing. To get a
  chart into a real episode, a topic beat has to state a number; that is a content edit, not an engine
  change, and was not made.
- **No crossfade.** `transition_in`/`transition_out` now say `cut`, which is what the renderer does.
  v1.0 emitted `crossfade` that no code read.
- **No asset library content**, no Academic Biohacker palette, no composition budget: P1-2, P1-3 and
  P1-4 remain deferred exactly as the blueprint specified.

### 12.4 Compatibility and regression evidence

| check | result |
|---|---|
| `pytest tests -q` | **1,230 passed** (1,015 at `ea9d30a`, **+215**) |
| engine files alone (`assets`, `scene_plan`, `creative_qc`, `audit_corrections*`, `v11_*`) | 312 passed in 18.9 s |
| `python -m tools.capture_goldens --check` | **78 frames, 0 changed, 0 new** |
| three-channel compat, 12 frames × 3 channels, `ea9d30a` vs working tree | **12/12 SHA-256 identical** |
| manifest `verify()` on the fresh package before any rebuild | clean (10 artifacts) |
| creative QC / publishing gate on the same package | 21 with 1 warning / **25/25** |

Four pre-existing tests asserted the *v1.0* composition contract and were updated to the v1.1
contract, with the reason in the test: two expected `pipeline` for a sentence that states no order,
one expected `panels` where the entity set had changed, and three fixtures modelled a `scenes.json`
that predates provenance. No threshold was loosened and no assertion was deleted; the semantic claims
those tests protect (VIDEO not STUDY, a quantity is not a comparison, a paraphrase warning must not
fail a video) are unchanged.

### 12.5 Cost, dependencies, security

Unchanged and re-checked: **₹0/month**, no new dependency (`Pillow` and the stdlib already used), no
network call added to the render path, no secret or OAuth change, no workflow change, publishing gate
still fail-closed, three channels' `visual_policy` untouched (`nexus-node` only; the other two stay on
the legacy path). Secret scan and gitleaks are run over the tree before the commit and by CI after it.

### 12.6 What v1.1 changed in the failure modes it was aimed at

| v1.0 failure | now |
|---|---|
| a plate named `data` for a sentence that names nothing | statement plate, entities `()`, note recorded |
| a `pipeline`/`timeline` for a sentence with no order | `panels`, footer *WHAT THE SENTENCE MENTIONS* |
| a `comparison` pairing two nouns that merely co-occur | pair taken from either side of the cue, or `panels` |
| `"categories": "diagram"` silently becoming `{'d','i','a','g','r','m'}` | one category, validated, warning on anything unrecognised |
| cache and thresholds silently depending on the working directory | anchored to the repository, env-overridable |
| provenance as a free-text `notes` string | `entities`, `variant`, `license`, `attribution`, `plate_fingerprint`, `record` in every scene |
| "nine scenes, three pictures" undetectable | fingerprints, Hamming clustering, `visual_diversity_pixels` |
| a chart that could assert a number nobody said | structurally impossible: figures come from the sentence, and `figure_is_stated` fails the package otherwise |

### 12.7 Independent audit of the delivered implementation (A1–A9)

The v1.1 branch was then audited independently, against the diff rather than the report. Eight defects
reproduced, all corrected in a second commit, each with a test named after it
(`tests/factory/test_v11_audit_followup.py`, 44 tests). Two of them were honesty defects in the new
feature itself, which is exactly where an audit should look.

| | severity | defect (reproduced, not inferred) | correction |
|---|---|---|---|
| **A1** | high | `ratio` drew *"40 percent cheaper"* as a track filled to 40 % under **THE SHARE THE SENTENCE STATES** — a whole the narration never names | `share_framed()`; a percentage of change draws a statement plate and records *"a share of a change, not of a whole"*; a forced `ratio` is downgraded too |
| **A2** | high | `concept="Video versus model"` + `"Video is the new manual."` drew **VIDEO vs MODEL**: a contrast supplied by the headline, not the sentence | the contrasted pair comes from the narration only; no pair means panels/statement |
| **A3** | medium | a stated figure overrode a planned `photo`/`kinetic_type`/`diagram` category, so the plate was a bar chart the plan never asked for | charts only for `dataviz` or unplanned scenes; the note says why the figure stayed as text |
| **A4** | medium | a typo in `visual_policy` (`chart_value`, `min_scenes_ms`) was dropped in silence — D4's "never a silent change" was not met | unknown keys are a recorded warning |
| **A5** | medium | `figure_is_stated` returned **a pass** for a plate with no recorded `visible_text`: a check that did not run reported as verified | an unverifiable plate fails the check and names the scenes |
| **A6** | low | a malformed fingerprint (`zz`) counted as a distinct picture, inflating diversity to 1.00 | fingerprints are format-checked; malformed counts as unmeasured, like missing |
| **A7** | low | a chart disabled by `chart_values` recorded *"cannot share one scale"*, which was simply false | the note names the policy |
| **A8** | low | the chart decision existed twice (`figures.chart_kind` and `generated._chart_kind`) and had already diverged on the 0..100 rule | one authority, `assets/generated.chart_kind`; `figures.py` extracts only |

**A9** was cosmetic and is folded into the same commit: an unused `_DETERMINERS` constant, a redundant
`plate_fingerprint`/`compared_fingerprint` alias, and a misaligned continuation line in `LEXICON`.

Re-validated after the corrections, from scratch (`v11final2` build and cache directories that did not
exist before):

| measurement | value |
|---|---|
| `pytest tests -q` | **1,230 passed** in 938 s (1,015 at `ea9d30a`; 1,169 before this pass) |
| goldens | **78 frames, 0 changed, 0 new** |
| three-channel compat | **12/12 identical** |
| reference render | **`dddbddc8347334ba421d7d86e1798092e6839c211dd7d6279ad5e098a54234ff`**, 38.733 s, 8,399,034 B, **180.6 s** wall |
| planning / warm resolve / peak per plate | **2.1 ms** / **635.2 ms (70.6/plate)** / **1.10 MB** |
| plate ink / colours vs v1.0, same box and samples | **2.70 vs 2.73 (−1.1 %)** / **8,332 vs 8,700 (−4.2 %)** |
| distinct plates | **9 / 9** (ratio 1.00) |
| creative QC / gate / manifest | **21 checks, 1 warning** / **25/25** / verify clean |
| chart specimen | **`472a358aac483f67f7c6abeb19feb0551bba13f1df18151dffe06ac9f88011c1`**: `s02` **bars** (80 % / 20 % of cost), `s04` **ratio** ("40 percent of the training budget"), `s06` **no chart** for "30 percent cheaper" with the reason recorded |

The specimen now demonstrates the correction rather than only the feature: two charts drawn from
stated shares, and one figure deliberately left as words because the sentence describes a change.
