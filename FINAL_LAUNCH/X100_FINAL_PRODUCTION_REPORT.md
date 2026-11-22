# X100 FINAL PRODUCTION REPORT

Starting SHA `60afdb1` → ending SHA recorded in the commit that adds this file. Branch
`feat/landscape-16x9`, `main` untouched at `567e63c`, PRs #2/#3/#4 open and MERGEABLE.

## Executive verdict: READY WITH OWNER ACTIONS

The factory is a working local production system with a real research front end, hardened security and
honest gates. It is **not** a cloud production system yet, and it has never published anything. Two of
the three channels currently fail QC, which is a defect, not a configuration gap.

## What was executed in this assignment

| Step | Result |
| --- | --- |
| Baseline re-verified | `FINAL_LAUNCH/BASELINE_AUDIT.md`; HEAD, tree, remote, identity, PRs, settings all re-checked |
| Emergency stop | `factory/controls.py` + `factory.cli pause/resume` + a workflow gate; 8 tests; pause verified to block a render and resume to clear it |
| Failure notification | `factory.cli notify` + a `if: failure()` step in `produce.yml`; provider-independent, silent unless `FACTORY_NOTIFY_WEBHOOK` is set |
| Research, three channels | nexus-node: **3 candidates from 4 sources, 0 errors**; academic-biohacker: **0 candidates from 2 sources, 1 source error**; natkhat-toons: **0 sources configured** (by design — see below) |
| Nexus Node render | 39.97 s portrait Short, **QC FAILED: frozen 1.5 s at 18.3 s** |
| Academic Biohacker render | 38.23 s portrait Short, **QC FAILED: frozen 2.2 s at 6.2 s** |
| Natkhat Toons render | verified earlier this session: 32.135 s, `qc_ok: true` |
| Landscape episode | verified earlier: 64.501 s, 27/27 checks, sha `bf93b056…` |
| Tests | **796 passed**, goldens 78/0/0 |
| Security | secret scan 0/0, Gitleaks 0/0, dependency audit 0/0, workflow audit 0 over 7 workflows |

## Outstanding defects

1. **English card renderer freezes.** Nexus Node and Academic Biohacker Shorts each hold a static card
   long enough to trip `frozen_frames` (1.5 s and 2.2 s). The gate is right; the renderer needs motion on
   the card (parallax, type reveal, or a diagram beat) before either channel can ship.
2. **Academic Biohacker research produced no candidates** from its two live sources (arXiv q-bio came
   back with a source error). Either the feed is down or its titles score below the relevance floor; the
   report records which, and needs a second run to separate the two.
3. **Natkhat Toons has no discovery source, deliberately.** A news feed is the wrong research basis for
   original children's stories; its research basis is the series bible (`content/series/natkhat-toons.json`).
   Making that explicit in the engine is outstanding work, not a missing feed.
4. Hand-off staging overlaps the two drawn bodies (arm length vs body width).
5. No clean 10-minute episode (the benchmark plan was incoherent and QC refused it).

## Cloud and publishing: not executed, and why

`production.yml` is `workflow_dispatch`-only. GitHub only dispatches a workflow from the default branch,
which does not contain it until **PR #3 merges** (owner action). There are **0 repository secrets**, so no
OAuth flow can run. Nothing has been uploaded, scheduled, or published; the three crons remain
`disabled_manually`; `UPLOAD_ENABLED=false`, `SCHEDULED_PUBLISHING_ENABLED=false`,
`PUBLICATION_APPROVAL_REQUIRED=true`.

## Required owner actions

1. Merge PR #3, then #2, then #4 is redundant.
2. Add `YT_<CHANNEL>_{CLIENT_ID,CLIENT_SECRET,REFRESH_TOKEN}` and confirm the OAuth app is production.
3. Dispatch `production.yml --ref main -f channel=natkhat-toons -f mode=render+validate -f upload=false`.
4. Enable schedules only after that run is green and a private upload is verified.
5. Enable non-provider secret scanning and code scanning in Settings → Code security.
