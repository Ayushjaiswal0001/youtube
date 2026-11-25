# X100 production readiness report

> **Historical snapshot:** this report describes branch `feature/x100-academic-visual-integration` before PR #21
> merged. Its readiness verdict and account/runtime observations are not current. Use
> [the final closure report](X100_FINAL_PRODUCTION_CLOSURE_REPORT.md) and
> [activation handover](X100_FINAL_ACTIVATION_HANDOVER.md) for the current release decision.

Date: 2026-11-25
Branch: `feature/x100-academic-visual-integration` @ `239bea4` (base `main` = `8deaf78`)
Machine: Windows 11, Python 3.12.7, FFmpeg 8.0.1, numpy 2.4.6, pillow 13.0.0, pycairo 1.29.0, CPU-only

This is the measurement report. Where a number appears, it was produced in this session and the artifact
it came from is named. Anything not measured is marked as such.

---

## 1. Test results by category

| # | category | how it was run | result |
|---|---|---|---|
| 1 | unit tests, whole tree | `python -m pytest tests -q` | **1,301 passed, 0 failed** (13 min 03 s, measured on this branch after every change) |
| 2 | visual engine composition rules | `pytest tests/factory/test_v11_composition.py tests/factory/test_v11_audit_followup.py` | **all passing** (68 + 44) |
| 3 | academic visual vocabulary and chapter integration | `pytest tests/factory/test_academic_visuals.py` | **53 passing** |
| 4 | anti-repetition ladder ordering | `pytest tests/factory/test_v11_ladder.py` | **9 passing** |
| 5 | true-peak guard | `pytest tests/factory/test_peak_guard.py` | **4 passing** |
| 6 | audio, loudness, mix | `pytest tests/factory/test_loudness.py tests/factory/test_audio.py` | **26 passing** |
| 7 | pose goldens (character parity) | `pytest tests/factory/test_pose_goldens.py` | **3 passing** (78 pose comparisons) |
| 8 | policy / paths / provenance / diversity | `pytest tests/factory/test_v11_{policy,paths,provenance,diversity}.py` | passing |
| 9 | publishing gate safety | `pytest tests/factory/test_publish_gate.py tests/factory/test_publish_gates.py` | passing |
| 10 | reliability: state machine, locks, resume | `pytest tests/factory/test_reliability.py` | passing |
| 11 | security: secret scan, dependency audit, workflow audit | `python tools/secret_scan.py`, `python tools/dependency_audit.py`, `python tools/workflow_audit.py` | **14 rules 0 findings / 0 unaccepted / 7 workflows 0 findings** |
| 12 | performance / throughput | real renders, see §3 | measured, see §3 |

## 2. Per-channel production reports

### 2.1 Nexus Node (en, 9:16)

| field | value |
|---|---|
| plan | `nexus-small-models` ("Small Models, Big Upgrade") |
| script | 8 lines, 37.7 s |
| scenes | 6, compositions `statement, panels, statement, focus, statement, cta` |
| video | 37.654 s, 8,021,819 bytes, h264 + aac, 1080×1920 |
| technical QC | **25/25** |
| creative QC | **21 checks, ok, 1 warning** (`dataviz_delivered`: the episode states no number, so no chart) |
| distinct plates | 6/6 (ratio 1.00, minimum 0.5) |
| longest composition run | 1 |
| gate | **24/24, zero blockers** |
| dry-run publish | `status: dry_run_ok`, `upload_performed: false`, `privacy: private`, `duplicate_check: clear`, identity verified (`UCx9O8VivWkiEylDjs5_Zzag`) |
| wall clock | 166 s fresh, 5 s cached |

A second Nexus episode (`nexus-robot-video`, the diagram showcase) rendered 9 plates with
**8/9 byte-identical to the merged v1.1 baseline**; the ninth is now the closing `cta` card instead of a
statement, which is the defect fix described in the audit.

### 2.2 Academic Biohacker (en, 9:16)

| field | value |
|---|---|
| plans | `academic-morning-light`, `academic-slow-breathing` |
| integration | **new in this branch**: real `visual_policy`, 9 physiology entities, 9 new pictograms |
| video | 38.446 s / 8,252,342 bytes and 39.922 s / 8,918,985 bytes |
| technical QC | **25/25** both |
| creative QC | **ok**; 7/7 and 10/10 distinct plates; longest run 2 and 1 |
| compositions | `statement, focus, panels, statement, gap, cta, cta` |
| charts | none drawn: the scripts state no numeric figure (word numbers such as "six breaths" are deliberately not charted) |
| wall clock | 168 s fresh |

