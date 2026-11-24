# X100 Visual Engine v1.1 — Post-Merge Audit

Status: **audit complete, read-only.** No code was changed to produce this document. Every finding below
was reproduced on the merged `main`, not copied from the v1.0 report.

Repository: `Ayushjaiswal0001/youtube` · merged PR: #13
Merged base:

```
e5cff1789a60d4dfd133155cbeb48d10c7ca37a2  Merge pull request #13 from Ayushjaiswal0001/feature/x100-visual-engine-v1
6bbfd6b26c119bf8e4abc9437228867de8810a8e  docs: record the v1.0 commit, branch and PR in the visual engine report
44030107adf480b913b770811b02a0c60feb89a6  feat: implement X100 visual engine v1.0
b87edb36ef491dfcc597e068a1da39d96cfb05e9  main before the engine
```

## 1. Verified foundation

| check | evidence |
|---|---|
| PR #13 merged | `state: MERGED`, `mergedAt: 2026-11-24T12:28:49Z`, `mergedBy: Ayushjaiswal0001` |
| merge commit | `e5cff17`, parents `b87edb3` + `6bbfd6b` |
| both PR commits in `main` | `git merge-base --is-ancestor` → yes for `4403010` and `6bbfd6b` |
| current `main` | `e5cff17`, local tree fast-forwarded, `## main...origin/main` |
| working tree | clean before and after this audit |
| health check | `factory.cli doctor`: ffmpeg, ffprobe, chrome, fonts, build root, 3 channel configs OK |
| visual-engine tests | `115 passed` in 22.08 s (the six engine test files) |
| full suite (last run on this tree) | `1015 passed` |

Merged engine size: `scene_plan.py` 571 · `creative.py` 351 · `assets/` 1,550 (8 files, of which
`generated.py` alone is 863) · plus the renderer, gate, manifest and orchestrator edits.

## 2. Measured v1.0 baseline (this machine, merged code)

Established for v1.1 budget work, so no later claim has to invent a number.

| metric | value | how measured |
|---|---|---|
| episode | `nexus-robot-video`, 38.722 s, 1,162 frames, 1080×1920 @30 | `ffprobe` on the encoded file |
| encoded size | 8,487,833 B | `render.json` |
| render wall time | **160–180 s** (159.9 s idle, 179.6 s while the test suite ran) | `render_plan.py` timer |
| scene planning | **0.9 ms** | `plan_scenes` on the real timed lines |
| plate resolution, cold | **1,861.7 ms** for 9 plates (**206.9 ms** each) | fresh cache directory |
| plate resolution, warm | **620.2 ms** for 9 plates (**68.9 ms** each) | same directory, second pass |
| Python allocation peak per plate | **1.1 MB** | `tracemalloc` |
| cache footprint | **470,373 B** for 9 plates (**52,264 B** each) | `x100_asset_cache/` on disk |
| plate ink (mean) | **3.10** (pre-engine 1.65, **+87.9 %**) | `measure_plate.py`, plate region only |
| plate colours (mean) | **8,447** (pre-engine 4,195, **+101.4 %**) | same script |
| freezes | 0 | `freezedetect -50dB/0.6 s` |
| compositions used | **6 of 10** (pipeline ×3, panels ×2, gap, statement, timeline, cta) | `scenes.json` |
| pictograms defined | **12** | `generated.ICONS` |
| creative QC | 16/16 | `creative.json` |
| publishing gate | 25/25 | `evaluate_publish_gate` |

The v1.0 headline holds: the plate carries roughly twice the ink and twice the colour of the
type-and-motif card it replaced, for 10 % less file size and a faster render. What it does **not** carry
is *content*: all nine scenes report `coverage_category: diagram`, and seven of nine use one of four
compositions (`pipeline` ×3, `panels` ×2, `gap`, `statement`).

## 3. Outstanding findings, verified one by one

Severity is judged on user-visible consequence, not on tidiness. "Reproduced" means a command in this
audit produced the quoted output on `e5cff17`.

**The twelve limitations named in the v1.0 brief, and where each is verified below:**

