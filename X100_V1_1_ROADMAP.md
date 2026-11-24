# X100 Visual Engine v1.1 — Roadmap

Base: merged v1.0 at `e5cff17`. Every "verify" line below is a command or test that exists, or a new
one this roadmap specifies. No number in this document is invented: the v1.0 column comes from
`X100_V1_1_AUDIT.md` §2, measured on this machine.

## 0. The smallest meaningful v1.1

**Ship these seven items together, nothing else:**

| # | item | class | user-visible effect |
|---|---|---|---|
| 1 | `figures.py` + `bars`/`ratio` drawers + `figure_is_stated` QC | P1 | the first plate that shows a **number the video actually states** |
| 2 | no invented subject for entity-less sentences (`data` fallback removed) | P0 | a plate can no longer name a noun the narration does not say |
| 3 | composition requires the cue it claims (sequence → pipeline/timeline) | P0 | no more chronology invented from the word "future" |
| 4 | `visual_policy` validated into a typed policy | P0 | a config typo can no longer silently change the visual language |
| 5 | cache + thresholds anchored to the repo, env-overridable | P0 | warm renders survive a different working directory |
| 6 | provenance structured: `entities`, `variant`, `license`, `attribution` in every scene; `with Image.open` | P0 | a reviewer can audit what was drawn, from what, under what licence |
| 7 | `distinct_visuals` measured on plate pixels | P0 | "nine scenes, three pictures" becomes detectable |

That is a coherent release: **honest content-bearing plates, auditable provenance, and a config layer
that fails loudly.** It changes no composition's existing output except where v1.0 was wrong, and it
needs no new dependency, no paid service and no network access (₹0/month preserved).

The **6.5 engineering days** in §6 is an **estimate, not a commitment**: it assumes one engineer familiar
with the v1.0 code, no interruptions, and no discoveries that change the design. Treat it as a sizing
aid, not a delivery date.

