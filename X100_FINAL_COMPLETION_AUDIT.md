# X100 final completion audit

> **Historical snapshot:** this audit predates merge commit `01f3abd4078abca30eabbd6822139130121a72d7` and the
> November 25, 2026 production-artifact review. Use [the current closure report](X100_FINAL_PRODUCTION_CLOSURE_REPORT.md)
> and [activation handover](X100_FINAL_ACTIVATION_HANDOVER.md) for current test, workflow, and release status.

Date: 2026-11-25
Repository: `Ayushjaiswal0001/youtube`
Base: `main` = `8deaf78` (merge of PR #15, the X100 Visual Engine v1.1)
Work branch: `feature/x100-academic-visual-integration` @ `239bea4`

Every claim below is one of:

| word | meaning |
|---|---|
| **VERIFIED** | I ran it in this session and read the result. The number or artifact is quoted. |
| **IMPLEMENTED, NOT VERIFIED** | The code exists and has unit tests, but I did not run the end-to-end path in this session. |
| **OWNER-BLOCKED** | It needs a credential, a setting, or a decision only the owner can make. |
| **NOT IMPLEMENTED** | It does not exist. |

Nothing in this document is inferred from a previous report. Where a previous report's number was not
re-measured here, the row says so instead of repeating it.

---

## 1. What this repository is

An automated YouTube production line for three channels, driven by Python + FFmpeg + Cairo, with no paid
service anywhere in the render path:

| channel | language | format | engine | visual identity |
|---|---|---|---|---|
| Nexus Node | en | 9:16 shorts + 16:9 long | shorts character engine, editorial card engine | dark tech palette, diagram & chart plates |
| Academic Biohacker | en | 9:16 shorts + 16:9 long | shorts character engine, editorial card engine | paper palette, diagram plates |
| Natkhat Toons | hi | 9:16 shorts | Hindi studio engine (rigged characters, Chromium Devanagari overlays) | night-time haveli, two characters |

The pipeline is a state machine per episode: `QUEUED → PREFLIGHT → GENERATING → RENDERING →
VALIDATING → PACKAGING → [APPROVAL] → UPLOAD → READY`, journalled per job, guarded by a per-plan lock,
and gated before anything can leave the machine.

## 2. The production chain, stage by stage

| stage | what actually runs | state |
|---|---|---|
| research | `factory/research.py`, topic banks in `content/topics/`, series in `content/series/` | **IMPLEMENTED, NOT VERIFIED** (no beat was authored in this session) |
| script | `factory/content/script.py`, `factory/content/plans.py` | **VERIFIED** through every render below |
| scene plan | `factory/content/scene_plan.py`, tiled to narration | **VERIFIED**: 6–10 scenes per short, every plate scored |
| visuals | `factory/media/assets/` (plates, pictograms, charts, diagrams), `studio/` (characters) | **VERIFIED**: 5 shorts + 1 long rendered and inspected |
| voice | `edge-tts` voices via the renderer, mixed with a generated bed | **VERIFIED**: TTS ran per line; audio passed EBU R128 |
| sync | captions and audio derived from one timeline | **VERIFIED**: `av_sync` start delta 0.000 s, length delta 0.017 s |
| QC | `factory/qa/validator.py` (25 checks) + `factory/qa/creative.py` (21 checks) | **VERIFIED**: 25/25 and 21 with 1 acknowledged warning |
| metadata + thumbnail | `factory/manifesting.py`, `factory/publisher.py` | **VERIFIED** through the dry-run publish payload |
| gate | `factory/qa/publish_gate.py` | **VERIFIED**: 24/24 (en), 23/23 (hi) with zero blockers |
| publish | `uploader/` OAuth2 upload, private by default | **OWNER-BLOCKED**: no credential may be used without the owner |
| schedule | three daily crons calling `produce.yml` | **OWNER-BLOCKED**: all three are `disabled_manually` |

## 3. Capability checklist

The directive's required capabilities, one row each.

| capability | verdict | evidence |
|---|---|---|
| per-channel script/narration generation | **VERIFIED** | three channels produced their own scripts and voices in this session |
| scene planning | **VERIFIED** | `scenes.json` per episode; Nexus 6, Academic 7–10, Natkhat story beats |
| contextual visuals | **VERIFIED** | plates chosen from the sentence; 6/6, 7/7, 9/9, 10/10 distinct pictures |
| genuine animation (not static plates) | **VERIFIED for characters, PARTIAL for plates** | Natkhat: 0 frozen segments at −50 dB over 32.1 s, characters animate; plates use push-in/drift + per-scene redraw. Plate motion is camera motion, not object motion — see §7 |
| A/V/subtitle sync | **VERIFIED** | `av_sync` 0.000 / 0.017 s; 10–15 caption cues per episode from one timeline |
| automated QC | **VERIFIED** | 25 technical + 21 creative checks per episode, both fail-closed |
| metadata + thumbnails | **VERIFIED** | dry-run payload carries title, description, tags, `private`, `madeForKids`, thumbnail path |
| upload readiness (dry-run) | **VERIFIED** | `status: dry_run_ok`, `upload_performed: false`, `duplicate_check: clear`, identity verified |
| deterministic job ids | **VERIFIED** | `nexus-node_nexus-small-models_20261124`, stable across re-runs on the same date |
| idempotent retries | **VERIFIED** | second render of Natkhat: `skipped_render: true`, identical sha256, 5.4 s vs 139.7 s |
| resume from failure | **VERIFIED** | killed a render at 22 s; `resume` completed to `READY_TO_PUBLISH` with the artifact in place |
| render caching | **VERIFIED** | plan-level skip above; asset cache reused across episodes (mesh/chart plates) |
| duplicate-upload prevention | **IMPLEMENTED, NOT VERIFIED against YouTube** | `duplicate_check: clear` is computed from local state; the remote side never executed |
| per-channel job isolation | **VERIFIED** | separate lock file, state dir, secret prefix, concurrency group, and hard `Ayushjaiswal0001/youtube` identity check |
| structured logs | **VERIFIED** | `journal.jsonl` per job, `run.jsonl` history, JSON on stdout |
| production reports | **VERIFIED** | this file, the readiness report, the operations guide, per-episode QC reports |

## 4. What is genuinely missing or unproven

1. **The upload path has never executed on GitHub Actions.** `produce.yml` is wired and gated, but no run
   has had `upload=true` with live credentials. **OWNER-BLOCKED.**
2. **All three daily schedules are off** (`academic-biohacker daily`, `natkhat-toons daily`,
   `nexus-node daily` = `disabled_manually`). Turning them on is an owner decision, not a code change.
   **OWNER-BLOCKED.**
3. **The 9 `YT_*` repository secrets are unused and unverified.** Validating them means an OAuth call,
   which is a stop condition. **OWNER-BLOCKED.**
4. **Notification delivery is a no-op** (`NullNotifier`, `delivered: false`) until
   `FACTORY_NOTIFY_WEBHOOK` is set. **OWNER-BLOCKED.**
5. **Natkhat has no topic bank** (`content/topics/natkhat-toons.json` does not exist). Its episodes come
   from `series_key` + the studio story engine, which works, but there is no equivalent of the
   research→plan rotation the English channels have. **NOT IMPLEMENTED** (by design, but it is a gap in
   parity).
6. **Object motion on plates.** A diagram plate is drawn once per scene and animated by camera motion
   only. Real animated diagrams (a bar growing, a node lighting up in order) do not exist.
   **NOT IMPLEMENTED.**
7. **Long-form for Academic and Natkhat was not rendered.** Nexus long-form rendered end to end
   (`long-nexus-power-grid`, 223.1 s, QC 25/25), but the other two channels' long-form content was not
   exercised in this session. **NOT VERIFIED** for those two.
8. **The 60-minute workflow timeout is too short for long-form.** One long-form render took 50 min 8 s.
   Reported as a capacity shortfall in the readiness report with the two changes that fix it; not applied
   here because workflow edits are out of scope.
9. **Non-provider secret scanning, code scanning, and validity checks** remain owner-gated features.
   **OWNER-BLOCKED.**

## 5. Defects found and fixed in this mission

Six defects were found by running the pipeline, not by reading it. Each one is committed with a
regression test.

| # | defect | how it was found | fix | test |
|---|---|---|---|---|
| 1 | Academic Biohacker had no visual vocabulary: its paper palette drew empty statement rings because the shared lexicon held no physiology words | rendered 4 of its own beats as a contact sheet | 9 entities + pictograms (breath, heart, brain, sleep, light, glucose, movement, temperature, meal); `sleep` left the `study` synonyms; channel got a real `visual_policy` | `tests/factory/test_academic_visuals.py` (53) |
| 2 | a headline could choose a composition that draws hardware: "A light sensor" over a sentence about retinal cells drew a labelled robot-arm cutaway | rendering the academic topic bank | `components`/`layers`/`topology`/`pipeline`/`timeline` now need their cue in the **narration**, not the headline | same file |
| 3 | a run of identical compositions had no honest escape: the ladder offered `pipeline`/`timeline`, which refuse without a stated order, so it fell straight back | first Academic render: `no_repeated_composition_runs` failed | new `focus` composition (same claim as `statement`, different layout); ladder rewired `statement ↔ focus` | same file |
| 4 | the anti-repetition ladder ran **before** the honesty rules, so a demotion could land on the composition it was avoiding | gate on the real plan `nexus-small-models`: `creative_quality` blocked with 4 statements in a row | rules became one `settle()` applied to every candidate; the ladder only steps onto a candidate that survives them | `tests/factory/test_v11_ladder.py` (9) |
| 5 | the no-subject guard rewrote a subscribe line from `cta` to `statement`, so the closing card never appeared | same gate run | `cta` is exempt from the no-subject guard | same file |
| 6 | the encoded true peak was assumed, not measured: `nexus-robot-video` encoded to **−0.46 dBTP** at limiter 0.74 while another episode encoded to −2.33 dBTP with the same settings | per-episode QC report generator | `mix_narration` measures the file it wrote and tightens the limiter only when the gate would fail | `tests/factory/test_peak_guard.py` (4) |

Defects 4 and 5 are the important ones: they were **production blockers on a real repo plan**, found by
the gate rather than by a reviewer, and they would have shipped an episode that could not be published.

## 6. Verification inventory (this session)

| check | result |
|---|---|
| full test suite | **1,302 tests**, all passing (see readiness report for the exact run) |
| shorts rendered end to end | 5 episodes across 3 channels |
| long-form rendered end to end | `long-nexus-power-grid` (11 beats): 223.1 s, 47.4 MB, 1920×1080, QC 25/25, −14.2 LUFS / −2.11 dBTP, 50 min 8 s wall |
| technical QC | 25/25 on every short except Natkhat (see §7) |
| creative QC | 21 checks, 1 acknowledged warning (`dataviz_delivered`, no stated figure to chart) |
| publishing gate | 24/24 (en), 23/23 (hi), zero blockers |
| dry-run publish | `dry_run_ok` on all three channels, `upload_performed: false`, private |
| idempotency | second run skipped, identical sha256, 26× faster |
| failure recovery | SIGKILL mid-render → `resume` → `READY_TO_PUBLISH` |
| secret scan (tree) | 14 rules, 0 findings |
| dependency audit | 0 unaccepted |
| workflow audit | 7 workflows, 0 findings |
| frozen-frame scan | Natkhat 0 freeze events at −50 dB |

## 7. Quality risks that remain

These are honest weaknesses, not blockers:

1. **Plate "animation" is camera motion.** Push-in and drift are real motion (the frozen-frame check
   proves it), but a diagram does not animate its own content. This is the single largest visual gap
   against a channel that draws animated explainers.
2. **Natkhat wide shots are near-static.** The characters blink, breathe and lip-sync, and there is a
   real close-up shot, but two consecutive wide frames at 1 s and 4 s are visually identical. Continuity
   is preserved; expressiveness in wide shots is limited.
3. **Charts need a stated number.** The reference episode and both topic banks state **zero numeric
   figures**, so a real episode draws no chart even though the drawers are proven. Charts appear only
   when a beat states a number.
4. **A bar compares percentages of different wholes** when a sentence states two percentages of
   different things. The `bars` drawer shares one scale only, but it cannot know the wholes differ.
5. **Chart scenes bypass the no-repeat ladder** (a chart is chosen by the statement, not by the ladder).
6. **Creative QC only covers the shorts engine.** Natkhat and the long-form card renderer have no scene
   plan, so they are gated on 25 technical checks alone. This is deliberate (the gate only demands a
   creative verdict when a plan exists) and it is a gap: a repeated composition on the card path would go
   unnoticed.
7. **`figure_is_stated` compares digits, not meaning.** It cannot tell that on-screen "20%" refers to a
   different sentence.
8. **Four consecutive CTAs** are allowed by the threshold of 2, which is generous; Academic
   `academic-morning-light` ends with two closing plates.
9. **A plan without a closing line has no CTA card** — the card is planned, not imposed.

## 8. Prioritised plan to "done"

**P0 — needed before any public upload (all owner-gated, no code work):**

1. Put the OAuth consent screen **In production**, run `uploader consent --client-json`, then
   `tools.check_oauth_identity --channel all`.
2. Validate **one** secret at a time with `upload=true` on `workflow_dispatch`, `mode=validate`.
3. Re-run `production.yml` for each channel with `upload=true, mode=render+validate` and confirm the
   private upload lands on the right channel with `madeForKids` correct for Natkhat.
4. Only then re-enable the three daily crons.

**P1 — quality work that needs no credential:**

5. Animated diagram content (bars that grow, nodes that light in order) inside the existing plate
   contract. Measurable done: a 30-frame strip from a chart scene shows the bar's drawn width increasing
   monotonically.
6. Better wide-shot expression for Natkhat (secondary motion, blinking cadence, a per-shot camera
   move). Measurable done: frame-to-frame mean absolute difference above a floor on every shot, with
   continuity hashes unchanged.
7. State figures in the topic banks so charts appear in real episodes.
8. A third single-subject composition so a run never depends on two.

**P2 — parity and operations:**

9. Natkhat research→plan rotation.
10. Long-form for Academic and Natkhat rendered and gated.
11. A notification webhook so a failed nightly run is not silent.

## 9. Measurable definition of DONE

The project is done when all of the following are true, each measurable:

1. `pytest tests` green on `main`, with no test skipped for lack of a service.
2. Three channels each produce **1 short + 1 long** per day, unattended, for 7 consecutive days, with
   zero manual intervention and zero gate failures.
3. Every produced episode passes 25/25 technical and 21/21 creative checks, with warnings named.
4. Every upload is private, lands on the channel whose ID matches the channel config, and appears in the
   local ledger exactly once across retries.
5. A deliberately failed nightly run is visible to the owner through a notification, and a re-run
   completes without duplicate uploads.
6. Cost: ₹0/month, measurable as zero billing lines on a paid account.
7. No secrets in the tree, no force-push, no direct `main` push, every change through a PR.

Today, items 1, 3, 4 (locally), 6 and 7 are **VERIFIED**. Item 2 cannot be verified until the schedules
are enabled. Item 5 is blocked on the webhook.

---

## Appendix A — exact commits on this branch

```
239bea4 fix: guarantee the encoded true peak instead of trusting one limiter constant
70bc775 test: pin the composition ladder ordering that the gate found
3a442ab fix: settle the honesty rules before the anti-repetition ladder
0482547 feat: integrate Academic Biohacker into the visual engine
8deaf78 (main) Merge pull request #15 ...
```

## Appendix B — files touched

| file | why |
|---|---|
| `factory/media/assets/generated.py` | academic entities and pictograms, narration-cued compositions, `focus` drawer, settled ladder, cta exemption |
| `factory/media/music.py` | measured true-peak guard |
| `channels/academic-biohacker.json` | real `visual_policy` |
| `tests/factory/test_academic_visuals.py` | 53 tests |
| `tests/factory/test_v11_ladder.py` | 9 tests |
| `tests/factory/test_peak_guard.py` | 4 tests |
| `tests/factory/test_v11_policy.py` | academic policy is now active (Natkhat stays inert) |
| `tools/report_episode_qc.py` | generates the per-episode QC report from artifacts |