| # | v1.0 limitation | verified in | v1.1 class |
|---|---|---|---|
| 1 | schematic pictograms instead of contextual imagery | 3.13, §2 (12 pictograms) | — accepted, not a defect |
| 2 | no third-party imagery or footage | 3.1, 3.13 | P1-2 (library pilot); footage deferred |
| 3 | dataviz classified but not rendered | **3.2** | **P1-1** (release headline) |
| 4 | geometric pictograms and visual repetition | §2 (6 of 10 compositions, 7 of 9 scenes in four) | P1-4 |
| 5 | Academic and Natkhat compatibility-only | **3.12** | P1-3 (Academic), P2 (Natkhat) |
| 6 | timeline chronology metaphor | **3.4** | **P0-3** |
| 7 | CWD-relative asset cache | **3.7** | **P0-4** |
| 8 | unconfined sidecar paths | **3.9** | **P0-5** |
| 9 | image file handle leak | **3.8** | **P0-5** |
| 10 | `distinct_visuals` counts digests | **3.5** | **P0-6** |
| 11 | entity-less DATA fallback | **3.3** | **P0-2** |
| 12 | unvalidated `visual_policy` | **3.6** | **P0-1** |

**Three findings that are not in the v1.0 limitation list** — all verified during this audit:

| # | finding | section | class |
|---|---|---|---|
| N1 | `transition_in`/`transition_out` (and `fallback`) are emitted but no renderer code reads them; `scenes.json` claims a crossfade the video does not perform | **3.11** | P1-5 |
| N2 | per-scene provenance is a free-text `notes` string; `scenes.json` carries no structured `entities` or `variant` | **3.10** | **P0-5** |
| N3 | `visible_text` is recorded per scene and no QC check reads it, so nothing verifies that a plate shows words grounded in the narration | 3.10, roadmap P0-5 / P1-1 (`figure_is_stated`) | P1-1 |

### 3.1 HIGH — the asset layer has never been exercised

| | |
|---|---|
| Where | `factory/media/assets/resolver.py:104` `_from_library`, `factory/media/assets/local.py:44` `_scan` |
| Evidence | `assets/library/` **does not exist** (`Path('assets')/'library'` → `is_dir() == False`). Every resolution record carries `attempts: ['library: no entry matched the scene query', 'provider: none is not enabled', 'generated: cache hit …']` |
| Impact | The "prefer a real picture, fall back to a drawing" design is **unproven in production**; the first owner-supplied image will be the first test of it |
| Complexity | Low — the code path exists and is unit-tested, but never with a real file end-to-end in a render |
| v1.1? | **Yes, P1** (roadmap P1-2) — an intake tool plus a pilot library of owner-supplied files converts a promise into a working feature, after the P0 items |

### 3.2 HIGH — `dataviz` is classified, then ignored

| | |
|---|---|
| Where | `factory/content/scene_plan.py:238` (`_objective_of` returns "show the comparison or magnitude"), `generated.py` `_DRAWERS` (10 entries, none is a chart) |
| Reproduced | `_category_of` on "Robots need thousands of demonstrations, and video is 40 percent cheaper." → `'dataviz'`; the composition chosen for the same sentence is `'comparison'` — two labelled panels, no magnitude |
| Impact | A sentence that states a number gets a picture that shows none. The scene plan's own objective is unmet by the render, and nothing in the pipeline notices |
| Complexity | Medium — parsing stated figures honestly, one chart drawer (`bars`/`ratio`), and a QC check that a `dataviz` scene contains the stated number |
| v1.1? | **Yes, P1** (roadmap P1-1) — this is the single largest visual-quality gain available at ₹0 |

### 3.3 HIGH — invented subject for entity-less sentences

| | |
|---|---|
| Where | `generated.py:240-244`: if fewer than two entities are found, the loop appends `"data"` |
| Reproduced | `spec_for(concept="That is the whole point.", narration="That is the whole point.")` → `entities=('data',)`, `variant='pipeline'`; same for `"It just works."` |
| Impact | The plate names a noun the narration never says, and draws it as a process stage. This is the exact defect class the H4 audit finding was about (STUDY), reintroduced by a different path |
| Complexity | Low — replace the invented entity with a neutral statement plate and record the reason |
| v1.1? | **Yes, P0** |

### 3.4 MEDIUM — composition chosen from a keyword the sentence does not support

