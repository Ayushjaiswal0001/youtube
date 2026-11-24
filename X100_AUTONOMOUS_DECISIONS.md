# X100 Visual Engine — implementation decisions

Each entry states the decision, the reason, and what it costs. These are the choices that a reviewer
would otherwise have to reverse-engineer from the diff.

## D1. Scene planning is opt-in per channel (`visual_policy`)

**Decision.** A channel renders with the scene planner only when its JSON sets
`factory.visual_policy.scene_planning = true`. Only `nexus-node` does.

**Why.** The directive makes Nexus Node the full integration and the other two compatibility only.
An opt-in flag makes "compatibility" a property of configuration rather than a promise in a report,
and it means a channel that has not been validated cannot accidentally ship the new card.

**Cost.** Two card renderers exist in `english_renderer.py`. The shared chrome/headline/caption code
was extracted into helpers so they cannot diverge; a 12-frame byte comparison proves they agree.

## D2. The plate is sized by the safe width divided by the maximum push-in

**Decision.** Plate `(84, 716)–(996, 1330)`, i.e. 912 px wide, not the full 968 px between margins.

**Why.** The camera pushes in by up to 6 %, which moves an edge pixel `(x − 540) × 1.06 + 540`. A
plate laid out to the safe width therefore drifts *outside* it — the same defect that once measured
29 frames of caption overflow. The layout target has to be the safe area pre-divided by the push-in.

**Cost.** 56 px narrower than it could be at scale 1.0. Measured overflow on the final render: 0 px.

## D3. A still plate is pushed in rather than animated

**Decision.** No per-frame animation inside the diagram. The plate grows 5.5 % across its scene and
drifts 14 px laterally; the entrance is a 0.30 s rise-and-fade with an accent rule.

**Why.** The prior finding still holds — `freezedetect` at −50 dB survives *geometry* motion and not
noise, and a held still card measures as a freeze. A push-in moves tens of thousands of pixels for
half the cost of drawing anything, and it cannot desynchronise from the narration because it is
derived from scene-local time.

**Cost.** A diagram is static art. It reads as a schematic on a moving camera, not as animation.

## D4. Comparison shows two panels, not two bars

**Decision.** The `comparison` composition draws two labelled panels with pictograms; the bar version
was deleted.

**Why.** Bars assert a ratio. The narration says "thousands of examples" and "slow and costly" — it
never states how much bigger one thing is than another. A chart that invents a magnitude is worse
than a panel that does not claim one, especially on a channel whose whole promise is that it explains
things accurately.

**Cost.** The composition is less quantitative. A real chart becomes possible only when a plan carries
real numbers, which would be a data-model change, not a drawing change.

## D5. Entity lexicon, not free-text keywords

**Decision.** Twelve entities with synonyms and drawn pictograms; a sentence earns the entities whose
synonyms it contains, in narrative order.

**Why.** The first attempt labelled diagrams with the sentence's longest words, which produced cards
labelled `LETS`, `LOOKS`, `FIX`, `SMALL`. A curated lexicon means every label on screen is a thing
that was drawn, and the set of things that can be drawn is auditable.

**Cost.** A sentence outside the lexicon falls back to the pipeline composition with whatever entities
matched. Extending coverage means adding an entity and an icon, which is a small, reviewable change.

## D6. Consecutive scenes may not reuse a composition

**Decision.** When the chosen composition equals the previous scene's, a fixed ladder selects the next
one that still explains the sentence.

**Why.** Two identical cards in a row is indistinguishable from a rendering bug, and it was visible in
the first integrated render (`gap` twice, then `comparison` twice).

**Cost.** The second-best composition may be a slightly weaker fit for one scene. The ladder is
ordered by how generic the alternative is, and `cta` is exempt.

## D7. Creative QC fails on an empty plan

**Decision.** `scene_count_in_derived_window` is an error check, so a plan with no scenes fails.

**Why.** `all()` over an empty list is `True`. Every gate in this codebase has been bitten once by a
check that passes because it examined nothing; an empty plan is the purest form of that.

**Cost.** A channel that has no narration cannot pass creative QC. That is the intended behaviour.

## D8. Thresholds are code defaults plus a file that can only tune

**Decision.** `content/creative_qc.json` may override values for keys already in `DEFAULTS`; unknown
keys are ignored, and a malformed file falls back to the defaults.

**Why.** A config file that can remove a check is a way to make a red report green without changing
the video. Tuning a number is a legitimate production need; disabling the question is not.

**Cost.** Adding a genuinely new threshold needs a code change.

## D9. The gate requires a creative verdict only when a scene plan exists

**Decision.** `creative_quality` is evaluated only when `scenes.json` is present; then a missing
`creative.json` is a blocker.

**Why.** A channel that has not adopted the engine produces no `scenes.json` and must not suddenly
fail its gate. But a render that *claims* a scene plan while having no creative verdict is exactly the
state where a video ships as a wall of type with nothing complaining.

**Cost.** Gate totals differ by channel (25/25 for Nexus, 24/24 for the others). Reporters that assume
a fixed number need to read `total`.

## D10. The provider interface exists and is disabled

**Decision.** `AssetProvider` protocol + `DisabledProvider` default; the resolver always records
"provider: none is not enabled".