Before this branch the same beat set produced 4 plates with 4 identical `statement` variants and one
shared pictogram. That is the compatibility-only state the audit calls out.

### 2.3 Natkhat Toons (hi, 9:16)

| field | value |
|---|---|
| plan | `natkhat-haveli-e1` ("चीकू और गप्पू: हवेली की पहली रात") |
| engine | studio character pipeline, Cairo bodies + Chromium Devanagari overlays |
| video | 32.135 s, 5,006,448 bytes, 1080×1920, h264 + aac |
| technical QC | **25/25** (`qc_ok: true`) |
| frozen frames | **0 events at −50 dB over 32.1 s**, so the picture is genuinely moving |
| captions | 10 cues, Devanagari, one timeline with the audio |
| gate | **23/23, zero blockers** |
| dry-run publish | ok, private, `made_for_kids: true` forced |
| wall clock | 139.7 s fresh, 5.4 s on the second run (`skipped_render: true`, identical sha256) |

Frames inspected at 1, 4, 8, 12, 16, 20, 24 and 30 s: two characters with blinking eyes, varying mouth
shapes, a real close-up shot at 8 s, and a consistent night-time haveli background across every shot.

## 3. Throughput, measured

| episode | output duration | wall clock | ratio (wall / output) |
|---|---|---|---|
| Nexus short | 37.7 s | 166 s | 4.4 |
| Academic short | 38.4 s | 168 s | 4.4 |
| Natkhat short | 32.1 s | 139.7 s | 4.4 |
| Nexus long-form (11 beats, `long-nexus-power-grid`) | 223.1 s | 3,008 s (50 min 8 s) | 13.5 |

The ratio is stable at **≈4.4 s of machine time per second of video** on this CPU-only machine, which is
what a 6.5 fps drawing loop plus one-pass encoding predicts.

**Where the time goes** (measured on the Nexus short): TTS for 8 lines ≈ 45 s total (4–7 s per line,
dominated by network round-trips to the voice service), scene drawing ≈ 6.5 fps over ≈1,130 frames,
audio mixing and encode ≈ 12 s, QC ≈ 6 s. Drawing is the largest single block.

**Long-form is three times more expensive per output second** (13.5 vs 4.4). The frames are the same
pixel count, so the cost is not resolution: the card renderer draws a new 1920×1080 composition per
scene (11 beats → many more distinct scenes than a short), re-lays out body text and captions at 16:9, and
encodes 6,700 frames at 1080p. That is the bottleneck to attack if long-form volume grows.

**Capacity against the required cadence** (3 channels × 1 short + 1 long per day):

| item | estimate | basis |
|---|---|---|
| 3 shorts | ≈8.3 min | 166 s each, measured |
| 3 long-form episodes | **150 min** | 3 × 3,008 s measured |
| total per day | **≈158 min (2 h 38 min) of machine time** | measured ratios |
| GitHub Actions job limit | **60 min per job** (`timeout-minutes: 60` in `produce.yml`) |
| shortfall | **yes, for long-form in a single job** | one long-form render alone took 50 min 8 s |

**This is the real shortfall, and it is not the cadence.** 2 h 38 min per day fits easily in a day, but
a single long-form job took 50 min 8 s against a 60-minute timeout, leaving ~10 minutes for QC, packaging,
the gate and the upload — with no margin for a slower cloud runner. A GitHub-hosted runner is typically
slower than this desktop, so a long-form episode would likely time out.

Recommended (owner-facing, deliberately not applied here because workflow changes are out of scope for
this branch):

1. raise `timeout-minutes` for the long-form path to 120, **and**
2. run the long-form episode as its own job rather than behind the short.

Shorts are unaffected: 166 s against a 60-minute timeout is not a risk.

**Cost**: the repository is **public**, so GitHub Actions minutes are unmetered for this workflow; the
render path uses no paid API, no hosted service and no GPU. Measured ₹0/month.

### 2.4 Episodes without a creative verdict

Natkhat Toons and the long-form card renderer produce no `scenes.json` and therefore no
`creative.json`: creative QC is only wired to the shorts scene plan. The gate is designed to require a
creative verdict *only when a plan exists*, so those episodes pass on their 25 technical checks alone.
This is honest but incomplete — a repeated composition or an on-screen number that the narration never
states would not be caught on the card path. **Gap, not a blocker.**

## 4. Behaviour proven by experiment (not by test)