| | |
|---|---|
| Where | `generated.py:194-195`: `year|month|decade|future|next` → `timeline`; `pipeline` is the fall-through |
| Reproduced | For the real s08 narration ("The future of robot training looks less like programming and more like a very large video library"), `variant='timeline'` while **no sequence word is present** (`['first','then','next','finally','after']` → `[]`) |
| Impact | A chronology the video does not assert. Mild for "the future of…", wrong for any sentence that merely contains "next" or "years" |
| Complexity | Low — require an ordering cue (or an explicit `future` + a stated change) for `timeline`/`pipeline`, otherwise `panels`/`statement` |
| v1.1? | **Yes, P0** — same class as H4, cheap to fix, easy to test |

### 3.5 MEDIUM — `distinct_visuals` counts specs, not pictures

| | |
|---|---|
| Where | `factory/qa/creative.py:203-212` |
| Evidence | The metric is `len(set(asset_ids)) / len(scenes)`; a generated `asset_id` is the **spec digest** (`gen-pipeline-5d5820bb`), so two different specs that happen to draw similar plates count as two visuals |
| Impact | The one check that is supposed to detect "nine scenes, three pictures" can be satisfied by nine spec strings. In practice v1.0's plates are genuinely distinct, so this is a measurement weakness, not a live defect |
| Complexity | Low — hash the rendered plate at low resolution and cluster; keep the existing check as a fast pre-check |
| v1.1? | **Yes, P0** (roadmap P0-6) — it is the gate for claiming visual diversity |

### 3.6 MEDIUM — `visual_policy` is unvalidated and silently mis-parses

| | |
|---|---|
| Where | `factory/config.py:113` field + `:213` `dict(factory.get("visual_policy") or {})` |
| Reproduced | `visual_policy={"categories": "diagram", "min_scene_ms": "two thousand"}` is accepted verbatim; `set("diagram")` becomes `{'d','i','a','g','r','m'}`, and `_category_of` then returns `kinetic_type` for a robotics sentence |
| Impact | A typo in a channel config changes the visual language of every scene, silently, with no error. Same hazard for `min_scene_ms` reaching comparisons as a string |
| Complexity | Low — parse and validate into dataclass fields, warn and fall back on bad values |
| v1.1? | **Yes, P0** — configuration that silently misbehaves is a reliability defect |

### 3.7 MEDIUM — cache and threshold paths are CWD-relative

| | |
|---|---|
| Where | `factory/media/assets/resolver.py:32` `CACHE_ROOT = Path("x100_asset_cache")`; `factory/qa/creative.py` `load_thresholds(path=None)` resolves relative to the process CWD |
| Evidence | `CACHE_ROOT` → `WindowsPath('x100_asset_cache')`, resolved as `<cwd>/x100_asset_cache`. In this session that produced cache directories in the repository root |
| Impact | Running the factory from another directory silently loses the cache (cold renders everywhere) or writes it somewhere unexpected; a CI job and a local run do not share state |
| Complexity | Low — anchor to the repo root (or `FACTORY_BUILD_DIR`), allow an env override |
| v1.1? | **Yes, P0** |

### 3.8 LOW — image handle leak in `Resolution.image()`

| | |
|---|---|
| Where | `resolver.py:63` `return Image.open(self.path).convert("RGB")` — no context manager, so the file handle lives until GC |
| Evidence | `inspect.getsource(Resolution.image)`; by contrast `local.py:82` and `validators.py:38,50` use `with` |
| Impact | One leaked handle per library-backed plate; with 9 scenes per video and repeated renders, plausible on Windows (file locked), invisible today because no library file exists |
| Complexity | Trivial — `with Image.open(...) as im: return im.convert("RGB")` |
| v1.1? | **Yes, P0** (three lines) |

### 3.9 LOW — sidecar values are trusted

| | |
|---|---|
| Where | `local.py:60-92`: `license` falls back to `"owner-supplied"` and `local_path` is recorded as the path on disk |
| Impact | A hand-edited sidecar can claim any licence, and the record's `local_path` is not confined to the library root. With a public repo of owner-supplied media this is a provenance weakness rather than an exploit |
| Complexity | Low — validate `license` against `metadata.ALLOWED_LICENSES`, refuse unconfined paths, require attribution when the licence needs it |
| v1.1? | **Yes**, P0-5 for the path/attribution checks, P1-2 for the first real file |

### 3.10 LOW — per-scene provenance is a string, not data

