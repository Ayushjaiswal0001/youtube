# X100 Visual Engine v1.1 — Architecture

Scope: an incremental layer on the merged v1.0 engine (`e5cff17`). No rewrite, no new runtime
dependency, no paid service, no network requirement at render time.

Constraints carried forward:

- **₹0/month.** stdlib + `numpy`, `pillow`, `pycairo`, `ffmpeg` (already required). Nothing else.
- **Offline-capable.** A render must succeed with no network and no library assets.
- **Backward compatible.** Channels without `visual_policy` keep the legacy path; Nexus Node keeps its
  v1.0 output except where a specific fix changes it on purpose.
- **Fail closed.** Missing measurement or missing verdict blocks the gate; it never silently passes.
- **Every claim measurable.** A new composition must be measurable in pixels and in `scenes.json`.

## 1. Where v1.0 ends and v1.1 begins

```
v1.0 (merged)                                    v1.1 (this design)
────────────────────────────────────────────────────────────────────────────────
narration ──► scene_plan ──► resolver ──► generated.draw ──► plate ──► encode
                 │              │              │
                 │              │              └─ 10 compositions, 12 pictograms
                 │              └─ library → provider(disabled) → generated
                 └─ objective say "show the magnitude" (never delivered)

v1.1 adds three narrow layers, each independently testable:

  (a) FIGURES   scene_plan extracts stated figures ──► generated.draw_bars / draw_ratio
  (b) INTAKE    assets/library + tools/asset_intake.py ──► provenance record ──► resolver (existing)
  (c) HONESTY   provenance fields, policy validation, cache anchoring, plate-fingerprint QC
```

## 2. Components

Every component below is **proposed and unimplemented**: nothing in this document exists on `main` until
the corresponding roadmap item ships its own PR. The priority column uses the roadmap's classes so the
four documents can be read side by side.

| component | section | roadmap class |
|---|---|---|
| `figure.py` / `figures.py` + `bars`/`ratio` drawers + `figure_is_stated` | 2.1, 2.2 | **P1-1** |
| `tools/asset_intake.py` + library pilot | 2.3 | **P1-2** |
| structured provenance (`entities`, `variant`, `license`, `attribution`) | 2.4 | **P0-5** |
| `VisualPolicy` parsing | 2.5 | **P0-1** |
| new QC checks (`figure_is_stated`, `dataviz_delivered`, `visual_diversity_pixels`, `provenance_recorded`, `attribution_present`) | 2.6 | P0-5, P0-6, P1-1 |
| `assets/paths.py` anchoring | 2.7 | **P0-4** |
| truthful transitions (implement crossfade or stop emitting it) | 2.4 | **P1-5** |
| `palette: "paper"` for Academic Biohacker | §5 | **P1-3** |

### 2.1 `factory/content/figures.py` (new, ~120 lines)

Purpose: find figures a sentence *states*, and only those.

```python
@dataclass(frozen=True)
class Figure:
    value: float | None      # numeric magnitude when the sentence states one (40, 2, 0.5)
    unit: str                # "%", "x", "ms", "" — only when stated
    phrase: str              # the exact words, e.g. "40 percent" or "thousands of"
    kind: str                # "percent" | "multiplier" | "count" | "ordinal" | "vague"
    start: int               # character offsets, so the plate can quote the phrase
    end: int

def extract(text: str) -> list[Figure]: ...
```

Rules, all testable:

1. A figure exists only if a numeral ("40", "2", "1,200") or an explicit vague quantifier
   ("thousands", "millions", "half", "double") appears with a unit or a noun it counts.
2. `kind="vague"` (thousands, half, double) carries **no numeric value** — it may be drawn as "many"
   or as two-thirds of a bar, never as "40 %".
3. No figure → no chart. `dataviz` then degrades to `statement`/`panels` and records why.

This module is pure text analysis. It never invents, rounds or converts between units.

### 2.2 Chart compositions in `assets/generated.py` (two new drawers)

- `bars` — one to three horizontal bars, each labelled with the **phrase as spoken** and, when the
  figure has a numeric value and a shared unit, a value label. Bars for different units are not drawn
  to a shared scale; each is drawn as a proportion pill instead (`ratio`).
- `ratio` — a single stated proportion (40 % → 40 % of an outlined track), labelled with the phrase.

Both are registered in `_DRAWERS`, `NEEDS_TWO`-free (they work with one entity), and added to the
diversity ladder. `spec_for()` grows an optional `figures: tuple[Figure, ...]` argument; when empty,
behaviour is exactly v1.0 (no change for any existing scene).

Honesty invariants, enforced by tests rather than review:

| invariant | test |
|---|---|
| a bar's label is a substring of the narration | `figure.phrase in narration` for every drawn figure |
| no drawn number is absent from the narration | regex the rendered spec's numbers against the sentence |
| different units never share a scale | two figures with `%` and `x` → `ratio` drawer, not `bars` |
| a `vague` figure has no numeric label | `value is None` → no digits in the visible text |
| no figure → no chart | `spec_for` with an empty figure tuple never returns a chart variant |

