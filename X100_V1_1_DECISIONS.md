# X100 Visual Engine v1.1 — Decisions

Architectural decisions for v1.1, in the same style as `X100_AUTONOMOUS_DECISIONS.md`. Each entry
records the decision, why it was taken, the alternative that was rejected, and what it costs.

The v1.0 decision log (D1–D18) is unaffected and remains the record of the merged engine.

Standing constraint for every decision below: **₹0/month, offline-capable, no new runtime dependency, no
paid service** — anything that cannot meet that is rejected regardless of how good the plate looks.

Roadmap class of each decision, so the four documents cross-reference cleanly:

| decision | roadmap |
|---|---|
| D1 layering, D11 doc separation | constrains all items |
| D2 stated-figure charts | **P1-1** |
| D3 truthful metadata | **P1-5** |
| D4 typed policy | **P0-1** |
| D5 anchored paths | **P0-4** |
| D6 pixel diversity | **P0-6** |
| D7 library intake | **P1-2** |
| D8 Academic paper palette, Natkhat deferred | **P1-3** (P2 for Natkhat) |
| D9 budgets, D10 guarantees | constrains all items |

---

## D1. v1.1 is a layer of three narrow components, not a v2

**Decision.** v1.1 adds `factory/content/figures.py`, two chart drawers, and a set of honesty/plumbing
fixes. It does not restructure `scene_plan.py`, the renderer, or the composition selector, and it
introduces no dependency.

**Why.** The merged engine already has the right seams — `ScenePlan` carries `search_query`,
`asset_source`, `license`, `attribution_text`, `fallback`, `transition_in/out`; `_DRAWERS` is a
dispatch table; the resolver has three ordered sources. Every v1.1 requirement can be met by filling
those slots. A rewrite would put the 12/12 cross-channel compatibility guarantee and the 78 golden
frames at risk to buy tidiness nobody can see in a video.

**Rejected.** (a) A `visual_engine/` package with plugin registries — rejected as abstraction with no
second caller. (b) Splitting `generated.py` now — rejected as churn that would dominate the diff in a
release whose value is elsewhere; the split is scheduled for when the file passes ~1,000 lines or a
second channel needs its own pictograms.

**Cost.** `generated.py` stays large through v1.1. Accepted deliberately.

---

## D2. A chart may only draw a number the narration states, or a stated proportion of nothing

**Decision.** `figures.extract()` returns only figures present in the sentence, keeping the exact
phrase and character offsets. `kind="vague"` ("thousands", "half", "double") carries **no numeric
value**. A `dataviz` scene with no extractable figure is not drawn as a chart, and the reason is
recorded.

**Why.** This is the same failure mode as H4 (a plate labelled STUDY) and the comparison-footer defect
("two routes to the same result"), one level up: a chart is the most authoritative-looking thing on
screen, so an invented bar ratio is the most damaging lie the engine could tell. A bar chart of
"thousands of examples" against nothing would be exactly that.

**Rejected.** (a) Estimate proportions from adjectives ("many", "most") — rejected: unmeasurable
invention. (b) Draw a bar for every count noun — rejected for the same reason with extra steps.

**Cost.** Fewer charts than a chart-happy engine would produce. A video with no stated figure gets no
chart, which is correct: the narration did not quantify anything.

**Enforcement.** `figure_is_stated` (fail) in creative QC, plus unit tests that regex the rendered
spec's digits against the sentence.

---

## D3. Metadata must describe the video that was rendered

**Decision.** For v1.1, either the renderer honours `transition_in/out` and a 200 ms crossfade is
implemented, **or** the planner stops emitting `crossfade`. The two must agree before the release ships.
Same rule for `fallback` and `motion`: a field that no renderer reads is removed rather than left
misleading.

**Why.** v1.0's `scenes.json` says `transition_out: "crossfade"` on eight of nine scenes and the renderer
never reads the field — every scene is a hard cut. That is a small version of the defect the whole engine
exists to avoid: a claim in the data that the pixels do not support. It also quietly misleads any future
consumer of `scenes.json`.

**Rejected.** Leaving it as "documentation debt" — rejected because `scenes.json` is the audit artefact;
its fields are read by QC, by reviewers, and by whoever extends this next. A field that lies is worse
than a missing field.

**Cost.** Either 0.5 day (make it truthful) or ~2 days (implement the crossfade). The decision can be
taken at implementation time; the invariant cannot.

---

## D4. Policy is parsed into a type, and a bad policy is a recorded warning, never a silent change

**Decision.** `visual_policy` parses into a frozen `VisualPolicy`. Unknown categories are dropped with a
warning; a string where a list belongs becomes a 1-tuple; an invalid duration band falls back to the
code defaults with a recorded reason. `ChannelSpec.visual_policy` keeps an `.as_dict()` view.

**Why.** Reproduced on the merged code: `{"categories": "diagram"}` is accepted verbatim, `set()` turns it
into characters, and the planner then returns `kinetic_type` for a robotics sentence. A config typo
changed the entire visual language of a channel with no error anywhere. In a system whose whole premise
is "measure, do not assume", silently accepting an unparseable policy is indefensible.