| | |
|---|---|
| Where | `resolver.py:186` builds `notes=f"variant={spec.variant} entities={','.join(spec.entities)}"` |
| Evidence | Every `resolution` block in the produced `scenes.json` has **no `entities` key**; the entities exist only inside `visible_text` and a free-text note |
| Impact | A reviewer cannot audit "which pictogram, from which entities, for which sentence" without re-running the generator; QC cannot check composition-to-entity agreement |
| Complexity | Trivial — add `entities` and `variant` as structured fields |
| v1.1? | **Yes, P0** |

### 3.11 LOW — transitions and motion are declared but unread

| | |
|---|---|
| Where | `scene_plan.py:520-521` sets `transition_in="cut"`, `transition_out="crossfade"`; `grep` finds **no** reader in `factory/media/english_renderer.py` |
| Evidence | `renderer` reads only `resolution.motion` (line 1289); `motion_plan()` returns a fixed push-in treatment; nothing consumes `transition_in/out` or the `fallback` field |
| Impact | The scene plan documents behaviour the renderer does not have. Today the video cuts; the metadata says crossfade. Either implement or stop claiming it |
| Complexity | Low–medium (a real crossfade touches the encode loop) |
| v1.1? | **Partly, P1** (roadmap P1-5) — at minimum make the metadata truthful; a real crossfade is P2 |

### 3.12 MEDIUM — channel coverage is one channel

| | |
|---|---|
| Where | `channels/academic-biohacker.json` and `channels/natkhat-toons.json` have **no** `visual_policy` |
| Evidence | loader: `visual_policy=None` for both; the engine is opt-in and they take the legacy path, which is why compatibility is 12/12 pixel-identical |
| Impact | Two of three channels still render type cards. The engine's visual language (dark technical schematics) is wrong for a Hindi children's cartoon, so simply enabling it would be a regression in tone |
| Complexity | Medium — each channel needs its own visual language, not a flag flip |
| v1.1? | **Academic: yes (P1, light "paper" palette). Natkhat: no — needs a cartoon-scene renderer, P2** |

### 3.13 Using v1.0's own limitation list as a checklist

| v1.0 statement | Verified on `e5cff17` |
|---|---|
| "No third-party imagery exists, by design" | **True** — `assets/library/` absent, `DisabledProvider().enabled() == False`, no network code in the new modules |
| "Category coverage is diagrams only" | **True** — 9/9 scenes `coverage_category: diagram` |
| "`dataviz` planned but not rendered as charts" | **True** — see 3.2, and the plan's objective is unmet |
| "Pictograms are geometric" | **True** — 12 vector pictograms, no illustration |
| "The CTA card is intentionally plain" | **True** |
| "Scene planning tuned on one plan" | **True** — 9 scenes on the only real script, plus synthetic tests |
| "Timeline is a chronology metaphor" | **True** — see 3.4 |
| "Audit lows L2–L9 not addressed" | **Partly stale**: L2 (unreachable `or` in `local.entries()`) is still present; L3 (`+0.45` punctuation bonus) still present; L4 = 3.5; L5 = 3.7; L6 = 3.9; L7 = 3.8; L8 = 3.6; L9 = 3.3 (and worse: the invented `data` entity) |

## 4. Technical debt inventory

| # | debt | location | cost of leaving it |
|---|---|---|---|
| D1 | one 863-line module holds canvas, 12 pictograms, 10 drawers, lexicon and composition selection | `assets/generated.py` | every new composition touches an 863-line file; merge conflicts and review fatigue |
| D2 | composition selection is a chain of `if has(" word ")` rules | `generated.py:171-196` | false positives (3.4), untestable combinatorics, no way to see why a choice was made |
| D3 | entity lexicon is 12 hard-coded nouns with hand-written synonyms | `generated.py:31-47` | channel two needs a different lexicon; today it would need a second copy |
| D4 | QC thresholds are read from a JSON file that can only *tune* code defaults | `qa/creative.py`, `content/creative_qc.json` | fine as designed, but there is no schema check on the file either |
| D5 | `scenes.json` schema is implicit (no version field beyond `"scene-plan/1"`) | `scene_plan.py:111` | v1.1 adding fields is safe, but nothing validates a consumer's expectations |
| D6 | renderer grew +461/−58 lines to host the plate | `media/english_renderer.py` | the Shorts renderer is now the largest file in the media path; a separate `visual_plate.py` would isolate the next changes |
| D7 | no integration test with a real library asset | `tests/factory/test_assets.py` | the highest-value path (real picture) is the least tested |

## 5. Risk assessment