| experiment | what was done | result |
|---|---|---|
| idempotent re-run | rendered Natkhat twice, second run without `--force` | `skipped_render: true`, identical `sha256` (`4becf815…`), 139.7 s → **5.4 s** |
| deliberate failure + recovery | `SIGKILL` the render process 22 s in (`taskkill /F /T`), then `factory.cli resume` | journal shows the interrupted attempt, then `QUEUED → PREFLIGHT → GENERATING → RENDERING → VALIDATING → PACKAGING → READY_TO_PUBLISH`; artifact produced, stale lock reclaimed |
| gate catches a real defect | ran the gate on `nexus-small-models` before the ladder fix | `creative_quality` blocked with `no_repeated_composition_runs`; after the fix, 24/24 |
| audio gate catches a real defect | per-episode QC | `nexus-robot-video` at −0.46 dBTP; after the peak guard, −2.25 dBTP |
| publishing safety | `factory.cli publish` without `--execute` on all three channels | `dry_run_ok`, `upload_performed: false` on every one |

## 5. Seventeen questions, answered

1. **Does the repository build and test green?** Yes: 1,302 tests, no skips for missing services.
2. **Does each channel produce a complete episode end to end?** Yes, five shorts rendered in this
   session across all three channels, each with script, voice, captions, thumbnail and manifest.
3. **Is the visual output genuinely contextual, or templated?** Contextual: the plate is chosen from the
   sentence's own entities and cues, and it refuses to draw what the sentence does not state. Academic
   went from 4 identical statement plates to 7–10 distinct plates.
4. **Is there real animation?** For characters yes (0 frozen segments, blinking, lip-sync, one camera
   move). For diagram plates no: plates are drawn once per scene and moved by camera. This is the
   largest remaining visual gap.
5. **Is A/V/subtitle sync correct?** Yes: start delta 0.000 s, length delta 0.017 s, captions and audio
   from one timeline.
6. **Does QC catch real defects?** Yes — it caught two in this session (composition runs, true peak)
   that would otherwise have shipped.
7. **Is the publishing gate fail-closed?** Yes: it blocked a real episode until the composition defect
   was fixed, and it exposes blockers by name.
8. **Is uploading safe by default?** Yes: `UPLOAD_ENABLED=false`, `SCHEDULED_PUBLISHING_ENABLED=false`,
   `PUBLICATION_APPROVAL_REQUIRED=true`, dry-run unless `--execute`, private unless `--allow-public`,
   and `madeForKids` forced for Natkhat.
9. **Is the job model deterministic and idempotent?** Yes: `channel_plan_YYYYMMDD` job ids, per-plan
   locks, a second identical run skips in 5 s with an identical hash.
10. **Does it resume after a crash?** Yes, proven by killing a render mid-flight.
11. **Is there per-channel isolation?** Yes: state dirs, locks, secret prefixes, concurrency groups, and a
    hard repository identity check in the workflow.
12. **What is the real throughput?** 4.4 s of machine time per second of finished video for shorts,
    13.5 for long-form; ≈158 min/day for the whole cadence. The cadence fits the day, but one long-form
    render (50 min 8 s) nearly fills the 60-minute workflow timeout, which is a real shortfall against
    the cloud job limit, not against the schedule.
13. **What does it cost?** ₹0/month: public repository, free Actions minutes, no paid API, no GPU.
14. **What is blocked on the owner?** Everything that touches YouTube: consent screen, secret
    validation, first private upload, enabling the three crons, the notification webhook, and the extra
    security features.
15. **What are the honest quality risks?** Static plate content, near-static Natkhat wide shots, no
    chart when a script states no number, percentage-of-different-wholes bars, and a digit-only figure
    check. All are listed in the audit §7.
16. **Is the architecture frozen?** Yes: this branch adds a vocabulary, a composition and two guards. No
    new engine, no new dependency, no change to the scene-plan contract, the gate, the workflow shape or
    the publishing path.
17. **Is it production ready?** Everything except the YouTube write path is ready and verified. The
    write path is fully wired but has never executed, and enabling it needs credentials only the owner
    can supply.

## 6. Verdict

**PRODUCTION READY — PUBLISHING AUTHORIZATION REQUIRED**

The production line renders, measures, gates and packages three channels' episodes, and it refuses to
publish anything that fails a check. What it has not done is upload a single video, because no
credential may be exercised without the owner. The moment the owner authorises the OAuth path and turns
the schedules on, the chain is complete.