**Rejected.** Hard failure on a bad policy — rejected because a typo in one channel must not stop the
other two from rendering; a warning plus a safe default is the fail-closed-but-productive choice, and
the warning is asserted by a test.

**Cost.** ~1 day and one new dataclass. The `.as_dict()` view keeps every existing caller unchanged.

---

## D5. Paths are anchored, and the environment can override them

**Decision.** `assets/paths.py` resolves the asset cache, build root and thresholds path from the repo
root; `FACTORY_ASSET_CACHE` overrides the cache location. The CWD-relative default is gone.

**Why.** `CACHE_ROOT = Path("x100_asset_cache")` means the cache is wherever the process happens to be
standing. In this very session that produced cache directories in the repository root, and a render from
another directory would silently rebuild every plate. A cache that depends on the caller's `cd` is not a
cache.

**Rejected.** Always using an absolute path with no override — rejected because tests and CI legitimately
want a throwaway cache directory, and `FACTORY_ASSET_CACHE` gives that without touching the default.

**Cost.** 0.5 day, one module, two call sites, one test pinning both branches.

---

## D6. `distinct_visuals` measures pixels, not identifiers

**Decision.** The check keeps its name and gains a pixel fingerprint: a 16×16 greyscale hash per plate,
clustered at Hamming distance ≤ 6, with a configurable minimum ratio. The spec-id count survives only as
detail text.

**Why.** v1.0 measured `len(set(asset_ids))` — and for generated plates the identifier *is* the spec
digest. The check that exists to catch "nine scenes, three pictures" could be satisfied by nine spec
strings, some of which may draw near-identical plates. v1.0 passes the pixel test honestly; better to
keep the check honest *before* a release that adds compositions, so it can be trusted during v1.1.

**Rejected.** (a) Full perceptual hashing with a library — rejected, no dependency. (b) Leaving it —
rejected: a release that claims "more diversity" needs a measurement that can fail.

**Cost.** ~1 day (fingerprint + clustering + a calibration test that the v1.0 render passes).

---

## D7. The library path ships with an intake tool, or it does not ship

**Decision.** No owner file enters `assets/library/` without `tools/asset_intake.py` recording hash,
licence (checked against the allow-list), source URL, creator and attribution text. The resolver's
preference order is unchanged.

**Why.** The "prefer a real picture" path has never run against a real file (audit §3.1). The first
person to drop a JPEG in will otherwise be the first tester — and with a public repository, provenance
is not optional. The allow-list already exists (`metadata.ALLOWED_LICENSES`,
`REQUIRES_ATTRIBUTION`); nothing uses it on the intake side today.

**Rejected.** Documenting a manual sidecar format — rejected: it invites files with `license: "mine"` and
no source, which is exactly the state a public repo cannot be in.

**Cost.** ~1.5 days plus the owner's assets. The renderer needs no change.

---

## D8. Academic Biohacker gets a light "paper" palette; Natkhat Toons gets nothing in v1.1

**Decision.** `palette: "paper"` is a policy value that changes the generated layer's colours for a
channel. Natkhat Toons is excluded from v1.1 entirely.

**Why.** Academic Biohacker's card is light (`#F4F1EA`) and its subject is health/education; the same
schematic in its own palette is a plausible, low-risk win, measurable by contrast ratio and goldens.
Natkhat Toons is a Hindi children's cartoon with two characters — it needs staged scenes, not
diagrams, and enabling the engine there would be a tonal regression, not an improvement.

**Rejected.** Enabling `scene_planning: true` for all three channels as a "quick win" — rejected: it
would put schematics on a children's cartoon and call it progress.

**Cost.** ~1.5 days; the Natkhat decision is deferred, not solved.

---

## D9. Every v1.1 claim is gated by a number recorded before the release

**Decision.** The roadmap fixes the budgets before implementation: render ≤ 200 s for a 38 s episode
(v1.0: 160–180 s), warm resolve ≤ 700 ms (v1.0: 620 ms), plate Python peak ≤ 2 MB (v1.0: 1.1 MB), plate
ink/colour within ±20 % of 3.10 / 8,447, and the full suite ≥ 1,015 tests.

**Why.** v1.0's credibility came from measuring everything and publishing the numbers, including the
unflattering ones. A v1.1 that says "better visuals" without a budget invites a slow, darker, more
expensive engine that nobody notices until the queue backs up. Fixing the thresholds first means a
regression fails a test instead of being discovered by an audience.

**Rejected.** Measuring after implementation and writing the thresholds to match — rejected: that is how
budgets become fiction.

**Cost.** Some v1.1 ideas will not fit the budget and will be cut. That is the point.

---

## D10. Nothing in v1.1 may weaken the four v1.0 guarantees

**Decision.** The release is rejected if it changes any of: (1) measurement over assertion, (2) honest
`coverage_category`, (3) fail-closed gates, (4) backward compatibility by construction (opt-in policy,
legacy path untouched, 12/12 pixel equality for channels without a policy).