| risk | likelihood | impact | mitigation |
|---|---|---|---|
| A v1.1 chart asserts a number the narration does not state | medium if unguarded | high — a false claim on screen | parse only explicit figures; render the source phrase beside the bar; QC fails a `dataviz` scene whose stated number is absent from the diagram |
| Enabling the engine on another channel regresses tone or layout | medium | high — published video | per-channel policy + goldens per channel + the existing 12-frame compatibility comparison, now three-way |
| Cache-path change breaks warm renders in CI | low | medium | env override with the old default honoured; a test asserts both |
| New compositions crash on thin entity sets | low (H3 fixed) | high — a render dies | the exhaustive "every composition × 0/1/2/3 entities" test already exists; extend it to every new drawer |
| Library assets with unclear licensing get committed | low | high — legal | intake tool refuses a licence outside the allow-list, and requires `source_url` + attribution text |
| Scope creep turns v1.1 into a rewrite | **medium–high** | medium | the roadmap below caps v1.1 at six P0 items, one P1 feature pair, and no renderer rewrite |

## 6. What v1.0 got right, and must not be lost

- **Measurement over assertion**: plate ink/colour, framing overflow, caption collisions, golden frames,
  cross-channel pixel equality. Every claim in the v1.0 report is reproducible.
- **Honesty in the data model**: `coverage_category` records what was *rendered*, which is why "diagrams
  only" is a fact rather than a marketing line.
- **Fail-closed gates**: missing creative verdict blocks a scene-planned video; unmeasured loudness
  blocks any video.
- **Backward compatibility by construction**: opt-in policy, legacy path untouched, 12/12 identical.

Any v1.1 change that weakens one of these four is not an improvement, regardless of how the plate looks.

---

## 7. Delivered (v1.1 implementation)

Everything in §3 was fixed in the implementation branch, each with the test that fails if it returns.
Measured results and evidence live in `VISUAL_ENGINE_V1_REPORT.md` §12; this table is the index.

| finding | status | fix | test |
|---|---|---|---|
| §3.2 `dataviz` classified then ignored | **fixed** | `figures.py` + `bars`/`ratio` drawers, `figure_is_stated` (error) and `dataviz_delivered` (warning) | `test_v11_figures.py`, `test_v11_diversity.py::TestDatavizDelivery` |
| §3.3 invented `data` subject | **fixed** | `"data"` fallback removed from `spec_for`, `_entity_row`, `_draw_statement` | `test_v11_composition.py::TestNoInventedSubject` |
| §3.4 composition from an unsupported keyword | **fixed** | sequence cue required for pipeline/timeline; `comparison_pair` required for comparison; part word required for components | `test_v11_composition.py::TestCueBasedComposition` |
| §3.5 `distinct_visuals` counts specs | **fixed** | plate fingerprints + Hamming clustering + `visual_diversity_pixels` | `test_v11_diversity.py` |
| §3.6 `visual_policy` unvalidated | **fixed** | `VisualPolicy`, `parse_visual_policy`, recorded warnings | `test_v11_policy.py` |
| §3.7 CWD-relative cache and thresholds | **fixed** | `factory/media/assets/paths.py`, `FACTORY_ASSET_CACHE`, `FACTORY_ASSET_LIBRARY` | `test_v11_paths.py` |
| §3.8 image handle leak | **fixed** | `with Image.open(...)` in `Resolution.image()`; observable by deleting a loaded file | `test_v11_provenance.py::TestHandles` |
| §3.9 sidecar values trusted | **fixed** | license allow-list, path confinement, recorded rejections, derived attribution line | `test_v11_provenance.py::TestLibrarySafety` |
| §3.10 provenance is a string | **fixed** | `entities`, `variant`, `license`, `attribution`, `plate_fingerprint`, `record` in `scenes.json` | `test_v11_provenance.py::TestResolutionProvenance` |
| §3.11 transitions declared but unread | **fixed (truthfully)** | `transition_in`/`out` now `cut`; no crossfade was implemented, so none is claimed | `test_scene_plan.py` (transitions) |
| §3.1 asset layer never exercised | **partly**: exercised by every render and test, but with **no library content** — P1-2 needs owner-supplied files | — | `test_v11_provenance.py`, `test_assets.py` |
| §3.12 one channel | **unchanged by design** | Nexus Node only; other two stay legacy (compatibility only) | 12/12 identical |