Explicitly **not** in the first release: the asset-library pilot (needs the owner's files), the Academic
Biohacker policy, and any crossfade work. Those are v1.1.1 / v1.2.

## 1. P0 — reliability and correctness

Each item lists: what changes, the test that proves it, and the acceptance criterion.

### P0-1 · Typed `visual_policy`

- **Change:** `factory/config.py` parses `visual_policy` into a `VisualPolicy` frozen dataclass
  (`scene_planning`, `categories`, `min_scene_ms`, `max_scene_ms`, `palette`, `chart_values`); unknown
  categories dropped with a recorded warning; a string where a list is expected becomes a 1-tuple;
  an invalid band falls back to defaults and records why. `ChannelSpec.visual_policy` keeps a
  `.as_dict()` view so existing callers keep working.
- **Tests:** `test_config_policy.py` — valid policy parses; `categories: "diagram"` becomes
  `("diagram",)` and **not** a character set; `min_scene_ms: "two thousand"` → default 2000 +
  warning; unknown category dropped; inverted band rejected; `as_dict()` round-trips.
- **Acceptance:** `_category_of` returns the same category for `categories: "diagram"` and
  `categories: ["diagram"]`; no config in the repo changes behaviour; legacy channels still have no
  policy object.

### P0-2 · Entity-less sentences stop inventing `data`

- **Change:** remove the `entities.append("data")` fallback in `spec_for`; when fewer than one entity
  is found, return a `statement` spec whose title is the scene's on-screen text and whose property row
  is empty, and record `fallback="statement_no_entity"` with the reason.
- **Tests:** the two reproduced sentences (`"That is the whole point."`, `"It just works."`) produce
  no entity, no invented label, and a renderable plate; `visible_text` contains no lexicon noun.
- **Acceptance:** zero plates in a real render show a lexicon word absent from the narration of the
  scene and its neighbours; `provenance_recorded` passes.

### P0-3 · A composition must have the cue it claims

- **Change:** `choose_variant` requires an explicit ordering cue (`first`, `then`, `next`, `after`,
  `before`, `finally`, `step`, ordinal) for `pipeline`/`timeline`; a comparative cue for `comparison`
  (already true); otherwise `panels` (≥2 entities) or `statement`.
- **Tests:** the s08 narration (`"…future of robot training…"`, no sequence word) yields `panels`;
  a sentence with "then" still yields `pipeline`; the audited comparisons still yield `comparison`;
  every composition × 0/1/2/3 entities still renders (existing exhaustive test extended).
- **Acceptance:** in the real render, every `pipeline`/`timeline` plate's narration contains an
  ordering cue — asserted as a test over the produced `scenes.json`.

### P0-4 · Paths anchored, not ambient

- **Change:** `assets/paths.py` with `asset_cache_root()`, `build_root()`, `thresholds_path()`;
  `FACTORY_ASSET_CACHE` overrides the cache; default `<repo>/x100_asset_cache`.
- **Tests:** running from a temporary CWD writes the cache under the repo root (not the CWD); with
  the env var set, it writes there and the resolver reports that path; `load_thresholds()` finds
  `content/creative_qc.json` from any CWD.
- **Acceptance:** two renders from different working directories share one cache directory;
  `x100_asset_cache/` never appears outside the repo or the configured root.

### P0-5 · Provenance and handles

- **Change:** `Resolution.to_dict()` emits `entities` and `variant`; `local.py` validates `license`
  against `ALLOWED_LICENSES`, confines `local_path` to the library root, and fills
  `attribution_text` when the licence requires it; `Resolution.image()` uses `with Image.open(...)`.
- **Tests:** a scene's `resolution` block in `scenes.json` has `entities` and `variant`; a sidecar with
  `license: "gpl"` is refused with a recorded reason; a sidecar with `source_url` outside the library
  is refused; a library-backed plate leaves no open handle (Windows: the file can be deleted
  immediately after `image()`).
- **Acceptance:** `provenance_recorded` and `attribution_present` pass on a real render;
  `os.remove()` of a library file succeeds right after plate resolution.

### P0-6 · `distinct_visuals` measured on pixels

- **Change:** compute a 16×16 greyscale fingerprint per rendered plate; cluster by Hamming distance
  ≤ 6; the check fails when distinct clusters < `ceil(min_distinct_ratio × scenes)`. Keep the spec-id
  count as a cheap secondary detail string.
- **Tests:** nine identical plates fail; nine genuinely different plates pass; the v1.0 render passes
  (it is genuinely diverse) — proving the change does not retroactively condemn good output.
- **Acceptance:** threshold `min_distinct_ratio = 0.5` in `content/creative_qc.json`; the real render
  reports ≥ 5 distinct plate clusters over 9 scenes.

## 2. P1 — visual quality

### P1-1 · Stated figures become charts (the headline feature)

- **Change:** `factory/content/figures.py`; `bars` and `ratio` drawers; `spec_for(figures=…)`;
  `figure_is_stated` (fail) and `dataviz_delivered` (warn) checks.
- **Tests (unit):** `extract` over a table of sentences — "40 percent" → value 40, unit `%`;
  "2x faster" → 2, `x`; "thousands of examples" → `vague`, value `None`; "1,200 robots" → 1200, count;
  "half the cost" → `vague`; "in 2026" → `None` (a year is not a magnitude).
  **Tests (drawer):** a numeric label is a substring of the narration; a vague figure produces no
  digits; mixed units produce `ratio`, not `bars`; two figures with the same unit share one scale and
  the values are printed as spoken (no rounding invented).
  **Tests (QC):** a plate showing "40 %" for a sentence without "40" fails `figure_is_stated`.
- **Acceptance:** on a script containing one stated percentage, at least one plate shows that
  percentage with the source phrase; zero plates show a number the narration does not state; the
  dataviz scene's `coverage_category` becomes `dataviz` and the gate still passes.
- **Effort:** ~2 days. **Risk:** medium — the failure mode (an invented number) is exactly what the
  tests above exist to prevent.

### P1-2 · Asset library pilot (needs owner-supplied files)

- **Change:** `tools/asset_intake.py`; documentation in `VISUAL_ENGINE_V1_REPORT.md`;
  3–5 owner files in `assets/library/nexus-node/` with sidecars.
- **Tests:** intake refuses an unknown licence, refuses a missing `source_url` for `cc-*`, writes a
  sidecar with hash + attribution, and `verify` detects a modified file; a render that finds a library
  match reports `asset_source: "local"`, `kind: "library"`, and a non-null `attribution_text` when
  the licence requires it; a render with no library files still passes (fallback path).
- **Acceptance:** one real plate in a real render comes from a library file with a verified hash and
  attribution; plate ink/colour stay within ±20 % of the v1.0 baseline (a photographed plate must not
  darken the card).
- **Effort:** ~1.5 days + owner's assets. **Risk:** low technically, medium editorially (tone).

### P1-3 · Academic Biohacker visual policy (`palette: "paper"`)

- **Change:** `channels/academic-biohacker.json` gets `visual_policy {scene_planning: true,
  palette: "paper"}`; `generated.py` reads the palette to draw on the channel's light background
  (`#F4F1EA`) with its `#D62839` / `#2A9D8F` accents. Natkhat Toons is **not** included.
- **Tests:** goldens for Academic; 12-frame compatibility comparison proves Natkhat is unchanged;
  dark-palette scenes are byte-identical to v1.0.
- **Acceptance:** an Academic render gates 25/25 with creative ≥ 14/16; contrast ratio of plate text ≥
  4.5:1 on the light card (measured); no Nexus Node golden changes.
- **Effort:** ~1.5 days. **Risk:** medium — contrast on a light card is the real hazard.

### P1-4 · Composition budget per episode

- **Change:** cap any single composition at `ceil(scenes / 3)` per episode (v1.0 rendered `pipeline`
  three times out of nine), enforced in the planner's selection pass with a recorded decision.
- **Tests:** a nine-scene plan with no budget violation is unchanged; a plan that would use four
  pipelines steps down the ladder and records why; the ladder never yields a composition lacking its
  cue (P0-3 interaction test).
- **Acceptance:** no composition exceeds the cap in the real render; `composition_variety` and
  `no_repeated_composition_runs` still pass.
- **Effort:** ~0.5 day. **Risk:** low.

### P1-5 · Truthful transitions (and, if cheap, a real crossfade)

- **Change:** either implement a 200 ms crossfade between scenes in the encode loop, or emit
  `transition_* = "cut"` everywhere and document that v1.1 has no transitions. Decide before writing
  code (see `X100_V1_1_DECISIONS.md` §D3).
- **Tests:** `scenes.json` transition values match what the encoder does (asserted against the frame
  plan); if crossfade ships, a frame sampled at the boundary differs from both neighbours and the
  render time increase stays under 5 %.
- **Acceptance:** no metadata claims a transition the video does not perform.
- **Effort:** 0.5 day (truthfulness) or 2 days (crossfade). **Risk:** low / medium.

## 3. P2 — advanced capabilities (explicitly deferred)

Nothing in this section is proposed for v1.1. Each row is a capability this engine should eventually have,
recorded here so a reviewer can see what was considered and consciously left out rather than unconsidered.

| item | why later | rough size |
|---|---|---|
| Natkhat Toons visual language | needs character staging (chiku/gappu), not diagrams; a different renderer path entirely | 1–2 weeks, separate milestone |
| Video footage plates | licensing + trim + bitrate budget; a 3 s clip can outweigh the whole card | ~1 week |
| Layered motion graphics (staged reveal, arrows drawing themselves) | frame-level animation inside the plate; needs a frame-budget check first | ~1 week |
| Chart types beyond bars/ratio (line, scatter) | needs multiple stated data points; today's scripts rarely state two comparable numbers | later, demand-driven |
| `generated.py` package split | mechanical; do it when the file passes ~1,000 lines | 0.5 day |
| Provider-backed stock imagery | violates ₹0/offline; owner decision, never an engineering default | n/a |

## 4. Dependencies

```
P0-1 policy ──────────────► P1-3 academic paper palette (needs `palette` in the policy)
P0-5 provenance ──────────► P1-2 library pilot (attribution must exist before a real file ships)
P0-3 cue rules ───────────► P1-4 budget (the ladder must be cue-safe first)
P1-1 figures ─────────────► P1-2 (a photographed plate and a chart can coexist; figures first)
P0-6 pixel diversity ─────► P1-4 (budget without diversity measurement is a guess)
```

## 5. Test strategy (the standing bar)

Every release keeps this suite green; nothing here is optional.

| layer | requirement |
|---|---|
| unit | every new module ≥ 90 % line coverage of its own public functions; table-driven for `figures.extract` |
| integration | render → `scenes.json` → `creative.json` → manifest → `verify()` → gate, on a real encoded package (the v1.0 `test_package_integration.py` pattern) |
| regression | `pytest tests -q` must stay ≥ the v1.0 count (1,015) plus new tests; no test deleted or weakened |
| golden frames | `tools.capture_goldens --check` → 0 changed for existing frames; new frames added explicitly |
| channel compatibility | 12 frames × 3 channels, `main@e5cff17` vs branch → identical for channels without a policy |
| creative QC | 16 v1.0 checks + 5 new; the real render passes all |
| publish gate | 25/25 on the scene-planned render; 24/24 unchanged for legacy channels |
| render budget | wall time ≤ **200 s** for a 38 s episode on this machine (v1.0: 160–180 s), i.e. ≤ +12 % |
| memory | Python allocation peak per plate ≤ **2 MB** (v1.0: 1.1 MB); no growth in held plate count |
| cache | warm resolve ≤ 700 ms for 9 plates (v1.0: 620 ms); no cache directory outside the anchored root |
| secrets | `python -m tools.secret_scan` tree + history: 0 findings; gitleaks unchanged in CI |

## 6. Estimated complexity and order

| order | item | effort | cumulative |
|---|---|---|---|
| 1 | P0-2 entity fallback | 0.5 d | 0.5 d |
| 2 | P0-3 cue rules | 1 d | 1.5 d |
| 3 | P0-1 policy typing | 1 d | 2.5 d |
| 4 | P0-4 path anchoring | 0.5 d | 3 d |
| 5 | P0-5 provenance + handle | 0.5 d | 3.5 d |
| 6 | P0-6 pixel diversity | 1 d | 4.5 d |
| 7 | P1-1 figures + charts + QC | 2 d | **6.5 d — v1.1 release** |
| 8 | P1-4 composition budget | 0.5 d | 7 d |
| 9 | P1-5 truthful transitions | 0.5 d | 7.5 d |
| 10 | P1-2 library pilot (+ owner assets) | 1.5 d | 9 d |
| 11 | P1-3 academic paper palette | 1.5 d | 10.5 d |

Items 1–7 are the release. Items 8–11 can follow as v1.1.x without re-opening the release.

## 7. Definition of done for v1.1

1. `pytest tests -q` green, count ≥ 1,015 + new tests, and the six engine files still pass alone.
2. `capture_goldens --check` → 0 changed; new goldens only for new compositions.
3. 12/12 × 3-channel compatibility against `e5cff17`.
4. A fresh render: gate 25/25, creative 16/16 + 5 new checks, manifest `verify()` clean without a
   rebuild, plate ink/colour within ±20 % of the v1.0 baseline (3.10 / 8,447).
5. Render wall time ≤ 200 s; warm resolve ≤ 700 ms; per-plate Python peak ≤ 2 MB.
6. At least one plate shows a number the narration states; zero plates show a number it does not.
7. `scenes.json` carries `entities`, `variant`, `license`, and `attribution` for every scene.
8. Secret scan and gitleaks clean; no new dependency; no network call added.
9. Docs updated: `VISUAL_ENGINE_V1_REPORT.md` (v1.1 section, appended, v1.0 history intact),
   `X100_V1_1_*.md` marked as delivered with measured results.
10. PR against `main`, CI green on all required checks, merged only by the owner.