**Why.** These four are why v1.0 could be merged with confidence. A chart drawer that reports `diagram`
because the chart failed, a gate that passes a scene-planned video without a creative verdict, or a
"small" change to the legacy card path would each trade the engine's credibility for a nicer screenshot.

**Rejected.** "Temporarily relax the compatibility check while the new compositions settle" — rejected
outright: that is the check's whole purpose.

**Cost.** Slower feature work. Accepted.

---

## D11. Documentation does not travel with the code it describes

**Decision.** This blueprint ships as a documentation-only pull request, separate from any implementation.
The audit, architecture, roadmap and decisions are reviewed and merged on their own merits; the code they
describe arrives later, in its own PRs, with its own measurements.

**Why.** A blueprint merged inside an implementation PR is reviewed as a justification rather than as a
plan, and its estimates get read as claims. Keeping them apart means the review of "is this the right
work?" happens before any code exists to defend, and the review of "is this correct?" happens with the
numbers in hand.

**Rejected.** Bundling the docs with the first implementation commit — rejected: it would also make a
later change to the plan look like a change to the code.

**Cost.** Two reviews instead of one, and the blueprint must stay honest as implementation reveals what
the estimate got wrong. That is the intended outcome, not a cost.

---

## Delivered status

Each decision below was implemented as written. Two were sharpened by the first rendered video, and are
recorded here rather than being silently folded into the code.

| decision | status | note |
|---|---|---|
| **D1** layer of three narrow components | delivered | `figures.py`, the two drawers, and the honesty/plumbing fixes; nothing else |
| **D2** a chart may only draw a stated number | delivered | `extract()` never invents a value; a vague quantifier draws a `panels`/`statement` plate with a recorded reason; `figure_is_stated` fails a package that shows an unstated digit |
| **D3** metadata must describe the rendered video | delivered | `transition_in`/`out` are `cut`; no crossfade is claimed |
| **D4** typed policy, warnings never silent | delivered | `VisualPolicy` + `parse_visual_policy`; a non-object, a string category, an unknown category, a bad band and an unknown palette each produce a recorded warning and a safe default |
| **D5** paths anchored, env-overridable | delivered | `paths.py`; the environment wins, the repository is the fallback, the working directory is never consulted |
| **D6** diversity measured on pixels | delivered | 16×16 fingerprint per plate, Hamming ≤ 6 clusters, ratio ≥ 0.5 |
| **D7** library path ships with an intake tool or not at all | **partly**: the library path shipped, the intake tool did not | the library is implemented, confined and tested, but with no licensed files the intake CLI has nothing to take in; P1-2 remains deferred, so this decision is *open*, not satisfied |
| **D8** Academic paper palette, Natkhat excluded | honoured by not doing it | both channels untouched, 12/12 identical |
| **D9** every claim gated by a number | delivered | the numbers are in `VISUAL_ENGINE_V1_REPORT.md` §12.2, measured before this branch was committed |
| **D10** nothing weakens the four v1.0 guarantees | delivered | opt-in policy, pixel-identical legacy path, fail-closed gate (a missing creative verdict still blocks), measured-only claims |
| **D11** documentation does not travel with the code | followed | the blueprint was merged as PR #14 before any implementation commit existed |

### D12 (new). A comparison draws the pair the sentence contrasts, or it draws nothing

**Decision.** `comparison` requires a `_COMPARATOR` (`versus`, `than`, `compared to`, `less like`,
`more like`, `instead of`) with at least one entity on each side, and the plate draws exactly that pair.
A side that names only a property (`cost`, `time`) is represented by its concrete subject.

**Why.** The first v1.1 render put **TIME vs ROBOT** on the card for *"the future of robot training
looks less like programming and more like a very large video library"*: four nouns matched, and the
first two were drawn. That is the v1.0 co-mention defect wearing a new mask, and the audit had already
named it (§3.4). After the fix the same sentence draws **ROBOT vs VIDEO**, which is the contrast it
makes.

**Rejected.** Keeping first-two-entities and only requiring comparative language (that is what D17 in
`X100_AUTONOMOUS_DECISIONS.md` already forbade).

**Cost.** Some real comparisons will now fall back to `panels` because the sentence puts both sides on
one side of the cue. That is the correct direction of error: a plate may say less than the sentence, it
may not say something else.

### D13 (new). A chart label comes from the narration's own words for the figure

**Decision.** `figure_labels()` takes up to three words immediately before each figure, minus
stopwords, and the bar/ratio drawers print those instead of the figure's own phrase; the value is
printed separately. When no label can be derived, the phrase is used as before.

**Why.** The specimen render showed "80 PERCENT … 80%": the number repeated as both the subject and the
value, which tells a viewer nothing about *what* is 80 %. The narration already names it.

**Cost.** Labels can be terse ("VIDEO PRETRAINING"), and a sentence that states a figure before naming
its subject produces no label; the phrase fallback still applies. Both are visible on the card, which is
the point.