### 2.3 `tools/asset_intake.py` (new, ~180 lines)

The missing half of the library path. CLI:

```
python -m tools.asset_intake add --channel nexus-node --file path/to/picture.jpg \
    --license cc-by --source-url https://… --creator "Name" --keywords "robot arm, warehouse" \
    --scene-ids nexus-node
python -m tools.asset_intake verify --channel all          # re-hash, re-check licence, report drift
python -m tools.asset_intake list --channel nexus-node
```

What it does: validate the file (`validators.validate_image`, min short edge, aspect drift warning),
compute SHA-256, refuse a licence outside `metadata.ALLOWED_LICENSES`, require `source_url` for
`cc-*`/`public-domain`, derive `attribution_line()` when the licence requires attribution, write the
sidecar next to the file, and copy the file into `assets/library/<channel>/`.

What it must not do: download anything, accept a licence string it does not know, or overwrite an
existing file with a different hash without `--force`.

### 2.4 Provenance and fallback, structured

`Resolution.to_dict()` gains `entities: list[str]` and `variant: str`; `scenes.json` therefore records
what was drawn and from what. `ScenePlan.fallback` and `transition_in/out` become truthful: either the
renderer consumes them (v1.1: honour `cut` and implement a 200 ms `crossfade` **or** stop emitting
`crossfade`) — decided explicitly in `X100_V1_1_DECISIONS.md` §D3.

### 2.5 Policy validation in `factory/config.py`

```python
@dataclass(frozen=True)
class VisualPolicy:
    scene_planning: bool = False
    categories: tuple[str, ...] = ()
    min_scene_ms: int = 2000
    max_scene_ms: int = 8000
    palette: str = "default"     # "default" | "paper" — channel-level visual language
    chart_values: bool = True    # allow numeric labels on dataviz plates
```

`load_channel_specs` parses into this type: unknown categories are dropped with a warning, a string
where a list is expected becomes a one-item tuple, a non-positive or inverted band falls back to the
defaults and records why. `ChannelSpec.visual_policy` keeps its dict view for backward compatibility
(`.as_dict()`), so no existing caller changes behaviour.

### 2.6 QC additions (`factory/qa/creative.py`)

| check | severity | rule |
|---|---|---|
| `figure_is_stated` | fail | a `dataviz` scene whose plate shows a number must show a number the narration states |
| `dataviz_delivered` | warn | a `dataviz` scene rendered as a non-chart composition |
| `visual_diversity_pixels` | fail | perceptual fingerprint of each plate (16×16 grey, hash-clustered) must give ≥ ceil(0.5 × scenes) distinct pictures |
| `provenance_recorded` | fail | every scene has `asset_id`, `asset_source`, `license`, and `entities` |
| `attribution_present` | fail | a scene whose licence requires attribution carries `attribution_text` |

Thresholds continue to live in `content/creative_qc.json` and can only tune, never disable.

### 2.7 Cache and path anchoring

`assets/paths.py` (new, ~30 lines): one place that answers "where is the asset cache, the build root,
the thresholds file?" — `FACTORY_ASSET_CACHE` env override, else `<repo>/x100_asset_cache`, resolved
absolutely. `resolver.CACHE_ROOT` and `creative.load_thresholds` both use it. The old CWD-relative
behaviour is not preserved unless the env var says so; that is a deliberate fix, and a test pins both
branches.

## 3. Data flow after v1.1

```
script lines ──► scene_plan
                   │  per scene: narration_text, main_concept, objective, category,
                   │             figures = figures.extract(narration_text)      ← new
                   ▼
                scenes.json (v1.1 adds: figures, entities, variant, license, attribution)
                   ▼
             AssetResolver.resolve(scene)
                   │  1. library  (assets/library/<channel>/, validated + attributed)
                   │  2. provider (still disabled, still recorded)
                   │  3. generated (composition from entities + figures)
                   ▼
             Resolution(spec | path, category, motion, entities, variant, record)
                   ▼
         english_renderer: plate + push-in + caption + framing measurement
                   ▼
         creative.json (17+ checks) ──► publish_gate ──► manifest
```

Every arrow is already present in v1.0 except `figures` and the two chart drawers; the data model
already has slots for the rest (`license`, `attribution_text`, `fallback`, `transition_*`,
`search_query`).

## 4. Integration points and blast radius