**Why.** The budget forbids paid APIs and the directive forbids enabling a provider. Writing the
interface anyway means the deferral is visible in the code and in every resolution record, and a
future provider is a class, not a refactor. It also gave the tests something to point at: a fake
provider proves the fetch/validate/attribute path works without enabling anything real.

**Cost.** One protocol and one stub that production never executes.

## D11. Generated diagrams are re-drawn from their spec, not loaded from disk

**Decision.** `Resolution.image()` renders from `DiagramSpec` when the asset is generated; the file is
written to the cache as an artefact and for provenance.

**Why.** A generated asset whose source of truth is a PNG can silently drift from its spec. Re-drawing
makes the spec authoritative, and the cache copy still gives content addressing and a hash for the
manifest.

**Cost.** ~200 ms per scene on a cold render (once), and the cache file is not read back during
rendering.

## D12. The sync check compares spans, not absolute times

**Decision.** The plan's span must equal `narration_ms` within 40 ms, and no scene may end past the
video.

**Why.** The first version compared `scenes[-1].end_ms` to `narration_ms`, which differ by the opening
pause (~310 ms). It failed a plan that was exact to the millisecond — a false alarm, which is its own
kind of failure and would have trained the next engineer to ignore the check.

**Cost.** None; it now catches real drift and nothing else.

## D13. A brittle source-text assertion was strengthened, not relaxed

**Decision.** `test_the_measured_frame_is_what_gets_encoded` now asserts the call site, the shared
geometry argument and the dispatcher argument, instead of matching one formatted line of source.

**Why.** The test's intent is "the frame that is encoded is the frame that was measured". A literal
string match broke when the call gained an argument — a formatting change. Regenerating the expected
string would have preserved a meaningless check; rewriting it to the invariant makes it stricter.

**Cost.** None. It is the only pre-existing test touched.

## D14. A manifest entry must be declared where the artifact is built, not where it is rebuilt

**Decision.** `render_episode` declares `scene_plan`/`scenes.json` and `creative_qc`/`creative.json`
explicitly, as `(name, filename)` pairs matching `CANONICAL`, instead of deriving names by stripping
`.json` from a list of optional artifact keys.

**Why.** The derived version wrote both files and declared neither, so `verify()` reported them as
unlisted and the gate failed 24/25. CI survived only because it rebuilds the manifest before gating —
which is exactly the kind of accident that hides a defect: an operator running `gate` on a fresh
package got a different answer from CI on the same code.

**Cost.** None. The derivation also shadowed `video.json` (video probe) as `video`, which was a second
latent bug in the same three lines.

## D15. An inter-line pause belongs to the line that just ended

**Decision.** `_active_line()` returns the preceding line (and its index) throughout a pause, and the
final line after the last word.

**Why.** The card is a claim about what is being said. During a pause nothing is being said, so the
honest options were the preceding line or no card at all; showing the *next* line's headline and
counter while the previous line's plate was still on screen contradicted the audio for 32 frames.

**Cost.** None visible: goldens are unchanged because no golden samples a pause. The regression test
now samples every pause at four offsets, so a future change to gap handling cannot hide.

## D16. A check that fires on good work is worse than no check

**Decision.** `title_matches_narration` compares a plate title with the **whole episode's** vocabulary,
not with its own sentence's words.

**Why.** Against its own sentence it flagged 2 of 9 scenes on the real render — "WATCH AND LEARN" and
"THE DATA PROBLEM", both legitimate paraphrases. The defect it exists to catch is narrower: a plate
naming something the video never mentions (the audited STUDY). Measuring the episode vocabulary keeps
that detection and removes the false alarms.

**Cost.** The check can no longer catch a plate that is right for the episode but wrong for its
sentence. That case stays covered structurally instead: a plate's labels are drawn only from entities
found in that scene's own narration, so it cannot drift from its sentence without a synonym bug — and
the synonym table now has a test built from the audited narration.

## D17. Co-mention is not a relationship

**Decision.** Added the `panels` composition: two things a sentence mentions, side by side, with no
"vs" badge, no connecting arrow, and the footer "WHAT THE SENTENCE MENTIONS". `comparison` now requires
comparative language; its footer says "WHAT THE SENTENCE CONTRASTS" instead of "TWO ROUTES TO THE SAME
RESULT".

**Why.** "A robot arm needs thousands of examples to learn one grasp" states a quantity. Drawing
"ROBOT vs DATA / TWO ROUTES TO THE SAME RESULT" asserts a contest and a shared outcome the narration
never states — the same class of error as drawing cost as a pipeline stage (H4), found only because the
rendered plates were inspected after the fix rather than assumed correct.

**Cost.** Two more compositions to maintain (10 defined, 6 used). The alternative — an arrow or a
versus badge — is a claim, and a plate that is merely plain is better than a plate that is confidently
wrong.

## D18. Re-render after every correctness fix, and measure the file

**Decision.** Each semantic fix was followed by a full re-render and inspection of frames extracted
from the encoded MP4, not from in-memory composition.

**Why.** H2, H4 and the comparison claim were all invisible to the test suite as it stood and visible
in one frame. The suite now covers each of them, but the habit is the point: three renders
(`3cd77bc…`, `fb0c1a6…`, `2f4a936…`) were made because each one revealed or confirmed something the
previous could not.

**Cost.** ~160 s per render, plus inspection. Cheap next to shipping a plate that says STUDY over a
sentence about videos.
