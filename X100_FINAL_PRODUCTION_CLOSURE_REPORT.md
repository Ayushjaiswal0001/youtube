# X100 final production closure report

Audit date: 2026-11-26 (IST)

Repository: `Ayushjaiswal0001/youtube`

Verified base `main`: `01f3abd4078abca30eabbd6822139130121a72d7` (merge commit for PR #21)

Candidate branch: `codex/fix-publishing-policy-clock-test`

## A. Executive summary

The merged implementation has working render, QC, gate, and private-upload code paths, and representative GitHub Actions artifacts were inspected for all three channels in both output formats. The merge-commit CI run exposed a clock-dependent test failure; the production resolver correctly rejected the missed release. The local Windows regression run also exposed a real lock-liveness portability bug: `os.kill(pid, 0)` sends a Ctrl+C event on Windows. The lock check now uses a waitable Win32 process handle and fails closed on uncertain access. Security review found a workflow-dispatch command injection in the production upload path; the focused branch now normalizes plan IDs and passes step outputs through environment variables. The available Nexus evaluation Short also had an unsupported absolute claim; it now uses qualified language and direct evidence links.

The candidate is **ready for owner review with documented limitations**. PR #22's code and security checks are green. This does not mean production is activated: all three daily channel workflows remain disabled, no workflow was dispatched, no upload or public schedule was created, and no OAuth secret was read. Live YouTube schedule verification and current account-state checks remain owner-dependent.

## B. Repository identity and source of truth

- Expected repository and remote: `Ayushjaiswal0001/youtube`.
- Original workspace `D:\animated` was a different repository with user changes and was not modified.
- The X100 repository was cloned separately to `D:\X100-youtube`.
- Audit base `main`: `01f3abd4078abca30eabbd6822139130121a72d7`; PR #21 is merged.
- The clock-test, Windows lock, shell-injection, editorial, and documentation changes are isolated on `codex/fix-publishing-policy-clock-test`; PR #22 carries the review and CI record.

## C. CI status

- Merge-commit run `45655992920`: six of seven checks passed. `factory (plan + publish gates)` failed one test after 1,371 passed and 2 skipped. The failure was `test_publish_looks_up_the_release_for_its_own_plan`; its fixed November 25 release had passed the late-grace window because the test used wall-clock time.
- Security run `45655992820` passed. It ran the repository's secret, history, dependency, and workflow-permission checks.
- The test now pins the resolver to a time before the intended release while still calling the real resolver. The focused test passed locally.
- PR [#22](https://github.com/Ayushjaiswal0001/youtube/pull/22) remains open and unmerged. The final documentation refresh received its own CI and security runs, and all checks are green; GitHub reports merge state `CLEAN`. Owner review remains pending.
- Final PR CI run `45685498369`: factory tests **1,375 passed, 2 skipped** in 449.80 seconds; uploader unit tests **77 passed** on both Python 3.11 and 3.12. Security run `45685498495` passed all four jobs: secret/history scanning, Gitleaks, dependency audit, and workflow permissions/pinning. Duplicate push-triggered CI run `45685484629` passed the factory tests (**1,375 passed, 2 skipped** in 441.34 seconds); its security run `45685484719` also passed all four jobs.

## D. Test results

Before the security-auditor regression tests were added, `python -m pytest --collect-only -q` collected **1,451 tests across 81 modules**. Six disjoint, exhaustive file batches passed: **1,451 passed, 0 failed, 0 skipped, 5 successful subtests**; cumulative pytest runtime **1,009.88 s (16:49.88)**, excluding collection. After the audit fix, the current collection is **1,454 tests across 82 modules** and the added workflow-auditor tests passed **3/3** locally. The green PR CI covers the current suite through 1,375 factory pytest cases (2 skipped) and 77 uploader unit tests on each supported Python version.

Environment: Windows 11, Python 3.12.7. `python -m compileall -q factory studio tools` passed after the workflow-audit change. The current collection is 1,454 tests across 82 modules; the new workflow-audit tests passed 3/3. Final PR CI covered 1,375 factory tests (2 skipped) plus all 77 uploader unit tests on Python 3.11 and 3.12.

Batch 1: 243 tests — 188.71 s
```powershell
python -m pytest -q tests/factory/test_v11_composition.py tests/factory/test_assets.py tests/factory/test_publish_gate.py tests/factory/test_plan_factory.py tests/factory/test_handoff.py tests/factory/test_content_availability.py tests/factory/test_stage.py tests/test_oauth.py tests/factory/test_housekeeping.py tests/factory/test_silhouette.py tests/factory/test_force_rerender.py tests/test_config.py tests/factory/test_skipped_render_flag.py
```

Batch 2: 242 tests — 106.58 s
```powershell
python -m pytest -q tests/factory/test_interaction.py tests/factory/test_reliability.py tests/factory/test_gaze.py tests/factory/test_props.py tests/factory/test_security.py tests/factory/test_v11_policy.py tests/factory/test_observability.py tests/factory/test_transitions.py tests/factory/test_longform_cards.py tests/test_credentials.py tests/factory/test_read_side_formats.py tests/test_upload_geometry.py tests/test_youtube.py tests/test_logging.py
```

Batch 3: 241 tests — 14.34 s
```powershell
python -m pytest -q tests/factory/test_v11_audit_followup.py tests/factory/test_publishing_policy.py tests/factory/test_ik_pickup.py tests/factory/test_audit_corrections.py tests/factory/test_creative_qc.py tests/factory/test_set_dressing.py tests/factory/test_camera.py tests/factory/test_controls.py tests/test_router.py tests/factory/test_lipsync.py tests/test_metadata.py tests/factory/test_grounding.py tests/test_check_oauth_identity.py
```

Batch 4: 241 tests — 454.34 s
```powershell
python -m pytest -q tests/factory/test_framing.py tests/factory/test_continuity.py tests/factory/test_performance.py tests/factory/test_shot_plan.py tests/factory/test_longform_planning.py tests/factory/test_scene_plan.py tests/factory/test_english_motion.py tests/factory/test_landscape_stage.py tests/factory/test_publish_gates.py tests/factory/test_v11_ladder.py tests/factory/test_v11_paths.py tests/factory/test_interrupted_render_recovery.py tests/factory/test_peak_guard.py
```

Batch 5: 242 tests — 222.64 s
```powershell
python -m pytest -q tests/factory/test_v11_figures.py tests/factory/test_production_workflow_shape.py tests/factory/test_visemes.py tests/factory/test_locomotion.py tests/factory/test_pickup_integration.py tests/factory/test_longform_schema.py tests/factory/test_cloud_gate_repairs.py tests/factory/test_landscape.py tests/factory/test_v11_provenance.py tests/factory/test_research_focus.py tests/factory/test_qc.py tests/factory/test_audio.py tests/factory/test_pose_goldens.py tests/factory/test_dependencies.py
```

Batch 6: 242 tests — 23.27 s
```powershell
python -m pytest -q tests/factory/test_academic_visuals.py tests/factory/test_orchestration.py tests/factory/test_character_schema.py tests/factory/test_research.py tests/factory/test_loudness.py tests/factory/test_audit_corrections_medium.py tests/factory/test_inline_cuts.py tests/factory/test_v11_diversity.py tests/factory/test_lighting.py tests/test_identity.py tests/factory/test_plan_lookup_errors.py tests/factory/test_package_integration.py tests/test_ledger.py tests/factory/test_delivered_audio.py
```

The content-bank regression checks also passed after the Nexus edit: `python -m pytest tests/factory/test_plan_factory.py tests/factory/test_content_availability.py -q` — 36 passed in 4.49 seconds. The reliability tests passed after the Windows lock fix: `python -m pytest tests/factory/test_reliability.py -q` — 38 passed in 2.06 seconds. The publishing-policy file passed after both deterministic-clock fixes: `python -m pytest tests/factory/test_publishing_policy.py -q` — 36 passed in 3.01 seconds.

## E. Defects discovered

1. A publishing-policy test depended on the current time and became invalid after its hard-coded release passed. Production correctly rejected the late release.
2. `JobLock.is_stale()` used POSIX `os.kill(pid, 0)` on Windows; Python maps signal 0 to a console Ctrl+C event, interrupting the process during lock checks.
3. A second publishing test encoded “five minutes ago” as a time-only string and failed around the IST date boundary because that string means the next occurrence on the current local day.
4. `nexus-eval-problem` asserted that task-specific evaluation was “the only number” that predicts results and used a broad arXiv search page as a source.
5. Several older repository pages described pre-merge or pre-hosted-render states, or presented outdated activation steps without a clear historical label.
6. The content bank supports only one authored horizontal plan per channel; Natkhat's horizontal sample is 64.5 seconds and does not substantiate a daily long-form cadence.
7. A manual `plan_id` could be interpreted as shell syntax in the credential-bearing upload workflow. The issue was found by source review and fixed on the current branch; branch CI has not run yet.

## F. Defects fixed

- Made the release-lookup regression deterministic by pinning only the resolver clock in that test; production time handling and assertions remain intact.
- Replaced the Windows lock PID probe with `OpenProcess`/`WaitForSingleObject`; only a confirmed missing or exited process is stale, while access or API uncertainty keeps the lock live. The existing lock-liveness tests now pass on Windows.
- Made the five-minute-late publishing test use a fixed `20:05 IST` resolver time, so the test does not confuse a prior-day `23:56` time string with a late release.
- Qualified the Nexus evaluation claims, softened causal language, and replaced the broad search URL with the direct study [NLP Evaluation in Trouble](https://arxiv.org/abs/2310.18018), retaining the Stanford [HELM](https://crfm.stanford.edu/helm/) reference.
- Updated the operations, limitations, and activation documents with the actual six-item Natkhat bank state (three remaining Haveli episodes and three Jungle episodes).
- Marked older readiness and activation pages as historical or superseded, and aligned the README with the hosted artifacts and dated private-upload evidence.
- Corrected stale cron and global pause examples in the current operational documentation.
- Fixed the workflow-dispatch injection by slugifying the explicit plan ID before output, removing its raw `GITHUB_OUTPUT` serialization, and passing resolved plan IDs and other step values through `env` rather than embedding GitHub expressions in shell source. Improved `tools.workflow_audit` to inspect multiline `run:` blocks and added three regression tests.

## G. Remaining defects and limitations

- The candidate fixes are not on `main` until the owner reviews and merges the PR.
- No live `publishAt` schedule was created or read back during this audit. Schedule behavior is supported by code and mocked tests, not a production YouTube observation.
- Prior reports record an Academic thumbnail 403 and insufficient OAuth permission for `videos.update`; captions were not attached. The current OAuth grant was not inspected, and no credential values were read.
- The local read-only pause check returned `paused: false`, scope `none`; the production runner's pause state, duplicate state, and pending YouTube releases were not checked through an authorized runtime.
- Each channel has one authored horizontal plan. Natkhat's inspected horizontal sample lasts 64.5 seconds. More source material is needed for sustained horizontal releases.
- The visuals were sampled at five points per file. This is not exhaustive frame-by-frame review, black/frozen-frame analysis, or a full child-safety review. Encoded audio was measured but not independently judged by a full listening pass.

## H. Visual quality audit

Artifacts were downloaded locally from Actions runs, probed with FFprobe 8.0.1, decoded through FFmpeg, and reviewed as five-frame contact sheets per file. All six representative files used H.264/AAC, 30 fps, the intended geometry, and decoded without reported errors.

| Channel | Format / artifact | Run | Duration | Geometry | Sampled visual result |
| --- | --- | ---: | ---: | --- | --- |
| Nexus Node | Short `nexus-data-wall` | `45196341328` | 41.967 s | 1080×1920 | Distinct technical plates; title and captions stayed within the frame |
| Nexus Node | Horizontal `long-nexus-power-grid` | `45625058307` | 214.067 s | 1920×1080 | Clear card hierarchy and varied diagrams |
| Academic Biohacker | Short `academic-post-meal-walk` | `45196366254` | 38.367 s | 1080×1920 | Relevant paper/chart visuals; caption wrapping merits handset-scale review |
| Academic Biohacker | Horizontal `long-academic-study-protocol` | `45196440363` | 218.933 s | 1920×1080 | Clear cards and diagrams; some dense card text is small at preview size |
| Natkhat Toons | Short `natkhat-haveli-e1` | `45196207861` | 32.100 s | 1080×1920 | Hindi captions and character identity visible; dark setting has readable contrast in sampled frames |
| Natkhat Toons | Horizontal `natkhat-haveli-stage-e1` | `45196390881` | 64.500 s | 1920×1080 | Poses and dialogue vary; repeated background limits scene variety |

Visual result: **PASS WITH LIMITATIONS**. Sampled frames and successful decode do not prove every frame is free of black or frozen segments.

## I. Audio quality audit

FFmpeg EBU R128 measurements were made on the encoded AAC outputs, not source WAVs. Loudness was −14.1 to −14.3 LUFS; true peaks were −1.4 to −2.5 dBTP, below the project's −1 dBTP ceiling. Natkhat has the least headroom. Decode succeeded for all six files. Full subjective listening was not performed.

Result: **PASS WITH LIMITATIONS**.

## J. Subtitle quality audit

SRT cues were present and the final cue ended before the corresponding file ended. Cue counts: Nexus Short 18 / horizontal 97; Academic Short 17 / horizontal 94; Natkhat Short 10 / horizontal 21. Hindi samples use Devanagari. Captions were visible in sampled frames. Cue overlap, every line break, and external YouTube caption attachment were not exhaustively verified.

Result: **PASS WITH LIMITATIONS**. Local SRT and burned-in captions do not establish that a YouTube caption track was attached.

## K. Content quality audit

- Nexus evaluation copy was corrected on this branch and now points to a direct contamination study plus HELM.
- The Academic health sample used qualifying phrasing, but one source was a PubMed search page and the other a general WHO activity page. Other topic-bank sources also include broad search or institution pages; claims still need plan-level editorial review.
- The sampled Natkhat story was in Hindi and child-appropriate in the inspected frames and script. This does not certify the full channel or all future content.

Result: **PASS WITH LIMITATIONS**.

## L. Channel readiness matrix

| Channel | Config / plan state | Short artifact | Horizontal artifact | Readiness |
| --- | --- | --- | --- | --- |
| Nexus Node | Scheduled policy configured; four unused topic entries; one horizontal plan | Inspected | Inspected | Ready for owner review, subject to content review and account preflight |
| Academic Biohacker | Scheduled policy configured; four unused topic entries; one horizontal plan | Inspected | Inspected | Ready for owner review, subject to scientific source review and account preflight |
| Natkhat Toons | Scheduled policy configured; made-for-kids forced true; six authored Shorts remain across two series; one horizontal plan | Inspected | Inspected; 64.5 seconds | Ready for owner review, with limited horizontal duration and variety |

All six channel/format plan-availability checks returned available at the time of the read-only query. This is not a reservation for a future scheduled run.

## M. Publishing and scheduling audit

The three publishing workflows were checked with `gh workflow list --all` and were `disabled_manually`: `nexus-node daily`, `academic-biohacker daily`, and `natkhat-toons daily`. No workflow was enabled or dispatched. No video was uploaded and no release was scheduled by this task.

Current configured UTC crons and IST starts/releases:

| Channel | Cron UTC | Start IST | Release IST |
| --- | --- | --- | --- |
| Nexus Node | `30 12 * * *` | 18:00 | 20:00 |
| Academic Biohacker | `30 4 * * *` | 10:00 | 12:00 |
| Natkhat Toons | `30 10 * * *` | 16:00 | 18:00 |

Policy, late-window handling, per-plan lookup, mocked schedule read-back, pause behavior, and duplicate guards have automated coverage. No real scheduled-release read-back was performed. Prior private pilot uploads are documented in `X100_PRIVATE_UPLOAD_CHECKLIST.md`; their current YouTube state was not checked in this audit.

## N. Performance and capacity audit

An 11-beat horizontal hosted render was measured at 3,008 seconds (about 50 minutes); the workflow uses a 120-minute timeout. Shorts are configured with a 60-minute timeout and prior hosted samples complete in minutes. Short and horizontal jobs run independently. These measurements show margin for the observed run, not daily reliability across changing runners or a sustainable content cadence. The one-horizontal-plan-per-channel bank is the cadence limit.

## O. Security findings

- The completed Standard security review (scan `809f271b-0654-454a-9ea3-c7579717dada`) reported one high-confidence CWE-78: a manual `plan_id` could reach Bash source in the upload step after channel OAuth credentials were exported. The scan snapshot predates the fix; the current branch normalizes the value and avoids direct expression interpolation in shell.
- After the fix, `python -m tools.workflow_audit` reported **7 workflows, 0 findings**; `tests/factory/test_workflow_audit.py` passed **3/3**; the local tree secret scan reported **0 findings**; `produce.yml` parsed as YAML. The base commit security workflow `45655992820` passed, but its older multiline audit did not catch this issue. The final PR security run `45683044836` passed all four jobs, including the enhanced workflow audit.
- Production workflows grant `contents: read` and pass channel-specific YouTube credentials to that channel's reusable jobs. CI uses read-only GitHub permissions.
- No OAuth values were read, printed, copied, changed, or rotated. No repository secrets were modified.
- Codex Security Daybreak access was not granted, the dependency audit was not rerun locally, and no independent reviewer was assigned. This is repository/workflow evidence, not an account-level OAuth grant audit.

Result: **FINDING FIXED ON BRANCH — CI GREEN; OWNER REVIEW PENDING**.

## P. Documentation completed

Created or refreshed `X100_FINAL_SYSTEM_ARCHITECTURE.md`, `X100_FINAL_QUALITY_AUDIT.md`, `X100_PRODUCTION_OPERATIONS_GUIDE.md`, `X100_FINAL_ACTIVATION_HANDOVER.md`, `X100_KNOWN_LIMITATIONS.md`, and this report. Older deployment and activation pages now identify themselves as historical or superseded. Artifact reports remain as evidence for their named runs.

## Q. Remaining account-owner actions

1. Review the focused PR and wait for all required branch checks to pass; merge only through the normal owner-reviewed process.
2. In an authorized runtime, verify the global pause state, pending schedules, duplicate state, and current plan availability without exposing secrets.
3. Resolve or explicitly accept YouTube account limitations for thumbnails, caption attachment, schedule changes, and schedule read-back. Confirm the minimum required OAuth scopes with the account owner.
4. Keep all workflows disabled until the code is merged, account preflight is clear, and explicit owner approval is given.
5. If approved, enable Nexus alone and inspect its first scheduled run and YouTube metadata before considering another channel.

## R. Final quality scorecard

| Area | Status | Evidence and limit |
| --- | --- | --- |
| Architecture | PASS | Static review, plan/config inspection, artifacts, and passing suite; no formal independent architecture review |
| Python quality | PASS | Deterministic regression fix and final suite result recorded above |
| Security | FIXED ON BRANCH; CI GREEN | One high CWE-78 in the pre-fix snapshot; current PR security workflow and local auditor regression tests pass |
| Visual quality | PASS WITH LIMITATIONS | Six decoded artifacts and five sampled frames each; not frame-exhaustive |
| Audio quality | PASS WITH LIMITATIONS | Encoded-output loudness/peak and decode measurements; no full listening pass |
| Subtitle quality | PASS WITH LIMITATIONS | SRT timing bounds and sampled-frame visibility; no YouTube track verification |
| Content quality | PASS WITH LIMITATIONS | Nexus claim corrected; representative scripts reviewed; source traceability varies |
| Pipeline reliability | PASS WITH LIMITATIONS | Hosted render artifacts and automated gates; no newly dispatched production run |
| Recovery | PASS | Existing interrupted-render/resume tests passed; no new production interruption drill |
| Idempotency | PASS | Existing duplicate-prevention and state tests passed; no live duplicate attempt |
| Publishing | PASS WITH LIMITATIONS | Gate and auth paths covered by mocks/tests; current account state not checked |
| Scheduling | PASS WITH LIMITATIONS | Resolver and mocked read-back tests; no live YouTube schedule observation |
| Performance | PASS WITH LIMITATIONS | One measured 3,008-second hosted horizontal render; no long-run reliability sample |
| Documentation | PASS | Current architecture, quality, operations, activation, limitations, and closure docs align |

## S. Exact activation procedure

After owner review and merge, require green checks on `main`, a fresh authorized preflight, confirmed content availability, and a clear account state. Keep Academic and Natkhat disabled until separately approved. To enable Nexus only after those conditions and explicit owner approval:

```powershell
gh workflow enable "nexus-node daily" --repo Ayushjaiswal0001/youtube
```

Do not manually dispatch the publishing workflow as a substitute for the scheduled first run. Verify the first run's plan, QC, gate, private upload, and exact YouTube `publishAt` read-back. If any item differs, disable the workflow and keep the video private while investigating. Disabling the workflow does not cancel a running job or an already-created YouTube schedule.

## T. Final verdict

**RELEASE CANDIDATE WITH DOCUMENTED LIMITATIONS** — PR #22 is open with all CI and security checks green; owner review and merge remain pending. The three daily channel workflows remain disabled. Publishing is not activated; a separate account preflight and explicit activation approval described above are still required.