| file | change | risk |
|---|---|---|
| `factory/content/figures.py` | new module, no imports from the renderer | none |
| `factory/content/scene_plan.py` | +`figures` on the scene record, +`palette` from policy | low; additive field |
| `factory/media/assets/generated.py` | +2 drawers, `spec_for(figures=())`, split `ICONS`/`drawers` into `pictograms.py` + `compositions.py` **only if** the file exceeds ~1,000 lines during implementation | medium; the split is optional and mechanical |
| `factory/media/assets/resolver.py` | +`entities`/`variant` in the record, absolute cache root, `with Image.open` | low |
| `factory/media/assets/local.py` | +licence allow-list, +path confinement, +attribution | low |
| `factory/config.py` | +`VisualPolicy` parsing | low; `.as_dict()` preserves callers |
| `factory/qa/creative.py` | +5 checks, 1 metric swap (`distinct_visuals` keeps its name) | medium; the gate's creative check reads `failures`, so new fails must be deliberate |
| `factory/media/english_renderer.py` | honour `crossfade` **or** stop emitting it; chart plates need no renderer change (they are just plates) | low |
| `content/creative_qc.json` | +`min_distinct_pixel_ratio` | trivial |
| `channels/academic-biohacker.json` | +`visual_policy` with `palette: "paper"` (Phase 2 of v1.1) | medium; first second-channel rollout |

Not touched: `uploader/`, `.github/`, publish gates' upload logic, schedules, secrets, the Hindi
renderer, `studio/`.

## 5. Compatibility strategy

1. **Legacy path untouched.** No `visual_policy` → no dispatcher → byte-identical cards. The existing
   12-frame × 3-channel comparison stays the regression gate, extended to a three-way check
   (`v1.0`, `v1.1`, and `main` before the engine).
2. **Golden frames never regenerated to match new output.** A changed golden is a deliberate,
   reviewed act with a written reason, exactly as in v1.0. New compositions add frames; they do not
   overwrite old ones.
3. **Schema additive only.** `scenes.json` gains fields; no field is renamed or removed. Consumers
   (`creative.py`, gate, docs) read with `.get()`.
4. **Policy is opt-in per channel**, and `palette: "paper"` is a *rendering* choice inside the
   generated layer, not a new renderer.
5. **Deterministic output.** Charts derive from the scene's own text; the same script must produce the
   same plate bytes. A test renders the same spec twice and compares hashes.

## 6. What is deliberately *not* in v1.1

| deferred | why | where it goes |
|---|---|---|
| Video footage clips | needs a licensing/attribution story, an ffmpeg trim path and a freeze/bitrate budget; a 3 s clip can cost more bitrate than the whole card | v1.3 |
| Natkhat Toons cartoon scenes | the engine's visual language (dark technical schematics) is wrong for Hindi children's animation; it needs character staging, not diagrams | v1.2+ (separate renderer, `studio/`) |
| A real content-addressed *plan* cache | v1.0's cache already covers the expensive part (plate drawing) | later, only if measurement demands it |
| Provider-backed stock imagery | violates ₹0 and offline determinism | owner decision, not an engineering one |
| Splitting `generated.py` into a package | mechanical, but touching 863 lines for tidiness is the kind of churn that hides real diffs | when it crosses ~1,000 lines *or* when a second channel needs its own pictograms |
| Crossfade transitions | touches the encode loop and the frame budget | v1.2, unless the metadata truthfulness fix lands first (see D3) |

---

## 7. As built — where the implementation differs from this design

The design in §2 was followed, with four deltas worth recording.

| § | design | as built | why |
|---|---|---|---|
| — | (not in the blueprint) | **new `factory/media/assets/paths.py`** | §2.7 required anchored paths but placed the helpers inside existing modules; a tiny dedicated module keeps the resolver, the library and creative QC reading the same source of truth, and gives tests one place to redirect |
| 2.2 | two new drawers in `assets/generated.py` | **`bars` + `ratio`**, plus `figure_labels()` and `comparison_pair()` | a bar labelled with its own number is unreadable, so labels come from the narration; and a comparison must draw the pair the sentence contrasts, not the first two nouns |
| 2.3 | `tools/asset_intake.py` (~180 lines) | **not built** | P1-2 is deferred: the intake tool only earns its place when there are licensed files to take in. The library path is implemented and tested, so the tool is a thin CLI over it when the owner supplies assets |
| 2.5 | policy parsed into a type | **as designed**, plus `VISUAL_CATEGORIES`, `VISUAL_PALETTES`, `DEFAULT_VISUAL_MIN_MS/MAX_MS` as the single vocabulary | an unknown category must be a recorded warning, which needs a known set to compare against |

Two additions beyond the blueprint, both driven by inspection of the rendered video rather than by the
plan: the `dataviz` note names the actual cause when a figure is vague, and a `comparison` scene's
`entities` are narrowed to the contrasted pair. Both are recorded in `VISUAL_ENGINE_V1_REPORT.md` §12.1.

Test counts as built: **1,169 collected and passing** (1,015 at `ea9d30a`), goldens **78 / 0 changed**,
three-channel compat **12/12 identical**.
